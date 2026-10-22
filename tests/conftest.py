import pytest_asyncio

from core.database import create_engine, create_session_factory, init_db


@pytest_asyncio.fixture
async def session():
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    factory = create_session_factory(engine)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(tmp_path):
    """File-backed DB so several sessions can be used concurrently (as in the scheduler jobs)."""
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path}/test.db")
    await init_db(engine)
    yield create_session_factory(engine)
    await engine.dispose()
