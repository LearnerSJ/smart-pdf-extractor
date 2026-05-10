"""Tests for tests/mocks.py — verify mocks implement port interfaces."""

from __future__ import annotations

import pytest

from pipeline.models import EntityRedactionConfig, Token, VLMFieldResult
from pipeline.ports import DeliveryPort, OCRClientPort, RedactorPort, VLMClientPort
from tests.mocks import (
    MockDeliveryClient,
    MockOCRClient,
    MockRedactor,
    MockVLMClient,
)


def test_mock_vlm_client_implements_port():
    """MockVLMClient implements VLMClientPort interface."""
    client = MockVLMClient()
    assert isinstance(client, VLMClientPort)


def test_mock_vlm_client_returns_fixture():
    """MockVLMClient returns the configured fixture."""
    fixture = VLMFieldResult(
        value="test_value", confidence=0.9, raw_response="raw", model_id="test"
    )
    client = MockVLMClient(fixture=fixture)
    result = client.extract_field("sample document text", "field", "desc", "bank_statement")
    assert result.value == "test_value"
    assert result.confidence == 0.9
    assert len(client.calls) == 1


def test_mock_redactor_implements_port():
    """MockRedactor implements RedactorPort interface."""
    redactor = MockRedactor()
    assert isinstance(redactor, RedactorPort)


def test_mock_redactor_returns_unchanged_text():
    """MockRedactor returns text unchanged with empty log."""
    redactor = MockRedactor()
    config = [EntityRedactionConfig(entity_type="PERSON", enabled=True)]
    text, log = redactor.redact_page_text("Hello John", config)
    assert text == "Hello John"
    assert log.redacted_count == 0
    assert log.entities_redacted == []


def test_mock_ocr_client_implements_port():
    """MockOCRClient implements OCRClientPort interface."""
    client = MockOCRClient()
    assert isinstance(client, OCRClientPort)


def test_mock_ocr_client_returns_fixture():
    """MockOCRClient returns configured fixture tokens."""
    tokens = [Token(text="hello", bbox=(0, 0, 10, 10), confidence=0.99)]
    client = MockOCRClient(fixture=tokens)
    result = client.extract_tokens(b"image")
    assert len(result) == 1
    assert result[0].text == "hello"


def test_mock_delivery_client_implements_port():
    """MockDeliveryClient implements DeliveryPort interface."""
    client = MockDeliveryClient()
    assert isinstance(client, DeliveryPort)


@pytest.mark.asyncio
async def test_mock_delivery_client_records_attempts():
    """MockDeliveryClient records delivery attempts."""
    client = MockDeliveryClient(should_succeed=True)
    result = await client.deliver({"key": "value"}, "https://example.com/hook")
    assert result.success is True
    assert result.status_code == 200
    assert len(client.attempts) == 1
    assert client.attempts[0]["url"] == "https://example.com/hook"


@pytest.mark.asyncio
async def test_mock_delivery_client_failure():
    """MockDeliveryClient can simulate failures."""
    client = MockDeliveryClient(should_succeed=False)
    result = await client.deliver({"key": "value"}, "https://example.com/hook")
    assert result.success is False
    assert result.status_code == 500
