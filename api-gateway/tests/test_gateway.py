"""Integration tests for api-gateway.

Uses httpx.AsyncClient against the FastAPI app backed by a Postgres testcontainer
(or API_GATEWAY_DATABASE_URL env var), a Redis testcontainer (or API_GATEWAY_REDIS_URL),
and a mock paperclipai ASGI app injected via FastAPI dependency override.

All tests in this module share one event loop (module scope).
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
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.claims import build_claims_headers, verify_claims_headers
from app.auth.keys import generate_api_key
from app.db.models import ApiKey, Base
from app.db.session import get_db
from app.main import app
from app.routes.intent import get_http_client

pytestmark = pytest.mark.asyncio(loop_scope="module")

# ---------------------------------------------------------------------------
# Fixtures: Postgres testcontainer (or DATABASE_URL)
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
    env_url = os.environ.get("API_GATEWAY_DATABASE_URL")
    if env_url:
        return env_url

    if not _docker_available():
        pytest.skip("Docker not available and API_GATEWAY_DATABASE_URL not set")

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


# ---------------------------------------------------------------------------
# Fixtures: Redis testcontainer (or REDIS_URL)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def redis_url() -> str:
    env_url = os.environ.get("API_GATEWAY_REDIS_URL")
    if env_url:
        return env_url

    if not _docker_available():
        pytest.skip("Docker not available and API_GATEWAY_REDIS_URL not set")

    from testcontainers.redis import RedisContainer

    with RedisContainer("redis:7") as r:
        yield f"redis://{r.get_container_host_ip()}:{r.get_exposed_port(6379)}/0"
        return
    return ""  # pragma: no cover


# ---------------------------------------------------------------------------
# Mock paperclipai ASGI app
# ---------------------------------------------------------------------------

_mock_paperclipai = FastAPI()
_received_headers: dict = {}


@_mock_paperclipai.post("/intent")
async def mock_intent(request: Request) -> JSONResponse:
    global _received_headers
    _received_headers = dict(request.headers)
    return JSONResponse(
        status_code=202,
        content={"intent_id": "01HXMOCK0000000000000001", "status": "accepted"},
    )


# ---------------------------------------------------------------------------
# Fixtures: test client with dependency overrides
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="module")
async def client(db_engine, redis_url: str) -> AsyncGenerator[httpx.AsyncClient, None]:
    import redis.asyncio as aioredis
    from app.routes import intent as intent_module

    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    # Override Redis with the test container client
    test_redis = aioredis.from_url(redis_url, decode_responses=True)
    intent_module._redis_client = test_redis

    # Override the signing secret so claims can be built
    os.environ.setdefault("API_GATEWAY_SIGNING_SECRET", "test-gateway-secret")

    # Override httpx client via FastAPI dependency — no global patching needed
    mock_transport = httpx.ASGITransport(app=_mock_paperclipai)

    async def _override_http_client() -> AsyncGenerator[httpx.AsyncClient, None]:
        async with httpx.AsyncClient(
            transport=mock_transport,
            base_url="http://mock-paperclipai",
        ) as c:
            yield c

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_http_client] = _override_http_client

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac

    app.dependency_overrides.clear()
    intent_module._redis_client = None
    await test_redis.aclose()


# ---------------------------------------------------------------------------
# Seed test API key (module-scoped, runs before all tests)
# ---------------------------------------------------------------------------

_TEST_KEY: str = ""
_TEST_KEY_ID: str = ""


@pytest_asyncio.fixture(scope="module", autouse=True)
async def seed_test_key(db_engine) -> None:
    global _TEST_KEY, _TEST_KEY_ID
    from ulid import ULID

    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    plaintext, prefix, hashed = generate_api_key()
    key_id = str(ULID())
    async with session_factory() as session:
        row = ApiKey(
            id=key_id,
            app_id="test-app",
            caller_type="n8n",
            key_prefix=prefix,
            key_hash=hashed,
            capabilities=["qualify_and_respond"],
            budget_pool="default",
            rate_limit_per_minute=100,
        )
        session.add(row)
        await session.commit()
    _TEST_KEY = plaintext
    _TEST_KEY_ID = key_id


_VALID_INTENT = {
    "intent_id": "01HXTEST000000000000000010",
    "source": "n8n:workflow_1:exec_1",
    "caller_type": "n8n",
    "trigger_type": "webhook",
    "requested_outcome": "qualify_and_respond",
    "payload": {},
    "constraints": {},
    "idempotency_key": "gw-test-key-001",
}


# ---------------------------------------------------------------------------
# Tests: authentication
# ---------------------------------------------------------------------------


async def test_missing_authorization_returns_401(client: httpx.AsyncClient) -> None:
    r = await client.post("/intent", json=_VALID_INTENT)
    assert r.status_code == 401


async def test_malformed_authorization_returns_401(client: httpx.AsyncClient) -> None:
    r = await client.post("/intent", json=_VALID_INTENT, headers={"Authorization": "Basic abc"})
    assert r.status_code == 401


async def test_invalid_bearer_returns_401(client: httpx.AsyncClient) -> None:
    r = await client.post(
        "/intent", json=_VALID_INTENT, headers={"Authorization": "Bearer totally-invalid-key"}
    )
    assert r.status_code == 401


async def test_revoked_key_returns_401(client: httpx.AsyncClient, db_engine) -> None:
    from datetime import UTC, datetime
    from ulid import ULID

    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    plaintext, prefix, hashed = generate_api_key()
    revoked_id = str(ULID())
    async with session_factory() as session:
        row = ApiKey(
            id=revoked_id,
            app_id="revoked-app",
            caller_type="n8n",
            key_prefix=prefix,
            key_hash=hashed,
            capabilities=[],
            budget_pool="default",
            rate_limit_per_minute=60,
            revoked_at=datetime.now(UTC),
        )
        session.add(row)
        await session.commit()

    r = await client.post(
        "/intent", json=_VALID_INTENT, headers={"Authorization": f"Bearer {plaintext}"}
    )
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Tests: caller_type claim validation
# ---------------------------------------------------------------------------


async def test_caller_type_mismatch_returns_400(client: httpx.AsyncClient) -> None:
    bad = {**_VALID_INTENT, "caller_type": "client_app", "idempotency_key": "gw-mismatch-001"}
    r = await client.post("/intent", json=bad, headers={"Authorization": f"Bearer {_TEST_KEY}"})
    assert r.status_code == 400
    assert "mismatch" in r.json()["detail"]


# ---------------------------------------------------------------------------
# Tests: valid request forwarding
# ---------------------------------------------------------------------------


async def test_valid_request_forwarded_with_claims_headers(client: httpx.AsyncClient) -> None:
    payload = {**_VALID_INTENT, "idempotency_key": "gw-fwd-001"}
    r = await client.post("/intent", json=payload, headers={"Authorization": f"Bearer {_TEST_KEY}"})
    assert r.status_code == 202, r.text

    # All five claims headers must be present on the forwarded request
    assert "x-caller-type" in _received_headers
    assert "x-app-id" in _received_headers
    assert "x-capabilities" in _received_headers
    assert "x-budget-pool" in _received_headers
    assert "x-claims-signature" in _received_headers

    assert verify_claims_headers(_received_headers), "X-Claims-Signature did not verify"
    assert _received_headers["x-caller-type"] == "n8n"
    assert _received_headers["x-app-id"] == "test-app"


async def test_capabilities_header_is_base64_json(client: httpx.AsyncClient) -> None:
    payload = {**_VALID_INTENT, "idempotency_key": "gw-caps-001"}
    await client.post("/intent", json=payload, headers={"Authorization": f"Bearer {_TEST_KEY}"})
    caps_raw = _received_headers.get("x-capabilities", "")
    decoded = json.loads(base64.b64decode(caps_raw).decode())
    assert isinstance(decoded, list)
    assert "qualify_and_respond" in decoded


async def test_authorization_header_stripped_from_upstream(client: httpx.AsyncClient) -> None:
    payload = {**_VALID_INTENT, "idempotency_key": "gw-strip-auth-001"}
    await client.post("/intent", json=payload, headers={"Authorization": f"Bearer {_TEST_KEY}"})
    assert "authorization" not in _received_headers


# ---------------------------------------------------------------------------
# Tests: rate limiting
# ---------------------------------------------------------------------------


async def test_rate_limit_returns_429(client: httpx.AsyncClient, db_engine) -> None:
    from ulid import ULID

    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    plaintext, prefix, hashed = generate_api_key()
    app_id = f"rate-limited-app-{str(ULID())}"
    rl_id = str(ULID())
    async with session_factory() as session:
        row = ApiKey(
            id=rl_id,
            app_id=app_id,
            caller_type="n8n",
            key_prefix=prefix,
            key_hash=hashed,
            capabilities=[],
            budget_pool="default",
            rate_limit_per_minute=2,
        )
        session.add(row)
        await session.commit()

    headers = {"Authorization": f"Bearer {plaintext}"}
    payload = {**_VALID_INTENT}

    r1 = await client.post("/intent", json={**payload, "idempotency_key": "gw-rl-001"}, headers=headers)
    r2 = await client.post("/intent", json={**payload, "idempotency_key": "gw-rl-002"}, headers=headers)
    r3 = await client.post("/intent", json={**payload, "idempotency_key": "gw-rl-003"}, headers=headers)

    assert r1.status_code == 202
    assert r2.status_code == 202
    assert r3.status_code == 429
    assert "Retry-After" in r3.headers
    assert int(r3.headers["Retry-After"]) > 0


# ---------------------------------------------------------------------------
# Tests: management CLI
# ---------------------------------------------------------------------------


async def test_cli_create_list_revoke(db_engine, db_url: str) -> None:
    import argparse
    import sys
    from io import StringIO

    from app.cli import cmd_create_key, cmd_list_keys, cmd_revoke_key

    # Point CLI at the testcontainer DB
    os.environ["API_GATEWAY_DATABASE_URL"] = db_url

    create_args = argparse.Namespace(
        app_id="cli-test-app",
        caller_type="client_app",
        capabilities="read,write",
        budget_pool="premium",
        rate=30,
    )

    captured = StringIO()
    sys.stdout, orig = captured, sys.stdout
    await cmd_create_key(create_args)
    sys.stdout = orig
    output = captured.getvalue()

    assert "cli-test-app" in output
    assert "client_app" in output
    assert "agk_" in output

    key_id = None
    for line in output.splitlines():
        if line.startswith("Key ID:"):
            key_id = line.split(":", 1)[1].strip()
            break
    assert key_id is not None

    captured2 = StringIO()
    sys.stdout, orig = captured2, sys.stdout
    await cmd_list_keys(argparse.Namespace())
    sys.stdout = orig
    assert "cli-test-app" in captured2.getvalue()
    assert key_id in captured2.getvalue()

    captured3 = StringIO()
    sys.stdout, orig = captured3, sys.stdout
    await cmd_revoke_key(argparse.Namespace(key_id=key_id))
    sys.stdout = orig
    assert "Revoked" in captured3.getvalue()

    captured4 = StringIO()
    sys.stdout, orig = captured4, sys.stdout
    await cmd_list_keys(argparse.Namespace())
    sys.stdout = orig
    assert "REVOKED" in captured4.getvalue()
