"""Application configuration via Pydantic Settings."""

from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration settings loaded from environment variables or .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Telegram Bot
    TELEGRAM_BOT_TOKEN: str = Field(..., description="Telegram bot API token")
    ADMIN_USER_IDS_RAW: str = Field(
        default="",
        alias="ADMIN_USER_IDS",
        description="Comma-separated list of numeric Telegram User IDs with admin access",
    )
    TEACHER_CHAT_ID: int = Field(..., description="Primary teacher Telegram chat ID")

    # Timezone & Localization
    TIMEZONE: str = Field(default="Asia/Riyadh", description="Business timezone")

    # Database
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5433/ocr_bot",
        description="Async SQLAlchemy database URL (e.g. postgresql+asyncpg://user:pass@host/db)",
    )
    DB_POOL_SIZE: int = Field(default=10, ge=1, le=100, description="PostgreSQL connection pool size")
    DB_MAX_OVERFLOW: int = Field(default=20, ge=0, le=100, description="PostgreSQL max overflow connections")
    DB_POOL_TIMEOUT: int = Field(default=30, ge=1, le=300, description="Pool connection acquisition timeout in seconds")
    DB_POOL_RECYCLE: int = Field(default=1800, ge=60, description="Seconds after which connection is recycled")

    # File Storage
    STORAGE_PATH: Path = Field(default=Path("./storage"), description="Base storage path")

    # OCR and AI Providers
    OCR_PROVIDER: str = Field(default="tesseract", description="Primary OCR provider: tesseract, gemini, mock")
    OCR_API_KEY: str | None = Field(default=None, description="Optional OCR API key")
    OPENAI_API_KEY: str | None = Field(default=None, description="Optional OpenAI API key")
    GEMINI_API_KEY: str | None = Field(default=None, description="Optional Gemini API key")

    # Resource & Security Limits
    MAX_FILE_SIZE_MB: int = Field(default=20, ge=1, le=100, description="Max allowed upload size in MB")
    MAX_IMAGE_WIDTH: int = Field(default=6000, ge=100, le=20000, description="Max image width in pixels")
    MAX_IMAGE_HEIGHT: int = Field(default=6000, ge=100, le=20000, description="Max image height in pixels")
    MAX_CONCURRENT_JOBS: int = Field(default=10, ge=1, le=50, description="Max concurrent processing jobs")
    IMAGE_RETENTION_DAYS: int = Field(default=30, ge=1, description="Days to retain original & processed images")
    EXPORT_RETENTION_DAYS: int = Field(default=30, ge=1, description="Days to retain generated export files")

    # Scheduler & Export Defaults
    DEFAULT_EXPORT_TIME: str = Field(default="23:00", description="Default HH:MM for daily recurring exports")
    SKIP_EMPTY_DAYS: bool = Field(default=True, description="Skip generating empty exports if no submissions exist")

    # Rate Limiting
    RATE_LIMIT_REQUESTS: int = Field(default=5, ge=1, description="Max requests allowed per window per user")
    RATE_LIMIT_WINDOW_SECONDS: int = Field(default=60, ge=5, description="Rate limit window in seconds")

    # Observability & Environment
    LOG_LEVEL: str = Field(default="INFO", description="Logging level: DEBUG, INFO, WARNING, ERROR")
    ENVIRONMENT: str = Field(default="development", description="Environment: development, staging, production")

    # Parsed Properties
    @property
    def admin_user_ids(self) -> set[int]:
        """Parse comma-separated ADMIN_USER_IDS into a set of numeric ints."""
        if not self.ADMIN_USER_IDS_RAW:
            return set()
        ids = set()
        for item in self.ADMIN_USER_IDS_RAW.split(","):
            cleaned = item.strip()
            if cleaned and cleaned.isdigit():
                ids.add(int(cleaned))
        return ids

    @property
    def tz(self) -> ZoneInfo:
        """Return timezone object for business date/time calculations."""
        try:
            return ZoneInfo(self.TIMEZONE)
        except Exception:
            return ZoneInfo("Asia/Riyadh")

    @property
    def max_file_size_bytes(self) -> int:
        return self.MAX_FILE_SIZE_MB * 1024 * 1024

    @property
    def originals_dir(self) -> Path:
        p = self.STORAGE_PATH / "originals"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def processed_dir(self) -> Path:
        p = self.STORAGE_PATH / "processed"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def exports_dir(self) -> Path:
        p = self.STORAGE_PATH / "exports"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def tmp_dir(self) -> Path:
        p = self.STORAGE_PATH / "tmp"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def normalize_database_url(cls, v: str) -> str:
        """Automatically adapt standard postgres/postgresql connection strings to use asyncpg driver."""
        if not v:
            return v
        url = str(v).strip()
        if url.startswith("postgres://"):
            url = "postgresql+asyncpg://" + url[len("postgres://"):]
        elif url.startswith("postgresql://"):
            url = "postgresql+asyncpg://" + url[len("postgresql://"):]
        elif url.startswith("sqlite://") and not url.startswith("sqlite+aiosqlite://"):
            url = "sqlite+aiosqlite://" + url[len("sqlite://"):]
        return url

    @field_validator("DEFAULT_EXPORT_TIME")
    @classmethod
    def validate_time_format(cls, v: str) -> str:
        parts = v.strip().split(":")
        if len(parts) != 2:
            raise ValueError("DEFAULT_EXPORT_TIME must be in HH:MM format")
        h, m = int(parts[0]), int(parts[1])
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError("DEFAULT_EXPORT_TIME must have 0<=HH<=23 and 0<=MM<=59")
        return f"{h:02d}:{m:02d}"


# Global settings singleton loader
_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
