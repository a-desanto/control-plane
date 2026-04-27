"""Phase 2A: ClaimsVerificationMiddleware integration tests.

Verifies that paperclipai rejects /intent* requests with missing or tampered
X-Claims-Signature, and accepts requests with a valid signature.

Uses httpx.AsyncClient against the real FastAPI app (with BYPASS_CLAIMS_CHECK unset)
and a Postgres testcontainer.
"""

import base64
import hashlib
import hmac
import json
import os
from collections.abc import AsyncGenerator

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import Base

pytestmark = pytest.mark.asyncio(loop_scope="module")

_TEST_SECRET = "test-signing-secret-phase2a"

_VALID_INTENT = {
    "intent_id": "01HXMWTEST0000000000000001",
    "source": "n8n:workflow_mw:exec_1",
    "caller_type": "n8n",
    "trigger_type": "webhook",
    "requested_outcome": "qualify_and_respond",
    "payload": {},
    "constraints": {},
    "idempotency_key": "mw-test-key-001",
}


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
async def client(db_engine) -> AsyncGenerator[httpx.AsyncClient, None]:
    from app.db.session import get_db
    from app.main import app

    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db

    # Set the signing secret; env checks are lazy so no reload needed.
    os.environ["API_GATEWAY_SIGNING_SECRET"] = _TEST_SECRET
    os.environ.pop("BYPASS_CLAIMS_CHECK", None)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac

    app.dependency_overrides.clear()
    os.environ.pop("API_GATEWAY_SIGNING_SECRET", None)


def _make_claims_headers(
    caller_type: str = "n8n",
    app_id: str = "test-app",
    capabilities: list | None = None,
    budget_pool: str = "default",
    secret: str = _TEST_SECRET,
) -> dict[str, str]:
    if capabilities is None:
        capabilities = []
    caps_b64 = base64.b64encode(json.dumps(capabilities).encode()).decode()
    canonical = f"{caller_type}|{app_id}|{caps_b64}|{budget_pool}"
    sig = hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    return {
        "X-Caller-Type": caller_type,
        "X-App-Id": app_id,
        "X-Capabilities": caps_b64,
        "X-Budget-Pool": budget_pool,
        "X-Claims-Signature": sig,
    }


async def test_missing_signature_returns_401(client: httpx.AsyncClient) -> None:
    r = await client.post("/intent", json=_VALID_INTENT)
    assert r.status_code == 401
    assert "signature" in r.json()["detail"].lower() or "claims" in r.json()["detail"].lower()


async def test_tampered_signature_returns_401(client: httpx.AsyncClient) -> None:
    headers = _make_claims_headers()
    headers["X-Claims-Signature"] = "deadbeef" * 8  # wrong sig
    r = await client.post("/intent", json=_VALID_INTENT, headers=headers)
    assert r.status_code == 401


async def test_wrong_secret_returns_401(client: httpx.AsyncClient) -> None:
    # Sign with a different secret
    headers = _make_claims_headers(secret="wrong-secret")
    r = await client.post("/intent", json={**_VALID_INTENT, "idempotency_key": "mw-wrong-secret"}, headers=headers)
    assert r.status_code == 401


async def test_valid_signature_accepted(client: httpx.AsyncClient) -> None:
    headers = _make_claims_headers()
    r = await client.post(
        "/intent",
        json={**_VALID_INTENT, "idempotency_key": "mw-valid-sig-001"},
        headers=headers,
    )
    assert r.status_code == 202, r.text


async def test_health_endpoint_bypasses_middleware(client: httpx.AsyncClient) -> None:
    # /health is not under /intent, so middleware does not apply
    r = await client.get("/health")
    assert r.status_code == 200


async def test_caller_type_from_header_stored(client: httpx.AsyncClient, db_engine) -> None:
    """The header X-Caller-Type is authoritative; its value is persisted."""
    from sqlalchemy import text

    headers = _make_claims_headers(caller_type="n8n")
    payload = {**_VALID_INTENT, "idempotency_key": "mw-header-caller-001", "caller_type": "n8n",
               "intent_id": "01HXMWTEST0000000000000099"}
    r = await client.post("/intent", json=payload, headers=headers)
    assert r.status_code == 202, r.text

    async with async_sessionmaker(db_engine, expire_on_commit=False)() as session:
        row = await session.execute(
            text("SELECT caller_type FROM intents WHERE id = :id"),
            {"id": payload["intent_id"]},
        )
        row = row.mappings().one()

    assert row["caller_type"] == "n8n"
