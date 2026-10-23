import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.methods import SendMessage
from aiogram.types import Message

from bot.bot_instance import create_bot, create_dispatcher
from bot.handlers import settings as settings_handlers
from bot.handlers.digest import cmd_now
from bot.keyboards.inline import (
    ActionCB,
    CategoryCB,
    TimeCB,
    TimezoneCB,
    settings_keyboard,
    timezone_keyboard,
)
from core.config import Settings
from db import crud
from services import delivery
from services.summarizer.gemini_client import SummarizationError

METHOD = SendMessage(chat_id=1, text="x")


def make_settings():
    return Settings(bot_token="123456:TESTTOKEN", gemini_api_key="k", _env_file=None)


# ------------------------------------------------------------------ settings helpers


@pytest.mark.parametrize(
    "text,expected",
    [("07:30", (7, 30)), ("7.05", (7, 5)), (" 23:59 ", (23, 59)), ("24:00", None), ("12:60", None), ("abc", None), ("1230", None)],
)
def test_parse_time(text, expected):
    assert settings_handlers.parse_time(text) == expected


async def test_settings_keyboard_marks_selection(session):
    user = await crud.get_or_create_user(session, 1)
    await crud.toggle_category(session, 1, "culture")
    await session.refresh(user)
    kb = settings_keyboard(user)
    labels = [b.text for row in kb.inline_keyboard for b in row]
    assert "✅ 21:00" in labels and "13:00" in labels
    assert any(l.startswith("▫️") and "Культура" in l for l in labels)
    assert sum(1 for l in labels if l.startswith("✅") and "21:00" not in l) == 5
    assert any("Вимкнути" in l for l in labels)
    # callback data must fit Telegram's 64-byte limit
    assert all(len(b.callback_data.encode()) <= 64 for row in kb.inline_keyboard for b in row)


async def test_cannot_disable_last_category(session):
    user = await crud.get_or_create_user(session, 1)
    user.category_list = ["war"]
    await session.commit()
    callback = MagicMock(from_user=MagicMock(id=1, username="u", first_name="n"), answer=AsyncMock(), message=None)
    await settings_handlers.on_category_toggled(callback, CategoryCB(key="war"), session, make_settings())
    callback.answer.assert_awaited_once()
    assert callback.answer.await_args.kwargs.get("show_alert") is True
    await session.refresh(user)
    assert user.category_list == ["war"]


async def test_time_callback_updates_user(session):
    await crud.get_or_create_user(session, 1)
    callback = MagicMock(from_user=MagicMock(id=1, username="u", first_name="n"), answer=AsyncMock(), message=None)
    await settings_handlers.on_time_selected(callback, TimeCB(hour=8, minute=0), session, make_settings())
    user = await crud.get_user(session, 1)
    assert (user.delivery_hour, user.delivery_minute) == (8, 0)


async def test_timezone_keyboard_and_callbacks(session):
    user = await crud.get_or_create_user(session, 1)
    kb = timezone_keyboard(user.timezone)
    labels = [b.text for row in kb.inline_keyboard for b in row]
    assert any("✅" in l and "Київ" in l for l in labels)
    assert any("Варшава" in l for l in labels)
    assert any("Назад" in l for l in labels)
    assert all(len(b.callback_data.encode()) <= 64 for row in kb.inline_keyboard for b in row)

    # on_pick_timezone
    msg = MagicMock(spec=Message, edit_text=AsyncMock())
    callback = MagicMock(from_user=MagicMock(id=1, username="u", first_name="n"), answer=AsyncMock(), message=msg)
    await settings_handlers.on_pick_timezone(callback, session, make_settings())
    msg.edit_text.assert_awaited_once()
    assert "часовий пояс" in msg.edit_text.await_args.args[0].lower()

    # on_timezone_selected
    await settings_handlers.on_timezone_selected(
        callback, TimezoneCB(name="Europe/Warsaw"), session, make_settings()
    )
    user = await crud.get_user(session, 1)
    assert user.timezone == "Europe/Warsaw"

    # on_back_to_settings
    msg.edit_text.reset_mock()
    await settings_handlers.on_back_to_settings(callback, session, make_settings())
    msg.edit_text.assert_awaited_once()


# ------------------------------------------------------------------ delivery


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    sleeps = []

    async def fake_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr(delivery.asyncio, "sleep", fake_sleep)
    return sleeps


async def test_send_retries_after_flood_wait(no_sleep):
    bot = MagicMock()
    bot.send_message = AsyncMock(side_effect=[TelegramRetryAfter(METHOD, "flood", 3), None])
    assert await delivery.send_digest_text(bot, 1, "hi") == "sent"
    assert bot.send_message.await_count == 2 and no_sleep == [4]
    kwargs = bot.send_message.await_args.kwargs
    assert kwargs["parse_mode"] == "HTML" and kwargs["link_preview_options"].is_disabled is True


async def test_send_reports_blocked_user():
    bot = MagicMock()
    bot.send_message = AsyncMock(side_effect=TelegramForbiddenError(METHOD, "Forbidden: bot was blocked by the user"))
    assert await delivery.send_digest_text(bot, 1, "hi") == "blocked"


