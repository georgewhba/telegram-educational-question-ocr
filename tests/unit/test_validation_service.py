"""Unit tests for the Quality Gate validation service."""

import pytest

from app.domain.enums import QualityGateResult
from app.domain.models import QuestionPayload
from app.services.validation_service import ValidationService


def test_quality_gate_pass(sample_question_payload):
    validator = ValidationService()
    res = validator.evaluate(sample_question_payload, ocr_confidence=0.95)
    assert res.result == QualityGateResult.PASS
    assert res.cleaned_payload is not None


def test_quality_gate_empty_payload():
    validator = ValidationService()
    res = validator.evaluate(None, is_retry=False)
    assert res.result == QualityGateResult.RETRY

    res_retry = validator.evaluate(None, is_retry=True)
    assert res_retry.result == QualityGateResult.FAIL


def test_quality_gate_empty_option():
    from pydantic import ValidationError as PydanticValidationError

    with pytest.raises(PydanticValidationError):
        QuestionPayload(
            question="ما هو السؤال؟",
            option_a="خيار أ",
            option_b="",  # Empty string rejected by min_length=1
            option_c="خيار ج",
            option_d="خيار د",
            job_id="job-val-1",
        )


def test_quality_gate_duplicate_options():
    validator = ValidationService()
    payload = QuestionPayload(
        question="سؤال مكرر؟",
        option_a="نفس الخيار",
        option_b="نفس الخيار",
        option_c="نفس الخيار",
        option_d="نفس الخيار",
        job_id="job-val-2",
    )
    res = validator.evaluate(payload)
    assert res.result == QualityGateResult.FAIL
    assert "متطابقة" in res.reason


def test_quality_gate_low_confidence_triggers_retry(sample_question_payload):
    validator = ValidationService()
    res = validator.evaluate(sample_question_payload, ocr_confidence=0.20, is_retry=False)
    assert res.result == QualityGateResult.RETRY
