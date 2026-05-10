"""Ingestion layer: validation, deduplication, and repair.

Validates uploaded files (magic bytes, size, encryption), computes SHA-256
for deduplication, and repairs malformed PDFs via pikepdf.
"""

from __future__ import annotations

import hashlib
from typing import Callable

import pikepdf
import structlog

from api.config import Settings
from api.errors import ErrorCode
from pipeline.models import CachedResult, IngestedDocument

logger = structlog.get_logger()

# PDF magic bytes: %PDF (hex: 25 50 44 46)
PDF_MAGIC_BYTES = b"%PDF"


class IngestionError(Exception):
    """Raised when ingestion validation fails."""

    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


async def ingest(
    file_bytes: bytes,
    filename: str,
    settings: Settings,
    dedup_lookup: Callable[[str], CachedResult | None] | None = None,
) -> IngestedDocument | CachedResult:
    """Validate, deduplicate, and repair a PDF file.

    Args:
        file_bytes: Raw bytes of the uploaded file.
        filename: Original filename.
        settings: Application settings (for max file size).
        dedup_lookup: Optional callable that checks if a hash already exists.
            Returns CachedResult if duplicate, None otherwise.

    Returns:
        IngestedDocument if the file is new and valid.
        CachedResult if the file is a duplicate.

    Raises:
        IngestionError: If validation fails (invalid type, too large, encrypted).
    """
    # 1. Validate magic bytes — confirm it's a PDF
    if not file_bytes[:4].startswith(PDF_MAGIC_BYTES):
        logger.warning(
            "ingestion.rejected",
            reason="invalid_file_type",
            filename=filename,
            code=ErrorCode.INGESTION_INVALID_FILE_TYPE,
        )
        raise IngestionError(
            code=ErrorCode.INGESTION_INVALID_FILE_TYPE,
            message="File is not a valid PDF",
            status_code=422,
        )

    # 2. Validate file size
    max_size_bytes = settings.max_file_size_mb * 1024 * 1024
    if len(file_bytes) > max_size_bytes:
        logger.warning(
            "ingestion.rejected",
            reason="file_too_large",
            filename=filename,
            size_bytes=len(file_bytes),
            max_size_bytes=max_size_bytes,
            code=ErrorCode.INGESTION_FILE_TOO_LARGE,
        )
        raise IngestionError(
            code=ErrorCode.INGESTION_FILE_TOO_LARGE,
            message=f"File exceeds maximum size of {settings.max_file_size_mb} MB",
            status_code=413,
        )

    # 3. Compute SHA-256 hash for deduplication
    doc_hash = hashlib.sha256(file_bytes).hexdigest()

    # 4. Check for duplicate
    if dedup_lookup is not None:
        cached = dedup_lookup(doc_hash)
        if cached is not None:
            logger.info(
                "ingestion.deduplicated",
                filename=filename,
                hash=doc_hash,
            )
            return cached

    # 5. Attempt pikepdf repair and check for encryption
    repaired_bytes = _repair_pdf(file_bytes, filename)

    logger.info(
        "ingestion.accepted",
        filename=filename,
        hash=doc_hash,
        size_bytes=len(file_bytes),
    )

    return IngestedDocument(
        hash=doc_hash,
        content=repaired_bytes,
        filename=filename,
    )


def _repair_pdf(file_bytes: bytes, filename: str) -> bytes:
    """Attempt to open and repair a PDF using pikepdf.

    Raises:
        IngestionError: If the PDF is password-protected.
    """
    import io

    try:
        pdf = pikepdf.open(io.BytesIO(file_bytes))
    except pikepdf.PasswordError:
        logger.warning(
            "ingestion.rejected",
            reason="encrypted_pdf",
            filename=filename,
            code=ErrorCode.INGESTION_ENCRYPTED_PDF,
        )
        raise IngestionError(
            code=ErrorCode.INGESTION_ENCRYPTED_PDF,
            message="Password-protected PDFs are not supported",
            status_code=422,
        )
    except Exception:
        # If pikepdf can't open it at all, try to repair
        try:
            pdf = pikepdf.open(io.BytesIO(file_bytes), allow_overwriting_input=True)
        except pikepdf.PasswordError:
            raise IngestionError(
                code=ErrorCode.INGESTION_ENCRYPTED_PDF,
                message="Password-protected PDFs are not supported",
                status_code=422,
            )
        except Exception:
            # Return original bytes if repair also fails — downstream will handle
            logger.warning(
                "ingestion.repair_failed",
                filename=filename,
            )
            return file_bytes

    # Save repaired PDF to bytes
    output = io.BytesIO()
    pdf.save(output)
    pdf.close()
    repaired = output.getvalue()
    return repaired
