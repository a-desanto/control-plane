# COSTS_DASHBOARD_MVP_RUNBOOK.md — unified costs dashboard (stop-gap before Phase 5.5 Grafana)

**Phase:** 5.4 (Costs Dashboard MVP — precedes Phase 5.5 Grafana operator dashboard)
**Companion to:** `ARCHITECTURE.md`, `ROADMAP.md`, future `PHASE5_5_GRAFANA_RUNBOOK.md`
**Effort:** ~5-6 hours
**Outcome:** `https://costs.cfpa.sekuirtek.com` (or similar subdomain) — single page showing AWS spend, per-client paperclipai cost, vendor subscription totals, all in one view

---

## Why this work, why now

You're about to start tracking real client revenue and need one place to see all spend in real-time. The Phase 5.5 Grafana operator dashboard will eventually cover ~80% of this, but it's 2-3 weeks out. You need visibility before then.

This is **intentionally a stop-gap MVP**. Single static page, three data sources, no SPA framework, no custom backend beyond a thin FastAPI scraper. Goal is "see all costs in 30 seconds" — not "build a great cost product."

When Phase 5.5 Grafana lands:
- AWS spend section → migrate to Grafana CloudWatch + Cost Explorer datasources
- Per-client paperclipai breakdown → migrate to Grafana SQL panels against `cost_events`
- Vendor subscription list → keep as a separate page (Grafana doesn't do static tables well) OR migrate to Notion/Airtable
- Anomaly alerting → Grafana alerting replaces the simple Discord webhook

This MVP keeps the vendor subscription page going forward. Live data sections retire.

---

## Architecture decisions

### Scope: three data sources, one page, hourly refresh

| Section | Source | Refresh |
|---|---|---|
| AWS spend (today, MTD, by service, forecast) | AWS Cost Explorer API | Hourly cache (CE has rate limits + per-request cost) |
| Per-client / per-model / per-agent paperclipai cost | `cost_events` table on paperclipai DB | On every page load (cheap query) |
| Vendor subscriptions | `vendors.json` file in repo | Manual edits + redeploy |

The page renders all three sections from the cached + live data. No JavaScript framework — just server-rendered HTML with a tiny refresh button.

### Stack

| Component | Choice | Reason |
|---|---|---|
| Language | Python 3.12 | Matches bedrock-proxy pattern; boto3 + asyncpg already proven |
| Framework | FastAPI + Jinja2 templates | Server-rendered HTML, no SPA complexity |
| AWS SDK | boto3 (existing IAM creds) | Same pattern as fetch_bedrock_model_ids.py |
| DB client | asyncpg | Same pattern as bedrock-proxy |
| Cache | Local JSON file `/tmp/aws_cost_cache.json` refreshed hourly via background task | Simple, no Redis needed |
| Container | python:3.12-slim | Standard |
| Deployment | Coolify app on srv1408380, port 4003, internal network | Consistent with rest of the stack |
| Auth | Coolify basic auth (single operator credential) | Behind cfpa.sekuirtek.com subdomain |

### Why FastAPI + Jinja2 (not Next.js or React)

Cost dashboard is a thin "fetch + render" use case. FastAPI is one process, ~150 lines of code, no build step, no node_modules. Next.js would be over-engineered for what's essentially a server-rendered HTML page. When Phase 5.5 Grafana lands, this entire app retires for the live data sections — keeping it minimal makes deletion easy.

### Why not put it inside paperclipai

paperclipai is the agent orchestration layer. Cost dashboard is operator-internal tooling, conceptually separate. Mixing the two means cost-dashboard bugs could affect agent reliability. Separate Coolify app keeps the blast radius contained.

### Auth model

- Coolify built-in basic auth, single shared operator credential (rotated quarterly, stored in 1Password as `costs-dashboard-basic-auth`)
- Subdomain: `costs.cfpa.sekuirtek.com` (point Cloudflare DNS at srv1408380, Coolify handles TLS termination)
- Future option: Cloudflare Access policy with email-based SSO when team scales

---

## IAM additions for cfpa-deploy-script-runner

The Cost Explorer API requires additional IAM permissions beyond what the existing policy grants. Extend `cfpa-deploy-script-runner-policy` (or create a new dedicated user `cfpa-costs-dashboard` if you prefer least-privilege isolation):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ce:GetCostAndUsage",
        "ce:GetCostForecast",
        "ce:GetDimensionValues",
        "ce:GetTags"
      ],
      "Resource": "*"
    }
  ]
}
```

Cost Explorer is region-pinned to **us-east-1** regardless of where your services run. The boto3 client must specify `region_name="us-east-1"` for these calls.

---

## Repo structure

```
control-plane/
└── apps/
    └── costs-dashboard/                # NEW
        ├── app.py                      # FastAPI + Jinja2 + boto3 + asyncpg
        ├── templates/
        │   └── dashboard.html          # Single-page Jinja2 template
        ├── static/
        │   └── style.css               # Minimal CSS, ~50 lines
        ├── vendors.json                # Vendor subscription list (manually maintained)
        ├── requirements.txt
        ├── Dockerfile
        └── README.md
