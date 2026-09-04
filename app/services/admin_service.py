"""Admin service orchestrating dashboard metrics, searches, submissions, exports, and health checks."""

from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config.settings import Settings, get_settings
from app.database.models import Submission
from app.database.repositories import (
    AuditLogRepository,
    ExportRepository,
    RecipientRepository,
    ScheduleRepository,
    SubmissionRepository,
    UserRepository,
)
from app.domain.enums import (
    AdminAction,
    DeliveryStatus,
    ProcessingStatus,
    QualityGateResult,
)
from app.domain.exceptions import UnauthorizedError
from app.services.export_service import ExportService
from app.services.file_service import FileService
from app.services.image_service import ImageService
from app.services.ocr_service import OCRService
from app.services.parser_service import ParserService
from app.services.rendering_service import RenderingService
from app.services.validation_service import ValidationService


class AdminService:
    def __init__(
        self,
        session_factory: async_sessionmaker,
        settings: Settings | None = None,
        file_service: FileService | None = None,
        export_service: ExportService | None = None,
    ):
        self.session_factory = session_factory
        self.settings = settings or get_settings()
        self.file_service = file_service or FileService(self.settings)
        self.export_service = export_service or ExportService(self.settings)

    def verify_admin(self, telegram_user_id: int) -> None:
        """Verify that the user is an authorized admin using their numeric Telegram user ID."""
        if telegram_user_id not in self.settings.admin_user_ids:
            raise UnauthorizedError("غير مصرح لك بالوصول إلى لوحة الإدارة.")

    async def get_dashboard_metrics(self) -> dict[str, Any]:
        """Fetch real-time operational metrics for the admin dashboard."""
        today = datetime.now(self.settings.tz).date()
        async with self.session_factory() as session:
            sub_repo = SubmissionRepository(session)
            user_repo = UserRepository(session)
            sched_repo = ScheduleRepository(session)

            stats = await sub_repo.get_statistics(today)
            stats["blocked_students"] = await user_repo.count_students(is_blocked=True)
            active_schedules = await sched_repo.get_active()
            stats["active_schedules_count"] = len(active_schedules)
            return stats

    async def list_submissions_paginated(
        self,
        page: int = 1,
        per_page: int = 8,
        date_from: date | None = None,
        date_to: date | None = None,
        processing_status: ProcessingStatus | None = None,
        delivery_status: DeliveryStatus | None = None,
        search_term: str | None = None,
    ) -> dict[str, Any]:
        """Fetch paginated submissions with optional filters."""
        skip = (max(1, page) - 1) * per_page
        async with self.session_factory() as session:
            sub_repo = SubmissionRepository(session)
            items = await sub_repo.list_submissions(
                skip=skip,
                limit=per_page,
                date_from=date_from,
                date_to=date_to,
                processing_status=processing_status,
                delivery_status=delivery_status,
                search_term=search_term,
            )
            total = await sub_repo.count_submissions(
                date_from=date_from,
                date_to=date_to,
                processing_status=processing_status,
                delivery_status=delivery_status,
            )

        total_pages = max(1, (total + per_page - 1) // per_page)
        return {
            "items": items,
            "page": page,
            "per_page": per_page,
            "total_items": total,
            "total_pages": total_pages,
        }

    async def get_submission_details(self, job_id: str) -> Submission | None:
        """Fetch full details for a submission including processing attempts and user."""
        async with self.session_factory() as session:
            sub_repo = SubmissionRepository(session)
            return await sub_repo.get_by_job_id(job_id)

    async def set_student_blocked(self, admin_id: int, student_telegram_id: int, is_blocked: bool) -> bool:
        """Block or unblock a student."""
        self.verify_admin(admin_id)
        async with self.session_factory() as session:
            user_repo = UserRepository(session)
            audit_repo = AuditLogRepository(session)

            success = await user_repo.set_blocked_status(student_telegram_id, is_blocked)
            if success:
                action = (
                    AdminAction.ADMIN_BLOCK_STUDENT.value if is_blocked else AdminAction.ADMIN_UNBLOCK_STUDENT.value
                )
                await audit_repo.log_action(
                    admin_user_id=admin_id,
                    action=action,
                    target_type="user",
                    target_id=str(student_telegram_id),
                )
                await session.commit()
            return success

    async def delete_submission(self, admin_id: int, job_id: str) -> bool:
        """Permanently delete a submission and its associated processed files."""
        self.verify_admin(admin_id)
        async with self.session_factory() as session:
            sub_repo = SubmissionRepository(session)
            audit_repo = AuditLogRepository(session)

            submission = await sub_repo.get_by_job_id(job_id)
            if not submission:
                return False

            # Delete processed file if exists
            if submission.processed_file_path:
                p = Path(submission.processed_file_path)
                if p.exists():
                    p.unlink(missing_ok=True)

            deleted = await sub_repo.delete_submission(job_id)
            if deleted:
                await audit_repo.log_action(
                    admin_user_id=admin_id,
                    action=AdminAction.ADMIN_DELETE_SUBMISSION.value,
                    target_type="submission",
                    target_id=job_id,
                )
                await session.commit()
            return deleted

    async def get_system_health(self) -> dict[str, Any]:
        """Perform diagnostics on DB, Storage, and System components."""
        db_ok = False
        storage_ok = False

        # 1. Test database
        try:
            async with self.session_factory() as session:
                user_repo = UserRepository(session)
                await user_repo.count_students()
                db_ok = True
        except Exception:
            db_ok = False

        # 2. Test storage writeability
        try:
            test_file = self.settings.tmp_dir / "health_check.tmp"
            test_file.write_text("health")
            test_file.unlink()
            storage_ok = True
        except Exception:
            storage_ok = False

        return {
            "bot_running": True,
            "database": "🟢 متصلة" if db_ok else "🔴 غير متصلة",
            "storage": "🟢 متاح" if storage_ok else "🔴 غير متاح",
            "timezone": self.settings.TIMEZONE,
            "ocr_provider": self.settings.OCR_PROVIDER,
            "environment": self.settings.ENVIRONMENT,
        }

    async def get_failed_submissions(self, skip: int = 0, limit: int = 10) -> list[Submission]:
        """Fetch failed submissions for the Error Center."""
        async with self.session_factory() as session:
            sub_repo = SubmissionRepository(session)
            return await sub_repo.list_submissions(
                skip=skip,
                limit=limit,
                processing_status=ProcessingStatus.FAILED,
            )

    async def list_exports_paginated(self, page: int = 1, per_page: int = 6) -> dict[str, Any]:
        """Fetch paginated exported documents for the archive."""
        skip = (max(1, page) - 1) * per_page
        async with self.session_factory() as session:
            export_repo = ExportRepository(session)
            items = await export_repo.list_exports(skip=skip, limit=per_page)
            total = await export_repo.count_exports()

        total_pages = max(1, (total + per_page - 1) // per_page)
        return {
            "items": items,
            "page": page,
            "per_page": per_page,
            "total_items": total,
            "total_pages": total_pages,
        }

    async def list_audit_logs_paginated(self, page: int = 1, per_page: int = 8) -> dict[str, Any]:
        """Fetch paginated audit trail logs."""
        skip = (max(1, page) - 1) * per_page
        async with self.session_factory() as session:
            audit_repo = AuditLogRepository(session)
            items = await audit_repo.list_logs(skip=skip, limit=per_page)
            total = await audit_repo.count_logs()

        total_pages = max(1, (total + per_page - 1) // per_page)
        return {
            "items": items,
            "page": page,
            "per_page": per_page,
            "total_items": total,
            "total_pages": total_pages,
        }

    async def reprocess_submission(self, admin_id: int, job_id: str) -> tuple[bool, str]:
        """Re-run preprocessing, OCR extraction, parsing, and rendering for an existing submission."""
        self.verify_admin(admin_id)
        sub = await self.get_submission_details(job_id)
        if not sub:
            return False, "السؤال غير موجود في قاعدة البيانات."

        if not sub.original_file_path or not Path(sub.original_file_path).exists():
            return False, "ملف الصورة الأصلية غير متوفر لإعادة المعالجة."

        orig_path = Path(sub.original_file_path)
        tmp_dir = self.file_service.get_isolated_tmp_dir(job_id)

        image_service = ImageService(self.settings)
        ocr_service = OCRService(self.settings)
        parser_service = ParserService(self.settings)
        validation_service = ValidationService()
        rendering_service = RenderingService(self.settings)

        payload = None
        last_reason = "لم يتم التعرف على المحتوى"
        current_attempts_count = len(sub.attempts)

        for attempt_idx, strategy in enumerate(["standard", "enhanced_contrast"], start=1):
            preproc_path = tmp_dir / f"reproc_{attempt_idx}.png"
            image_service.preprocess_image(orig_path, preproc_path, strategy=strategy)

            ocr_res = await ocr_service.extract(preproc_path)
            candidate_payload = parser_service.parse(ocr_res.raw_text, job_id=job_id)

            eval_res = validation_service.evaluate(
                candidate_payload,
                ocr_confidence=ocr_res.confidence,
                is_retry=(attempt_idx > 1),
            )

            async with self.session_factory() as session:
                sub_repo = SubmissionRepository(session)
                await sub_repo.record_attempt(
                    submission_id=sub.id,
                    attempt_number=current_attempts_count + attempt_idx,
                    stage=f"REPROCESS_{strategy}",
                    status=eval_res.result.value,
                    safe_error_message=eval_res.reason if eval_res.result != QualityGateResult.PASS else None,
                )
                await session.commit()

            if eval_res.result == QualityGateResult.PASS and eval_res.cleaned_payload:
                payload = eval_res.cleaned_payload
                break
            else:
                last_reason = eval_res.reason or last_reason

        self.file_service.cleanup_tmp_dir(job_id)

        if payload is None:
            async with self.session_factory() as session:
                sub_repo = SubmissionRepository(session)
                audit_repo = AuditLogRepository(session)
                await sub_repo.update_status(job_id, processing_status=ProcessingStatus.FAILED)
                await audit_repo.log_action(
                    admin_user_id=admin_id,
                    action=AdminAction.ADMIN_REPROCESS_SUBMISSION.value,
                    target_type="submission",
                    target_id=job_id,
                    metadata_safe={"success": False, "reason": last_reason},
                )
                await session.commit()
            return False, f"فشلت إعادة المعالجة: {last_reason}"

        # Render deterministic output template
        processed_path = self.file_service.get_processed_path(job_id)
        rendering_service.render_question(payload, processed_path)

        async with self.session_factory() as session:
            sub_repo = SubmissionRepository(session)
            audit_repo = AuditLogRepository(session)
            await sub_repo.update_parsed_question(
                job_id=job_id,
                question_text=payload.question,
                option_a=payload.option_a,
                option_b=payload.option_b,
                option_c=payload.option_c,
                option_d=payload.option_d,
                processed_file_path=str(processed_path),
                processing_status=ProcessingStatus.READY,
            )
            await audit_repo.log_action(
                admin_user_id=admin_id,
                action=AdminAction.ADMIN_REPROCESS_SUBMISSION.value,
                target_type="submission",
                target_id=job_id,
                metadata_safe={"success": True},
            )
            await session.commit()

        return True, "تمت إعادة معالجة السؤال وتحديث القالب بنجاح!"

    async def toggle_schedule(self, admin_id: int, schedule_id: int) -> bool:
        """Toggle active status for a recurring export schedule."""
        self.verify_admin(admin_id)
        async with self.session_factory() as session:
            sched_repo = ScheduleRepository(session)
            audit_repo = AuditLogRepository(session)
            new_state = await sched_repo.toggle_active(schedule_id)
            await audit_repo.log_action(
                admin_user_id=admin_id,
                action="ADMIN_TOGGLE_SCHEDULE",
                target_type="schedule",
                target_id=str(schedule_id),
                metadata_safe={"is_active": new_state},
            )
            await session.commit()
            return new_state

    async def toggle_recipient(self, admin_id: int, recipient_id: int) -> bool:
        """Toggle active status for a recipient."""
        self.verify_admin(admin_id)
        async with self.session_factory() as session:
            recip_repo = RecipientRepository(session)
            audit_repo = AuditLogRepository(session)
            new_state = await recip_repo.toggle_active(recipient_id)
            await audit_repo.log_action(
                admin_user_id=admin_id,
                action="ADMIN_TOGGLE_RECIPIENT",
                target_type="recipient",
                target_id=str(recipient_id),
                metadata_safe={"is_active": new_state},
            )
            await session.commit()
            return new_state
