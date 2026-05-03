#!/usr/bin/env python3
"""
bedrock-proxy — Anthropic messages API → AWS Bedrock InvokeModel

Translates Anthropic SDK requests to Bedrock's InvokeModel / InvokeModelWithResponseStream
API, writes cost_events to paperclip's PostgreSQL, and traces via Langfuse.

Routes:
  GET  /health
  GET  /models/{model_id}   — fake stub for Anthropic SDK model lookups
  POST /v1/messages         — unary and streaming
  POST /messages            — alias (OpenCode omits the /v1 prefix)
"""
import asyncio
import base64
import json
import os
import struct
import time
import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator

import asyncpg
import httpx
import structlog
from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from langfuse import get_client

# ── Logging ─────────────────────────────────────────────────────────────────
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer(),
    ]
)
log = structlog.get_logger()

# ── Config ──────────────────────────────────────────────────────────────────
BEDROCK_API_KEY = os.environ["BEDROCK_API_KEY"]
BEDROCK_BASE_URL = os.environ.get(
    "BEDROCK_BASE_URL", "https://bedrock-runtime.us-east-2.amazonaws.com"
)
PAPERCLIP_DB_URL = os.environ.get(
    "PAPERCLIP_DB_URL",
    "postgresql://paperclip:paperclip"
    "@ihe84uqp2yr5bu9wd43w34dq-013746708684:54329/paperclip",
)
LISTEN_PORT = int(os.environ.get("PROXY_PORT", "4002"))

# Max 2 retries (3 total attempts) on 5xx or network error.
_RETRY_DELAYS = [0.5, 1.0]

# ── Model translation ────────────────────────────────────────────────────────
# Model IDs verified against boto3 bedrock.list_foundation_models (us-east-2, 2026-05):
#   anthropic.claude-sonnet-4-6          (ACTIVE, INFERENCE_PROFILE only)
#   anthropic.claude-haiku-4-5-20251001-v1:0  (ACTIVE, INFERENCE_PROFILE only)
#   anthropic.claude-opus-4-7            (ACTIVE, INFERENCE_PROFILE only)
#
# ⚠ INFERENCE_PROFILE REQUIRED: All three models set inferenceTypesSupported=
# ["INFERENCE_PROFILE"] — direct InvokeModel with bare "anthropic.xxx" IDs fails.
# Must use the system-managed cross-region inference profile IDs ("us.anthropic.xxx")
# which route across US-region capacity automatically.
#
# TODO — Opus 4.7 thinking shape: Opus 4.7 only supports thinking.type='adaptive'.
# If a request arrives with thinking={'type':'enabled', 'budget_tokens':N} and the
# resolved model is opus-4-7, the proxy must either rewrite the field to
# {'type':'adaptive'} or return HTTP 400 with a clear error message. Silently
# forwarding 'enabled' to Bedrock will fail with a schema error. This is a
# migration trap from Opus 4.6, which used the older 'enabled' shape.
ANTHROPIC_TO_BEDROCK: dict[str, str] = {
    "claude-sonnet-4-6":          "us.anthropic.claude-sonnet-4-6",
    "claude-sonnet-4-6-20250515": "us.anthropic.claude-sonnet-4-6",
    "claude-haiku-4-5":           "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    "claude-haiku-4-5-20251001":  "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    "claude-opus-4-7":            "us.anthropic.claude-opus-4-7",
    "claude-opus-4-7-20250514":   "us.anthropic.claude-opus-4-7",
    # Phase 5.9 — Nemotron via Bedrock Converse API (not InvokeModel)
    # inferenceTypesSupported=["ON_DEMAND"] — no cross-region inference profile needed
    "nemotron-nano":              "nvidia.nemotron-nano-3-30b",
    "nvidia/nemotron-nano-3-30b": "nvidia.nemotron-nano-3-30b",
}

