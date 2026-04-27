"""Orchestration worker — runs as a separate process under honcho.

Lifecycle:
  1. On startup: recover any non-terminal intents (missed while down).
  2. LISTEN on 'paperclipai_intent_ready' for new intents.
  3. Polling fallback every 30 s catches any notifications that slipped through.
  4. SIGTERM / SIGINT sets a stop event; the current intent finishes before exit.
"""

import asyncio
import json
import logging
import os
import signal
from datetime import UTC, datetime

import asyncpg
import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.contracts.tool_output import ToolOutputFailure, ToolOutputSuccess
from app.db.models import Contract, Intent, Plan
from app.mcp_client.client import invoke_tool
from app.orchestration.callback import emit_callback
from app.orchestration.planner import plan_for_intent
from app.tool_registry import ToolRegistryEntry, load_tool_registry

logger = structlog.get_logger(__name__)

_DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/paperclipai",
)
_BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")

INTENT_READY_CHANNEL = "paperclipai_intent_ready"
EVENTS_CHANNEL = "paperclipai_events"
POLL_INTERVAL = 30.0

_stop = asyncio.Event()
_registry: list[ToolRegistryEntry] = []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _raw_url(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgresql+psycopg2://", "postgresql://"
    )


def _find_registry_entry(
    tool_name: str, tool_version: str
) -> ToolRegistryEntry | None:
    for entry in _registry:
        if entry.tool_name == tool_name and entry.tool_version == tool_version:
            return entry
    return None


def _extract_image_digest(command: list[str]) -> str | None:
    for part in command:
        if part.startswith("sha256:"):
            return part
    return None


async def _notify(conn: asyncpg.Connection, payload: dict) -> None:
    await conn.execute(
        f"SELECT pg_notify($1, $2)",
        EVENTS_CHANNEL,
        json.dumps(payload),
    )


# ---------------------------------------------------------------------------
# Core processing
# ---------------------------------------------------------------------------


async def process_intent(
    intent_id: str,
    session_factory: async_sessionmaker,
    database_url: str | None = None,
) -> None:
    log = logger.bind(intent_id=intent_id)

    async with session_factory() as db:
        intent: Intent | None = await db.get(Intent, intent_id)
        if intent is None:
            log.warning("intent_not_found")
            return
        if intent.status in ("completed", "failed"):
            log.debug("intent_already_terminal", status=intent.status)
            return

    # Open a dedicated asyncpg connection for NOTIFYs within this processing run.
    pg_url = _raw_url(database_url or _DATABASE_URL)
    notify_conn = await asyncpg.connect(pg_url)
    try:
        await _process(intent_id, session_factory, notify_conn)
    finally:
        await notify_conn.close()