```

---

## Stages

### Stage 1 — Extend IAM policy (~5 min)

Add `ce:GetCostAndUsage`, `ce:GetCostForecast`, `ce:GetDimensionValues`, `ce:GetTags` to `cfpa-deploy-script-runner-policy`. Verify with:

```bash
python3 -c "
import boto3, datetime
ce = boto3.client('ce', region_name='us-east-1')
today = datetime.date.today()
resp = ce.get_cost_and_usage(
    TimePeriod={'Start': str(today.replace(day=1)), 'End': str(today)},
    Granularity='MONTHLY',
    Metrics=['UnblendedCost']
)
print('OK:', resp['ResultsByTime'])
"
```

Should print MTD spend total. If 403 → IAM not propagated yet, retry in 30s.

### Stage 2 — Build app skeleton + deploy

1. Create directory + files per repo structure above
2. Commit + push
3. Coolify: New app, configure per deployment block, deploy
4. Set `custom_network_aliases = '["costs-dashboard"]'` in Coolify DB
5. Verify health: `curl http://costs-dashboard:4003/health`

### Stage 3 — Cloudflare DNS + auth

1. Cloudflare DNS: add A record `costs.cfpa.sekuirtek.com` → srv1408380 IP
2. Coolify: configure public domain + Let's Encrypt cert
3. Coolify: enable basic auth, save to 1Password as `costs-dashboard-basic-auth`
4. Verify: open `https://costs.cfpa.sekuirtek.com/` in browser

### Stage 4 — Verify each section renders correctly

| Section | Pass criteria |
|---|---|
| AWS MTD card | Shows non-zero $ matching AWS console |
| AWS forecast | Shows reasonable EOM projection |
| AWS by service | Lists Bedrock, S3, etc. with $ values |
| Per-client paperclipai | Lists company_id rows from cost_events |
| Per-model | Lists Sonnet/Haiku/etc. |
| Vendor subs | Lists 6 entries from vendors.json with portal links working |
| Refresh button | Triggers cache refresh, page reloads with newer timestamp |

### Stage 5 — Document + add to RUNBOOK

Add to RUNBOOK.md §5 (Operational dashboards).

---

## Coolify deployment

```
App name:           costs-dashboard
Source:             github.com/a-desanto/control-plane, branch main, base /apps/costs-dashboard
Build pack:         Dockerfile
Internal port:      4003
Network:            coolify
Public domain:      costs.cfpa.sekuirtek.com
Auth:               Coolify basic auth
custom_network_aliases:  ["costs-dashboard"]
Restart policy:     always
```

Env vars:

| Variable | Value |
|----------|-------|
| `PAPERCLIP_DB_URL` | `postgresql://paperclip:paperclip@paperclip:54329/paperclip` |
| `AWS_ACCESS_KEY_ID` | cfpa-deploy-script-runner key (with ce:* added) |
| `AWS_SECRET_ACCESS_KEY` | paired secret |

---

## Verification checklist

| # | Check | Pass criteria |
|---|---|---|
| 1 | IAM policy extended | Cost Explorer one-liner returns data |
| 2 | App container healthy | `/health` returns 200, Coolify shows green |
| 3 | Network alias durable | resolves from sibling container |
| 4 | DNS + TLS | `https://costs.cfpa.sekuirtek.com` loads with valid cert |
| 5 | Basic auth working | Wrong password → 401; right password → dashboard |
| 6 | AWS MTD section | Non-zero, matches AWS billing console |
| 7 | Per-client section | Returns rows (or "no data" message if empty) |
| 8 | Per-model section | Sonnet + Haiku present |
| 9 | Vendor list | 6 entries, portal links correct |
| 10 | Refresh button | Cache file timestamp updates after click |
| 11 | Background refresh | 1 hour later, cache auto-refreshes |
| 12 | Failure mode | CE down: serves stale cache, doesn't 500 |

---

## Maintenance

- **Vendor updates:** edit `vendors.json`, commit, push, auto-redeploy.
- **Quarterly review:** verify costs match vendors.json, update `last_reviewed` dates.

---

## When to retire (Phase 5.5 Grafana cutover)

Migrate live AWS + per-client sections to Grafana. Keep vendor subscription page here or move to Notion. Update RUNBOOK §5.
