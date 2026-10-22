"""SQLAlchemy ORM models. All datetimes are stored as naive UTC."""

import json
from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from core.categories import ALL_CATEGORY_KEYS
from core.database import Base


def utcnow() -> datetime:
    """Current time as naive UTC (the storage convention)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)  # Telegram user ID
    username: Mapped[str | None] = mapped_column(String, nullable=True)
    first_name: Mapped[str | None] = mapped_column(String, nullable=True)
    delivery_hour: Mapped[int] = mapped_column(Integer, default=21, server_default="21")
    delivery_minute: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    timezone: Mapped[str] = mapped_column(String, default="Europe/Kyiv", server_default="Europe/Kyiv")
    # JSON list of category keys, or the literal "all"
    categories: Mapped[str] = mapped_column(Text, default="all", server_default="all")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())

    @property
    def category_list(self) -> list[str]:
        raw = (self.categories or "all").strip()
        if raw == "all":
            return list(ALL_CATEGORY_KEYS)
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = [part.strip() for part in raw.split(",")]
        return [c for c in ALL_CATEGORY_KEYS if c in parsed]  # keep canonical order, drop unknown

    @category_list.setter
    def category_list(self, value: list[str]) -> None:
        selected = [c for c in ALL_CATEGORY_KEYS if c in value]
        self.categories = "all" if len(selected) == len(ALL_CATEGORY_KEYS) else json.dumps(selected)


class NewsItem(Base):
    __tablename__ = "news_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    url: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    url_hash: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str | None] = mapped_column(String, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())


class Digest(Base):
    __tablename__ = "digests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    target_date: Mapped[date] = mapped_column(Date, nullable=False)
    category_group: Mapped[str] = mapped_column(String, default="all", server_default="all")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())


class UserDeliveryLog(Base):
    __tablename__ = "user_delivery_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    digest_id: Mapped[int | None] = mapped_column(ForeignKey("digests.id"), nullable=True)
    status: Mapped[str] = mapped_column(String)  # sent | failed | blocked
    sent_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())