async def test_send_falls_back_to_plain_text_on_parse_error():
    bot = MagicMock()
    bot.send_message = AsyncMock(side_effect=[TelegramBadRequest(METHOD, "can't parse entities: bad tag"), None])
    assert await delivery.send_digest_text(bot, 1, "<b>hi</b>") == "sent"
    assert bot.send_message.await_args.args[1] == "hi"
    assert bot.send_message.await_args.kwargs["parse_mode"] is None


async def test_send_splits_long_digest():
    bot = MagicMock()
    bot.send_message = AsyncMock()
    long_text = "\n\n───────────────\n\n".join("слово " * 400 for _ in range(4))
    assert await delivery.send_digest_text(bot, 1, long_text) == "sent"
    assert bot.send_message.await_count > 1


async def test_deliver_digest_deactivates_blocked_user(session):
    await crud.get_or_create_user(session, 1)
    bot = MagicMock()
    bot.send_message = AsyncMock(side_effect=TelegramForbiddenError(METHOD, "Forbidden"))
    assert await delivery.deliver_digest(bot, session, 1, "hi", None) == "blocked"
    user = await crud.get_user(session, 1)
    await session.refresh(user)
    assert user.is_active is False


# ------------------------------------------------------------------ /now handler


async def test_now_reports_summarizer_failure(session, monkeypatch):
    from bot.handlers import digest

    status_message = MagicMock(edit_text=AsyncMock(), delete=AsyncMock())
    message = MagicMock(from_user=MagicMock(id=1, username="u", first_name="n"), answer=AsyncMock(return_value=status_message))
    monkeypatch.setattr(digest, "get_or_generate_digest", AsyncMock(side_effect=SummarizationError("boom")))
    await cmd_now(message, MagicMock(), session, make_settings(), MagicMock())
    status_message.edit_text.assert_awaited_once()
    assert 1 not in digest._in_flight  # guard released


async def test_now_reports_unexpected_failure(session, monkeypatch):
    from bot.handlers import digest

    status_message = MagicMock(edit_text=AsyncMock(), delete=AsyncMock())
    message = MagicMock(from_user=MagicMock(id=1, username="u", first_name="n"), answer=AsyncMock(return_value=status_message))
    monkeypatch.setattr(digest, "get_or_generate_digest", AsyncMock(side_effect=RuntimeError("db exploded")))
    await cmd_now(message, MagicMock(), session, make_settings(), MagicMock())
    status_message.edit_text.assert_awaited_once()
    assert "неочікувана помилка" in status_message.edit_text.await_args.args[0]
    assert 1 not in digest._in_flight


async def test_now_survives_status_delete_failure(session, monkeypatch):
    from bot.handlers import digest
    from services.summarizer.digest_service import DigestResult

    status_message = MagicMock(
        edit_text=AsyncMock(), delete=AsyncMock(side_effect=TelegramBadRequest(METHOD, "message to delete not found"))
    )
    message = MagicMock(from_user=MagicMock(id=1, username="u", first_name="n"), answer=AsyncMock(return_value=status_message))
    monkeypatch.setattr(digest, "get_or_generate_digest", AsyncMock(return_value=DigestResult("TEXT", 5, False)))
    send = AsyncMock(return_value="sent")
    monkeypatch.setattr(digest, "send_digest_text", send)
    bot = MagicMock()
    await cmd_now(message, bot, session, make_settings(), MagicMock())
    send.assert_awaited_once_with(bot, 1, "TEXT")


async def test_now_sends_digest(session, monkeypatch):
    from bot.handlers import digest
    from services.summarizer.digest_service import DigestResult

    status_message = MagicMock(edit_text=AsyncMock(), delete=AsyncMock())
    message = MagicMock(from_user=MagicMock(id=1, username="u", first_name="n"), answer=AsyncMock(return_value=status_message))
    monkeypatch.setattr(digest, "get_or_generate_digest", AsyncMock(return_value=DigestResult("TEXT", 5, False)))
    send = AsyncMock(return_value="sent")
    monkeypatch.setattr(digest, "send_digest_text", send)
    bot = MagicMock()
    await cmd_now(message, bot, session, make_settings(), MagicMock())
    send.assert_awaited_once_with(bot, 1, "TEXT")
    status_message.delete.assert_awaited_once()


# ------------------------------------------------------------------ wiring


async def test_dispatcher_builds():
    settings = make_settings()
    bot = create_bot(settings)
    dp = create_dispatcher(settings, MagicMock(), MagicMock())
    assert {r.name for r in dp.sub_routers} == {"common", "settings", "digest"}
    await bot.session.close()


async def test_cmd_stats_restricted(session):
    from bot.handlers.common import cmd_stats

    settings = Settings(bot_token="t", gemini_api_key="k", admin_ids=[777], _env_file=None)
    # Non-admin
    msg_user = MagicMock(from_user=MagicMock(id=111), answer=AsyncMock())
    await cmd_stats(msg_user, session, settings)
    msg_user.answer.assert_not_called()

    # Admin
    msg_admin = MagicMock(from_user=MagicMock(id=777), answer=AsyncMock())
    await cmd_stats(msg_admin, session, settings)
    msg_admin.answer.assert_awaited_once()
    assert "Статистика бота" in msg_admin.answer.await_args.args[0]
