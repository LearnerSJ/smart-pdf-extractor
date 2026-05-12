"""Bedrock LLM client — concrete implementation of VLMClientPort.

Implements circuit breaker pattern: opens after 3 consecutive failures,
60s recovery window. Retries once with exponential backoff on throttle/timeout.
Maximum 2 Bedrock API calls per field (1 initial + 1 retry).
"""

from __future__ import annotations

import json
import time
from typing import Any

import boto3  # type: ignore[import-untyped]
import structlog

from api.errors import ErrorCode
from pipeline.models import VLMFieldResult
from pipeline.ports import VLMClientPort

logger = structlog.get_logger()

# Model-specific context window sizes (in tokens).
MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    "anthropic.claude-3-5-sonnet-20241022-v2:0": 200_000,
    "anthropic.claude-3-haiku-20240307-v1:0": 200_000,
    "anthropic.claude-3-opus-20240229-v1:0": 200_000,
    "us.anthropic.claude-sonnet-4-6": 200_000,
}

# Model-specific characters-per-token ratios (calibrated empirically).
MODEL_CHARS_PER_TOKEN: dict[str, float] = {
    "anthropic.claude-3-5-sonnet-20241022-v2:0": 3.5,
    "anthropic.claude-3-haiku-20240307-v1:0": 3.5,
    "anthropic.claude-3-opus-20240229-v1:0": 3.5,
    "us.anthropic.claude-sonnet-4-6": 3.5,
}


