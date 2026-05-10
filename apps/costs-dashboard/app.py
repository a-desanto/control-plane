import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import asyncpg
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import uuid as _uuid

from addons import schemas as addon_schemas
import health_poller
import provisioning

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
        SELECT addon_key, enabled, installed_at, updated_at, settings
        FROM operator_client_addons
        WHERE company_id = $1::uuid
        ORDER BY addon_key
    """, company_id)
    out = []
    for r in rows:
        d = dict(r)
        # asyncpg returns JSONB as str (no codec configured here); parse if needed
        s = d.get("settings")
        if isinstance(s, str):
            try:
                d["settings"] = json.loads(s)
            except (json.JSONDecodeError, TypeError):
                d["settings"] = {}
        elif s is None:
            d["settings"] = {}
        d["has_schema"] = addon_schemas.get_schema(d["addon_key"]) is not None
        out.append(d)
    return out


async def query_addon_row(conn: asyncpg.Connection, company_id: str, addon_key: str) -> dict | None:
    row = await conn.fetchrow("""
        SELECT addon_key, enabled, installed_at, updated_at, settings
        FROM operator_client_addons
        WHERE company_id = $1::uuid AND addon_key = $2
    """, company_id, addon_key)
    if not row:
        return None
    d = dict(row)
    s = d.get("settings")
    if isinstance(s, str):
        try:
            d["settings"] = json.loads(s)
        except (json.JSONDecodeError, TypeError):
            d["settings"] = {}
    elif s is None:
        d["settings"] = {}
    return d


async def addon_save_settings(
    conn: asyncpg.Connection, company_id: str, addon_key: str, settings: dict
) -> None:
    await conn.execute("""
        UPDATE operator_client_addons
        SET settings   = $3::jsonb,
            updated_at = now()
        WHERE company_id = $1::uuid AND addon_key = $2
    """, company_id, addon_key, json.dumps(settings))
    await conn.execute("""
        INSERT INTO operator_audit_log (operator_email, company_id, action, addon_key, details)
        VALUES ($1, $2::uuid, 'addon.configured', $3, $4::jsonb)
    """, OPERATOR_EMAIL, company_id, addon_key, json.dumps(settings))


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


# ── Phase 9.1 Stage 1: client_configs + supporting queries ─────────────────

async def query_client_config(conn: asyncpg.Connection, company_id: str) -> dict | None:
    row = await conn.fetchrow("""
        SELECT
            id::text                  AS config_id,
            tier,
            slug,
            intake_methods,
            intake_email_address,
            onboarding_status,
            onboarding_started_at,
            onboarding_completed_at,
            ses_identity_status,
            ses_receipt_rule_name,
            s3_intake_bucket,
            sns_intake_topic_arn,
            dns_dkim_cnames,
            dns_mx_record,
            board_api_keys_count,
            agents_count,
            skills_installed_count,
            created_at,
            updated_at
        FROM client_configs
        WHERE company_id = $1::uuid
    """, company_id)
    return dict(row) if row else None


async def query_client_agents_full(conn: asyncpg.Connection, company_id: str) -> list[dict]:
    rows = await conn.fetch("""
        SELECT
            id::text AS id,
            name,
            role,
            status,
            last_heartbeat_at,
            paused_at,
            pause_reason
        FROM agents
        WHERE company_id = $1::uuid
        ORDER BY name
    """, company_id)
    return [dict(r) for r in rows]


async def query_client_skills(conn: asyncpg.Connection, company_id: str) -> list[dict]:
    rows = await conn.fetch("""
        SELECT
            id::text AS id,
            name,
            source_type,
            trust_level,
            created_at
        FROM company_skills
        WHERE company_id = $1::uuid
        ORDER BY name
    """, company_id)
    return [dict(r) for r in rows]


async def query_client_board_api_keys(conn: asyncpg.Connection, company_id: str) -> list[dict]:
    # board_api_keys is per-user; join via company_memberships to get keys for this company
    rows = await conn.fetch("""
        SELECT DISTINCT
            bak.id::text AS id,
            bak.name,
            bak.last_used_at,
            bak.created_at,
            bak.expires_at,
            bak.revoked_at,
            bak.user_id
        FROM board_api_keys bak
        JOIN company_memberships cm
          ON cm.principal_id = bak.user_id AND cm.principal_type = 'user'
        WHERE cm.company_id = $1::uuid
          AND cm.status = 'active'
          AND bak.revoked_at IS NULL
        ORDER BY bak.created_at DESC
    """, company_id)
    return [dict(r) for r in rows]


async def query_client_secrets(conn: asyncpg.Connection, company_id: str) -> list[dict]:
    """Returns secret presence (name + metadata) — never values."""
    rows = await conn.fetch("""
        SELECT
            id::text AS id,
            name,
            provider,
            description,
            latest_version,
            created_at,
            updated_at
        FROM company_secrets
        WHERE company_id = $1::uuid
        ORDER BY name
    """, company_id)
    return [dict(r) for r in rows]


async def query_client_health_latest(conn: asyncpg.Connection, company_id: str) -> dict | None:
    row = await conn.fetchrow("""
        SELECT
            dns_ok,
            ses_verified,
            containers_ok,
            backup_ok,
            snapshot_data,
            created_at
        FROM client_health_snapshots
        WHERE client_uuid = $1::uuid
        ORDER BY created_at DESC
        LIMIT 1
    """, company_id)
    return dict(row) if row else None


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
            "active_nav": "costs",
        },
    )


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


@app.get("/client/{company_id}", response_class=HTMLResponse)
async def client_detail(request: Request, company_id: str):
    db_error = None
    company = None
    stats: dict = {}
    addons: list[dict] = []
    activity: list[dict] = []
    audit_rows: list[dict] = []
    config: dict | None = None
    agents_full: list[dict] = []
    skills: list[dict] = []
    board_keys: list[dict] = []
    secrets: list[dict] = []
    health_snap: dict | None = None

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
            # Phase 9.1 Stage 1
            config = await query_client_config(conn, company_id)
            agents_full = await query_client_agents_full(conn, company_id)
            skills = await query_client_skills(conn, company_id)
            board_keys = await query_client_board_api_keys(conn, company_id)
            secrets = await query_client_secrets(conn, company_id)
            health_snap = await query_client_health_latest(conn, company_id)
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
            "config": config,
            "agents_full": agents_full,
            "skills": skills,
            "board_keys": board_keys,
            "secrets": secrets,
            "health_snap": health_snap,
            "db_error": db_error,
            "active_nav": "clients",
            "generated_at": _now_str(),
        },
    )


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


# ── Phase 9.1 Stage 4: per-add-on configure ────────────────────────────────

@app.get("/client/{company_id}/addon/{addon_key}/configure", response_class=HTMLResponse)
async def addon_configure_form(request: Request, company_id: str, addon_key: str):
    schema = addon_schemas.get_schema(addon_key)
    if not schema:
        raise HTTPException(status_code=404, detail=f"No config schema for addon '{addon_key}'")

    conn = await asyncpg.connect(DB_URL)
    try:
        company = await query_client_detail(conn, company_id)
        if company is None:
            raise HTTPException(status_code=404, detail="Client not found")
        addon_row = await query_addon_row(conn, company_id, addon_key)
        if addon_row is None:
            raise HTTPException(status_code=404, detail=f"Add-on '{addon_key}' not configured for this client")
    finally:
        await conn.close()

    current = addon_schemas.merge_with_defaults(addon_key, addon_row.get("settings"))
    return templates.TemplateResponse(
        "addon_configure.html",
        {
            "request": request,
            "company": company,
            "addon_key": addon_key,
            "addon_row": addon_row,
            "schema": schema,
            "current": current,
            "active_nav": "clients",
            "generated_at": _now_str(),
        },
    )


@app.post("/client/{company_id}/addon/{addon_key}/configure")
async def addon_configure_save(request: Request, company_id: str, addon_key: str):
    schema = addon_schemas.get_schema(addon_key)
    if not schema:
        raise HTTPException(status_code=404, detail=f"No config schema for addon '{addon_key}'")
    form = await request.form()
    # FastAPI's FormData behaves like a multidict; coerce_settings handles str values
    cleaned = addon_schemas.coerce_settings(addon_key, dict(form))

    conn = await asyncpg.connect(DB_URL)
    try:
        addon_row = await query_addon_row(conn, company_id, addon_key)
        if addon_row is None:
            raise HTTPException(status_code=404, detail=f"Add-on '{addon_key}' not configured for this client")
        await addon_save_settings(conn, company_id, addon_key, cleaned)
    finally:
        await conn.close()

    return RedirectResponse(url=f"/client/{company_id}", status_code=303)


# ── Phase 9.1 Stage 2: onboarding wizard ──────────────────────────────────

ADDON_KEYS_FOR_WIZARD = [
    "document_workflows", "voice", "marketing_social", "sales_outreach",
    "customer_support", "vertical_extensions", "premium_reasoning", "custom_workflow",
]


@app.get("/clients/new", response_class=HTMLResponse)
async def wizard_form(request: Request):
    return templates.TemplateResponse(
        "wizard.html",
        {
            "request": request,
            "active_nav": "clients",
            "addon_keys": ADDON_KEYS_FOR_WIZARD,
            "addon_titles": {k: addon_schemas.SCHEMAS.get(k, {}).get("title", k) for k in ADDON_KEYS_FOR_WIZARD},
            "generated_at": _now_str(),
        },
    )


@app.post("/clients/new")
async def wizard_submit(request: Request):
    form = await request.form()
    addons = [k for k in ADDON_KEYS_FOR_WIZARD if k in form]
    inputs = {
        "display_name": (form.get("display_name") or "").strip(),
        "slug":         (form.get("slug") or "").strip().lower(),
        "vertical":     form.get("vertical") or "",
        "primary_contact_email": form.get("primary_contact_email") or "",
        "tier":         form.get("tier") or "standard",
        "vps_provider": form.get("vps_provider") or "shared-srv1408380",
        "vps_region":   form.get("vps_region") or "us-east-2",
        "vps_size":     form.get("vps_size") or "shared",
        "addons":       addons,
        "client_legal_name":  form.get("client_legal_name") or "",
        "client_owner_email": form.get("client_owner_email") or "",
        "notes":              form.get("notes") or "",
    }
    if not inputs["display_name"] or not inputs["slug"]:
        raise HTTPException(status_code=400, detail="display_name and slug are required")

    client_uuid = str(_uuid.uuid4())
    # Run orchestrator as a background task so the HTTP response returns immediately
    asyncio.create_task(provisioning.run_orchestrator(client_uuid, inputs))
    # Stash inputs in audit log for retry/resume reference (no per-wizard table)
    conn = await asyncpg.connect(DB_URL)
    try:
        await conn.execute("""
            INSERT INTO operator_audit_log (operator_email, action, details)
            VALUES ($1, 'wizard.kickoff', $2::jsonb)
        """, OPERATOR_EMAIL, json.dumps({"client_uuid": client_uuid, **inputs}))
    finally:
        await conn.close()

    return RedirectResponse(url=f"/client/{client_uuid}/provisioning", status_code=303)


@app.get("/client/{company_id}/provisioning", response_class=HTMLResponse)
async def provisioning_page(request: Request, company_id: str):
    conn = await asyncpg.connect(DB_URL)
    try:
        config = await query_client_config(conn, company_id)
        company = await query_client_detail(conn, company_id)
    finally:
        await conn.close()
    return templates.TemplateResponse(
        "provisioning.html",
        {
            "request": request,
            "company_id": company_id,
            "company": company or {},
            "config": config or {},
            "active_nav": "clients",
            "generated_at": _now_str(),
        },
    )


@app.get("/client/{company_id}/provisioning/events", response_class=HTMLResponse)
async def provisioning_events_fragment(request: Request, company_id: str):
    """HTMX-polled fragment that renders the latest events."""
    conn = await asyncpg.connect(DB_URL)
    try:
        events = await conn.fetch("""
            SELECT step_name, status, message, payload, created_at
            FROM client_onboarding_events
            WHERE client_uuid = $1::uuid
            ORDER BY created_at ASC
        """, company_id)
        config = await query_client_config(conn, company_id)
    finally:
        await conn.close()
    return templates.TemplateResponse(
        "_provisioning_events.html",
        {
            "request": request,
            "events": [dict(e) for e in events],
            "config": config or {},
            "company_id": company_id,
        },
    )


@app.post("/client/{company_id}/provisioning/verify-dns")
async def provisioning_verify_dns(request: Request, company_id: str):
    """Operator clicked 'I've added DNS records'. Resume orchestrator from DNS-verify step."""
    # We need the original wizard inputs to resume; pull from the audit log entry
    conn = await asyncpg.connect(DB_URL)
    try:
        row = await conn.fetchrow("""
            SELECT details
            FROM operator_audit_log
            WHERE action = 'wizard.kickoff' AND details->>'client_uuid' = $1
            ORDER BY created_at DESC LIMIT 1
        """, company_id)
    finally:
        await conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="No wizard kickoff found for this client")
    inputs = json.loads(row["details"]) if isinstance(row["details"], str) else dict(row["details"])
    asyncio.create_task(provisioning.resume_after_dns(company_id, inputs))
    return RedirectResponse(url=f"/client/{company_id}/provisioning", status_code=303)


# ── Phase 9.1 Stage 3: health poller HTTP trigger ─────────────────────────

@app.post("/_internal/poll-health")
async def poll_health_route(request: Request):
    expected = os.environ.get("INTERNAL_TOKEN", "")
    if not expected:
        raise HTTPException(status_code=503, detail="INTERNAL_TOKEN env var not set; refusing")
    if request.headers.get("X-Internal-Token", "") != expected:
        raise HTTPException(status_code=401, detail="bad token")
    n = await health_poller.poll_all()
    return {"clients_polled": n}


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
