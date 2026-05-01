# RUNBOOK.md — per-VPS operations

Companion to `ARCHITECTURE.md` and `BUILD_BRIEF.md`. Covers deployment, env vars, and operational procedures for the per-client VPS stack.

---

## §1 Environment variables

### paperclipai

| Variable | Required | Default | Notes |
|---|---|---|---|
| `BETTER_AUTH_SECRET` | Yes | — | Secret for better-auth session signing. Min 32 chars, random. **Never commit.** |
| `BETTER_AUTH_BASE_URL` | Yes | — | Public-facing URL, e.g. `https://paperclipai.cfpa.sekuirtek.com` |
| `PAPERCLIP_DEPLOYMENT_MODE` | Yes | `authenticated` | `authenticated` for production. |
| `PAPERCLIP_AUTH_MODE` | Yes | `public` | Controls sign-up openness. |
| `PAPERCLIP_ALLOWED_HOSTNAMES` | Yes | — | Comma-separated allowed hostnames for CORS/auth. |
| `ANTHROPIC_API_KEY` | Yes | — | API key for Claude. **Never commit.** |
| `PAPERCLIP_REQUIRE_AGENT_APPROVAL` | No | `false` | Set `true` to require admin approval for new agents. |
| `ANTHROPIC_BASE_URL` | Yes | — | Set to `http://openrouter-proxy:4001` to route through the proxy. Omit only when using direct Anthropic API. |
| `NODE_ENV` | No | `production` | Standard Node env flag. Leave as `production`. |

paperclipai uses an **embedded PostgreSQL** instance (port 54329 inside the container). No
external `DATABASE_URL` is needed. The database is persisted via the container volume at
`/paperclip/instances/default/`.

### Traefik (Coolify labels)

| Label | Service | Value |
|---|---|---|
| `traefik.enable=true` | paperclipai | Enables Traefik routing |
| `traefik.http.routers.*.rule` | paperclipai | `Host(\`paperclipai.cfpa.sekuirtek.com\`)` |

paperclipai is directly public-facing. The `allowlist-internal-only` middleware from the
previous api-gateway architecture has been removed — paperclipai now accepts external traffic
directly.

### api-gateway (decommissioned 2026-04-27, code deleted)

api-gateway env vars (`API_GATEWAY_DATABASE_URL`, `API_GATEWAY_REDIS_URL`,
`API_GATEWAY_SIGNING_SECRET`, `PAPERCLIPAI_INTERNAL_URL`) are no longer used.
The Coolify app `fh3l092hvgk621zagxwg4non` is stopped with `traefik.enable=false`.
Code deleted from working tree; last commit containing it: `467c0c7`.
See `PIVOT_TO_PAPERCLIP.md` for re-enable instructions from git history.

---

## §2 Deploy steps

### First deploy (new VPS)

1. Provision VPS, add to Coolify as a server.
2. In Coolify, create a paperclipai application from the `paperclipai/paperclip` GitHub repo.
3. Set env vars from §1. Generate `BETTER_AUTH_SECRET` with `openssl rand -hex 32`.
4. Deploy paperclipai:
   ```
   git push → Coolify auto-deploy
   ```
   paperclipai bootstraps its own embedded PostgreSQL on first start. No manual migration needed.
5. Create the first admin user by visiting `https://{PAPERCLIPAI_HOSTNAME}/` and completing the
   bootstrap flow.
6. Issue the first API key for n8n (see §3 Key management).
7. Verify:
   - `curl https://{PAPERCLIPAI_HOSTNAME}/api/health` → `{"status":"ok","bootstrapStatus":"ready",...}`
   - `curl -H "Authorization: Bearer pcp_board_<token>" https://{PAPERCLIPAI_HOSTNAME}/api/health` → 200

### Redeployment (code change)

```
git push origin main
```
Coolify picks up the change and redeploys rolling. No manual steps required.

### Rollback

In Coolify UI: select the service → Deployments → redeploy previous tag.

---

## §3 Paperclip API keys

**Design:** paperclip native board API key bearer tokens. api-gateway decommissioned
2026-04-27, code deleted (last state: commit `467c0c7`).

### API key format

Keys have the prefix `pcp_board_` followed by 48 hex characters (24 random bytes).
Format: `pcp_board_<48 hex chars>`. Keys are shown exactly once at creation. Only a
SHA-256 hash is stored in the `board_api_keys` table — plaintext is never persisted.

### Current keys (2026-04-27)

