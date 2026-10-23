import pytest
from pydantic import ValidationError

from core.config import Settings


def test_settings_load(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "t")
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    s = Settings(_env_file=None)
    assert s.default_delivery_hour == 21
    assert s.database_url.startswith("sqlite+aiosqlite")
    assert len(s.rss_feeds) == 3


def test_custom_rss_feeds(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "t")
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("RSS_FEEDS", '[{"name": "Custom", "url": "https://example.com/rss"}]')
    s = Settings(_env_file=None)
    assert len(s.rss_feeds) == 1
    assert s.rss_feeds[0].name == "Custom"
    assert s.rss_feeds[0].url == "https://example.com/rss"


def test_settings_require_secrets(monkeypatch):
    monkeypatch.delenv("BOT_TOKEN", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
