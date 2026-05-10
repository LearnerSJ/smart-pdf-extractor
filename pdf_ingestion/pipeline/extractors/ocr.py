"""PaddleOCR client — concrete implementation of OCRClientPort.

Communicates with PaddleOCR Docker container via HTTP (httpx).
Implements circuit breaker: open after 3 consecutive failures, 30s recovery.
Caches results by (page_hash, model_version).
"""

from __future__ import annotations

import hashlib
import time
from typing import Any

import httpx
import structlog

from pipeline.models import Token
from pipeline.ports import OCRClientPort

logger = structlog.get_logger()


class CircuitBreaker:
    """Simple circuit breaker for OCR service calls.

    States:
    - closed: normal operation
    - open: calls rejected immediately
    - half_open: one test call allowed after recovery window

    Args:
        failure_threshold: Consecutive failures to open circuit.
        recovery_window_seconds: Time before transitioning to half_open.
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        recovery_window_seconds: float = 30.0,
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
            elapsed = time.time() - self.last_failure_time
            if elapsed >= self.recovery_window_seconds:
                self.state = "half_open"
                return True
            return False
        # half_open: allow one test call
        return True

    def record_success(self) -> None:
        """Record a successful call — reset and close circuit."""
        self.failure_count = 0
        self.state = "closed"

    def record_failure(self) -> None:
        """Record a failed call — increment count, potentially open circuit."""
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            self.state = "open"


class PaddleOCRClient(OCRClientPort):
    """Concrete PaddleOCR client implementing OCRClientPort.

    Features:
    - HTTP communication with PaddleOCR Docker container via httpx
    - Result caching by (page_hash, model_version)
    - Circuit breaker: open after 3 consecutive failures, 30s recovery
    - Abstains on scanned pages if service unavailable
    """

    MODEL_VERSION = "paddleocr_v4"

    def __init__(
        self,
        endpoint: str = "http://paddleocr:8080",
        timeout: float = 30.0,
    ) -> None:
        """Initialize the PaddleOCR client.

        Args:
            endpoint: Base URL of the PaddleOCR HTTP service.
            timeout: Request timeout in seconds.
        """
        self._endpoint = endpoint.rstrip("/")
        self._timeout = timeout
        self._circuit_breaker = CircuitBreaker(
            failure_threshold=3,
            recovery_window_seconds=30.0,
        )
        self._cache: dict[str, list[Token]] = {}

    def extract_tokens(self, page_image: bytes) -> list[Token]:
        """Extract text tokens from a page image via PaddleOCR.

        Checks cache first, then circuit breaker, then calls the service.
        Returns empty list if service is unavailable (abstain on scanned pages).

        Args:
            page_image: PNG/JPEG image bytes of the page.

        Returns:
            List of Token objects with text, bbox, and confidence.
            Empty list if service unavailable (circuit open).
        """
        # Compute cache key
        page_hash = hashlib.sha256(page_image).hexdigest()
        cache_key = f"{page_hash}:{self.MODEL_VERSION}"

        # Check cache
        if cache_key in self._cache:
            logger.info("ocr.cache_hit", page_hash=page_hash[:12])
            return self._cache[cache_key]

        # Check circuit breaker
        if not self._circuit_breaker.is_call_allowed():
            logger.warning(
                "ocr.circuit_open",
                page_hash=page_hash[:12],
            )
            return []

        # Call PaddleOCR service
        try:
            tokens = self._call_ocr_service(page_image)
            self._circuit_breaker.record_success()

            # Cache the result
            self._cache[cache_key] = tokens

            logger.info(
                "ocr.extracted",
                page_hash=page_hash[:12],
                token_count=len(tokens),
            )
            return tokens

        except Exception as e:
            self._circuit_breaker.record_failure()
            logger.warning(
                "ocr.call_failed",
                page_hash=page_hash[:12],
                error=str(e),
                failure_count=self._circuit_breaker.failure_count,
                circuit_state=self._circuit_breaker.state,
            )
            return []

    def _call_ocr_service(self, page_image: bytes) -> list[Token]:
        """Make HTTP call to PaddleOCR service.

        Args:
            page_image: Image bytes to send.

        Returns:
            List of Token objects parsed from the response.

        Raises:
            httpx.HTTPError: On network or HTTP errors.
        """
        url = f"{self._endpoint}/ocr"

        with httpx.Client(timeout=self._timeout) as client:
            response = client.post(
                url,
                files={"image": ("page.png", page_image, "image/png")},
            )
            response.raise_for_status()

        data = response.json()
        return self._parse_response(data)

    def _parse_response(self, data: Any) -> list[Token]:
        """Parse PaddleOCR JSON response into Token objects.

        Expected response format:
        {
            "results": [
                {
                    "text": "...",
                    "bbox": [x0, y0, x1, y1],
                    "confidence": 0.95
                },
                ...
            ]
        }

        Args:
            data: Parsed JSON response from PaddleOCR.

        Returns:
            List of Token objects.
        """
        tokens: list[Token] = []
        results = data.get("results", [])

        for item in results:
            text = item.get("text", "")
            bbox_raw = item.get("bbox", [0, 0, 0, 0])
            confidence = float(item.get("confidence", 0.0))

            # Ensure bbox has 4 elements
            if len(bbox_raw) >= 4:
                bbox = (
                    float(bbox_raw[0]),
                    float(bbox_raw[1]),
                    float(bbox_raw[2]),
                    float(bbox_raw[3]),
                )
            else:
                bbox = (0.0, 0.0, 0.0, 0.0)

            tokens.append(Token(text=text, bbox=bbox, confidence=confidence))

        return tokens

    def is_available(self) -> bool:
        """Check if the PaddleOCR service is reachable.

        Used by the readiness health check.

        Returns:
            True if service responds to health check.
        """
        try:
            with httpx.Client(timeout=5.0) as client:
                response = client.get(f"{self._endpoint}/health")
                return response.status_code == 200
        except Exception:
            return False