# Models that use Bedrock Converse API instead of InvokeModel/InvokeModelWithResponseStream.
# Nemotron and other non-Anthropic models do not support the Anthropic-native InvokeModel
# body format; they require the provider-agnostic Converse API.
CONVERSE_MODELS: frozenset[str] = frozenset({
    "nvidia.nemotron-nano-3-30b",
})

# USD / 1M tokens. Claude 4.x is NOT in the AWS Pricing API as of 2026-05.
# Values from runbook — UNVERIFIED until confirmed at https://aws.amazon.com/bedrock/pricing/
# Keys use inference profile IDs to match ANTHROPIC_TO_BEDROCK values above.
BEDROCK_PRICING: dict[str, dict[str, float]] = {
    "us.anthropic.claude-sonnet-4-6":               {"input": 3.00,  "output": 15.00},  # UNVERIFIED
    "us.anthropic.claude-haiku-4-5-20251001-v1:0":  {"input": 0.80,  "output":  4.00},  # UNVERIFIED
    "us.anthropic.claude-opus-4-7":                 {"input": 15.00, "output": 75.00},  # UNVERIFIED
    "nvidia.nemotron-nano-3-30b":                   {"input": 0.20,  "output":  0.20},  # UNVERIFIED
}

# ── Database pool ────────────────────────────────────────────────────────────
_db_pool: asyncpg.Pool | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global _db_pool
    try:
        _db_pool = await asyncpg.create_pool(
            PAPERCLIP_DB_URL, min_size=1, max_size=5, command_timeout=10
        )
        log.info("db_pool_ready")
    except Exception as exc:
        log.warning("db_pool_unavailable", error=str(exc))
    yield
    if _db_pool:
        await _db_pool.close()


app = FastAPI(lifespan=lifespan)
_lf = get_client()


# ── Helpers ──────────────────────────────────────────────────────────────────

def _bedrock_model(anthropic_model: str) -> str:
    bid = ANTHROPIC_TO_BEDROCK.get(anthropic_model)
    if not bid:
        raise HTTPException(
            422,
            detail=(
                f"Unsupported model: {anthropic_model!r}. "
                f"Known: {sorted(ANTHROPIC_TO_BEDROCK)}"
            ),
        )
    return bid


def _cost_cents(bedrock_model: str, inp: int, out: int) -> int:
    p = BEDROCK_PRICING.get(bedrock_model, {"input": 3.00, "output": 15.00})
    usd = (inp * p["input"] + out * p["output"]) / 1_000_000
    return max(1, int(usd * 100))


async def _write_cost_event(
    company_id: str,
    agent_id: str,
    bedrock_model: str,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int,
) -> None:
    if not _db_pool:
        return
    cost = _cost_cents(bedrock_model, input_tokens, output_tokens)
    try:
        await _db_pool.execute(
            """
            INSERT INTO cost_events
              (company_id, agent_id, provider, model,
               input_tokens, output_tokens, cached_input_tokens,
               cost_cents, occurred_at, biller, billing_type)
            VALUES ($1,$2,'bedrock',$3,$4,$5,$6,$7,NOW(),'bedrock','metered_api')
            """,
            uuid.UUID(company_id),
            uuid.UUID(agent_id),
            bedrock_model,
            input_tokens,
            output_tokens,
            cached_tokens,
            cost,
        )
        log.info(
            "cost_event_written",
            company_id=company_id, agent_id=agent_id,
            model=bedrock_model, input_tokens=input_tokens,
            output_tokens=output_tokens, cost_cents=cost,
        )
    except Exception as exc:
        log.error("cost_event_failed", error=str(exc))


def _bedrock_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {BEDROCK_API_KEY}",
        "Content-Type": "application/json",
    }


def _prepare_body(raw: dict) -> bytes:
    """Strip 'model' and 'stream' (Bedrock uses URL for model); inject anthropic_version."""
    body = {k: v for k, v in raw.items() if k not in ("model", "stream")}
    body.setdefault("anthropic_version", "bedrock-2023-05-31")
    return json.dumps(body).encode()