| Name | ID | Scope | Purpose | Expires |
|------|-----|-------|---------|---------|
| n8n-prod | `98c90c86-8765-424a-8554-b259b98c6b34` | board (full) | n8n workflow automation | 2027-04-27 |
| paperclipai-ui | `ad0dd2b4-df7e-42f6-96d6-4e5ec3d0cfda` | board (full) | Programmatic UI-adjacent access | 2027-04-27 |
| openclaw-worker | `5893678b-c34a-47db-92de-8d16d455d78c` | board (full) | openclaw-worker polling and status updates | — |

Key **values** are stored in your secrets manager. Never in git.

### Auth flow (end-to-end)

```
Caller → paperclipai (direct, public):
  Authorization: Bearer pcp_board_<token>
  Content-Type: application/json
  { ... }
```

1. **paperclipai** auth middleware extracts the Bearer token.
2. Hashes with SHA-256 and looks up in `board_api_keys` where `revoked_at IS NULL`.
   - Not found → actor set to `none`, request continues unauthenticated (may 401 at route level).
3. Resolves the board user's company memberships and instance admin role.
4. Sets `req.actor` with `type: "board"`, company IDs, and `isInstanceAdmin` flag.
5. Route handlers call `assertBoard(req)` to enforce board-level auth.

### Key management

Keys are created directly against the embedded PostgreSQL in the paperclipai container.
See `PIVOT_TO_PAPERCLIP.md` → "How to issue more keys" for the full command.

```bash
# List existing keys (shows names and IDs, never hashes)
docker exec ihe84uqp2yr5bu9wd43w34dq-022254323882 node -e "
const { Client } = require('/app/node_modules/.pnpm/pg@8.18.0/node_modules/pg');
const c = new Client({host:'127.0.0.1',port:54329,user:'paperclip',password:'paperclip',database:'paperclip'});
c.connect().then(()=>c.query('SELECT id,name,created_at,expires_at,revoked_at FROM board_api_keys ORDER BY created_at')).then(r=>{console.log(JSON.stringify(r.rows,null,2));c.end();}).catch(e=>{console.error(e.message);c.end();});
"

# Revoke a key by ID
docker exec ihe84uqp2yr5bu9wd43w34dq-022254323882 node -e "
const { Client } = require('/app/node_modules/.pnpm/pg@8.18.0/node_modules/pg');
const c = new Client({host:'127.0.0.1',port:54329,user:'paperclip',password:'paperclip',database:'paperclip'});
c.connect().then(()=>c.query('UPDATE board_api_keys SET revoked_at=NOW() WHERE id=\$1', ['KEY-UUID-HERE'])).then(()=>{console.log('revoked');c.end();}).catch(e=>{console.error(e.message);c.end();});
"
```

Revocation takes effect immediately — the next request with the revoked key is treated as unauthenticated.

### Network topology

```
Internet → Traefik (coolify-proxy) → paperclipai (direct public route)
```

paperclipai is now the public endpoint. `api.cfpa.sekuirtek.com` returns 503 (Traefik
catch-all, no backend). DNS record preserved but no route configured.

### Provisioned keys (2026-04-27)

| Name | ID | Purpose |
|---|---|---|
| n8n-prod | `98c90c86-8765-424a-8554-b259b98c6b34` | n8n workflow automation |
| paperclipai-ui | `ad0dd2b4-df7e-42f6-96d6-4e5ec3d0cfda` | Programmatic UI-adjacent access |

Key values stored in your secrets manager. Never in git.

---

## §4 LLM Provider Configuration

### Current provider: OpenRouter

All Claude CLI invocations from the paperclipai container route through OpenRouter's
Anthropic-compatible endpoint via the `openrouter-proxy` Coolify container.

**Why a proxy?** The Claude Code CLI v2.1.119 sends `POST /v1/messages?beta=true` with
`anthropic-beta` headers containing Claude-specific beta feature flags. OpenRouter's
`/api/v1` endpoint returns 404 for the `?beta=true` suffix. The proxy strips those before
forwarding.

### How it works

```
claude CLI → ANTHROPIC_BASE_URL → http://openrouter-proxy:4001 (Coolify container)
                                           ↓
                          POST https://openrouter.ai/api/v1/messages
                          Authorization: Bearer <OPENROUTER_API_KEY>
```

The proxy (`proxy/openrouter-proxy/proxy.py` in this repo) runs as a Coolify container
(`scc2ob001qhs6d16voewfy0r`) on the `coolify` Docker network with alias `openrouter-proxy`:
- Strips `?beta=true` and Anthropic-specific headers (`anthropic-beta`, `anthropic-version`, etc.)
- Forwards only `Content-Type` and `Authorization: Bearer <key>` to OpenRouter
- Handles `GET /models/*` with a fake 200 response so the CLI doesn't abort on model lookup
- `traefik.enable=false` — internal-only, no public route

### Env vars

**paperclipai** (`ihe84uqp2yr5bu9wd43w34dq`):

