# ARCHITECTURE.md — paperclipai Control Plane

## Status

**v3.4 — MSP-managed AI services for SMBs.** This document describes both the live system (sections 1–10, deployed and working) and the target architecture (section "Target architecture (in flight)") that closes the gap to a productized MSP AI-services offering.

Live deployment last verified 2026-04-28: Path B (openclaw-worker) and OpenCode native adapter both confirmed working end-to-end (Phase 3B + Phase 3C smoke tests). Target architecture phases (5.5–21) tracked in `ROADMAP.md`. Add-on service catalog in `ADD_ON_SERVICES.md`. End-to-end readiness in `PLATFORM_READINESS.md`.

**Positioning (resolved 2026-05-02):** the platform is an AI services layer added to an existing MSP business. Tony is an MSP serving SMB clients across 5 verticals (legal, medical, accounting, home services, real estate). The control-plane platform automates AI ops for these clients as an upsell to the existing managed services relationship.

**Commercial structure:**
- Base tier ($499 Starter / $1,499 Pro / $4,999 Enterprise) — every paying client gets the AI ops foundation
- Add-on services — plug-and-play modular services (Voice/Marketing/Sales/Support/etc.) priced separately and installed per-client based on what they buy
- Vertical bundles — pre-packaged combinations for each vertical (Medical Practice Bundle, Legal Firm Bundle, etc.)
- See `ADD_ON_SERVICES.md` for the full catalog

**Architectural canonical pattern (resolved 2026-05-02):**
- One client per VPS. Per-VPS isolation is the MSP-aligned moat — clients trust dedicated infrastructure they pay for. Pods (multi-client per VPS) is a future option deferred until client count justifies it; not the canonical pattern.
- Multi-provider tiered. Hostinger for non-compliance (~$15-30/mo VPS), Linode Business for HIPAA / compliance (~$45-60/mo VPS, BAA available), AWS EC2 for premium / enterprise (~$80-150/mo VPS). Same git repo, same software stack, deployed to whichever VPS provider matches the client tier.
- IaC-automated at 3-5 client scale (Terraform + Ansible — see ROADMAP Phase 5.7).
- Single Coolify control instance orchestrates all client VPSes regardless of provider.

Differentiates from competitors via: existing MSP relationships (warm pipeline), per-client managed-service value (vs self-serve SaaS), vertical workflow depth via add-on extensions (vs horizontal AI assistants), dedicated infrastructure (vs shared SaaS), HIPAA-and-other compliance posture (vs consumer-grade tools). Competitive set is other MSPs not yet offering productized AI services, not Lindy / Zapier / Beam AI direct-to-business plays.

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
| B-alt | OpenCode + `anthropic/` model (paperclip native adapter) | Live — verified Phase 3C | Production code execution; `opencode-agent` uses `claude-sonnet-4-6` |
| B-alt | OpenCode + `opencode/` preset model (paperclip native adapter) | Live — verified 2026-04-28 | Free-tier / housekeeping; `opencode-free-agent` uses `nemotron-3-super-free`, $0.00/run |
| B-alt | Claude Code (paperclip native adapter) | Available, not yet configured | Anthropic-tuned tasks, exploratory |
| D | Claude CLI on host | Non-canonical | Human-driven exploration only |

**OpenCode model prefix determines API routing** — `anthropic/` and `opencode/` both work via OpenRouter; `openai/` is structurally broken (Responses API). See `RUNBOOK.md §4`.

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
| paperclip-mcp | `p13q05uj5ehqi866jp27g6fg` | internal only (port 9011) | Operator MCP — exposes paperclip REST API as MCP tools so Claude CLI manages paperclipai conversationally instead of via curl/psql |
| client-knowledge-db | `xcn2es4vmn01a1ug0w99vdr3` | internal only | Phase 6 RAG: shared Postgres + pgvector. Hosts `client_knowledge` database (schema deployed, ingestion + retrieval pending Phase 6 Stages 2-3); `openclaw` database reserved for future openclaw vector use |
| cfpa-watchdog | standalone docker (not Coolify-managed) | internal only | Cost watchdog — polls costs/by-agent, pauses agents on threshold breach. See RUNBOOK §8 |
| langfuse-web (etc.) | self-hosted on srv1408380 | `https://langfuse.cfpa.sekuirtek.com` | LLM observability + trace store. PR #22 instrumented openrouter-proxy and openclaw-worker for trace emission |

