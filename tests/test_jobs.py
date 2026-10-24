from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import SendMessage
from sqlalchemy import select

from db import crud
from db.models import UserDeliveryLog, utcnow
from services.scheduler import jobs
from services.scheduler.scheduler_mgr import create_scheduler
from services.summarizer.gemini_client import SummarizationError, Topic

# 21:00 Kyiv (EEST, UTC+3) on 2026-10-22
DELIVERY_MOMENT = datetime(2026, 10, 22, 18, 0)


class FakeSummarizer:
    def __init__(self, error=None):
        self.calls, self.error = 0, error

    async def generate_topics(self, items, categories, window_hours):
        self.calls += 1
        if self.error:
            raise self.error
        return [Topic(category="war", headline="H", summary="S", source_id=items[0].id)]


def make_bot(side_effect=None):
    bot = MagicMock()
    bot.send_message = AsyncMock(side_effect=side_effect)
    return bot


async def seed(session_factory, users=(1, 2)):
    async with session_factory() as db:
        for uid in users:
            await crud.get_or_create_user(db, uid)
        await crud.add_news_items(
            db, [crud.NewsItemData("https://e.com/1", "T", "Src", DELIVERY_MOMENT - timedelta(hours=2), "war", "x")]
        )


async def logs(session_factory):
    async with session_factory() as db:
        return [(r.user_id, r.status) for r in (await db.scalars(select(UserDeliveryLog).order_by(UserDeliveryLog.id)))]


async def test_sends_to_due_users_with_one_generation(session_factory):
    await seed(session_factory)
    bot, summarizer = make_bot(), FakeSummarizer()
    sent = await jobs.check_and_send_scheduled_digests(bot, session_factory, summarizer, DELIVERY_MOMENT)
    assert sent == 2 and summarizer.calls == 1  # shared digest for identical category sets
    assert bot.send_message.await_count == 2
    assert sorted(await logs(session_factory)) == [(1, "sent"), (2, "sent")]


async def test_nothing_due_at_other_minute(session_factory):
    await seed(session_factory)
    bot, summarizer = make_bot(), FakeSummarizer()
    assert await jobs.check_and_send_scheduled_digests(bot, session_factory, summarizer, DELIVERY_MOMENT + timedelta(minutes=1)) == 0
    assert bot.send_message.await_count == 0 and summarizer.calls == 0


async def test_no_duplicate_delivery_when_job_reruns(session_factory):
    # Delivery logs are stamped with the real clock, so use the real "now" as the delivery minute.
    real_now = utcnow()
    async with session_factory() as db:
        await crud.get_or_create_user(db, 1)
        await crud.set_delivery_time(db, 1, *_kyiv_hm(real_now))
        await crud.add_news_items(
            db, [crud.NewsItemData("https://e.com/2", "T2", "Src", real_now - timedelta(hours=1), "war", "x")]
        )
    bot, summarizer = make_bot(), FakeSummarizer()
    assert await jobs.check_and_send_scheduled_digests(bot, session_factory, summarizer, real_now) == 1
    assert await jobs.check_and_send_scheduled_digests(bot, session_factory, summarizer, real_now) == 0
    assert bot.send_message.await_count == 1


def _kyiv_hm(naive_utc):
    from zoneinfo import ZoneInfo
    local = naive_utc.replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo("Europe/Kyiv"))
    return local.hour, local.minute


async def test_blocked_user_is_deactivated_others_still_served(session_factory):
    await seed(session_factory)

    async def send(chat_id, *args, **kwargs):
        if chat_id == 1:
            raise TelegramForbiddenError(SendMessage(chat_id=1, text="x"), "Forbidden: bot was blocked by the user")

    bot = make_bot(side_effect=send)
    sent = await jobs.check_and_send_scheduled_digests(bot, session_factory, FakeSummarizer(), DELIVERY_MOMENT)
    assert sent == 1
    async with session_factory() as db:
        assert (await crud.get_user(db, 1)).is_active is False
        assert (await crud.get_user(db, 2)).is_active is True
    assert sorted(await logs(session_factory)) == [(1, "blocked"), (2, "sent")]


