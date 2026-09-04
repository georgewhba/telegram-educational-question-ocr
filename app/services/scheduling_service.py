"""Persistent, timezone-aware scheduling service for daily recurring exports."""

import asyncio
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from aiogram import Bot
from aiogram.types import FSInputFile
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config.settings import Settings, get_settings
from app.database.models import Recipient
from app.database.repositories import (
    AuditLogRepository,
    ExportRepository,
    RecipientRepository,
    ScheduleRepository,
    SubmissionRepository,
)
from app.domain.enums import AdminAction, DeliveryStatus, ExportFormat, ExportStatus
from app.services.export_service import ExportService
from app.services.file_service import FileService


class SchedulingService:
    def __init__(
        self,
        bot: Bot,
        session_factory: async_sessionmaker,
        settings: Settings | None = None,
        export_service: ExportService | None = None,
        file_service: FileService | None = None,
    ):
        self.bot = bot
        self.session_factory = session_factory
        self.settings = settings or get_settings()
        self.export_service = export_service or ExportService(self.settings)
        self.file_service = file_service or FileService(self.settings)
        self._running = False
        self._task: asyncio.Task | None = None

    def start(self):
        """Start the background scheduler evaluation loop."""
        if not self._running:
            self._running = True
            self._task = asyncio.create_task(self._scheduler_loop())

    async def stop(self):
        """Stop the background scheduler loop gracefully."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _scheduler_loop(self):
        """Periodic loop checking every 30 seconds for scheduled triggers."""
        while self._running:
            try:
                await self.evaluate_schedules()
            except asyncio.CancelledError:
                break
            except Exception as e:
                # Catch any unexpected error in the loop to avoid dying
                print(f"[Scheduler Loop Error] {e}")
            await asyncio.sleep(30)

    async def evaluate_schedules(self, specific_date: date | None = None):
        """Check all active schedules and execute any due for the current business time."""
        now_utc = datetime.now(timezone.utc)
        local_now = now_utc.astimezone(self.settings.tz)
        current_time_str = local_now.strftime("%H:%M")
        current_business_date = specific_date or local_now.date()

        async with self.session_factory() as session:
            schedule_repo = ScheduleRepository(session)
            active_schedules = await schedule_repo.get_active()

            for sched in active_schedules:
                # Trigger if current time matches scheduled time
                if sched.time_of_day == current_time_str or specific_date is not None:
                    # Check idempotency: did we already execute this schedule today?
                    existing_exec = await schedule_repo.get_execution(sched.id, current_business_date)
                    if existing_exec and existing_exec.status in ("SUCCESS", "SKIPPED_EMPTY"):
                        continue  # Already executed successfully today

                    # Execute the schedule
                    await self.execute_schedule(sched.id, current_business_date)

    async def execute_schedule(self, schedule_id: int, business_date: date) -> dict[str, Any]:
        """Execute a scheduled export job idempotently."""
        async with self.session_factory() as session:
            schedule_repo = ScheduleRepository(session)
            submission_repo = SubmissionRepository(session)
            export_repo = ExportRepository(session)
            recipient_repo = RecipientRepository(session)
            audit_repo = AuditLogRepository(session)

            schedule = await schedule_repo.get_by_id(schedule_id)
            if not schedule:
                return {"status": "ERROR", "reason": "Schedule not found"}

            # Idempotency lock: check and record execution start
            existing_exec = await schedule_repo.get_execution(schedule_id, business_date)
            if existing_exec and existing_exec.status == "SUCCESS":
                return {"status": "ALREADY_COMPLETED", "execution_id": existing_exec.id}

            if not existing_exec:
                execution = await schedule_repo.record_execution_start(schedule_id, business_date)
                await session.commit()
            else:
                execution = existing_exec

            execution_id = execution.id

        # Query submissions for business date
        async with self.session_factory() as session:
            submission_repo = SubmissionRepository(session)
            submissions = await submission_repo.get_chronological_for_date_range(
                date_from=business_date, date_to=business_date, successful_only=True
            )

        # Handle empty day
        if len(submissions) == 0 and self.settings.SKIP_EMPTY_DAYS:
            async with self.session_factory() as session:
                schedule_repo = ScheduleRepository(session)
                await schedule_repo.record_execution_complete(execution_id, status="SKIPPED_EMPTY")
                await session.commit()
            return {"status": "SKIPPED_EMPTY", "reason": "No submissions found for date"}

        # Get active recipients
        async with self.session_factory() as session:
            recipient_repo = RecipientRepository(session)
            recipients = await recipient_repo.get_all(active_only=True)

        if not recipients:
            # Fallback to teacher chat ID if no explicit recipients configured
            teacher_chat = self.settings.TEACHER_CHAT_ID
            recipients = [Recipient(id=0, telegram_chat_id=teacher_chat, name="المعلم الأساسي", is_active=True)]

        # Generate Export
        export_id = self.file_service.generate_export_id()
        fmt = schedule.format

        # Create export record in DB
        async with self.session_factory() as session:
            export_repo = ExportRepository(session)
            await export_repo.create(
                export_id=export_id,
                export_type="SCHEDULED",
                date_from=business_date,
                date_to=business_date,
                format=fmt,
                content_config={"schedule_id": schedule_id},
                created_by=None,
                recipient_ids=[r.id for r in recipients if r.id > 0],
            )
            await session.commit()

        ext = "docx" if fmt == ExportFormat.DOCX else "xlsx"
        file_path = self.file_service.get_export_path(export_id, ext)

        try:
            if fmt == ExportFormat.DOCX:
                self.export_service.generate_docx(
                    submissions=submissions,
                    output_path=file_path,
                    date_from=business_date,
                    date_to=business_date,
                )
            else:
                self.export_service.generate_excel(
                    submissions=submissions,
                    output_path=file_path,
                    date_from=business_date,
                    date_to=business_date,
                )

            # Update export to READY
            async with self.session_factory() as session:
                export_repo = ExportRepository(session)
                await export_repo.update_status(export_id, status=ExportStatus.READY, file_path=str(file_path))
                await session.commit()

            # Deliver to recipients
            delivered_count = 0
            for r in recipients:
                deliv_res = await self._deliver_file(r.telegram_chat_id, file_path, business_date, len(submissions))
                if r.id > 0:
                    async with self.session_factory() as session:
                        export_repo = ExportRepository(session)
                        await export_repo.update_recipient_delivery(
                            export_id=export_id,
                            recipient_id=r.id,
                            delivery_status=DeliveryStatus.DELIVERY_SUCCESS
                            if deliv_res
                            else DeliveryStatus.DELIVERY_FAILED,
                        )
                        await session.commit()
                if deliv_res:
                    delivered_count += 1

            # Finalize status
            final_status = "SUCCESS" if delivered_count > 0 else "DELIVERY_FAILED"
            async with self.session_factory() as session:
                schedule_repo = ScheduleRepository(session)
                export_repo = ExportRepository(session)
                audit_repo = AuditLogRepository(session)

                await schedule_repo.record_execution_complete(execution_id, status=final_status, export_id=export_id)
                await export_repo.update_status(
                    export_id,
                    status=ExportStatus.SENT if delivered_count == len(recipients) else ExportStatus.PARTIAL_SUCCESS,
                    completed_at=datetime.now(timezone.utc),
                )
                await audit_repo.log_action(
                    admin_user_id=0,
                    action=AdminAction.ADMIN_CREATE_EXPORT.value,
                    target_type="export",
                    target_id=export_id,
                    metadata_safe={"schedule_id": schedule_id, "delivered": delivered_count},
                )
                await session.commit()

            return {"status": final_status, "export_id": export_id, "delivered_count": delivered_count}

        except Exception as e:
            async with self.session_factory() as session:
                schedule_repo = ScheduleRepository(session)
                export_repo = ExportRepository(session)
                await schedule_repo.record_execution_complete(execution_id, status="FAILED")
                await export_repo.update_status(export_id, status=ExportStatus.FAILED)
                await session.commit()
            return {"status": "FAILED", "error": str(e)}

    async def _deliver_file(self, chat_id: int, file_path: Path, business_date: date, count: int) -> bool:
        """Send the generated export document via Telegram."""
        try:
            caption = (
                f"📄 <b>ملف الأسئلة المجدول</b>\n\n"
                f"📅 <b>التاريخ:</b> {business_date.strftime('%Y-%m-%d')}\n"
                f"📥 <b>عدد الأسئلة:</b> {count}\n"
                f"✅ تم التجهيز والإرسال آليًا."
            )
            doc_file = FSInputFile(str(file_path))
            await self.bot.send_document(
                chat_id=chat_id,
                document=doc_file,
                caption=caption,
                parse_mode="HTML",
            )
            return True
        except Exception as e:
            print(f"[Delivery error to {chat_id}]: {e}")
            return False

    async def trigger_manually(self, schedule_id: int, business_date: date | None = None) -> bool:
        """Trigger immediate manual execution of a scheduled export."""
        target_date = business_date or datetime.now(self.settings.tz).date()
        # Reset any prior status if needed so manual run always executes
        async with self.session_factory() as session:
            schedule_repo = ScheduleRepository(session)
            exec_record = await schedule_repo.get_execution(schedule_id, target_date)
            if exec_record:
                exec_record.status = "RUNNING"
                await session.commit()

        res = await self.execute_schedule(schedule_id, target_date)
        return res.get("status") in ("SUCCESS", "SKIPPED_EMPTY", "ALREADY_COMPLETED")
