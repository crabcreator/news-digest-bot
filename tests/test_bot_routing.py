"""End-to-end routing tests: real Dispatcher + fake Telegram session + in-memory DB."""

from datetime import datetime

import pytest
import pytest_asyncio
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import SendMessage, TelegramMethod
from aiogram.types import Chat, Message, Update
from aiogram.types import User as TgUser

from bot.bot_instance import create_bot, create_dispatcher
from core.config import Settings
from core.database import create_engine, create_session_factory, init_db
from db import crud
from services.summarizer.digest_service import DigestResult


class FakeSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.requests: list[TelegramMethod] = []

    async def close(self): ...

    async def make_request(self, bot, method, timeout=None):
        self.requests.append(method)
        if isinstance(method, SendMessage):
            return Message(message_id=len(self.requests), date=datetime.now(), chat=Chat(id=method.chat_id, type="private"), text=method.text).as_(bot)
        return True

    async def stream_content(self, *args, **kwargs):  # pragma: no cover
        yield b""


@pytest_asyncio.fixture
async def app():
    settings = Settings(bot_token="123456:TESTTOKEN", gemini_api_key="k", _env_file=None)
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    factory = create_session_factory(engine)

    class StubSummarizer:
        pass

    dp = create_dispatcher(settings, factory, StubSummarizer())
    bot = create_bot(settings)
    fake = FakeSession()
    bot.session = fake
    yield dp, bot, fake, factory
    await engine.dispose()


_update_id = 0


def text_update(text: str, user_id: int = 42) -> Update:
    global _update_id
    _update_id += 1
    user = TgUser(id=user_id, is_bot=False, first_name="Nik", username="nik")
    msg = Message(message_id=_update_id, date=datetime.now(), chat=Chat(id=user_id, type="private"), from_user=user, text=text,
                  entities=[{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}] if text.startswith("/") else None)
    return Update(update_id=_update_id, message=msg)


def sent_texts(fake):
    return [m.text for m in fake.requests if isinstance(m, SendMessage)]


async def test_start_registers_user(app):
    dp, bot, fake, factory = app
    await dp.feed_update(bot, text_update("/start"))
    async with factory() as s:
        user = await crud.get_user(s, 42)
    assert user and user.delivery_hour == 21 and user.is_active
    assert "Привіт, Nik" in sent_texts(fake)[0]


async def test_settings_command_and_custom_time_flow(app):
    dp, bot, fake, factory = app
    await dp.feed_update(bot, text_update("/settings"))
    assert "Налаштування" in sent_texts(fake)[-1]

    # simulate pressing the custom-time button by feeding the state directly through the callback path
    from aiogram.fsm.storage.base import StorageKey
    from bot.handlers.settings import SettingsStates

    key = StorageKey(bot_id=bot.id, chat_id=42, user_id=42)
    await dp.storage.set_state(key, SettingsStates.waiting_time)

    await dp.feed_update(bot, text_update("not a time"))
    assert "Не схоже на час" in sent_texts(fake)[-1]

    await dp.feed_update(bot, text_update("07:45"))
    assert "07:45" in sent_texts(fake)[-1]
    async with factory() as s:
        user = await crud.get_user(s, 42)
    assert (user.delivery_hour, user.delivery_minute) == (7, 45)
    assert await dp.storage.get_state(key) is None


async def test_commands_work_while_waiting_for_time(app, monkeypatch):
    dp, bot, fake, factory = app
    from aiogram.fsm.storage.base import StorageKey
    from bot.handlers import digest
    from bot.handlers.settings import SettingsStates

    async def fake_generate(*args, **kwargs):
        return DigestResult("DIGEST", 1, False)

    monkeypatch.setattr(digest, "get_or_generate_digest", fake_generate)
    key = StorageKey(bot_id=bot.id, chat_id=42, user_id=42)
    await dp.storage.set_state(key, SettingsStates.waiting_time)

    await dp.feed_update(bot, text_update("/now"))
    assert "DIGEST" in sent_texts(fake)

    await dp.feed_update(bot, text_update("/cancel"))
    assert "скасовано" in sent_texts(fake)[-1]
    assert await dp.storage.get_state(key) is None
