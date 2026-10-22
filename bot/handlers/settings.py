"""/settings: delivery time picker, category toggles, subscription toggle."""

import html
import re

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.inline import ActionCB, CategoryCB, TimeCB, settings_keyboard
from bot.keyboards.reply import BTN_NOW, BTN_SETTINGS, main_menu
from bot.utils import ensure_user
from core.categories import CATEGORY_BY_KEY
from core.config import Settings
from db import crud
from db.models import User


class SettingsStates(StatesGroup):
    waiting_time = State()


_TIME_RE = re.compile(r"^\s*(\d{1,2})\s*[:.]\s*(\d{2})\s*$")


def parse_time(text: str) -> tuple[int, int] | None:
    """Parse 'HH:MM' (also 'H.MM'); returns None for invalid input."""
    match = _TIME_RE.match(text)
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    return (hour, minute) if 0 <= hour <= 23 and 0 <= minute <= 59 else None


def settings_text(user: User) -> str:
    status = "увімкнено ✅" if user.is_active else "вимкнено 🔕"
    return (
        "⚙️ <b>Налаштування</b>\n\n"
        f"⏰ Час доставки: <b>{user.delivery_hour:02d}:{user.delivery_minute:02d}</b> ({html.escape(user.timezone)})\n"
        f"📬 Щоденний дайджест: <b>{status}</b>\n\n"
        "Оберіть час і теми, які вас цікавлять:"
    )


async def _refresh(callback: CallbackQuery, user: User) -> None:
    if not isinstance(callback.message, Message):
        return
    try:
        await callback.message.edit_text(settings_text(user), reply_markup=settings_keyboard(user))
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc):
            raise


async def show_settings(message: Message, session: AsyncSession, settings: Settings, state: FSMContext) -> None:
    await state.clear()
    if message.from_user is None:
        return
    user = await ensure_user(session, message.from_user, settings)
    await message.answer(settings_text(user), reply_markup=settings_keyboard(user))


async def on_time_selected(
    callback: CallbackQuery, callback_data: TimeCB, session: AsyncSession, settings: Settings
) -> None:
    user = await ensure_user(session, callback.from_user, settings)
    await crud.set_delivery_time(session, user.id, callback_data.hour, callback_data.minute)
    await session.refresh(user)
    await callback.answer(f"Час доставки: {callback_data.hour:02d}:{callback_data.minute:02d}")
    await _refresh(callback, user)


async def on_category_toggled(
    callback: CallbackQuery, callback_data: CategoryCB, session: AsyncSession, settings: Settings
) -> None:
    if callback_data.key not in CATEGORY_BY_KEY:
        await callback.answer()
        return
    user = await ensure_user(session, callback.from_user, settings)
    if user.category_list == [callback_data.key]:
        await callback.answer("Потрібна хоча б одна тема", show_alert=True)
        return
    user = await crud.toggle_category(session, user.id, callback_data.key)
    await callback.answer()
    if user:
        await _refresh(callback, user)


async def on_toggle_active(callback: CallbackQuery, session: AsyncSession, settings: Settings) -> None:
    user = await ensure_user(session, callback.from_user, settings)
    await crud.set_active(session, user.id, not user.is_active)
    await session.refresh(user)
    await callback.answer("Дайджест увімкнено" if user.is_active else "Дайджест вимкнено")
    await _refresh(callback, user)


async def on_custom_time(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SettingsStates.waiting_time)
    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.answer(
            "Введіть час доставки у форматі <b>ГГ:ХХ</b> (наприклад, 07:30).\nСкасувати: /cancel"
        )


async def on_custom_time_input(message: Message, state: FSMContext, session: AsyncSession, settings: Settings) -> None:
    parsed = parse_time(message.text or "")
    if parsed is None or message.from_user is None:
        await message.answer("Не схоже на час. Приклад: <b>07:30</b>. Скасувати: /cancel")
        return
    user = await ensure_user(session, message.from_user, settings)
    await crud.set_delivery_time(session, user.id, *parsed)
    await state.clear()
    await message.answer(
        f"✅ Час доставки: <b>{parsed[0]:02d}:{parsed[1]:02d}</b> ({html.escape(user.timezone)})",
        reply_markup=main_menu(),
    )


def create_router() -> Router:
    router = Router(name="settings")
    router.message.register(show_settings, Command("settings"))
    router.message.register(show_settings, F.text == BTN_SETTINGS)
    router.callback_query.register(on_time_selected, TimeCB.filter())
    router.callback_query.register(on_category_toggled, CategoryCB.filter())
    router.callback_query.register(on_toggle_active, ActionCB.filter(F.name == "toggle_active"))
    router.callback_query.register(on_custom_time, ActionCB.filter(F.name == "custom_time"))
    # Free-text time input; commands and menu buttons fall through to their own handlers.
    router.message.register(
        on_custom_time_input,
        SettingsStates.waiting_time,
        F.text,
        ~F.text.startswith("/"),
        F.text.not_in({BTN_NOW, BTN_SETTINGS}),
    )
    return router
