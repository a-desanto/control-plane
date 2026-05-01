# ROADMAP.md

Current architecture is stable. This file tracks what comes next.

For the current deployed state, see `ARCHITECTURE.md`.
For ops procedures, see `RUNBOOK.md`.

---

## Phase 3C — Enable OpenCode native adapter ✓ DONE

**Status:** Complete (2026-04-28). Two OpenCode agents live and verified:

- `opencode-agent` — `anthropic/claude-sonnet-4-6` via `ANTHROPIC_BASE_URL=http://openrouter-proxy:4001`
  - Smoke test CAR-6: exitCode 0, $0.077, billed via OpenRouter
  - Production-quality; use for real code execution tasks
- `opencode-free-agent` — `opencode/nemotron-3-super-free` via OpenRouter Chat Completions
  - Smoke test CAR-13: exitCode 0, $0.00, ~15 steps (more verbose than Claude Sonnet)
  - Free-tier only; use for housekeeping, triage, dev/test — not production code work

No new containers required — paperclip's heartbeat drives execution directly for both.

**Key finding:** OpenCode's model prefix determines API routing, not the model name. `anthropic/`
and `opencode/` both work via OpenRouter. `openai/` is structurally broken — see `RUNBOOK.md §4`
and "Explicitly dropped" section below.

---

## Phase 4 — OpenClaw Gateway native adapter migration

**Status:** Blocked on upstream paperclip release.

paperclip's adapter dropdown lists "OpenClaw Gateway (gateway)" as *Coming soon*. When it ships:
1. Create an agent in paperclip with adapter type `OpenClaw Gateway`, point it at the OpenClaw instance URL.
2. Delete `workers/openclaw-worker/` from this repo.
3. Remove the Coolify app `v3b2daw5wvaval2r6sb6mrxn`.

The issue queue and API key stay the same. This is a shrink-the-surface-area change, not a feature.

---

## Phase 5 — Per-VPS Coolify template for new clients

**Status:** Not started.

Export the current Coolify project state (paperclipai + openrouter-proxy + openclaw-worker + n8n + ancillary) as a deployable template. Document the onboarding flow in `RUNBOOK.md`:

```
Coolify → Add Server → apply template → set per-client env vars
  → bootstrap company in paperclip → issue first API key → verify health
```

**SMB-safe defaults that MUST bake into the template** (lessons from the 2026-04-30 cost runaway — see `RUNBOOK.md §8`):

- New agents ship with `runtime_config.heartbeat.enabled: false`. Agents wake on assignment only until the operator opts into a timer for a specific workflow. The historic upstream default of `enabled: true` + 300s interval is an SMB-hostile setting — idle agents bleed money on no-op heartbeats.
- cfpa-watchdog ships with `PER_HOUR_MAX_USD=1.00` (not 8.00). Catches slow drips at single-digit dollars instead of $30+.
- Onboarding flow asks "which agents should currently spend nothing?" and writes per-agent `WATCHDOG_AGENT_<UUID>_PER_HOUR_MAX_USD=0.10` overrides for those.

**Open input:** Decide which optional apps (Flowise, activepieces) belong in the base template vs. added per-client.

---

## Phase 6 — Knowledge layer (RAG over client data)

**Status:** Not started. **Priority: highest** — this is the single biggest credibility gap for "client's operating system" positioning.

Add per-VPS pgvector store + ingestion worker for client documents (Gmail, Drive, Dropbox, etc.). Expose retrieval as MCP tool `search_client_knowledge(query, scope)`. Per-document ACLs scope which agents see what. Tables: `client_documents`, `client_document_chunks`. Embeddings via Anthropic, OpenAI, or Voyage.

**Acceptance:** new agent in paperclip can install the `client_knowledge` skill and answer "find that contract from 2023" against ingested data, returning citations. Re-ingest is incremental, not full-reindex.

**Open input:** which sources to support in v1 (Gmail/Drive minimum, full ingestion suite later?). Embedding provider. pgvector vs separate vector DB — recommendation: **pgvector**, keep ops simple; revisit at 50M+ chunks per client.

---

## Phase 7 — Browser-use worker (Path C executor)

