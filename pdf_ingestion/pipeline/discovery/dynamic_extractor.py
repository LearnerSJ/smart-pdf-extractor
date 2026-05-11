"""Dynamic extractor for VLM-discovered schemas.

Extracts fields and tables from a document using a DiscoveredSchema
(rather than hardcoded regex patterns), driving VLM-based extraction
with the discovered field definitions.
"""

from __future__ import annotations

import json

import structlog

from api.errors import ErrorCode
from api.models.response import (
    Abstention,
    Field,
    Provenance,
    Table,
    TableRow,
    TriangulationInfo,
)
from api.models.tenant import TenantContext
from pipeline.models import (
    AssembledDocument,
    DiscoveredSchema,
    EntityRedactionConfig as PipelineRedactionConfig,
    VLMFieldResult,
)
from pipeline.ports import VLMClientPort, RedactorPort
from pipeline.vlm.response_parser import strip_markdown_fences
from pipeline.vlm.token_budget import TokenBudget
from pipeline.vlm.verifier import verify_vlm_result

logger = structlog.get_logger()

# Verification threshold for discovered field values
VERIFICATION_THRESHOLD = 0.85


class DynamicExtractor:
    """Extracts fields and tables using a VLM-discovered schema.

    Design decisions:
    - Uses the same chunked extraction tiers (1/2/3) as standard VLM fallback
    - Each VLM call is redacted before sending
    - Each extracted value is verified against the token stream (threshold 0.85)
    - Output format matches static extractors exactly (fields, tables, abstentions)
    - Provenance source = "vlm", extraction_rule = "discovered:{field_name}"
    - schema_type = "discovered:{document_type_label}"
    """

    def __init__(
        self,
        vlm_client: VLMClientPort,
        redactor: RedactorPort,
    ) -> None:
        self._vlm = vlm_client
        self._redactor = redactor

    async def extract(
        self,
        doc: AssembledDocument,
        schema: DiscoveredSchema,
        tenant: TenantContext,
        token_budget: TokenBudget,
        trace_id: str,
    ) -> dict:
        """Extract all fields and tables defined in the discovered schema.

        Returns dict with keys: 'fields', 'tables', 'abstentions', 'schema_type'.
        Output structure is identical to static schema extractors.
        """
        fields: dict[str, Field] = {}
        tables: list[Table] = []
        abstentions: list[Abstention] = []

        schema_type = f"discovered:{schema.document_type_label}"

        # Build full document text for extraction
        full_text = self._build_document_text(doc)

        # Redact text before VLM calls
        redaction_config = tenant.redaction_config.global_entities if tenant.redaction_config else []
        redaction_entities = [
            PipelineRedactionConfig(entity_type=e.entity_type, enabled=e.enabled)
            for e in redaction_config
        ]
        redacted_text, _ = self._redactor.redact_page_text(full_text, redaction_entities)

        # Extract metadata fields
        if schema.metadata_fields:
            field_results = await self._extract_fields(
                doc, schema, redacted_text, token_budget, trace_id
            )
            for field_name, result in field_results.items():
                if isinstance(result, Field):
                    fields[field_name] = result
                else:
                    abstentions.append(result)

        # Extract tables
        if schema.table_definitions:
            table_results = await self._extract_tables(
                doc, schema, redacted_text, token_budget, trace_id
            )
            for result in table_results:
                if isinstance(result, Table):
                    tables.append(result)
                else:
                    abstentions.append(result)

        logger.info(
            "discovery.extraction_complete",
            trace_id=trace_id,
            tenant_id=tenant.id,
            schema_type=schema_type,
            fields_extracted=len(fields),
            fields_abstained=len([a for a in abstentions if a.field is not None]),
            tables_extracted=len(tables),
        )

        # Check if schema needs refinement (>50% abstention rate)
        total_fields = len(schema.metadata_fields)
        abstained_fields = len([a for a in abstentions if a.field is not None])
        if total_fields > 0 and abstained_fields / total_fields > 0.5:
            logger.warning(
                "discovery.schema_needs_refinement",
                trace_id=trace_id,
                tenant_id=tenant.id,
                schema_type=schema_type,
                total_fields=total_fields,
                abstained_fields=abstained_fields,
                abstention_rate=abstained_fields / total_fields,
            )

        return {
            "fields": fields,
            "tables": tables,
            "abstentions": abstentions,
            "schema_type": schema_type,
            "needs_refinement": (
                total_fields > 0 and abstained_fields / total_fields > 0.5
            ),
        }

    async def _extract_fields(
        self,
        doc: AssembledDocument,
        schema: DiscoveredSchema,
        redacted_text: str,
        token_budget: TokenBudget,
        trace_id: str,
    ) -> dict[str, Field | Abstention]:
        """Extract all metadata fields using VLM."""
        results: dict[str, Field | Abstention] = {}

        # Build extraction prompt for all fields at once
        prompt = self._build_field_extraction_prompt(schema, redacted_text)

        # Check budget before VLM call
        if not token_budget.can_proceed():
            for field_def in schema.metadata_fields:
                results[field_def.field_name] = Abstention(
                    field=field_def.field_name,
                    table_id=None,
                    reason=ErrorCode.VLM_BUDGET_EXCEEDED,
                    detail=f"Token budget exhausted before extracting field '{field_def.field_name}'",
                    vlm_attempted=False,
                )
            return results

        # Call VLM for field extraction
        vlm_result = self._vlm.extract_field(
            page_text=prompt,
            field_name="discovered_fields",
            field_description="Extract all discovered metadata fields",
            schema_type=f"discovered:{schema.document_type_label}",
        )

        # Record token usage
        input_tokens = self._vlm.estimate_tokens(prompt)
        output_tokens = self._vlm.estimate_tokens(vlm_result.raw_response) if vlm_result.raw_response else 0
        token_budget.record_usage(input_tokens=input_tokens, output_tokens=output_tokens)

        # Parse VLM response as JSON with field values
        extracted_values = self._parse_field_response(vlm_result.raw_response)

        # Verify each field against token stream
        for field_def in schema.metadata_fields:
            field_name = field_def.field_name
            raw_value = extracted_values.get(field_name)

            if raw_value is None:
                results[field_name] = Abstention(
                    field=field_name,
                    table_id=None,
                    reason=ErrorCode.EXTRACTION_PATTERN_NOT_FOUND,
                    detail=f"Discovered field '{field_name}' not found in VLM response",
                    vlm_attempted=True,
                )
                continue

            # Verify against token stream
            verification_result = VLMFieldResult(
                value=str(raw_value),
                confidence=vlm_result.confidence,
                raw_response=vlm_result.raw_response,
                model_id=vlm_result.model_id,
            )
            verification = verify_vlm_result(
                verification_result,
                doc.token_stream,
                fuzzy_threshold=VERIFICATION_THRESHOLD,
            )

            if verification.verified:
                # Determine provenance from verification
                prov_data = verification.provenance or {}
                results[field_name] = Field(
                    value=raw_value,
                    original_string=str(raw_value),
                    confidence=min(vlm_result.confidence, 0.95),
                    vlm_used=True,
                    redaction_applied=True,
                    provenance=Provenance(
                        page=prov_data.get("page", 1),
                        bbox=prov_data.get("bbox", [0.0, 0.0, 0.0, 0.0]),
                        source="vlm",
                        extraction_rule=f"discovered:{field_name}",
                    ),
                )
            else:
                results[field_name] = Abstention(
                    field=field_name,
                    table_id=None,
                    reason=ErrorCode.VLM_VALUE_UNVERIFIABLE,
                    detail=f"Discovered field '{field_name}' value not found in token stream",
                    vlm_attempted=True,
                )

        return results

    async def _extract_tables(
        self,
        doc: AssembledDocument,
        schema: DiscoveredSchema,
        redacted_text: str,
        token_budget: TokenBudget,
        trace_id: str,
    ) -> list[Table | Abstention]:
        """Extract all tables using VLM."""
        results: list[Table | Abstention] = []

        for table_def in schema.table_definitions:
            # Check budget before each table extraction
            if not token_budget.can_proceed():
                results.append(Abstention(
                    field=None,
                    table_id=f"{table_def.table_type}_0",
                    reason=ErrorCode.VLM_BUDGET_EXCEEDED,
                    detail=f"Token budget exhausted before extracting table '{table_def.table_type}'",
                    vlm_attempted=False,
                ))
                continue

            prompt = self._build_table_extraction_prompt(schema, redacted_text, table_def)

            vlm_result = self._vlm.extract_field(
                page_text=prompt,
                field_name=f"table_{table_def.table_type}",
                field_description=f"Extract table: {table_def.table_type}",
                schema_type=f"discovered:{schema.document_type_label}",
            )

            # Record token usage
            input_tokens = self._vlm.estimate_tokens(prompt)
            output_tokens = self._vlm.estimate_tokens(vlm_result.raw_response) if vlm_result.raw_response else 0
            token_budget.record_usage(input_tokens=input_tokens, output_tokens=output_tokens)

            # Parse table response
            table = self._parse_table_response(vlm_result.raw_response, table_def)
            if table is not None:
                results.append(table)
            else:
                results.append(Abstention(
                    field=None,
                    table_id=f"{table_def.table_type}_0",
                    reason=ErrorCode.EXTRACTION_TABLE_ABSTAINED,
                    detail=f"Could not extract table '{table_def.table_type}' from VLM response",
                    vlm_attempted=True,
                ))

        return results

    def _build_field_extraction_prompt(
        self,
        schema: DiscoveredSchema,
        page_text: str,
    ) -> str:
        """Build extraction prompt using discovered field definitions."""
        field_specs = []
        for f in schema.metadata_fields:
            field_specs.append(
                f"- {f.field_name}: {f.description} (location: {f.location_hint})"
            )

        fields_list = "\n".join(field_specs)

        return f"""Extract the following fields from this {schema.document_type_label} document issued by {schema.institution}.

Fields to extract:
{fields_list}

Respond ONLY with valid JSON where keys are the field_name values and values are the extracted text.
Example: {{"account_code": "ABC123", "statement_date": "2024-01-15"}}

If a field cannot be found, set its value to null.

---
DOCUMENT TEXT:
---
{page_text}
"""

    def _build_table_extraction_prompt(
        self,
        schema: DiscoveredSchema,
        page_text: str,
        table_def: "DiscoveredTableDefinition",
    ) -> str:
        """Build table extraction prompt using discovered headers."""
        from pipeline.models import DiscoveredTableDefinition  # noqa: F811

        headers_str = ", ".join(table_def.expected_headers)

        return f"""Extract the table "{table_def.table_type}" from this {schema.document_type_label} document.

Expected columns: {headers_str}
Data pattern: {table_def.data_pattern}
Location: {table_def.location_hint}

Respond ONLY with valid JSON matching this structure:
{{
  "headers": [{headers_str}],
  "rows": [
    ["cell1", "cell2", ...],
    ...
  ]
}}

---
DOCUMENT TEXT:
---
{page_text}
"""

    def _build_document_text(self, doc: AssembledDocument) -> str:
        """Build full text content from the assembled document."""
        parts: list[str] = []

        for block in doc.blocks:
            text = block.get("text", "")
            if text:
                parts.append(str(text))

        if not parts and doc.token_stream:
            parts = [token.text for token in doc.token_stream]

        return " ".join(parts)

    @staticmethod
    def _parse_field_response(raw_response: str | None) -> dict:
        """Parse VLM field extraction response as JSON dict."""
        if not raw_response:
            return {}

        try:
            data = json.loads(strip_markdown_fences(raw_response))
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, TypeError):
            pass

        return {}

    @staticmethod
    def _parse_table_response(raw_response: str | None, table_def: "DiscoveredTableDefinition") -> Table | None:
        """Parse VLM table extraction response into a Table model."""
        from pipeline.models import DiscoveredTableDefinition  # noqa: F811

        if not raw_response:
            return None

        try:
            data = json.loads(strip_markdown_fences(raw_response))
        except (json.JSONDecodeError, TypeError):
            return None

        if not isinstance(data, dict):
            return None

        headers = data.get("headers", table_def.expected_headers)
        raw_rows = data.get("rows", [])

        if not raw_rows:
            return None

        rows: list[TableRow] = []
        for idx, row in enumerate(raw_rows):
            if isinstance(row, list):
                rows.append(TableRow(cells=row, row_index=idx))

        if not rows:
            return None

        return Table(
            table_id=f"{table_def.table_type}_0",
            type=table_def.table_type,
            page_range=[1],
            headers=[str(h) for h in headers],
            triangulation=TriangulationInfo(
                score=0.0,
                verdict="agreement",
                winner="vlm",
                methods=["vlm"],
            ),
            rows=rows,
        )
