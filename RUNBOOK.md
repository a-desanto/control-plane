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

### Anti-pattern: OpenAI models via OpenCode through OpenRouter

**Do not attempt this.** Two attempts, two structural failures at different layers.

**Failure 1 — Codex CLI (2026-04-28):**
The `codex` binary (v0.125.0) uses OpenAI's Responses API exclusively via WebSocket
(`wss://api.openai.com/v1/responses`). `OPENAI_BASE_URL` only redirects REST calls —
WebSocket connections are hardcoded to `api.openai.com`. OpenRouter does not implement
the Responses API WebSocket protocol. Every heartbeat exits 1 with:
```
401 Unauthorized: Missing bearer or basic authentication in header
url: https://api.openai.com/v1/responses
```

**Failure 2 — OpenCode CLI with `openai/gpt-4.1` (2026-04-28):**
OpenCode routes all `openai/*` models to OpenRouter's REST Responses API endpoint
(`POST https://openrouter.ai/api/v1/responses`). OpenRouter's Responses API
implementation is unstable — the request fails with Zod validation errors:
```
{"error":{"code":"invalid_prompt","message":"Invalid Responses API request"},
 "metadata":{"url":"https://openrouter.ai/api/v1/responses"}}
```
The Chat Completions path (`/api/v1/chat/completions`), which OpenRouter implements
stably, is **never taken** for `openai/*` models in OpenCode. Model selection
(`gpt-4.1`, `gpt-4o`, `gpt-5`, etc.) does not change this — all `openai/*` models
hit the same broken path.

**Root cause:** OpenCode's `openai` provider hardcodes the Responses API. The `opencode/`
prefix models (e.g. `opencode/nemotron-3-super-free`) use a different internal path that
goes through Chat Completions and does work via OpenRouter.

**Confirmed working via OpenRouter:** `anthropic/*` models (claude-sonnet-4-6, etc.)
and `opencode/*` preset models.

**If OpenAI capability becomes truly required:**
- Wait for OpenRouter to stabilize Responses API parity, OR
- Wait for OpenCode to support a `--provider chat-completions` flag or equivalent, OR
- Accept a separate direct OpenAI account (two billing dashboards, two keys, two
  rotation procedures per VPS) — requires explicit decision before implementing.

**OPENAI_BASE_URL / OPENAI_API_KEY** are not set on paperclipai and must not be added
without a verified working path. `opencode-openai-agent` was deleted 2026-04-28.

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
