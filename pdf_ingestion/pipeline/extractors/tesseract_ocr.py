"""Tesseract OCR client — local alternative to PaddleOCR.

Runs Tesseract directly on the machine without needing a Docker container.
Implements OCRClientPort for seamless swapping.

Requires: brew install tesseract (macOS) or apt install tesseract-ocr (Linux)
Python dep: pip install pytesseract Pillow
"""

from __future__ import annotations

import hashlib
import io
from typing import Any

import structlog
from PIL import Image

from pipeline.models import Token
from pipeline.ports import OCRClientPort

logger = structlog.get_logger()

try:
    import pytesseract  # type: ignore[import-untyped]
    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False


class TesseractOCRClient(OCRClientPort):
    """Local Tesseract OCR client implementing OCRClientPort.

    Features:
    - Runs locally without Docker
    - Result caching by page hash
    - Returns tokens with bounding boxes and confidence
    - Falls back gracefully if Tesseract is not installed
    """

    def __init__(self) -> None:
        self._cache: dict[str, list[Token]] = {}

    def extract_tokens(self, page_image: bytes) -> list[Token]:
        """Extract text tokens from a page image using Tesseract.

        Args:
            page_image: PNG/JPEG image bytes of the page.

        Returns:
            List of Token objects with text, bbox, and confidence.
            Empty list if Tesseract is not available.
        """
        if not TESSERACT_AVAILABLE:
            logger.warning("ocr.tesseract_not_installed")
            return []

        if not page_image:
            return []

        # Check cache
        page_hash = hashlib.sha256(page_image).hexdigest()
        if page_hash in self._cache:
            return self._cache[page_hash]

        try:
            image = Image.open(io.BytesIO(page_image))
            # Get word-level data with bounding boxes and confidence
            data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)

            tokens: list[Token] = []
            n_boxes = len(data["text"])

            for i in range(n_boxes):
                text = data["text"][i].strip()
                conf = float(data["conf"][i])

                # Skip empty text and low-confidence results
                if not text or conf < 0:
                    continue

                x = float(data["left"][i])
                y = float(data["top"][i])
                w = float(data["width"][i])
                h = float(data["height"][i])

                tokens.append(Token(
                    text=text,
                    bbox=(x, y, x + w, y + h),
                    confidence=conf / 100.0,  # Tesseract returns 0-100
                ))

            self._cache[page_hash] = tokens

            logger.info(
                "ocr.tesseract_extracted",
                page_hash=page_hash[:12],
                token_count=len(tokens),
            )
            return tokens

        except Exception as e:
            logger.error("ocr.tesseract_failed", error=str(e))
            return []

    def is_available(self) -> bool:
        """Check if Tesseract is installed and working."""
        if not TESSERACT_AVAILABLE:
            return False
        try:
            pytesseract.get_tesseract_version()
            return True
        except Exception:
            return False
