"""Integration tests for all database repositories."""

from datetime import date, datetime, timezone

import pytest

from app.database.repositories import (
    ScheduleRepository,
    SubmissionRepository,
    UserRepository,
)
from app.domain.enums import ExportFormat, ProcessingStatus


@pytest.mark.asyncio
async def test_user_and_submission_repositories(session_factory):
    async with session_factory() as session:
        user_repo = UserRepository(session)
        sub_repo = SubmissionRepository(session)

        # 1. User creation
        user = await user_repo.get_or_create(
            telegram_user_id=987654,
            display_name="سارة علي",
            username="sara_ali",
        )
        await session.commit()
        assert user.id is not None
        assert user.display_name == "سارة علي"
        assert user.is_blocked is False

        # 2. Block/Unblock
        await user_repo.set_blocked_status(987654, is_blocked=True)
        await session.commit()
        updated_user = await user_repo.get_by_telegram_id(987654)
        assert updated_user.is_blocked is True

        # 3. Create Submission
        today = datetime.now(timezone.utc).date()
        sub = await sub_repo.create_submission(
            job_id="job-integration-1",
            user_id=user.id,
            submitted_at_utc=datetime.now(timezone.utc),
            business_date=today,
            original_file_path="/storage/originals/job-1.jpg",
        )
        await session.commit()
        assert sub.job_id == "job-integration-1"
        assert sub.processing_status == ProcessingStatus.RECEIVED

        # 4. Update Parsed Question
        await sub_repo.update_parsed_question(
            job_id="job-integration-1",
            question_text="ما هي عاصمة الكويت؟",
            option_a="الكويت",
            option_b="المنامة",
            option_c="الدوحة",
            option_d="مسقط",
            processed_file_path="/storage/processed/job-1.png",
            processing_status=ProcessingStatus.READY,
        )
        await session.commit()

        # 5. Record Attempt
        await sub_repo.record_attempt(
            submission_id=sub.id,
            attempt_number=1,
            stage="OCR_standard",
            status="PASS",
        )
        await session.commit()
        session.expire_all()

        # 6. Verify Fetch
        fetched_sub = await sub_repo.get_by_job_id("job-integration-1")
        assert fetched_sub.question_text == "ما هي عاصمة الكويت؟"
        assert fetched_sub.processing_status == ProcessingStatus.READY
        assert len(fetched_sub.attempts) == 1


@pytest.mark.asyncio
async def test_schedule_repository_and_idempotency(session_factory):
    async with session_factory() as session:
        sched_repo = ScheduleRepository(session)

        # 1. Create schedule
        sched = await sched_repo.create(
            time_of_day="23:00",
            timezone_str="Asia/Riyadh",
            format=ExportFormat.DOCX,
            content_config={"test": True},
        )
        await session.commit()
        assert sched.id is not None
        assert sched.is_active is True

        # 2. Record execution start
        today = date(2026, 9, 4)
        exec_record = await sched_repo.record_execution_start(sched.id, today)
        await session.commit()
        assert exec_record.id is not None

        # 3. Verify duplicate check
        existing = await sched_repo.get_execution(sched.id, today)
        assert existing is not None
        assert existing.status == "RUNNING"

        # 4. Complete execution
        await sched_repo.record_execution_complete(exec_record.id, status="SUCCESS", export_id="exp-123")
        await session.commit()

        updated_exec = await sched_repo.get_execution(sched.id, today)
        assert updated_exec.status == "SUCCESS"
        assert updated_exec.export_id == "exp-123"