def _prepare_converse_body(raw: dict) -> bytes:
    """Translate Anthropic Messages API body → Bedrock Converse API body.

    Converse uses a provider-agnostic format:
      messages: [{role, content: [{text: "..."}]}]
      system:   [{text: "..."}]
      inferenceConfig: {maxTokens, temperature, topP, stopSequences}
    """
    def _to_converse_content(content) -> list[dict]:
        if isinstance(content, str):
            return [{"text": content}]
        if isinstance(content, list):
            out = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    out.append({"text": block.get("text", "")})
            return out or [{"text": ""}]
        return [{"text": str(content)}]

    messages = []
    for msg in raw.get("messages", []):
        messages.append({
            "role": msg["role"],
            "content": _to_converse_content(msg.get("content", "")),
        })

    body: dict = {"messages": messages}

    system_raw = raw.get("system")
    if system_raw:
        if isinstance(system_raw, str):
            body["system"] = [{"text": system_raw}]
        elif isinstance(system_raw, list):
            body["system"] = [{"text": b.get("text", "")} for b in system_raw if isinstance(b, dict)]

    inf: dict = {}
    if "max_tokens" in raw:
        inf["maxTokens"] = raw["max_tokens"]
    if "temperature" in raw:
        inf["temperature"] = raw["temperature"]
    if "top_p" in raw:
        inf["topP"] = raw["top_p"]
    if "stop_sequences" in raw:
        inf["stopSequences"] = raw["stop_sequences"]
    if inf:
        body["inferenceConfig"] = inf

    return json.dumps(body).encode()


def _parse_converse_response(resp_json: dict, bedrock_model: str, original_model: str) -> dict:
    """Translate Bedrock Converse response → Anthropic Messages response shape."""
    out_msg = resp_json.get("output", {}).get("message", {})
    content_blocks = out_msg.get("content", [])
    text = " ".join(b.get("text", "") for b in content_blocks if "text" in b)
    usage = resp_json.get("usage", {})
    stop_reason_map = {"end_turn": "end_turn", "stop_sequence": "stop_sequence", "max_tokens": "max_tokens"}
    stop = stop_reason_map.get(resp_json.get("stopReason", "end_turn"), "end_turn")
    return {
        "id": f"msg_{uuid.uuid4().hex}",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": text}],
        "model": bedrock_model,
        "stop_reason": stop,
        "stop_sequence": None,
        "usage": {
            "input_tokens": usage.get("inputTokens", 0),
            "output_tokens": usage.get("outputTokens", 0),
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        },
    }


async def _post_with_retry(
    client: httpx.AsyncClient, url: str, content: bytes
) -> httpx.Response:
    last_exc: BaseException | None = None
    for attempt in range(len(_RETRY_DELAYS) + 1):
        try:
            resp = await client.post(url, content=content, headers=_bedrock_headers())
            if resp.status_code < 500 or attempt >= len(_RETRY_DELAYS):
                return resp
            log.warning(
                "bedrock_5xx_retry",
                status=resp.status_code,
                attempt=attempt + 1,
                delay=_RETRY_DELAYS[attempt],
            )
            await asyncio.sleep(_RETRY_DELAYS[attempt])
        except (httpx.ConnectError, httpx.ReadTimeout) as exc:
            last_exc = exc
            if attempt >= len(_RETRY_DELAYS):
                break
            log.warning(
                "bedrock_network_retry", error=str(exc), attempt=attempt + 1
            )
            await asyncio.sleep(_RETRY_DELAYS[attempt])
    raise HTTPException(502, detail=f"Bedrock unreachable: {last_exc}")


