import asyncio
import os
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_DEFAULT_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/paperclipai"
# Keyed by (url, event_loop_id) so each asyncio event loop gets its own engine.
# In production there is exactly one event loop so behaviour is identical to a
# plain dict[str, ...].  In tests every module-scoped loop gets a fresh engine,
# preventing "Event loop is closed" errors when pytest-asyncio rotates loops.
_factories: dict[tuple, async_sessionmaker] = {}


def _get_factory() -> async_sessionmaker:
    url = os.environ.get("DATABASE_URL", _DEFAULT_URL)
    try:
        loop_key = id(asyncio.get_running_loop())
    except RuntimeError:
        loop_key = None
    key = (url, loop_key)
    if key not in _factories:
        engine = create_async_engine(url, pool_pre_ping=True)
        _factories[key] = async_sessionmaker(engine, expire_on_commit=False)
    return _factories[key]


def AsyncSessionLocal() -> AsyncSession:
    """Return a new AsyncSession for the currently configured DATABASE_URL."""
    return _get_factory()()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with _get_factory()() as session:
        yield session
