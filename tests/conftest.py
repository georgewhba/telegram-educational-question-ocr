"""Pytest configuration and shared fixtures for unit, integration, and E2E tests."""

import asyncio
import io
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config.settings import Settings
from app.database.base import Base
from app.domain.models import QuestionPayload


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def test_settings(tmp_path_factory) -> Settings:
    storage_tmp = tmp_path_factory.mktemp("test_storage")
    return Settings(
        TELEGRAM_BOT_TOKEN="1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ_TEST_TOKEN",
        ADMIN_USER_IDS="123456789,987654321",
        TEACHER_CHAT_ID=-1001234567890,
        TIMEZONE="Asia/Riyadh",
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        STORAGE_PATH=storage_tmp,
        OCR_PROVIDER="mock",
        MAX_FILE_SIZE_MB=10,
        MAX_IMAGE_WIDTH=4000,
        MAX_IMAGE_HEIGHT=4000,
        DEFAULT_EXPORT_TIME="23:00",
        SKIP_EMPTY_DAYS=True,
    )


@pytest_asyncio.fixture
async def session_factory(test_settings: Settings) -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    engine = create_async_engine(test_settings.DATABASE_URL, connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    yield factory

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(session_factory) -> AsyncGenerator[AsyncSession, None]:
    async with session_factory() as session:
        yield session
        await session.rollback()


@pytest.fixture
def sample_question_payload() -> QuestionPayload:
    return QuestionPayload(
        question="ما هي عاصمة المملكة العربية السعودية؟",
        option_a="الرياض",
        option_b="جدة",
        option_c="الدمام",
        option_d="مكة المكرمة",
        language="ar",
        confidence=0.98,
        job_id="test-job-001",
    )


@pytest.fixture
def sample_image_bytes() -> bytes:
    """Create a minimal valid JPEG image in memory."""
    img = Image.new("RGB", (200, 200), color=(255, 255, 255))
    bio = io.BytesIO()
    img.save(bio, format="JPEG")
    return bio.getvalue()