All containers run on the `coolify` Docker network. openrouter-proxy, openclaw-worker, paperclip-mcp, client-knowledge-db are `traefik.enable=false` — internal only.

### Decommissioned (fully deleted 2026-04-27)

| App | UUID | Why removed |
|-----|------|-------------|
| api-gateway | `fh3l092hvgk621zagxwg4non` | Redundant once paperclip handles its own auth |
| paperclip-backend | `kz9wfv4by3aggvz1eaw2kol4` | Custom FastAPI brain replaced by paperclipai |

See `PIVOT_TO_PAPERCLIP.md` for the full history. Code recovery via git history if ever needed.

---

## Canonical deployment pattern — 1-per-VPS, multi-provider, IaC-automated

This section documents the canonical pattern for deploying the platform per client. Resolved 2026-05-02.

### One client per VPS

Each paying client gets a dedicated VPS running their own paperclipai + workers + observability stack. Per-VPS isolation is the MSP-aligned architectural pattern — clients pay for managed-service-with-dedicated-infrastructure, which is what their existing MSP relationship trains them to expect. Multi-tenant SaaS undermines the managed-service value proposition; per-VPS reinforces it.

This means:
- Client A's data, agents, workflows, and configurations live entirely on their VPS
- Client B's failure modes never affect Client A
- Per-client compliance is a per-VPS decision (HIPAA medical client gets BAA-covered host; non-compliance retail client doesn't pay for compliance overhead)
- Per-client capacity scaling is independent (resize one VPS without affecting others)
- Per-client provider choice is independent

### Provider tiering

Each VPS is hosted on whichever provider matches the client's compliance and pricing tier:

| Tier | Provider | VPS sizing | Compliance | Per-VPS cost |
|------|----------|------------|------------|--------------|
| General SMB (non-compliance) | Hostinger | KVM 2-4 (4-8GB RAM) | None | $15-30/mo |
| Compliance (HIPAA, SOX, legal privilege) | Linode/Akamai Business | KVM 8GB+ | BAA available, SMB-friendly pricing | $45-60/mo |
| Premium / Enterprise | AWS EC2 | m5.large or larger | Full AWS BAA, native Bedrock integration | $80-150/mo |

The provider choice is made per-client at onboarding based on their needs. All providers run identical software stacks — same paperclipai, same workers, same observability, same git repo. The difference is purely the underlying infrastructure tier.

### Single Coolify control instance

A single Coolify instance (currently on the control VPS at 187.77.213.142) manages all client VPSes regardless of provider. Adding a new VPS = adding a server to Coolify with SSH credentials. Deploying code = git push triggers Coolify to deploy to all relevant VPSes in parallel.

This means:
- One source of truth for deployments (Coolify dashboard)
- One git repo deploys everywhere
- Multi-provider ops is one operational workflow, not three
- Same monitoring, alerting, deployment patterns across the fleet

### IaC automation at 3-5 client scale

Once client count crosses 3-5, manual VPS provisioning becomes a real time sink. Phase 5.7 of `ROADMAP.md` introduces Infrastructure-as-Code automation:
- Terraform (or OpenTofu) declares VPSes per-client based on tier variables
- Ansible configures the OS, Coolify agent, firewall, monitoring agents
- Onboarding script orchestrates Terraform → Ansible → Coolify API → paperclipai company creation in one command
- State storage in S3 (~$0.10/mo)

Cost: $0 in tooling licenses, ~3 weeks engineering investment. Pays back within 5-7 client onboardings.

### Deployment topology at scale

```
                  ┌──────────────────────────────────┐
                  │ Coolify Control + Langfuse       │
                  │  187.77.213.142                  │
                  └────────────────┬─────────────────┘
                                   │ manages all servers below
        ┌──────────────────────────┼──────────────────────────────┐
        ▼                          ▼                              ▼
┌────────────────────┐   ┌────────────────────┐         ┌────────────────────┐
│   HOSTINGER        │   │   LINODE Business  │         │   AWS EC2          │
│   (general SMB)    │   │   (HIPAA / compl)  │         │   (premium)        │
├────────────────────┤   ├────────────────────┤         ├────────────────────┤
│ Client A VPS       │   │ Caring First VPS   │         │ Enterprise client  │
│  (retail)          │   │  (medical)         │         │  (high-value)      │
│ ~$15/mo            │   │ ~$45/mo            │         │ ~$80-150/mo        │
├────────────────────┤   ├────────────────────┤         └────────────────────┘
│ Client B VPS       │   │ Medical Client #2  │
│  (real estate)     │   │  ~$45/mo           │
│ ~$15/mo            │   ├────────────────────┤
├────────────────────┤   │ Law Firm VPS       │
│ Client C VPS       │   │  ~$45/mo           │
│  (accounting)      │   └────────────────────┘
│ ~$15/mo            │
└────────────────────┘
```

Same codebase. Different VPS providers. Per-client tier choice. This is the architecture-of-record going forward.

### Considered and deferred: pod model (5-clients-per-VPS)

The "pod" pattern (5 clients sharing one VPS with paperclipai's native multi-company support) was extensively considered 2026-05-02 and deferred — not the canonical pattern.

Reasons:
- 1-per-VPS aligns with MSP managed-service value proposition; pods undermine it
- Per-VPS isolation is a marketing point clients value; pod isolation is invisible
- Tenant-scoping bugs in custom code = data leakage between clients on same pod = catastrophic for HIPAA
- Operational complexity savings of pods only matter past ~15-20 clients; 1-per-VPS + IaC handles 1-15 clients cleanly
- Compliance is simpler per-VPS (per-client BAA chain) than per-pod (mixing rules)

Pod model remains an option for the future as a low-tier offering when client count exceeds ~15-20 and ops burden justifies engineering investment. If introduced, pods serve only the lowest-cost tier (general SMB on shared infrastructure); compliance and premium clients always remain 1-per-VPS as upsell. Not on the current roadmap.

---

## Data model

paperclip is multi-tenant. All entities live inside its embedded PostgreSQL (port 54329 inside the container).

| Entity | Notes |
|--------|-------|
| **Companies** | Top-level tenant. "Caring First" is the canonical company: UUID `bd80728d-6755-4b63-a9b9-c0e24526c820`, URL slug `CAR`. **Always use UUID in API calls — the slug never works as a path segment.** |
| **Agents** | Named actors within a company. CEO, Operator, and openclaw-agent are provisioned. Workers are identified by UUID, not name. |
| **Issues** | The unit of work. Status lifecycle: `todo` → `in_progress` → `done` or `blocked`. Issues are assigned to an agent by UUID. Workers poll for `todo` issues assigned to their agent ID. |
| **Board API keys** | `pcp_board_<48 hex chars>`. SHA-256 hashed at rest. Scoped to the owning user's company memberships via UUID join. |

### Canonical agent UUIDs

| Agent | UUID |
|-------|------|
| openclaw-agent | `e3e191c3-b7d4-4d2d-bfe4-2709db3b76a2` |
| opencode-agent | `0930e444-c1f1-43ee-9b10-98e67b3daa44` |
| opencode-free-agent | `513f5d7f-aba3-43fe-9d97-25a22fb3cc2e` |

---

## Agent runtime model — heartbeats, memory, skills

paperclip agents do **not** run continuously. Each agent runs in **heartbeats**: short execution windows where the configured adapter (Claude CLI, OpenCode, OpenClaw, etc.) is launched, given prompt + context, runs to completion or timeout, and exits. Continuity across heartbeats is preserved by adapter session IDs and database state — not by a long-lived process.

### Wake sources

An agent wakes via one of four triggers (`docs/agents-runtime.md` in `paperclipai/paperclip`):

| Source | When |
|--------|------|
| `timer` | scheduled interval (configurable per agent, e.g. every 5 min) |
| `assignment` | work assigned/checked out to the agent |
| `on_demand` | manual wakeup via UI button or API |
| `automation` | system-triggered (future) |

If a heartbeat is already running when a new wake fires, paperclip **coalesces** the wake — no duplicate runs. Wake context (`PAPERCLIP_WAKE_REASON`, `PAPERCLIP_TASK_ID`, `PAPERCLIP_WAKE_PAYLOAD_JSON`, etc.) is injected as env vars into the adapter process.

### Memory: three layers

Memory in paperclip has three distinct layers, each serving a different purpose:

**1. Adapter session memory (conversational context).** Each resumable adapter (Claude CLI, OpenCode, etc.) has its own native session that persists across heartbeats. paperclip stores the session ID in `agent_runtime_state.session_id`; the next heartbeat re-launches the adapter with `--resume <id>` (or equivalent) so the model's conversation context carries over. Reset via the agent's "session reset" UI control when the agent is stuck or you've changed prompt strategy. **This is where most "agent memory" lives** — it's owned by the adapter, not by paperclip.

**2. Agent runtime state (`agent_runtime_state` table).** One row per agent. Tracks: current `sessionId`, `lastRunId`, `lastRunStatus`, cumulative `totalInputTokens` / `totalOutputTokens` / `totalCachedInputTokens` / `totalCostCents`, `lastError`, free-form `stateJson`. This is paperclip's view of what the adapter did, not the adapter's internal context.

**3. File-based PARA memory (optional, per-agent skill).** Agents that install the `para-memory-files` skill get a structured file system at `$AGENT_HOME/`:

- `$AGENT_HOME/life/` — knowledge graph in PARA folders (Projects / Areas / Resources / Archives), each entity with `summary.md` + atomic facts in `items.yaml`
- `$AGENT_HOME/memory/YYYY-MM-DD.md` — daily notes / raw timeline
- `$AGENT_HOME/MEMORY.md` — tacit knowledge about the user's operating patterns

This layer is *durable*, *human-readable*, and *survives session resets*. Agents extract durable facts from conversation into Layer 3 during heartbeats; the conversational session (Layer 1) can be reset without losing knowledge.

### Heartbeat audit trail

Every heartbeat is recorded in two tables:

| Table | Purpose |
|-------|---------|
| `heartbeat_runs` | one row per run: status (`queued`, `running`, `succeeded`, `failed`, `timed_out`, `cancelled`), exitCode, token usage, cost, error text |
| `heartbeat_run_events` | structured events within a run (assignments, status updates, comments posted, etc.) |

Used for observability and for the watchdog (§8 of `RUNBOOK.md`) — it queries `costs/by-agent` derived from these tables.

### Agent prompts (system prompts)

Each agent has a **prompt template** in its `runtimeConfig.promptTemplate` field. Variables like `{{agent.id}}`, `{{agent.name}}`, run context, and wake payload are interpolated at heartbeat start. Changes to the prompt are tracked in `agent_config_revisions` (full before/after diff, `changedKeys`, who changed it, source: `patch` / `rollback` / etc.). This is the audit trail for "what was the agent told to do."

`bootstrapPromptTemplate` is deprecated — new agents use the **managed instructions bundle system** which composes prompt templates with assigned skills (below).

### Skills: portable, versioned capability bundles

A **skill** is a markdown-defined capability that an agent can install. Skills are stored in `company_skills` (per-company, scoped) and shipped as markdown + optional file inventory.

| Field | Purpose |
|-------|---------|
| `key` | unique identifier within company (e.g. `paperclip`, `para-memory-files`) |
| `markdown` | the SKILL.md body — instructions the model reads at heartbeat start |
| `fileInventory` | additional files bundled with the skill (references, scripts) |
| `sourceType` / `sourceLocator` / `sourceRef` | where the skill came from (`local_path`, `git`, etc.) for reproducibility |
| `trustLevel` | `markdown_only` (no scripts run) up through trusted execution levels |
| `compatibility` | `compatible` / version pin |

**Built-in skills** shipped with paperclip (in `skills/` of `paperclipai/paperclip`):

- `paperclip` — the canonical heartbeat procedure (how to check assignments, post comments, manage routines, call paperclip API). Every agent installs this.
- `paperclip-converting-plans-to-tasks` — turning plans into trackable tasks
- `paperclip-create-agent` — creating new agents from inside an agent
- `paperclip-create-plugin` — creating paperclip plugins
- `paperclip-dev` — paperclip-internal development workflows
- `para-memory-files` — the file-based PARA memory system described above

Skills are designed to be **portable** — the same `para-memory-files` skill markdown can be installed in any paperclip company, and an agent's resulting memory files are reproducible from the skill + the agent's accumulated history.

### Configuration lives in paperclipai, not in this repo

Agent definitions, system prompts, runtime config, and skill installations all live inside paperclipai's database (`agents`, `agent_runtime_state`, `agent_config_revisions`, `company_skills`) and are managed via the paperclipai UI or REST API. There is no file-based configuration for them in this repo. The skills *themselves* (the SKILL.md content) live in `paperclipai/paperclip` upstream — companies install them by reference, not by checking them into per-VPS repos.

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

**Cost:** ~5% markup over Anthropic list pricing. Single key for `anthropic/*` and `opencode/*` models. `openai/*` models via OpenCode are not viable — see `RUNBOOK.md §4` for the prefix routing rule.

---

## Target architecture (in flight) — high-end SMB business OS

The sections above describe the live system as of 2026-04-30. This section captures the planned direction — components that close the gap between "capable agentic platform" and "business operating system for SMBs." Each component has a Phase number in `ROADMAP.md` and a concrete tech choice; nothing here is research-grade.

The bar this section is being written to: a sophisticated SMB buyer asking "why you instead of Microsoft Copilot, Notion AI, or Zapier AI" should have a credible, specific answer once these are in place.

### 1. Knowledge layer — RAG over client data (Phase 6)

**Gap:** the live system has no way to answer questions about the client's own documents, email history, contracts, or operational records. Agents reason from short-term context only. For a system positioned as the client's "operating system," this is the single largest credibility hole.

**Target:** per-VPS vector store via **pgvector** (already on Postgres — no new database). An ingestion worker watches client data sources (Gmail, Drive, Dropbox, Box, custom S3) and writes embeddings + chunked content into `client_documents` and `client_document_chunks`. Retrieval is exposed as an MCP tool `search_client_knowledge(query, scope)` that any agent can call. Per-document ACLs enforce which agents can see what.

**Why pgvector vs Qdrant/Weaviate:** simpler ops (one DB), good enough up to ~10M chunks per client, no separate service to back up. Revisit if a client crosses 50M+ chunks.

### 2. Browser-use worker — Path C executor (Phase 7)

**Gap:** `openclaw-worker` is Path B for code execution. Most SMB workflows touch SaaS tools that don't have clean APIs (mid-tier CRMs, scheduling tools, helpdesks, accounting). Agents currently can't drive those.

**Target:** new worker container `browseruse-worker` polling the same paperclip queue, executing tasks via Anthropic Computer Use (or the Browser Use library) inside an ephemeral Chromium env. Same MCP-style tool surface as openclaw-worker. Path C in the execution paths table once shipped.

**Decision pending:** Computer Use vs Browser Use vs a custom Playwright wrapper — evaluate against the actual SaaS tools the first vertical needs to drive.

### 3. Evaluation and regression layer (Phase 8)

**Gap:** every agent prompt change is currently a leap of faith. No regression suite, no offline evals, no replay-based testing. The first big client incident will be unexplainable without this.

**Target:** Langfuse already collects traces. Layer **Promptfoo or Braintrust** on top for offline eval. Per-workflow eval suites run on a sample of historical traces every time the prompt changes. Block prompt deploys when the regression score drops below threshold. CI integration so this fires on every PR touching prompts or skills.

### 4. End-client UI (Phase 9)

**Gap:** paperclipai's UI is an operator console — useful for the operator, useless for the SMB owner. There is no daily-driver interface for the actual client.

**Target:** separate Next.js app per VPS, deployed alongside paperclipai, scoped to the client's workflows. Conversational front door, document drop zone, agent activity feed, calendar view, human-in-the-loop approval queue, "what did my agents do today" digest. Calls paperclipai's REST API via the client's session — no direct DB access. Branded per-client.

### 5. Multi-agent collaboration patterns (Phase 10)

**Gap:** CEO, Operator, and specialist agents exist as separate actors but they're not collaborating on shared tasks. The frontier in 2026 is hierarchical/parallel multi-agent systems with delegation, criticism, and judging.

**Target:** add three patterns to paperclip's agent runtime: hierarchical delegation (CEO plans, specialists execute, judge closes), debate (two agents propose, third judges), review gate (sensitive workflows require critic sign-off). paperclip's `issue_relations` and `issue_approvals` tables already support this; the orchestration logic is the missing piece.

### 6. Event-driven wake sources (Phase 11)

**Gap:** agents wake on `timer` / `assignment` / `on_demand` / `automation`. External events from the client's tools (email arrived, payment failed, calendar invite received, customer texted) are not first-class wake sources — they must be polled by n8n and converted to assignments.

**Target:** treat n8n webhooks as first-class wakes. Extend `agent_wakeup_requests` with `external_event` source type. Webhook payload becomes part of `PAPERCLIP_WAKE_PAYLOAD_JSON` so the agent has full event context on wake without an extra round-trip.

### 7. Workflow library — vertical or horizontal (Phase 12)

**Gap:** SMBs buy outcomes, not infrastructure. The current platform can theoretically do anything; out-of-the-box it does nothing concrete. Each new client today is a custom build.

**Target:** ship a library of pre-built workflows: lead qualification, invoice processing, support triage, appointment scheduling, contract review, weekly reporting, customer onboarding. Each is a paperclip skill bundle + n8n workflow + agent assignments + eval suite. Library depth depends on whether the platform stays horizontal or picks a vertical (open question, see below).

### 8. Voice interface (Phase 13, year 2)

**Gap:** in 2026 voice is the front door for SMB customer interaction. Without it, the platform is a backend, not an OS.

**Target:** **Pipecat or LiveKit** + a paperclip MCP tool that lets agents place outbound calls and answer inbound ones. Real-time voice models (OpenAI Realtime, Anthropic voice). Year-2 priority — defer until first 10 clients are stable on text/document workflows.

### Open strategic questions

These are not architectural decisions; they're product decisions that gate architectural ones.

- **Vertical or horizontal?** "Business OS for SMBs" horizontal is hard to win. "Business OS for [accounting firms / medical practices / law firms / home services / real estate]" is 10x easier because workflows pre-build themselves and per-VPS isolation plays even better in compliance-heavy verticals. Decision needed before Phase 12.
- **Pricing tier structure.** Per-VPS monthly is good positioning, but flat-fee caps account expansion. Define Starter / Pro / Enterprise tiers gated on workflow count, agent count, or data volume.
- **Cross-client learning.** Per-VPS isolation prevents pattern learning across clients. Acceptable in v3.3; design a federated-learning story when fleet hits 10+ VPSes.

---

## What this document is NOT

- Not a build guide — see `RUNBOOK.md` for ops procedures.
- Not a roadmap — see `ROADMAP.md`.
- Not a historical record of the pivot — see `PIVOT_TO_PAPERCLIP.md`.
- Not a reference for the old FastAPI brain — see git history pre-commit `684694f`.
- Not a reference for OpenCode model routing behavior — see `RUNBOOK.md §4` for the prefix routing rule (`anthropic/` vs `opencode/` vs `openai/`).