**Status:** Not started. **Priority: high** — gates any workflow that touches a SaaS tool without an API.

New worker container `browseruse-worker`. Polls paperclip queue same as openclaw-worker. Executes via Anthropic Computer Use, Browser Use library, or a custom Playwright wrapper inside ephemeral Chromium env. Same MCP-style tool surface as existing workers.

**Acceptance:** an agent can complete a task in a SaaS tool that has no API (e.g., book an appointment in a niche scheduling system, file an entry in an industry-specific CRM, submit a form on a state regulator's portal).

**Open input:** Computer Use vs Browser Use vs custom Playwright — evaluate against the actual SMB SaaS tools the first vertical needs to drive.

---

## Phase 8 — Evaluation and regression layer

**Status:** Not started. **Priority: must-do before scaling past 3 clients.**

Langfuse already collects traces. Add Promptfoo or Braintrust for offline eval. Per-workflow regression suites run on sample historical traces every prompt change. CI integration blocks deploys when score drops > 5%.

**Acceptance:** changing a prompt template in `agent_config_revisions` triggers automatic regression run; merge blocked if score drops below threshold. Per-workflow eval coverage > 80% of production traces.

---

## Phase 9 — End-client UI

**Status:** Not started. **Priority: high — required before second client onboards.**

Separate Next.js app per VPS. Scoped to client's workflows. Conversational front door, document drop zone, agent activity feed, calendar view, approval queue, daily digest. Calls paperclipai's REST API via the client's session — no direct DB access. Branded per-client.

**Acceptance:** an SMB owner can log in, drop a document, ask an agent to do something, see what happened, approve a sensitive action — without ever touching paperclipai's operator UI. White-labelable per client.

---

## Phase 10 — Multi-agent collaboration patterns

**Status:** Not started.

Add hierarchical delegation, debate, and review-gate patterns to paperclip's orchestration. Existing `issue_relations` and `issue_approvals` tables already support the data model; the orchestration logic is the missing piece.

**Acceptance:** a workflow can specify "CEO plans, Operator executes, Critic reviews" and the orchestration runs that pattern end-to-end with audit trail. Debate pattern produces a judged decision with reasoning recorded.

---

## Phase 11 — Event-driven wake sources

**Status:** Not started.

Extend `agent_wakeup_requests` with `external_event` source type. n8n webhook payload becomes part of `PAPERCLIP_WAKE_PAYLOAD_JSON`. External events become first-class wake triggers — no polling.

**Acceptance:** an agent assigned to a workflow wakes within 30 seconds of an external event firing, with full event context already in its env. End-to-end latency for "customer emails → agent acts" under 60 seconds.

---

## Phase 12 — Workflow library (universal-first, vertical extensions)

**Status:** Not started. Strategy resolved 2026-04-30: **horizontal platform with vertical extensions** — build the universal SMB workflow set first (works for every client regardless of vertical), then layer vertical-specific workflows as individual clients pull on them.

### Universal SMB workflows (build first, ship to every client)

These are the workflows every SMB owner needs regardless of vertical. They are document-heavy and SaaS-tool-heavy, which means Phase 6 (RAG) and Phase 7 (browser-use worker) deliver maximum leverage here.

1. **Lead qualification** — inbound triage, scoring, routing
2. **Email / inbox management** — triage, drafting, follow-up reminders
3. **Invoice processing** — extraction, categorization, AP/AR tracking
4. **Document organization & search** — Phase 6 RAG layer in production form
5. **Meeting notes + follow-up tracking** — capture, action-item extraction, reminders
6. **Customer support triage** — ticket categorization, priority routing, draft responses
7. **Scheduling / appointment workflows** — calendar coordination, reminders, rescheduling

Each = paperclip skill bundle + n8n workflow + agent assignments + eval suite (Phase 8). Each ships with eval coverage > 80% before going to a paying client.

### Vertical-specific extensions (add as clients pull)

Layered on top of the universal seven. Tony's existing client relationships span all five verticals — extensions are added when a specific client's workflow needs them.

| Vertical | Vertical-specific workflows |
|----------|------------------------------|
| Legal | Contract review, conflict checking, billable-hour summarization |
| Medical | Intake forms, appointment reminders, claims status |
| Accounting | Client onboarding, document collection, deadline tracking |
| Home services | Dispatch logic, route optimization, follow-up estimates |
| Real estate | Listing sync, lead routing, contract chasing |

### Acceptance

- Every new client gets the universal seven on day one (live within 30 minutes of onboarding pick).
- 1-3 vertical-specific extensions per client based on their actual business.
- Each shipped workflow has an eval suite at >80% coverage.
- Positioning: "AI operating system for service businesses, with vertical extensions" — not "everything for everybody."

---

## Phase 13 — Voice interface (year 2)

**Status:** Deferred — year 2 priority.

Pipecat or LiveKit + paperclip MCP tool for inbound/outbound calls. Real-time voice models (OpenAI Realtime, Anthropic voice). First 10 clients should be stable on text/document workflows before voice ships.

**Acceptance:** an agent can answer an inbound call, identify the caller, run a workflow (e.g. take an appointment), and post the resulting issue/note back to paperclip. Outbound: an agent can place an outreach call from a campaign workflow.

---

## Open questions to resolve before scaling beyond one VPS

### Strategic / product

- **Vertical or horizontal?** "Business OS for SMBs" horizontal is hard to win — Microsoft, Notion, Zapier are all there with bigger libraries. "Business OS for [accounting firms / medical practices / law firms / home services / real estate]" is 10x easier because workflows pre-build themselves and the per-VPS isolation story plays even better in compliance-heavy verticals. **Decision needed before Phase 12.**
- **Pricing tier structure.** Per-VPS monthly is good positioning but flat-fee caps account expansion. Define Starter / Pro / Enterprise tiers — likely gated on workflow count, agent count, or data volume.
- **Cross-client learning.** Per-VPS isolation prevents pattern learning across clients. Acceptable in v3.3; design a federated or anonymized-pattern-sharing story when fleet hits 10+.

### Operational

- **Agent budget tracking:** How do paperclip's per-agent budgets interact with worker-claimed tasks? Verify cost from `openclaw-worker` invocations registers against the `openclaw-agent` budget cap.
- **Company portability:** Does paperclip's export feature work cleanly for the openclaw-worker setup, or does each new VPS need manual agent creation + key issuance?
- **OpenRouter key strategy:** Single shared key across fleet, or per-VPS keys for cost isolation and blast-radius control?

---

## Explicitly dropped

**OpenAI via OpenCode through OpenRouter — structurally blocked by Responses API routing.**
Two attempts, same root cause: OpenCode's `openai/` prefix unconditionally routes to Responses
API. OpenRouter does not implement it stably.

- *Codex CLI (attempt 1):* hardcodes `wss://api.openai.com/v1/responses` (WebSocket).
  Cannot redirect via `OPENAI_BASE_URL`. `codex-agent` exits 1 with `401 Unauthorized`.
- *OpenCode + `openai/gpt-4.1` (attempt 2):* routes to `openrouter.ai/api/v1/responses`
  (REST). Fails with Zod validation errors. Model selection (`gpt-4.1`, `gpt-4o`, etc.)
  is irrelevant — the prefix determines the path, not the model name.

`codex-agent` and `opencode-openai-agent` both deleted 2026-04-28. `OPENAI_BASE_URL` /
`OPENAI_API_KEY` removed from paperclipai env.

Workaround would require a direct OpenAI billing relationship (separate account, separate
key rotation per VPS). Requires explicit approval before implementing — see `RUNBOOK.md §4`.

---

**Holon worker (formerly "Phase 3C"):** Dropped. The original idea was a second worker container implementing a structured issue→PR lifecycle via the Holon protocol. This is unnecessary:

- An OpenClaw worker with a PR-tuned system prompt on the assigned agent handles issue→PR today.
- A specialized executor for one workflow pattern violates the "executors are replaceable" principle — the workflow should be a system prompt configuration, not an architectural component.
- Holon's specific niche is being absorbed by general-purpose agents and GitHub's first-party tooling.
- Adding another external worker with its own operational surface (container, polling loop, error modes) isn't worth it when the existing worker can do the same job.
