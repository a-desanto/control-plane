"""Orchestration integration tests.

These tests exercise the orchestration loop end-to-end against a real Postgres
testcontainer. The worker's process_intent() is called directly (no separate
process), keeping tests fast and deterministic.

Requires: Docker available and DATABASE_URL not set (or set to a real Postgres).
"""

import asyncio
import os
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base, CallbackAttempt, Contract, Intent, Plan
from app.tool_registry import McpTransport, ToolRegistryEntry

pytestmark = pytest.mark.asyncio(loop_scope="module")

ECHO_MCP_PATH = (
    Path(__file__).parent.parent.parent / "mcp-servers" / "cli" / "echo-mcp" / "echo_mcp.py"
)

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


# ---------------------------------------------------------------------------
# Postgres fixture
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


# Expose the db_url as a module-level accessible fixture for process_intent calls.
@pytest.fixture(scope="module")
def asyncpg_url(db_url: str) -> str:
    return db_url.replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgresql+psycopg2://", "postgresql://"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_intent(
    session_factory,
    intent_id: str,
    idempotency_key: str,
    payload: dict | None = None,
    callback_url: str | None = None,
    requested_outcome: str = "echo_test",
) -> Intent:
    async with session_factory() as db:
        row = Intent(
            id=intent_id,
            caller_type="client_app",
            idempotency_key=idempotency_key,
            source="test",
            trigger_type="manual",
            requested_outcome=requested_outcome,
            payload=payload or {"text": "hello"},
            constraints={"read_only": False},
            callback_url=callback_url,
            status="accepted",
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_echo_test_intent_completes(session_factory, asyncpg_url) -> None:
    """Full E2E: accepted intent → plan → contract → echo call → completed."""
    if not ECHO_MCP_PATH.exists():
        pytest.skip("echo_mcp.py not found")

    from app.orchestration import worker as w

    w._registry = [_ECHO_REGISTRY_ENTRY]

    intent_id = "01HXWRKR000000000000000001"
    await _create_intent(session_factory, intent_id, "orch-e2e-001")

    await w.process_intent(intent_id, session_factory, asyncpg_url)

    async with session_factory() as db:
        intent = await db.get(Intent, intent_id)
        assert intent.status == "completed"

        plan = await db.scalar(select(Plan).where(Plan.intent_id == intent_id))
        assert plan is not None
        assert plan.workflow_id == "echo_test"

        contract = await db.scalar(
            select(Contract).where(Contract.intent_id == intent_id)
        )
        assert contract is not None
        assert contract.tool_name == "echo"
        assert contract.status == "completed"
        assert contract.result is not None
        assert contract.result["status"] == "success"
        assert contract.result["data"]["text"] == "hello"
        assert contract.result["data"]["length"] == 5
        assert contract.parent_contract_id is None


async def test_contract_result_validates_as_tool_output_success(session_factory) -> None:
    """The stored contract.result must parse as ToolOutputSuccess v3.3."""
    if not ECHO_MCP_PATH.exists():
        pytest.skip("echo_mcp.py not found")

    async with session_factory() as db:
        contract = await db.scalar(
            select(Contract).where(
                Contract.intent_id == "01HXWRKR000000000000000001"
            )
        )
    assert contract is not None

    from app.contracts.tool_output import ToolOutput

    output = ToolOutput.model_validate(contract.result)
    assert output.root.status == "success"


async def test_idempotency_same_intent_processed_once(session_factory, asyncpg_url) -> None:
    """Calling process_intent twice with the same intent_id only runs the tool once."""
    if not ECHO_MCP_PATH.exists():
        pytest.skip("echo_mcp.py not found")

    from app.orchestration import worker as w

    w._registry = [_ECHO_REGISTRY_ENTRY]

    intent_id = "01HXWRKR000000000000000002"
    await _create_intent(session_factory, intent_id, "orch-idem-002")

    await w.process_intent(intent_id, session_factory, asyncpg_url)
    await w.process_intent(intent_id, session_factory, asyncpg_url)  # second call is a no-op

    async with session_factory() as db:
        contracts = await db.scalars(
            select(Contract).where(Contract.intent_id == intent_id)
        )
        contract_list = contracts.all()
    assert len(contract_list) == 1, "Echo must be invoked exactly once"


async def test_unknown_requested_outcome_fails_intent(session_factory, asyncpg_url) -> None:
    from app.orchestration import worker as w

    w._registry = [_ECHO_REGISTRY_ENTRY]

    intent_id = "01HXWRKR000000000000000003"
    await _create_intent(
        session_factory,
        intent_id,
        "orch-unknown-003",
        requested_outcome="nonexistent_workflow",
    )

    await w.process_intent(intent_id, session_factory, asyncpg_url)

    async with session_factory() as db:
        intent = await db.get(Intent, intent_id)
        assert intent.status == "failed"


async def test_payload_text_passed_to_echo(session_factory, asyncpg_url) -> None:
    """Custom payload.text is forwarded to the echo tool."""
    if not ECHO_MCP_PATH.exists():
        pytest.skip("echo_mcp.py not found")

    from app.orchestration import worker as w

    w._registry = [_ECHO_REGISTRY_ENTRY]

    intent_id = "01HXWRKR000000000000000004"
    await _create_intent(
        session_factory,
        intent_id,
        "orch-payload-004",
        payload={"text": "paperclipai"},
    )

    await w.process_intent(intent_id, session_factory, asyncpg_url)

    async with session_factory() as db:
        contract = await db.scalar(
            select(Contract).where(Contract.intent_id == intent_id)
        )
    assert contract.result["data"]["text"] == "paperclipai"
    assert contract.result["data"]["length"] == len("paperclipai")


async def test_worker_resumes_running_intent(session_factory, asyncpg_url) -> None:
    """An intent stuck in 'running' (worker died mid-flight) is recovered on restart."""
    if not ECHO_MCP_PATH.exists():
        pytest.skip("echo_mcp.py not found")

    from app.orchestration import worker as w

    w._registry = [_ECHO_REGISTRY_ENTRY]

    intent_id = "01HXWRKR000000000000000005"
    async with session_factory() as db:
        row = Intent(
            id=intent_id,
            caller_type="client_app",
            idempotency_key="orch-resume-005",
            source="test",
            trigger_type="manual",
            requested_outcome="echo_test",
            payload={"text": "resume"},
            constraints={"read_only": False},
            status="running",  # simulate mid-flight crash
        )
        db.add(row)
        await db.commit()

    await w.process_intent(intent_id, session_factory, asyncpg_url)

    async with session_factory() as db:
        intent = await db.get(Intent, intent_id)
        assert intent.status == "completed"
