"""Phase 1 integration tests: POST /intent, GET /status, GET /events.

Uses httpx.AsyncClient against a live FastAPI app backed by a Postgres
testcontainer (or DATABASE_URL env var if already set).
"""

import os
from collections.abc import AsyncGenerator

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import Base

# All tests in this module share one event loop so the module-scoped
# async engine/client fixtures don't cross loop boundaries.
pytestmark = pytest.mark.asyncio(loop_scope="module")

# ---------------------------------------------------------------------------
# Postgres fixture: reuse DATABASE_URL from env or spin up a testcontainer
# ---------------------------------------------------------------------------


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
        return env_url

    if not _docker_available():
        pytest.skip("Docker not available and DATABASE_URL not set")

    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:16") as pg:
        raw = pg.get_connection_url()
        url = raw.replace("psycopg2", "asyncpg")
        if "postgresql+asyncpg" not in url:
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        # keep the container alive for the whole module
        yield url
        return

    # unreachable — context manager handles teardown
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
async def client(db_engine) -> AsyncGenerator[httpx.AsyncClient, None]:
    """FastAPI test client with DB dependency overridden to use the testcontainer."""
    from fastapi.testclient import TestClient

    from app.db.session import get_db
    from app.main import app

    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_INTENT = {
    "intent_id": "01HXTEST000000000000000001",
    "source": "n8n:workflow_42:exec_9876",
    "caller_type": "n8n",
    "trigger_type": "webhook",
    "requested_outcome": "qualify_and_respond",
    "target": "lead_abc",
    "payload": {"email": "jane@example.com"},
    "constraints": {"environment": "prod", "max_cost_usd": 2.0},
    "idempotency_key": "test-dedup-key-001",
    "callback_url": "https://n8n.example.com/webhook/result",
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_valid_intent_returns_202_with_all_urls(
    client: httpx.AsyncClient,
) -> None:
    payload = {**_VALID_INTENT, "idempotency_key": "test-urls-001", "intent_id": "01HXTEST000000000000000002"}
    r = await client.post("/intent", json=payload)
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["intent_id"] == payload["intent_id"]
    assert body["status"] == "accepted"
    assert "audit_link" in body
    assert "events_url" in body
    assert "status_url" in body
    assert body["intent_id"] in body["audit_link"]
    assert body["intent_id"] in body["events_url"]
    assert body["intent_id"] in body["status_url"]


async def test_dedup_same_idempotency_key_returns_same_intent_id(
    client: httpx.AsyncClient,
) -> None:
    payload = {**_VALID_INTENT, "idempotency_key": "dedup-key-002", "intent_id": "01HXTEST000000000000000003"}
    r1 = await client.post("/intent", json=payload)
    assert r1.status_code == 202

    # Second POST: same caller_type + idempotency_key, different intent_id —
    # must return the FIRST intent_id.
    payload2 = {**payload, "intent_id": "01HXTEST000000000000000004"}
    r2 = await client.post("/intent", json=payload2)
    assert r2.status_code == 202
    assert r2.json()["intent_id"] == r1.json()["intent_id"]


async def test_missing_idempotency_key_returns_422(
    client: httpx.AsyncClient,
) -> None:
    bad = {k: v for k, v in _VALID_INTENT.items() if k != "idempotency_key"}
    bad["intent_id"] = "01HXTEST000000000000000005"
    r = await client.post("/intent", json=bad)
    assert r.status_code == 422
    errors = r.json()["detail"]
    paths = [".".join(str(loc) for loc in e["loc"]) for e in errors]
    assert any("idempotency_key" in p for p in paths), f"offending field not in paths: {paths}"


async def test_bad_caller_type_returns_422(
    client: httpx.AsyncClient,
) -> None:
    bad = {**_VALID_INTENT, "caller_type": "robot", "intent_id": "01HXTEST000000000000000006", "idempotency_key": "bad-caller-003"}
    r = await client.post("/intent", json=bad)
    assert r.status_code == 422
    errors = r.json()["detail"]
    paths = [".".join(str(loc) for loc in e["loc"]) for e in errors]
    assert any("caller_type" in p for p in paths), f"offending field not in paths: {paths}"


async def test_persisted_row_matches_submitted_payload(
    client: httpx.AsyncClient,
    db_engine,
) -> None:
    payload = {**_VALID_INTENT, "idempotency_key": "persist-check-004", "intent_id": "01HXTEST000000000000000007"}
    r = await client.post("/intent", json=payload)
    assert r.status_code == 202

    from sqlalchemy import text

    async with async_sessionmaker(db_engine, expire_on_commit=False)() as session:
        row = await session.execute(
            text("SELECT * FROM intents WHERE id = :id"),
            {"id": payload["intent_id"]},
        )
        row = row.mappings().one()

    assert row["id"] == payload["intent_id"]
    assert row["caller_type"] == payload["caller_type"]
    assert row["idempotency_key"] == payload["idempotency_key"]
    assert row["source"] == payload["source"]
    assert row["trigger_type"] == payload["trigger_type"]
    assert row["requested_outcome"] == payload["requested_outcome"]
    assert row["target"] == payload["target"]
    assert row["payload"] == payload["payload"]
    assert row["callback_url"] == payload["callback_url"]
    assert row["correlation_id"] == payload.get("correlation_id")
    assert row["status"] == "accepted"
    # constraints stored as-is from the submitted object
    stored_constraints = row["constraints"]
    assert stored_constraints["environment"] == payload["constraints"]["environment"]
    assert stored_constraints["max_cost_usd"] == payload["constraints"]["max_cost_usd"]


async def test_sse_emits_accepted_and_closes(
    client: httpx.AsyncClient,
) -> None:
    payload = {**_VALID_INTENT, "idempotency_key": "sse-check-005", "intent_id": "01HXTEST000000000000000008"}
    # create the intent first
    r = await client.post("/intent", json=payload)
    assert r.status_code == 202
    intent_id = r.json()["intent_id"]

    # consume the SSE stream
    events = []
    async with client.stream("GET", f"/intent/{intent_id}/events") as resp:
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")
        async for line in resp.aiter_lines():
            if line.startswith("event:"):
                events.append(line.split(":", 1)[1].strip())
            if line.startswith("data:"):
                pass  # consumed

    assert "accepted" in events, f"expected 'accepted' event, got: {events}"


async def test_status_endpoint_returns_intent_state(
    client: httpx.AsyncClient,
) -> None:
    payload = {**_VALID_INTENT, "idempotency_key": "status-check-006", "intent_id": "01HXTEST000000000000000009"}
    await client.post("/intent", json=payload)

    r = await client.get(f"/intent/{payload['intent_id']}/status")
    assert r.status_code == 200
    body = r.json()
    assert body["intent_id"] == payload["intent_id"]
    assert body["status"] == "accepted"
    assert body["requested_outcome"] == payload["requested_outcome"]
    assert body["last_contract"] is None


async def test_status_404_for_unknown_intent(
    client: httpx.AsyncClient,
) -> None:
    r = await client.get("/intent/01HXDOESNOTEXIST0000000000/status")
    assert r.status_code == 404
