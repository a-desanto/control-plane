# RUNBOOK.md — per-VPS operations

Companion to `ARCHITECTURE.md` and `BUILD_BRIEF.md`. Covers deployment, env vars, and operational procedures for the per-client VPS stack.

---

## §1 Environment variables

### api-gateway

| Variable | Required | Default | Notes |
|---|---|---|---|
| `API_GATEWAY_DATABASE_URL` | Yes | — | `postgresql+asyncpg://user:pass@host:5432/api_gateway` |
| `API_GATEWAY_REDIS_URL` | Yes | — | `redis://redis:6379/0` |
| `API_GATEWAY_SIGNING_SECRET` | Yes | — | Shared HMAC secret with paperclipai. Min 32 chars, random. **Never commit.** |
| `PAPERCLIPAI_INTERNAL_URL` | Yes | `http://paperclipai:8000` | Internal Docker network URL for paperclipai |

### paperclipai

| Variable | Required | Default | Notes |
|---|---|---|---|
| `DATABASE_URL` | Yes | — | `postgresql+asyncpg://user:pass@host:5432/paperclipai` |
| `API_GATEWAY_SIGNING_SECRET` | Yes | — | Must match the value set on api-gateway |
| `BASE_URL` | Yes | `http://localhost:8000` | Public-facing URL; used to build `audit_link`, `events_url`, `status_url` in 202 responses |
| `BYPASS_CLAIMS_CHECK` | Dev/test only | unset | Set to `1` to skip HMAC verification when running paperclipai without api-gateway (local dev, unit tests). **Never set in production.** |

### Traefik (Coolify labels)

| Label | Service | Value |
|---|---|---|
| `traefik.http.routers.api-gateway.rule` | api-gateway | `Host(\`{API_GATEWAY_HOSTNAME}\`)` |
| `traefik.http.routers.paperclipai.middlewares` | paperclipai | `allowlist-internal-only` |

`allowlist-internal-only` is a Traefik middleware that restricts source IPs to the Docker internal network. This ensures paperclipai is unreachable from the public internet — all public traffic must enter through api-gateway.

---

## §2 Deploy steps

### First deploy (new VPS)

1. Provision VPS, add to Coolify as a server.
2. Create two Postgres databases: `api_gateway` and `paperclipai`.
3. Create a Redis instance (Coolify-managed).
4. In Coolify, set all env vars from §1 for both services. Generate `API_GATEWAY_SIGNING_SECRET` with `openssl rand -hex 32`.
5. Deploy api-gateway:
   ```
   git push → Coolify auto-deploy from control-plane/api-gateway/
   ```
6. Deploy paperclipai:
   ```
   git push → Coolify auto-deploy from control-plane/paperclipai/
   ```
7. Run Alembic migrations for both services (Coolify release command or manual):
   ```
   # api-gateway
   uv run alembic upgrade head

   # paperclipai
   uv run alembic upgrade head
   ```
8. Seed the first API key for n8n using the CLI:
   ```
   python -m app.cli create-key \
     --app-id n8n-prod \
     --caller-type n8n \
     --capabilities qualify_and_respond \
     --budget-pool default \
     --rate 60
   ```
   Copy the displayed key into n8n's credential store immediately.
9. Verify routing:
   - `curl https://{API_GATEWAY_HOSTNAME}/health` → `{"status": "ok"}`
   - `curl https://{PAPERCLIPAI_HOSTNAME}/health` → blocked (connection refused or 403)
   - `curl https://{API_GATEWAY_HOSTNAME}/intent -H "Authorization: Bearer <key>" -d '...'` → 202

### Redeployment (code change)

```
git push origin main
```
Coolify picks up the change and redeploys rolling. No manual steps required.

### Rollback

In Coolify UI: select the service → Deployments → redeploy previous tag.

---

## §3 Auth mechanism

**Design:** API key bearer tokens with HMAC-signed claims forwarding.

### API key format

Keys are generated as `agk_` followed by 64 hex characters (32 random bytes). They are shown exactly once on creation. Only a bcrypt hash is stored in the `api_keys` table — plaintext is never persisted.

### Auth flow (end-to-end)

```
Client → api-gateway:
  Authorization: Bearer agk_<token>
  Content-Type: application/json
  { "caller_type": "n8n", ... }
```

1. **api-gateway** hashes the bearer token with bcrypt and looks it up in `api_keys`.
   - Not found or `revoked_at` is set → 401.
2. **api-gateway** validates that the body's `caller_type` matches the key's stored `caller_type` claim.
   - Mismatch → 400. The key's claim wins; a mismatch indicates a misconfigured caller.
3. **api-gateway** checks a fixed-window Redis rate limit keyed by `app_id`.
   - Exceeded → 429 with `Retry-After` header.
4. **api-gateway** builds signed claims headers:
   ```
   X-Caller-Type: n8n
   X-App-Id: n8n-prod
   X-Capabilities: <base64(["qualify_and_respond"])>
   X-Budget-Pool: default
   X-Claims-Signature: <HMAC-SHA256(canonical, API_GATEWAY_SIGNING_SECRET)>
   ```
   Canonical string: `{X-Caller-Type}|{X-App-Id}|{X-Capabilities}|{X-Budget-Pool}`
5. **api-gateway** strips the original `Authorization` header and forwards the request to paperclipai's internal URL with the signed headers.

```
api-gateway → paperclipai (internal Docker network only):
  X-Caller-Type: n8n
  X-App-Id: n8n-prod
  X-Capabilities: <base64 JSON>
  X-Budget-Pool: default
  X-Claims-Signature: <hex>
  Content-Type: application/json
  { "caller_type": "n8n", ... }
```

6. **paperclipai** (`ClaimsVerificationMiddleware`) verifies `X-Claims-Signature` against the four claim headers using the shared `API_GATEWAY_SIGNING_SECRET`.
   - Missing or invalid → 401. Request is rejected before any handler runs.
7. **paperclipai** sets `request.state.caller_type` from `X-Caller-Type`. The intent handler uses this as the authoritative value for persistence.

### Key management

```bash
# Create key
python -m app.cli create-key --app-id myapp --caller-type client_app \
  --capabilities read_status,qualify --budget-pool default --rate 120

# List keys (shows prefix only, never hash)
python -m app.cli list-keys

# Revoke key
python -m app.cli revoke-key --key-id 01HX...
```

Revocation takes effect immediately — the next request with the revoked key returns 401.

### Network topology

```
Internet → Traefik (coolify-proxy) → api-gateway (public route)
                                    ↓ internal Docker network
                                 paperclipai (internal-only route)
```

paperclipai's Traefik router is labeled with `allowlist-internal-only` middleware. Direct public requests to `{PAPERCLIPAI_HOSTNAME}` are blocked at the proxy layer. The only path from the internet to paperclipai is through api-gateway.

### Open questions resolved

- **Auth mechanism:** API key bearer + HMAC claim signing (this document).
- **Key storage:** bcrypt hash in `api_gateway.api_keys` table.
- **Coolify env vars:** `API_GATEWAY_SIGNING_SECRET` set per-VPS in Coolify's environment config. Never committed to git.
- **BASE_URL per-VPS:** set as `BASE_URL` Coolify env var on the paperclipai service.

Previously recorded as TBD in `PHASE_1_NOTES.md` — now definitive.
