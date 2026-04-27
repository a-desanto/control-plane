# Pivot to Paperclip

**Date:** 2026-04-26

---

## Phase 1 — paperclip-backend decommissioned (2026-04-26)

`paperclip-backend` — the custom FastAPI service built during Phases 0–2B of this project
(Coolify application `kz9wfv4by3aggvz1eaw2kol4`).

The container has been stopped and left in `exited:unhealthy` state. The Postgres database
(`paperclip-backend-db`) and all Coolify configuration have been preserved; nothing was deleted.

## Phase 2 — api-gateway decommissioned (2026-04-27)

`api-gateway` — the FastAPI edge router that validated HMAC-signed claims before forwarding
to paperclipai (Coolify application `fh3l092hvgk621zagxwg4non`).

The container has been stopped. `traefik.enable=false` has been set on the Coolify app so
that even a manual restart does not advertise the Traefik route. The Coolify app record and
image are preserved.

**Why decommissioned:** paperclipai handles its own auth via board API keys (`pcp_board_*`
tokens, SHA-256 hashed in `board_api_keys` table). The HMAC claim-signing layer api-gateway
provided is redundant now that callers authenticate directly to paperclipai.

**Code deleted** in this repo (PR #5, commit 467c0c7 is the last state containing it). To
re-deploy from git history: `git checkout 467c0c7 -- api-gateway/`, then deploy as a
Coolify app pointing at that directory. Remove `traefik.enable=false` from the app's
custom labels before deploying.

---

## Why

The orchestration brain we were building in phases already exists as a production product:
**paperclipai** (`paperclipai/paperclip` on GitHub), a Node.js/Express application already
deployed to this cluster at `https://paperclipai.cfpa.sekuirtek.com`. Continuing to develop
a parallel FastAPI backend duplicates effort and creates maintenance risk. The pivot consolidates
routing through the existing product.

---

## Current architecture

```
Caller (n8n, UI, etc.)
  │  Authorization: Bearer pcp_board_<token>
  │
  └─► Coolify Traefik (coolify-proxy)
           │
           └─► paperclipai  (https://paperclipai.cfpa.sekuirtek.com)
                   │  Node.js/Express, deploymentMode=authenticated
                   │  Embedded PostgreSQL (port 54329 inside container)
                   │
                   └─► /api/health, /api/companies/{id}/issues, …
```

`api.cfpa.sekuirtek.com` DNS record is preserved but returns `503 no available server`
(Traefik catch-all). No action needed on DNS.

---

## Coolify application IDs

| Service | UUID | Status |
|---|---|---|
| paperclipai | `ihe84uqp2yr5bu9wd43w34dq` | running |
| api-gateway | `fh3l092hvgk621zagxwg4non` | stopped (traefik.enable=false) |
| paperclip-backend | `kz9wfv4by3aggvz1eaw2kol4` | stopped |

---

## API keys

paperclipai uses board API keys (`pcp_board_*` prefix). Keys are stored SHA-256 hashed in
the `board_api_keys` table of the embedded PostgreSQL instance inside the container.

| Key name | ID | Scope | Tied to user | Created | Expires |
|---|---|---|---|---|---|
| n8n-prod | `98c90c86-8765-424a-8554-b259b98c6b34` | board (full) | a.desanto@sekuirtek.com | 2026-04-27 | 2027-04-27 |
| paperclipai-ui | `ad0dd2b4-df7e-42f6-96d6-4e5ec3d0cfda` | board (full) | a.desanto@sekuirtek.com | 2026-04-27 | 2027-04-27 |

**Note:** `paperclipai-ui` was provisioned for completeness. The HTML UI uses browser
sessions (better-auth cookies) for its own calls; this key is for programmatic UI-adjacent
automation if needed.

**Key values are NOT stored here.** They were displayed once at creation and must be stored
in your secrets manager (n8n credential store, vault, etc.).

### How to issue more keys

Connect to the container and run:

```bash
docker exec ihe84uqp2yr5bu9wd43w34dq-022254323882 node -e "
const crypto = require('crypto');
const { Client } = require('/app/node_modules/.pnpm/pg@8.18.0/node_modules/pg');
const token = 'pcp_board_' + crypto.randomBytes(24).toString('hex');
const hash = crypto.createHash('sha256').update(token).digest('hex');
const userId = '5iqq34wPV9id6soJWlrBsTY2eWMsQaHk';
const name = 'YOUR-KEY-NAME';
const expiresAt = new Date(Date.now() + 365 * 24 * 60 * 60 * 1000);
const c = new Client({host:'127.0.0.1',port:54329,user:'paperclip',password:'paperclip',database:'paperclip'});
c.connect()
  .then(() => c.query('INSERT INTO board_api_keys (user_id, name, key_hash, expires_at) VALUES (\$1, \$2, \$3, \$4) RETURNING id', [userId, name, hash, expiresAt]))
  .then(r => { console.log('Created key id:', r.rows[0].id); console.log('Token (save now):', token); return c.end(); })
  .catch(e => { console.error(e.message); c.end(); });
"
```

Replace `YOUR-KEY-NAME` and copy the displayed token immediately — it is never stored in plaintext.

---

## Verification (2026-04-27)

```
# paperclipai UI → 200
curl -i https://paperclipai.cfpa.sekuirtek.com/
# → HTTP/2 200, x-powered-by: Express

# paperclipai health → 200
curl -i https://paperclipai.cfpa.sekuirtek.com/api/health
# → {"status":"ok","deploymentMode":"authenticated","bootstrapStatus":"ready",...}

# api.* domain → 503 (no route, Traefik catch-all)
curl -i https://api.cfpa.sekuirtek.com/
# → HTTP/2 503, "no available server"
```
