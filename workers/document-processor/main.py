"""
document-processor — Phase 12 Stage 2 OCR + extraction worker.

Polls document_intake for 'received' rows, runs OCR (PaddleOCR primary /
Textract fallback), classifies doc type, and populates invoices /
contracts / intake_forms.

OCR routing logic:
  standard tier:         PaddleOCR → Textract fallback if mean_confidence < 0.80
  compliance-hipaa tier: intake_form → always Textract (PHI sensitivity)
                         other types → Textract fallback if mean_confidence < 0.85

Status progression per row:
  received → ocr_pending → ocr_done → classified → done | failed
"""
import asyncio
import json
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from typing import Any

import asyncpg
import boto3
import httpx
import structlog

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer(),
    ]
)
log = structlog.get_logger()

# ── Config ────────────────────────────────────────────────────────────────────

CKDB_URL         = os.environ["CKDB_URL"]
PAPERCLIP_DB_URL = os.environ["PAPERCLIP_DB_URL"]
PADDLEOCR_URL    = os.environ.get("PADDLEOCR_URL", "http://paddleocr-service:4006")
BEDROCK_API_URL  = os.environ.get("BEDROCK_API_URL", "http://bedrock-proxy:4002")
BEDROCK_API_KEY  = os.environ["BEDROCK_API_KEY"]
BEDROCK_AGENT_ID = os.environ.get("BEDROCK_AGENT_ID", "")   # for cost tracking
COMPANY_ID       = os.environ.get("COMPANY_ID", "")          # for cost tracking
AWS_REGION       = os.environ.get("AWS_REGION", "us-east-2")
AWS_KEY          = os.environ["AWS_ACCESS_KEY_ID"]
AWS_SECRET       = os.environ["AWS_SECRET_ACCESS_KEY"]
POLL_INTERVAL    = int(os.environ.get("POLL_INTERVAL_SECONDS", "15"))
CONF_STANDARD    = float(os.environ.get("OCR_CONFIDENCE_STANDARD", "0.80"))
CONF_HIPAA       = float(os.environ.get("OCR_CONFIDENCE_HIPAA", "0.85"))

# ── Helpers ───────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def pre_classify(source_uri: str, notes) -> str | None:
    """Best-effort doc type from filename and email subject. Returns None if unclear."""
    invoice_kw  = ("invoice", "billing", "receipt", "inv_", "_inv")
    contract_kw = ("contract", "agreement", "nda", "lease", "mou")
    form_kw     = ("intake", "patient", "form", "hipaa", "enrollment")

    def _check(text: str) -> str | None:
        t = text.lower()
        if any(k in t for k in invoice_kw):
            return "invoice"
        if any(k in t for k in contract_kw):
            return "contract"
        if any(k in t for k in form_kw):
            return "intake_form"
        return None

    if notes:
        # notes may arrive as a dict (asyncpg JSONB) or as a JSON string
        if isinstance(notes, str):
            try:
                notes = json.loads(notes)
            except Exception:
                notes = {}
        if isinstance(notes, dict):
            if hit := _check(notes.get("subject", "") or ""):
                return hit

    return _check(source_uri)


def needs_textract(tier: str, pre_type: str | None, confidence: float) -> bool:
    """Return True when we should use (or fall back to) Textract."""
    if tier == "compliance-hipaa" and pre_type == "intake_form":
        return True
    threshold = CONF_HIPAA if tier == "compliance-hipaa" else CONF_STANDARD
    return confidence < threshold


# ── AWS clients (thread-bound, created lazily) ────────────────────────────────

def _s3_client():
    return boto3.client(
        "s3", region_name=AWS_REGION,
        aws_access_key_id=AWS_KEY, aws_secret_access_key=AWS_SECRET,
    )


def _textract_client():
    return boto3.client(
        "textract", region_name=AWS_REGION,
        aws_access_key_id=AWS_KEY, aws_secret_access_key=AWS_SECRET,
    )


# ── S3 fetch ──────────────────────────────────────────────────────────────────

