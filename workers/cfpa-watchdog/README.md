# cfpa-watchdog

Spend-velocity kill-switch. Polls paperclip's cost API every `POLL_INTERVAL_SECONDS` and
pauses any agent whose rolling-window spend exceeds a threshold. Fires a Discord alert on
detection. Pings a healthchecks.io URL so you know the watchdog itself is alive.

---

## Required environment variables

| Variable | Example | Notes |
|---|---|---|
| `PAPERCLIP_API_URL` | `https://paperclipai.cfpa.sekuirtek.com` | No trailing slash |
| `PAPERCLIP_API_KEY` | `pcp_board_...` | Dedicated key named `cfpa-watchdog`; needs read + write (pause) |
| `PAPERCLIP_COMPANY_ID` | `bd80728d-6755-4b63-a9b9-c0e24526c820` | UUID, not slug |
| `DISCORD_WEBHOOK_URL` | `https://discord.com/api/webhooks/...` | Shared with Coolify alerts |
| `HEALTHCHECK_PING_URL` | `https://hc-ping.com/<uuid>` | Separate check from backup runner |
| `POLL_INTERVAL_SECONDS` | `60` | How often to poll (default 60) |
| `PER_MINUTE_MAX_USD` | `1.00` | Default per-agent 1-minute ceiling |
| `PER_5MIN_MAX_USD` | `3.00` | Default per-agent 5-minute ceiling |
| `PER_HOUR_MAX_USD` | `8.00` | Default per-agent 60-minute ceiling |

## Per-agent threshold overrides

Raise limits for agents that legitimately spend more (e.g. CEO during planning):

```
WATCHDOG_AGENT_<UUID>_PER_HOUR_MAX_USD=20
WATCHDOG_AGENT_<UUID>_PER_5MIN_MAX_USD=10
WATCHDOG_AGENT_<UUID>_PER_MINUTE_MAX_USD=5
```

All three suffixes are supported per agent. Unset suffixes use the global defaults.

## Deploy in Coolify

- Source: `a-desanto/control-plane`, branch `main`, base dir `/workers/cfpa-watchdog`
- Build pack: Dockerfile
- Network: `coolify` (so it can reach paperclipai over Docker DNS)
- No public domain, `traefik.enable=false`
- Set all env vars above as Secret

## What it does NOT do

- Does not monitor or act on company-wide budget (use paperclip's built-in budget policies)
- Does not auto-resume paused agents (manual review required)
- Does not persist pause state across restarts — on startup it scans for already-paused
  agents and respects that state without re-pausing

## Re-enabling a watchdog-paused agent

1. Investigate the cause in paperclip's heartbeat run log
2. Resume via paperclip UI or `POST /api/agents/<id>/resume`
3. The watchdog will respect the resume until the next threshold breach
