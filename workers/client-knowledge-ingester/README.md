# client-knowledge-ingester

Phase 6 Stage 2 worker. Reads from Redis `ck:ingest:queue`, chunks text,
embeds via Cohere Embed v4 on Bedrock, writes to `client_knowledge` pgvector DB.

Port 4004. Internal only (no Traefik label).

## Endpoints

- `GET /health` — liveness check
- `POST /upload` — manual document ingestion (JSON body, see `UploadRequest` in app.py)

## Queue event shape

```json
{
  "companyId": "uuid",
  "content": "full document text",
  "title": "optional title",
  "sourceType": "manual_upload",
  "sourceUri": null,
  "mimeType": "text/plain",
  "agentId": "uuid (for cost attribution)",
  "agentIds": ["uuid", "..."]
}
```

## Env vars

| Var | Required | Notes |
|-----|----------|-------|
| `CKDB_URL` | Yes | `postgresql://client_knowledge:<pass>@<host>:5432/client_knowledge` |
| `PAPERCLIP_DB_URL` | Yes | `postgresql://paperclip:paperclip@paperclip:54329/paperclip` |
| `AWS_BEARER_TOKEN_BEDROCK` | Yes | Long-term Bedrock API key (same as bedrock-proxy) |
| `REDIS_URL` | No | Default `redis://redis:6379/2` |
| `AWS_REGION` | No | Default `us-east-2` |
| `EMBED_MODEL_ID` | No | Default `cohere.embed-v4:0` |
| `LANGFUSE_HOST` | No | Optional observability |
| `LANGFUSE_SECRET_KEY` | No | |
| `LANGFUSE_PUBLIC_KEY` | No | |