| Variable | Value | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | `sk-or-v1-***` | OpenRouter API key (never commit) |
| `ANTHROPIC_BASE_URL` | `http://openrouter-proxy:4001` | Points claude CLI at the proxy |

**openrouter-proxy** (`scc2ob001qhs6d16voewfy0r`):

| Variable | Purpose |
|---|---|
| `OPENROUTER_API_KEY` | OpenRouter API key — set in Coolify, never in source |

### Proxy management

```bash
# View logs
docker logs $(docker ps -q --filter name=scc2ob001qhs6d16voewfy0r) --tail 50

# Restart
docker restart $(docker ps -q --filter name=scc2ob001qhs6d16voewfy0r)
```

To update proxy logic: edit `proxy/openrouter-proxy/proxy.py` and `git push origin main`.
Coolify auto-deploys on push.

### Swapping providers

To revert to direct Anthropic API:

1. In Coolify, on app `ihe84uqp2yr5bu9wd43w34dq`:
   - Set `ANTHROPIC_API_KEY` to your Anthropic key (`sk-ant-...`)
   - Delete or unset `ANTHROPIC_BASE_URL`
2. Restart paperclipai via Coolify.

To swap to a different OpenRouter key:

1. In Coolify, on app `scc2ob001qhs6d16voewfy0r`: update `OPENROUTER_API_KEY`.
2. Restart the proxy container.
3. Update `ANTHROPIC_API_KEY` on app `ihe84uqp2yr5bu9wd43w34dq` to the new key and restart paperclipai.

### Gotchas

**`?beta=true` / `anthropic-beta` headers:** The Claude Code CLI sends
`POST /v1/messages?beta=true` with `anthropic-beta` and `anthropic-version` request headers.
OpenRouter's `/api/v1` endpoint returns 404 on the `?beta=true` suffix and may reject the
beta headers. The proxy strips both before forwarding — this is the entire reason the proxy
exists. **If you ever swap to direct Anthropic API, remove `ANTHROPIC_BASE_URL` from all apps
that set it; don't just point it at Anthropic's base URL, as the proxy header-stripping is
not needed there and would silently break beta features.**

**Slug-vs-UUID for paperclip API access:** see §6 Known Operational Quirks. Short version:
always pass the company UUID (`bd80728d-6755-4b63-a9b9-c0e24526c820`) in API paths — never
the URL slug (`CAR`).

### OpenCode model prefix routing

The model prefix in OpenCode determines which API path is used, not just which provider:

| Prefix | API path | OpenRouter compat |
|---|---|---|
| `anthropic/` | OpenCode's Anthropic provider → Messages API | ✓ verified (`opencode-agent` runs `claude-sonnet-4-6`) |
| `opencode/` | OpenCode's preset catalog → Chat Completions | ✓ verified (`opencode-free-agent` runs `nemotron-3-super-free`) |
| `openai/` | OpenCode defers to OpenAI SDK → Responses API | ✗ broken (Codex, `gpt-4.1`, `gpt-5` all fail) |

For OpenAI capability via OpenCode + OpenRouter:
- Not currently possible. OpenCode's `openai/` prefix unconditionally uses Responses API.
- Fix would require either: OpenCode adding a chat-completions flag, OpenRouter stabilizing
  Responses API, or OpenCode exposing GPT-class models under the `opencode/` prefix.
- Workaround for OpenAI access: configure direct OpenAI account (separate billing, separate
  key — requires explicit decision before implementing).

Evidence for the broken `openai/` path (two attempts, 2026-04-28):

- **Codex CLI:** The `codex` binary hardcodes `wss://api.openai.com/v1/responses`
  (WebSocket Responses API). `OPENAI_BASE_URL` only redirects REST — WebSocket is
  hardcoded to `api.openai.com`. Exits 1 with `401 Unauthorized`.
- **OpenCode + `openai/gpt-4.1`:** Routes to `https://openrouter.ai/api/v1/responses`
  (REST Responses API). OpenRouter's impl fails with Zod validation errors on the request
  schema. Changing the model name (`gpt-4o`, `gpt-5`, etc.) does not help — the routing
  decision is made by the prefix, not the model.

**`OPENAI_BASE_URL` / `OPENAI_API_KEY` are not set on paperclipai** and must not be added
without a verified working path. `opencode-openai-agent` was deleted 2026-04-28.

### opencode-free-agent operational notes

`opencode-free-agent` (`513f5d7f-aba3-43fe-9d97-25a22fb3cc2e`) uses
`opencode/nemotron-3-super-free` — a free-tier Llama 70B model via OpenCode's preset
catalog. Verified working 2026-04-28 (CAR-13, exitCode 0, $0.00, billed via OpenRouter).

