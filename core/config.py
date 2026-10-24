"""Strongly typed application settings loaded from environment / `.env`."""

from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class FeedConfig(BaseModel):
    name: str
    url: str
    default_category: str | None = None
    scope: Literal["ua", "world"] = "ua"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bot_token: str = Field(..., description="Telegram Bot API token from @BotFather")
    gemini_api_key: str = Field(..., description="Google AI Studio API key")
    gemini_model: str = "gemini-3.5-flash"
    # Used on retries when the primary model is overloaded (503/504); empty disables it.
    gemini_fallback_model: str | None = "gemini-3.8-flash"
    database_url: str = "sqlite+aiosqlite:///./data/news_bot.db"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    default_timezone: str = "Europe/Kyiv"
    default_delivery_hour: int = Field(21, ge=0, le=23)
    default_delivery_minute: int = Field(0, ge=0, le=59)

    fetch_interval_minutes: int = Field(30, ge=5, le=120)
    rss_feeds: list[FeedConfig] = Field(
        default_factory=lambda: [
            # Ukrainian feeds
            FeedConfig(name="Суспільне", url="https://suspilne.media/rss/all.rss", scope="ua"),
            FeedConfig(name="BBC Україна", url="https://feeds.bbci.co.uk/ukrainian/rss.xml", scope="ua"),
            FeedConfig(name="Українська правда", url="https://www.pravda.com.ua/rss/", scope="ua"),
            FeedConfig(name="Mezha.Media", url="https://mezha.media/feed/", default_category="technology", scope="ua"),
            FeedConfig(name="AIN.UA", url="https://ain.ua/feed/", default_category="technology", scope="ua"),
            FeedConfig(name="DOU", url="https://dou.ua/feed/", default_category="technology", scope="ua"),
            # World feeds (English sources)
            FeedConfig(name="BBC World", url="https://feeds.bbci.co.uk/news/world/rss.xml", scope="world"),
            FeedConfig(name="The Guardian", url="https://www.theguardian.com/world/rss", scope="world"),
            FeedConfig(name="DW World", url="https://rss.dw.com/rdf/rss-en-world", scope="world"),
            FeedConfig(name="The Verge", url="https://www.theverge.com/rss/index.xml", default_category="technology", scope="world"),
            FeedConfig(name="TechCrunch", url="https://techcrunch.com/feed/", default_category="technology", scope="world"),
            FeedConfig(name="Ars Technica", url="https://feeds.arstechnica.com/arstechnica/index", default_category="technology", scope="world"),
            FeedConfig(name="Wired", url="https://www.wired.com/feed/rss", default_category="technology", scope="world"),
        ]
    )
    # Gemini request handling
    gemini_timeout_seconds: int = Field(90, ge=5)
    gemini_max_attempts: int = Field(3, ge=1)

    admin_ids: list[int] | str = Field(default_factory=list)

    @field_validator("admin_ids")
    @classmethod
    def _parse_admin_ids(cls, value: object) -> list[int]:
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return []
            if value.startswith("["):
                import json

                parsed = json.loads(value)
                return [int(x) for x in parsed]
            return [int(x.strip()) for x in value.split(",") if x.strip()]
        if isinstance(value, (list, tuple)):
            return [int(x) for x in value]
        return []

    @field_validator("gemini_fallback_model", mode="before")
    @classmethod
    def _empty_fallback_is_none(cls, value: str | None) -> str | None:
        return value or None


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
