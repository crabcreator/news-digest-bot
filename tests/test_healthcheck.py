import time
from unittest.mock import AsyncMock, MagicMock

import pytest

import healthcheck
from services.scheduler.jobs import check_and_send_scheduled_digests


def test_healthcheck_missing_file(tmp_path):
    p = tmp_path / "heartbeat"
    assert not healthcheck.check_health(p)


def test_healthcheck_touch_and_success(tmp_path):
    p = tmp_path / "heartbeat"
    healthcheck.touch_heartbeat(p)
    assert p.exists()
    assert healthcheck.check_health(p, max_age=60)


def test_healthcheck_expired(tmp_path):
    p = tmp_path / "heartbeat"
    p.write_text(str(time.time() - 300))
    assert not healthcheck.check_health(p, max_age=60)


def test_healthcheck_corrupted_file(tmp_path):
    p = tmp_path / "heartbeat"
    p.write_text("invalid timestamp\n")
    assert not healthcheck.check_health(p)


def test_healthcheck_remove(tmp_path):
    p = tmp_path / "heartbeat"
    healthcheck.touch_heartbeat(p)
    assert p.exists()
    healthcheck.remove_heartbeat(p)
    assert not p.exists()


async def test_job_touches_heartbeat(tmp_path, monkeypatch):
    p = tmp_path / "heartbeat"
    monkeypatch.setattr(healthcheck, "DEFAULT_HEARTBEAT_FILE", p)

    # Mock session factory that returns no due users
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session_factory = MagicMock(return_value=session)

    monkeypatch.setattr("services.scheduler.jobs.crud.get_due_users", AsyncMock(return_value=[]))

    await check_and_send_scheduled_digests(MagicMock(), session_factory, MagicMock())
    assert p.exists()
    assert healthcheck.check_health(p, max_age=10)