async def fetch_s3_bytes(bucket: str, key: str) -> bytes:
    def _get():
        s3 = _s3_client()
        resp = s3.get_object(Bucket=bucket, Key=key)
        return resp["Body"].read()
    return await asyncio.to_thread(_get)


def _bucket_from_uri(source_uri: str) -> str:
    """Extract bucket name from s3://bucket/key or email-attachments/… key."""
    if source_uri.startswith("s3://"):
        return source_uri[5:].split("/")[0]
    # email_forwarded rows store the S3 key; bucket is the CFPA intake bucket
    return os.environ.get("S3_INTAKE_BUCKET", "cfpa-doc-intake-bd80728d")


# ── PaddleOCR call ────────────────────────────────────────────────────────────

async def run_paddleocr(pdf_bytes: bytes, filename: str, client: httpx.AsyncClient) -> dict:
    files = {"file": (filename, pdf_bytes, "application/pdf")}
    resp = await client.post(f"{PADDLEOCR_URL}/ocr", files=files, timeout=120)
    resp.raise_for_status()
    return resp.json()


# ── Textract fallback ─────────────────────────────────────────────────────────

async def run_textract(bucket: str, key: str) -> str:
    """Start async Textract job on an S3 PDF; return joined line text."""
    def _start():
        tc = _textract_client()
        return tc.start_document_text_detection(
            DocumentLocation={"S3Object": {"Bucket": bucket, "Name": key}}
        )

    resp = await asyncio.to_thread(_start)
    job_id = resp["JobId"]
    log.info("textract.job.started", job_id=job_id, bucket=bucket, key=key)

    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        def _check(jid=job_id):
            tc = _textract_client()
            return tc.get_document_text_detection(JobId=jid)

        result = await asyncio.to_thread(_check)
        status = result["JobStatus"]
        if status == "SUCCEEDED":
            break
        if status == "FAILED":
            raise RuntimeError(f"Textract {job_id} failed: {result.get('StatusMessage', '')}")
        await asyncio.sleep(3)
    else:
        raise TimeoutError(f"Textract job {job_id} timed out after 180s")

    blocks: list[dict] = list(result["Blocks"])
    while "NextToken" in result:
        token = result["NextToken"]
        def _page(jid=job_id, t=token):
            tc = _textract_client()
            return tc.get_document_text_detection(JobId=jid, NextToken=t)
        result = await asyncio.to_thread(_page)
        blocks.extend(result["Blocks"])

    lines = [b["Text"] for b in blocks if b.get("BlockType") == "LINE"]
    log.info("textract.job.done", job_id=job_id, lines=len(lines))
    return "\n".join(lines)


# ── LLM calls via bedrock-proxy ───────────────────────────────────────────────

def _llm_headers() -> dict:
    h = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {BEDROCK_API_KEY}",
    }
    if BEDROCK_AGENT_ID:
        h["X-Paperclip-Agent-Id"] = BEDROCK_AGENT_ID
    if COMPANY_ID:
        h["X-Paperclip-Company-Id"] = COMPANY_ID
    return h


