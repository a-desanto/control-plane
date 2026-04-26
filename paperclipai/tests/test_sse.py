"""SSE fan-out integration tests.

Tests are split into two layers:
  1. Event-routing tests: subscribe directly to the ev module queue and verify
     the worker emits the right events via pg_notify (no HTTP layer needed,
     avoids httpx ASGI transport + BaseHTTPMiddleware streaming deadlock).
  2. HTTP-layer tests: use httpx ASGITransport for quick-close streams (terminal
     intents whose generators close immediately after reading from DB).

Requires Docker (testcontainers Postgres).
"""

import asyncio
import os
import sys
from pathlib import Path
from typing import AsyncGenerator

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import Base, Contract, Intent
from app.tool_registry import McpTransport, ToolRegistryEntry

pytestmark = pytest.mark.asyncio(loop_scope="module")

ECHO_MCP_PATH = (
    Path(__file__).parent.parent.parent / "mcp-servers" / "cli" / "echo-mcp" / "echo_mcp.py"
)


def _docker_available() -> bool:
    try:
        import docker
        docker.from_env().ping()
        return True
    except Exception:
        return False


@pytest.fixture(scope="module")
def db_url() -> str:
    env_url = os.environ.get("DATABASE_URL")
    if env_url:
        yield env_url
        return

    if not _docker_available():
        pytest.skip("Docker not available and DATABASE_URL not set")

    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:16") as pg:
        raw = pg.get_connection_url()
        url = raw.replace("psycopg2", "asyncpg")
        if "postgresql+asyncpg" not in url:
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        yield url
        return

    return ""  # pragma: no cover


@pytest_asyncio.fixture(scope="module")
async def db_engine(db_url: str):
    engine = create_async_engine(db_url, pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(scope="module")
async def session_factory(db_engine):
    return async_sessionmaker(db_engine, expire_on_commit=False)


@pytest.fixture(scope="module")
def asyncpg_url(db_url: str) -> str:
    return db_url.replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgresql+psycopg2://", "postgresql://"
    )


@pytest_asyncio.fixture(scope="module")
async def sse_client(db_engine, db_url: str) -> AsyncGenerator[httpx.AsyncClient, None]:
    """FastAPI client with DATABASE_URL set to the testcontainer so the lifespan
    starts the events listener (and AsyncSessionLocal) against the right DB."""
    from app.db.session import get_db
    from app.main import app

    engine = db_engine
    sf = async_sessionmaker(engine, expire_on_commit=False)

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with sf() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    os.environ["BYPASS_CLAIMS_CHECK"] = "1"
    os.environ["DATABASE_URL"] = db_url

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac

    app.dependency_overrides.clear()
    os.environ.pop("BYPASS_CLAIMS_CHECK", None)
    os.environ.pop("DATABASE_URL", None)


_ECHO_REGISTRY_ENTRY = ToolRegistryEntry(
    tool_name="echo",
    tool_version="1.0.0",
    mcp=McpTransport(
        transport="stdio",
        command=[sys.executable, str(ECHO_MCP_PATH)],
        tool_call="echo",
    ),
    input_schema="echo_input@v1",
    output_schema="tool_output@v3.3",
)

_BASE_INTENT = {
    "source": "test",
    "caller_type": "client_app",
    "trigger_type": "manual",
    "requested_outcome": "echo_test",
    "payload": {"text": "sse_test"},
    "constraints": {},
}


# ---------------------------------------------------------------------------
# Layer 1: event-routing tests (no HTTP, direct queue subscription)
# ---------------------------------------------------------------------------


