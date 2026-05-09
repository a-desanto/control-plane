# Phase 15 — Nango self-hosted (skeleton)

DNS pre-staged: `nango.cfpa.sekuirtek.com → 187.77.213.142`. Drop at `apps/nango/` in `a-desanto/control-plane`.

## Required env vars (Coolify)

```
NANGO_DB_PASSWORD     (REQUIRED — strong password, store in secrets manager)
NANGO_ENCRYPTION_KEY  (REQUIRED — 32-byte base64; generate with: openssl rand -base64 32)
```

## Deploy

1. Copy this dir to `apps/nango/` in `a-desanto/control-plane`, push.
2. Coolify Docker Compose deploy from `apps/nango/docker-compose.yaml`.
3. Set domain `nango.cfpa.sekuirtek.com` on the `nango-server` service.
4. Set env vars, deploy.
5. Bootstrap admin via the UI; configure first integration (Buffer? CRM? whatever you need first).

## What's NOT in this skeleton

- **Per-integration OAuth provider configs** (Buffer/HubSpot/Salesforce/Slack/...) — each requires you to register an OAuth app with the provider + add client_id/secret to Nango admin UI.
- **`paperclip-mcp` wiring to call Nango** — paperclipai needs an MCP server that wraps Nango's connection API. Some scaffolding exists at `apps/paperclip-mcp/` per the Coolify app list; verify what's there.
- **Per-client connection isolation** — Nango supports `connection_id` scoping per company; needs to be wired into how paperclipai calls it.

## Effort to fully ship per ROADMAP

Multi-day. Skeleton is half a day. Per-integration setup is 30–60 min each. paperclipai wiring is the heavier piece — likely a small TypeScript MCP shim.
