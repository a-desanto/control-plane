# PHASE14_LANGFUSE_RUNBOOK.md — deploy Langfuse on a control VPS

**Phase:** 14 (Observability layer) — see `ROADMAP.md`
**Scope:** MVP — Langfuse only. Loki + Grafana are follow-on sub-phases.
**Outcome:** every paperclipai heartbeat ships a trace to Langfuse; you can see runs, costs, and prompts in a centralized UI.
**Effort:** ~1 working day (most is waiting for VPS provision + Coolify boot + DNS).

---

## Why now

Phase 8 (eval/regression) depends on Langfuse traces. Phases 6, 7, 9, and 10 all benefit from observability. Without Langfuse, every "what did the agent do?" question requires direct DB queries. With it, you have a UI for the entire fleet.

This is the cheapest infrastructure win on the roadmap.

---

## Architecture target

```
Client VPS (cfpa.sekuirtek.com)              Control VPS (NEW)
┌──────────────────────────┐                 ┌─────────────────────────┐
│ paperclipai              │                 │ Coolify                 │
│ openrouter-proxy         │ ──── traces ──► │ Langfuse web            │
│ openclaw-worker          │     (HTTPS)     │ Langfuse worker         │
│ cfpa-watchdog            │                 │ Postgres (Langfuse DB)  │
│ n8n / Flowise / etc.     │                 │ ClickHouse              │
└──────────────────────────┘                 │ Redis                   │
                                             │ MinIO (blob storage)    │
                                             └─────────────────────────┘
```

All Langfuse infra lives on the control VPS. Client VPSes ship traces via HTTPS. Control VPS becomes shared infrastructure across the future fleet — every new client VPS sends to the same Langfuse instance, scoped per-project.

---

## Pre-flight (Tony does this before starting — ~10 min)

**1. Pick the control VPS provider and tier.**

Recommendation: Hostinger KVM 2 (~$8/mo): 2 vCPU, 8GB RAM, 100GB SSD. Langfuse v3 needs ClickHouse which is RAM-hungry; the smallest Hostinger tier (2GB) won't be enough.

Alternative: any VPS with ≥8GB RAM, ≥40GB SSD, public IP, Ubuntu 22.04 or 24.04.

**2. Pick the Langfuse hostname.**

Suggested: `langfuse.cfpa.sekuirtek.com`. Add A record pointing to the new VPS's public IP once provisioned. TTL 300 so testing is fast.

**3. Decide secrets storage.**

You have a secrets manager already (per RUNBOOK §3). The new secrets you'll generate during this runbook:

