import json
import os
from datetime import datetime, timezone
from pathlib import Path

import asyncpg
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
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

OPERATOR_EMAIL = os.environ.get("OPERATOR_EMAIL", "operator@cfpa.sekuirtek.com")


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


def _now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


# ── Operator: client list helpers ──────────────────────────────────────────

async def query_clients(conn: asyncpg.Connection) -> list[dict]:
    rows = await conn.fetch("""
        SELECT
            c.id::text              AS company_id,
            c.name,
            c.status,
            c.budget_monthly_cents,
            c.created_at,
            COALESCE(mtd.mtd_cents, 0)  AS mtd_cents,
            COALESCE(mb.members, 0)     AS members,
            COALESCE(ag.agents, 0)      AS agents
        FROM companies c
        LEFT JOIN (
            SELECT company_id, SUM(cost_cents) AS mtd_cents
            FROM cost_events
            WHERE occurred_at >= DATE_TRUNC('month', NOW())
            GROUP BY company_id
        ) mtd ON mtd.company_id = c.id
        LEFT JOIN (
            SELECT company_id, COUNT(*) AS members
            FROM company_memberships
            WHERE status = 'active'
            GROUP BY company_id
        ) mb ON mb.company_id = c.id
        LEFT JOIN (
            SELECT company_id, COUNT(*) AS agents
            FROM agents
            GROUP BY company_id
        ) ag ON ag.company_id = c.id
        ORDER BY c.created_at DESC
    """)

    addon_rows = await conn.fetch("""
        SELECT company_id::text, addon_key
        FROM operator_client_addons
        WHERE enabled = true
        ORDER BY addon_key
    """)
    addons_by_company: dict[str, list[str]] = {}
    for ar in addon_rows:
        addons_by_company.setdefault(ar["company_id"], []).append(ar["addon_key"])

    result = []
    for row in rows:
        d = dict(row)
        d["addons_enabled"] = addons_by_company.get(d["company_id"], [])
        result.append(d)
    return result


# ── Operator: client detail helpers ────────────────────────────────────────

async def query_client_detail(conn: asyncpg.Connection, company_id: str) -> dict | None:
    row = await conn.fetchrow("""
        SELECT
            id::text        AS company_id,
            name,
            status,
            issue_prefix,
            budget_monthly_cents,
            spent_monthly_cents,
            created_at,
            paused_at
        FROM companies
        WHERE id = $1::uuid
    """, company_id)
    return dict(row) if row else None


async def query_client_stats(conn: asyncpg.Connection, company_id: str) -> dict:
    mtd = await conn.fetchval("""
        SELECT COALESCE(SUM(cost_cents), 0)
        FROM cost_events
        WHERE company_id = $1::uuid
          AND occurred_at >= DATE_TRUNC('month', NOW())
    """, company_id)

    members = await conn.fetchval("""
        SELECT COUNT(*) FROM company_memberships
        WHERE company_id = $1::uuid AND status = 'active'
    """, company_id)

    agents = await conn.fetchval("""
        SELECT COUNT(*) FROM agents WHERE company_id = $1::uuid
    """, company_id)

    issues = await conn.fetchval("""
        SELECT COUNT(*) FROM issues WHERE company_id = $1::uuid
    """, company_id)

    calls_30d = await conn.fetchval("""
        SELECT COUNT(*) FROM cost_events
        WHERE company_id = $1::uuid
          AND occurred_at >= NOW() - INTERVAL '30 days'
    """, company_id)

    return {
        "mtd_cents": int(mtd or 0),
        "members": int(members or 0),
        "agents": int(agents or 0),
        "issues": int(issues or 0),
        "calls_30d": int(calls_30d or 0),
    }


async def query_client_addons(conn: asyncpg.Connection, company_id: str) -> list[dict]:
    rows = await conn.fetch("""
        SELECT addon_key, enabled, installed_at, updated_at
        FROM operator_client_addons
        WHERE company_id = $1::uuid
        ORDER BY addon_key
    """, company_id)
    return [dict(r) for r in rows]


async def query_client_activity(conn: asyncpg.Connection, company_id: str) -> list[dict]:
    rows = await conn.fetch("""
        SELECT actor_type, actor_id, action, entity_type, entity_id, created_at
        FROM activity_log
        WHERE company_id = $1::uuid
        ORDER BY created_at DESC
        LIMIT 20
    """, company_id)
    return [dict(r) for r in rows]


async def query_client_audit(conn: asyncpg.Connection, company_id: str) -> list[dict]:
    rows = await conn.fetch("""
        SELECT operator_email, action, addon_key, details, created_at
        FROM operator_audit_log
        WHERE company_id = $1::uuid
        ORDER BY created_at DESC
        LIMIT 20
    """, company_id)
    return [dict(r) for r in rows]


# ── Operator: addon toggle helpers ─────────────────────────────────────────

