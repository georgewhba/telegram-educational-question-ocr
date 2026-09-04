"""Repository classes for atomic database access, filtering, and indexing."""

from datetime import date, datetime
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import (
    AdminAuditLog,
    Export,
    ExportRecipient,
    ProcessingAttempt,
    Recipient,
    Schedule,
    ScheduleExecution,
    Submission,
    SystemSetting,
    User,
    utc_now,
)
from app.domain.enums import (
    DeliveryStatus,
    ExportFormat,
    ExportStatus,
    ProcessingStatus,
    ScheduleType,
    UserRole,
)


class UserRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_or_create(
        self,
        telegram_user_id: int,
        display_name: str,
        username: str | None = None,
        role: UserRole = UserRole.STUDENT,
    ) -> User:
        stmt = select(User).where(User.telegram_user_id == telegram_user_id)
        result = await self.session.execute(stmt)
        user = result.scalar_one_or_none()

        if user is None:
            user = User(
                telegram_user_id=telegram_user_id,
                username=username,
                display_name=display_name,
                role=role,
                is_blocked=False,
                created_at=utc_now(),
                last_seen_at=utc_now(),
            )
            self.session.add(user)
            await self.session.flush()
        else:
            # Update last seen and profile changes
            user.last_seen_at = utc_now()
            user.display_name = display_name
            if username is not None:
                user.username = username
            await self.session.flush()

        return user

    async def get_by_telegram_id(self, telegram_user_id: int) -> User | None:
        stmt = select(User).where(User.telegram_user_id == telegram_user_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id(self, user_id: int) -> User | None:
        stmt = select(User).where(User.id == user_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def set_blocked_status(self, telegram_user_id: int, is_blocked: bool) -> bool:
        user = await self.get_by_telegram_id(telegram_user_id)
        if user:
            user.is_blocked = is_blocked
            await self.session.flush()
            return True
        return False

    async def list_students(
        self, skip: int = 0, limit: int = 20, search_term: str | None = None, is_blocked: bool | None = None
    ) -> list[User]:
        stmt = select(User).order_by(desc(User.last_seen_at)).offset(skip).limit(limit)
        if is_blocked is not None:
            stmt = stmt.where(User.is_blocked == is_blocked)
        if search_term:
            term = f"%{search_term}%"
            stmt = stmt.where((User.display_name.ilike(term)) | (User.username.ilike(term)))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_students(self, is_blocked: bool | None = None) -> int:
        stmt = select(func.count(User.id))
        if is_blocked is not None:
            stmt = stmt.where(User.is_blocked == is_blocked)
        result = await self.session.execute(stmt)
        return result.scalar_one() or 0


class SubmissionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_submission(
        self,
        job_id: str,
        user_id: int,
        submitted_at_utc: datetime,
        business_date: date,
        original_file_path: str,
    ) -> Submission:
        submission = Submission(
            job_id=job_id,
            user_id=user_id,
            submitted_at_utc=submitted_at_utc,
            business_date=business_date,
            original_file_path=original_file_path,
            processing_status=ProcessingStatus.RECEIVED,
            delivery_status=DeliveryStatus.PENDING,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        self.session.add(submission)
        await self.session.flush()
        return submission

    async def get_by_job_id(self, job_id: str) -> Submission | None:
        stmt = (
            select(Submission)
            .where(Submission.job_id == job_id)
            .options(selectinload(Submission.user), selectinload(Submission.attempts))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id(self, submission_id: int) -> Submission | None:
        stmt = (
            select(Submission)
            .where(Submission.id == submission_id)
            .options(selectinload(Submission.user), selectinload(Submission.attempts))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_parsed_question(
        self,
        job_id: str,
        question_text: str,
        option_a: str,
        option_b: str,
        option_c: str,
        option_d: str,
        processed_file_path: str | None = None,
        processing_status: ProcessingStatus = ProcessingStatus.READY,
    ) -> Submission | None:
        submission = await self.get_by_job_id(job_id)
        if submission:
            submission.question_text = question_text
            submission.option_a = option_a
            submission.option_b = option_b
            submission.option_c = option_c
            submission.option_d = option_d
            if processed_file_path:
                submission.processed_file_path = processed_file_path
            submission.processing_status = processing_status
            submission.updated_at = utc_now()
            await self.session.flush()
        return submission

    async def update_status(
        self,
        job_id: str,
        processing_status: ProcessingStatus | None = None,
        delivery_status: DeliveryStatus | None = None,
        processed_file_path: str | None = None,
    ) -> Submission | None:
        submission = await self.get_by_job_id(job_id)
        if submission:
            if processing_status is not None:
                submission.processing_status = processing_status
            if delivery_status is not None:
                submission.delivery_status = delivery_status
            if processed_file_path is not None:
                submission.processed_file_path = processed_file_path
            submission.updated_at = utc_now()
            await self.session.flush()
        return submission

    async def record_attempt(
        self,
        submission_id: int,
        attempt_number: int,
        stage: str,
        status: str,
        error_type: str | None = None,
        safe_error_message: str | None = None,
    ) -> ProcessingAttempt:
        attempt = ProcessingAttempt(
            submission_id=submission_id,
            attempt_number=attempt_number,
            stage=stage,
            status=status,
            error_type=error_type,
            safe_error_message=safe_error_message,
            started_at=utc_now(),
            completed_at=utc_now(),
        )
        self.session.add(attempt)
        await self.session.flush()
        return attempt

    async def list_submissions(
        self,
        skip: int = 0,
        limit: int = 10,
        date_from: date | None = None,
        date_to: date | None = None,
        processing_status: ProcessingStatus | None = None,
        delivery_status: DeliveryStatus | None = None,
        user_id: int | None = None,
        search_term: str | None = None,
    ) -> list[Submission]:
        stmt = (
            select(Submission)
            .options(selectinload(Submission.user))
            .order_by(desc(Submission.submitted_at_utc))
            .offset(skip)
            .limit(limit)
        )

        if date_from:
            stmt = stmt.where(Submission.business_date >= date_from)
        if date_to:
            stmt = stmt.where(Submission.business_date <= date_to)
        if processing_status:
            stmt = stmt.where(Submission.processing_status == processing_status)
        if delivery_status:
            stmt = stmt.where(Submission.delivery_status == delivery_status)
        if user_id:
            stmt = stmt.where(Submission.user_id == user_id)
        if search_term:
            term = f"%{search_term}%"
            stmt = stmt.join(Submission.user).where(
                (Submission.job_id.ilike(term)) | (User.display_name.ilike(term)) | (User.username.ilike(term))
            )

        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_submissions(
        self,
        date_from: date | None = None,
        date_to: date | None = None,
        processing_status: ProcessingStatus | None = None,
        delivery_status: DeliveryStatus | None = None,
        user_id: int | None = None,
    ) -> int:
        stmt = select(func.count(Submission.id))
        if date_from:
            stmt = stmt.where(Submission.business_date >= date_from)
        if date_to:
            stmt = stmt.where(Submission.business_date <= date_to)
        if processing_status:
            stmt = stmt.where(Submission.processing_status == processing_status)
        if delivery_status:
            stmt = stmt.where(Submission.delivery_status == delivery_status)
        if user_id:
            stmt = stmt.where(Submission.user_id == user_id)
        result = await self.session.execute(stmt)
        return result.scalar_one() or 0

    async def get_chronological_for_date_range(
        self, date_from: date, date_to: date, successful_only: bool = True
    ) -> list[Submission]:
        """Fetch submissions strictly sorted chronologically (ASC) for reports/exports."""
        stmt = (
            select(Submission)
            .options(selectinload(Submission.user))
            .where(Submission.business_date >= date_from, Submission.business_date <= date_to)
            .order_by(Submission.submitted_at_utc.asc())
        )
        if successful_only:
            stmt = stmt.where(Submission.processing_status == ProcessingStatus.READY)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_statistics(self, business_date: date | None = None) -> dict[str, Any]:
        """Calculate system dashboard metrics."""
        today_date = business_date or utc_now().date()

        # Today's submissions query
        today_total_q = select(func.count(Submission.id)).where(Submission.business_date == today_date)
        today_success_q = select(func.count(Submission.id)).where(
            Submission.business_date == today_date,
            Submission.processing_status == ProcessingStatus.READY,
        )
        today_failed_q = select(func.count(Submission.id)).where(
            Submission.business_date == today_date,
            Submission.processing_status == ProcessingStatus.FAILED,
        )
        today_delivered_q = select(func.count(Submission.id)).where(
            Submission.business_date == today_date,
            Submission.delivery_status == DeliveryStatus.DELIVERY_SUCCESS,
        )
        today_delivery_failed_q = select(func.count(Submission.id)).where(
            Submission.business_date == today_date,
            Submission.delivery_status == DeliveryStatus.DELIVERY_FAILED,
        )

        all_time_total_q = select(func.count(Submission.id))
        all_time_success_q = select(func.count(Submission.id)).where(
            Submission.processing_status == ProcessingStatus.READY
        )
        all_time_failed_q = select(func.count(Submission.id)).where(
            Submission.processing_status == ProcessingStatus.FAILED
        )

        today_total = (await self.session.execute(today_total_q)).scalar_one() or 0
        today_success = (await self.session.execute(today_success_q)).scalar_one() or 0
        today_failed = (await self.session.execute(today_failed_q)).scalar_one() or 0
        today_delivered = (await self.session.execute(today_delivered_q)).scalar_one() or 0
        today_delivery_failed = (await self.session.execute(today_delivery_failed_q)).scalar_one() or 0

        all_total = (await self.session.execute(all_time_total_q)).scalar_one() or 0
        all_success = (await self.session.execute(all_time_success_q)).scalar_one() or 0
        all_failed = (await self.session.execute(all_time_failed_q)).scalar_one() or 0

        # Unique active students today
        today_students_q = select(func.count(func.distinct(Submission.user_id))).where(
            Submission.business_date == today_date
        )
        today_students = (await self.session.execute(today_students_q)).scalar_one() or 0

        return {
            "today_date": today_date,
            "today_total": today_total,
            "today_success": today_success,
            "today_failed": today_failed,
            "today_delivered": today_delivered,
            "today_delivery_failed": today_delivery_failed,
            "today_students": today_students,
            "all_total": all_total,
            "all_success": all_success,
            "all_failed": all_failed,
        }

    async def delete_submission(self, job_id: str) -> bool:
        submission = await self.get_by_job_id(job_id)
        if submission:
            await self.session.delete(submission)
            await self.session.flush()
            return True
        return False


class RecipientRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_all(self, active_only: bool = True) -> list[Recipient]:
        stmt = select(Recipient).order_by(Recipient.name.asc())
        if active_only:
            stmt = stmt.where(Recipient.is_active.is_(True))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_id(self, recipient_id: int) -> Recipient | None:
        stmt = select(Recipient).where(Recipient.id == recipient_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_chat_id(self, telegram_chat_id: int) -> Recipient | None:
        stmt = select(Recipient).where(Recipient.telegram_chat_id == telegram_chat_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(
        self, telegram_chat_id: int, name: str, role: str = "TEACHER", is_active: bool = True
    ) -> Recipient:
        recipient = await self.get_by_chat_id(telegram_chat_id)
        if recipient:
            recipient.name = name
            recipient.role = role
            recipient.is_active = is_active
            recipient.updated_at = utc_now()
        else:
            recipient = Recipient(
                telegram_chat_id=telegram_chat_id,
                name=name,
                role=role,
                is_active=is_active,
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            self.session.add(recipient)
        await self.session.flush()
        return recipient

    async def toggle_active(self, recipient_id: int) -> bool:
        recipient = await self.get_by_id(recipient_id)
        if recipient:
            recipient.is_active = not recipient.is_active
            recipient.updated_at = utc_now()
            await self.session.flush()
            return recipient.is_active
        return False

    async def delete(self, recipient_id: int) -> bool:
        recipient = await self.get_by_id(recipient_id)
        if recipient:
            await self.session.delete(recipient)
            await self.session.flush()
            return True
        return False


class ExportRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        export_id: str,
        export_type: str,
        date_from: date,
        date_to: date,
        format: ExportFormat,
        content_config: dict[str, Any],
        created_by: int | None = None,
        recipient_ids: list[int] | None = None,
    ) -> Export:
        export = Export(
            id=export_id,
            export_type=export_type,
            date_from=date_from,
            date_to=date_to,
            format=format,
            content_config=content_config,
            status=ExportStatus.PENDING,
            created_by=created_by,
            created_at=utc_now(),
        )
        self.session.add(export)
        await self.session.flush()

        if recipient_ids:
            for r_id in recipient_ids:
                er = ExportRecipient(
                    export_id=export_id,
                    recipient_id=r_id,
                    delivery_status=DeliveryStatus.PENDING,
                )
                self.session.add(er)
            await self.session.flush()

        return export

    async def get_by_id(self, export_id: str) -> Export | None:
        stmt = (
            select(Export)
            .where(Export.id == export_id)
            .options(selectinload(Export.export_recipients).selectinload(ExportRecipient.recipient))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_status(
        self,
        export_id: str,
        status: ExportStatus,
        file_path: str | None = None,
        completed_at: datetime | None = None,
    ) -> Export | None:
        export = await self.get_by_id(export_id)
        if export:
            export.status = status
            if file_path:
                export.file_path = file_path
            if completed_at:
                export.completed_at = completed_at
            await self.session.flush()
        return export

    async def update_recipient_delivery(
        self,
        export_id: str,
        recipient_id: int,
        delivery_status: DeliveryStatus,
        telegram_message_id: int | None = None,
        error_type: str | None = None,
    ) -> bool:
        stmt = select(ExportRecipient).where(
            ExportRecipient.export_id == export_id,
            ExportRecipient.recipient_id == recipient_id,
        )
        result = await self.session.execute(stmt)
        er = result.scalar_one_or_none()
        if er:
            er.delivery_status = delivery_status
            er.telegram_message_id = telegram_message_id
            er.delivered_at = utc_now() if delivery_status == DeliveryStatus.DELIVERY_SUCCESS else None
            er.error_type = error_type
            await self.session.flush()
            return True
        return False

    async def list_exports(self, skip: int = 0, limit: int = 10) -> list[Export]:
        stmt = (
            select(Export)
            .options(selectinload(Export.export_recipients).selectinload(ExportRecipient.recipient))
            .order_by(desc(Export.created_at))
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_exports(self) -> int:
        stmt = select(func.count(Export.id))
        result = await self.session.execute(stmt)
        return result.scalar_one() or 0

    async def delete(self, export_id: str) -> bool:
        export = await self.get_by_id(export_id)
        if export:
            await self.session.delete(export)
            await self.session.flush()
            return True
        return False


class ScheduleRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_active(self) -> list[Schedule]:
        stmt = select(Schedule).where(Schedule.is_active.is_(True))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_all(self) -> list[Schedule]:
        stmt = select(Schedule).order_by(Schedule.id.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_id(self, schedule_id: int) -> Schedule | None:
        stmt = select(Schedule).where(Schedule.id == schedule_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(
        self,
        time_of_day: str,
        timezone_str: str,
        format: ExportFormat,
        content_config: dict[str, Any],
        created_by: int | None = None,
        is_active: bool = True,
    ) -> Schedule:
        schedule = Schedule(
            schedule_type=ScheduleType.DAILY,
            time_of_day=time_of_day,
            timezone=timezone_str,
            format=format,
            content_config=content_config,
            is_active=is_active,
            created_by=created_by,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        self.session.add(schedule)
        await self.session.flush()
        return schedule

    async def toggle_active(self, schedule_id: int) -> bool:
        schedule = await self.get_by_id(schedule_id)
        if schedule:
            schedule.is_active = not schedule.is_active
            schedule.updated_at = utc_now()
            await self.session.flush()
            return schedule.is_active
        return False

    async def delete(self, schedule_id: int) -> bool:
        schedule = await self.get_by_id(schedule_id)
        if schedule:
            await self.session.delete(schedule)
            await self.session.flush()
            return True
        return False

    async def get_execution(self, schedule_id: int, business_date: date) -> ScheduleExecution | None:
        stmt = select(ScheduleExecution).where(
            ScheduleExecution.schedule_id == schedule_id,
            ScheduleExecution.business_date == business_date,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def record_execution_start(self, schedule_id: int, business_date: date) -> ScheduleExecution:
        execution = ScheduleExecution(
            schedule_id=schedule_id,
            business_date=business_date,
            started_at=utc_now(),
            status="RUNNING",
        )
        self.session.add(execution)
        await self.session.flush()
        return execution

    async def record_execution_complete(self, execution_id: int, status: str, export_id: str | None = None) -> None:
        stmt = select(ScheduleExecution).where(ScheduleExecution.id == execution_id)
        result = await self.session.execute(stmt)
        execution = result.scalar_one_or_none()
        if execution:
            execution.status = status
            execution.export_id = export_id
            execution.completed_at = utc_now()
            await self.session.flush()


class AuditLogRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def log_action(
        self,
        admin_user_id: int,
        action: str,
        target_type: str | None = None,
        target_id: str | None = None,
        metadata_safe: dict[str, Any] | None = None,
    ) -> AdminAuditLog:
        log = AdminAuditLog(
            admin_user_id=admin_user_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            metadata_safe=metadata_safe or {},
            created_at=utc_now(),
        )
        self.session.add(log)
        await self.session.flush()
        return log

    async def list_logs(self, skip: int = 0, limit: int = 20) -> list[AdminAuditLog]:
        stmt = select(AdminAuditLog).order_by(desc(AdminAuditLog.created_at)).offset(skip).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_logs(self) -> int:
        stmt = select(func.count(AdminAuditLog.id))
        result = await self.session.execute(stmt)
        return result.scalar_one() or 0


class SystemSettingRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, key: str, default: str | None = None) -> str | None:
        stmt = select(SystemSetting).where(SystemSetting.key == key)
        result = await self.session.execute(stmt)
        setting = result.scalar_one_or_none()
        return setting.value if setting else default

    async def set(self, key: str, value: str, description: str | None = None) -> None:
        stmt = select(SystemSetting).where(SystemSetting.key == key)
        result = await self.session.execute(stmt)
        setting = result.scalar_one_or_none()
        if setting:
            setting.value = value
            if description:
                setting.description = description
            setting.updated_at = utc_now()
        else:
            setting = SystemSetting(
                key=key,
                value=value,
                description=description,
                updated_at=utc_now(),
            )
            self.session.add(setting)
        await self.session.flush()
