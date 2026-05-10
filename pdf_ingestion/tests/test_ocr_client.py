"""Tests for the PaddleOCR client."""

from __future__ import annotations

import time

from pipeline.extractors.ocr import CircuitBreaker, PaddleOCRClient


class TestOCRCircuitBreaker:
    """Tests for the OCR CircuitBreaker."""

    def test_starts_closed(self) -> None:
        cb = CircuitBreaker(failure_threshold=3, recovery_window_seconds=30.0)
        assert cb.state == "closed"
        assert cb.is_call_allowed() is True

    def test_opens_after_3_failures(self) -> None:
        cb = CircuitBreaker(failure_threshold=3, recovery_window_seconds=30.0)
        cb.record_failure()
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "open"
        assert cb.is_call_allowed() is False

    def test_recovery_window(self) -> None:
        cb = CircuitBreaker(failure_threshold=3, recovery_window_seconds=0.01)
        cb.record_failure()
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.02)
        assert cb.is_call_allowed() is True
        assert cb.state == "half_open"


class TestPaddleOCRClient:
    """Tests for PaddleOCRClient."""

    def test_cache_hit(self) -> None:
        """Cached results should be returned without calling the service."""
        client = PaddleOCRClient(endpoint="http://localhost:9999")

        # Pre-populate cache
        import hashlib
        page_image = b"test_image_bytes"
        page_hash = hashlib.sha256(page_image).hexdigest()
        cache_key = f"{page_hash}:{client.MODEL_VERSION}"

        from pipeline.models import Token
        cached_tokens = [Token(text="cached", bbox=(0, 0, 10, 10), confidence=0.99)]
        client._cache[cache_key] = cached_tokens

        # Should return cached result
        result = client.extract_tokens(page_image)
        assert len(result) == 1
        assert result[0].text == "cached"

    def test_circuit_open_returns_empty(self) -> None:
        """When circuit is open, should return empty list (abstain)."""
        client = PaddleOCRClient(endpoint="http://localhost:9999")

        # Force circuit open
        client._circuit_breaker.record_failure()
        client._circuit_breaker.record_failure()
        client._circuit_breaker.record_failure()

        result = client.extract_tokens(b"test_image")
        assert result == []

    def test_parse_response(self) -> None:
        """Should correctly parse PaddleOCR JSON response."""
        client = PaddleOCRClient()

        data = {
            "results": [
                {"text": "Hello", "bbox": [10, 20, 50, 40], "confidence": 0.95},
                {"text": "World", "bbox": [60, 20, 100, 40], "confidence": 0.92},
            ]
        }

        tokens = client._parse_response(data)
        assert len(tokens) == 2
        assert tokens[0].text == "Hello"
        assert tokens[0].bbox == (10.0, 20.0, 50.0, 40.0)
        assert tokens[0].confidence == 0.95
        assert tokens[1].text == "World"

    def test_parse_empty_response(self) -> None:
        """Empty response should return empty list."""
        client = PaddleOCRClient()
        tokens = client._parse_response({"results": []})
        assert tokens == []

    def test_service_failure_records_in_circuit_breaker(self) -> None:
        """Failed service call should increment circuit breaker failure count."""
        client = PaddleOCRClient(endpoint="http://localhost:1")  # Invalid port

        # This will fail to connect
        result = client.extract_tokens(b"test_image")
        assert result == []
        assert client._circuit_breaker.failure_count == 1
