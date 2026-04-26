import asyncio
import logging
from datetime import UTC, datetime

import httpx

from app.db.models import CallbackAttempt, Intent
from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)

_RETRY_DELAYS = [1.0, 2.0, 4.0]


async def _post_with_retries(
    callback_url: str,
    payload: dict,
    intent_id: str,
) -> None:
    attempt_number = 0
    async with httpx.AsyncClient(timeout=10.0) as http:
        for delay in [0.0] + _RETRY_DELAYS:
            if delay:
                await asyncio.sleep(delay)
            attempt_number += 1
            status_code: int | None = None
            error_message: str | None = None
            succeeded = False
            try:
                resp = await http.post(callback_url, json=payload)
                status_code = resp.status_code
                succeeded = resp.status_code < 400
            except Exception as exc:
                error_message = str(exc)
                logger.warning(
                    "Callback attempt %d failed for intent_id=%s: %s",
                    attempt_number,
                    intent_id,
                    exc,
                )

            try:
                async with AsyncSessionLocal() as db:
                    row = CallbackAttempt(
                        intent_id=intent_id,
                        attempt_number=attempt_number,
                        callback_url=callback_url,
                        status_code=status_code,
                        succeeded=succeeded,
                        error_message=error_message,
                        attempted_at=datetime.now(UTC),
                    )
                    db.add(row)
                    await db.commit()
            except Exception:
                logger.exception("Failed to persist callback_attempt for intent_id=%s", intent_id)

            if succeeded:
                logger.info(
                    "Callback delivered on attempt %d for intent_id=%s status=%d",
                    attempt_number,
                    intent_id,
                    status_code,
                )
                return

    logger.error("All callback attempts exhausted for intent_id=%s", intent_id)


async def emit_callback(
    intent: Intent,
    result_schema_ref: str,
    result_data: dict,
    base_url: str,
) -> None:
    if not intent.callback_url:
        return

    payload = {
        "intent_id": intent.id,
        "correlation_id": intent.correlation_id,
        "status": intent.status,
        "result": {
            "schema_ref": result_schema_ref,
            "data": result_data,
        },
        "adaptations_applied": [],
        "cost_usd": 0.0,
        "audit_link": f"{base_url}/intent/{intent.id}/audit",
    }

    asyncio.create_task(
        _post_with_retries(str(intent.callback_url), payload, intent.id)
    )
