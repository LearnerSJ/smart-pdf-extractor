"""PaddleOCR native client — runs PaddleOCR directly in-process.

No Docker container needed. Uses the paddleocr Python package directly.
Implements OCRClientPort for seamless swapping.

Requires: pip install paddlepaddle paddleocr
"""

from __future__ import annotations

import hashlib
import io
from typing import Any

import structlog

from pipeline.models import Token
from pipeline.ports import OCRClientPort

logger = structlog.get_logger()

try:
    from paddleocr import PaddleOCR  # type: ignore[import-untyped]

    PADDLE_AVAILABLE = True
except ImportError:
    PADDLE_AVAILABLE = False


class PaddleNativeOCRClient(OCRClientPort):
    """Native PaddleOCR client — runs OCR in-process without Docker.

    Features:
    - Direct Python call to PaddleOCR (no HTTP, no container)
    - Result caching by page hash
    - Returns tokens with bounding boxes and confidence
    - Lazy initialization (model loaded on first call)
    """

    MODEL_VERSION = "paddleocr_native_v4"

    def __init__(self, lang: str = "en") -> None:
        self._lang = lang
        self._ocr: Any = None
        self._cache: dict[str, list[Token]] = {}

    def _get_ocr(self) -> Any:
        """Lazy-init the PaddleOCR instance (downloads model on first use)."""
        if self._ocr is None:
            # PaddleOCR 3.x: use_angle_cls -> use_textline_orientation; show_log removed.
            self._ocr = PaddleOCR(use_textline_orientation=True, lang=self._lang)
            logger.info("ocr.paddle_native_initialized", lang=self._lang)
        return self._ocr

    def extract_tokens(self, page_image: bytes) -> list[Token]:
        """Extract text tokens from a page image using PaddleOCR natively.

        Args:
            page_image: PNG/JPEG image bytes of the page.

        Returns:
            List of Token objects with text, bbox, and confidence.
            Empty list if PaddleOCR is not available.
        """
        if not PADDLE_AVAILABLE:
            logger.warning("ocr.paddle_not_installed")
            return []

        # Cache check
        page_hash = hashlib.sha256(page_image).hexdigest()
        cache_key = f"{page_hash}:{self.MODEL_VERSION}"
        if cache_key in self._cache:
            logger.info("ocr.cache_hit", page_hash=page_hash[:12])
            return self._cache[cache_key]

        try:
            import numpy as np
            from PIL import Image

            # Convert bytes to numpy array (PaddleOCR expects ndarray or file path)
            image = Image.open(io.BytesIO(page_image)).convert("RGB")
            img_array = np.array(image)

            ocr = self._get_ocr()
            # PaddleOCR 3.x: .predict() returns a list of dict-like results with
            # parallel arrays (rec_texts / rec_scores / rec_polys), replacing the
            # old .ocr(cls=True) nested [bbox, (text, conf)] format.
            result = ocr.predict(img_array)

            tokens: list[Token] = []
            for page in result:
                texts = page.get("rec_texts") or []
                scores = page.get("rec_scores") or []
                polys = page.get("rec_polys")
                if polys is None:
                    polys = page.get("dt_polys") or []

                for text, confidence, bbox_points in zip(texts, scores, polys):
                    if not text.strip():
                        continue

                    # Convert 4-point bbox to (x0, y0, x1, y1)
                    xs = [float(p[0]) for p in bbox_points]
                    ys = [float(p[1]) for p in bbox_points]
                    bbox = (min(xs), min(ys), max(xs), max(ys))

                    tokens.append(
                        Token(text=text, bbox=bbox, confidence=float(confidence))
                    )

            self._cache[cache_key] = tokens
            logger.info(
                "ocr.paddle_native_extracted",
                page_hash=page_hash[:12],
                token_count=len(tokens),
            )
            return tokens

        except Exception as e:
            logger.error("ocr.paddle_native_failed", error=str(e))
            return []

    def is_available(self) -> bool:
        """Check if PaddleOCR is installed."""
        return PADDLE_AVAILABLE
