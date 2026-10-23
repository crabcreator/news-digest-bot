"""APScheduler initialisation (AsyncIOScheduler running inside the bot's event loop)."""

from datetime import datetime, timezone

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from core.config import Settings
from services.scheduler.jobs import (
    SessionFactory,
    check_and_send_scheduled_digests,
    cleanup_old_data,
    fetch_and_store_rss_news,
)
from services.summarizer.gemini_client import GeminiSummarizer


def create_scheduler(
    settings: Settings,
    bot: Bot,
    session_factory: SessionFactory,
    summarizer: GeminiSummarizer,
) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=timezone.utc)

    scheduler.add_job(
        fetch_and_store_rss_news,
        trigger="interval",
        minutes=settings.fetch_interval_minutes,
        args=[session_factory],
        id="fetch_rss",
        max_instances=1,
        coalesce=True,
        # Startup (DB init, bot commands) can take seconds; the default 1s grace would skip the first run.
        misfire_grace_time=300,
        next_run_time=datetime.now(timezone.utc),  # populate the DB right at startup
    )
    scheduler.add_job(
        check_and_send_scheduled_digests,
        trigger="cron",
        minute="*",
        args=[bot, session_factory, summarizer],
        id="send_digests",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=30,
    )
    scheduler.add_job(
        cleanup_old_data,
        trigger="cron",
        hour=3,
        minute=0,
        args=[session_factory],
        id="cleanup_data",
        max_instances=1,
        coalesce=True,
    )
    return scheduler