def _decode_eventstream(buf: bytes) -> tuple[list[bytes], bytes]:
    """
    Parse zero or more complete AWS EventStream frames from buf.

    Bedrock invoke-with-response-stream uses a binary framing protocol:
      [4B total-len][4B header-len][4B prelude-CRC32][headers][body][4B msg-CRC32]

    Each chunk frame body is JSON: {"bytes": "<base64-Anthropic-SSE-event>", "p": "..."}
    We decode the base64 and re-emit as SSE data lines so any Anthropic SDK
    client (OpenCode, claude CLI, etc.) can parse it without modification.

    Returns (list_of_sse_lines, unconsumed_remainder).
    """
    sse_lines: list[bytes] = []
    while len(buf) >= 12:
        total_len = struct.unpack(">I", buf[:4])[0]
        if len(buf) < total_len or total_len < 16:
            break
        frame = buf[:total_len]
        buf = buf[total_len:]
        headers_len = struct.unpack(">I", frame[4:8])[0]
        body_start = 12 + headers_len
        body_end = total_len - 4
        if body_start >= body_end:
            continue
        try:
            frame_json = json.loads(frame[body_start:body_end])
            event_b64 = frame_json.get("bytes", "")
            if event_b64:
                event_data = base64.b64decode(event_b64)
                sse_lines.append(b"data: " + event_data + b"\n\n")
        except Exception:
            pass
    return sse_lines, buf


def _extract_sse_usage(chunk: bytes) -> tuple[int, int, int]:
    """Parse SSE chunk; return (input_tokens, output_tokens, cached_tokens)."""
    inp = out = cached = 0
    try:
        for line in chunk.decode("utf-8", errors="ignore").splitlines():
            if not line.startswith("data:"):
                continue
            ev = json.loads(line[5:].strip())
            t = ev.get("type")
            if t == "message_start":
                u = ev.get("message", {}).get("usage", {})
                inp    = u.get("input_tokens", 0)
                cached = u.get("cache_read_input_tokens", 0)
            elif t == "message_delta":
                out = ev.get("usage", {}).get("output_tokens", 0)
    except Exception:
        pass
    return inp, out, cached


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "db_pool": _db_pool is not None}


@app.get("/models/{model_id:path}")
@app.get("/v1/models/{model_id:path}")
async def get_model(model_id: str) -> dict:
    return {
        "id": model_id, "type": "model",
        "display_name": model_id, "created_at": "2025-01-01T00:00:00Z",
    }


def _extract_pca_attribution(auth_header: str | None) -> tuple[str | None, str | None]:
    """
    Extract (agent_id, company_id) from a synthetic ANTHROPIC_API_KEY value.

    OpenCode adapters that route through bedrock-proxy set:
      ANTHROPIC_API_KEY=pca:agent_id=<uuid>,company_id=<uuid>

    The proxy replaces the client's Authorization header with the Bedrock key, so
    any value works for auth; we borrow the field to carry attribution metadata.
    """
    if not auth_header:
        return None, None
    # Strip "Bearer " prefix if present
    token = auth_header.removeprefix("Bearer ").strip()
    if not token.startswith("pca:"):
        return None, None
    parts = dict(
        p.split("=", 1) for p in token[4:].split(",") if "=" in p
    )
    return parts.get("agent_id"), parts.get("company_id")


