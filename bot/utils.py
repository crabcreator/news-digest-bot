"""Helpers shared by bot handlers."""

from aiogram.types import User as TgUser
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import Settings
from db import crud
from db.models import User


async def ensure_user(
    session: AsyncSession, tg_user: TgUser, settings: Settings, *, reactivate: bool = False
) -> User:
    """Get the DB user for a Telegram user, registering them with the configured defaults if new."""
    return await crud.get_or_create_user(
        session,
        tg_user.id,
        tg_user.username,
        tg_user.first_name,
        delivery_hour=settings.default_delivery_hour,
        delivery_minute=settings.default_delivery_minute,
        timezone=settings.default_timezone,
        reactivate=reactivate,
    )
