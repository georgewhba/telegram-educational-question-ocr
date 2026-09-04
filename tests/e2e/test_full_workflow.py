"""End-to-End simulation of the complete business workflow.

Student -> Upload Image -> OCR -> Parser -> Quality Gate -> Canvas Rendering -> Teacher Delivery -> DB
-> Admin Panel -> DOCX/Excel Exports -> Scheduler Execution -> Audit Log
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram import Bot
from PIL import Image

from app.database.repositories import (
    AuditLogRepository,
    ScheduleRepository,
    SubmissionRepository,
    UserRepository,
)
from app.domain.enums import (
    DeliveryStatus,
    ExportFormat,
    ProcessingStatus,
    QualityGateResult,
)
from app.services.admin_service import AdminService
from app.services.export_service import ExportService
from app.services.file_service import FileService
from app.services.image_service import ImageService
from app.services.ocr_service import MockOCRProvider, OCRService
from app.services.parser_service import ParserService
from app.services.rendering_service import RenderingService
from app.services.scheduling_service import SchedulingService
from app.services.teacher_delivery_service import TeacherDeliveryService
from app.services.validation_service import ValidationService


@pytest.mark.asyncio
async def test_complete_e2e_workflow(session_factory, test_settings):
    # Setup mocks and services
    mock_bot = MagicMock(spec=Bot)
    mock_message = MagicMock()
    mock_message.message_id = 9999
    mock_bot.send_photo = AsyncMock(return_value=mock_message)
    mock_bot.send_document = AsyncMock(return_value=mock_message)

    file_service = FileService(test_settings)
    image_service = ImageService(test_settings)

    # Use deterministic OCR provider
    mock_ocr = MockOCRProvider(
        default_text=("ما هو العنصر الأكثر وفرة في الكون؟\nأ) الهيدروجين\nب) الهيليوم\nج) الأكسجين\nد) الكربون\n")
    )
    ocr_service = OCRService(test_settings, primary_provider=mock_ocr)
    parser_service = ParserService(test_settings)
    validation_service = ValidationService()
    rendering_service = RenderingService(test_settings)
    delivery_service = TeacherDeliveryService(mock_bot, test_settings)
    admin_service = AdminService(session_factory, test_settings, file_service)
    export_service = ExportService(test_settings)
    scheduler = SchedulingService(mock_bot, session_factory, test_settings, export_service, file_service)

    # ----------------------------------------------------
    # Phase 1: Student Submits Question Image
    # ----------------------------------------------------
    student_telegram_id = 555444333
    student_name = "أحمد خالد"

    # Register student
    async with session_factory() as session:
        user_repo = UserRepository(session)
        student = await user_repo.get_or_create(
            telegram_user_id=student_telegram_id,
            display_name=student_name,
            username="ahmed_khaled",
        )
        await session.commit()
        student_id = student.id

    # Simulate uploaded image
    job_id = file_service.generate_job_id()
    orig_path = file_service.get_original_path(job_id, "jpg")
    img = Image.new("RGB", (800, 600), color=(240, 240, 240))
    img.save(orig_path, format="JPEG")

    # Validate image
    val_res = image_service.validate_image_file(orig_path)
    assert val_res.is_valid is True

    # Record submission
    now_utc = datetime.now(timezone.utc)
    today = now_utc.astimezone(test_settings.tz).date()

    async with session_factory() as session:
        sub_repo = SubmissionRepository(session)
        await sub_repo.create_submission(
            job_id=job_id,
            user_id=student_id,
            submitted_at_utc=now_utc,
            business_date=today,
            original_file_path=str(orig_path),
        )
        await session.commit()

    # Preprocessing
    tmp_dir = file_service.get_isolated_tmp_dir(job_id)
    preproc_path = tmp_dir / "preproc.png"
    image_service.preprocess_image(orig_path, preproc_path, strategy="standard")
    assert preproc_path.exists()

    # OCR extraction
    ocr_result = await ocr_service.extract(preproc_path)
    assert "الهيدروجين" in ocr_result.raw_text

    # Normalization & Parsing
    parsed_payload = parser_service.parse(ocr_result.raw_text, job_id=job_id)
    assert parsed_payload is not None
    assert parsed_payload.option_a == "الهيدروجين"

    # Quality Gate
    eval_res = validation_service.evaluate(parsed_payload, ocr_confidence=ocr_result.confidence)
    assert eval_res.result == QualityGateResult.PASS

    # Template Rendering
    processed_path = file_service.get_processed_path(job_id)
    rendering_service.render_question(parsed_payload, processed_path)
    assert processed_path.exists()

    # Deliver to Teacher
    deliv_res = await delivery_service.deliver_processed_question(
        job_id=job_id,
        processed_image_path=processed_path,
        student_name=student_name,
        student_telegram_id=student_telegram_id,
        business_date=str(today),
        submitted_at=now_utc,
    )
    assert deliv_res.is_success is True

    # Update DB
    async with session_factory() as session:
        sub_repo = SubmissionRepository(session)
        await sub_repo.update_parsed_question(
            job_id=job_id,
            question_text=parsed_payload.question,
            option_a=parsed_payload.option_a,
            option_b=parsed_payload.option_b,
            option_c=parsed_payload.option_c,
            option_d=parsed_payload.option_d,
            processed_file_path=str(processed_path),
            processing_status=ProcessingStatus.READY,
        )
        await sub_repo.update_status(job_id, delivery_status=DeliveryStatus.DELIVERY_SUCCESS)
        await session.commit()

    # Cleanup tmp
    file_service.cleanup_tmp_dir(job_id)

    # ----------------------------------------------------
    # Phase 2: Admin Panel Inspection & Metrics
    # ----------------------------------------------------
    admin_id = 123456789  # in test_settings.admin_user_ids
    admin_service.verify_admin(admin_id)

    metrics = await admin_service.get_dashboard_metrics()
    assert metrics["today_total"] >= 1
    assert metrics["today_success"] >= 1
    assert metrics["today_delivered"] >= 1

    sub_list = await admin_service.list_submissions_paginated(page=1, per_page=10)
    assert len(sub_list["items"]) >= 1

    detail = await admin_service.get_submission_details(job_id)
    assert detail is not None
    assert detail.question_text == parsed_payload.question
    assert detail.delivery_status == DeliveryStatus.DELIVERY_SUCCESS

    # ----------------------------------------------------
    # Phase 3: Manual DOCX & Excel Exports
    # ----------------------------------------------------
    async with session_factory() as session:
        sub_repo = SubmissionRepository(session)
        today_submissions = await sub_repo.get_chronological_for_date_range(today, today, successful_only=True)

    export_id_docx = file_service.generate_export_id()
    export_id_xlsx = file_service.generate_export_id()

    docx_path = file_service.get_export_path(export_id_docx, "docx")
    xlsx_path = file_service.get_export_path(export_id_xlsx, "xlsx")

    export_service.generate_docx(today_submissions, docx_path, today, today, include_processed_images=True)
    export_service.generate_excel(today_submissions, xlsx_path, today, today)

    assert docx_path.exists()
    assert xlsx_path.exists()
    assert docx_path.stat().st_size > 0
    assert xlsx_path.stat().st_size > 0

    # ----------------------------------------------------
    # Phase 4: Persistent Daily Scheduler Execution & Idempotency
    # ----------------------------------------------------
    # Create active schedule
    async with session_factory() as session:
        sched_repo = ScheduleRepository(session)
        sched = await sched_repo.create(
            time_of_day="23:00",
            timezone_str=test_settings.TIMEZONE,
            format=ExportFormat.DOCX,
            content_config={},
            is_active=True,
        )
        await session.commit()
        schedule_id = sched.id

    # Execute schedule for today
    sched_result = await scheduler.execute_schedule(schedule_id, today)
    assert sched_result["status"] == "SUCCESS"

    # Idempotency verification: Executing again today must skip/report already completed
    second_run = await scheduler.execute_schedule(schedule_id, today)
    assert second_run["status"] == "ALREADY_COMPLETED"

    # ----------------------------------------------------
    # Phase 5: Audit Trail Verification
    # ----------------------------------------------------
    async with session_factory() as session:
        audit_repo = AuditLogRepository(session)
        logs = await audit_repo.list_logs(skip=0, limit=20)
        assert len(logs) >= 1
