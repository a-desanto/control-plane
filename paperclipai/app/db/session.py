import os
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_DEFAULT_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/paperclipai"
_factories: dict[str, async_sessionmaker] = {}


def _get_factory() -> async_sessionmaker:
    url = os.environ.get("DATABASE_URL", _DEFAULT_URL)
    if url not in _factories:
        engine = create_async_engine(url, pool_pre_ping=True)
        _factories[url] = async_sessionmaker(engine, expire_on_commit=False)
    return _factories[url]


def AsyncSessionLocal() -> AsyncSession:
    """Return a new AsyncSession for the currently configured DATABASE_URL."""
    return _get_factory()()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with _get_factory()() as session:
        yield session
