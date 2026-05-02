# bedrock-proxy

Thin proxy: Anthropic SDK → AWS Bedrock InvokeModel (Phase 5.8).

Listens on port **4002**. Accepts the same request format as the Anthropic messages API; translates model IDs, injects `anthropic_version`, and forwards to Bedrock with Bearer auth.

## Required env vars

| Var | Notes |
|-----|-------|
| `BEDROCK_API_KEY` | Long-term Bedrock API key (Bearer token, not SigV4) |
| `BEDROCK_BASE_URL` | Bedrock runtime endpoint, e.g. `https://bedrock-runtime.us-east-1.amazonaws.com` |
| `PAPERCLIP_DB_URL` | asyncpg DSN for paperclip PostgreSQL (port 54329) |
| `LANGFUSE_HOST` | Langfuse instance URL |
| `LANGFUSE_PUBLIC_KEY` | Langfuse public key |
| `LANGFUSE_SECRET_KEY` | Langfuse secret key |

Optional:
- `PROXY_PORT` — override listen port (default: `4002`)

## Supported models

| Anthropic model | Bedrock model ID |
|-----------------|------------------|
| `claude-sonnet-4-6` | `anthropic.claude-sonnet-4-6` |
| `claude-haiku-4-5` | `anthropic.claude-haiku-4-5-20251001-v1:0` |
| `claude-opus-4-7` | `anthropic.claude-opus-4-7:0` (**unverified** — not in Bedrock legacy table as of 2026-05) |

## Headers consumed from caller

- `X-Paperclip-Agent-Id` — UUID; used to write `cost_events` row
- `X-Paperclip-Company-Id` — UUID; used to write `cost_events` row

Both are optional. If either is absent the request is proxied but no cost event is written.

## Stage 1 smoke test

```bash
docker run --rm --network coolify curlimages/curl -s -X POST \
  http://bedrock-proxy:4002/v1/messages \
  -H "Content-Type: application/json" \
  -H "X-Paperclip-Agent-Id: 0930e444-c1f1-43ee-9b10-98e67b3daa44" \
  -H "X-Paperclip-Company-Id: bd80728d-6755-4b63-a9b9-c0e24526c820" \
  -d '{"model":"claude-haiku-4-5","max_tokens":50,"messages":[{"role":"user","content":"say hello"}]}'
```

## Pricing note

Claude 4.x pricing was not yet listed on the AWS Bedrock pricing page as of 2026-05. Values in `BEDROCK_PRICING` are taken from the runbook and should be verified against `https://aws.amazon.com/bedrock/pricing/` before production use.
