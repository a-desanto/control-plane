import os
from typing import Annotated, AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.contracts.intent import Model as IntentModel
from app.db.models import Contract, Intent
from app.db.session import get_db

router = APIRouter()

_BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")


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

    # X-Caller-Type from the gateway is authoritative; body must match (set by middleware).
    header_caller_type = getattr(request.state, "caller_type", None) or body.caller_type.value
    if header_caller_type != body.caller_type.value:
        raise HTTPException(
            status_code=400,
            detail=f"caller_type mismatch: header '{header_caller_type}' != body '{body.caller_type.value}'",
        )
    caller_type = header_caller_type

    # De-dup: return existing intent if (caller_type, idempotency_key) already seen.
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

    async def _stream() -> AsyncGenerator[dict, None]:
        yield {"event": "accepted", "data": f'{{"intent_id": "{intent_id}", "status": "accepted"}}'}

    return EventSourceResponse(_stream())
