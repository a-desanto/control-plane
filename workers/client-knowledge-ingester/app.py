"""
client-knowledge-ingester
Reads from Redis ck:ingest:queue, embeds via Cohere Embed v4 on Bedrock,
writes to client_knowledge pgvector DB. Also exposes /upload REST endpoint.

Auth: AWS Bearer token (same pattern as bedrock-proxy, not SigV4/boto3).
Embed pricing: Cohere Embed v4 on Bedrock — VERIFY_PRICING constant below.
"""
import asyncio
import hashlib
import json
import os
import uuid
from contextlib import asynccontextmanager

import asyncpg
import httpx
import redis.asyncio as aioredis
import structlog
import tiktoken
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# ── Pricing note ──────────────────────────────────────────────────────────────
# UNVERIFIED — update once confirmed via AWS Bedrock pricing page.
# Cohere Embed-English-v3 on Bedrock = $0.10/1M tokens; v4 likely similar.
_EMBED_PRICE_PER_1M_USD = 0.10

# ── Config ────────────────────────────────────────────────────────────────────
CKDB_URL = os.environ["CKDB_URL"]
PAPERCLIP_DB_URL = os.environ["PAPERCLIP_DB_URL"]
AWS_BEARER_TOKEN = os.environ["AWS_BEARER_TOKEN_BEDROCK"]
REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
REDIS_DB = int(os.environ.get("REDIS_DB", "2"))
REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD") or None  # None → no auth
AWS_REGION = os.environ.get("AWS_REGION", "us-east-2")
EMBED_MODEL_ID = os.environ.get("EMBED_MODEL_ID", "cohere.embed-v4:0")
# LANGFUSE_HOST / LANGFUSE_SECRET_KEY / LANGFUSE_PUBLIC_KEY read automatically by get_client()

QUEUE_KEY = "ck:ingest:queue"
DLQ_KEY = "ck:ingest:dlq"
CHUNK_TOKENS = 512
CHUNK_OVERLAP = 64
EMBED_BATCH_SIZE = 96  # Cohere hard limit
EXPECTED_DIMS = 1024

_enc = tiktoken.get_encoding("cl100k_base")
log = structlog.get_logger()

# ── Shared state (populated at startup) ───────────────────────────────────────
_ckdb: asyncpg.Pool | None = None
_ppdb: asyncpg.Pool | None = None
_redis: aioredis.Redis | None = None


# ── Chunking ──────────────────────────────────────────────────────────────────
def chunk_text(text: str) -> list[str]:
    tokens = _enc.encode(text)
    chunks: list[str] = []
    start = 0
    while start < len(tokens):
        end = min(start + CHUNK_TOKENS, len(tokens))
        chunks.append(_enc.decode(tokens[start:end]))
        if end == len(tokens):
            break
        start += CHUNK_TOKENS - CHUNK_OVERLAP
    return chunks


# ── Bedrock Cohere Embed ──────────────────────────────────────────────────────
_BEDROCK_BASE = f"https://bedrock-runtime.{AWS_REGION}.amazonaws.com"


async def embed_texts(texts: list[str], input_type: str = "search_document") -> tuple[list[list[float]], int]:
    """Batch-embed texts via Cohere Embed v4 on Bedrock. Returns (embeddings, total_input_tokens)."""
    all_embeddings: list[list[float]] = []
    total_tokens = 0

    async with httpx.AsyncClient(timeout=120.0) as client:
        for i in range(0, len(texts), EMBED_BATCH_SIZE):
            batch = texts[i : i + EMBED_BATCH_SIZE]
            resp = await client.post(
                f"{_BEDROCK_BASE}/model/{EMBED_MODEL_ID}/invoke",
                headers={
                    "Authorization": f"Bearer {AWS_BEARER_TOKEN}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                json={
                    "texts": batch,
                    "input_type": input_type,
                    "truncate": "END",
                    "embedding_types": ["float"],
                    "output_dimension": 1024,
                },
            )
            if resp.status_code != 200:
                raise RuntimeError(f"Bedrock embed {resp.status_code}: {resp.text[:400]}")
            body = resp.json()
            batch_embeddings = body["embeddings"]["float"]
            all_embeddings.extend(batch_embeddings)
            total_tokens += body.get("input_token_count", 0)

    if all_embeddings and len(all_embeddings[0]) != EXPECTED_DIMS:
        raise RuntimeError(
            f"Unexpected embedding dims: got {len(all_embeddings[0])}, expected {EXPECTED_DIMS}. "
            "Check EMBED_MODEL_ID and schema VECTOR() size."
        )

    return all_embeddings, total_tokens


