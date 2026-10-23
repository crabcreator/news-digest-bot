"""Async SQLAlchemy engine (SQLite, WAL) and declarative base."""

import logging
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def _ensure_sqlite_dir(database_url: str) -> None:
    url = make_url(database_url)
    if url.get_backend_name() == "sqlite" and url.database and url.database != ":memory:":
        Path(url.database).parent.mkdir(parents=True, exist_ok=True)


def create_engine(database_url: str, echo: bool = False) -> AsyncEngine:
    _ensure_sqlite_dir(database_url)
    engine = create_async_engine(database_url, echo=echo)

    if make_url(database_url).get_backend_name() == "sqlite":

        @event.listens_for(engine.sync_engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection, _record) -> None:  # noqa: ANN001
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("PRAGMA synchronous=NORMAL;")
            cursor.execute("PRAGMA foreign_keys=ON;")
            cursor.execute("PRAGMA busy_timeout=10000;")
            cursor.close()

    return engine


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


def _migrate_sqlite_schema(connection) -> None:  # noqa: ANN001
    """Lightweight schema migration for existing SQLite databases."""
    try:
        rows = connection.exec_driver_sql("PRAGMA table_info(users);").fetchall()
        cols = {row[1] for row in rows}
        if cols and "tech_subcategories" not in cols:
            connection.exec_driver_sql("ALTER TABLE users ADD COLUMN tech_subcategories TEXT DEFAULT 'all';")
    except Exception:
        logger.exception("Schema migration check failed")


async def init_db(engine: AsyncEngine) -> None:
    """Create all tables (idempotent)."""
    from db import models  # noqa: F401  (register models on Base.metadata)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if engine.url.get_backend_name() == "sqlite":
            await conn.run_sync(_migrate_sqlite_schema)
    logger.info("Database initialised")
