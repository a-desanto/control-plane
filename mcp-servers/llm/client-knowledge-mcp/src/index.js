/**
 * client-knowledge-mcp — Phase 6 Stage 3
 * MCP retrieval server: embeds query via Cohere Embed v4 on Bedrock,
 * runs pgvector cosine similarity against client_document_chunks,
 * returns top-k chunks with citations.
 *
 * Auth: AWS_BEARER_TOKEN_BEDROCK via Bearer header (not SigV4/AWS SDK —
 * same pattern as bedrock-proxy; standard AWS SDK won't pick this up).
 * Transport: MCP Streamable HTTP — OpenCode connects via opencode.json
 *   type: "streamable-http", url: "http://client-knowledge-mcp:4005"
 */
import express from 'express';
import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import { ListToolsRequestSchema, CallToolRequestSchema } from '@modelcontextprotocol/sdk/types.js';
import postgres from 'postgres';
import pino from 'pino';

// ── Config ────────────────────────────────────────────────────────────────────
const CKDB_URL            = process.env.CKDB_URL;
const AWS_BEARER_TOKEN    = process.env.AWS_BEARER_TOKEN_BEDROCK;
const AWS_REGION          = process.env.AWS_REGION          || 'us-east-2';
const EMBED_MODEL_ID      = process.env.EMBED_MODEL_ID      || 'us.cohere.embed-v4:0';
const DEFAULT_COMPANY_ID  = process.env.DEFAULT_COMPANY_ID;
const PORT                = parseInt(process.env.PORT       || '4005', 10);

if (!CKDB_URL)         throw new Error('CKDB_URL is required');
if (!AWS_BEARER_TOKEN) throw new Error('AWS_BEARER_TOKEN_BEDROCK is required');

const BEDROCK_BASE = `https://bedrock-runtime.${AWS_REGION}.amazonaws.com`;

// ── Logger + DB ───────────────────────────────────────────────────────────────
const log = pino({ level: 'info' });
const sql = postgres(CKDB_URL);

// ── Bedrock embed (fetch + Bearer — not AWS SDK; matches bedrock-proxy) ───────
async function embedQuery(query) {
  const resp = await fetch(`${BEDROCK_BASE}/model/${EMBED_MODEL_ID}/invoke`, {
    method: 'POST',
    headers: {
      Authorization:   `Bearer ${AWS_BEARER_TOKEN}`,
      'Content-Type':  'application/json',
      Accept:          'application/json',
    },
    body: JSON.stringify({
      texts:            [query],
      input_type:       'search_query',   // Cohere asymmetry: query ≠ document
      embedding_types:  ['float'],
      output_dimension: 1024,             // Must match ingester + VECTOR(1024) schema
      truncate:         'END',
    }),
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`Bedrock embed ${resp.status}: ${text.slice(0, 400)}`);
  }
  const body = await resp.json();
  return body.embeddings.float[0]; // 1024-dim float array
}