async def _process(
    intent_id: str,
    session_factory: async_sessionmaker,
    notify_conn: asyncpg.Connection,
) -> None:
    log = logger.bind(intent_id=intent_id)
    now_iso = datetime.now(UTC).isoformat()

    async with session_factory() as db:
        intent: Intent | None = await db.get(Intent, intent_id)
        if intent is None:
            return

        # --- Mark intent as running ---
        if intent.status == "accepted":
            intent.status = "running"
            await db.commit()

        # --- Idempotent plan creation ---
        from app.contracts.workflow_plan import Step

        plan_row: Plan | None = await db.scalar(
            select(Plan).where(Plan.intent_id == intent_id)
        )
        if plan_row is None:
            try:
                plan = await plan_for_intent(intent, db)
            except ValueError as exc:
                log.warning("planning_failed", error=str(exc))
                intent.status = "failed"
                await db.commit()
                await _notify(
                    notify_conn,
                    {"intent_id": intent_id, "event": "failed", "error": str(exc)},
                )
                return
            step = plan.steps[0]
            plan_id = str(plan.plan_id)
            workflow_id = plan.workflow_id
            workflow_version = plan.workflow_version
        else:
            steps_raw = plan_row.steps
            step_data = steps_raw[0] if steps_raw else {}
            plan_id = plan_row.id
            workflow_id = plan_row.workflow_id
            workflow_version = plan_row.workflow_version
            step = Step(**step_data)

        # --- Idempotent contract creation ---
        contract_row: Contract | None = await db.scalar(
            select(Contract).where(
                Contract.intent_id == intent_id,
                Contract.step_id == step.step_id,
            )
        )
        if contract_row is None:
            from ulid import ULID

            contract_id = str(ULID())
            registry_entry = _find_registry_entry(step.tool_name, step.tool_version)
            image_digest = (
                _extract_image_digest(registry_entry.mcp.command)
                if registry_entry and registry_entry.mcp.command
                else None
            )
            input_data = (
                {"text": intent.payload.get("text", "hello")}
                if step.tool_name == "echo"
                else intent.payload
            )

            contract_row = Contract(
                id=contract_id,
                intent_id=intent_id,
                plan_id=plan_id,
                workflow_id=workflow_id,
                workflow_version=workflow_version,
                step_id=step.step_id,
                tool_name=step.tool_name,
                tool_version=step.tool_version,
                execution_mode=step.execution_mode.value,
                input_schema_ref=step.input_schema_ref,
                output_schema_ref=step.output_schema_ref,
                image_digest=image_digest,
                status="pending",
                instruction={
                    "contract_id": contract_id,
                    "intent_id": intent_id,
                    "plan_id": plan_id,
                    "step_id": step.step_id,
                    "tool_name": step.tool_name,
                    "tool_version": step.tool_version,
                    "tool_implementation": {
                        "protocol": "mcp",
                        "transport": registry_entry.mcp.transport if registry_entry else "stdio",
                        "image_digest": image_digest,
                    },
                    "execution_mode": step.execution_mode.value,
                    "input_schema_ref": step.input_schema_ref,
                    "output_schema_ref": step.output_schema_ref,
                    "input": input_data,
                    "cost_budget": {"class": "default", "ceiling_usd": 0.0},
                    "policy_decisions": [
                        {
                            "policy": "capability_gate",
                            "decision": "allow",
                            "reason": "permissive policy for Phase 2B",
                            "evaluated_at": now_iso,
                        }
                    ],
                    "observability": {"trace_id": contract_id},
                },
            )
            db.add(contract_row)
            await db.commit()
            log.info("contract_created", contract_id=contract_id)

            await _notify(
                notify_conn,
                {
                    "intent_id": intent_id,
                    "event": "contract_started",
                    "contract_id": contract_id,
                    "tool_name": step.tool_name,
                },
            )
        else:
            contract_id = contract_row.id
            registry_entry = _find_registry_entry(step.tool_name, step.tool_version)
            input_data = (
                contract_row.instruction.get("input", {})
                if contract_row.instruction
                else {}
            )

        # --- Execute if still pending ---
        tool_output: ToolOutputSuccess | ToolOutputFailure | None = None
        if contract_row.status == "pending":
            if registry_entry is None:
                tool_output: ToolOutputSuccess | ToolOutputFailure = _make_failure(
                    contract_id,
                    step.output_schema_ref,
                    "TOOL_NOT_FOUND",
                    f"No registry entry for {step.tool_name}@{step.tool_version}",
                )
            else:
                tool_output = await invoke_tool(registry_entry, contract_id, input_data)

            contract_row.status = (
                "completed" if tool_output.status == "success" else "failed"
            )
            contract_row.result = tool_output.model_dump(mode="json")
            await db.commit()
            log.info(
                "contract_completed",
                contract_id=contract_id,
                status=contract_row.status,
            )

            await _notify(
                notify_conn,
                {
                    "intent_id": intent_id,
                    "event": "contract_completed",
                    "contract_id": contract_id,
                    "status": contract_row.status,
                },
            )

        # --- Update intent terminal status ---
        intent.status = (
            "completed" if contract_row.status == "completed" else "failed"
        )
        await db.commit()

        terminal_event = "completed" if intent.status == "completed" else "failed"
        await _notify(
            notify_conn,
            {
                "intent_id": intent_id,
                "event": terminal_event,
                "status": intent.status,
            },
        )
        log.info("intent_terminal", status=intent.status)

        # --- Callback ---
        if tool_output is not None and intent.callback_url and isinstance(tool_output, ToolOutputSuccess):
            await emit_callback(
                intent,
                tool_output.schema_ref,
                tool_output.data,
                _BASE_URL,
            )


def _make_failure(contract_id, schema_ref, code, message):
    from app.contracts.tool_output import Category, ToolError, ToolOutputFailure
    from ulid import ULID

    return ToolOutputFailure(
        contract_id=ULID.from_str(contract_id),
        status="failure",
        schema_ref=schema_ref,
        error=ToolError(code=code, message=message, category=Category.permanent, retriable=False),
        completed_at=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# Event loop
# ---------------------------------------------------------------------------


async def _main() -> None:
    global _registry
    _registry = load_tool_registry()

    engine = create_async_engine(_DATABASE_URL, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    queue: asyncio.Queue[str] = asyncio.Queue()

    # Set up SIGTERM / SIGINT handling
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _stop.set)

    # Connect asyncpg for LISTEN
    listen_conn = await asyncpg.connect(_raw_url(_DATABASE_URL))

    async def _on_notify(conn, pid, channel, payload):
        await queue.put(payload)

    await listen_conn.add_listener(INTENT_READY_CHANNEL, _on_notify)
    logger.info("worker_started", channel=INTENT_READY_CHANNEL)

    # Recover non-terminal intents on startup
    async with session_factory() as db:
        rows = await db.scalars(
            select(Intent).where(Intent.status.in_(["accepted", "running"]))
        )
        for intent in rows.all():
            await queue.put(intent.id)

    try:
        while not _stop.is_set():
            try:
                intent_id = await asyncio.wait_for(queue.get(), timeout=POLL_INTERVAL)
            except asyncio.TimeoutError:
                # Polling fallback: re-enqueue any non-terminal intents
                async with session_factory() as db:
                    rows = await db.scalars(
                        select(Intent).where(Intent.status.in_(["accepted", "running"]))
                    )
                    for intent in rows.all():
                        await queue.put(intent.id)
                continue

            if _stop.is_set():
                break

            try:
                await process_intent(intent_id, session_factory)
            except Exception:
                logger.exception("process_intent_error", intent_id=intent_id)
    finally:
        await listen_conn.remove_listener(INTENT_READY_CHANNEL, _on_notify)
        await listen_conn.close()
        await engine.dispose()
        logger.info("worker_stopped")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_main())