- Coolify admin password
- Langfuse NEXTAUTH_SECRET (32-byte random)
- Langfuse SALT (32-byte random)
- Langfuse ENCRYPTION_KEY (32-byte random)
- Postgres password (for Langfuse's DB)
- ClickHouse password
- MinIO root credentials
- Langfuse public/secret API keys (generated after first login)

Have your secrets manager (1Password, vault, whatever you use) ready.

---

## Stage 1 — Provision control VPS (Tony, ~30 min)

Manual ops on the Hostinger control panel.

1. Provision Hostinger KVM 2, region close to existing client VPS for low latency.
2. Choose Ubuntu 24.04 LTS.
3. Set root SSH key (use the same key as the client VPS for simplicity, or a new one).
4. Note the public IP.
5. Add DNS A record: `langfuse.cfpa.sekuirtek.com` → public IP. TTL 300.
6. SSH in: `ssh root@<ip>`. Confirm uptime, OS version (`cat /etc/os-release`).
7. Run baseline updates: `apt update && apt upgrade -y && apt install -y curl wget htop`.
8. Set hostname (optional): `hostnamectl set-hostname cfpa-control-1`.

**Done when:** you can SSH into the new VPS and `dig langfuse.cfpa.sekuirtek.com` returns its IP.

---

## Stage 2 — Install Coolify on control VPS (Tony, ~15 min)

Coolify install is a one-liner per their docs. Run on the control VPS as root:

```bash
curl -fsSL https://cdn.coollabs.io/coolify/install.sh | bash
```

The installer:

- Installs Docker and Docker Compose
- Creates Coolify's own Postgres + Redis + nginx
- Boots Coolify on port 8000

While it runs (~5 min), open two more DNS A records pointing to the same VPS IP:

- `coolify.cfpa.sekuirtek.com` (Coolify admin UI)
- `langfuse.cfpa.sekuirtek.com` (already done above)

When the installer finishes:

1. Visit `http://<vps-ip>:8000` (or the coolify subdomain after DNS propagates).
2. Bootstrap admin account (email + strong password — store in secrets manager).
3. Settings → Server → confirm Coolify shows the VPS as "localhost" (it manages itself).
4. Settings → Domain → set Coolify's own domain to `coolify.cfpa.sekuirtek.com`. Coolify will auto-issue a Let's Encrypt cert.
5. Connect to GitHub: Source → Add → GitHub App, install on `a-desanto/control-plane`. (Optional for Langfuse but useful later.)

**Done when:** you can log into `https://coolify.cfpa.sekuirtek.com` with TLS.

---

## Stage 3 — Deploy Langfuse via Coolify (Claude CLI on control VPS can drive this — ~30 min)

Langfuse v3 ships a docker-compose. Coolify supports Docker Compose deployments natively.

**Option A — Coolify "Docker Compose" deployment (preferred):**

1. In Coolify: New Project → "observability". Within it: Add Resource → Docker Compose.
2. Source: paste the contents of Langfuse's official `docker-compose.yml` (fetch the latest from `https://github.com/langfuse/langfuse/blob/main/docker-compose.yml` — pin to a tagged release like `v3.x.x`).
3. Configure env vars (use the secrets manager values from pre-flight). Critical ones:

```
NEXTAUTH_SECRET=<32-byte random hex>
NEXTAUTH_URL=https://langfuse.cfpa.sekuirtek.com
SALT=<32-byte random hex>
ENCRYPTION_KEY=<32-byte random hex>

DATABASE_URL=postgresql://langfuse:<pgpass>@langfuse-postgres:5432/langfuse
POSTGRES_PASSWORD=<pgpass>
POSTGRES_DB=langfuse
POSTGRES_USER=langfuse

CLICKHOUSE_URL=http://langfuse-clickhouse:8123
CLICKHOUSE_USER=default
CLICKHOUSE_PASSWORD=<chpass>
CLICKHOUSE_MIGRATION_URL=clickhouse://langfuse-clickhouse:9000
CLICKHOUSE_CLUSTER_ENABLED=false

REDIS_HOST=langfuse-redis
REDIS_PORT=6379

LANGFUSE_S3_EVENT_UPLOAD_BUCKET=langfuse
LANGFUSE_S3_EVENT_UPLOAD_REGION=auto
LANGFUSE_S3_EVENT_UPLOAD_ACCESS_KEY_ID=<minio-access-key>
LANGFUSE_S3_EVENT_UPLOAD_SECRET_ACCESS_KEY=<minio-secret-key>
LANGFUSE_S3_EVENT_UPLOAD_ENDPOINT=http://langfuse-minio:9000
LANGFUSE_S3_EVENT_UPLOAD_FORCE_PATH_STYLE=true

# MinIO config
MINIO_ROOT_USER=<minio-access-key>
MINIO_ROOT_PASSWORD=<minio-secret-key>

TELEMETRY_ENABLED=false
LANGFUSE_ENABLE_EXPERIMENTAL_FEATURES=false
```

Generate the random secrets with: `openssl rand -hex 32` (run on any machine, paste into secrets manager + Coolify env).

4. Set domain on the `langfuse-web` service: `langfuse.cfpa.sekuirtek.com`, port 3000. Coolify auto-issues TLS.
5. Deploy. Watch logs for ~5 min while ClickHouse migrations run.

**Option B — Manual docker-compose on the VPS (fallback if Coolify struggles):**

```bash
mkdir -p /opt/langfuse && cd /opt/langfuse
curl -L -o docker-compose.yml https://raw.githubusercontent.com/langfuse/langfuse/main/docker-compose.yml
# Edit env vars per above into a .env file alongside
docker compose up -d
```

Then add a Traefik label-only Coolify entry to route `langfuse.cfpa.sekuirtek.com` → `localhost:3000`.

**Done when:**

- `https://langfuse.cfpa.sekuirtek.com` returns the Langfuse login page with valid TLS.
- Login as admin, create an organization "CFPA", create a project "Caring First".
- Generate API keys for the project (Settings → API Keys → "Create new key"). Save `pk-lf-...` (public) and `sk-lf-...` (secret) to secrets manager. Save both; you only see them once.

---

## Stage 4 — Wire paperclipai to ship traces (Claude CLI on client VPS — ~15 min)

On the client VPS (`srv1408380`), update paperclipai's Coolify env vars:

```
LANGFUSE_HOST=https://langfuse.cfpa.sekuirtek.com
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
```

These are already documented in RUNBOOK §1 as expected env vars; wire them now.

Steps:

1. In Coolify (client VPS, app `ihe84uqp2yr5bu9wd43w34dq`): Settings → Environment Variables → add the three above.
2. Redeploy paperclipai (Coolify will roll the container).
3. Wait for healthy. Verify with: `curl https://paperclipai.cfpa.sekuirtek.com/api/health` returns 200.

Apply the same env vars to other containers that use Langfuse:

- `openclaw-worker` (`v3b2daw5wvaval2r6sb6mrxn`)
- `cfpa-watchdog` (recreate with the same Langfuse vars added)

Each one needs the same three env vars. Redeploy after.

**Done when:** all four containers (paperclipai, openclaw-worker, opencode adapters, cfpa-watchdog) have `LANGFUSE_HOST` set and are running healthy.

---

## Stage 5 — Verify trace flow (Claude CLI — ~10 min)

1. Trigger a test heartbeat. Easiest: assign an existing issue to opencode-agent and unpause it briefly (or use the on-demand wake button in paperclipai UI).
2. Wait 30s for the heartbeat to complete and the trace to ship.
3. Open `https://langfuse.cfpa.sekuirtek.com` → Caring First project → Traces.
4. Confirm: a trace appears with the agent name, model used, input/output, token counts, cost.
5. Sanity check: cost on the Langfuse trace should match cost recorded in paperclip's `cost_events` table for the same heartbeat (run the same query you used in our cost-debug session).

If traces don't appear within 60s, debug paths:

- Container logs: `docker logs <paperclipai-container> 2>&1 | grep -i langfuse` — look for connection errors.
- DNS: `docker exec <paperclipai-container> curl -v https://langfuse.cfpa.sekuirtek.com/api/public/health` should return 200.
- Auth: verify the public/secret keys match exactly what's in Langfuse Settings → API Keys.

---

## Stage 6 — Document the deployment (~15 min)

After Langfuse is live and verified:

1. Update `ARCHITECTURE.md` component inventory — add Langfuse row pointing at `langfuse.cfpa.sekuirtek.com`. Add the control VPS to the deployment topology.
2. Update `RUNBOOK.md` — add §9 "Control VPS operations" covering: how to access, how to update Langfuse, how to rotate Langfuse API keys, how to add a new client project to Langfuse.
3. Update `ROADMAP.md` Phase 14 status: from "Not started" to "Langfuse done. Loki + Grafana pending."
4. Save the Langfuse keys + Coolify creds in your secrets manager. Do NOT commit any of these to the repo.

This becomes a PR (your Claude CLI can write the prompt the same way it has for prior doc PRs).

---

## After Phase 14 (Langfuse): the next sub-phases

Same control VPS, same Coolify, deploy alongside Langfuse:

**Phase 14B — Loki + Promtail.** Centralized log aggregation. ~1 day. Promtail on each client VPS ships docker logs to Loki. Useful for debugging incidents across the fleet.

**Phase 14C — Grafana + dashboards.** ~1 day. Build dashboards for: paperclip activity, worker health, openrouter-proxy throughput, per-agent cost trends, watchdog alert history. Langfuse already gives most LLM observability; Grafana fills in the operational/infra side.

These two are nice-to-haves until you have multiple clients. Skip them initially if you want to move on to Phase 6 (RAG) faster — the eval layer (Phase 8) only needs Langfuse, not Loki/Grafana.

---

## Handoff to Claude CLI

Stages 3, 4, and 5 are largely Claude-CLI-executable once Stages 1 and 2 are done. When you're ready:

1. Complete Stage 1 (provision VPS) and Stage 2 (install Coolify) manually — these are the parts a CLI can't do because they touch your provider account and Coolify bootstrap.
2. Hand Stages 3-5 to Claude CLI on the new control VPS with this runbook in context. The CLI can deploy Langfuse via Coolify API (Coolify has a REST API for app deploys), wire env vars on the client VPS via docker exec + paperclipai's API, and run the verification queries.
3. The CLI's deliverable: Langfuse URL, screenshot of a trace, the Stage 6 doc-update PR.

Before handing off, make sure the CLI has:

- Access to the new control VPS (SSH key + Coolify API key)
- Access to the existing client VPS (it already has this)
- The Langfuse API keys you generated in Stage 3
- This runbook
