"""Central error code registry.

All errors emitted by this service use namespaced codes. Codes appear in log
entries, API error responses, and abstention reasons. They must never be ad-hoc
strings.

Every Abstention reason field must reference an ErrorCode constant, not a raw
string.
"""


class ErrorCode:
    """Namespaced error code constants for the PDF Ingestion Layer."""

    # ─── Authentication ───────────────────────────────────────────────────────
    AUTH_MISSING_CREDENTIALS: str = "ERR_AUTH_001"
    AUTH_INVALID_CREDENTIALS: str = "ERR_AUTH_002"
    AUTH_TENANT_SUSPENDED: str = "ERR_AUTH_003"

    # ─── Ingestion ────────────────────────────────────────────────────────────
    INGESTION_INVALID_FILE_TYPE: str = "ERR_INGESTION_001"
    INGESTION_FILE_TOO_LARGE: str = "ERR_INGESTION_002"
    INGESTION_ENCRYPTED_PDF: str = "ERR_INGESTION_003"
    INGESTION_ZERO_PAGES: str = "ERR_INGESTION_004"

    # ─── Extraction ───────────────────────────────────────────────────────────
    EXTRACTION_PATTERN_NOT_FOUND: str = "ERR_EXTRACT_001"
    EXTRACTION_SCHEMA_UNKNOWN: str = "ERR_EXTRACT_002"
    EXTRACTION_TABLE_ABSTAINED: str = "ERR_EXTRACT_003"

    # ─── VLM ──────────────────────────────────────────────────────────────────
    VLM_DISABLED_FOR_TENANT: str = "ERR_VLM_001"
    VLM_REDACTION_CONFIDENCE_LOW: str = "ERR_VLM_002"
    VLM_RETURNED_NULL: str = "ERR_VLM_003"
    VLM_VALUE_UNVERIFIABLE: str = "ERR_VLM_004"
    VLM_BEDROCK_THROTTLED: str = "ERR_VLM_005"
    VLM_PARSE_ERROR: str = "ERR_VLM_006"
    VLM_BUDGET_EXCEEDED: str = "ERR_VLM_007"
    VLM_WINDOW_FAILED: str = "ERR_VLM_008"
    VLM_MERGE_CONFLICT: str = "ERR_VLM_009"

    # ─── Validation ───────────────────────────────────────────────────────────
    VALIDATION_ARITHMETIC_MISMATCH: str = "ERR_VALID_001"
    VALIDATION_INVALID_IBAN: str = "ERR_VALID_002"
    VALIDATION_INVALID_ISIN: str = "ERR_VALID_003"
    VALIDATION_INVALID_BIC: str = "ERR_VALID_004"
    VALIDATION_DATE_OUT_OF_RANGE: str = "ERR_VALID_005"
    VALIDATION_INVALID_CURRENCY: str = "ERR_VALID_006"
    VALIDATION_PROVENANCE_BROKEN: str = "ERR_VALID_007"

    # ─── Delivery ─────────────────────────────────────────────────────────────
    DELIVERY_CALLBACK_NOT_CONFIGURED: str = "ERR_DELIVERY_001"
    DELIVERY_FAILED_AFTER_RETRIES: str = "ERR_DELIVERY_002"
    DELIVERY_BATCH_NOT_FOUND: str = "ERR_DELIVERY_003"