**Appropriate uses:**
- Low-stakes housekeeping: status sweeps, issue closing, comment drafts
- Triage: routing, labelling, duplicate detection
- Dev/test: validating pipeline mechanics without burning quota

**Avoid:**
- Production code execution
- Multi-step reasoning tasks or anything requiring consistent API protocol adherence
- Customer-facing output

**Quality benchmark (CAR-13 vs opencode-agent equivalent):**

| Metric | `opencode-free-agent` (nemotron) | `opencode-agent` (claude-sonnet-4-6) |
|---|---|---|
| Steps to complete "echo a string" | ~15 | ~3–5 |
| API call errors before success | 3 (validation + checkout conflict) | 0 |
| Total tokens billed | 312K input cumulative | ~50–80K estimated |
| Cost | $0.00 | ~$0.08 |
| Cache hits | 0 | Benefits from caching |

The model recovers from errors correctly — it's not unreliable, it's verbose. For zero-cost
housekeeping where a 2-minute runtime is acceptable, it's a valid option.

### Cost expectations

- OpenRouter markup: ~5% over Anthropic list pricing
- Benefit: single key, multi-model routing for Anthropic and `opencode/` preset models
- OpenRouter model names use `anthropic/claude-sonnet-4.6` format; the proxy uses
  `claude-sonnet-4-6` (Anthropic short form) because it strips the `anthropic-beta` headers
  that break OpenRouter routing, and OpenRouter accepts short model names in `/messages`.

---

## §5 openclaw-worker

Long-running worker container that polls paperclip for `todo` issues assigned to the
`openclaw-agent` agent, executes each via OpenClaw's embedded agent, and reports
results back. Source: `workers/openclaw-worker/` in this repo.

### Coolify app

| Field | Value |
|---|---|
| App UUID | `v3b2daw5wvaval2r6sb6mrxn` |
| Source | `a-desanto/control-plane`, branch `main`, base `/workers/openclaw-worker` |
| Network | `coolify` (shares Docker network with `paperclipai` and `openrouter-proxy`) |
| Public domain | None (`traefik.enable=false`) |

### Env vars (set in Coolify on app `v3b2daw5wvaval2r6sb6mrxn`)

| Variable | Value |
|---|---|
| `PAPERCLIP_API_URL` | `https://paperclipai.cfpa.sekuirtek.com` |
| `PAPERCLIP_COMPANY_ID` | `bd80728d-6755-4b63-a9b9-c0e24526c820` |
| `PAPERCLIP_AGENT_ID` | `e3e191c3-b7d4-4d2d-bfe4-2709db3b76a2` |
| `PAPERCLIP_API_KEY` | `pcp_board_f0d3***` (never commit — key id `5893678b-c34a-47db-92de-8d16d455d78c`) |
| `OPENROUTER_API_KEY` | OpenRouter key (never commit) |
| `ANTHROPIC_BASE_URL` | `http://openrouter-proxy:4001` |
| `OPENCLAW_AGENT_PROFILE` | `executor` |
| `WORKING_DIR_BASE` | `/workspace` |
| `TASK_TIMEOUT_SECONDS` | `1800` |

### Observability

```bash
docker logs $(docker ps -q --filter name=v3b2daw5wvaval2r6sb6mrxn) -f
```

### Update worker logic

Edit `workers/openclaw-worker/src/worker.py` and `git push origin main`. Coolify auto-deploys.

---

## §6 Known Operational Quirks

### Agent rename history

`Code Execution Worker` → `openclaw-agent` on 2026-04-28. UUID `e3e191c3-b7d4-4d2d-bfe4-2709db3b76a2` unchanged. Worker container `PAPERCLIP_AGENT_ID` env var was unaffected.

### "User does not have access to this company" — slug vs UUID

paperclip's URL shows the company's `issue_prefix` (e.g. `CAR`), not its UUID. The REST API
`assertCompanyAccess` compares against UUID-based `companyIds` on the actor. Passing the
`issue_prefix` as the company ID will always return this error even when the user has valid
membership.

**Fix:** always use the UUID in `PAPERCLIP_COMPANY_ID` and all API paths.

| Field | Correct value |
|---|---|
| "Caring First" company UUID | `bd80728d-6755-4b63-a9b9-c0e24526c820` |
| URL slug (`issuePrefix`) | `CAR` — visible in browser URL, not usable as API path segment |

### OpenClaw workspace vs. worker working directory

`openclaw-worker` sets `cwd` to `/workspace/{issueId}` when invoking OpenClaw.
OpenClaw itself maintains its own internal workspace at
`/root/.openclaw/workspace-executor/` (configured in `openclaw.json`). These are different:

