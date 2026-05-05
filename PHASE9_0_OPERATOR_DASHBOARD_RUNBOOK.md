# Phase 9.0 — Operator Dashboard MVP Runbook

**Drafted:** 2026-05-05  
**Status:** Stage 1 DONE. Stage 2 in progress.  
**Route base:** `costs.cfpa.sekuirtek.com/clients` (additive — does not touch `/` or `/costs`)  
**App:** `control-plane/apps/costs-dashboard` (existing FastAPI + Jinja2, port 4003)  
**DB:** `postgresql://paperclip:paperclip@paperclip:54329/paperclip`

---

## Why this work, why now

Operator dashboard gives us a UI surface to:
- See all clients at a glance (status, spend, add-ons)
- View per-client detail without a SQL session
- Toggle Document Workflows (Phase 12) on/off per client via checkbox — eliminating the SQL-session install flow

After Stage 4 ships, Phase 12 Stage 2 (PaddleOCR + document-agent) can be verified and deployed
faster because the install toggle is in the dashboard, not in a psql session.

---

## Stages

| Stage | Scope | Effort | Status |
|-------|-------|--------|--------|
| 1 | Schema migration + Caring First bootstrap | ~30 min | DONE 2026-05-05 |
| 2 | `/clients` list view, read-only | ~3 hr | DONE 2026-05-05 |
| 3 | `/client/{uuid}` detail view, read-only | ~4-6 hr | DONE 2026-05-05 |
| 4 | Add-on toggle UI + Document Workflows install/uninstall | ~6-8 hr | DONE 2026-05-05 |
| 5 | Audit log table + display | ~1 hr | DONE 2026-05-05 |
| 6 | Deploy verification (10-point checklist) | | TODO |

**v1 = Stages 1-3** (read-only client management)  
**v1.5 = Stages 4-5** (write capability)

---

## Stage 1 — Schema migration (DONE 2026-05-05)

Migration file: `migrations/phase9_0_operator_schema.sql`  
Applied to: `paperclip` DB on `paperclip:54329`

### Tables created

#### `operator_client_addons`
One row per `(company_id, addon_key)`. Tracks whether each add-on is enabled and when it was installed.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | gen_random_uuid() |
| company_id | UUID FK → companies | |
| addon_key | TEXT | 'document_workflows', future: 'rag_search', 'langfuse_tracing' |
| enabled | BOOLEAN | false until operator enables |
| installed_at | TIMESTAMPTZ | null until first enable |
| updated_at | TIMESTAMPTZ | |

Unique constraint: `(company_id, addon_key)`

#### `operator_audit_log`
Every operator write action (toggle add-on, etc.).

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| operator_email | TEXT | Who performed the action |
| company_id | UUID FK → companies | |
| action | TEXT | 'addon.enabled', 'addon.disabled' |
| addon_key | TEXT | Which add-on |
| details | JSONB | Arbitrary context |
| created_at | TIMESTAMPTZ | |

### Bootstrap data

Caring First (`bd80728d-6755-4b63-a9b9-c0e24526c820`) seeded with `document_workflows = false`.

### Apply (idempotent — safe to re-run)

```bash
docker exec -i cfpa-backup-runner psql \
  "postgresql://paperclip:paperclip@paperclip:54329/paperclip" \
  < migrations/phase9_0_operator_schema.sql
```

---

## Stage 2 — /clients list view (DONE 2026-05-05)

Route: `GET /clients`  
Template: `apps/costs-dashboard/templates/clients.html`

### Columns displayed

| Column | Source |
|--------|--------|
| Company name (→ detail link) | `companies.name` |
| Status | `companies.status` |
| Monthly budget | `companies.budget_monthly_cents` |
| MTD spend (live) | `SUM(cost_events.cost_cents)` WHERE month = current month |
| Members | `COUNT(company_memberships)` WHERE status='active' |
| Agents | `COUNT(agents)` |
| Add-ons | `operator_client_addons` WHERE enabled=true |
| Created | `companies.created_at` |

---

## Stage 3 — /client/{uuid} detail view (DONE 2026-05-05)

Route: `GET /client/{company_id}`  
Template: `apps/costs-dashboard/templates/client_detail.html`

### Sections

1. **Company header** — name, status, budget, MTD spend, created date
2. **Add-ons** — each known add-on with enabled/disabled badge (toggle in Stage 4)
3. **Stats** — agents count, issues count, active members count, 30-day API calls
4. **Recent activity** — last 20 rows from `activity_log` for this company

---

## Stage 4 — Add-on toggle UI (DONE 2026-05-05)

Routes:
- `POST /client/{company_id}/addon/{addon_key}/enable`
- `POST /client/{company_id}/addon/{addon_key}/disable`

Both redirect back to `/client/{company_id}` after writing.

### Document Workflows install logic

**Enable:**
1. `UPDATE operator_client_addons SET enabled=true, installed_at=now(), updated_at=now()`
   WHERE `company_id=? AND addon_key='document_workflows'`
2. INSERT audit log row: `action='addon.enabled'`

**Disable:**
1. `UPDATE operator_client_addons SET enabled=false, updated_at=now()`
2. INSERT audit log row: `action='addon.disabled'`

Note: These are toggle-only. No side-effects yet (no Docker container start/stop). Phase 12 Stage 2
will add the actual PaddleOCR container orchestration, keyed off the `enabled` flag.

---

## Stage 5 — Audit log display (DONE 2026-05-05)

Audit log shown in two places:
- `/client/{uuid}` detail page: last 20 entries for that company
- `/audit` global page: last 100 entries across all companies

---

## Stage 6 — Deploy verification

After git push + Coolify redeploy, run through the 10-point checklist:

| # | Check | Command / URL |
|---|-------|---------------|
| 1 | Container healthy | `curl http://costs-dashboard:4003/health` → `{"status":"ok"}` |
| 2 | `/` still works | `https://costs.cfpa.sekuirtek.com/` loads cost dashboard |
| 3 | `/costs` still works | `https://costs.cfpa.sekuirtek.com/costs` loads (if route exists) |
| 4 | `/clients` loads | Lists Caring First with correct status/spend/agents |
| 5 | `/client/bd80728d-...` loads | Shows Caring First detail with add-ons section |
| 6 | document_workflows shows as disabled | Badge = "Disabled" before toggle |
| 7 | Enable toggle works | POST → `enabled=true` in DB + audit row created |
| 8 | Disable toggle works | POST → `enabled=false` in DB + audit row created |
| 9 | `/audit` shows log entries | Rows from steps 7-8 appear |
| 10 | No 500s on any route | Check Coolify logs for errors |

---

## File changes summary

```
control-plane/
├── migrations/
│   └── phase9_0_operator_schema.sql        NEW
├── apps/costs-dashboard/
│   ├── app.py                               MODIFIED (added /clients, /client/{uuid}, /addon/*, /audit)
│   └── templates/
│       ├── base.html                        NEW (shared nav + layout)
│       ├── clients.html                     NEW
│       ├── client_detail.html               NEW
│       └── audit.html                       NEW
└── PHASE9_0_OPERATOR_DASHBOARD_RUNBOOK.md  NEW
```

---

## Known add-on keys

| Key | Phase | Description |
|-----|-------|-------------|
| `document_workflows` | Phase 12 | S3 drop bucket → SNS → webhook → OCR pipeline |

Future (not yet in schema): `rag_search` (Phase 6), `langfuse_tracing` (Phase 14)
