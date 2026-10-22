"""Strongly typed application settings loaded from environment / `.env`."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bot_token: str = Field(..., description="Telegram Bot API token from @BotFather")
    gemini_api_key: str = Field(..., description="Google AI Studio API key")
    gemini_model: str = "gemini-2.5-flash"
    database_url: str = "sqlite+aiosqlite:///./data/news_bot.db"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    default_timezone: str = "Europe/Kyiv"
    default_delivery_hour: int = Field(21, ge=0, le=23)
    default_delivery_minute: int = Field(0, ge=0, le=59)

    fetch_interval_minutes: int = Field(30, ge=5, le=120)
    # Gemini request handling
    gemini_timeout_seconds: int = Field(60, ge=5)
    gemini_max_attempts: int = Field(3, ge=1)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