- `/workspace/{issueId}` — the repo clone directory; this is what the agent's `bash`, `read`,
  `edit`, `write` tools operate on (OpenClaw uses the process cwd as the root).
- `/root/.openclaw/workspace-executor/` — OpenClaw's session state directory.

If you exec into the container and don't see files where you expect them, check both paths.
The worker deletes `/workspace/{issueId}` after each task (`shutil.rmtree` in `finally`).

To look up company UUID from the embedded DB:
```bash
docker exec ihe84uqp2yr5bu9wd43w34dq-* node -e "
const { Client } = require('/app/node_modules/.pnpm/pg@8.18.0/node_modules/pg');
const c = new Client({host:'127.0.0.1',port:54329,user:'paperclip',password:'paperclip',database:'paperclip'});
c.connect().then(()=>c.query('SELECT id, name, issue_prefix FROM companies')).then(r=>{console.log(JSON.stringify(r.rows,null,2));c.end();}).catch(e=>{console.error(e.message);c.end();});
"
```

### Failed agent runs may be auto-closed by the CEO heartbeat

When a native adapter agent's heartbeat run fails (exitCode 1), paperclip does not
automatically move the issue to `blocked`. Instead, the CEO agent's heartbeat scan may
survey the issue queue, determine the issue is unresolvable in its current state, and PATCH
it to `done` — even though the adapter never successfully executed.

**Observed:** Phase 3C smoke test issue CAR-7 (`codex-agent`) was marked `done` despite
four consecutive failed heartbeat runs (all `401 Unauthorized`). The CEO's heartbeat run
at 02:10:52 UTC cost $0.62 and closed the issue.

**Implications:**
- `status=done` does NOT guarantee an adapter ran. Check `executionRunId` and the heartbeat
  run's `exitCode` if you need to verify actual execution.
- The CEO closing issues adds unexpected LLM cost when adapters are misconfigured. Fix the
  adapter first, not after noticing cost on the OpenRouter dashboard.
- To prevent CEO interference while debugging an adapter: temporarily turn off heartbeat on
  the CEO agent in paperclip's UI.

---

## §6 Disaster recovery

### Backup runner

Container `cfpa-backup-runner` runs `backup.sh` daily at 03:00 UTC. Dumps all 8 Postgres
instances in `-Fc` format to `r2:cfpa-backups/daily/YYYY-MM-DD/`. Retention: 7 daily,
4 weekly (Sundays), 3 monthly (1st of month).

**Check backup health:**
```bash
docker logs cfpa-backup-runner --tail 20
# healthcheck at https://hc-ping.com (check hc-ping.com dashboard for last ping)
```

**Manual run:**
```bash
docker exec cfpa-backup-runner /usr/local/bin/backup.sh
```

**Container restart after VPS reboot:** handled by `--restart always` on the Docker container.

**After a Coolify redeploy of odoo-r147, odoo-qa3, or gwsw** (these live on isolated service
networks), re-run the network connect commands:
```bash
docker network connect coolify postgresql-r147p2dhkmafaco58b5boxwo
docker network connect coolify postgresql-qa3ernlh747z79f6o5wpmoem
docker network connect coolify postgresql-gwsw0wcc0co44088swwgkooc
```

**After any paperclip redeploy**, verify port 54329 is still network-accessible:
```bash
docker exec cfpa-backup-runner pg_isready -h paperclip -p 54329
```
If it fails: paperclip's `postgresql.conf` and `pg_hba.conf` may have been regenerated from
defaults (blank listen_addresses). Re-apply the settings in
`/paperclip/instances/default/db/` and restart paperclip. See §6.1 below.

### §6.1 Re-applying paperclip Postgres network access

paperclip's embedded Postgres must be configured to accept Docker-network connections:

1. Edit `/paperclip/instances/default/db/postgresql.conf` — ensure this line is active (not commented):
   ```
   listen_addresses = '*'
   ```
2. Edit `/paperclip/instances/default/db/pg_hba.conf` — add after the IPv4 local block:
   ```
   # Docker coolify network (backup runner):
   host    all             all             10.0.1.0/24             password
   ```
3. Fix file ownership (the postgres process runs as UID 1000 / `ubuntu` on host):
   ```bash
   chown ubuntu:ubuntu /paperclip/instances/default/db/postgresql.conf \
                       /paperclip/instances/default/db/pg_hba.conf
   ```
4. `docker restart <paperclip-container-id>` (brief ~5s downtime).

### §6.2 Restore procedure

