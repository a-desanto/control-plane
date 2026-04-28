# openclaw-worker

Long-running task worker that polls paperclip for issues assigned to the `openclaw-worker` agent, executes each via OpenClaw's embedded agent (`--local` mode), and reports results back.

## Architecture

```
Worker (asyncio + httpx)
  │
  ├── GET  /api/companies/{id}/issues?status=todo&assigneeAgentId={id}
  ├── POST /api/issues/{id}/checkout          ← claim
  ├── PATCH /api/issues/{id}                  ← in_progress / done / blocked
  │
  └── openclaw agent --agent executor --local --thinking high --json
        └── OpenRouter / Anthropic (via ANTHROPIC_BASE_URL → openrouter-proxy)
              └── Claude Sonnet 4.6 (executes bash, edit, read, write, glob, grep)
```

## Env vars (all set in Coolify)

| Variable | Required | Notes |
|---|---|---|
| `PAPERCLIP_API_URL` | Yes | e.g. `https://paperclipai.cfpa.sekuirtek.com` |
| `PAPERCLIP_API_KEY` | Yes | Board API key for the openclaw-worker agent |
| `PAPERCLIP_COMPANY_ID` | Yes | UUID of the company to poll |
| `PAPERCLIP_AGENT_ID` | Yes | UUID of the `openclaw-worker` agent in paperclip |
| `OPENROUTER_API_KEY` | Yes | Passed to OpenClaw subprocess |
| `ANTHROPIC_BASE_URL` | Yes | `http://openrouter-proxy:4001` |
| `OPENCLAW_AGENT_PROFILE` | No | Default: `executor` |
| `WORKING_DIR_BASE` | No | Default: `/workspace` |
| `TASK_TIMEOUT_SECONDS` | No | Default: `1800` (30 min) |
| `POLL_INTERVAL_SECONDS` | No | Default: `10` |

## Deployment

Deployed as Coolify app (no public domain, `traefik.enable=false`) on the `coolify` Docker network alongside `paperclipai` and `openrouter-proxy`.

Create the `openclaw-worker` agent in paperclip's UI first, then supply its UUID as `PAPERCLIP_AGENT_ID` and a fresh API key as `PAPERCLIP_API_KEY`.

To update worker logic: edit `src/worker.py` and `git push origin main`. Coolify auto-deploys.

## Task flow

1. Worker polls for `todo` issues assigned to `PAPERCLIP_AGENT_ID`.
2. Claims the first issue via `/checkout` (atomic — 409 on race means skip).
3. Sets status `in_progress`.
4. If the issue has a `repoUrl`, clones it into `/workspace/{issueId}`.
5. Runs `openclaw agent --local --json` with the issue title + description as the prompt.
6. Captures git diff and runs tests if present (`pytest` / `npm test`).
7. Sets status `done` (exit 0) or `blocked` (non-zero), with a JSON summary comment.

## Observability

```bash
docker logs $(docker ps -q --filter name=<coolify-app-uuid>) -f
```

The worker logs every poll cycle, checkout, openclaw invocation, and final status update.