async def test_worker_emits_correct_event_sequence(
    session_factory, asyncpg_url: str
) -> None:
    """
    AC6: worker NOTIFYs contract_started, contract_completed, completed in order.

    Tests the event routing layer directly without HTTP streaming.
    """
    if not ECHO_MCP_PATH.exists():
        pytest.skip("echo_mcp.py not found")

    from app import events as ev
    from app.orchestration import worker as w

    w._registry = [_ECHO_REGISTRY_ENTRY]

    # Start the events listener for this test.
    await ev.start_listener(asyncpg_url)

    intent_id = "01HXSSE0000000000000000020"
    async with session_factory() as db:
        row = Intent(
            id=intent_id,
            caller_type="client_app",
            idempotency_key="sse-routing-020",
            source="test",
            trigger_type="manual",
            requested_outcome="echo_test",
            payload={"text": "sse_test"},
            constraints={"read_only": False},
            status="accepted",
        )
        db.add(row)
        await db.commit()

    q = ev.subscribe(intent_id)
    try:
        await w.process_intent(intent_id, session_factory, asyncpg_url)

        # Give the event loop a moment to process asyncpg notifications.
        await asyncio.sleep(0.1)

        events = []
        while True:
            try:
                event_data = q.get_nowait()
                events.append(event_data["event"])
            except asyncio.QueueEmpty:
                break
    finally:
        ev.unsubscribe(intent_id, q)
        await ev.stop_listener()

    assert "contract_started" in events, f"events: {events}"
    assert "contract_completed" in events, f"events: {events}"
    assert "completed" in events, f"events: {events}"

    # Events must be in the right order
    starts = events.index("contract_started")
    completed_contract = events.index("contract_completed")
    terminal = events.index("completed")
    assert starts < completed_contract < terminal, f"events out of order: {events}"


async def test_failed_intent_emits_failed_event(
    session_factory, asyncpg_url: str
) -> None:
    """Unknown requested_outcome → worker emits 'failed' event."""
    from app import events as ev
    from app.orchestration import worker as w

    w._registry = [_ECHO_REGISTRY_ENTRY]

    await ev.start_listener(asyncpg_url)

    intent_id = "01HXSSE0000000000000000021"
    async with session_factory() as db:
        row = Intent(
            id=intent_id,
            caller_type="client_app",
            idempotency_key="sse-fail-021",
            source="test",
            trigger_type="manual",
            requested_outcome="nonexistent_workflow",
            payload={},
            constraints={"read_only": False},
            status="accepted",
        )
        db.add(row)
        await db.commit()

    q = ev.subscribe(intent_id)
    try:
        await w.process_intent(intent_id, session_factory, asyncpg_url)
        await asyncio.sleep(0.1)

        events = [q.get_nowait()["event"] for _ in range(q.qsize())]
    except asyncio.QueueEmpty:
        events = []
    finally:
        ev.unsubscribe(intent_id, q)
        await ev.stop_listener()

    assert "failed" in events, f"events: {events}"


# ---------------------------------------------------------------------------
# Layer 2: HTTP-layer tests (terminal-intent paths that close the stream fast)
# ---------------------------------------------------------------------------


async def test_sse_already_completed_intent_delivers_events(
    sse_client: httpx.AsyncClient,
    session_factory,
    asyncpg_url: str,
) -> None:
    """
    Connecting SSE after the intent is already completed still delivers all events
    (synthesized from DB).  The generator closes immediately → no streaming deadlock.
    """
    if not ECHO_MCP_PATH.exists():
        pytest.skip("echo_mcp.py not found")

    from app import events as ev
    from app.orchestration import worker as w

    w._registry = [_ECHO_REGISTRY_ENTRY]

    intent_id = "01HXSSE0000000000000000030"
    intent_payload = {
        **_BASE_INTENT,
        "intent_id": intent_id,
        "idempotency_key": "sse-post-complete-030",
    }
    r = await sse_client.post("/intent", json=intent_payload)
    assert r.status_code == 202

    # Start a fresh listener for the asyncpg_url.
    await ev.start_listener(asyncpg_url)
    try:
        await w.process_intent(intent_id, session_factory, asyncpg_url)
    finally:
        await ev.stop_listener()

    # Now connect SSE after intent is already completed.
    received_events: list[str] = []
    async with sse_client.stream("GET", f"/intent/{intent_id}/events") as resp:
        assert resp.status_code == 200
        async for line in resp.aiter_lines():
            if line.startswith("event:"):
                received_events.append(line.split(":", 1)[1].strip())
            # Stream closes when generator terminates (terminal event reached).

    assert "accepted" in received_events, f"events: {received_events}"
    assert "completed" in received_events, f"events: {received_events}"


async def test_sse_404_for_nonexistent_intent(sse_client: httpx.AsyncClient) -> None:
    """SSE on a non-existent intent returns 404."""
    r = await sse_client.get("/intent/01HXSSE0000000000000000099/events")
    assert r.status_code == 404
