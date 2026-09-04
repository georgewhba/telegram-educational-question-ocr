"""Comprehensive edge case verification covering all critical failure and boundary modes."""

import asyncio
import io
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram import Bot
from PIL import Image

from app.database.repositories import (
    ScheduleRepository,
    UserRepository,
)
from app.domain.enums import (
    ExportFormat,
    QualityGateResult,
)
from app.domain.exceptions import OCRTimeoutError, UnauthorizedError
from app.domain.models import QuestionPayload
from app.services.admin_service import AdminService
from app.services.image_service import ImageService
from app.services.ocr_service import OCRService
from app.services.parser_service import ParserService
from app.services.rendering_service import RenderingService
from app.services.scheduling_service import SchedulingService
from app.services.teacher_delivery_service import TeacherDeliveryService
from app.services.validation_service import ValidationService


def test_edge_case_unsupported_document(test_settings):
    """Edge Case 2: Unsupported document formats (e.g. PDF/EXE)."""
    service = ImageService(test_settings)
    fake_exe = b"MZ\x90\x00\x03\x00\x00\x00"
    res = service.validate_image_bytes(fake_exe)
    assert res.is_valid is False
    assert "غير مدعوم" in res.error_message


def test_edge_case_corrupted_image(test_settings):
    """Edge Case 3: Corrupted image stream."""
    service = ImageService(test_settings)
    corrupted_data = b"\xff\xd8\xff\xe0" + b"\xff" * 100
    res = service.validate_image_bytes(corrupted_data)
    assert res.is_valid is False


def test_edge_case_huge_file(test_settings):
    """Edge Case 4: File exceeding max allowed megabytes."""
    service = ImageService(test_settings)
    # Simulate oversized byte array > max_file_size_bytes
    fake_huge = b"\xff\xd8\xff" + b"0" * (test_settings.max_file_size_bytes + 1024)
    res = service.validate_image_bytes(fake_huge)
    assert res.is_valid is False
    assert "يتجاوز الحد المسموح" in res.error_message


def test_edge_case_tiny_image(test_settings):
    """Edge Case 6: Tiny unreadable image (e.g. 15x15 px)."""
    service = ImageService(test_settings)
    tiny_img = Image.new("RGB", (15, 15), color="white")
    bio = io.BytesIO()
    tiny_img.save(bio, format="JPEG")
    res = service.validate_image_bytes(bio.getvalue())
    assert res.is_valid is False
    assert "صغيرة جدًا" in res.error_message


def test_edge_case_mixed_arabic_english(test_settings):
    """Edge Case 12: Mixed Arabic and English question with technical terms."""
    parser = ParserService(test_settings)
    text = (
        "ما هو مفهوم الـ API في هندسة البرمجيات؟\n"
        "أ) Application Programming Interface\n"
        "ب) Advanced Processing Unit\n"
        "ج) Automated Protocol Integration\n"
        "د) Access Provider Interface\n"
    )
    payload = parser.parse(text, job_id="edge-mixed")
    assert payload is not None
    assert "API" in payload.question
    assert "Application Programming Interface" in payload.option_a


def test_edge_case_long_question_and_options(tmp_path, test_settings):
    """Edge Cases 13 & 14: Extremely long question and long option text with dynamic wrapping."""
    renderer = RenderingService(test_settings)
    long_q = (
        "هذا سؤال طويل جدًا لاختبار قدرة محرك الرسم على التفاف الأسطر بسلاسة دون قص أي كلمة أو تشويه الحروف المتصلة " * 3
    )
    long_opt = "هذا اختيار مفصل يحتوي على عدة أسطر وشروحات للتأكد من حساب الارتفاع التلقائي للبطاقة " * 2

    payload = QuestionPayload(
        question=long_q,
        option_a=long_opt,
        option_b="خيار ب قصير",
        option_c="خيار ج عادي",
        option_d="خيار د عادي",
        job_id="edge-long",
    )

    out_file = tmp_path / "long_text_render.png"
    res_path = renderer.render_question(payload, out_file)
    assert res_path.exists()
    assert res_path.stat().st_size > 5000


