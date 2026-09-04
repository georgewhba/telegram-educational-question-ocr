"""Aiogram Bot and Dispatcher setup with routers and middlewares."""

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.bot.handlers.admin import admin_router
from app.bot.handlers.student import student_router
from app.bot.middlewares.rate_limit import RateLimitMiddleware
from app.config.settings import Settings


def create_bot_and_dispatcher(settings: Settings, session_factory: async_sessionmaker) -> tuple[Bot, Dispatcher]:
    """Create and configure the aiogram Bot and Dispatcher instances."""
    bot = Bot(
        token=settings.TELEGRAM_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    dp = Dispatcher()

    # Pass global dependencies in dispatcher workflow data
    dp["settings"] = settings
    dp["session_factory"] = session_factory

    # Register Middlewares
    rate_limiter = RateLimitMiddleware(settings)
    dp.message.middleware(rate_limiter)

    # Register Handlers Routers (Admin first to intercept /admin and admin callbacks cleanly)
    dp.include_router(admin_router)
    dp.include_router(student_router)

    return bot, dp
