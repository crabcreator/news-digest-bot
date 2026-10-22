"""Application entry point."""

import asyncio
import logging

from bot.bot_instance import create_bot, create_dispatcher, setup_bot_commands
from core.config import get_settings
from core.database import create_engine, create_session_factory, init_db
from services.scheduler.scheduler_mgr import create_scheduler
from services.summarizer.gemini_client import GeminiSummarizer

logger = logging.getLogger("main")


def configure_logging(level: str) -> None:
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)-8s %(name)s: %(message)s")
    # Keep third-party chatter out of INFO logs.
    for noisy in ("httpx", "httpcore", "aiohttp", "trafilatura", "htmldate", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    engine = create_engine(settings.database_url)
    await init_db(engine)
    session_factory = create_session_factory(engine)

    summarizer = GeminiSummarizer(
        api_key=settings.gemini_api_key,
        model=settings.gemini_model,
        timeout_seconds=settings.gemini_timeout_seconds,
        max_attempts=settings.gemini_max_attempts,
    )
    bot = create_bot(settings)
    dp = create_dispatcher(settings, session_factory, summarizer)
    scheduler = create_scheduler(settings, bot, session_factory, summarizer)

    try:
        await setup_bot_commands(bot)
        scheduler.start()
        logger.info("Bot started (model=%s)", settings.gemini_model)
        # Drop updates that piled up while the bot was offline.
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        logger.info("Shutting down")
        if scheduler.running:
            scheduler.shutdown(wait=False)
        await bot.session.close()
        await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
