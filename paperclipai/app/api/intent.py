import asyncio
import json
import os
from typing import Annotated, AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app import events as ev
from app.contracts.intent import Model as IntentModel
from app.db.models import Contract, Intent
from app.db.session import AsyncSessionLocal, get_db

router = APIRouter()

_BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")

_TERMINAL = {"completed", "failed"}


def _intent_urls(intent_id: str) -> dict:
    return {
        "audit_link": f"{_BASE_URL}/intent/{intent_id}/audit",
        "events_url": f"{_BASE_URL}/intent/{intent_id}/events",
        "status_url": f"{_BASE_URL}/intent/{intent_id}/status",
    }


def _accepted_response(intent_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=202,
        content={"intent_id": intent_id, "status": "accepted", **_intent_urls(intent_id)},
    )


@router.post("/intent")
async def create_intent(
    request: Request,
    body: IntentModel,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> JSONResponse:
    intent_id = str(body.intent_id)

    header_caller_type = getattr(request.state, "caller_type", None) or body.caller_type.value
    if header_caller_type != body.caller_type.value:
        raise HTTPException(
            status_code=400,
            detail=f"caller_type mismatch: header '{header_caller_type}' != body '{body.caller_type.value}'",
        )
    caller_type = header_caller_type

    existing = await db.scalar(
        select(Intent).where(
            Intent.caller_type == caller_type,
            Intent.idempotency_key == body.idempotency_key,
        )
    )
    if existing is not None:
        return _accepted_response(existing.id)

    row = Intent(
        id=intent_id,
        caller_type=caller_type,
        idempotency_key=body.idempotency_key,
        source=body.source,
        trigger_type=body.trigger_type.value,
        requested_outcome=body.requested_outcome,
        target=body.target,
        payload=body.payload,
        constraints=body.constraints.model_dump(exclude_none=False),
        callback_url=str(body.callback_url) if body.callback_url else None,
        correlation_id=body.correlation_id,
        status="accepted",
    )
    db.add(row)
    try:
        # Flush to DB then NOTIFY in the same transaction so the worker only
        # sees the intent after the row is committed.
        await db.flush()
        await db.execute(
            text("SELECT pg_notify('paperclipai_intent_ready', :payload)"),
            {"payload": intent_id},
        )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        existing = await db.scalar(
            select(Intent).where(
                Intent.caller_type == caller_type,
                Intent.idempotency_key == body.idempotency_key,
            )
        )
        if existing is None:
            raise HTTPException(status_code=409, detail="intent_id collision")
        return _accepted_response(existing.id)

    return _accepted_response(intent_id)


class IntentStatusResponse(BaseModel):
    intent_id: str
    status: str
    requested_outcome: str
    caller_type: str
    created_at: str
    last_contract: dict | None


@router.get("/intent/{intent_id}/status")
async def get_intent_status(
    intent_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> IntentStatusResponse:
    intent = await db.scalar(select(Intent).where(Intent.id == intent_id))
    if intent is None:
        raise HTTPException(status_code=404, detail="intent not found")

    last_contract_row = await db.scalar(
        select(Contract)
        .where(Contract.intent_id == intent_id)
        .order_by(Contract.created_at.desc())
        .limit(1)
    )
    last_contract = None
    if last_contract_row is not None:
        last_contract = {
            "contract_id": last_contract_row.id,
            "status": last_contract_row.status,
            "tool_name": last_contract_row.tool_name,
            "created_at": last_contract_row.created_at.isoformat(),
        }

    return IntentStatusResponse(
        intent_id=intent.id,
        status=intent.status,
        requested_outcome=intent.requested_outcome,
        caller_type=intent.caller_type,
        created_at=intent.created_at.isoformat(),
        last_contract=last_contract,
    )


@router.get("/intent/{intent_id}/events")
async def get_intent_events(
    intent_id: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> EventSourceResponse:
    intent = await db.scalar(select(Intent).where(Intent.id == intent_id))
    if intent is None:
        raise HTTPException(status_code=404, detail="intent not found")

    # Subscribe to the fan-out queue BEFORE checking current state to avoid
    # a race where the worker NOTIFYs between our DB read and queue subscribe.
    queue = ev.subscribe(intent_id)

    async def _stream() -> AsyncGenerator[dict, None]:
        try:
            # Always emit "accepted" immediately as a liveness signal.
            yield {
                "event": "accepted",
                "data": json.dumps({"intent_id": intent_id, "status": "accepted"}),
            }

            # If intent is already terminal, synthesize events from DB and close.
            try:
                async with AsyncSessionLocal() as stream_db:
                    fresh_intent = await stream_db.get(Intent, intent_id)
                    if fresh_intent and fresh_intent.status in _TERMINAL:
                        # Emit synthetic events for completed contracts.
                        contracts = await stream_db.scalars(
                            select(Contract)
                            .where(Contract.intent_id == intent_id)
                            .order_by(Contract.created_at)
                        )
                        for c in contracts.all():
                            yield {
                                "event": "contract_started",
                                "data": json.dumps(
                                    {"intent_id": intent_id, "contract_id": c.id}
                                ),
                            }
                            yield {
                                "event": "contract_completed",
                                "data": json.dumps(
                                    {
                                        "intent_id": intent_id,
                                        "contract_id": c.id,
                                        "status": c.status,
                                    }
                                ),
                            }
                        yield {
                            "event": fresh_intent.status,
                            "data": json.dumps(
                                {"intent_id": intent_id, "status": fresh_intent.status}
                            ),
                        }
                        return
            except Exception:
                return  # DB unavailable; yield "accepted" was already sent above

            # Wait for live notifications from the worker.
            while True:
                if await request.is_disconnected():
                    return
                try:
                    event_data = await asyncio.wait_for(queue.get(), timeout=5.0)
                except asyncio.TimeoutError:
                    # Heartbeat + re-check terminal state
                    try:
                        async with AsyncSessionLocal() as check_db:
                            check_intent = await check_db.get(Intent, intent_id)
                            if check_intent and check_intent.status in _TERMINAL:
                                yield {
                                    "event": check_intent.status,
                                    "data": json.dumps(
                                        {
                                            "intent_id": intent_id,
                                            "status": check_intent.status,
                                        }
                                    ),
                                }
                                return
                    except Exception:
                        return
                    continue

                event_name = event_data.get("event", "update")
                yield {
                    "event": event_name,
                    "data": json.dumps(event_data),
                }
                if event_name in _TERMINAL:
                    return
        finally:
            ev.unsubscribe(intent_id, queue)

    return EventSourceResponse(_stream())