@app.post("/v1/messages")
@app.post("/messages")
async def post_messages(
    request: Request,
    x_paperclip_agent_id: str | None = Header(default=None),
    x_paperclip_company_id: str | None = Header(default=None),
) -> Response:
    # Fall back to attribution encoded in Authorization header (OpenCode adapters
    # set ANTHROPIC_API_KEY=pca:agent_id=...,company_id=... for cost tracking).
    if not x_paperclip_agent_id or not x_paperclip_company_id:
        # Anthropic SDK sends API key as x-api-key (not Authorization: Bearer)
        auth = (request.headers.get("x-api-key")
                or request.headers.get("authorization")
                or request.headers.get("Authorization"))
        pca_agent, pca_company = _extract_pca_attribution(auth)
        x_paperclip_agent_id = x_paperclip_agent_id or pca_agent
        x_paperclip_company_id = x_paperclip_company_id or pca_company

    raw: dict = await request.json()
    anthropic_model: str = raw.get("model", "claude-sonnet-4-6")
    bmodel = _bedrock_model(anthropic_model)
    is_stream = bool(raw.get("stream"))

    log.info(
        "request_in",
        model=anthropic_model, bedrock_model=bmodel, stream=is_stream,
        agent_id=x_paperclip_agent_id, company_id=x_paperclip_company_id,
    )

    if bmodel in CONVERSE_MODELS:
        # Non-Anthropic models (e.g. Nemotron) require Bedrock Converse API format.
        # Streaming is not yet implemented for Converse — shim sends stream=false.
        converse_body = _prepare_converse_body(raw)
        url = f"{BEDROCK_BASE_URL}/model/{bmodel}/converse"
        return await _unary_converse(
            converse_body, url, bmodel, anthropic_model, raw,
            x_paperclip_agent_id, x_paperclip_company_id,
        )

    body = _prepare_body(raw)
    if is_stream:
        url = f"{BEDROCK_BASE_URL}/model/{bmodel}/invoke-with-response-stream"
        return StreamingResponse(
            _stream_generate(
                body, url, bmodel, raw,
                x_paperclip_agent_id, x_paperclip_company_id,
            ),
            media_type="text/event-stream",
        )

    url = f"{BEDROCK_BASE_URL}/model/{bmodel}/invoke"
    return await _unary(body, url, bmodel, raw, x_paperclip_agent_id, x_paperclip_company_id)


# ── Unary handler ─────────────────────────────────────────────────────────────

async def _unary(
    body: bytes,
    url: str,
    bmodel: str,
    raw: dict,
    agent_id: str | None,
    company_id: str | None,
) -> Response:
    messages_val = raw.get("messages") or raw.get("prompt")
    meta = {k: raw[k] for k in ("max_tokens", "system") if k in raw}

    with _lf.start_as_current_observation(
        name="messages", as_type="generation",
        model=bmodel, input=messages_val, metadata=meta or None,
    ) as gen:
        t0 = time.monotonic()
        async with httpx.AsyncClient(timeout=300) as client:
            resp = await _post_with_retry(client, url, body)
        latency_ms = int((time.monotonic() - t0) * 1000)

        if resp.status_code >= 400:
            gen.update(
                level="ERROR",
                status_message=f"HTTP {resp.status_code}",
                metadata={"latency_ms": latency_ms},
            )
            log.error("bedrock_error", status=resp.status_code, body=resp.text[:500])
            return Response(
                content=resp.content,
                status_code=resp.status_code,
                media_type="application/json",
            )

        rj = resp.json()
        usage  = rj.get("usage", {})
        inp    = usage.get("input_tokens", 0)
        out    = usage.get("output_tokens", 0)
        cached = usage.get("cache_read_input_tokens", 0)

        gen.update(
            output=rj.get("content"),
            usage_details={"input": inp, "output": out},
            metadata={"latency_ms": latency_ms},
        )
        log.info(
            "response_ok",
            latency_ms=latency_ms, input_tokens=inp, output_tokens=out,
        )

        if agent_id and company_id:
            asyncio.create_task(
                _write_cost_event(company_id, agent_id, bmodel, inp, out, cached)
            )

        return Response(
            content=resp.content,
            status_code=resp.status_code,
            media_type="application/json",
        )


# ── Converse (non-Anthropic) unary handler ────────────────────────────────────

