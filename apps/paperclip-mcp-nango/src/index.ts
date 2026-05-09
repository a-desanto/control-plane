/**
 * paperclip-mcp-nango — MCP server wrapping Nango self-hosted for paperclip agents.
 *
 * Exposes 4 tools to agents:
 *   - nango_list_connections(company_id?)         — list configured connections
 *   - nango_get_connection(provider, connection_id) — retrieve credentials/metadata
 *   - nango_proxy_get(provider, connection_id, endpoint)  — passthrough GET to provider API
 *   - nango_proxy_post(provider, connection_id, endpoint, body) — passthrough POST
 *
 * Per-client isolation: connection_id should be the company UUID so each client's
 * connections stay separate within Nango.
 *
 * Required env:
 *   NANGO_URL          — e.g. https://nango.cfpa.sekuirtek.com
 *   NANGO_SECRET_KEY   — server-side admin key (Nango admin UI → Environment Settings)
 */

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";

const NANGO_URL = process.env.NANGO_URL ?? "http://nango-server:3003";
const NANGO_SECRET_KEY = process.env.NANGO_SECRET_KEY ?? "";

if (!NANGO_SECRET_KEY) {
  console.error("FATAL: NANGO_SECRET_KEY not set");
  process.exit(1);
}

async function nangoFetch(path: string, init: RequestInit = {}): Promise<unknown> {
  const url = `${NANGO_URL.replace(/\/$/, "")}${path}`;
  const headers = {
    Authorization: `Bearer ${NANGO_SECRET_KEY}`,
    "Content-Type": "application/json",
    ...(init.headers ?? {}),
  };
  const r = await fetch(url, { ...init, headers });
  if (!r.ok) {
    const body = await r.text().catch(() => "");
    throw new Error(`Nango ${r.status} ${r.statusText} on ${path}: ${body.slice(0, 500)}`);
  }
  const ct = r.headers.get("content-type") ?? "";
  return ct.includes("application/json") ? r.json() : r.text();
}

const server = new Server(
  { name: "paperclip-mcp-nango", version: "0.1.0" },
  { capabilities: { tools: {} } }
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: "nango_list_connections",
      description: "List all Nango connections, optionally filtered by company_id (used as connection_id prefix).",
      inputSchema: {
        type: "object",
        properties: {
          company_id: { type: "string", description: "Optional company UUID to scope the list." },
        },
      },
    },
    {
      name: "nango_get_connection",
      description: "Fetch a single Nango connection's metadata + credentials. Use sparingly — credentials are sensitive.",
      inputSchema: {
        type: "object",
        properties: {
          provider_config_key: { type: "string", description: "The provider config key (e.g. 'hubspot', 'slack')." },
          connection_id:       { type: "string", description: "The connection ID (typically the company UUID)." },
        },
        required: ["provider_config_key", "connection_id"],
      },
    },
    {
      name: "nango_proxy_get",
      description: "Passthrough GET to the provider's API via Nango's proxy. Nango injects the right auth headers.",
      inputSchema: {
        type: "object",
        properties: {
          provider_config_key: { type: "string" },
          connection_id:       { type: "string" },
          endpoint:            { type: "string", description: "Provider-side path, e.g. '/v3/objects/contacts'" },
        },
        required: ["provider_config_key", "connection_id", "endpoint"],
      },
    },
    {
      name: "nango_proxy_post",
      description: "Passthrough POST to the provider's API via Nango's proxy. Use with care — this writes to the provider.",
      inputSchema: {
        type: "object",
        properties: {
          provider_config_key: { type: "string" },
          connection_id:       { type: "string" },
          endpoint:            { type: "string" },
          body:                { type: "object", description: "Provider-specific request body" },
        },
        required: ["provider_config_key", "connection_id", "endpoint", "body"],
      },
    },
  ],
}));

server.setRequestHandler(CallToolRequestSchema, async (req) => {
  const { name, arguments: args = {} } = req.params;

  try {
    switch (name) {
      case "nango_list_connections": {
        const cid = (args as { company_id?: string }).company_id;
        const path = cid ? `/connection?connectionId=${encodeURIComponent(cid)}` : "/connection";
        const result = await nangoFetch(path);
        return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
      }

      case "nango_get_connection": {
        const a = args as { provider_config_key: string; connection_id: string };
        const result = await nangoFetch(
          `/connection/${encodeURIComponent(a.connection_id)}?provider_config_key=${encodeURIComponent(a.provider_config_key)}`
        );
        return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
      }

      case "nango_proxy_get": {
        const a = args as { provider_config_key: string; connection_id: string; endpoint: string };
        const result = await nangoFetch(`/proxy${a.endpoint}`, {
          method: "GET",
          headers: {
            "Provider-Config-Key": a.provider_config_key,
            "Connection-Id": a.connection_id,
          },
        });
        return { content: [{ type: "text", text: typeof result === "string" ? result : JSON.stringify(result, null, 2) }] };
      }

      case "nango_proxy_post": {
        const a = args as { provider_config_key: string; connection_id: string; endpoint: string; body: unknown };
        const result = await nangoFetch(`/proxy${a.endpoint}`, {
          method: "POST",
          headers: {
            "Provider-Config-Key": a.provider_config_key,
            "Connection-Id": a.connection_id,
          },
          body: JSON.stringify(a.body),
        });
        return { content: [{ type: "text", text: typeof result === "string" ? result : JSON.stringify(result, null, 2) }] };
      }

      default:
        return { content: [{ type: "text", text: `Unknown tool: ${name}` }], isError: true };
    }
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e);
    return { content: [{ type: "text", text: `Error: ${msg}` }], isError: true };
  }
});

const transport = new StdioServerTransport();
await server.connect(transport);
console.error("paperclip-mcp-nango ready (stdio)");