```bash
# Download a dump from R2 (using the backup runner):
docker exec cfpa-backup-runner rclone copy \
  r2:cfpa-backups/daily/YYYY-MM-DD/paperclip.pgdump /tmp/

# Create throwaway DB and restore:
docker exec cfpa-backup-runner sh -c "
  PGPASSWORD=\$PAPERCLIP_PG_PASSWORD psql -h paperclip -p 54329 -U paperclip paperclip \
    -c 'CREATE DATABASE restore_test;'
  docker cp cfpa-backup-runner:/tmp/paperclip.pgdump /tmp/restore.pgdump
"
# (then pg_restore as shown in backups/runner/README.md)

# Verify row counts match production before promoting.
# Drop throwaway: DROP DATABASE restore_test;
```

Restore is tested — Phase 4 smoke test (2026-04-29) confirmed full paperclip dump
restores cleanly with correct row counts (1156 heartbeat_run_events, 13 issues, etc.).

---

## §7 Day-1 hardening

Configured 2026-04-29. Both items are live and verified.

### §7.1 Coolify Discord notifications

Discord webhook configured for team_id=0 in `discord_notification_settings` (coolify-db).
The webhook URL is stored Laravel-encrypted (AES-256-CBC) — it is NOT in this repo.

**Enabled triggers:**

| Event | Column | Notes |
|---|---|---|
| Deployment success | `deployment_success_discord_notifications` | Verified: message received in Discord |
| Deployment failure | `deployment_failure_discord_notifications` | |
| Container stopped / restarted | `status_change_discord_notifications` | Maps to `ContainerStopped` + `ContainerRestarted` |
| Server unreachable | `server_unreachable_discord_notifications` | |
| Scheduled task failure | `scheduled_task_failure_discord_notifications` | |

**To change webhook URL** (e.g. rotating the Discord webhook):
```bash
docker exec -i coolify php artisan tinker --no-interaction << TINKER
\$s = \App\Models\DiscordNotificationSettings::where('team_id', 0)->first();
\$s->discord_webhook_url = 'https://discord.com/api/webhooks/NEW_URL';
\$s->save();
echo strlen(\$s->discord_webhook_url) . "\n";
TINKER
```
Must use the Eloquent model — direct SQL will store plaintext which Coolify cannot decrypt.

**To disable all Discord notifications:**
```bash
docker exec coolify-db psql -U coolify -d coolify -c \
  "UPDATE discord_notification_settings SET discord_enabled = false WHERE team_id = 0;"
```

### §7.2 paperclip local backup rotation

Coolify scheduled task `paperclip-local-backup-cleanup` (UUID: `tql16206jv2no4mqhavrnihg`) runs at `0 4 * * *` UTC inside the paperclipai container:

```
find /paperclip/instances/default/data/backups -name '*.sql.gz' -mtime +1 -delete
```

paperclip writes hourly `.sql.gz` snapshots. The task keeps only the most recent ~24h of local files; anything older is deleted. Off-VPS coverage (the canonical source for older data) is provided by `cfpa-backup-runner` at 03:00 UTC (§6).

**One-time recovery (2026-04-29):** 120 files deleted, 391 MB freed (406 MB → 15 MB).
**Going forward:** ~24 files/day accumulate, pruned daily — net disk impact near zero.

**To verify task history:**
```bash
# Via Coolify API:
curl -sf -H "Authorization: Bearer <token>" \
  http://localhost:8000/api/v1/applications/ihe84uqp2yr5bu9wd43w34dq/scheduled-tasks/tql16206jv2no4mqhavrnihg/executions

# Or check directly:
docker exec ihe84uqp2yr5bu9wd43w34dq-103207382226 \
  find /paperclip/instances/default/data/backups -name '*.sql.gz' | wc -l
```

---

## §8 Watchdog and kill-switch

Container `cfpa-watchdog` (source: `workers/cfpa-watchdog/`) polls paperclip's cost API every
60 seconds. If any agent's rolling-window spend exceeds a threshold it pauses the agent
immediately and fires a Discord alert. The pause is manual-resume-only — the watchdog never
auto-resumes.

### What it does

Each cycle the watchdog:
1. Fetches all non-paused, non-terminated agents.
2. Queries `GET /api/companies/:id/costs/by-agent?from=ISO&to=ISO` for three rolling windows
   simultaneously (1 min, 5 min, 60 min). This endpoint returns **true windowed spend** —
   verified 2026-04-29 (Phase 4): `opencode-agent` had $3.58 in the 60-minute window and
   triggered immediately; the query is not lifetime spend.
3. Checks each agent against per-window thresholds. On first breach:
   - `POST /api/agents/:id/pause`
   - Posts Discord alert (see format below)
   - Marks agent in in-memory set; skips it for remaining cycles until restart
4. Pings healthchecks.io so you know the watchdog process itself is alive.

### Default thresholds