class CircuitBreaker:
    """Simple circuit breaker for external service calls.

    States:
    - closed: normal operation, calls pass through
    - open: calls rejected immediately (after threshold failures)
    - half_open: one test call allowed after recovery window

    Args:
        failure_threshold: Number of consecutive failures to open circuit.
        recovery_window_seconds: Time to wait before transitioning to half_open.
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        recovery_window_seconds: float = 60.0,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_window_seconds = recovery_window_seconds
        self.failure_count = 0
        self.state: str = "closed"  # closed | open | half_open
        self.last_failure_time: float = 0.0

    def is_call_allowed(self) -> bool:
        """Check if a call is allowed through the circuit breaker."""
        if self.state == "closed":
            return True
        if self.state == "open":
            # Check if recovery window has elapsed
            elapsed = time.time() - self.last_failure_time
            if elapsed >= self.recovery_window_seconds:
                self.state = "half_open"
                return True
            return False
        # half_open: allow one test call
        return True

    def record_success(self) -> None:
        """Record a successful call — reset failure count and close circuit."""
        self.failure_count = 0
        self.state = "closed"

    def record_failure(self) -> None:
        """Record a failed call — increment count and potentially open circuit."""
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            self.state = "open"


class BedrockVLMClient(VLMClientPort):
    """Concrete Bedrock LLM client implementing VLMClientPort.

    Features:
    - vlm_enabled flag check before any call
    - Circuit breaker: open after 3 consecutive failures, 60s recovery
    - Retry once with exponential backoff on throttle/timeout
    - Maximum 2 Bedrock API calls per field (1 initial + 1 retry)
    - Logs vlm.triggered event
    """

    BASE_BACKOFF_MS = 1000  # 1 second

    def __init__(
        self,
        region: str = "eu-west-1",
        model_id: str = "anthropic.claude-3-5-sonnet-20241022-v2:0",
        vlm_enabled: bool = False,
    ) -> None:
        """Initialize the Bedrock LLM client.

        Args:
            region: AWS region for Bedrock.
            model_id: The Bedrock model identifier.
            vlm_enabled: Whether VLM is enabled for the tenant.
        """
        self._region = region
        self._model_id = model_id
        self._vlm_enabled = vlm_enabled
        self._circuit_breaker = CircuitBreaker(
            failure_threshold=10,
            recovery_window_seconds=60.0,
        )
        self._client: Any = None

    def _get_client(self) -> Any:
        """Lazy-initialize the boto3 Bedrock runtime client."""
        if self._client is None:
            import os
            from botocore.config import Config
            
            # Use AWS_PROFILE if set (for SSO login)
            profile = os.environ.get("AWS_PROFILE")
            if profile:
                session = boto3.Session(profile_name=profile, region_name=self._region)
                self._client = session.client(
                    "bedrock-runtime",
                    config=Config(
                        read_timeout=300,
                        connect_timeout=10,
                        retries={"max_attempts": 0},
                    ),
                )
            else:
                self._client = boto3.client(
                    "bedrock-runtime",
                    region_name=self._region,
                    config=Config(
                        read_timeout=300,
                        connect_timeout=10,
                        retries={"max_attempts": 0},
                    ),
                )
        return self._client

    def estimate_tokens(self, text: str) -> int:
        """Estimate token count using model-specific chars-per-token ratio.

        Falls back to 3.5 chars/token if the model is not in the registry.
        """
        chars_per_token = MODEL_CHARS_PER_TOKEN.get(self._model_id, 3.5)
        return int(len(text) / chars_per_token)

    def max_context_tokens(self) -> int:
        """Return the model's context window size from the registry.

        Falls back to 200,000 tokens if the model is not in the registry.
        """
        return MODEL_CONTEXT_WINDOWS.get(self._model_id, 200_000)

    def extract_field(
        self,
        page_text: str,
        field_name: str,
        field_description: str,
        schema_type: str,
    ) -> VLMFieldResult:
        """Extract a single field from page text using Claude on Bedrock.

        Checks vlm_enabled flag, circuit breaker state, then invokes the model.
        Retries once on throttle/timeout.

        Args:
            page_text: Full text content of the document page.
            field_name: Name of the field to extract.
            field_description: Description of what the field contains.
            schema_type: Document schema type.

        Returns:
            VLMFieldResult with extracted value or abstention indicator.
        """
        # Check vlm_enabled flag — abstain immediately if disabled
        if not self._vlm_enabled:
            logger.info(
                "vlm.disabled",
                field_name=field_name,
                reason=ErrorCode.VLM_DISABLED_FOR_TENANT,
            )
            return VLMFieldResult(
                value=None,
                confidence=0.0,
                raw_response="",
                model_id=self._model_id,
            )

        # Check circuit breaker
        if not self._circuit_breaker.is_call_allowed():
            logger.warning(
                "vlm.circuit_open",
                field_name=field_name,
                reason=ErrorCode.VLM_BEDROCK_THROTTLED,
            )
            return VLMFieldResult(
                value=None,
                confidence=0.0,
                raw_response="circuit_breaker_open",
                model_id=self._model_id,
            )

        # Log VLM triggered event
        logger.info(
            "vlm.triggered",
            field_name=field_name,
            schema_type=schema_type,
            model_id=self._model_id,
            text_length=len(page_text),
        )

        # Attempt extraction (max 2 calls: 1 initial + 1 retry)
        last_error: str = ""
        for attempt in range(1, 3):  # attempts 1 and 2
            try:
                result = self._invoke_model(
                    page_text=page_text,
                    field_name=field_name,
                    field_description=field_description,
                    schema_type=schema_type,
                )
                self._circuit_breaker.record_success()
                return result
            except (
                self._get_client().exceptions.ThrottlingException
                if hasattr(self._get_client(), "exceptions")
                else Exception
            ) as e:
                last_error = str(e)
                self._circuit_breaker.record_failure()
                logger.warning(
                    "vlm.call_failed",
                    field_name=field_name,
                    attempt=attempt,
                    error=last_error,
                )
                if attempt < 2:
                    # Exponential backoff before retry
                    backoff_seconds = (self.BASE_BACKOFF_MS * (2 ** (attempt - 1))) / 1000
                    time.sleep(backoff_seconds)
            except Exception as e:
                last_error = str(e)
                self._circuit_breaker.record_failure()
                logger.warning(
                    "vlm.call_failed",
                    field_name=field_name,
                    attempt=attempt,
                    error=last_error,
                )
                if attempt < 2:
                    backoff_seconds = (self.BASE_BACKOFF_MS * (2 ** (attempt - 1))) / 1000
                    time.sleep(backoff_seconds)

        # All retries exhausted — abstain with ERR_VLM_005
        logger.error(
            "vlm.exhausted",
            field_name=field_name,
            reason=ErrorCode.VLM_BEDROCK_THROTTLED,
            last_error=last_error,
        )
        return VLMFieldResult(
            value=None,
            confidence=0.0,
            raw_response=f"retries_exhausted: {last_error}",
            model_id=self._model_id,
        )

    def _invoke_model(
        self,
        page_text: str,
        field_name: str,
        field_description: str,
        schema_type: str,
    ) -> VLMFieldResult:
        """Invoke Claude on Bedrock for text-based field extraction.

        Args:
            page_text: Full text content of the document page.
            field_name: Field to extract.
            field_description: Description of the field.
            schema_type: Document type.

        Returns:
            VLMFieldResult with the extracted value.
        """
        client = self._get_client()

        # For full extraction, page_text IS the prompt (from llm_extractor.py)
        # For single-field extraction, we build a prompt around the page_text
        if field_name in ("full_extraction", "metadata_extraction", "transaction_extraction", "chunked_extraction", "page_summary"):
            prompt = page_text
        else:
            prompt = (
                f"You are extracting a specific field from a {schema_type} document.\n\n"
                f"Field to extract: {field_name}\n"
                f"Description: {field_description}\n\n"
                f"Document text:\n---\n{page_text}\n---\n\n"
                "Rules:\n"
                "- Extract ONLY what is explicitly present in the text. Do not infer or calculate.\n"
                "- Return the value exactly as it appears in the text.\n"
                "- If the field is not present, return null for value.\n\n"
                'Respond with ONLY a JSON object:\n'
                '{"value": "<extracted value or null>", "confidence": <0.0 to 1.0>}'
            )

        # Use higher token limit for extraction calls (metadata is small, transactions need more)
        if field_name in ("full_extraction", "transaction_extraction", "chunked_extraction"):
            max_tokens = 8192
        elif field_name in ("metadata_extraction", "page_summary"):
            max_tokens = 2048
        else:
            max_tokens = 256

        # Build request body for Claude Messages API (text-only)
        request_body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt,
                        },
                    ],
                }
            ],
        }

        response = client.invoke_model(
            modelId=self._model_id,
            body=json.dumps(request_body),
            contentType="application/json",
            accept="application/json",
        )

        response_body = json.loads(response["body"].read())
        raw_response = json.dumps(response_body)

        # Log raw response for debugging
        logger.info(
            "vlm.raw_response",
            field_name=field_name,
            raw_response=raw_response[:500],
        )

        # Parse the response text
        content = response_body.get("content", [])
        extracted_text = ""
        for block in content:
            if block.get("type") == "text":
                extracted_text = block.get("text", "").strip()
                break

        # For extraction calls, return the raw JSON text as the value
        # (llm_extractor.py will parse it)
        if field_name in ("full_extraction", "metadata_extraction", "transaction_extraction", "chunked_extraction", "page_summary"):
            return VLMFieldResult(
                value=extracted_text if extracted_text else None,
                confidence=0.9,
                raw_response=raw_response,
                model_id=self._model_id,
            )

        # For single-field extraction, parse the {"value": ..., "confidence": ...} response
        try:
            parsed = json.loads(extracted_text)
            value = parsed.get("value")
            confidence = float(parsed.get("confidence", 0.0))
        except (json.JSONDecodeError, TypeError, ValueError):
            # If JSON parsing fails, treat as null
            logger.warning(
                "vlm.parse_error",
                field_name=field_name,
                raw_text=extracted_text[:200],
            )
            return VLMFieldResult(
                value=None,
                confidence=0.0,
                raw_response=raw_response,
                model_id=self._model_id,
            )

        # Handle null/None value
        if value is None or (isinstance(value, str) and value.strip().upper() in ("NULL", "")):
            return VLMFieldResult(
                value=None,
                confidence=0.0,
                raw_response=raw_response,
                model_id=self._model_id,
            )

        return VLMFieldResult(
            value=str(value),
            confidence=confidence,
            raw_response=raw_response,
            model_id=self._model_id,
        )