// ── pgvector search ───────────────────────────────────────────────────────────
async function searchKnowledge({ query, scope = {}, k = 5 }) {
  const companyId = scope.companyId || DEFAULT_COMPANY_ID;
  if (!companyId) throw new Error('companyId is required (pass in scope or set DEFAULT_COMPANY_ID)');

  const embedding = await embedQuery(query);
  const embStr    = '[' + embedding.join(',') + ']';

  log.info({ companyId, k, hasAgentId: !!scope.agentId, hasSourceType: !!scope.sourceType },
    'searching');

  let rows;
  if (scope.agentId) {
    rows = await sql`
      SELECT
        ck.content,
        (1 - (ck.embedding <=> ${embStr}::vector))::float8 AS score,
        d.id::text   AS document_id,
        d.title,
        d.source_type,
        d.source_uri,
        ck.chunk_index
      FROM  client_document_chunks ck
      JOIN  client_documents       d  ON d.id = ck.document_id
      JOIN  client_document_acls   a  ON a.document_id = d.id
                                     AND a.agent_id = ${scope.agentId}::uuid
      WHERE ck.company_id   = ${companyId}::uuid
        AND d.deleted_at   IS NULL
        ${scope.sourceType ? sql`AND d.source_type = ${scope.sourceType}` : sql``}
      ORDER BY ck.embedding <=> ${embStr}::vector
      LIMIT ${k}
    `;
  } else {
    rows = await sql`
      SELECT
        ck.content,
        (1 - (ck.embedding <=> ${embStr}::vector))::float8 AS score,
        d.id::text   AS document_id,
        d.title,
        d.source_type,
        d.source_uri,
        ck.chunk_index
      FROM  client_document_chunks ck
      JOIN  client_documents       d ON d.id = ck.document_id
      WHERE ck.company_id   = ${companyId}::uuid
        AND d.deleted_at   IS NULL
        ${scope.sourceType ? sql`AND d.source_type = ${scope.sourceType}` : sql``}
      ORDER BY ck.embedding <=> ${embStr}::vector
      LIMIT ${k}
    `;
  }

  log.info({ hits: rows.length, topScore: rows[0]?.score }, 'search_done');
  return rows.map(r => ({
    content:     r.content,
    score:       Number(r.score),
    document_id: r.document_id,
    title:       r.title,
    source_type: r.source_type,
    source_uri:  r.source_uri,
    chunk_index: r.chunk_index,
  }));
}

// ── MCP tool definition ───────────────────────────────────────────────────────
const TOOL_DEF = {
  name: 'search_client_knowledge',
  description:
    "Search the client's indexed documents (contracts, emails, files) by natural-language query. " +
    'Returns relevant excerpts with cosine similarity scores and document citations.',
  inputSchema: {
    type: 'object',
    properties: {
      query: {
        type:        'string',
        description: 'Natural-language search query',
      },
      scope: {
        type:        'object',
        description: 'Optional filter: { companyId, agentId, sourceType }',
        properties: {
          companyId:  { type: 'string', description: 'UUID of the company' },
          agentId:    { type: 'string', description: 'UUID of the agent — restricts to ACL-granted docs' },
          sourceType: { type: 'string', description: 'e.g. manual_upload, gmail, drive' },
        },
      },
      k: {
        type:        'integer',
        default:     5,
        description: 'Number of results to return (default 5)',
      },
    },
    required: ['query'],
  },
};

// ── MCP server factory (one per stateless request) ────────────────────────────
function buildMcpServer() {
  const server = new Server(
    { name: 'client-knowledge', version: '0.1.0' },
    { capabilities: { tools: {} } },
  );

  server.setRequestHandler(ListToolsRequestSchema, async () => ({
    tools: [TOOL_DEF],
  }));

  server.setRequestHandler(CallToolRequestSchema, async (request) => {
    const { name, arguments: args } = request.params;
    if (name !== 'search_client_knowledge') {
      throw new Error(`Unknown tool: ${name}`);
    }
    const { query, scope, k } = args ?? {};
    const results = await searchKnowledge({ query, scope, k });
    return {
      content: [{ type: 'text', text: JSON.stringify(results, null, 2) }],
    };
  });

  return server;
}

// ── Express app ───────────────────────────────────────────────────────────────
const app = express();
app.use(express.json());

app.get('/health', (_req, res) => {
  res.json({ status: 'ok', service: 'client-knowledge-mcp' });
});

// Stateless Streamable HTTP: new transport per POST (no session state needed)
app.post('/mcp', async (req, res) => {
  const transport = new StreamableHTTPServerTransport({ sessionIdGenerator: undefined });
  const server    = buildMcpServer();
  await server.connect(transport);
  try {
    await transport.handleRequest(req, res, req.body);
  } catch (err) {
    log.error({ err }, 'mcp_request_failed');
    if (!res.headersSent) res.status(500).json({ error: String(err) });
  }
});

// GET /mcp needed for SSE notifications (return 405 for stateless mode)
app.get('/mcp', (_req, res) => res.status(405).end());

app.listen(PORT, () => {
  log.info({ port: PORT, model: EMBED_MODEL_ID }, 'client-knowledge-mcp started');
});