async def test_gemini_failure_falls_back_to_headline_digest(session_factory):
    await seed(session_factory)
    bot = make_bot()
    summarizer = FakeSummarizer(error=SummarizationError("overloaded"))
    assert await jobs.check_and_send_scheduled_digests(bot, session_factory, summarizer, DELIVERY_MOMENT) == 2
    text = bot.send_message.await_args.args[1]
    assert "ШІ-підсумок тимчасово недоступний" in text and "🔗" in text
    assert sorted(await logs(session_factory)) == [(1, "sent"), (2, "sent")]


async def test_generation_failure_without_usable_items_is_logged_not_raised(session_factory):
    async with session_factory() as db:
        for uid in (1, 2):
            await crud.get_or_create_user(db, uid)
        # Uncategorised item: the fallback cannot place it, so there is nothing to send.
        await crud.add_news_items(
            db, [crud.NewsItemData("https://e.com/9", "T", "Src", DELIVERY_MOMENT - timedelta(hours=2), None, "x")]
        )
    bot = make_bot()
    summarizer = FakeSummarizer(error=SummarizationError("quota"))
    assert await jobs.check_and_send_scheduled_digests(bot, session_factory, summarizer, DELIVERY_MOMENT) == 0
    assert bot.send_message.await_count == 0
    assert sorted(await logs(session_factory)) == [(1, "failed"), (2, "failed")]


async def test_empty_news_window_sends_calm_notice(session_factory):
    async with session_factory() as db:
        await crud.get_or_create_user(db, 1)
    bot, summarizer = make_bot(), FakeSummarizer()
    assert await jobs.check_and_send_scheduled_digests(bot, session_factory, summarizer, DELIVERY_MOMENT) == 1
    assert summarizer.calls == 0
    assert "нічого значущого" in bot.send_message.await_args.args[1]


async def test_fetch_job_swallows_errors(session_factory, monkeypatch):
    monkeypatch.setattr(jobs, "ingest_feeds", AsyncMock(side_effect=RuntimeError("network down")))
    assert await jobs.fetch_and_store_rss_news(session_factory) == 0


async def test_scheduler_has_jobs():
    from core.config import Settings

    settings = Settings(bot_token="1:T", gemini_api_key="k", _env_file=None)
    scheduler = create_scheduler(settings, MagicMock(), MagicMock(), MagicMock())
    jobs_by_id = {j.id: j for j in scheduler.get_jobs()}
    assert set(jobs_by_id) == {"fetch_rss", "send_digests", "cleanup_data"}
    # Regression: the startup fetch was skipped as "missed" when bot startup took >1s.
    assert jobs_by_id["fetch_rss"].misfire_grace_time >= 60


async def test_cleanup_job_executes(session_factory):
    res = await jobs.cleanup_old_data(session_factory)
    assert res == (0, 0, 0)


async def test_scheduled_delivery_sends_world_digest_as_second_message(session_factory):
    # User 1 has world active, User 2 does not
    await seed(session_factory, users=(1, 2))
    async with session_factory() as db:
        await crud.set_world_active(db, 1, True)
        # Add world news item
        await crud.add_news_items(
            db, [crud.NewsItemData("https://e.com/w1", "WT", "WorldSrc", DELIVERY_MOMENT - timedelta(hours=2), "war", "wx", scope="world")]
        )

    bot, summarizer = make_bot(), FakeSummarizer()
    sent = await jobs.check_and_send_scheduled_digests(bot, session_factory, summarizer, DELIVERY_MOMENT)
    assert sent == 2  # 2 primary users served
    # Bot sent messages: User 1 got UA + World (2 messages), User 2 got UA (1 message) -> total 3 messages sent
    assert bot.send_message.await_count == 3

