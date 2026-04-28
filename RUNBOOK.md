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

## §3 Auth mechanism

**Design:** paperclip native board API key bearer tokens. api-gateway decommissioned
2026-04-27, code deleted (last state: commit `467c0c7`).

### API key format

Keys have the prefix `pcp_board_` followed by 48 hex characters (24 random bytes).
Format: `pcp_board_<48 hex chars>`. Keys are shown exactly once at creation. Only a
SHA-256 hash is stored in the `board_api_keys` table — plaintext is never persisted.

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

### Cost expectations

- OpenRouter markup: ~5% over Anthropic list pricing
- Benefit: single key, multi-provider fallback, routing flexibility (can add `openai/gpt-*`
  or `google/gemini-*` agents without separate accounts)
- OpenRouter model names use `anthropic/claude-sonnet-4.6` format; the proxy uses
  `claude-sonnet-4-6` (Anthropic short form) because it strips the `anthropic-beta` headers
  that break OpenRouter routing, and OpenRouter accepts short model names in `/messages`.
