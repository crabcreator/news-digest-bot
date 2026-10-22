"""/start, /help, /cancel and block/unblock tracking."""

import html
import logging

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import ChatMemberUpdated, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.reply import main_menu
from bot.utils import ensure_user
from core.config import Settings
from db import crud

logger = logging.getLogger(__name__)

HELP_TEXT = (
    "<b>Команди</b>\n"
    "/now — дайджест за останні 4 години\n"
    "/settings — час доставки та теми\n"
    "/cancel — скасувати поточну дію\n"
    "/help — ця довідка\n\n"
    "Щодня у вибраний час я надсилаю короткий дайджест головних новин "
    "з Суспільного, BBC Україна та Української правди."
)


async def cmd_start(message: Message, session: AsyncSession, settings: Settings, state: FSMContext) -> None:
    await state.clear()
    if message.from_user is None:
        return
    user = await ensure_user(session, message.from_user, settings, reactivate=True)
    name = html.escape(message.from_user.first_name or "друже")
    await message.answer(
        f"👋 Привіт, {name}!\n\n"
        "Я щодня надсилаю дайджест головних новин України.\n"
        f"⏰ Зараз доставка о <b>{user.delivery_hour:02d}:{user.delivery_minute:02d}</b> ({html.escape(user.timezone)}).\n\n"
        "Змінити час і теми: /settings\n"
        "Отримати дайджест просто зараз: /now",
        reply_markup=main_menu(),
    )


async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT, reply_markup=main_menu())


async def cmd_cancel(message: Message, state: FSMContext) -> None:
    if await state.get_state() is None:
        await message.answer("Немає активної дії для скасування.")
        return
    await state.clear()
    await message.answer("Дію скасовано.", reply_markup=main_menu())


async def on_my_chat_member(event: ChatMemberUpdated, session: AsyncSession) -> None:
    """Keep `is_active` in sync when a user blocks or unblocks the bot."""
    if event.chat.type != "private":
        return
    status = event.new_chat_member.status
    if status in ("kicked", "left"):
        await crud.set_active(session, event.chat.id, False)
        logger.info("User %s blocked the bot", event.chat.id)
    elif status == "member":
        if await crud.get_user(session, event.chat.id) is not None:
            await crud.set_active(session, event.chat.id, True)


def create_router() -> Router:
    router = Router(name="common")
    router.message.register(cmd_start, CommandStart())
    router.message.register(cmd_help, Command("help"))
    router.message.register(cmd_cancel, Command("cancel"))
    router.my_chat_member.register(on_my_chat_member)
    return router
