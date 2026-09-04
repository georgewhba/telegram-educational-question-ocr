"""Main application entry point with graceful lifecycle management, DB setup, and scheduler."""

import asyncio
import logging
import signal
import sys

from app.bot.bot_instance import create_bot_and_dispatcher
from app.config.settings import get_settings
from app.database.base import check_db_health, get_session_factory, init_db
from app.database.repositories import RecipientRepository, ScheduleRepository
from app.domain.enums import ExportFormat
from app.services.file_service import FileService
from app.services.scheduling_service import SchedulingService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("app.main")


async def bootstrap_database(session_factory, settings):
    """Seed initial defaults such as default recipient and recurring schedule if table is empty."""
    async with session_factory() as session:
        recip_repo = RecipientRepository(session)
        recipients = await recip_repo.get_all(active_only=False)
        if not recipients and settings.TEACHER_CHAT_ID:
            await recip_repo.create(
                telegram_chat_id=settings.TEACHER_CHAT_ID,
                name="المعلم الأساسي",
                role="TEACHER",
                is_active=True,
            )
            await session.commit()
            logger.info(f"Initialized default teacher recipient: {settings.TEACHER_CHAT_ID}")

        sched_repo = ScheduleRepository(session)
        schedules = await sched_repo.get_all()
        if not schedules:
            await sched_repo.create(
                time_of_day=settings.DEFAULT_EXPORT_TIME,
                timezone_str=settings.TIMEZONE,
                format=ExportFormat.DOCX,
                content_config={"default": True},
                is_active=True,
            )
            await session.commit()
            logger.info(f"Initialized default daily export schedule at {settings.DEFAULT_EXPORT_TIME}")


async def main():
    logger.info("Starting Telegram Educational Question Processing Bot...")

    # Load and validate settings
    settings = get_settings()
    logger.info(f"Loaded configuration for environment: {settings.ENVIRONMENT}")
    logger.info(f"Configured Admin user IDs: {settings.admin_user_ids}")
    logger.info(f"Configured Teacher Chat ID: {settings.TEACHER_CHAT_ID}")

    # Ensure storage paths exist
    file_service = FileService(settings)
    file_service.cleanup_expired_files()

    # Initialize async database engine
    engine = init_db(settings.DATABASE_URL)
    if not await check_db_health():
        logger.error("Database health check failed! Unable to connect to PostgreSQL.")
        raise RuntimeError("Database connection failure on startup.")
    logger.info("Database connection established and verified healthy.")

    session_factory = get_session_factory()

    # Bootstrap default records
    await bootstrap_database(session_factory, settings)

    # Initialize Bot & Dispatcher
    bot, dp = create_bot_and_dispatcher(settings, session_factory)

    # Initialize Scheduler
    scheduler = SchedulingService(bot=bot, session_factory=session_factory, settings=settings)
    scheduler.start()
    logger.info("Persistent scheduling service started.")

    # Graceful shutdown handler
    stop_event = asyncio.Event()

    def signal_handler():
        logger.info("Received termination signal. Initiating graceful shutdown...")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, signal_handler)
        except NotImplementedError:
            # Windows may not support add_signal_handler for all signals
            pass

    try:
        logger.info("Bot is now polling for Telegram updates...")
        polling_task = asyncio.create_task(dp.start_polling(bot))

        # Wait until termination signal or polling exit
        done, pending = await asyncio.wait(
            [polling_task, asyncio.create_task(stop_event.wait())],
            return_when=asyncio.FIRST_COMPLETED,
        )

        for task in pending:
            task.cancel()

    finally:
        logger.info("Shutting down services...")
        await scheduler.stop()
        await bot.session.close()
        await engine.dispose()
        logger.info("Cleanup completed. Bot stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot execution terminated.")
