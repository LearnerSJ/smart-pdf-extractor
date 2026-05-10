"""API request models."""

from __future__ import annotations

from pydantic import BaseModel


class ExtractionRequest(BaseModel):
    """Request body for POST /v1/extract.

    The actual file is uploaded as multipart form data.
    These fields are optional metadata sent alongside the file.
    """

    schema_type: str | None = None
    batch_id: str | None = None
