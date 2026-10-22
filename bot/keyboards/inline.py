"""Inline keyboards: delivery time picker, category toggles, subscription toggle."""

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from core.categories import CATEGORIES
from db.models import User

# Quick-pick delivery times (hour, minute).
DELIVERY_TIMES: tuple[tuple[int, int], ...] = ((8, 0), (13, 0), (19, 0), (20, 0), (21, 0), (22, 0))


class TimeCB(CallbackData, prefix="t"):
    hour: int
    minute: int


class CategoryCB(CallbackData, prefix="c"):
    key: str


class ActionCB(CallbackData, prefix="a"):
    name: str  # "toggle_active" | "custom_time"


def settings_keyboard(user: User) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    for hour, minute in DELIVERY_TIMES:
        selected = (user.delivery_hour, user.delivery_minute) == (hour, minute)
        label = f"{'✅ ' if selected else ''}{hour:02d}:{minute:02d}"
        builder.button(text=label, callback_data=TimeCB(hour=hour, minute=minute))
    builder.adjust(3)

    custom = InlineKeyboardBuilder()
    custom.button(text="🕐 Свій час", callback_data=ActionCB(name="custom_time"))
    builder.attach(custom)

    selected_categories = set(user.category_list)
    cats = InlineKeyboardBuilder()
    for cat in CATEGORIES:
        mark = "✅" if cat.key in selected_categories else "▫️"
        cats.button(text=f"{mark} {cat.emoji} {cat.title}", callback_data=CategoryCB(key=cat.key))
    cats.adjust(2)
    builder.attach(cats)

    toggle = InlineKeyboardBuilder()
    toggle.button(
        text="🔕 Вимкнути щоденний дайджест" if user.is_active else "🔔 Увімкнути щоденний дайджест",
        callback_data=ActionCB(name="toggle_active"),
    )
    builder.attach(toggle)
    return builder.as_markup()