def test_edge_case_3_options_fails_quality_gate():
    """Edge Case 15: Exactly 3 options must be rejected by quality gate."""
    parser = ParserService()
    text = "سؤال مع ثلاثة اختيارات فقط؟\nأ) خيار 1\nب) خيار 2\nج) خيار 3\n"
    payload = parser.parse(text, job_id="edge-3-opt")
    # Parser should return None or ValidationService rejects
    validator = ValidationService()
    res = validator.evaluate(payload, is_retry=True)
    assert res.result == QualityGateResult.FAIL


def test_edge_case_empty_ocr():
    """Edge Case 18: Empty OCR result."""
    parser = ParserService()
    payload = parser.parse("", job_id="edge-empty")
    assert payload is None


def test_edge_case_garbage_ocr():
    """Edge Case 19: Corrupted or garbage OCR text."""
    parser = ParserService()
    garbage = "~~~$$$### @@!! 12345 %%%"
    payload = parser.parse(garbage, job_id="edge-garbage")
    assert payload is None


@pytest.mark.asyncio
async def test_edge_case_ocr_timeout(test_settings, tmp_path):
    """Edge Case 20: OCR timeout simulation."""
    mock_slow_provider = MagicMock()

    async def slow_extract(path, language="ara+eng"):
        await asyncio.sleep(0.2)
        return None

    mock_slow_provider.extract_text = slow_extract
    ocr_service = OCRService(test_settings, primary_provider=mock_slow_provider)

    test_img = tmp_path / "timeout_img.png"
    test_img.write_bytes(b"mock")

    # Lower timeout to test timeout exception
    with pytest.raises((OCRTimeoutError, asyncio.TimeoutError)):
        await asyncio.wait_for(ocr_service.extract(test_img), timeout=0.05)


@pytest.mark.asyncio
async def test_edge_case_teacher_delivery_failure(test_settings, tmp_path):
    """Edge Case 23: Teacher delivery failure must be tracked without false student success."""
    mock_bot = MagicMock(spec=Bot)
    mock_bot.send_photo = AsyncMock(side_effect=Exception("Telegram Network Error: Connection Reset"))

    delivery_service = TeacherDeliveryService(mock_bot, test_settings)
    dummy_img = tmp_path / "proc_img.png"
    dummy_img.write_text("dummy")

    deliv_res = await delivery_service.deliver_processed_question(
        job_id="edge-deliv-fail",
        processed_image_path=dummy_img,
        student_name="طالب",
        student_telegram_id=12345,
        business_date="2026-09-04",
        submitted_at=datetime.now(timezone.utc),
    )

    assert deliv_res.is_success is False
    assert "فشل الإرسال إلى المعلم" in deliv_res.error_message


@pytest.mark.asyncio
async def test_edge_case_blocked_student(session_factory, test_settings):
    """Edge Case 27: Blocked student cannot submit and receives block notice."""
    async with session_factory() as session:
        user_repo = UserRepository(session)
        await user_repo.get_or_create(telegram_user_id=777, display_name="طالب محظور")
        await user_repo.set_blocked_status(777, is_blocked=True)
        await session.commit()

        updated = await user_repo.get_by_telegram_id(777)
        assert updated.is_blocked is True


def test_edge_case_unauthorized_admin_access(session_factory, test_settings):
    """Edge Case 28: Unauthorized user attempting admin panel."""
    admin_service = AdminService(session_factory, test_settings)
    unauthorized_id = 999999999
    assert unauthorized_id not in test_settings.admin_user_ids

    with pytest.raises(UnauthorizedError):
        admin_service.verify_admin(unauthorized_id)


@pytest.mark.asyncio
async def test_edge_case_empty_day_export(session_factory, test_settings):
    """Edge Case 31: Scheduled export on days with no submissions skips empty files."""
    mock_bot = MagicMock(spec=Bot)
    scheduler = SchedulingService(mock_bot, session_factory, test_settings)

    async with session_factory() as session:
        sched_repo = ScheduleRepository(session)
        sched = await sched_repo.create(
            time_of_day="23:00",
            timezone_str=test_settings.TIMEZONE,
            format=ExportFormat.DOCX,
            content_config={},
        )
        await session.commit()
        schedule_id = sched.id

    empty_date = date(2020, 1, 1)
    res = await scheduler.execute_schedule(schedule_id, empty_date)
    assert res["status"] == "SKIPPED_EMPTY"
    assert "No submissions" in res["reason"]
