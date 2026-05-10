"""Tests for pipeline/ingestion.py."""

from __future__ import annotations

import pytest

from api.config import Settings
from pipeline.ingestion import IngestionError, ingest
from pipeline.models import CachedResult, IngestedDocument


@pytest.fixture
def settings():
    """Default settings for testing."""
    return Settings(max_file_size_mb=50)


@pytest.mark.asyncio
async def test_ingest_valid_pdf(settings):
    """Valid PDF bytes pass ingestion and return IngestedDocument."""
    # Minimal valid PDF
    pdf_bytes = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF"
    result = await ingest(pdf_bytes, "test.pdf", settings)
    assert isinstance(result, IngestedDocument)
    assert result.filename == "test.pdf"
    assert len(result.hash) == 64  # SHA-256 hex digest


@pytest.mark.asyncio
async def test_ingest_rejects_non_pdf(settings):
    """Non-PDF files are rejected with ERR_INGESTION_001."""
    with pytest.raises(IngestionError) as exc_info:
        await ingest(b"not a pdf file", "test.txt", settings)
    assert exc_info.value.code == "ERR_INGESTION_001"
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_ingest_rejects_oversized_file(settings):
    """Files exceeding max size are rejected with ERR_INGESTION_002."""
    small_settings = Settings(max_file_size_mb=1)
    # Create a file larger than 1MB
    large_pdf = b"%PDF-1.4" + b"\x00" * (2 * 1024 * 1024)
    with pytest.raises(IngestionError) as exc_info:
        await ingest(large_pdf, "large.pdf", small_settings)
    assert exc_info.value.code == "ERR_INGESTION_002"
    assert exc_info.value.status_code == 413


@pytest.mark.asyncio
async def test_ingest_dedup_returns_cached_result(settings):
    """Duplicate files return CachedResult."""
    pdf_bytes = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF"

    import hashlib
    expected_hash = hashlib.sha256(pdf_bytes).hexdigest()

    def dedup_lookup(h: str):
        if h == expected_hash:
            return CachedResult(hash=h)
        return None

    result = await ingest(pdf_bytes, "test.pdf", settings, dedup_lookup=dedup_lookup)
    assert isinstance(result, CachedResult)
    assert result.hash == expected_hash


@pytest.mark.asyncio
async def test_ingest_deterministic_hash(settings):
    """Identical bytes always produce the same hash."""
    pdf_bytes = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF"
    result1 = await ingest(pdf_bytes, "a.pdf", settings)
    result2 = await ingest(pdf_bytes, "b.pdf", settings)
    assert isinstance(result1, IngestedDocument)
    assert isinstance(result2, IngestedDocument)
    assert result1.hash == result2.hash
