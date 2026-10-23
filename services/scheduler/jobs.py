"""Background jobs: RSS aggregation and scheduled digest delivery."""

import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timedelta

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db import crud
from db.models import User, utcnow
from healthcheck import touch_heartbeat
from services.delivery import deliver_digest
from services.fetcher.rss_client import DEFAULT_FEEDS, FeedSource, ingest_feeds
from services.summarizer.digest_service import cache_key, get_or_generate_digest
from services.summarizer.gemini_client import GeminiSummarizer, SummarizationError

logger = logging.getLogger(__name__)

SessionFactory = async_sessionmaker[AsyncSession]

# Guards against sending twice if the minute-job runs twice for the same minute (e.g. after a misfire).
DUPLICATE_DELIVERY_WINDOW = timedelta(minutes=10)
DELIVERY_CONCURRENCY = 10


async def fetch_and_store_rss_news(
    session_factory: SessionFactory,
    sources: tuple[FeedSource, ...] | list[FeedSource] = DEFAULT_FEEDS,
) -> int:
    """Job 1 (every 30 min): ingest all configured RSS feeds into the database."""
    try:
        async with session_factory() as db:
            return await ingest_feeds(db, sources=sources)
    except Exception:  # noqa: BLE001 - a failed run must not stop the scheduler
        logger.exception("RSS aggregation failed")
        return 0


async def cleanup_old_data(
    session_factory: SessionFactory,
    news_retention_days: int = 14,
    digest_retention_days: int = 30,
    log_retention_days: int = 30,
) -> tuple[int, int, int]:
    """Job 3 (daily): prune old news, digests, and delivery logs, then optimize SQLite."""
    try:
        async with session_factory() as db:
            deleted = await crud.prune_old_data(
                db, news_retention_days, digest_retention_days, log_retention_days
            )
            await crud.optimize_db(db)
            logger.info(
                "Data cleanup finished: pruned %d news, %d digests, %d logs",
                deleted[0],
                deleted[1],
                deleted[2],
            )
            return deleted
    except Exception:  # noqa: BLE001
        logger.exception("Data cleanup job failed")
        return (0, 0, 0)


async def check_and_send_scheduled_digests(
    bot: Bot,
    session_factory: SessionFactory,
    summarizer: GeminiSummarizer,
    now_utc: datetime | None = None,
) -> int:
    """Job 2 (every minute): deliver digests to active users whose local delivery time is now.

    Returns the number of successfully delivered digests.
    """
    touch_heartbeat()
    now_utc = now_utc or utcnow()
    try:
        async with session_factory() as db:
            due = await crud.get_due_users(db, now_utc)
            due = [u for u in due if not await crud.was_delivered_since(db, u.id, now_utc - DUPLICATE_DELIVERY_WINDOW)]
    except Exception:  # noqa: BLE001
        logger.exception("Could not query due users")
        return 0
    if not due:
        return 0

    logger.info("Delivering scheduled digests to %d user(s)", len(due))

    # Users with identical categories (and tech subcategories, and timezone) share one digest -> one Gemini call.
    groups: dict[tuple[str, str], list[User]] = defaultdict(list)
    for user in due:
        key = cache_key(user.category_list, "daily", tech_subcategories=user.tech_subcategory_list)
        groups[(key, user.timezone)].append(user)

    semaphore = asyncio.Semaphore(DELIVERY_CONCURRENCY)
    delivered = 0

    async def send_to(user: User, text: str, digest_id: int | None) -> bool:
        async with semaphore:
            try:
                async with session_factory() as db:
                    return await deliver_digest(bot, db, user.id, text, digest_id) == "sent"
            except Exception:  # noqa: BLE001 - one user's failure must not affect the others
                logger.exception("Delivery to user %s crashed", user.id)
                return False

    for (_, timezone), users in groups.items():
        try:
            async with session_factory() as db:
                result = await get_or_generate_digest(
                    db,
                    summarizer,
                    users[0].category_list,
                    "daily",
                    timezone,
                    now_utc,
                    tech_subcategories=users[0].tech_subcategory_list,
                )
        except SummarizationError:
            logger.exception("Digest generation failed; %d user(s) skipped", len(users))
            async with session_factory() as db:
                for user in users:
                    await crud.log_delivery(db, user.id, None, "failed")
            continue
        except Exception:  # noqa: BLE001
            logger.exception("Unexpected error while generating digest")
            continue

        results = await asyncio.gather(*(send_to(u, result.text, result.digest_id) for u in users))
        delivered += sum(results)

    logger.info("Scheduled delivery finished: %d/%d sent", delivered, len(due))
    return delivered
