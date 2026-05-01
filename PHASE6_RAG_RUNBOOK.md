# PHASE6_RAG_RUNBOOK.md — knowledge layer (RAG over client data)

**Phase:** 6 (Knowledge layer) — see `ROADMAP.md`
**Scope:** MVP — pgvector store + ingestion worker + retrieval MCP server. Manual document upload only (Drive/Gmail OAuth source connectors are Phase 15-dependent and deferred).
**Outcome:** any agent can install the `client_knowledge` skill and answer "find that contract from 2023" against ingested data, returning citations.
**Effort:** ~3-5 working days for MVP. Source connectors add another 2-3 days each (Drive, Gmail, Dropbox).

---

## Why now

Phase 6 is flagged "highest priority" in the ROADMAP because it's the single biggest credibility gap for the "client's operating system" positioning. Without RAG, the system can't answer questions about the client's own data — and that's the table-stakes capability of any "AI for your business" product.

It also unlocks 4 of the universal seven workflows: document organization (=this), email management (sender history), invoice processing (vendor history), lead qualification (past leads).

---

## Architecture target

Separate pgvector store from paperclip's embedded Postgres. Do not modify paperclip's schema — paperclip is upstream (paperclipai/paperclip on GitHub), and our schema changes would conflict with their migrations.

```
paperclipai (existing, unmodified)
       │
       │ MCP call: search_client_knowledge(query, scope)
       ▼
client-knowledge-mcp (NEW, Coolify app)
       │
       │ SQL query
       ▼
client-knowledge-db (NEW, postgres-17 + pgvector)
       ▲
       │ INSERT
       │
client-knowledge-ingester (NEW, Coolify app)
       ▲
       │ polls queue (Redis or REST endpoint)
       │
[manual upload via REST endpoint] ──── (Phase 15 dependent: Gmail/Drive/Dropbox OAuth — DEFERRED)
```

Three new Coolify apps on the existing client VPS:

| App | Purpose | Public? | Stack |
|-----|---------|---------|-------|
| `client-knowledge-db` | Postgres 17 + pgvector | Internal only | `pgvector/pgvector:pg17` |
| `client-knowledge-ingester` | Reads upload queue, embeds, writes chunks | Internal only | Node.js worker |
| `client-knowledge-mcp` | Exposes `search_client_knowledge` MCP tool to agents | Internal only | Node.js MCP server |

All three live on the `coolify` Docker network so they can reach each other and paperclipai.

---

## Pre-flight (decisions before starting — ~30 min)

**1. Embedding provider.**

Recommendation: Voyage 3 (`voyage-3-large` for retrieval). Best retrieval quality as of mid-2026, $0.18 per 1M tokens. OpenAI `text-embedding-3-large` is a fine alternative ($0.13/1M tokens, slightly weaker on retrieval). Anthropic embeddings are catching up but not yet best-in-class.

Decision-driver: cost. For an SMB client with ~100k documents averaging 2k tokens each = 200M tokens to ingest = $36 at Voyage / $26 at OpenAI. One-time cost, then incremental as new docs arrive. Either works.

Get an API key for whichever you pick and save in your secrets manager.

**2. Vector dimensionality.**

Voyage 3 outputs 1024-dim. OpenAI `text-embedding-3-large` outputs 3072-dim (default) or can be configured to 256/1024. Pick 1024 — Voyage native, OpenAI configurable, and pgvector index sizes scale with dimensionality. Going from 3072 to 1024 cuts index size 3x with negligible quality loss in OpenAI's case.

**3. Chunking strategy.**

Recommendation: 512-token chunks with 64-token overlap. Standard for retrieval. Use tiktoken (OpenAI) or Voyage's tokenizer to count.

**4. ANN index type.**

pgvector supports `ivfflat` (faster build, slower query) and `hnsw` (slower build, faster query, more accurate). Use HNSW (`m=16`, `ef_construction=64`) — better quality and the build time hit only matters at initial backfill.

---

## Stage 1 — Deploy client-knowledge-db (Postgres + pgvector) — ~30 min

Pre-built image with pgvector: `pgvector/pgvector:pg17` (official).

In Coolify on the client VPS: New Resource → Database → Postgres. Use the pgvector image instead of stock postgres-17.

Coolify config:
- Image: `pgvector/pgvector:pg17`
- Database name: `client_knowledge`
- User: `client_knowledge`
- Password: `<generate via openssl rand -hex 24, save to secrets manager>`
- Network: `coolify`
- Internal hostname: `client-knowledge-db`
- Port: 5432 (internal only — no Traefik label)
- Volume: persistent (Coolify default)

