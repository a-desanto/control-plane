import json
import os
from datetime import datetime, timezone
from pathlib import Path

import asyncpg
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

DB_URL = os.environ.get(
    "PAPERCLIP_DB_URL",
    "postgresql://paperclip:paperclip@paperclip:54329/paperclip",
)
VENDORS_PATH = Path(__file__).parent / "vendors.json"


def load_vendors() -> dict:
    with open(VENDORS_PATH) as f:
        return json.load(f)


async def query_by_client(conn: asyncpg.Connection) -> list[dict]:
    rows = await conn.fetch("""
        SELECT
            ce.company_id::text,
            COALESCE(c.name, ce.company_id::text) AS company_name,
            SUM(ce.cost_cents)   AS total_cents,
            SUM(ce.input_tokens) AS input_tokens,
            SUM(ce.output_tokens) AS output_tokens,
            COUNT(*)             AS calls,
            MAX(ce.occurred_at)  AS last_event
        FROM cost_events ce
        LEFT JOIN companies c ON c.id = ce.company_id
        WHERE ce.occurred_at >= NOW() - INTERVAL '30 days'
        GROUP BY ce.company_id, c.name
        ORDER BY total_cents DESC
    """)
    return [dict(r) for r in rows]


async def query_by_model(conn: asyncpg.Connection) -> list[dict]:
    rows = await conn.fetch("""
        SELECT
            model,
            provider,
            SUM(cost_cents)    AS total_cents,
            SUM(input_tokens)  AS input_tokens,
            SUM(output_tokens) AS output_tokens,
            COUNT(*)           AS calls
        FROM cost_events
        WHERE occurred_at >= NOW() - INTERVAL '30 days'
        GROUP BY model, provider
        ORDER BY total_cents DESC
    """)
    return [dict(r) for r in rows]


async def query_mtd(conn: asyncpg.Connection) -> dict:
    row = await conn.fetchrow("""
        SELECT
            SUM(cost_cents)    AS total_cents,
            SUM(input_tokens)  AS input_tokens,
            SUM(output_tokens) AS output_tokens,
            COUNT(*)           AS calls
        FROM cost_events
        WHERE occurred_at >= DATE_TRUNC('month', NOW())
    """)
    return dict(row) if row else {}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    vendors_data = load_vendors()

    db_error = None
    by_client: list[dict] = []
    by_model: list[dict] = []
    mtd: dict = {}

    try:
        conn = await asyncpg.connect(DB_URL)
        try:
            by_client = await query_by_client(conn)
            by_model = await query_by_model(conn)
            mtd = await query_mtd(conn)
        finally:
            await conn.close()
    except Exception as e:
        db_error = str(e)

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "aws_last_checked": vendors_data.get("aws_last_checked", "—"),
            "vendors": vendors_data.get("subscriptions", []),
            "by_client": by_client,
            "by_model": by_model,
            "mtd": mtd,
            "db_error": db_error,
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        },
    )