# ── Cost event ────────────────────────────────────────────────────────────────
async def write_cost_event(company_id: str, agent_id: str, input_tokens: int) -> None:
    cost_cents = round(input_tokens * _EMBED_PRICE_PER_1M_USD / 1_000_000 * 100)
    await _ppdb.execute(
        """
        INSERT INTO cost_events
          (company_id, agent_id, provider, model,
           input_tokens, output_tokens, cost_cents, occurred_at, biller, billing_type)
        VALUES ($1::uuid, $2::uuid, 'bedrock', $3, $4, 0, $5, NOW(), 'system', 'embedding')
        """,
        company_id,
        agent_id,
        EMBED_MODEL_ID,
        input_tokens,
        cost_cents,
    )


# ── Langfuse (v4 get_client singleton, reads LANGFUSE_* env vars automatically) ─
try:
    from langfuse import get_client as _lf_get_client
    _lf = _lf_get_client()
except Exception:
    _lf = None


# ── Core ingest ───────────────────────────────────────────────────────────────
async def ingest(event: dict) -> str | None:
    """
    Process one ingest event. Returns doc_id string, or None on dedup.
    Required keys: companyId, content
    Optional keys: sourceType, sourceUri, title, mimeType, agentIds, agentId
    """
    company_id: str = event["companyId"]
    content: str = event["content"]
    source_type: str = event.get("sourceType", "manual_upload")
    source_uri: str | None = event.get("sourceUri")
    title: str = event.get("title", "Untitled")
    mime_type: str = event.get("mimeType", "text/plain")
    agent_ids: list[str] = event.get("agentIds") or []
    cost_agent_id: str | None = event.get("agentId")

    sha256 = hashlib.sha256(content.encode()).hexdigest()

    existing = await _ckdb.fetchrow(
        "SELECT id FROM client_documents WHERE company_id=$1::uuid AND sha256=$2 AND deleted_at IS NULL",
        company_id,
        sha256,
    )
    if existing:
        log.info("dedup_hit", sha256=sha256[:16], company_id=company_id, title=title)
        return None

    doc_id: uuid.UUID = await _ckdb.fetchval(
        """
        INSERT INTO client_documents
          (company_id, source_type, source_uri, title, mime_type, byte_size, sha256)
        VALUES ($1::uuid, $2, $3, $4, $5, $6, $7)
        RETURNING id
        """,
        company_id,
        source_type,
        source_uri,
        title,
        mime_type,
        len(content.encode()),
        sha256,
    )

    chunks = chunk_text(content)
    if not chunks:
        log.warning("no_chunks", doc_id=str(doc_id), title=title)
        return str(doc_id)

    log.info("chunking", doc_id=str(doc_id), chunk_count=len(chunks), title=title)

    lf_gen = None
    try:
        if _lf:
            lf_gen = _lf.start_observation(
                name="bedrock_embed_cohere",
                as_type="generation",
                model=EMBED_MODEL_ID,
                input={"chunk_count": len(chunks)},
                metadata={"doc_id": str(doc_id), "company_id": company_id},
            )
    except Exception as exc:
        log.warning("langfuse_init_failed", error=str(exc))

    # Count tokens before embedding — tiktoken is deterministic and avoids
    # relying on Bedrock's Cohere response which omits input_token_count.
    chunk_tokens = [len(_enc.encode(c)) for c in chunks]
    total_tokens = sum(chunk_tokens)

    embeddings, _ = await embed_texts(chunks, input_type="search_document")

    if lf_gen:
        try:
            lf_gen.update(usage_details={"input": total_tokens, "output": 0})
            lf_gen.end()
        except Exception as exc:
            log.warning("langfuse_end_failed", error=str(exc))

    log.info("embedding_done", doc_id=str(doc_id), chunks=len(chunks), tokens=total_tokens)

    async with _ckdb.acquire() as conn:
        async with conn.transaction():
            for idx, (chunk, emb, token_count) in enumerate(zip(chunks, embeddings, chunk_tokens)):
                emb_literal = "[" + ",".join(f"{v:.8f}" for v in emb) + "]"
                await conn.execute(
                    """
                    INSERT INTO client_document_chunks
                      (document_id, company_id, chunk_index, content, token_count, embedding)
                    VALUES ($1, $2::uuid, $3, $4, $5, $6::vector)
                    """,
                    doc_id,
                    company_id,
                    idx,
                    chunk,
                    token_count,
                    emb_literal,
                )
            for aid in agent_ids:
                await conn.execute(
                    """
                    INSERT INTO client_document_acls (document_id, agent_id, permission)
                    VALUES ($1, $2::uuid, 'read') ON CONFLICT DO NOTHING
                    """,
                    doc_id,
                    aid,
                )

    billing_agent_id = cost_agent_id or (agent_ids[0] if agent_ids else None)
    if billing_agent_id:
        try:
            await write_cost_event(company_id, billing_agent_id, total_tokens)
            log.info("cost_event_written", tokens=total_tokens, agent_id=billing_agent_id)
        except Exception as e:
            log.warning("cost_event_failed", error=str(e))
    else:
        log.warning("no_agent_id_for_cost_event", doc_id=str(doc_id))

    log.info("ingested", doc_id=str(doc_id), title=title, chunks=len(chunks), tokens=total_tokens)
    return str(doc_id)


