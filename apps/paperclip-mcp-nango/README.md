# paperclip-mcp-nango

MCP server that wraps Nango self-hosted (Phase 15) for paperclip agents. Drop into `apps/paperclip-mcp-nango/` in `a-desanto/control-plane`.

## Tools exposed to agents

- `nango_list_connections(company_id?)` — list configured connections, optionally scoped to a company UUID
- `nango_get_connection(provider_config_key, connection_id)` — fetch a single connection's metadata + credentials
- `nango_proxy_get(provider_config_key, connection_id, endpoint)` — passthrough GET to provider API
- `nango_proxy_post(provider_config_key, connection_id, endpoint, body)` — passthrough POST

Per-client isolation: pass the company UUID as `connection_id` so each client's OAuth tokens stay separate within Nango.

## Required env

```
NANGO_URL          (default: http://nango-server:3003 — the in-network Nango compose service)
NANGO_SECRET_KEY   (REQUIRED — generate in Nango admin UI → Environment Settings)
```

## Deploy

1. Drop at `apps/paperclip-mcp-nango/` in `a-desanto/control-plane`, push.
2. Coolify Dockerfile build, deploy.
3. In paperclip's UI: register this MCP server for whichever agents need SaaS-API access. The MCP runs over stdio so it should be invoked as `docker exec -i paperclip-mcp-nango node dist/index.js` from paperclip's adapter.

## Wiring to specific add-ons

Each Phase 15-dependent add-on (Marketing, Sales, Support, Vertical Extensions calling SaaS) gets a skill markdown that uses these tools. Example skill snippet for the marketing-social add-on:

```markdown
When asked to publish to a client's social channels:
1. Call nango_list_connections(company_id) to find the right channel.
2. Call nango_proxy_post(provider_config_key, company_id, "/posts", {body, schedule_for}).
```

## What's NOT in this skeleton

- Per-provider input validation (Nango handles it but UX would be better with typed schemas)
- Rate-limit awareness (Nango exposes rate limit info; agents don't know to back off yet)
- Webhook handling (incoming SaaS events from Nango — separate Express endpoint, not MCP)

## Effort to fully ship

This skeleton: ~1 day of authoring + Coolify wiring. Per-provider OAuth registration + skill markdowns: 30-60 min each.
