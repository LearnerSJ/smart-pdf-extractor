"""Contract tests for the feedback CorrectionRequest model.

The frontend modal sends `corrected_value`/`original_value`; older clients send
`correct_value`. The model must accept both, or submissions 422 (the bug this
guards against).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from api.routes.feedback import CorrectionRequest


def test_accepts_modal_payload() -> None:
    req = CorrectionRequest.model_validate(
        {"field_name": "currency", "original_value": "SGD", "corrected_value": "USD"}
    )
    assert req.field_name == "currency"
    assert req.corrected_value == "USD"
    assert req.original_value == "SGD"


def test_accepts_legacy_correct_value_alias() -> None:
    req = CorrectionRequest.model_validate(
        {"field_name": "currency", "correct_value": "USD"}
    )
    assert req.corrected_value == "USD"


def test_requires_a_corrected_value() -> None:
    with pytest.raises(ValidationError):
        CorrectionRequest.model_validate({"field_name": "currency"})
