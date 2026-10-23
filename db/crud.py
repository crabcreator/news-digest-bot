"""Repository functions for users, news items, digests and delivery logs."""

import hashlib
import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Digest, NewsItem, User, UserDeliveryLog, utcnow

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- users


async def get_user(session: AsyncSession, user_id: int) -> User | None:
    return await session.get(User, user_id)


async def get_or_create_user(
    session: AsyncSession,
    user_id: int,
    username: str | None = None,
    first_name: str | None = None,
    *,
    delivery_hour: int = 21,
    delivery_minute: int = 0,
    timezone: str = "Europe/Kyiv",
    reactivate: bool = False,
) -> User:
    """Return the user, creating it if needed and refreshing the profile.

    `reactivate=True` (used by /start) re-subscribes users who were deactivated or blocked the bot.
    """
    user = await session.get(User, user_id)
    if user is None:
        user = User(
            id=user_id,
            username=username,
            first_name=first_name,
            delivery_hour=delivery_hour,
            delivery_minute=delivery_minute,
            timezone=timezone,
            categories="all",
            is_active=True,
        )
        session.add(user)
    else:
        user.username = username
        user.first_name = first_name
        if reactivate:
            user.is_active = True
    await session.commit()
    await session.refresh(user)
    return user


async def set_delivery_time(session: AsyncSession, user_id: int, hour: int, minute: int = 0) -> None:
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("Invalid delivery time")
    await session.execute(
        update(User).where(User.id == user_id).values(delivery_hour=hour, delivery_minute=minute)
    )
    await session.commit()


async def toggle_category(session: AsyncSession, user_id: int, category: str) -> User | None:
    user = await session.get(User, user_id)
    if user is None:
        return None
    selected = set(user.category_list)
    selected.symmetric_difference_update({category})
    user.category_list = list(selected)
    await session.commit()
    return user


async def set_active(session: AsyncSession, user_id: int, is_active: bool) -> None:
    await session.execute(update(User).where(User.id == user_id).values(is_active=is_active))
    await session.commit()


async def set_user_timezone(session: AsyncSession, user_id: int, timezone: str) -> User | None:
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"Invalid timezone: {timezone}") from exc
    user = await session.get(User, user_id)
    if user is None:
        return None
    user.timezone = timezone
    await session.commit()
    await session.refresh(user)
    return user


async def get_due_users(session: AsyncSession, now_utc: datetime | None = None) -> list[User]:
    """Active users whose local delivery time (in their own timezone) matches the current minute."""
    now_utc = now_utc or utcnow()
    from datetime import timezone as dt_timezone

    aware_now = now_utc.replace(tzinfo=dt_timezone.utc)
    result = await session.scalars(select(User).where(User.is_active.is_(True)))
    due: list[User] = []
    for user in result:
        try:
            local = aware_now.astimezone(ZoneInfo(user.timezone))
        except ZoneInfoNotFoundError:
            logger.warning("User %s has unknown timezone %r", user.id, user.timezone)
            continue
        if local.hour == user.delivery_hour and local.minute == user.delivery_minute:
            due.append(user)
    return due


# --------------------------------------------------------------------------- news


def make_url_hash(url: str, title: str) -> str:
    return hashlib.sha256(f"{url}\n{title}".encode("utf-8")).hexdigest()


@dataclass(slots=True)
class NewsItemData:
    url: str
    title: str
    source: str
    published_at: datetime  # naive UTC
    category: str | None = None
    summary: str | None = None


async def get_existing_urls(session: AsyncSession, urls: Sequence[str]) -> set[str]:
    """Subset of `urls` that are already stored (queried in chunks to respect SQLite variable limits)."""
    found: set[str] = set()
    for i in range(0, len(urls), 500):
        chunk = list(urls[i : i + 500])
        found.update((await session.scalars(select(NewsItem.url).where(NewsItem.url.in_(chunk)))).all())
    return found


async def add_news_items(session: AsyncSession, items: Iterable[NewsItemData]) -> int:
    """Insert items with ON CONFLICT DO NOTHING on the unique constraints. Returns inserted count."""
    inserted = 0
    for item in items:
        stmt = (
            sqlite_insert(NewsItem)
            .values(
                url=item.url,
                url_hash=make_url_hash(item.url, item.title),
                title=item.title,
                source=item.source,
                category=item.category,
                summary=item.summary,
                published_at=item.published_at,
            )
            .on_conflict_do_nothing()
        )
        result = await session.execute(stmt)
        inserted += result.rowcount or 0
    await session.commit()
    return inserted


async def get_news_since(
    session: AsyncSession,
    since: datetime,
    categories: Sequence[str] | None = None,
    limit: int | None = None,
) -> list[NewsItem]:
    """News published since `since` (naive UTC), newest first. Uncategorised items are always included."""
    stmt = select(NewsItem).where(NewsItem.published_at >= since).order_by(NewsItem.published_at.desc())
    if categories is not None:
        stmt = stmt.where(NewsItem.category.in_(list(categories)) | NewsItem.category.is_(None))
    if limit:
        stmt = stmt.limit(limit)
    return list((await session.scalars(stmt)).all())


async def get_news_window(
    session: AsyncSession, hours: int = 24, categories: Sequence[str] | None = None
) -> list[NewsItem]:
    return await get_news_since(session, utcnow() - timedelta(hours=hours), categories)


