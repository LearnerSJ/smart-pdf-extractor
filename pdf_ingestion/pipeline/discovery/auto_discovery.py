"""Auto-schema discovery via VLM analysis.

Analyses a sample of an unknown document via VLM to discover its structure
and produce a reusable schema definition. The discovered schema is cached
for future reuse and handed off to DynamicExtractor for full extraction.
"""

from __future__ import annotations

import json

import structlog

from api.errors import ErrorCode
from api.models.response import Abstention
from api.models.tenant import TenantContext
from pipeline.discovery.schema_cache import SchemaCache
from pipeline.models import (
    AssembledDocument,
    DiscoveredFieldDefinition,
    DiscoveredSchema,
    DiscoveredTableDefinition,
    DiscoverySample,
    SchemaFingerprint,
)
from pipeline.ports import VLMClientPort, RedactorPort
from pipeline.vlm.response_parser import strip_markdown_fences
from pipeline.vlm.token_budget import TokenBudget

logger = structlog.get_logger()

DEFAULT_SAMPLE_PAGES = 5
DEFAULT_MAX_CONTEXT_RATIO = 0.80

SCHEMA_ANALYSIS_PROMPT = '''You are analysing a financial document to identify its structure.
Examine the provided pages and identify:

1. **document_type_label**: A concise human-readable label for this document type
   (e.g., "futures_trade_confirmation", "derivatives_daily_statement", "margin_call_notice")

2. **institution**: The issuing institution name (e.g., "Société Générale", "JP Morgan")

3. **metadata_fields**: Header/summary fields that appear once or on every page.
   For each field provide:
   - field_name: snake_case identifier (e.g., "account_code", "statement_date")
   - description: what the field contains
   - location_hint: where it typically appears ("header", "footer", "first_page", "last_page")

4. **table_definitions**: Tabular data structures in the document.
   For each table provide:
   - table_type: descriptive name (e.g., "trades", "positions", "balance_summary")
   - expected_headers: list of column header strings as they appear in the document
   - data_pattern: brief description of what each row represents
   - location_hint: where the table appears ("body_repeating", "last_page", "first_page")

Respond ONLY with valid JSON matching this schema:
{{
  "document_type_label": "string",
  "institution": "string",
  "metadata_fields": [
    {{
      "field_name": "string",
      "description": "string",
      "location_hint": "header|footer|first_page|last_page"
    }}
  ],
  "table_definitions": [
    {{
      "table_type": "string",
      "expected_headers": ["string"],
      "data_pattern": "string",
      "location_hint": "body_repeating|last_page|first_page"
    }}
  ]
}}

---
DOCUMENT SAMPLE (pages 1-{sample_page_count}):
---
{redacted_sample_text}
'''