async def addon_enable(conn: asyncpg.Connection, company_id: str, addon_key: str) -> None:
    await conn.execute("""
        UPDATE operator_client_addons
        SET enabled = true,
            installed_at = COALESCE(installed_at, now()),
            updated_at   = now()
        WHERE company_id = $1::uuid AND addon_key = $2
    """, company_id, addon_key)
    await conn.execute("""
        INSERT INTO operator_audit_log (operator_email, company_id, action, addon_key)
        VALUES ($1, $2::uuid, 'addon.enabled', $3)
    """, OPERATOR_EMAIL, company_id, addon_key)


async def addon_disable(conn: asyncpg.Connection, company_id: str, addon_key: str) -> None:
    await conn.execute("""
        UPDATE operator_client_addons
        SET enabled    = false,
            updated_at = now()
        WHERE company_id = $1::uuid AND addon_key = $2
    """, company_id, addon_key)
    await conn.execute("""
        INSERT INTO operator_audit_log (operator_email, company_id, action, addon_key)
        VALUES ($1, $2::uuid, 'addon.disabled', $3)
    """, OPERATOR_EMAIL, company_id, addon_key)


# ── Routes ──────────────────────────────────────────────────────────────────

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


# ── Stage 2: /clients list ──────────────────────────────────────────────────

@app.get("/clients", response_class=HTMLResponse)
async def clients_list(request: Request):
    db_error = None
    clients: list[dict] = []

    try:
        conn = await asyncpg.connect(DB_URL)
        try:
            clients = await query_clients(conn)
        finally:
            await conn.close()
    except Exception as e:
        db_error = str(e)

    return templates.TemplateResponse(
        "clients.html",
        {
            "request": request,
            "clients": clients,
            "db_error": db_error,
            "active_nav": "clients",
            "generated_at": _now_str(),
        },
    )


# ── Stage 3: /client/{company_id} detail ───────────────────────────────────

@app.get("/client/{company_id}", response_class=HTMLResponse)
async def client_detail(request: Request, company_id: str):
    db_error = None
    company = None
    stats: dict = {}
    addons: list[dict] = []
    activity: list[dict] = []
    audit_rows: list[dict] = []

    try:
        conn = await asyncpg.connect(DB_URL)
        try:
            company = await query_client_detail(conn, company_id)
            if company is None:
                raise HTTPException(status_code=404, detail="Client not found")
            stats = await query_client_stats(conn, company_id)
            addons = await query_client_addons(conn, company_id)
            activity = await query_client_activity(conn, company_id)
            audit_rows = await query_client_audit(conn, company_id)
        finally:
            await conn.close()
    except HTTPException:
        raise
    except Exception as e:
        db_error = str(e)

    return templates.TemplateResponse(
        "client_detail.html",
        {
            "request": request,
            "company": company or {},
            "mtd_cents": stats.get("mtd_cents", 0),
            "members": stats.get("members", 0),
            "agents": stats.get("agents", 0),
            "issues": stats.get("issues", 0),
            "calls_30d": stats.get("calls_30d", 0),
            "addons": addons,
            "activity": activity,
            "audit_rows": audit_rows,
            "db_error": db_error,
            "active_nav": "clients",
            "generated_at": _now_str(),
        },
    )


# ── Stage 4: addon toggles ──────────────────────────────────────────────────

@app.post("/client/{company_id}/addon/{addon_key}/enable")
async def addon_enable_route(company_id: str, addon_key: str):
    conn = await asyncpg.connect(DB_URL)
    try:
        await addon_enable(conn, company_id, addon_key)
    finally:
        await conn.close()
    return RedirectResponse(url=f"/client/{company_id}", status_code=303)


@app.post("/client/{company_id}/addon/{addon_key}/disable")
async def addon_disable_route(company_id: str, addon_key: str):
    conn = await asyncpg.connect(DB_URL)
    try:
        await addon_disable(conn, company_id, addon_key)
    finally:
        await conn.close()
    return RedirectResponse(url=f"/client/{company_id}", status_code=303)


# ── Stage 5: /audit global log ─────────────────────────────────────────────

@app.get("/audit", response_class=HTMLResponse)
async def audit_log(request: Request):
    db_error = None
    rows: list[dict] = []

    try:
        conn = await asyncpg.connect(DB_URL)
        try:
            raw = await conn.fetch("""
                SELECT
                    al.operator_email,
                    al.action,
                    al.addon_key,
                    al.details,
                    al.created_at,
                    c.name AS company_name,
                    al.company_id::text AS company_id
                FROM operator_audit_log al
                LEFT JOIN companies c ON c.id = al.company_id
                ORDER BY al.created_at DESC
                LIMIT 100
            """)
            rows = [dict(r) for r in raw]
        finally:
            await conn.close()
    except Exception as e:
        db_error = str(e)

    return templates.TemplateResponse(
        "audit.html",
        {
            "request": request,
            "rows": rows,
            "db_error": db_error,
            "active_nav": "audit",
            "generated_at": _now_str(),
        },
    )