| Window | Env var | Default | Pre-2026-04-30 |
|--------|---------|---------|----------------|
| 1 minute | `PER_MINUTE_MAX_USD` | $1.00 | $1.00 |
| 5 minutes | `PER_5MIN_MAX_USD` | $3.00 | $3.00 |
| 60 minutes | `PER_HOUR_MAX_USD` | **$1.00** | $8.00 |

**The 60-minute default was tightened from $8.00 to $1.00 on 2026-04-30** after a cost-runaway incident in which idle agents bled $31.30/month at ~$0.34/hour — well below the prior $8/hour threshold so the watchdog never fired. The new default catches a slow drip; the per-window 5-min and 1-min thresholds remain the same since they were already adequate for burst protection. See "Per-agent threshold overrides" below for the matching idle-agent overrides.

### Per-agent threshold overrides

Two patterns:

**Pattern A — raise limits for agents that legitimately spend more** (e.g. CEO during planning week):

```bash
WATCHDOG_AGENT_<UUID>_PER_HOUR_MAX_USD=20
WATCHDOG_AGENT_<UUID>_PER_5MIN_MAX_USD=10
WATCHDOG_AGENT_<UUID>_PER_MINUTE_MAX_USD=5
```

**Pattern B — lower limits for agents that should currently spend nothing** (idle by design — most common at onboarding when only one or two agents are active):

```bash
WATCHDOG_AGENT_<UUID>_PER_HOUR_MAX_USD=0.10
```

Production overrides on the canonical VPS as of 2026-04-30 (Pattern B):

| Agent | UUID | Per-hour cap |
|-------|------|--------------|
| CEO | `535d320c-8eef-4f2c-a3b9-9d94c2f99793` | $0.10 |
| Operator | `b512de5c-ea5a-4146-8aaa-750bba2846c7` | $0.10 |
| openclaw-agent | `e3e191c3-b7d4-4d2d-bfe4-2709db3b76a2` | $0.10 |
| opencode-free-agent | `513f5d7f-aba3-43fe-9d97-25a22fb3cc2e` | $0.10 |
| opencode-agent | `0930e444-c1f1-43ee-9b10-98e67b3daa44` | (global $1.00 default — may do real work) |

All three suffixes (`PER_MINUTE_MAX_USD`, `PER_5MIN_MAX_USD`, `PER_HOUR_MAX_USD`) are supported. Unset suffixes fall back to the global defaults. Override takes effect on the next cycle after container restart.

### Discord alert format

```
🚨 **Agent paused by watchdog**
**Agent:** opencode-agent (`0930e444-c1f1-43ee-9b10-98e67b3daa44`)
**Threshold breached:** $0.10 per 1 hour
**Actual spend:** $3.5800 in last 1 hour
**Next step:** Investigate in paperclip, then resume via `POST /api/agents/0930e444.../resume` or the UI.
```

### Re-enabling a watchdog-paused agent

1. Investigate the cause in paperclip's heartbeat run log.
2. Resume: `POST /api/agents/<id>/resume` (board auth) or via paperclip UI.
3. The watchdog respects the resumed state — it does not re-pause until a new threshold breach.
4. If the watchdog is still running (not restarted), the in-memory `_paused_by_watchdog` dict
   retains the entry until the watchdog detects the agent in the active list on the next cycle,
   at which point it logs `agent_manually_resumed` and removes it from the dict.

### Raising a threshold without redeploying

The thresholds are read from env vars at startup. To change them you must restart the container:

```bash
docker rm -f cfpa-watchdog && docker run -d \
  --name cfpa-watchdog \
  --restart always \
  --network coolify \
  -e PAPERCLIP_API_URL=https://paperclipai.cfpa.sekuirtek.com \
  -e PAPERCLIP_API_KEY=<key — stored in your secrets manager, never commit> \
  -e PAPERCLIP_COMPANY_ID=bd80728d-6755-4b63-a9b9-c0e24526c820 \
  -e DISCORD_WEBHOOK_URL=<webhook — stored in your secrets manager> \
  -e HEALTHCHECK_PING_URL=https://hc-ping.com/16de3dc6-a900-4609-bbaa-230a500ea19b \
  -e PER_HOUR_MAX_USD=20.00 \
  cfpa-watchdog:latest
```

### Disabling the watchdog entirely

```bash
docker stop cfpa-watchdog
```

The container has `--restart always`, so stopping it is temporary (it restarts on next VPS
boot). To permanently disable: `docker rm -f cfpa-watchdog`. Recreate from the command above.

### Observability

```bash
# Live logs (structured JSON, one line per event):
docker logs cfpa-watchdog -f

# Last cycle summary:
docker logs cfpa-watchdog 2>&1 | grep cycle_complete | tail -1

# All threshold breaches:
docker logs cfpa-watchdog 2>&1 | grep threshold_breached
```

