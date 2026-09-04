"""Unit tests for configuration and settings."""

from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from app.config.settings import Settings


def test_settings_parsing():
    settings = Settings(
        TELEGRAM_BOT_TOKEN="test_token",
        ADMIN_USER_IDS="111, 222, 333",
        TEACHER_CHAT_ID=-100999,
        TIMEZONE="Asia/Riyadh",
        STORAGE_PATH="./test_storage",
    )
    assert settings.admin_user_ids == {111, 222, 333}
    assert settings.TEACHER_CHAT_ID == -100999
    assert isinstance(settings.tz, ZoneInfo)
    assert settings.tz.key == "Asia/Riyadh"
    assert settings.max_file_size_bytes == 20 * 1024 * 1024


def test_invalid_time_format():
    with pytest.raises(ValidationError):
        Settings(
            TELEGRAM_BOT_TOKEN="test_token",
            TEACHER_CHAT_ID=123,
            DEFAULT_EXPORT_TIME="25:99",
        )


def test_database_url_normalization():
    # Railway/Heroku standard postgresql:// URL
    s1 = Settings(
        TELEGRAM_BOT_TOKEN="test_token",
        TEACHER_CHAT_ID=123,
        DATABASE_URL="postgresql://postgres:pass@localhost:5432/railway",
    )
    assert s1.DATABASE_URL == "postgresql+asyncpg://postgres:pass@localhost:5432/railway"

    # Legacy postgres:// URL
    s2 = Settings(
        TELEGRAM_BOT_TOKEN="test_token",
        TEACHER_CHAT_ID=123,
        DATABASE_URL="postgres://postgres:pass@localhost:5432/railway",
    )
    assert s2.DATABASE_URL == "postgresql+asyncpg://postgres:pass@localhost:5432/railway"

    # Raw sqlite:// URL
    s3 = Settings(
        TELEGRAM_BOT_TOKEN="test_token",
        TEACHER_CHAT_ID=123,
        DATABASE_URL="sqlite:///test.db",
    )
    assert s3.DATABASE_URL == "sqlite+aiosqlite:///test.db"

    # Explicit asyncpg URL remains untouched
    s4 = Settings(
        TELEGRAM_BOT_TOKEN="test_token",
        TEACHER_CHAT_ID=123,
        DATABASE_URL="postgresql+asyncpg://postgres:pass@localhost:5432/railway",
    )
    assert s4.DATABASE_URL == "postgresql+asyncpg://postgres:pass@localhost:5432/railway"