class AutoSchemaDiscovery:
    """Discovers document schema via VLM analysis of a page sample.

    Design decisions:
    - Sample defaults to first 5 pages (covers headers + first data rows)
    - Sample is adaptively reduced if it exceeds 80% of context window
    - Redaction applied before VLM call (same as standard VLM fallback)
    - Discovery VLM calls count toward the job's token budget
    - Circuit breaker respected (immediate abstention if open)
    """

    def __init__(
        self,
        vlm_client: VLMClientPort,
        redactor: RedactorPort,
        schema_cache: SchemaCache,
    ) -> None:
        self._vlm = vlm_client
        self._redactor = redactor
        self._cache = schema_cache

    async def discover(
        self,
        doc: AssembledDocument,
        tenant: TenantContext,
        token_budget: TokenBudget,
        trace_id: str,
    ) -> DiscoveredSchema | Abstention:
        """Attempt to discover the document's schema.

        Steps:
        1. Check circuit breaker — abstain if open
        2. Check token budget — abstain if exhausted
        3. Check schema cache for existing match
        4. If cache miss: select sample pages, redact, send to VLM
        5. Parse VLM response into DiscoveredSchema
        6. Store in cache for future reuse

        Returns DiscoveredSchema on success, Abstention on failure.
        """
        logger.info(
            "discovery.triggered",
            trace_id=trace_id,
            tenant_id=tenant.id,
        )

        # Step 1: Check circuit breaker
        if hasattr(self._vlm, "circuit_breaker_open") and self._vlm.circuit_breaker_open():
            logger.warning("discovery.circuit_breaker_open", tenant_id=tenant.id)
            return Abstention(
                field=None,
                table_id=None,
                reason=ErrorCode.VLM_BEDROCK_THROTTLED,
                detail="Circuit breaker open — cannot attempt schema discovery",
                vlm_attempted=False,
            )

        # Step 2: Check token budget
        if not token_budget.can_proceed():
            logger.warning("discovery.budget_exhausted", tenant_id=tenant.id)
            return Abstention(
                field=None,
                table_id=None,
                reason=ErrorCode.VLM_BUDGET_EXCEEDED,
                detail="Token budget exhausted before schema discovery",
                vlm_attempted=False,
            )

        # Step 3: Select sample and estimate tokens
        sample = self._select_sample(doc, max_pages=DEFAULT_SAMPLE_PAGES)

        # Step 4: Redact sample text
        redaction_config = tenant.redaction_config.global_entities if tenant.redaction_config else []
        # Convert Pydantic models to pipeline dataclass format for the port
        from pipeline.models import EntityRedactionConfig as PipelineRedactionConfig
        redaction_entities = [
            PipelineRedactionConfig(entity_type=e.entity_type, enabled=e.enabled)
            for e in redaction_config
        ]
        redacted_text, redaction_log = self._redactor.redact_page_text(
            sample.combined_text,
            redaction_entities,
        )

        logger.info(
            "discovery.redaction_applied",
            entities_redacted=redaction_log.redacted_count,
            trace_id=trace_id,
        )

        # Step 5: Build prompt and call VLM
        prompt = self._build_analysis_prompt(redacted_text, sample.page_count)

        vlm_result = self._vlm.extract_field(
            page_text=prompt,
            field_name="schema_analysis",
            field_description="Discover document schema structure",
            schema_type="discovery",
        )

        # Record token usage
        input_tokens = self._vlm.estimate_tokens(prompt)
        output_tokens = self._vlm.estimate_tokens(vlm_result.raw_response) if vlm_result.raw_response else 0
        token_budget.record_usage(input_tokens=input_tokens, output_tokens=output_tokens)

        # Step 6: Parse response
        schema = self._parse_schema_response(vlm_result.raw_response if vlm_result.value is None else vlm_result.value)

        if schema is None:
            logger.warning(
                "discovery.failed",
                trace_id=trace_id,
                tenant_id=tenant.id,
                error_code=ErrorCode.DISCOVERY_SCHEMA_ANALYSIS_FAILED,
                detail="VLM returned null or unparseable response",
            )
            return Abstention(
                field=None,
                table_id=None,
                reason=ErrorCode.DISCOVERY_SCHEMA_ANALYSIS_FAILED,
                detail="VLM schema analysis returned null or unparseable response",
                vlm_attempted=True,
            )

        # Step 7: Store in cache
        await self._cache.store(schema, schema.fingerprint, tenant.id)

        logger.info(
            "discovery.schema_analysed",
            trace_id=trace_id,
            document_type_label=schema.document_type_label,
            institution=schema.institution,
            fields_count=len(schema.metadata_fields),
            tables_count=len(schema.table_definitions),
        )

        return schema

    def _select_sample(
        self,
        doc: AssembledDocument,
        max_pages: int = DEFAULT_SAMPLE_PAGES,
    ) -> DiscoverySample:
        """Select pages for the discovery sample.

        Default: first N pages. Adaptively reduced if token estimate
        exceeds 80% of context window.
        """
        # Build page texts from document blocks grouped by page
        page_texts_map: dict[int, list[str]] = {}

        for block in doc.blocks:
            prov = block.get("provenance", {})
            page_num = prov.get("page", 1) if isinstance(prov, dict) else 1
            if page_num not in page_texts_map:
                page_texts_map[page_num] = []
            text = block.get("text", "")
            if text:
                page_texts_map[page_num].append(str(text))

        # If no blocks, try token stream
        if not page_texts_map and doc.token_stream:
            page_texts_map[1] = [t.text for t in doc.token_stream]

        # Sort pages and take first max_pages
        sorted_pages = sorted(page_texts_map.keys())
        selected_pages = sorted_pages[:max_pages]

        page_texts = [" ".join(page_texts_map[p]) for p in selected_pages]
        page_numbers = list(selected_pages)

        # Estimate tokens for the combined sample
        combined = "\n\n".join(page_texts)
        estimated_tokens = self._vlm.estimate_tokens(combined)

        # Adaptive reduction: if exceeds 80% of context window, reduce pages
        max_context = self._vlm.max_context_tokens()
        max_allowed = int(max_context * DEFAULT_MAX_CONTEXT_RATIO)

        original_page_count = len(page_texts)
        while estimated_tokens > max_allowed and len(page_texts) > 1:
            page_texts = page_texts[:-1]
            page_numbers = page_numbers[:-1]
            combined = "\n\n".join(page_texts)
            estimated_tokens = self._vlm.estimate_tokens(combined)

        if len(page_texts) < original_page_count:
            logger.info(
                "discovery.sample_reduced",
                original_pages=original_page_count,
                reduced_pages=len(page_texts),
                estimated_tokens=estimated_tokens,
            )

        return DiscoverySample(
            page_texts=page_texts,
            page_numbers=page_numbers,
            estimated_tokens=estimated_tokens,
        )

    def _build_analysis_prompt(self, sample_text: str, sample_page_count: int = 5) -> str:
        """Build the VLM prompt for schema analysis."""
        return SCHEMA_ANALYSIS_PROMPT.format(
            sample_page_count=sample_page_count,
            redacted_sample_text=sample_text,
        )

    def _parse_schema_response(self, raw_response: str | None) -> DiscoveredSchema | None:
        """Parse VLM JSON response into a DiscoveredSchema.

        Returns None if response is null, empty, or malformed JSON.
        """
        if not raw_response:
            return None

        try:
            data = json.loads(strip_markdown_fences(raw_response))
        except (json.JSONDecodeError, TypeError):
            return None

        if not isinstance(data, dict):
            return None

        # Validate required fields
        document_type_label = data.get("document_type_label", "")
        institution = data.get("institution", "")

        if not document_type_label or not institution:
            return None

        # Parse metadata fields
        metadata_fields: list[DiscoveredFieldDefinition] = []
        for f in data.get("metadata_fields", []):
            if isinstance(f, dict) and f.get("field_name"):
                metadata_fields.append(
                    DiscoveredFieldDefinition(
                        field_name=f["field_name"],
                        description=f.get("description", ""),
                        location_hint=f.get("location_hint", ""),
                    )
                )

        # Parse table definitions
        table_definitions: list[DiscoveredTableDefinition] = []
        for t in data.get("table_definitions", []):
            if isinstance(t, dict) and t.get("table_type"):
                table_definitions.append(
                    DiscoveredTableDefinition(
                        table_type=t["table_type"],
                        expected_headers=t.get("expected_headers", []),
                        data_pattern=t.get("data_pattern", ""),
                        location_hint=t.get("location_hint", ""),
                    )
                )

        # Must have at least one field or table definition
        if not metadata_fields and not table_definitions:
            return None

        return DiscoveredSchema(
            document_type_label=document_type_label,
            institution=institution,
            metadata_fields=metadata_fields,
            table_definitions=table_definitions,
        )
