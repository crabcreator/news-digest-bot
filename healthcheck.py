"""Container healthcheck script: verifies that the bot scheduler heartbeat is fresh."""

import os
import sys
import time
from pathlib import Path

DEFAULT_HEARTBEAT_FILE = Path(os.getenv("HEARTBEAT_FILE", "/tmp/bot_heartbeat"))
MAX_AGE_SECONDS = 180.0  # 3 minutes


def touch_heartbeat(heartbeat_path: Path | None = None) -> None:
    """Record current timestamp into the heartbeat file."""
    path = heartbeat_path or DEFAULT_HEARTBEAT_FILE
    try:
        path.write_text(f"{time.time()}\n")
    except Exception:
        pass


def remove_heartbeat(heartbeat_path: Path | None = None) -> None:
    """Remove heartbeat file upon shutdown."""
    path = heartbeat_path or DEFAULT_HEARTBEAT_FILE
    try:
        if path.exists():
            path.unlink()
    except Exception:
        pass


def check_health(
    heartbeat_path: Path | None = None, max_age: float = MAX_AGE_SECONDS
) -> bool:
    """Return True if heartbeat file exists and was updated within max_age seconds."""
    path = heartbeat_path or DEFAULT_HEARTBEAT_FILE
    if not path.exists():
        return False
    try:
        timestamp = float(path.read_text().strip())
        return (time.time() - timestamp) <= max_age
    except Exception:
        return False


if __name__ == "__main__":
    sys.exit(0 if check_health() else 1)