Healthcheck: https://hc-ping.com/16de3dc6-a900-4609-bbaa-230a500ea19b
(schedule `*/1 * * * *`, grace 5 min — pings every 60s on a clean cycle)

### Restart behaviour

On restart the watchdog does a startup scan of all agents and logs how many are already paused,
but it does NOT add pre-paused agents to its in-memory set. This is intentional: if the
watchdog was the one that paused them before the restart, a human should have reviewed and
resumed them. Agents left paused across a watchdog restart require explicit manual review.

### API key

The watchdog uses board key `cfpa-watchdog` (key ID `051066b3-98c9-4e84-b4be-74562d2b1d75`,
user ID `5iqq34wPV9id6soJWlrBsTY2eWMsQaHk`). Key value stored in your secrets manager —
never in git. To revoke:

```bash
docker exec <paperclip-container> node -e "
const { Client } = require('/app/node_modules/.pnpm/pg@8.18.0/node_modules/pg');
const c = new Client({host:'127.0.0.1',port:54329,user:'paperclip',password:'paperclip',database:'paperclip'});
c.connect()
  .then(() => c.query('UPDATE board_api_keys SET revoked_at=NOW() WHERE id=\$1',
                       ['051066b3-98c9-4e84-b4be-74562d2b1d75']))
  .then(() => { console.log('revoked'); c.end(); })
  .catch(e => { console.error(e.message); c.end(); });
"
```

### Phase 4 verification summary (2026-04-29)

**Scenario fired:** Windowed spend — real data, no synthetic issue needed.

- `opencode-agent` had **$3.58** in the 60-minute window (real prior spend).
- Triggered on the **first cycle** at `PER_HOUR_MAX_USD=0.10`.
- Agent paused, Discord alert delivered, healthcheck pinged.
- Thresholds reset to defaults; agent resumed via API.
- Next cycle: all 5 agents active, 0 paused — watchdog did not re-pause.

**Key finding:** `costs/by-agent` returns genuine rolling-window spend, not lifetime totals.
The 60-minute threshold is the most likely to trigger in practice for a busy agent. The
1-minute and 5-minute thresholds guard against sudden bursts (e.g. a runaway loop).

---

## §9 paperclip-mcp

paperclip-mcp is a FastMCP server that wraps the paperclipai board API and exposes it as 21 MCP tools to Claude CLI and any other MCP client.

**Coolify app UUID:** `p13q05uj5ehqi866jp27g6fg`
**Source:** `a-desanto/control-plane`, branch `main`, base dir `/mcp-servers/paperclip-mcp`, build pack: Dockerfile
**Port:** 9011 (mapped to host, `traefik.enable=false`)
**MCP endpoint:** `http://127.0.0.1:9011/mcp`
**Transport:** streamable-http (MCP 2024-11-05)

### Environment variables

| Variable | Value | Notes |
|---|---|---|
| `PAPERCLIP_BASE_URL` | `https://paperclipai.cfpa.sekuirtek.com/api` | External URL — internal Docker alias blocked by allowlist |
| `PAPERCLIP_API_KEY` | `pcp_board_...` | Scoped key named `paperclip-mcp-operator`, 1-year expiry |
| `PAPERCLIP_COMPANY_ID` | `bd80728d-6755-4b63-a9b9-c0e24526c820` | The active company ID |

### Registering with Claude CLI

```bash
claude mcp add paperclip --transport http "http://127.0.0.1:9011/mcp"
```

Run from the `/root/control-plane` directory (or any project where you want access).

### Available tools (21)

`list_issues`, `get_issue`, `create_issue`, `update_issue`, `checkout_issue`, `release_issue`, `comment_on_issue`, `delete_issue`, `list_agents`, `get_agent`, `invoke_agent_heartbeat`, `list_goals`, `create_goal`, `update_goal`, `list_approvals`, `approve`, `reject`, `request_approval_revision`, `get_cost_summary`, `get_dashboard`, `list_activity`

### Rebuilding

If you need to rebuild the image (e.g., after a new release of `paperclip-mcp` upstream):

```bash
# In Coolify UI: paperclip-mcp → Deployments → Deploy
# Or via API:
curl -X POST -H "Authorization: Bearer <coolify-token>" \
  http://localhost:8000/api/v1/applications/p13q05uj5ehqi866jp27g6fg/start
```

### Verification

```bash
# Quick tools/list check (requires session handshake)
INIT=$(curl -s -X POST http://127.0.0.1:9011/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}' \
  -D /tmp/mcp_h.txt)
SID=$(grep -i 'mcp-session-id' /tmp/mcp_h.txt | awk '{print $2}' | tr -d '\r\n')
curl -s -X POST http://127.0.0.1:9011/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "mcp-session-id: $SID" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'
```
