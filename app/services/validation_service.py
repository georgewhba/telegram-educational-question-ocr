"""Quality gate service for extracted question and options verification."""

from app.domain.enums import QualityGateResult
from app.domain.models import QualityGateEvaluation, QuestionPayload


class ValidationService:
    def evaluate(
        self,
        payload: QuestionPayload | None,
        ocr_confidence: float | None = None,
        is_retry: bool = False,
    ) -> QualityGateEvaluation:
        """Run quality gate checks on the extracted question structure."""
        if payload is None:
            if not is_retry:
                return QualityGateEvaluation(
                    result=QualityGateResult.RETRY,
                    reason="لم يتم العثور على سؤال و4 اختيارات مكتملة بالهيكل المحدد.",
                )
            return QualityGateEvaluation(
                result=QualityGateResult.FAIL,
                reason="تعذر استخراج سؤال و4 اختيارات واضحة بعد محاولات المعالجة.",
            )

        # 1. Question non-empty check
        q = payload.question.strip()
        if len(q) < 3:
            return QualityGateEvaluation(
                result=QualityGateResult.FAIL,
                reason="نص السؤال قصير جدًا أو غير مكتمل.",
            )

        # 2. Options non-empty and minimum length check
        opts = [
            payload.option_a.strip(),
            payload.option_b.strip(),
            payload.option_c.strip(),
            payload.option_d.strip(),
        ]
        if any(len(opt) == 0 for opt in opts):
            return QualityGateEvaluation(
                result=QualityGateResult.FAIL,
                reason="أحد الاختيارات الأربعة فارغ أو مفقود.",
            )

        # 3. Duplicate check (all 4 choices cannot be identical placeholder text)
        if len(set(opts)) == 1:
            return QualityGateEvaluation(
                result=QualityGateResult.FAIL,
                reason="جميع الاختيارات متطابقة أو مكررة.",
            )

        # 4. OCR Confidence Gate
        if ocr_confidence is not None and ocr_confidence < 0.30 and not is_retry:
            return QualityGateEvaluation(
                result=QualityGateResult.RETRY,
                reason=f"دقة التعرف على النص منخفضة ({int(ocr_confidence * 100)}%).",
                cleaned_payload=payload,
            )

        # 5. Length sanity check (e.g. max question length 2000 chars, max option 500 chars)
        if len(q) > 2500 or any(len(opt) > 1000 for opt in opts):
            return QualityGateEvaluation(
                result=QualityGateResult.FAIL,
                reason="حجم النص المستخرج يتجاوز الحدود المعقولة للأسئلة التعليمية.",
            )

        return QualityGateEvaluation(
            result=QualityGateResult.PASS,
            reason="اجتاز التحقق بنجاح.",
            cleaned_payload=payload,
        )