async def llm_message(
    prompt: str,
    model: str = "claude-haiku-4-5",
    max_tokens: int = 512,
    client: httpx.AsyncClient = None,
) -> str:
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    resp = await client.post(
        f"{BEDROCK_API_URL}/v1/messages",
        json=payload,
        headers=_llm_headers(),
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["content"][0]["text"].strip()


async def classify_doc_type(text: str, source_uri: str, client: httpx.AsyncClient) -> str:
    filename = source_uri.split("/")[-1] if "/" in source_uri else source_uri
    prompt = (
        f"Classify this document into exactly one of: invoice, contract, intake_form, unknown.\n"
        f"Filename: {filename}\n"
        f"Text (first 600 chars):\n{text[:600]}\n\n"
        "Reply with only the single classification word."
    )
    result = await llm_message(prompt, max_tokens=10, client=client)
    clean = result.lower().split()[0] if result.split() else "unknown"
    if clean in ("invoice", "contract", "intake_form", "unknown"):
        return clean
    return "unknown"


async def extract_invoice_data(text: str, client: httpx.AsyncClient) -> dict:
    prompt = (
        "Extract invoice fields from this text. Respond with valid JSON only.\n"
        "Schema: {vendor_name, invoice_number, invoice_date (YYYY-MM-DD or null), "
        "due_date (YYYY-MM-DD or null), total_amount (number or null), "
        "currency (3-letter or 'USD'), "
        "line_items: [{description, quantity, unit_price, total}]}\n\n"
        f"Text:\n{text[:3000]}"
    )
    raw = await llm_message(prompt, max_tokens=800, client=client)
    try:
        start = raw.index("{")
        end   = raw.rindex("}") + 1
        return json.loads(raw[start:end])
    except (ValueError, json.JSONDecodeError):
        return {}


async def extract_contract_data(text: str, client: httpx.AsyncClient) -> dict:
    prompt = (
        "Extract contract fields from this text. Respond with valid JSON only.\n"
        "Schema: {contract_type (service_agreement|nda|lease|other), "
        "parties: [{name, role}], "
        "effective_date (YYYY-MM-DD or null), "
        "expiry_date (YYYY-MM-DD or null), "
        "value_amount (number or null), "
        "currency (3-letter or 'USD'), "
        "key_clauses: [string]}\n\n"
        f"Text:\n{text[:3000]}"
    )
    raw = await llm_message(prompt, max_tokens=800, client=client)
    try:
        start = raw.index("{")
        end   = raw.rindex("}") + 1
        return json.loads(raw[start:end])
    except (ValueError, json.JSONDecodeError):
        return {}


async def extract_intake_form_data(text: str, client: httpx.AsyncClient) -> dict:
    prompt = (
        "Extract patient intake form fields from this text. Respond with valid JSON only.\n"
        "Schema: {form_type (new_patient|insurance|hipaa|other), "
        "patient_name (or null), "
        "date_of_service (YYYY-MM-DD or null), "
        "fields: {field_name: extracted_value}}\n\n"
        f"Text:\n{text[:3000]}"
    )
    raw = await llm_message(prompt, max_tokens=800, client=client)
    try:
        start = raw.index("{")
        end   = raw.rindex("}") + 1
        return json.loads(raw[start:end])
    except (ValueError, json.JSONDecodeError):
        return {}


# ── DB helpers ────────────────────────────────────────────────────────────────

async def claim_next_row(ck: asyncpg.Connection) -> dict | None:
    """SELECT FOR UPDATE SKIP LOCKED on the oldest received row; bump to ocr_pending."""
    async with ck.transaction():
        row = await ck.fetchrow("""
            SELECT id, company_id, source_type, source_uri, raw_pdf_s3_key, notes
            FROM document_intake
            WHERE status = 'received'
            ORDER BY created_at ASC
            LIMIT 1
            FOR UPDATE SKIP LOCKED
        """)
        if row is None:
            return None
        await ck.execute("""
            UPDATE document_intake
            SET status = 'ocr_pending', updated_at = NOW()
            WHERE id = $1
        """, row["id"])
    return dict(row)


async def get_company_tier(pp: asyncpg.Connection, company_id: str) -> str:
    row = await pp.fetchrow(
        "SELECT tier FROM client_configs WHERE company_id = $1::uuid", company_id
    )
    return row["tier"] if row else "standard"


async def set_status(ck: asyncpg.Connection, row_id, status: str, extra: dict | None = None):
    if extra:
        await ck.execute("""
            UPDATE document_intake
            SET status = $2, metadata = COALESCE(metadata, '{}'::jsonb) || $3::jsonb,
                updated_at = NOW()
            WHERE id = $1
        """, row_id, status, json.dumps(extra))
    else:
        await ck.execute("""
            UPDATE document_intake SET status = $2, updated_at = NOW() WHERE id = $1
        """, row_id, status)


async def set_doc_type(ck: asyncpg.Connection, row_id, doc_type: str):
    await ck.execute("""
        UPDATE document_intake SET doc_type = $2, updated_at = NOW() WHERE id = $1
    """, row_id, doc_type)


async def insert_invoice(ck: asyncpg.Connection, intake_id, company_id: str, data: dict, raw: dict):
    def _d(v): return v if v else None
    await ck.execute("""
        INSERT INTO invoices
          (document_intake_id, company_id, vendor_name, invoice_number,
           invoice_date, due_date, total_amount, currency, line_items, raw_extracted)
        VALUES ($1,$2,$3,$4,$5::date,$6::date,$7,$8,$9::jsonb,$10::jsonb)
    """,
        intake_id, company_id,
        data.get("vendor_name"), data.get("invoice_number"),
        _d(data.get("invoice_date")), _d(data.get("due_date")),
        data.get("total_amount"), data.get("currency", "USD"),
        json.dumps(data.get("line_items", [])),
        json.dumps(raw),
    )


async def insert_contract(ck: asyncpg.Connection, intake_id, company_id: str, data: dict, raw: dict):
    await ck.execute("""
        INSERT INTO contracts
          (document_intake_id, company_id, contract_type, parties,
           effective_date, expiry_date, value_amount, currency, key_clauses, raw_extracted)
        VALUES ($1,$2,$3,$4::jsonb,$5::date,$6::date,$7,$8,$9::jsonb,$10::jsonb)
    """,
        intake_id, company_id,
        data.get("contract_type"), json.dumps(data.get("parties", [])),
        data.get("effective_date"), data.get("expiry_date"),
        data.get("value_amount"), data.get("currency", "USD"),
        json.dumps(data.get("key_clauses", [])),
        json.dumps(raw),
    )


async def insert_intake_form(ck: asyncpg.Connection, intake_id, company_id: str, data: dict, raw: dict):
    await ck.execute("""
        INSERT INTO intake_forms
          (document_intake_id, company_id, form_type, patient_name,
           date_of_service, fields, raw_extracted)
        VALUES ($1,$2,$3,$4,$5::date,$6::jsonb,$7::jsonb)
    """,
        intake_id, company_id,
        data.get("form_type"), data.get("patient_name"),
        data.get("date_of_service"),
        json.dumps(data.get("fields", {})),
        json.dumps(raw),
    )


# ── Core processing ───────────────────────────────────────────────────────────

async def process_row(row: dict, ck: asyncpg.Connection, pp: asyncpg.Connection,
                      http: httpx.AsyncClient) -> None:
    row_id     = row["id"]
    company_id = str(row["company_id"])
    source_uri = row["source_uri"]
    s3_key     = row["raw_pdf_s3_key"]
    notes      = row["notes"]  # may be None or dict

    log.info("doc.start", id=str(row_id), source=source_uri)

    try:
        tier = await get_company_tier(pp, company_id)

        # ── Pre-classify from filename / email subject ──────────────────────
        pre_type = pre_classify(source_uri, notes)
        bucket   = _bucket_from_uri(source_uri)
        filename = (s3_key or source_uri).split("/")[-1] or "document.pdf"

        # ── PaddleOCR (primary) ────────────────────────────────────────────
        ocr_text   = ""
        ocr_source = "paddleocr"
        ocr_meta   = {}

        try:
            pdf_bytes = await fetch_s3_bytes(bucket, s3_key or filename)
        except Exception as e:
            raise RuntimeError(f"S3 fetch failed: {e}") from e

        # Force Textract for HIPAA intake forms before even calling PaddleOCR
        force_textract = (tier == "compliance-hipaa" and pre_type == "intake_form")

        if not force_textract:
            try:
                paddle_result = await run_paddleocr(pdf_bytes, filename, http)
                confidence    = paddle_result.get("mean_confidence", 0.0)
                ocr_meta      = {"confidence": confidence, "pages": paddle_result.get("page_count", 1)}

                if needs_textract(tier, pre_type, confidence):
                    log.info("doc.textract_fallback", id=str(row_id), confidence=confidence, tier=tier)
                    ocr_text   = await run_textract(bucket, s3_key or filename)
                    ocr_source = "textract"
                else:
                    ocr_text   = paddle_result.get("text", "")
                    ocr_meta["layout"]  = paddle_result.get("layout", [])
                    ocr_meta["tables"]  = paddle_result.get("tables", [])
            except Exception as e:
                log.warning("doc.paddleocr_error", id=str(row_id), error=str(e))
                log.info("doc.textract_fallback_after_error", id=str(row_id))
                ocr_text   = await run_textract(bucket, s3_key or filename)
                ocr_source = "textract"
        else:
            log.info("doc.textract_hipaa_required", id=str(row_id))
            ocr_text   = await run_textract(bucket, s3_key or filename)
            ocr_source = "textract"

        await set_status(ck, row_id, "ocr_done", {
            "ocr_source": ocr_source,
            "ocr_chars": len(ocr_text),
            **ocr_meta,
        })
        log.info("doc.ocr_done", id=str(row_id), source=ocr_source, chars=len(ocr_text))

        # ── Classify doc type ──────────────────────────────────────────────
        if pre_type:
            doc_type = pre_type
            log.info("doc.classify_pre", id=str(row_id), doc_type=doc_type)
        else:
            doc_type = await classify_doc_type(ocr_text, source_uri, http)
            log.info("doc.classify_llm", id=str(row_id), doc_type=doc_type)

        await set_doc_type(ck, row_id, doc_type)
        await set_status(ck, row_id, "classified")

        # ── Extract structured data ────────────────────────────────────────
        if doc_type == "invoice":
            data = await extract_invoice_data(ocr_text, http)
            await insert_invoice(ck, row_id, company_id, data, {"text": ocr_text[:2000], "source": ocr_source})
        elif doc_type == "contract":
            data = await extract_contract_data(ocr_text, http)
            await insert_contract(ck, row_id, company_id, data, {"text": ocr_text[:2000], "source": ocr_source})
        elif doc_type == "intake_form":
            data = await extract_intake_form_data(ocr_text, http)
            await insert_intake_form(ck, row_id, company_id, data, {"text": ocr_text[:2000], "source": ocr_source})
        else:
            data = {}

        await set_status(ck, row_id, "done")
        log.info("doc.done", id=str(row_id), doc_type=doc_type)

    except Exception as exc:
        log.exception("doc.failed", id=str(row_id), error=str(exc))
        try:
            await set_status(ck, row_id, "failed", {"error": str(exc)})
        except Exception:
            pass


# ── Main loop ─────────────────────────────────────────────────────────────────

async def main() -> None:
    shutdown = asyncio.Event()

    def _on_signal():
        log.info("shutdown.signal")
        shutdown.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _on_signal)

    ck = await asyncpg.connect(CKDB_URL)
    pp = await asyncpg.connect(PAPERCLIP_DB_URL)
    # asyncpg doesn't decode JSONB automatically — register codecs on both connections
    for conn in (ck, pp):
        await conn.set_type_codec("jsonb", schema="pg_catalog",
                                  encoder=json.dumps, decoder=json.loads)
        await conn.set_type_codec("json", schema="pg_catalog",
                                  encoder=json.dumps, decoder=json.loads)
    log.info("db.connected")

    async with httpx.AsyncClient(timeout=130) as http:
        # Quick self-check: make sure paddleocr-service is healthy
        try:
            r = await http.get(f"{PADDLEOCR_URL}/health", timeout=5)
            ready = r.json().get("engines_ready", False)
            log.info("paddleocr.health", ready=ready)
        except Exception as e:
            log.warning("paddleocr.health_failed", error=str(e))

        log.info("worker.ready", poll_interval=POLL_INTERVAL)

        while not shutdown.is_set():
            try:
                row = await claim_next_row(ck)
            except Exception as e:
                log.error("poll.error", error=str(e))
                await asyncio.sleep(30)
                continue

            if row is None:
                try:
                    await asyncio.wait_for(shutdown.wait(), timeout=float(POLL_INTERVAL))
                except asyncio.TimeoutError:
                    pass
                continue

            try:
                await process_row(row, ck, pp, http)
            except asyncio.CancelledError:
                break

    await ck.close()
    await pp.close()
    log.info("worker.stopped")


if __name__ == "__main__":
    asyncio.run(main())
