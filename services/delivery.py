"""Resilient Telegram delivery of digests (flood control, blocked users, network errors)."""

import asyncio
import logging
import re
from typing import Literal

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
)
from aiogram.types import LinkPreviewOptions
from sqlalchemy.ext.asyncio import AsyncSession

from db import crud
from services.summarizer.formatter import split_message

logger = logging.getLogger(__name__)

SendStatus = Literal["sent", "blocked", "failed"]

MAX_ATTEMPTS = 5
MAX_RETRY_AFTER_SECONDS = 60
_BLOCKED_BAD_REQUEST_MARKERS = ("chat not found", "user is deactivated", "bot was blocked", "peer_id_invalid")
_TAG_RE = re.compile(r"<[^>]+>")


async def _send_chunk(bot: Bot, chat_id: int, text: str, base_delay: float) -> SendStatus:
    parse_mode: str | None = ParseMode.HTML
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            await bot.send_message(
                chat_id,
                text,
                parse_mode=parse_mode,
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )
            return "sent"
        except TelegramRetryAfter as exc:  # FloodWait: honour the server-provided delay
            delay = min(exc.retry_after + 1, MAX_RETRY_AFTER_SECONDS)
            logger.warning("FloodWait for %s: sleeping %ss (attempt %d)", chat_id, delay, attempt)
            await asyncio.sleep(delay)
        except TelegramForbiddenError:
            return "blocked"
        except TelegramBadRequest as exc:
            message = str(exc).lower()
            if any(marker in message for marker in _BLOCKED_BAD_REQUEST_MARKERS):
                return "blocked"
            if parse_mode == ParseMode.HTML and "parse entities" in message:
                # Last-resort fallback: resend as plain text instead of losing the digest.
                logger.error("HTML parse error for %s, resending as plain text: %s", chat_id, exc)
                parse_mode, text = None, _TAG_RE.sub("", text)
                continue
            logger.error("Bad request while sending to %s: %s", chat_id, exc)
            return "failed"
        except TelegramNetworkError as exc:
            delay = base_delay * 2 ** (attempt - 1)
            logger.warning("Network error for %s (attempt %d): %s; retry in %.1fs", chat_id, attempt, exc, delay)
            await asyncio.sleep(delay)
        except TelegramAPIError as exc:
            logger.error("Telegram API error for %s: %s", chat_id, exc)
            return "failed"
    return "failed"


async def send_digest_text(bot: Bot, chat_id: int, text: str, base_delay: float = 1.0) -> SendStatus:
    """Send a (possibly long) digest, splitting it into several messages when needed."""
    for chunk in split_message(text):
        status = await _send_chunk(bot, chat_id, chunk, base_delay)
        if status != "sent":
            return status
    return "sent"


async def deliver_digest(
    bot: Bot, db: AsyncSession, user_id: int, text: str, digest_id: int | None
) -> SendStatus:
    """Scheduled delivery: send, write a delivery log entry and deactivate users who blocked the bot."""
    status = await send_digest_text(bot, user_id, text)
    await crud.log_delivery(db, user_id, digest_id, status)
    if status == "blocked":
        await crud.set_active(db, user_id, False)
        logger.info("User %s blocked the bot; deactivated", user_id)
    return status
