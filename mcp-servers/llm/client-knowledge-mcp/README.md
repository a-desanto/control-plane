# client-knowledge-mcp

Phase 6 Stage 3 MCP server. Embeds queries via Cohere Embed v4 on Bedrock,
runs pgvector cosine similarity against `client_knowledge` DB, returns top-k chunks.

Port 4005. Internal only (no Traefik). OpenCode connects via `opencode.json`
`type: "streamable-http"`.

## Tool

### `search_client_knowledge`

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `query` | string | Yes | Natural-language search query |
| `scope.companyId` | string | No | UUID — falls back to `DEFAULT_COMPANY_ID` |
| `scope.agentId` | string | No | UUID — restricts to ACL-granted docs |
| `scope.sourceType` | string | No | e.g. `manual_upload`, `gmail` |
| `k` | integer | No | Results to return (default 5) |

Returns array of `{ content, score, document_id, title, source_type, source_uri, chunk_index }`.

## Env vars

| Var | Required | Notes |
|-----|----------|-------|
| `CKDB_URL` | Yes | `postgresql://client_knowledge:<pass>@openclaw-pgvector-db:5432/client_knowledge` |
| `AWS_BEARER_TOKEN_BEDROCK` | Yes | Bearer token — same as bedrock-proxy and ingester |
| `AWS_REGION` | No | Default `us-east-2` |
| `EMBED_MODEL_ID` | No | Default `us.cohere.embed-v4:0` (cross-region inference profile) |
| `DEFAULT_COMPANY_ID` | No | UUID fallback when scope.companyId omitted |
| `PORT` | No | Default `4005` |

## Bedrock note

Uses `fetch` with `Authorization: Bearer` header — NOT `@aws-sdk` (which uses SigV4/IAM,
incompatible with this deployment's Bearer token auth). `input_type: search_query` is
critical — Cohere Embed v4 is asymmetric; using `search_document` here degrades retrieval
~10-15%. `output_dimension: 1024` must match the ingester and `VECTOR(1024)` schema.
