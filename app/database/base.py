"""SQLAlchemy declarative base and async session lifecycle."""

from typing import Any, AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


class Base(DeclarativeBase):
    """Base declarative class for all SQLAlchemy models."""

    pass


def init_db(
    database_url: str,
    echo: bool = False,
    pool_size: int = 10,
    max_overflow: int = 20,
    pool_timeout: int = 30,
    pool_recycle: int = 1800,
) -> AsyncEngine:
    """Initialize the async engine with production-grade connection pooling."""
    global _engine, _session_factory

    engine_kwargs: dict[str, Any] = {
        "echo": echo,
        "future": True,
    }

    if database_url.startswith("sqlite"):
        engine_kwargs["connect_args"] = {"check_same_thread": False}
    else:
        # PostgreSQL / asyncpg connection pool configuration
        engine_kwargs["pool_size"] = pool_size
        engine_kwargs["max_overflow"] = max_overflow
        engine_kwargs["pool_timeout"] = pool_timeout
        engine_kwargs["pool_recycle"] = pool_recycle
        engine_kwargs["pool_pre_ping"] = True

    _engine = create_async_engine(database_url, **engine_kwargs)
    _session_factory = async_sessionmaker(
        bind=_engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    return _engine


def get_engine() -> AsyncEngine | None:
    """Get the active async engine."""
    global _engine
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Get the async session factory."""
    global _session_factory
    if _session_factory is None:
        raise RuntimeError("Database is not initialized. Call init_db() first.")
    return _session_factory


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide an async session generator."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def check_db_health() -> bool:
    """Execute a lightweight test query to verify database connectivity."""
    engine = get_engine()
    if engine is None:
        return False
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def create_all_tables():
    """Create all tables in the database (used in development/testing)."""
    engine = get_engine()
    if engine is None:
        raise RuntimeError("Database engine not initialized")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
