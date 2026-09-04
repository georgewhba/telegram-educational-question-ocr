"""Unit tests for AdminService pagination, toggles, and newly added admin keyboards."""

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.bot.keyboards.admin_keyboards import (
    get_archive_keyboard,
    get_audit_keyboard,
    get_images_keyboard,
    get_recipients_keyboard,
    get_schedule_details_keyboard,
)
from app.config.settings import Settings
from app.database.base import Base
from app.database.models import Recipient, Schedule
from app.domain.enums import ExportFormat, ScheduleType
from app.services.admin_service import AdminService


@pytest.fixture
async def memory_db_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_admin_service_archive_and_audit_pagination(memory_db_factory):
    settings = Settings(
        TELEGRAM_BOT_TOKEN="dummy:token",
        ADMIN_USER_IDS="1420720902",
        TEACHER_CHAT_ID=1420720902,
    )
    admin_service = AdminService(session_factory=memory_db_factory, settings=settings)

    # Empty test
    res = await admin_service.list_exports_paginated(page=1, per_page=5)
    assert res["total_items"] == 0
    assert len(res["items"]) == 0
    assert res["total_pages"] == 1

    audit_res = await admin_service.list_audit_logs_paginated(page=1, per_page=5)
    assert audit_res["total_items"] == 0
    assert len(audit_res["items"]) == 0


@pytest.mark.asyncio
async def test_admin_service_toggles(memory_db_factory):
    settings = Settings(
        TELEGRAM_BOT_TOKEN="dummy:token",
        ADMIN_USER_IDS="1420720902",
        TEACHER_CHAT_ID=1420720902,
    )
    admin_service = AdminService(session_factory=memory_db_factory, settings=settings)

    # Seed a schedule and recipient
    async with memory_db_factory() as session:
        sched = Schedule(
            schedule_type=ScheduleType.DAILY,
            time_of_day="23:00",
            timezone="Africa/Cairo",
            format=ExportFormat.DOCX,
            content_config={},
            is_active=True,
        )
        recip = Recipient(
            telegram_chat_id=1420720902,
            name="Teacher",
            role="TEACHER",
            is_active=True,
        )
        session.add(sched)
        session.add(recip)
        await session.commit()
        sched_id = sched.id
        recip_id = recip.id

    # Toggle schedule
    new_sched_state = await admin_service.toggle_schedule(1420720902, sched_id)
    assert new_sched_state is False

    # Toggle recipient
    new_recip_state = await admin_service.toggle_recipient(1420720902, recip_id)
    assert new_recip_state is False


def test_keyboards_generation():
    sched_kb = get_schedule_details_keyboard(1, is_active=True)
    assert len(sched_kb.inline_keyboard) == 2
    assert "sched_toggle:1" in sched_kb.inline_keyboard[0][0].callback_data

    audit_kb = get_audit_keyboard(current_page=2, total_pages=5)
    assert any("admin_audit:1" in btn.callback_data for row in audit_kb.inline_keyboard for btn in row)

    archive_kb = get_archive_keyboard(exports=[], current_page=1, total_pages=1)
    assert len(archive_kb.inline_keyboard) >= 1

    recip_kb = get_recipients_keyboard([])
    assert len(recip_kb.inline_keyboard) >= 1

    images_kb = get_images_keyboard([], 1, 1)
    assert len(images_kb.inline_keyboard) >= 1
