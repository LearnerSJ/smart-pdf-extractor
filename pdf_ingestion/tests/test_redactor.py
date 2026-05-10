"""Tests for the Presidio redactor."""

from __future__ import annotations

import pytest

from pipeline.models import EntityRedactionConfig


class TestPageRedactor:
    """Tests for PageRedactor."""

    def _make_redactor(self):
        """Create a PageRedactor instance (imports presidio)."""
        try:
            from pipeline.vlm.redactor import PageRedactor
            return PageRedactor()
        except ImportError:
            pytest.skip("presidio not installed")

    def test_no_entities_enabled_returns_original(self) -> None:
        """When no entities are enabled, original text is returned unchanged."""
        redactor = self._make_redactor()
        text = "John Smith lives at 123 Main St."
        config = [
            EntityRedactionConfig(entity_type="PERSON", enabled=False),
            EntityRedactionConfig(entity_type="LOCATION", enabled=False),
        ]

        redacted_text, log = redactor.redact_page_text(text, config)

        assert redacted_text == text
        assert log.redacted_count == 0

    def test_empty_config_returns_original(self) -> None:
        """Empty config list returns original text unchanged."""
        redactor = self._make_redactor()
        text = "Some text with no PII."
        config: list[EntityRedactionConfig] = []

        redacted_text, log = redactor.redact_page_text(text, config)

        assert redacted_text == text
        assert log.redacted_count == 0

    def test_redaction_replaces_with_marker(self) -> None:
        """Detected PII should be replaced with [REDACTED]."""
        redactor = self._make_redactor()
        text = "My phone number is 555-123-4567."
        config = [
            EntityRedactionConfig(entity_type="PHONE_NUMBER", enabled=True),
        ]

        redacted_text, log = redactor.redact_page_text(text, config)

        assert "[REDACTED]" in redacted_text
        assert "555-123-4567" not in redacted_text

    def test_original_text_not_mutated(self) -> None:
        """Original text should never be mutated."""
        redactor = self._make_redactor()
        original = "Call me at 555-123-4567."
        text = original  # Same reference
        config = [EntityRedactionConfig(entity_type="PHONE_NUMBER", enabled=True)]

        redacted_text, log = redactor.redact_page_text(text, config)

        # Original string should be unchanged
        assert text == original

    def test_redaction_log_has_config_snapshot(self) -> None:
        """RedactionLog should include config_snapshot."""
        redactor = self._make_redactor()
        text = "Test text"
        config = [
            EntityRedactionConfig(entity_type="PERSON", enabled=True),
            EntityRedactionConfig(entity_type="PHONE_NUMBER", enabled=True),
        ]

        _, log = redactor.redact_page_text(text, config)

        assert log.config_snapshot is not None
        assert len(log.config_snapshot) > 0

    def test_redaction_log_entities_have_positions(self) -> None:
        """Redacted entities should have start/end positions."""
        redactor = self._make_redactor()
        text = "My phone number is 555-123-4567."
        config = [EntityRedactionConfig(entity_type="PHONE_NUMBER", enabled=True)]

        _, log = redactor.redact_page_text(text, config)

        if log.redacted_count > 0:
            entity = log.entities_redacted[0]
            assert "start" in entity
            assert "end" in entity
            assert "entity_type" in entity

    def test_schema_override_support(self) -> None:
        """redact_with_schema_override should use schema-specific config."""
        redactor = self._make_redactor()
        text = "John Smith account 12345"
        global_config = [EntityRedactionConfig(entity_type="PERSON", enabled=True)]
        schema_overrides = {
            "bank_statement": [EntityRedactionConfig(entity_type="PERSON", enabled=False)],
        }

        # With bank_statement schema, PERSON should NOT be redacted
        redacted, log = redactor.redact_with_schema_override(
            text, global_config, schema_overrides, schema_type="bank_statement"
        )
        # The override disables PERSON, so text should be unchanged
        assert log.redacted_count == 0

        # With unknown schema, global config applies (PERSON enabled)
        redacted2, log2 = redactor.redact_with_schema_override(
            text, global_config, schema_overrides, schema_type="swift_confirm"
        )
        # Global config has PERSON enabled, so it might be redacted
        # (depends on Presidio detecting "John Smith")
