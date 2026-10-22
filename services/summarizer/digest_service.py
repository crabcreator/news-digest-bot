"""Digest generation with caching: ties together news selection, Gemini and rendering."""

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from core.categories import ALL_CATEGORY_KEYS
from db import crud
from db.models import utcnow
from services.summarizer.formatter import render_digest, render_empty_digest
from services.summarizer.gemini_client import GeminiSummarizer

logger = logging.getLogger(__name__)

Mode = Literal["daily", "now"]


@dataclass(frozen=True, slots=True)
class DigestProfile:
    window_hours: int
    cache_ttl: timedelta
    group_prefix: str
    window_label: str


PROFILES: dict[Mode, DigestProfile] = {
    # Scheduled digest: the past 24 hours; shared between users with the same categories.
    "daily": DigestProfile(24, timedelta(minutes=60), "", "за добу"),
    # On-demand /now: the past 4 hours; cached briefly so repeated requests don't hit Gemini.
    "now": DigestProfile(4, timedelta(minutes=30), "now:", "за останні 4 години"),
}


@dataclass(frozen=True, slots=True)
class DigestResult:
    text: str  # Telegram HTML
    digest_id: int | None  # None for the "no news" notice (not stored)
    from_cache: bool


# One lock per cache key: users scheduled in the same minute share a single Gemini call.
_locks: dict[str, asyncio.Lock] = {}


def _normalize(categories: Sequence[str]) -> list[str]:
    return [c for c in ALL_CATEGORY_KEYS if c in set(categories)]


def cache_key(categories: Sequence[str], mode: Mode) -> str:
    cats = _normalize(categories)
    group = "all" if len(cats) == len(ALL_CATEGORY_KEYS) else crud.make_category_group(cats)
    return f"{PROFILES[mode].group_prefix}{group}"


async def get_or_generate_digest(
    db: AsyncSession,
    summarizer: GeminiSummarizer,
    categories: Sequence[str],
    mode: Mode = "daily",
    timezone: str = "Europe/Kyiv",
    now_utc: datetime | None = None,
) -> DigestResult:
    """Return a fresh cached digest or generate one.

    Raises `SummarizationError` if Gemini fails after all retries.
    """
    profile = PROFILES[mode]
    cats = _normalize(categories)
    now_utc = now_utc or utcnow()
    target_date = now_utc.replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo(timezone)).date()

    if not cats:
        return DigestResult(render_empty_digest(target_date, profile.window_label), None, False)

    key = cache_key(cats, mode)
    lock = _locks.setdefault(key, asyncio.Lock())
    async with lock:
        cached = await crud.get_fresh_digest(db, target_date, key, profile.cache_ttl, now_utc)
        if cached:
            return DigestResult(cached.content, cached.id, True)

        items = await crud.get_news_since(db, now_utc - timedelta(hours=profile.window_hours), cats)
        if not items:
            return DigestResult(render_empty_digest(target_date, profile.window_label), None, False)

        topics = await summarizer.generate_topics(items, cats, profile.window_hours)
        text = render_digest(topics, items, cats, target_date)
        if text is None:
            # Gemini found nothing significant (or nothing valid): calm notice, not cached.
            return DigestResult(render_empty_digest(target_date, profile.window_label), None, False)

        digest = await crud.save_digest(db, target_date, text, key)
        logger.info("Generated digest %s (%d topics, key=%s)", digest.id, len(topics), key)
        return DigestResult(text, digest.id, False)
