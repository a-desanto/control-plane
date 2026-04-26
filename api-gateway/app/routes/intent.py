import json
import os
import time
import uuid
from collections.abc import AsyncGenerator
from typing import Annotated

import httpx
import redis.asyncio as aioredis
import structlog
from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.claims import build_claims_headers
from app.auth.keys import verify_api_key
from app.db.models import ApiKey, AuditLog
from app.db.session import get_db
from app.ratelimit.bucket import check_rate_limit

log = structlog.get_logger()
router = APIRouter()

_PAPERCLIPAI_URL = os.environ.get("PAPERCLIPAI_INTERNAL_URL", "http://paperclipai:8000")
_REDIS_URL = os.environ.get("API_GATEWAY_REDIS_URL", "redis://localhost:6379/0")

_redis_client: aioredis.Redis | None = None


def _get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(_REDIS_URL, decode_responses=True)
    return _redis_client


async def get_http_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Dependency that yields a configured httpx client for upstream forwarding."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        yield client


async def _lookup_key(token: str, db: AsyncSession) -> ApiKey | None:
    result = await db.execute(select(ApiKey).where(ApiKey.revoked_at.is_(None)))
    for row in result.scalars():
        if verify_api_key(token, row.key_hash):
            return row
    return None


async def _write_audit(
    db: AsyncSession,
    request_id: str,
    app_id: str,
    method: str,
    path: str,
    status_code: int,
    latency_ms: int,
) -> None:
    from ulid import ULID

    entry = AuditLog(
        id=str(ULID()),
        request_id=request_id,
        app_id=app_id,
        method=method,
        path=path,
        status_code=status_code,
        latency_ms=latency_ms,
    )
    db.add(entry)
    try:
        await db.commit()
    except Exception:
        await db.rollback()


@router.api_route("/intent", methods=["GET", "POST"])
@router.api_route("/intent/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy_intent(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    http_client: Annotated[httpx.AsyncClient, Depends(get_http_client)],
) -> Response:
    start = time.monotonic()
    request_id = str(uuid.uuid4())

    # 1. Authenticate
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        return JSONResponse(status_code=401, content={"detail": "missing or malformed Authorization header"})

    token = auth.removeprefix("Bearer ").strip()
    api_key = await _lookup_key(token, db)
    if api_key is None:
        return JSONResponse(status_code=401, content={"detail": "invalid or revoked API key"})

    # 2. For requests with a JSON body, validate caller_type claim matches key.
    body_bytes = await request.body()
    if body_bytes and request.headers.get("content-type", "").startswith("application/json"):
        try:
            body_json = json.loads(body_bytes)
            body_caller_type = body_json.get("caller_type")
            if body_caller_type and body_caller_type != api_key.caller_type:
                return JSONResponse(
                    status_code=400,
                    content={
                        "detail": (
                            f"caller_type mismatch: key claim is '{api_key.caller_type}', "
                            f"body contains '{body_caller_type}'"
                        )
                    },
                )
        except json.JSONDecodeError:
            pass

    # 3. Rate limit
    allowed, retry_after = await check_rate_limit(_get_redis(), api_key.app_id, api_key.rate_limit_per_minute)
    if not allowed:
        return JSONResponse(
            status_code=429,
            headers={"Retry-After": str(retry_after)},
            content={"detail": "rate limit exceeded", "retry_after_seconds": retry_after},
        )

    # 4. Sign claims and build forwarding headers
    claims = build_claims_headers(
        caller_type=api_key.caller_type,
        app_id=api_key.app_id,
        capabilities=api_key.capabilities,
        budget_pool=api_key.budget_pool,
    )

    forward_headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in ("authorization", "host", "content-length", "transfer-encoding")
    }
    forward_headers.update(claims)
    forward_headers["X-Request-Id"] = request_id

    # 5. Forward to paperclipai
    path = str(request.url.path)
    query = f"?{request.url.query}" if request.url.query else ""
    target_url = _PAPERCLIPAI_URL.rstrip("/") + path + query

    try:
        upstream = await http_client.request(
            method=request.method,
            url=target_url,
            headers=forward_headers,
            content=body_bytes,
        )
    except httpx.RequestError as exc:
        log.error("upstream_error", error=str(exc), request_id=request_id)
        latency_ms = int((time.monotonic() - start) * 1000)
        await _write_audit(db, request_id, api_key.app_id, request.method, path, 502, latency_ms)
        return JSONResponse(status_code=502, content={"detail": "upstream unreachable"})

    latency_ms = int((time.monotonic() - start) * 1000)
    await _write_audit(db, request_id, api_key.app_id, request.method, path, upstream.status_code, latency_ms)

    excluded = {"transfer-encoding", "connection", "keep-alive", "te", "trailers", "upgrade"}
    response_headers = {k: v for k, v in upstream.headers.items() if k.lower() not in excluded}

    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=response_headers,
        media_type=upstream.headers.get("content-type"),
    )