# ── Redis worker loop ─────────────────────────────────────────────────────────
async def _worker_loop() -> None:
    log.info("worker_started", queue=QUEUE_KEY)
    while True:
        raw: str | None = None
        try:
            job = await _redis.blpop(QUEUE_KEY, timeout=5)
            if not job:
                continue
            _, raw = job
            event = json.loads(raw)
            doc_id = await ingest(event)
            log.info("worker_done", doc_id=doc_id, dedup=(doc_id is None))
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.error("worker_error", error=str(e))
            if raw:
                try:
                    await _redis.rpush(DLQ_KEY, raw)
                except Exception:
                    pass
            await asyncio.sleep(5)


# ── FastAPI app ───────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _ckdb, _ppdb, _redis

    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(),
        ]
    )

    _ckdb = await asyncpg.create_pool(CKDB_URL, min_size=2, max_size=10)
    _ppdb = await asyncpg.create_pool(PAPERCLIP_DB_URL, min_size=1, max_size=5)
    _redis = aioredis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        db=REDIS_DB,
        password=REDIS_PASSWORD,
        decode_responses=True,
    )

    worker_task = asyncio.create_task(_worker_loop())
    log.info("startup_complete", embed_model=EMBED_MODEL_ID, queue=QUEUE_KEY)

    yield

    worker_task.cancel()
    await asyncio.gather(worker_task, return_exceptions=True)
    await _ckdb.close()
    await _ppdb.close()
    await _redis.aclose()


app = FastAPI(title="client-knowledge-ingester", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "client-knowledge-ingester"}


class UploadRequest(BaseModel):
    companyId: str
    title: str
    content: str
    sourceType: str = "manual_upload"
    sourceUri: str | None = None
    mimeType: str = "text/plain"
    agentIds: list[str] = []
    agentId: str | None = None


@app.post("/upload")
async def upload(req: UploadRequest):
    try:
        doc_id = await ingest(req.model_dump())
        if doc_id is None:
            return {"status": "dedup", "doc_id": None}
        return {"status": "ingested", "doc_id": doc_id}
    except Exception as e:
        log.error("upload_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
