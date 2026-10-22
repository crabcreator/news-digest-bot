from datetime import datetime, timedelta

from db import crud
from db.models import utcnow


async def test_user_defaults_and_categories(session):
    user = await crud.get_or_create_user(session, 1, "nick", "Nikita")
    assert user.delivery_hour == 21 and user.delivery_minute == 0
    assert user.timezone == "Europe/Kyiv"
    assert len(user.category_list) == 6 and user.categories == "all"

    user = await crud.toggle_category(session, 1, "culture")
    assert "culture" not in user.category_list and len(user.category_list) == 5
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
