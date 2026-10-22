"""Bot and Dispatcher setup."""

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.handlers import common, digest, settings as settings_handlers
from bot.middlewares.db_session import DbSessionMiddleware
from core.config import Settings
from services.summarizer.gemini_client import GeminiSummarizer

BOT_COMMANDS = [
    BotCommand(command="now", description="Дайджест за останні 4 години"),
    BotCommand(command="settings", description="Час доставки та теми"),
    BotCommand(command="help", description="Довідка"),
    BotCommand(command="cancel", description="Скасувати поточну дію"),
]


def create_bot(settings: Settings) -> Bot:
    # HTML is the default parse mode: every dynamic string must go through html.escape().
    return Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))


def create_dispatcher(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    summarizer: GeminiSummarizer,
) -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage(), settings=settings, summarizer=summarizer)
    middleware = DbSessionMiddleware(session_factory)
    dp.update.outer_middleware(middleware)

    # Order matters: commands in `settings`/`digest` must win over the FSM text handler's fallthrough.
    dp.include_router(common.create_router())
    dp.include_router(settings_handlers.create_router())
    dp.include_router(digest.create_router())
    return dp


async def setup_bot_commands(bot: Bot) -> None:
    await bot.set_my_commands(BOT_COMMANDS)
