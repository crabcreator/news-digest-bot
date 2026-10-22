"""Persistent reply keyboard with quick actions."""

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

BTN_NOW = "📰 Дайджест зараз"
BTN_SETTINGS = "⚙️ Налаштування"


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_NOW), KeyboardButton(text=BTN_SETTINGS)]],
        resize_keyboard=True,
    )