After deploy, exec in and create the extension + schema:

```bash
docker exec -i $(docker ps -q --filter name=client-knowledge-db) \
  psql -U client_knowledge -d client_knowledge << 'SQL'

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;  -- for hybrid search later

CREATE TABLE client_documents (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id   UUID NOT NULL,
  source_type  TEXT NOT NULL,            -- 'manual_upload', 'gmail', 'drive', etc.
  source_uri   TEXT,                     -- e.g. gmail message ID, drive file ID
  title        TEXT,
  mime_type    TEXT,
  byte_size    BIGINT,
  sha256       TEXT,                     -- content hash for dedup
  metadata     JSONB DEFAULT '{}',
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at   TIMESTAMPTZ                -- soft delete; Phase 18 lifecycle
);
CREATE INDEX client_documents_company_idx ON client_documents (company_id) WHERE deleted_at IS NULL;
CREATE INDEX client_documents_sha256_idx ON client_documents (sha256);

CREATE TABLE client_document_chunks (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id  UUID NOT NULL REFERENCES client_documents(id) ON DELETE CASCADE,
  company_id   UUID NOT NULL,            -- denormalized for ACL filter
  chunk_index  INT NOT NULL,
  content      TEXT NOT NULL,
  token_count  INT,
  embedding    VECTOR(1024) NOT NULL,
  metadata     JSONB DEFAULT '{}',
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX client_document_chunks_company_idx ON client_document_chunks (company_id);
CREATE INDEX client_document_chunks_doc_idx ON client_document_chunks (document_id);
CREATE INDEX client_document_chunks_embedding_idx
  ON client_document_chunks USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);

-- For ACL: which agents can see which documents
CREATE TABLE client_document_acls (
  document_id  UUID NOT NULL REFERENCES client_documents(id) ON DELETE CASCADE,
  agent_id     UUID NOT NULL,
  permission   TEXT NOT NULL DEFAULT 'read',  -- 'read', 'admin'
  granted_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (document_id, agent_id)
);
CREATE INDEX client_document_acls_agent_idx ON client_document_acls (agent_id);

SQL
```

**Done when:** `\d client_document_chunks` in psql shows the table with the HNSW index, and `SELECT 1` works from a `docker run --rm --network coolify postgres:17 psql -h client-knowledge-db -U client_knowledge` connection.

---

## Stage 2 — Build client-knowledge-ingester worker — ~1-1.5 days

New directory in `control-plane/workers/client-knowledge-ingester/`. Pattern: copy the structure of `workers/openclaw-worker/` since it's already proven.

**Responsibilities:**

