from datetime import datetime, timedelta

from db import crud
from db.models import utcnow


async def test_user_defaults_and_categories(session):
    user = await crud.get_or_create_user(session, 1, "nick", "Nikita")
    assert user.delivery_hour == 21 and user.delivery_minute == 0
    assert user.timezone == "Europe/Kyiv"
    assert len(user.category_list) == 8 and user.categories == "all"

    user = await crud.toggle_category(session, 1, "culture")
    assert "culture" not in user.category_list and len(user.category_list) == 7
    user = await crud.toggle_category(session, 1, "culture")
    assert user.categories == "all"


async def test_due_users_respects_timezone(session):
    await crud.get_or_create_user(session, 1)
    await crud.set_delivery_time(session, 1, 21, 0)
    # 21:00 Kyiv in October (EEST, UTC+3) == 18:00 UTC; in January (EET) == 19:00 UTC
    assert [u.id for u in await crud.get_due_users(session, datetime(2026, 10, 22, 18, 0))] == [1]
    assert await crud.get_due_users(session, datetime(2026, 10, 22, 19, 0)) == []
    assert [u.id for u in await crud.get_due_users(session, datetime(2026, 1, 22, 19, 0))] == [1]

    await crud.set_active(session, 1, False)
    assert await crud.get_due_users(session, datetime(2026, 10, 22, 18, 0)) == []


async def test_news_dedup_and_window(session):
    now = utcnow()
    item = crud.NewsItemData("https://x/1", "Title", "Src", now - timedelta(hours=1))
    old = crud.NewsItemData("https://x/2", "Old", "Src", now - timedelta(hours=48))
    assert await crud.add_news_items(session, [item, old]) == 2
    assert await crud.add_news_items(session, [item]) == 0  # duplicate ignored

    window = await crud.get_news_window(session, 24)
    assert [n.url for n in window] == ["https://x/1"]


async def test_digest_cache_and_delivery_log(session):
    await crud.get_or_create_user(session, 1)
    today = utcnow().date()
    assert await crud.get_digest(session, today) is None
    digest = await crud.save_digest(session, today, "hello")
    assert (await crud.get_digest(session, today)).id == digest.id

    assert not await crud.was_delivered_since(session, 1, utcnow() - timedelta(hours=1))
    await crud.log_delivery(session, 1, digest.id, "sent")
    assert await crud.was_delivered_since(session, 1, utcnow() - timedelta(hours=1))


def test_category_group_is_stable():
    assert crud.make_category_group(["b", "a", "a"]) == "a,b"


async def test_sqlite_pragmas(session):
    from sqlalchemy import text

    result = await session.execute(text("PRAGMA busy_timeout;"))
    assert result.scalar() == 10000


async def test_prune_old_data(session):
    now = utcnow()
    await crud.get_or_create_user(session, 1)

    # News
    fresh_news = crud.NewsItemData("https://x/fresh", "Fresh", "Src", now - timedelta(days=2))
    old_news = crud.NewsItemData("https://x/old", "Old", "Src", now - timedelta(days=20))
    await crud.add_news_items(session, [fresh_news, old_news])

    # Digest
    await crud.save_digest(session, (now - timedelta(days=40)).date(), "old digest")
    fresh_digest = await crud.save_digest(session, now.date(), "fresh digest")

    # Delivery log
    await crud.log_delivery(session, 1, fresh_digest.id, "sent")
    from db.models import UserDeliveryLog
    from sqlalchemy import update
    # create an artificially old log
    await session.execute(
        update(UserDeliveryLog).where(UserDeliveryLog.id == 1).values(sent_at=now - timedelta(days=45))
    )
    await crud.log_delivery(session, 1, fresh_digest.id, "sent")  # fresh log

    deleted = await crud.prune_old_data(session, news_retention_days=14, digest_retention_days=30, log_retention_days=30, now=now)
    assert deleted == (1, 1, 1)

    # Verify fresh remain
    news = await crud.get_news_window(session, hours=100)
    assert len(news) == 1 and news[0].url == "https://x/fresh"
    assert await crud.get_digest(session, now.date()) is not None
    assert await crud.was_delivered_since(session, 1, now - timedelta(days=1))

    # Optimize doesn't crash
    await crud.optimize_db(session)


async def test_set_user_timezone(session):
    import pytest

    user = await crud.get_or_create_user(session, 10)
    assert user.timezone == "Europe/Kyiv"

    updated = await crud.set_user_timezone(session, 10, "Europe/Warsaw")
    assert updated.timezone == "Europe/Warsaw"

    # Non-existent user returns None
    assert await crud.set_user_timezone(session, 999, "Europe/London") is None

    # Invalid timezone raises ValueError
    with pytest.raises(ValueError, match="Invalid timezone"):
        await crud.set_user_timezone(session, 10, "Invalid/Unknown_Zone")


async def test_get_system_stats(session):
    now = utcnow()
    u1 = await crud.get_or_create_user(session, 101)
    u2 = await crud.get_or_create_user(session, 102)
    await crud.set_active(session, 102, False)

    # News: 1 recent, 1 old
    n1 = crud.NewsItemData("https://y/1", "T1", "Src", now - timedelta(hours=2))
    n2 = crud.NewsItemData("https://y/2", "T2", "Src", now - timedelta(hours=48))
    await crud.add_news_items(session, [n1, n2])

    # Digest
    d = await crud.save_digest(session, now.date(), "digest content")

    # Delivery logs: 1 sent recent, 1 sent old, 1 failed
    await crud.log_delivery(session, 101, d.id, "sent")
    await crud.log_delivery(session, 102, d.id, "failed")

    stats = await crud.get_system_stats(session, now=now)
    assert stats.total_users == 2
    assert stats.active_users == 1
    assert stats.total_news == 2
    assert stats.news_last_24h == 1
    assert stats.total_digests == 1
    assert stats.deliveries_last_24h == 1

