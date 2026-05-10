"""Tests for the VLM verifier (post-filter)."""

from __future__ import annotations

from api.errors import ErrorCode
from pipeline.models import Token, VLMFieldResult
from pipeline.vlm.verifier import verify_vlm_result


class TestVerifyVLMResult:
    """Tests for verify_vlm_result()."""

    def test_null_value_returns_unverified(self) -> None:
        """VLM returning null should abstain with ERR_VLM_003."""
        result = VLMFieldResult(
            value=None,
            confidence=0.0,
            raw_response="",
            model_id="test-model",
        )
        tokens = [Token(text="hello", bbox=(0, 0, 10, 10), confidence=0.95)]

        outcome = verify_vlm_result(result, tokens)
        assert outcome.verified is False
        assert outcome.reason == ErrorCode.VLM_RETURNED_NULL

    def test_exact_match_in_token_stream(self) -> None:
        """Value found exactly in token stream should be verified."""
        result = VLMFieldResult(
            value="12345",
            confidence=0.85,
            raw_response="",
            model_id="test-model",
        )
        tokens = [
            Token(text="Account", bbox=(0, 0, 50, 10), confidence=0.95),
            Token(text="12345", bbox=(60, 0, 100, 10), confidence=0.95),
        ]

        outcome = verify_vlm_result(result, tokens)
        assert outcome.verified is True
        assert outcome.matched_token is not None
        assert outcome.matched_token.text == "12345"

    def test_value_not_in_stream_rejected(self) -> None:
        """Value not found in token stream should be rejected with ERR_VLM_004."""
        result = VLMFieldResult(
            value="NOTFOUND",
            confidence=0.85,
            raw_response="",
            model_id="test-model",
        )
        tokens = [
            Token(text="hello", bbox=(0, 0, 50, 10), confidence=0.95),
            Token(text="world", bbox=(60, 0, 100, 10), confidence=0.95),
        ]

        outcome = verify_vlm_result(result, tokens)
        assert outcome.verified is False
        assert outcome.reason == ErrorCode.VLM_VALUE_UNVERIFIABLE

    def test_fuzzy_match_above_threshold(self) -> None:
        """Similar value above threshold should be verified."""
        result = VLMFieldResult(
            value="1234.56",
            confidence=0.85,
            raw_response="",
            model_id="test-model",
        )
        tokens = [
            Token(text="1234.56", bbox=(0, 0, 50, 10), confidence=0.95),
        ]

        outcome = verify_vlm_result(result, tokens)
        assert outcome.verified is True

    def test_empty_token_stream(self) -> None:
        """Empty token stream should reject the value."""
        result = VLMFieldResult(
            value="hello",
            confidence=0.85,
            raw_response="",
            model_id="test-model",
        )

        outcome = verify_vlm_result(result, [])
        assert outcome.verified is False
        assert outcome.reason == ErrorCode.VLM_VALUE_UNVERIFIABLE

    def test_empty_value_returns_unverified(self) -> None:
        """Empty string value should be treated as null."""
        result = VLMFieldResult(
            value="",
            confidence=0.0,
            raw_response="",
            model_id="test-model",
        )
        tokens = [Token(text="hello", bbox=(0, 0, 10, 10), confidence=0.95)]

        outcome = verify_vlm_result(result, tokens)
        assert outcome.verified is False
        assert outcome.reason == ErrorCode.VLM_RETURNED_NULL

    def test_multi_token_window_match(self) -> None:
        """Multi-word value should match across adjacent tokens."""
        result = VLMFieldResult(
            value="john smith",
            confidence=0.85,
            raw_response="",
            model_id="test-model",
        )
        tokens = [
            Token(text="Name:", bbox=(0, 0, 30, 10), confidence=0.95),
            Token(text="John", bbox=(35, 0, 60, 10), confidence=0.95),
            Token(text="Smith", bbox=(65, 0, 100, 10), confidence=0.95),
        ]

        outcome = verify_vlm_result(result, tokens)
        assert outcome.verified is True

    def test_custom_threshold(self) -> None:
        """Custom threshold should be respected."""
        result = VLMFieldResult(
            value="hello",
            confidence=0.85,
            raw_response="",
            model_id="test-model",
        )
        tokens = [
            Token(text="helo", bbox=(0, 0, 50, 10), confidence=0.95),
        ]

        # With high threshold, should not match
        outcome = verify_vlm_result(result, tokens, fuzzy_threshold=0.99)
        assert outcome.verified is False

        # With lower threshold, should match
        outcome = verify_vlm_result(result, tokens, fuzzy_threshold=0.70)
        assert outcome.verified is True