- Listen on a queue (use Redis pub/sub or paperclip's routines table — start with Redis for simplicity).
- For each upload event: fetch source content, dedup by sha256, chunk, embed, INSERT into `client_documents` + `client_document_chunks`.
- Idempotent: re-running the same upload event produces the same chunks.

Stack: Node.js 20+, Drizzle ORM, `@langchain/textsplitters` (or roll own chunker), Voyage SDK or OpenAI SDK.

**Skeleton (Node.js):**

```js
// workers/client-knowledge-ingester/src/index.js
import { drizzle } from 'drizzle-orm/postgres-js';
import postgres from 'postgres';
import { Voyage } from 'voyageai';  // or '@anthropic-ai/voyage' or use fetch directly
import { RecursiveCharacterTextSplitter } from '@langchain/textsplitters';
import Redis from 'ioredis';
import crypto from 'crypto';

const sql = postgres(process.env.CKDB_URL);
const db = drizzle(sql);
const voyage = new Voyage({ apiKey: process.env.VOYAGE_API_KEY });
const redis = new Redis(process.env.REDIS_URL);

const splitter = new RecursiveCharacterTextSplitter({
  chunkSize: 2048,        // ~512 tokens
  chunkOverlap: 256,      // ~64 tokens
});

async function ingest(event) {
  const { companyId, sourceType, sourceUri, title, content, mimeType, agentIds } = event;
  const sha256 = crypto.createHash('sha256').update(content).digest('hex');

  // Dedup
  const existing = await sql`SELECT id FROM client_documents WHERE company_id = ${companyId} AND sha256 = ${sha256} AND deleted_at IS NULL`;
  if (existing.length) return existing[0].id;

  const [doc] = await sql`
    INSERT INTO client_documents (company_id, source_type, source_uri, title, mime_type, byte_size, sha256)
    VALUES (${companyId}, ${sourceType}, ${sourceUri}, ${title}, ${mimeType}, ${content.length}, ${sha256})
    RETURNING id
  `;

  const chunks = await splitter.splitText(content);
  const embeddings = await voyage.embed({
    input: chunks,
    model: 'voyage-3-large',
    inputType: 'document',
  });

  await sql`
    INSERT INTO client_document_chunks (document_id, company_id, chunk_index, content, token_count, embedding)
    SELECT ${doc.id}, ${companyId}, idx, c, ${null}, e::vector
    FROM unnest(${chunks}::text[], ${embeddings.data.map(e => `[${e.embedding.join(',')}]`)}::text[]) WITH ORDINALITY AS t(c, idx, e)
  `;

  // ACLs: grant read to specified agents (default: all agents in company if agentIds is null)
  if (agentIds?.length) {
    await sql`
      INSERT INTO client_document_acls (document_id, agent_id, permission)
      SELECT ${doc.id}, unnest(${agentIds}::uuid[]), 'read'
    `;
  }

  return doc.id;
}

async function main() {
  console.log('client-knowledge-ingester starting');
  while (true) {
    const job = await redis.blpop('ck:ingest:queue', 5);
    if (!job) continue;
    try {
      const event = JSON.parse(job[1]);
      const docId = await ingest(event);
      console.log(`ingested ${docId} from ${event.sourceType}:${event.sourceUri}`);
    } catch (e) {
      console.error('ingest failed', e);
      // dead-letter pattern: push to ck:ingest:dlq
      await redis.rpush('ck:ingest:dlq', job[1]);
    }
  }
}

main();
```

**Coolify deployment:**
- App name: `client-knowledge-ingester`
- Source: `a-desanto/control-plane`, branch `main`, base `/workers/client-knowledge-ingester`
- Network: `coolify`
- Public: false (`traefik.enable=false`)
- Env vars:
  ```
  CKDB_URL=postgres://client_knowledge:<password>@client-knowledge-db:5432/client_knowledge
  REDIS_URL=redis://redis:6379/2  # use existing Coolify-managed Redis, separate DB index
  VOYAGE_API_KEY=<key>
  ```

**Test endpoint:** the ingester listens on Redis. To test, push a test event:

```bash
docker exec $(docker ps -q --filter name=coolify-redis) \
  redis-cli RPUSH ck:ingest:queue '{"companyId":"bd80728d-6755-4b63-a9b9-c0e24526c820","sourceType":"manual_upload","title":"Test doc","content":"This is a test document about contracts with Acme Corp signed in 2023.","mimeType":"text/plain"}'
```

Watch logs: `docker logs -f $(docker ps -q --filter name=client-knowledge-ingester)` — should see "ingested \<uuid\>".

Verify in DB: `SELECT id, title, sha256 FROM client_documents` should show one row.

---

## Stage 3 — Build client-knowledge-mcp server — ~1-1.5 days

New directory in `control-plane/mcp-servers/llm/client-knowledge-mcp/` (re-use the now-empty `mcp-servers/llm/` slot — it's been waiting for a real tenant).

**Responsibilities:**

- Expose MCP tool `search_client_knowledge(query, scope, k=5)` over HTTP transport.
- Embed the query using same model + dimensions as ingestion.
- Run pgvector cosine similarity, optionally filter by `company_id` + `agent_id` ACL.
- Return top-k chunks with: content, score, document_id, document_title, source_type, source_uri.

Stack: Node.js + `@modelcontextprotocol/sdk`. HTTP transport (paperclip configures MCP servers via URL, not stdio for hosted ones).

**Skeleton:**

```js
// mcp-servers/llm/client-knowledge-mcp/src/index.js
import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { HttpServerTransport } from '@modelcontextprotocol/sdk/server/http.js';
import postgres from 'postgres';
import { Voyage } from 'voyageai';

const sql = postgres(process.env.CKDB_URL);
const voyage = new Voyage({ apiKey: process.env.VOYAGE_API_KEY });

const server = new Server({ name: 'client-knowledge', version: '0.1.0' }, { capabilities: { tools: {} } });

server.setRequestHandler('tools/list', async () => ({
  tools: [{
    name: 'search_client_knowledge',
    description: 'Search the client\'s indexed documents (contracts, emails, files) by natural-language query. Returns relevant excerpts with citations.',
    inputSchema: {
      type: 'object',
      properties: {
        query: { type: 'string', description: 'Natural-language search query' },
        scope: { type: 'object', description: 'Optional filter: { companyId, agentId, sourceType }' },
        k: { type: 'integer', default: 5, description: 'Number of results to return' },
      },
      required: ['query'],
    },
  }],
}));

server.setRequestHandler('tools/call', async (req) => {
  if (req.params.name !== 'search_client_knowledge') throw new Error('Unknown tool');
  const { query, scope = {}, k = 5 } = req.params.arguments;

  const companyId = scope.companyId || process.env.DEFAULT_COMPANY_ID;
  if (!companyId) throw new Error('companyId required');

  // Embed query
  const emb = await voyage.embed({ input: [query], model: 'voyage-3-large', inputType: 'query' });
  const vec = `[${emb.data[0].embedding.join(',')}]`;

  // Vector search with optional ACL
  const rows = await sql`
    SELECT
      ck.content,
      ck.embedding <=> ${vec}::vector AS distance,
      d.id AS document_id,
      d.title,
      d.source_type,
      d.source_uri,
      ck.chunk_index
    FROM client_document_chunks ck
    JOIN client_documents d ON d.id = ck.document_id
    ${scope.agentId ? sql`JOIN client_document_acls a ON a.document_id = d.id AND a.agent_id = ${scope.agentId}::uuid` : sql``}
    WHERE ck.company_id = ${companyId}::uuid
      AND d.deleted_at IS NULL
      ${scope.sourceType ? sql`AND d.source_type = ${scope.sourceType}` : sql``}
    ORDER BY ck.embedding <=> ${vec}::vector
    LIMIT ${k}
  `;

  return {
    content: [{
      type: 'text',
      text: JSON.stringify(rows.map(r => ({
        content: r.content,
        score: 1 - r.distance,
        document_id: r.document_id,
        title: r.title,
        source_type: r.source_type,
        source_uri: r.source_uri,
        chunk_index: r.chunk_index,
      })), null, 2),
    }],
  };
});

const transport = new HttpServerTransport({ port: parseInt(process.env.PORT || '3030') });
await server.connect(transport);
console.log('client-knowledge-mcp listening on', process.env.PORT || 3030);
```

**Coolify deployment:** same network, internal only, port 3030, env vars `CKDB_URL`, `VOYAGE_API_KEY`, `DEFAULT_COMPANY_ID=bd80728d-6755-4b63-a9b9-c0e24526c820`.

**Test:** from inside any container on the coolify network:

```bash
curl http://client-knowledge-mcp:3030 \
  -X POST -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"search_client_knowledge","arguments":{"query":"contracts with Acme","k":3}},"id":1}'
```

Should return the test doc you ingested in Stage 2.

---

## Stage 4 — Wire to paperclip agents as a skill — ~half a day

Two pieces:

**1. Register the MCP server in paperclip.** Use paperclip's MCP server config (likely a settings table or env). Point paperclip at `http://client-knowledge-mcp:3030`. Reference: paperclipai/paperclip repo's docs on configuring custom MCP servers.

**2. Create a `client_knowledge` skill** in paperclip's `company_skills` table. Markdown content describing when/how to use the tool. Skeleton:

```markdown
---
name: client-knowledge
description: Search the client's indexed documents (contracts, emails, internal files) before answering any question that depends on client-specific information.
---

# Client Knowledge Skill

When you need to answer a question about the client's specific business — contracts, past communications, customer history, internal documents — call `search_client_knowledge` BEFORE answering. Do not rely on general knowledge for client-specific questions.

## Usage

`search_client_knowledge(query: string, scope?: object, k?: number)`

- `query`: natural-language question. Be specific. Bad: "contracts." Good: "NDAs signed with Acme in 2023."
- `scope.sourceType`: optional — restrict to "manual_upload", "gmail", "drive", etc.
- `k`: how many results, default 5.

## When to use

- "Find the contract we signed with X"
- "What did we promise customer Y?"
- "Summarize our past emails with Z"
- "What's the status of project Alpha?"

## When NOT to use

- General knowledge questions ("what is GDPR?")
- Math, code, logic
- Answers about your own (agent's) configuration

## Output handling

Returns up to k chunks with content, score (0-1), document title, and source info. Cite the document title and source when using these excerpts in your response.
```

Install this skill into Caring First's `company_skills` table; assign to the test agent (e.g. `opencode-free-agent` for cheap testing).

---

## Stage 5 — End-to-end verification — ~half a day

1. Upload a test document: push to the ingest queue (Stage 2 test command).
2. Trigger a heartbeat on the test agent with an issue like "What contracts do we have with Acme?"
3. Watch the heartbeat trace in Langfuse (assuming Phase 14 done). The agent should call `search_client_knowledge`, get the chunk back, cite it in its response.
4. Verify the issue gets a response that references the test document by name.

If retrieval quality is poor:

- Check chunk size / overlap (smaller chunks for short answers, larger for context)
- Check embedding model quality (try `voyage-3-large` if you started with `voyage-3` lite)
- Add re-ranking: Voyage Rerank-2 over top-20 candidates (improves top-5 quality 10-20%)

---

## Stage 6 — Source connectors (DEFERRED — needs Phase 15 OAuth)

The MVP above only supports manual upload. To ingest Gmail / Drive / Dropbox / Box automatically:

1. Phase 15 (OAuth manager) must ship first — it manages the per-client OAuth tokens.
2. Then add source-specific connector containers (one per source) that:
   - Periodically poll the source for new content (or webhook-driven where possible)
   - Fetch content via the OAuth token
   - Push to the existing ingester queue

Each connector is ~1-2 days of work. Order: Gmail (highest value) → Drive (similar) → Dropbox/Box (similar pattern, just different APIs).

---

## Stage 7 — Doc updates → PR — ~half a day

After Phase 6 MVP is verified working:

1. Update `ARCHITECTURE.md` component inventory — add three new rows: `client-knowledge-db`, `client-knowledge-ingester`, `client-knowledge-mcp`.
2. Update `ARCHITECTURE.md` execution paths — add the MCP retrieval flow.
3. Update `ROADMAP.md` Phase 6 status: from "Not started" to "MVP done. Source connectors pending Phase 15."
4. Update `WORKFLOWS.md` — workflows that depend on Phase 6 can move from "blocked" to "ready to build."

---

## Cost expectations

- **Ingestion (one-time):** $0.18 per 1M tokens at Voyage 3, $0.13/1M at OpenAI 3-large. A typical SMB has 10k-100k documents at 2k tokens each = $4-$36 to backfill.
- **Retrieval (per query):** $0.18/1M for the query embedding (~50 tokens = $0.00001), then trivial pgvector compute. Effectively free per query.
- **Storage:** 1024-dim embeddings at 4 bytes/dim = 4KB per chunk. 100k docs × 5 chunks/doc = 500k chunks = 2GB embeddings + ~1GB content. Negligible.
- **Where it adds up:** the LLM that consumes the retrieved chunks. Sonnet at $3/1M input tokens × 5 chunks × 500 tokens = $0.0075 per RAG-augmented call. Real cost driver is the model, not the embeddings or DB.

---

## What's NOT in scope for MVP

- Source connectors (Gmail/Drive/Dropbox) — needs Phase 15
- Re-ranking layer — quality optimization, not blocking for MVP
- Hybrid search (vector + keyword via pg_trgm) — same; add when retrieval-quality issues appear
- Chunk-level access logs / audit trail — extends to Phase 18 (data lifecycle)
- Multi-modal embeddings (images, PDFs with diagrams) — Phase 6.5; OpenAI/Voyage have multimodal models
- Cross-company search — explicitly forbidden by the per-VPS isolation invariant

---

## Handoff to Claude CLI

The full Phase 6 work spans Stages 1-7 above. Stages 1, 4, 5, 7 are largely Claude-CLI-executable on the existing client VPS. Stages 2 and 3 are real software development — your CLI can scaffold and deploy them, but you'll want to review code before merging.

Suggested sequencing for the CLI:

1. **Stage 1 (deploy DB):** CLI runs the Coolify deploy + schema bootstrap. ~30 min.
2. **Stage 2 (ingester):** CLI scaffolds the worker code, opens a PR for review. You merge after looking at it. CLI then deploys via Coolify push. ~1-1.5 days.
3. **Stage 3 (MCP server):** same pattern. ~1-1.5 days.
4. **Stage 4 (wire to paperclip):** CLI configures MCP server in paperclip + writes the skill markdown. ~half a day.
5. **Stage 5 (verify):** CLI runs the end-to-end test, captures Langfuse trace screenshot. ~half a day.
6. **Stage 7 (doc update PR):** CLI writes the PR. ~half a day.

For each stage, hand the CLI this runbook + the corresponding section as the prompt.

---

## Why this scope is right

- **Manual upload only for MVP** — building source connectors before the rest of the pipeline is proven adds risk. Once retrieval works for one document, the OAuth/ingestion-source layer is just an adapter on top.
- **Separate pgvector DB, not paperclip's embedded one** — paperclip is upstream; modifying its schema causes pain on every upgrade.
- **Voyage 3 over OpenAI** — slightly higher cost ($36 vs $26 for full backfill), much better retrieval quality. You can swap later if cost matters more than quality.
- **HNSW over IVFFlat** — better retrieval, build time only matters at backfill.
- **Per-document ACLs** — even though MVP only has one client, the table structure must support per-agent visibility from day one. Adding ACLs later is harder than including them now.
