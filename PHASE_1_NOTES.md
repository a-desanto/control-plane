# Phase 1 Notes

## api-gateway configuration

The api-gateway lives outside this repo (it runs as a separate Coolify service). The following configuration change is required for Phase 1.

### Route `/intent*` to paperclipai

Add a route that forwards all `/intent*` paths from api-gateway to the paperclipai container. In the existing Traefik-based api-gateway config this looks like:

```yaml
# In your Traefik dynamic config or docker-compose labels for the api-gateway service:
http:
  routers:
    paperclipai-intent:
      rule: "PathPrefix(`/intent`)"
      service: paperclipai
      middlewares:
        - paperclipai-auth
        - paperclipai-ratelimit

  services:
    paperclipai:
      loadBalancer:
        servers:
          - url: "http://paperclipai:8000"  # internal Docker network name

  middlewares:
    paperclipai-auth:
      # Validate the API key and inject X-Caller-Type header.
      # The header value must be "n8n" or "client_app" — this becomes
      # the caller_type claim checked by paperclipai's intent validator.
      # Add per-key metadata in the api-gateway's key store:
      #   n8n service accounts → X-Caller-Type: n8n
      #   client app API keys  → X-Caller-Type: client_app
      headers:
        customRequestHeaders:
          X-Caller-Type: "n8n"   # set dynamically per API key
```

### `caller_type` claim

paperclipai currently reads `caller_type` from the submitted JSON body (validated by the Intent Pydantic model). In Phase 2 or pre-flight, the api-gateway should inject an `X-Caller-Type` header derived from the authenticating API key's metadata, and paperclipai should treat that header as authoritative rather than accepting the caller-supplied value.

**For Phase 1:** `caller_type` in the body is caller-supplied and accepted as-is. This is acceptable because Phase 1 has no external callers in production yet.

**For Phase 2:** add a FastAPI middleware or dependency that reads `X-Caller-Type` from the gateway-injected header and overwrites (or validates) the body's `caller_type` field. The api-gateway is the trust boundary.

### `BASE_URL` environment variable

paperclipai constructs `audit_link`, `events_url`, and `status_url` using a `BASE_URL` env var (defaults to `http://localhost:8000`). Set it to the public-facing URL in the Coolify environment config:

```
BASE_URL=https://paperclipai.yourdomain.com
```

## n8n integration test workflow

See `n8n-workflows/test_post_intent.json`. Import this workflow into the n8n instance via the n8n UI (Settings → Import) or CLI. It POSTs a hardcoded intent payload to `POST /intent` and logs the 202 response.

Before importing, update the `url` field in the workflow JSON to point at the actual api-gateway `/intent` endpoint with the correct base URL and API key header.

## Open questions carried forward

These were deferred from pre-flight and remain open:

- api-gateway: which auth mechanism is in use (JWT, API key header, mTLS)?
- Where do per-client API keys live (Coolify env vars, Vault, inline in gateway config)?
- `BASE_URL` per VPS — should be injected as a Coolify env var at deploy time.
