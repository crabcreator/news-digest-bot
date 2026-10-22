import pytest
from pydantic import ValidationError

from core.config import Settings


def test_settings_load(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "t")
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    s = Settings(_env_file=None)
    assert s.default_delivery_hour == 21
    assert s.database_url.startswith("sqlite+aiosqlite")


def test_settings_require_secrets(monkeypatch):
    monkeypatch.delenv("BOT_TOKEN", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