async def _unary_converse(
    body: bytes,
    url: str,
    bmodel: str,
    original_model: str,
    raw: dict,
    agent_id: str | None,
    company_id: str | None,
) -> Response:
    messages_val = raw.get("messages")
    meta = {k: raw[k] for k in ("max_tokens", "system") if k in raw}

    with _lf.start_as_current_observation(
        name="messages", as_type="generation",
        model=bmodel, input=messages_val, metadata=meta or None,
    ) as gen:
        t0 = time.monotonic()
        async with httpx.AsyncClient(timeout=300) as client:
            resp = await _post_with_retry(client, url, body)
        latency_ms = int((time.monotonic() - t0) * 1000)

        if resp.status_code >= 400:
            gen.update(
                level="ERROR",
                status_message=f"HTTP {resp.status_code}",
                metadata={"latency_ms": latency_ms},
            )
            log.error("bedrock_converse_error", status=resp.status_code, body=resp.text[:500])
            return Response(
                content=resp.content,
                status_code=resp.status_code,
                media_type="application/json",
            )

        rj = resp.json()
        usage = rj.get("usage", {})
        inp    = usage.get("inputTokens", 0)
        out    = usage.get("outputTokens", 0)
        cached = 0

        translated = _parse_converse_response(rj, bmodel, original_model)

        gen.update(
            output=translated.get("content"),
            usage_details={"input": inp, "output": out},
            metadata={"latency_ms": latency_ms},
        )
        log.info(
            "converse_response_ok",
            latency_ms=latency_ms, input_tokens=inp, output_tokens=out,
        )

        if agent_id and company_id:
            asyncio.create_task(
                _write_cost_event(company_id, agent_id, bmodel, inp, out, cached)
            )

        return Response(
            content=json.dumps(translated).encode(),
            status_code=200,
            media_type="application/json",
        )


# ── Streaming handler ─────────────────────────────────────────────────────────

async def _stream_generate(
    body: bytes,
    url: str,
    bmodel: str,
    raw: dict,
    agent_id: str | None,
    company_id: str | None,
) -> AsyncIterator[bytes]:
    messages_val = raw.get("messages") or raw.get("prompt")
    meta = {k: raw[k] for k in ("max_tokens", "system") if k in raw}

    # Langfuse: use start_observation (stateful, no context manager) so tracing
    # spans cleanly across async generator yields. trace() was removed in v3+.
    lf_gen = None
    try:
        lf_gen = _lf.start_observation(
            name="messages", as_type="generation",
            model=bmodel, input=messages_val, metadata=meta or None,
        )
    except Exception as exc:
        log.warning("langfuse_init_failed", error=str(exc))

    inp = out = cached = 0
    t0 = time.monotonic()

    try:
        async with httpx.AsyncClient(timeout=300) as client:
            async with client.stream(
                "POST", url, content=body, headers=_bedrock_headers()
            ) as resp:
                if resp.status_code >= 400:
                    err = await resp.aread()
                    log.error("bedrock_stream_error", status=resp.status_code)
                    if lf_gen:
                        try:
                            lf_gen.end(level="ERROR", status_message=f"HTTP {resp.status_code}")
                        except Exception:
                            pass
                    yield err
                    return

                # Bedrock streams binary AWS EventStream frames; decode to SSE.
                stream_buf = b""
                async for raw_chunk in resp.aiter_bytes():
                    stream_buf += raw_chunk
                    sse_lines, stream_buf = _decode_eventstream(stream_buf)
                    for sse_line in sse_lines:
                        c_inp, c_out, c_cached = _extract_sse_usage(sse_line)
                        if c_inp:
                            inp    = c_inp
                            cached = c_cached
                        if c_out:
                            out = c_out
                        yield sse_line

    finally:
        latency_ms = int((time.monotonic() - t0) * 1000)
        log.info(
            "stream_complete",
            latency_ms=latency_ms, input_tokens=inp, output_tokens=out,
        )
        if lf_gen:
            try:
                lf_gen.update(
                    usage_details={"input": inp, "output": out},
                    metadata={"latency_ms": latency_ms},
                )
                lf_gen.end()
            except Exception as exc:
                log.warning("langfuse_end_failed", error=str(exc))
        if agent_id and company_id and (inp or out):
            asyncio.create_task(
                _write_cost_event(company_id, agent_id, bmodel, inp, out, cached)
            )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=LISTEN_PORT)
