# ARCHITECTURE.md — paperclipai Control Plane

## Status

Live. Last verified: 2026-04-27. Path B (openclaw-worker) confirmed working end-to-end via Phase 3B smoke test.

---

## Core philosophy

- One paperclip per client VPS. **paperclip is the brain.**
- paperclip's native auth (`pcp_board_*` API keys) is the ingress. No separate auth layer.
- External workers handle code execution; paperclip queues, workers claim.
- OpenRouter is the LLM provider for all reasoning. Anthropic Claude is the primary model class.
- Coolify manages the fleet: one VPS per client; per-VPS stack includes paperclip, openrouter-proxy, openclaw-worker, plus optional tools (n8n, Flowise, activepieces).

---

## Mental model

```
Agents think via API.
Agents act via executors.
Executors are replaceable.
No executor owns the workflow.
```

paperclip tracks all state. Workers are stateless consumers of the issue queue. If a worker dies mid-task, paperclip can reassign or the next poll cycle resets it.

---

## Execution paths

| Path | Executor | Status | Use for |
|------|----------|--------|---------|
| A | paperclip + OpenRouter (native LLM call) | Live | Planning, reasoning, decisions |
| B | OpenClaw via external worker (`openclaw-worker`) | Live — verified Phase 3B | Headless code execution (default) |
| B-alt | OpenCode (paperclip native adapter) | Roadmap — Phase 3C | Vendor-neutral fallback / second opinion |
| B-alt | Claude Code (paperclip native adapter) | Available, not yet configured | Anthropic-tuned tasks, exploratory |
| B-alt | Codex (paperclip native adapter) | Roadmap — Phase 3C | OpenAI-tuned tasks |
| D | Claude CLI on host | Non-canonical | Human-driven exploration only |

**NOTE on issue→PR work:** This runs through Path B (OpenClaw worker) with a PR-tuned system prompt on the assigned agent. There is no separate "Path C" executor for PR automation. Specialized PR workflow is a system prompt configuration, not an architectural component. The prior "Holon worker" idea was dropped — see `ROADMAP.md`.

---

## Component inventory

All apps deployed on the canonical VPS (`cfpa.sekuirtek.com`), managed by Coolify.

| App | Coolify UUID | Public URL | Role |
|-----|-------------|------------|------|
| paperclipai | `ihe84uqp2yr5bu9wd43w34dq` | `https://paperclipai.cfpa.sekuirtek.com` | The brain — issue tracker, agent orchestrator, auth |
| openrouter-proxy | `scc2ob001qhs6d16voewfy0r` | internal only (`openrouter-proxy:4001`) | Strips Claude-specific headers before forwarding to OpenRouter |
| openclaw-worker | `v3b2daw5wvaval2r6sb6mrxn` | internal only | Path B executor — polls, claims, runs OpenClaw |
| n8n | `tzek9xu60li84qqa8w68bgjh` | `https://n8n.cfpa.sekuirtek.com` | Automation workflows; calls paperclipai via board API key |
| Flowise | `hlw1a5tdz7mu9o4r183uq96y` | `https://flowise.cfpa.sekuirtek.com` | Visual LLM chain builder |
| activepieces | `l2wdubw2dwgfcaj38iidtcez` | `https://activepieces.cfpa.sekuirtek.com` | Automation alternative to n8n |

All containers run on the `coolify` Docker network. openrouter-proxy and openclaw-worker are `traefik.enable=false` — internal only.

### Decommissioned (fully deleted 2026-04-27)

| App | UUID | Why removed |
|-----|------|-------------|
| api-gateway | `fh3l092hvgk621zagxwg4non` | Redundant once paperclip handles its own auth |
| paperclip-backend | `kz9wfv4by3aggvz1eaw2kol4` | Custom FastAPI brain replaced by paperclipai |

See `PIVOT_TO_PAPERCLIP.md` for the full history. Code recovery via git history if ever needed.

---

## Data model

paperclip is multi-tenant. All entities live inside its embedded PostgreSQL (port 54329 inside the container).

| Entity | Notes |
|--------|-------|
| **Companies** | Top-level tenant. "Caring First" is the canonical company: UUID `bd80728d-6755-4b63-a9b9-c0e24526c820`, URL slug `CAR`. **Always use UUID in API calls — the slug never works as a path segment.** |
| **Agents** | Named actors within a company. CEO, Operator, and Code Execution Worker are provisioned. Workers are identified by UUID, not name. |
| **Issues** | The unit of work. Status lifecycle: `todo` → `in_progress` → `done` or `blocked`. Issues are assigned to an agent by UUID. Workers poll for `todo` issues assigned to their agent ID. |
| **Board API keys** | `pcp_board_<48 hex chars>`. SHA-256 hashed at rest. Scoped to the owning user's company memberships via UUID join. |

### Canonical agent UUIDs

| Agent | UUID |
|-------|------|
| Code Execution Worker | `e3e191c3-b7d4-4d2d-bfe4-2709db3b76a2` |

---

## Auth model

paperclip handles its own auth. There is no external auth layer.

**Board API keys** (`pcp_board_*` prefix):
- Issued once; plaintext shown at creation only — never stored.
- SHA-256 hash stored in `board_api_keys` table.
- Caller sends `Authorization: Bearer pcp_board_<token>`.
- paperclip hashes the token, looks up the key, resolves the owning user's `companyMemberships` to get `companyIds` (list of UUIDs).
- Route handlers call `assertCompanyAccess(companyId)` which compares against that UUID list.

**Critical gotcha — slug vs UUID:**
`/api/companies/{id}` endpoints compare `id` against UUID-based `companyIds`. The browser URL shows `CAR` (the company's `issue_prefix`), not the UUID. Passing `CAR` as the company ID always returns `"User does not have access to this company"` even with a valid key.

```bash
# Always use UUID:
GET /api/companies/bd80728d-6755-4b63-a9b9-c0e24526c820/issues   ✓
GET /api/companies/CAR/issues                                      ✗  → 403
```

See `RUNBOOK.md §3` for key issuance and revocation procedures.

---

## LLM routing

All Claude Code and OpenClaw invocations route through `openrouter-proxy:4001`, not directly to Anthropic.

```
Claude CLI / OpenClaw
        │  ANTHROPIC_BASE_URL=http://openrouter-proxy:4001
        ▼
openrouter-proxy (Coolify container scc2ob001qhs6d16voewfy0r)
        │  strips ?beta=true suffix
        │  strips anthropic-beta, anthropic-version headers
        │  forwards Authorization: Bearer <OPENROUTER_API_KEY>
        ▼
https://openrouter.ai/api/v1/messages
```

**Why the proxy exists:** The Claude Code CLI sends `POST /v1/messages?beta=true` with `anthropic-beta` headers. OpenRouter's `/api/v1` endpoint returns 404 on the `?beta=true` suffix. The proxy strips those before forwarding.

**OpenRouter model names:** Use `anthropic/claude-sonnet-4-6` in `openclaw.json`. OpenRouter accepts Anthropic short-form names (`claude-sonnet-4-6`) in the messages API too.

**Cost:** ~5% markup over Anthropic list pricing. Single key for all agents; routing flexibility (can add `openai/gpt-*` or `google/gemini-*` without new accounts).

---

## What this document is NOT

- Not a build guide — see `RUNBOOK.md` for ops procedures.
- Not a roadmap — see `ROADMAP.md`.
- Not a historical record of the pivot — see `PIVOT_TO_PAPERCLIP.md`.
- Not a reference for the old FastAPI brain — see git history pre-commit `684694f`.
