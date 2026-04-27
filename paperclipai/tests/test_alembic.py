"""Alembic upgrade/downgrade is clean against a real Postgres container."""

import os
import subprocess
from pathlib import Path

import pytest

PAPERCLIPAI_DIR = Path(__file__).parent.parent


def _docker_available() -> bool:
    try:
        import docker

        docker.from_env().ping()
        return True
    except Exception:
        return False


def _run_alembic(cmd: str, database_url: str) -> None:
    env = {**os.environ, "DATABASE_URL": database_url}
    result = subprocess.run(
        ["uv", "run", "alembic"] + cmd.split(),
        cwd=PAPERCLIPAI_DIR,
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"alembic {cmd} failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )


async def _table_names(database_url: str) -> set[str]:
    import asyncpg

    sync_url = database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(sync_url)
    rows = await conn.fetch(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
    )
    await conn.close()
    return {r["tablename"] for r in rows}


@pytest.fixture(scope="module")
def postgres_url():
    env_url = os.environ.get("DATABASE_URL")
    if env_url:
        yield env_url
        return

    if not _docker_available():
        pytest.skip("Docker not available and DATABASE_URL not set")

    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:16") as pg:
        raw = pg.get_connection_url()
        url = raw.replace("psycopg2", "asyncpg").replace("postgresql://", "postgresql+asyncpg://", 1)
        if "+asyncpg" not in url:
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        yield url


async def _column_names(database_url: str, table: str) -> set[str]:
    import asyncpg

    sync_url = database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(sync_url)
    rows = await conn.fetch(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = $1",
        table,
    )
    await conn.close()
    return {r["column_name"] for r in rows}


@pytest.mark.asyncio
async def test_upgrade_creates_tables(postgres_url: str) -> None:
    _run_alembic("upgrade head", postgres_url)
    tables = await _table_names(postgres_url)
    # Phase 1 tables
    assert "intents" in tables, f"intents table missing; found: {tables}"
    assert "contracts" in tables, f"contracts table missing; found: {tables}"
    # Phase 2B tables — previously unguarded, missing migration caused prod 500
    assert "plans" in tables, f"plans table missing; found: {tables}"
    assert "callback_attempts" in tables, f"callback_attempts table missing; found: {tables}"
    # Phase 2B column added to contracts — missing column caused GET /status 500
    contract_cols = await _column_names(postgres_url, "contracts")
    assert "image_digest" in contract_cols, f"image_digest column missing on contracts; found: {contract_cols}"


@pytest.mark.asyncio
async def test_downgrade_removes_tables(postgres_url: str) -> None:
    _run_alembic("downgrade base", postgres_url)
    tables = await _table_names(postgres_url)
    assert "intents" not in tables, f"intents still present: {tables}"
    assert "contracts" not in tables, f"contracts still present: {tables}"
    assert "plans" not in tables, f"plans still present: {tables}"
    assert "callback_attempts" not in tables, f"callback_attempts still present: {tables}"
