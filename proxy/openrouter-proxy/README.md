# openrouter-proxy

Thin HTTP proxy that translates Claude Code CLI requests into OpenRouter-compatible calls.

## Architecture

```
paperclipai container
  └── claude CLI
        └── ANTHROPIC_BASE_URL=http://openrouter-proxy:4001
              └── openrouter-proxy:4001  (this container)
                    └── POST https://openrouter.ai/api/v1/messages
                          └── Authorization: Bearer $OPENROUTER_API_KEY
```

## Why this proxy exists

Claude Code CLI v2.x sends `POST /v1/messages?beta=true` with an `anthropic-beta` header
listing multiple beta feature flags (e.g. `interleaved-thinking-2025-05-14,
context-management-2025-06-27, prompt-caching-scope-2026-01-05, ...`).

OpenRouter's Anthropic-compatible endpoint (`https://openrouter.ai/api/v1`) returns HTTP 404
for the `?beta=true` URL suffix, and likely rejects the `anthropic-beta` / `anthropic-version`
headers as well.

This proxy:
1. Accepts any `POST /v1/messages*` and forwards it to `POST /api/v1/messages` on OpenRouter,
   stripping the query string and Anthropic-specific headers.
2. Responds to `GET /models/*` with a fake 200 so the CLI doesn't abort on model lookup.
3. Preserves the full request body (model name, messages, tools, etc.) unchanged.

## Configuration

| Env var | Required | Notes |
|---|---|---|
| `OPENROUTER_API_KEY` | Yes | OpenRouter API key. Set in Coolify — never in source. |
| `PROXY_PORT` | No | Listen port. Defaults to `4001`. |

## Deployment

This container is deployed via Coolify with `traefik.enable=false` (internal-only, no
public route). It sits on the same Docker network as `paperclipai` and is addressable
as `openrouter-proxy` via Docker DNS.

To update the proxy logic:
1. Edit `proxy.py`
2. `git push origin main`
3. Coolify auto-deploys (webhook trigger on push)

## Upstream

- Endpoint: `https://openrouter.ai/api/v1/messages`
- Docs: https://openrouter.ai/docs
- Model names: use Anthropic short-form (`claude-sonnet-4-6`) — OpenRouter's `/messages`
  endpoint accepts them even though the model list uses the `anthropic/` prefix form.
