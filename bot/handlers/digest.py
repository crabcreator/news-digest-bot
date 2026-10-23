"""/now: on-demand digest for the last 4 hours (served from a short-lived cache when available)."""

import logging
from contextlib import suppress

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.utils.chat_action import ChatActionSender
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.reply import BTN_NOW
from bot.utils import ensure_user
from core.config import Settings
from services.delivery import send_digest_text
from services.summarizer.digest_service import get_or_generate_digest
from services.summarizer.gemini_client import GeminiSummarizer, SummarizationError

logger = logging.getLogger(__name__)
# Users whose /now is currently being generated; ignores double-taps while Gemini is working.
_in_flight: set[int] = set()


async def cmd_now(
    message: Message, bot: Bot, session: AsyncSession, settings: Settings, summarizer: GeminiSummarizer
) -> None:
    if message.from_user is None:
        return
    user = await ensure_user(session, message.from_user, settings)
    if user.id in _in_flight:
        await message.answer("⏳ Дайджест уже готується, зачекайте хвилинку.")
        return

    _in_flight.add(user.id)
    status_message = await message.answer("⏳ Готую дайджест за останні 4 години…")
    try:
        async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
            result = await get_or_generate_digest(session, summarizer, user.category_list, "now", user.timezone)
    except SummarizationError:
        logger.exception("/now failed for user %s", user.id)
        with suppress(TelegramAPIError):
            await status_message.edit_text("😔 Не вдалося підготувати дайджест. Спробуйте за кілька хвилин.")
        return
    except Exception:
        logger.exception("Unexpected error during /now for user %s", user.id)
        with suppress(TelegramAPIError):
            await status_message.edit_text("😔 Сталася неочікувана помилка. Спробуйте пізніше.")
        return
    finally:
        _in_flight.discard(user.id)

    with suppress(TelegramAPIError):
        await status_message.delete()
    await send_digest_text(bot, user.id, result.text)


def create_router() -> Router:
    router = Router(name="digest")
    router.message.register(cmd_now, Command("now"))
    router.message.register(cmd_now, F.text == BTN_NOW)
    return router
