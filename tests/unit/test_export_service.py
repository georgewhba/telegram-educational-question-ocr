"""Unit tests for DOCX and XLSX export generation."""

from datetime import datetime, timezone

from app.database.models import Submission, User
from app.domain.enums import DeliveryStatus, ProcessingStatus, UserRole
from app.services.export_service import ExportService


def test_generate_docx_and_excel(tmp_path, test_settings):
    export_service = ExportService(test_settings)

    dummy_user = User(
        id=1,
        telegram_user_id=123456789,
        display_name="أحمد محمد",
        username="ahmed",
        role=UserRole.STUDENT,
        is_blocked=False,
    )

    now = datetime.now(timezone.utc)
    today = now.date()

    sub1 = Submission(
        id=1,
        job_id="job-001",
        user_id=1,
        user=dummy_user,
        submitted_at_utc=now,
        business_date=today,
        original_file_path="",
        processed_file_path="",
        question_text="ما هو أول أركان الإسلام؟",
        option_a="الشهادتان",
        option_b="الصلاة",
        option_c="الزكاة",
        option_d="الصوم",
        processing_status=ProcessingStatus.READY,
        delivery_status=DeliveryStatus.DELIVERY_SUCCESS,
    )

    docx_path = tmp_path / "questions_test.docx"
    xlsx_path = tmp_path / "questions_test.xlsx"

    res_docx = export_service.generate_docx([sub1], docx_path, today, today, include_processed_images=False)
    assert res_docx.exists()
    assert res_docx.stat().st_size > 0

    res_xlsx = export_service.generate_excel([sub1], xlsx_path, today, today)
    assert res_xlsx.exists()
    assert res_xlsx.stat().st_size > 0
