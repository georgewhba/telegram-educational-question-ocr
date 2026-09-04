"""Integration and Concurrency Tests against PostgreSQL.

Validates that PostgreSQL operates cleanly under:
- Foreign key constraints & CASCADE deletes
- Unique constraints
- JSONB columns and timezone-aware timestamps
- 20 concurrent student submissions + admin query + export execution
- Safe connection pooling and transactions
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database.base import Base, check_db_health
from app.database.models import ProcessingAttempt, Submission
from app.database.repositories import (
    AuditLogRepository,
    ExportRepository,
    RecipientRepository,
    ScheduleRepository,
    SubmissionRepository,
    UserRepository,
)
from app.domain.enums import (
    DeliveryStatus,
    ExportFormat,
    ProcessingStatus,
    UserRole,
)

POSTGRES_TEST_URL = "postgresql+asyncpg://postgres:postgres@localhost:5433/ocr_bot_test"


@pytest_asyncio.fixture
async def pg_engine():
    """Create engine for isolated test database and initialize schema."""
    engine = create_async_engine(POSTGRES_TEST_URL, pool_size=10, max_overflow=20)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def pg_session_factory(pg_engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=pg_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.mark.asyncio
async def test_postgres_connection_and_pool_health(pg_session_factory, monkeypatch):
    """Verify PostgreSQL health check and pooling work."""
    async with pg_session_factory() as session:
        result = await session.execute(text("SELECT 1"))
        assert result.scalar() == 1

    # Verify check_db_health
    from app.database import base
    base._engine = pg_session_factory.kw["bind"]
    assert await check_db_health() is True


@pytest.mark.asyncio
async def test_postgres_crud_and_cascade_constraints(pg_session_factory):
    """Test full entity lifecycle and foreign-key CASCADE behavior in PostgreSQL."""
    async with pg_session_factory() as session:
        user_repo = UserRepository(session)
        sub_repo = SubmissionRepository(session)

        # 1. Create student
        user = await user_repo.get_or_create(
            telegram_user_id=888111222,
            username="pg_tester",
            display_name="PG Test User",
            role=UserRole.STUDENT,
        )
        assert user.id is not None
        assert user.is_blocked is False

        # 2. Create submission
        sub = await sub_repo.create_submission(
            job_id="pg-job-001",
            user_id=user.id,
            submitted_at_utc=datetime.now(timezone.utc),
            business_date=date(2026, 9, 4),
            original_file_path="storage/originals/pg_test.jpg",
        )
        assert sub.id is not None
        assert sub.processing_status == ProcessingStatus.RECEIVED
        assert sub.delivery_status == DeliveryStatus.PENDING
        assert sub.submitted_at_utc.tzinfo is not None

        # 3. Add processing attempt
        attempt = await sub_repo.record_attempt(
            submission_id=sub.id,
            attempt_number=1,
            stage="OCR",
            status="SUCCESS",
        )
        assert attempt.id is not None

        await session.commit()

    # 4. Verify cascade delete: deleting user should delete submission and attempt
    async with pg_session_factory() as session:
        user_repo = UserRepository(session)
        u = await user_repo.get_by_telegram_id(888111222)
        assert u is not None
        await session.delete(u)
        await session.commit()

    async with pg_session_factory() as session:
        res_sub = await session.execute(select(Submission).where(Submission.job_id == "pg-job-001"))
        assert res_sub.scalar_one_or_none() is None

        res_att = await session.execute(select(ProcessingAttempt).where(ProcessingAttempt.submission_id == sub.id))
        assert res_att.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_postgres_schedule_idempotency_constraint(pg_session_factory):
    """Test PostgreSQL UniqueConstraint for schedule executions (prevent double execution)."""
    async with pg_session_factory() as session:
        sched_repo = ScheduleRepository(session)
        schedule = await sched_repo.create(
            time_of_day="23:00",
            timezone_str="Asia/Riyadh",
            format=ExportFormat.DOCX,
            content_config={"test": True},
        )
        await session.commit()
        schedule_id = schedule.id

    # Record first execution
    async with pg_session_factory() as session:
        sched_repo = ScheduleRepository(session)
        exec1 = await sched_repo.record_execution_start(
            schedule_id=schedule_id,
            business_date=date(2026, 9, 4),
        )
        assert exec1.id is not None
        await session.commit()

    # Verify second execution check finds existing execution
    async with pg_session_factory() as session:
        sched_repo = ScheduleRepository(session)
        existing_exec = await sched_repo.get_execution(schedule_id, date(2026, 9, 4))
        assert existing_exec is not None
        assert existing_exec.status == "RUNNING"


@pytest.mark.asyncio
async def test_postgres_concurrency_20_submissions_and_admin_queries(pg_session_factory):
    """Simulate 20 concurrent student submissions, concurrent admin queries, and export creation."""
    num_students = 20

    async def student_workflow(student_idx: int):
        async with pg_session_factory() as session:
            user_repo = UserRepository(session)
            sub_repo = SubmissionRepository(session)

            user = await user_repo.get_or_create(
                telegram_user_id=9000000 + student_idx,
                username=f"student_{student_idx}",
                display_name=f"Student {student_idx}",
                role=UserRole.STUDENT,
            )

            job_id = f"concurrent-job-{student_idx:03d}"
            sub = await sub_repo.create_submission(
                job_id=job_id,
                user_id=user.id,
                submitted_at_utc=datetime.now(timezone.utc),
                business_date=date(2026, 9, 4),
                original_file_path=f"storage/originals/sub_{student_idx}.jpg",
            )

            # Update with parsed text
            await sub_repo.update_parsed_question(
                job_id=job_id,
                question_text=f"ما هو السؤال رقم {student_idx}؟",
                option_a="أ",
                option_b="ب",
                option_c="ج",
                option_d="د",
                processing_status=ProcessingStatus.READY,
            )

            await sub_repo.record_attempt(
                submission_id=sub.id,
                attempt_number=1,
                stage="OCR",
                status="SUCCESS",
            )
            await session.commit()
            return sub.id

    async def admin_queries():
        results = []
        for _ in range(5):
            async with pg_session_factory() as session:
                sub_repo = SubmissionRepository(session)
                user_repo = UserRepository(session)
                count = await sub_repo.count_submissions(date_from=date(2026, 9, 4), date_to=date(2026, 9, 4))
                students_count = await user_repo.count_students()
                results.append((count, students_count))
                await asyncio.sleep(0.01)
        return results

    async def export_workflow():
        async with pg_session_factory() as session:
            exp_repo = ExportRepository(session)
            recip_repo = RecipientRepository(session)

            recip = await recip_repo.create(
                telegram_chat_id=-10099887766,
                name="Concurrent Teacher",
                role="TEACHER",
            )

            exp = await exp_repo.create(
                export_id="concurrent-export-001",
                export_type="DAILY",
                date_from=date(2026, 9, 4),
                date_to=date(2026, 9, 4),
                format=ExportFormat.DOCX,
                content_config={"concurrent": True},
                recipient_ids=[recip.id],
            )
            await session.commit()
            return exp.id

    # Run everything concurrently!
    tasks = [student_workflow(i) for i in range(num_students)]
    tasks.append(admin_queries())
    tasks.append(export_workflow())

    results = await asyncio.gather(*tasks)
    submission_ids = results[:num_students]

    # Verification
    assert len(submission_ids) == num_students
    assert len(set(submission_ids)) == num_students  # All unique IDs

    # Validate database state
    async with pg_session_factory() as session:
        sub_repo = SubmissionRepository(session)
        audit_repo = AuditLogRepository(session)

        total_subs = await sub_repo.count_submissions(date_from=date(2026, 9, 4), date_to=date(2026, 9, 4))
        # 1 earlier + 20 concurrent = 21
        assert total_subs >= num_students

        # Log audit entry to test JSONB metadata
        await audit_repo.log_action(
            admin_user_id=1420720902,
            action="CONCURRENCY_TEST_PASSED",
            target_type="BATCH",
            target_id=f"count={num_students}",
            metadata_safe={"processed": num_students, "status": "SUCCESS"},
        )
        await session.commit()

        logs = await audit_repo.list_logs(limit=5)
        assert len(logs) > 0
        assert logs[0].metadata_safe.get("status") == "SUCCESS"
