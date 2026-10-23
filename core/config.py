"""Strongly typed application settings loaded from environment / `.env`."""

from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class FeedConfig(BaseModel):
    name: str
    url: str


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
            FeedConfig(name="Суспільне", url="https://suspilne.media/rss/all.rss"),
            FeedConfig(name="BBC Україна", url="https://feeds.bbci.co.uk/ukrainian/rss.xml"),
            FeedConfig(name="Українська правда", url="https://www.pravda.com.ua/rss/"),
        ]
    )
    # Gemini request handling
    gemini_timeout_seconds: int = Field(90, ge=5)
    gemini_max_attempts: int = Field(3, ge=1)

    @field_validator("gemini_fallback_model", mode="before")
    @classmethod
    def _empty_fallback_is_none(cls, value: str | None) -> str | None:
        return value or None


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
