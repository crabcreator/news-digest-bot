"""APScheduler initialisation (AsyncIOScheduler running inside the bot's event loop)."""

from datetime import datetime, timezone

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from core.config import Settings
from services.scheduler.jobs import (
    SessionFactory,
    check_and_send_scheduled_digests,
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
    return scheduler
