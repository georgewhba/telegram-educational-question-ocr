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
