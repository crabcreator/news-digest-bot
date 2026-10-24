"""Inline keyboards: delivery time picker, category toggles, subscription toggle."""

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from core.categories import CATEGORIES, TECH_SUBCATEGORIES
from db.models import User

# Quick-pick delivery times (hour, minute).
DELIVERY_TIMES: tuple[tuple[int, int], ...] = ((8, 0), (13, 0), (19, 0), (20, 0), (21, 0), (22, 0))

SUPPORTED_TIMEZONES: tuple[tuple[str, str], ...] = (
    ("Europe/Kyiv", "🇺🇦 Київ"),
    ("Europe/Warsaw", "🇵🇱 Варшава"),
    ("Europe/London", "🇬🇧 Лондон"),
    ("Europe/Berlin", "🇩🇪 Берлін"),
    ("Europe/Prague", "🇨🇿 Прага"),
    ("America/New_York", "🇺🇸 Нью-Йорк"),
)


class TimeCB(CallbackData, prefix="t"):
    hour: int
    minute: int


class CategoryCB(CallbackData, prefix="c"):
    key: str


class ActionCB(CallbackData, prefix="a"):
    name: str  # "toggle_active" | "custom_time" | "pick_timezone" | "back_to_settings" | "tech_subcategories" | "menu_ua" | "menu_world" | "toggle_world_active"


class TimezoneCB(CallbackData, prefix="tz"):
    name: str


class TechSubcategoryCB(CallbackData, prefix="ts"):
    key: str


class WorldCategoryCB(CallbackData, prefix="wc"):
    key: str


def settings_keyboard(user: User) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    for hour, minute in DELIVERY_TIMES:
        selected = (user.delivery_hour, user.delivery_minute) == (hour, minute)
        label = f"{'✅ ' if selected else ''}{hour:02d}:{minute:02d}"
        builder.button(text=label, callback_data=TimeCB(hour=hour, minute=minute))
    builder.adjust(3)

    actions = InlineKeyboardBuilder()
    actions.button(text="🕐 Свій час", callback_data=ActionCB(name="custom_time"))
    actions.button(text=f"🌍 Пояс ({user.timezone.split('/')[-1]})", callback_data=ActionCB(name="pick_timezone"))
    actions.adjust(2)
    builder.attach(actions)

    sections = InlineKeyboardBuilder()
    ua_count = len(user.category_list)
    world_status = "увімкнено ✅" if user.is_world_active else "вимкнено 🔕"
    sections.button(text=f"🇺🇦 Новини України ({ua_count}/8)", callback_data=ActionCB(name="menu_ua"))
    sections.button(text=f"🌍 Світові новини ({world_status})", callback_data=ActionCB(name="menu_world"))
    sections.adjust(1)
    builder.attach(sections)

    toggle = InlineKeyboardBuilder()
    toggle.button(
        text="🔕 Вимкнути щоденний дайджест" if user.is_active else "🔔 Увімкнути щоденний дайджест",
        callback_data=ActionCB(name="toggle_active"),
    )
    builder.attach(toggle)
    return builder.as_markup()


def ua_categories_keyboard(user: User) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    selected_categories = set(user.category_list)
    for cat in CATEGORIES:
        mark = "✅" if cat.key in selected_categories else "▫️"
        builder.button(text=f"{mark} {cat.emoji} {cat.title}", callback_data=CategoryCB(key=cat.key))
    builder.adjust(2)

    if "technology" in selected_categories:
        tech_btn = InlineKeyboardBuilder()
        sub_count = len(user.tech_subcategory_list)
        total_count = len(TECH_SUBCATEGORIES)
        suffix = "всі" if sub_count == total_count else f"{sub_count}/{total_count}"
        tech_btn.button(
            text=f"⚙️ Галузі технологій ({suffix})",
            callback_data=ActionCB(name="tech_subcategories"),
        )
        builder.attach(tech_btn)

    back = InlineKeyboardBuilder()
    back.button(text="⬅️ Назад до налаштувань", callback_data=ActionCB(name="back_to_settings"))
    builder.attach(back)
    return builder.as_markup()


def world_categories_keyboard(user: User) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    toggle = InlineKeyboardBuilder()
    toggle.button(
        text="🔕 Вимкнути світові новини" if user.is_world_active else "🔔 Увімкнути світові новини",
        callback_data=ActionCB(name="toggle_world_active"),
    )
    builder.attach(toggle)

    selected_categories = set(user.world_category_list)
    cats = InlineKeyboardBuilder()
    for cat in CATEGORIES:
        mark = "✅" if cat.key in selected_categories else "▫️"
        cats.button(text=f"{mark} {cat.emoji} {cat.title}", callback_data=WorldCategoryCB(key=cat.key))
    cats.adjust(2)
    builder.attach(cats)

    if "technology" in selected_categories:
        tech_btn = InlineKeyboardBuilder()
        sub_count = len(user.tech_subcategory_list)
        total_count = len(TECH_SUBCATEGORIES)
        suffix = "всі" if sub_count == total_count else f"{sub_count}/{total_count}"
        tech_btn.button(
            text=f"⚙️ Галузі технологій ({suffix})",
            callback_data=ActionCB(name="tech_subcategories"),
        )
        builder.attach(tech_btn)

    back = InlineKeyboardBuilder()
    back.button(text="⬅️ Назад до налаштувань", callback_data=ActionCB(name="back_to_settings"))
    builder.attach(back)
    return builder.as_markup()


def timezone_keyboard(current_timezone: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for tz_name, label in SUPPORTED_TIMEZONES:
        mark = "✅ " if tz_name == current_timezone else ""
        builder.button(text=f"{mark}{label}", callback_data=TimezoneCB(name=tz_name))
    builder.adjust(2)

    back = InlineKeyboardBuilder()
    back.button(text="⬅️ Назад до налаштувань", callback_data=ActionCB(name="back_to_settings"))
    builder.attach(back)
    return builder.as_markup()


def tech_subcategories_keyboard(user: User) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    selected = set(user.tech_subcategory_list)
    for sub in TECH_SUBCATEGORIES:
        mark = "✅" if sub.key in selected else "▫️"
        builder.button(
            text=f"{mark} {sub.emoji} {sub.title}",
            callback_data=TechSubcategoryCB(key=sub.key),
        )
    builder.adjust(1)

    back = InlineKeyboardBuilder()
    back.button(text="⬅️ Назад до налаштувань", callback_data=ActionCB(name="back_to_settings"))
    builder.attach(back)
    return builder.as_markup()