async def get_uncategorized_news(session: AsyncSession, since: datetime, limit: int = 100) -> list[NewsItem]:
    stmt = (
        select(NewsItem)
        .where(NewsItem.category.is_(None), NewsItem.published_at >= since)
        .order_by(NewsItem.published_at.desc())
        .limit(limit)
    )
    return list((await session.scalars(stmt)).all())


async def set_news_categories(session: AsyncSession, mapping: dict[int, str]) -> None:
    for news_id, category in mapping.items():
        await session.execute(update(NewsItem).where(NewsItem.id == news_id).values(category=category))
    await session.commit()


# --------------------------------------------------------------------------- digests


def make_category_group(categories: Sequence[str]) -> str:
    """Stable cache key for a set of categories (e.g. 'economy,politics')."""
    return ",".join(sorted(set(categories))) or "all"


async def get_digest(
    session: AsyncSession, target_date: date, category_group: str = "all"
) -> Digest | None:
    stmt = (
        select(Digest)
        .where(Digest.target_date == target_date, Digest.category_group == category_group)
        .order_by(Digest.id.desc())
        .limit(1)
    )
    return await session.scalar(stmt)


async def get_fresh_digest(
    session: AsyncSession,
    target_date: date,
    category_group: str,
    max_age: timedelta,
    now: datetime | None = None,
) -> Digest | None:
    """Latest cached digest for the key that was generated no longer than `max_age` ago."""
    stmt = (
        select(Digest)
        .where(
            Digest.target_date == target_date,
            Digest.category_group == category_group,
            Digest.created_at >= (now or utcnow()) - max_age,
        )
        .order_by(Digest.id.desc())
        .limit(1)
    )
    return await session.scalar(stmt)


async def save_digest(
    session: AsyncSession, target_date: date, content: str, category_group: str = "all"
) -> Digest:
    digest = Digest(target_date=target_date, category_group=category_group, content=content)
    session.add(digest)
    await session.commit()
    await session.refresh(digest)
    return digest


# --------------------------------------------------------------------------- delivery logs


async def log_delivery(
    session: AsyncSession, user_id: int, digest_id: int | None, status: str
) -> UserDeliveryLog:
    entry = UserDeliveryLog(user_id=user_id, digest_id=digest_id, status=status)
    session.add(entry)
    await session.commit()
    return entry


async def was_delivered_since(session: AsyncSession, user_id: int, since: datetime) -> bool:
    """Whether a digest was successfully sent to the user since `since` (naive UTC)."""
    stmt = (
        select(UserDeliveryLog.id)
        .where(
            UserDeliveryLog.user_id == user_id,
            UserDeliveryLog.status == "sent",
            UserDeliveryLog.sent_at >= since,
        )
        .limit(1)
    )
    return await session.scalar(stmt) is not None


# --------------------------------------------------------------------------- maintenance


async def prune_old_data(
    session: AsyncSession,
    news_retention_days: int = 14,
    digest_retention_days: int = 30,
    log_retention_days: int = 30,
    now: datetime | None = None,
) -> tuple[int, int, int]:
    """Delete records older than retention thresholds. Returns (deleted_news, deleted_digests, deleted_logs)."""
    now = now or utcnow()
    news_cutoff = now - timedelta(days=news_retention_days)
    digest_cutoff_date = (now - timedelta(days=digest_retention_days)).date()
    log_cutoff = now - timedelta(days=log_retention_days)

    res_news = await session.execute(delete(NewsItem).where(NewsItem.published_at < news_cutoff))
    res_digests = await session.execute(delete(Digest).where(Digest.target_date < digest_cutoff_date))
    res_logs = await session.execute(delete(UserDeliveryLog).where(UserDeliveryLog.sent_at < log_cutoff))
    await session.commit()
    return (res_news.rowcount or 0, res_digests.rowcount or 0, res_logs.rowcount or 0)


async def optimize_db(session: AsyncSession) -> None:
    """Run SQLite PRAGMA optimize."""
    await session.execute(text("PRAGMA optimize;"))


# --------------------------------------------------------------------------- stats


@dataclass(slots=True)
class SystemStats:
    total_users: int
    active_users: int
    total_news: int
    news_last_24h: int
    total_digests: int
    deliveries_last_24h: int


async def get_system_stats(session: AsyncSession, now: datetime | None = None) -> SystemStats:
    """Aggregate statistics for admin dashboard."""
    now = now or utcnow()
    cutoff_24h = now - timedelta(hours=24)

    total_users = await session.scalar(select(func.count(User.id))) or 0
    active_users = await session.scalar(select(func.count(User.id)).where(User.is_active.is_(True))) or 0
    total_news = await session.scalar(select(func.count(NewsItem.id))) or 0
    news_24h = await session.scalar(select(func.count(NewsItem.id)).where(NewsItem.published_at >= cutoff_24h)) or 0
    total_digests = await session.scalar(select(func.count(Digest.id))) or 0
    deliveries_24h = (
        await session.scalar(
            select(func.count(UserDeliveryLog.id)).where(
                UserDeliveryLog.status == "sent", UserDeliveryLog.sent_at >= cutoff_24h
            )
        )
        or 0
    )
    return SystemStats(
        total_users=total_users,
        active_users=active_users,
        total_news=total_news,
        news_last_24h=news_24h,
        total_digests=total_digests,
        deliveries_last_24h=deliveries_24h,
    )

