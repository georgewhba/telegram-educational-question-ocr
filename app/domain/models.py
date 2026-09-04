"""Pydantic domain models and data transfer objects."""

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import ExportFormat, QualityGateResult


class QuestionPayload(BaseModel):
    """Structured question and 4 choices extracted from OCR."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question: str = Field(..., min_length=2, description="The main question text")
    option_a: str = Field(..., min_length=1, description="First option (أ / A / 1)")
    option_b: str = Field(..., min_length=1, description="Second option (ب / B / 2)")
    option_c: str = Field(..., min_length=1, description="Third option (ج / C / 3)")
    option_d: str = Field(..., min_length=1, description="Fourth option (د / D / 4)")
    language: str | None = Field(default="ar", description="Detected or primary language")
    confidence: float | None = Field(default=None, ge=0.0, le=1.0, description="Confidence score")
    job_id: str = Field(..., description="Unique job identifier")

    @property
    def options(self) -> list[str]:
        return [self.option_a, self.option_b, self.option_c, self.option_d]


class ImageValidationResult(BaseModel):
    """Result of untrusted image validation."""

    model_config = ConfigDict(extra="forbid")

    is_valid: bool
    width: int = 0
    height: int = 0
    mime_type: str = ""
    file_size_bytes: int = 0
    error_message: str | None = None


class OCRResult(BaseModel):
    """Result of an OCR extraction step."""

    model_config = ConfigDict(extra="forbid")

    raw_text: str
    normalized_text: str
    confidence: float | None = None
    language: str = "ar"
    provider: str
    processing_time_ms: int = 0


class QualityGateEvaluation(BaseModel):
    """Evaluation result of the quality gate checks."""

    model_config = ConfigDict(extra="forbid")

    result: QualityGateResult
    reason: str
    cleaned_payload: QuestionPayload | None = None


class DeliveryResult(BaseModel):
    """Result of a Telegram delivery attempt."""

    model_config = ConfigDict(extra="forbid")

    is_success: bool
    telegram_message_id: int | None = None
    error_message: str | None = None
    delivered_at: datetime | None = None


class ExportRequest(BaseModel):
    """Specification for manual or scheduled export generation."""

    model_config = ConfigDict(extra="forbid")

    date_from: date
    date_to: date
    format: ExportFormat = ExportFormat.DOCX
    recipient_ids: list[int] = Field(default_factory=list)
    include_processed_image: bool = True
    include_original_image: bool = False
    export_type: str = "MANUAL"
    created_by: int | None = None
    content_config: dict[str, Any] = Field(default_factory=dict)
