"""VLM result verifier — post-filter for VLM-extracted values.

Checks that VLM-extracted values exist in the original unredacted token stream
using fuzzy matching (threshold 0.85). Rejects values that cannot be grounded
in the source document.
"""

from __future__ import annotations

from difflib import SequenceMatcher

import structlog

from api.errors import ErrorCode
from pipeline.models import Token, VLMFieldResult, VerificationOutcome

logger = structlog.get_logger()

# Default fuzzy matching threshold for VLM verification
DEFAULT_FUZZY_THRESHOLD = 0.85


def verify_vlm_result(
    vlm_result: VLMFieldResult,
    token_stream: list[Token],
    fuzzy_threshold: float = DEFAULT_FUZZY_THRESHOLD,
) -> VerificationOutcome:
    """Verify a VLM-extracted value against the unredacted token stream.

    Rules:
    - If VLM returns null → abstain with ERR_VLM_003
    - If value found in token stream (fuzzy >= threshold) → verified
    - If value not found → reject with ERR_VLM_004

    Args:
        vlm_result: The VLM extraction result to verify.
        token_stream: All tokens from the unredacted document.
        fuzzy_threshold: Minimum SequenceMatcher ratio for a match.

    Returns:
        VerificationOutcome indicating whether the value was verified.
    """
    # VLM returned null — abstain with ERR_VLM_003
    if vlm_result.value is None:
        logger.info(
            "vlm.verified",
            outcome="abstain",
            reason=ErrorCode.VLM_RETURNED_NULL,
        )
        return VerificationOutcome(
            verified=False,
            reason=ErrorCode.VLM_RETURNED_NULL,
        )

    # Normalise the VLM value for comparison
    normalised_value = _normalise_for_comparison(vlm_result.value)

    if not normalised_value:
        logger.info(
            "vlm.verified",
            outcome="abstain",
            reason=ErrorCode.VLM_RETURNED_NULL,
        )
        return VerificationOutcome(
            verified=False,
            reason=ErrorCode.VLM_RETURNED_NULL,
        )

    # Search token stream for a fuzzy match
    for token in token_stream:
        token_normalised = _normalise_for_comparison(token.text)
        if not token_normalised:
            continue

        ratio = SequenceMatcher(None, normalised_value, token_normalised).ratio()
        if ratio >= fuzzy_threshold:
            logger.info(
                "vlm.verified",
                outcome="verified",
                matched_token=token.text,
                ratio=ratio,
            )
            return VerificationOutcome(
                verified=True,
                reason=None,
                matched_token=token,
                provenance={
                    "page": 0,  # Token doesn't carry page info directly
                    "bbox": list(token.bbox),
                    "source": "vlm",
                    "extraction_rule": f"bedrock_{vlm_result.model_id}",
                },
            )

    # Also try matching against concatenated token windows
    # (VLM might return multi-token values like "John Smith" or "1,234.56")
    match = _search_token_windows(normalised_value, token_stream, fuzzy_threshold)
    if match is not None:
        logger.info(
            "vlm.verified",
            outcome="verified",
            matched_window=True,
        )
        return match

    # Final fallback: check if the value appears as a substring in the full document text
    full_text = " ".join(_normalise_for_comparison(t.text) for t in token_stream if t.text)
    if normalised_value in full_text:
        logger.info(
            "vlm.verified",
            outcome="verified",
            matched_substring=True,
        )
        return VerificationOutcome(
            verified=True,
            reason=None,
            matched_token=token_stream[0] if token_stream else None,
            provenance={
                "page": 1,
                "bbox": list(token_stream[0].bbox) if token_stream else [0, 0, 0, 0],
                "source": "vlm",
                "extraction_rule": f"bedrock_{vlm_result.model_id}",
            },
        )

    # Value not found in token stream — reject with ERR_VLM_004
    logger.info(
        "vlm.verified",
        outcome="rejected",
        reason=ErrorCode.VLM_VALUE_UNVERIFIABLE,
        value=vlm_result.value,
    )
    return VerificationOutcome(
        verified=False,
        reason=ErrorCode.VLM_VALUE_UNVERIFIABLE,
    )


def _search_token_windows(
    normalised_value: str,
    token_stream: list[Token],
    fuzzy_threshold: float,
) -> VerificationOutcome | None:
    """Search for multi-token matches by sliding a window over the token stream.

    Concatenates adjacent tokens and checks for fuzzy match.

    Args:
        normalised_value: The normalised VLM value to search for.
        token_stream: The token stream to search.
        fuzzy_threshold: Minimum ratio for a match.

    Returns:
        VerificationOutcome if found, None otherwise.
    """
    # Try windows of 2-5 tokens
    for window_size in range(2, min(6, len(token_stream) + 1)):
        for i in range(len(token_stream) - window_size + 1):
            window_tokens = token_stream[i : i + window_size]
            window_text = " ".join(
                _normalise_for_comparison(t.text) for t in window_tokens
            )

            ratio = SequenceMatcher(None, normalised_value, window_text).ratio()
            if ratio >= fuzzy_threshold:
                # Use the first token's bbox as provenance
                first_token = window_tokens[0]
                return VerificationOutcome(
                    verified=True,
                    reason=None,
                    matched_token=first_token,
                    provenance={
                        "page": 0,
                        "bbox": list(first_token.bbox),
                        "source": "vlm",
                        "extraction_rule": "bedrock_window_match",
                    },
                )

    return None


def _normalise_for_comparison(value: str) -> str:
    """Normalise a string for fuzzy comparison.

    Strips whitespace, lowercases, and removes common formatting noise.
    """
    if not value:
        return ""
    return value.strip().lower()
