# BUILD_BRIEF.md

## paperclipai — Claude CLI Handoff (Python edition)

**Companion to:** `ARCHITECTURE.md` (v3.2)
**Audience:** Claude CLI working in `github.com/a-desanto/control-plane`
**Goal:** Take the existing minimal `paperclipai/` scaffold and build it out to the v3.2 architecture in phases that ship working software at every stop.

This document is a build plan, not a re-statement of architecture. When in doubt, read `ARCHITECTURE.md`. If the two disagree, `ARCHITECTURE.md` wins — open a PR to fix this brief.

---

## Stack decisions (locked)

These are decided. Don't relitigate without a written reason in this brief.

- **Language:** Python 3.12+
- **HTTP framework:** FastAPI (with `uvicorn[standard]` for dev, `gunicorn` + `uvicorn` workers for prod)
- **Runtime validation:** Pydantic v2 — generated from JSON Schema, never hand-edited
- **Schema codegen:** `datamodel-code-generator` (`schemas/*.json` → `paperclipai/app/contracts/`)
- **Database:** Postgres 16+ with `pgvector`. SQLAlchemy 2 (async) + Alembic for migrations
- **Cache / locks:** Redis (already running per Coolify state)
- **SSE:** `sse-starlette` (official FastAPI-compatible SSE library)
- **MCP client:** `mcp` Python SDK (Anthropic) for stdio + HTTP transport
- **Package management:** `uv` — single tool for resolution, install, and lock. Replace the existing `requirements.txt` with `pyproject.toml` + `uv.lock` in Phase 0
- **Testing:** `pytest` + `pytest-asyncio` + `httpx.AsyncClient` for FastAPI testing
- **Observability:** `structlog` for logs, `opentelemetry-instrumentation-fastapi` for traces, Langfuse SDK for LLM traces

The existing loose Python at `/root/` (`app.py`, `worker.py`, `intent_worker.py`, `intent-venv/`, `intent-worker/`, `workflow-api/`, `api-gateway/`) is not in the repo. Inventory it in pre-flight; fold what's worth keeping into the repo, delete the rest.

---

## 0. Pre-flight checklist

Run before opening a single editor tab. None of this should take more than a morning.

1. **Inventory the loose code at `/root/` on the VPS.** For each of `app.py`, `worker.py`, `intent_worker.py`, `api-gateway/`, `intent-worker/`, `workflow-api/`, `staged/`, decide: fold into `control-plane`, or delete. Anything that's actually serving traffic via Coolify gets folded. Anything that was an experiment gets deleted.
2. **Confirm the runtime stack on one VPS.** Pick the least-busy client VPS and use Coolify's terminal (no ad-hoc SSH per §2 invariant 13).
   - Postgres 16+ with `pgvector`? `CREATE EXTENSION IF NOT EXISTS vector;` if not.
   - Redis reachable from the paperclipai container?
   - api-gateway terminates TLS and forwards `/intent*` to paperclipai?
   - n8n's webhook base URL is HTTPS and reachable from the paperclipai container?
3. **Decide Flowise's fate.** Stays scoped to client-facing visual builds only, or gets removed in Phase 0. The existing `DECOMMISSION_PLAN.md` (now deleted) had a stub on this — write the real decision into this brief.
4. **Pick the pilot workflow.** Lead qualification (§17) is the canonical example unless there's a stronger candidate. Everything in this brief assumes one pilot before fleet-wide migration.
5. **Decide the Python service shape.** `paperclipai/app/` is the FastAPI service. Workers (e.g., the orchestration loop, sweeper, callback emitter) run as separate processes from the same container or as separate containers — pick one and stick with it. Recommendation: **single container, multiple processes via a process manager** (e.g., `honcho` or a Procfile pattern), keeps the Coolify deployment simple.

**Definition of done for pre-flight:** a one-page `PREFLIGHT.md` in the repo root that records the answers to 1–5 above. Future-you and Claude CLI will need it.

---

## 1. Phased migration

Each phase ships an end-to-end working slice. Don't start phase N+1 until phase N's acceptance criteria pass.

### Phase 0 — Repo layout, schemas, codegen (week 1)

**Outcome:** the repo physically matches the v3.2 layout. Pydantic models are generated from JSON Schema. No production behavior change yet.

**Steps:**

1. Bring the repo to canonical layout. Create what's missing; the existing `paperclipai/` stays where it is:
   ```
   control-plane/
   ├── ARCHITECTURE.md
   ├── BUILD_BRIEF.md
   ├── PREFLIGHT.md
   ├── README.md
   ├── paperclipai/                       ← FastAPI service (exists)
   │   ├── pyproject.toml                 ← replace requirements.txt
   │   ├── uv.lock
   │   ├── Dockerfile                     ← exists, needs rewrite
   │   ├── alembic.ini
   │   ├── migrations/                    ← Alembic
   │   └── app/
   │       ├── main.py                    ← FastAPI entrypoint
   │       ├── api/                       ← route handlers
   │       ├── contracts/                 ← codegen target (do not hand-edit)
   │       ├── orchestration/             ← decision loop, planner, adaptive engine
   │       ├── policy/                    ← policy evaluation stage
   │       ├── mcp_client/                ← MCP client layer
   │       ├── memory/                    ← Memory Interface
   │       ├── db/                        ← SQLAlchemy models, sessions
   │       └── obs/                       ← logging + tracing setup
   ├── mcp-servers/
   │   ├── cli/
   │   ├── llm/
   │   └── action/
   ├── agents/
   ├── adapters/
   │   ├── paperclipai/
   │   └── claude-platform/
   ├── schemas/                           ← JSON Schema 2020-12, source of truth
   ├── skills/
   ├── policies/                          ← YAML
   └── tool-registry/                     ← YAML, loaded into Postgres on startup
   ```
2. Author the four canonical schemas under `schemas/` verbatim from `ARCHITECTURE.md` §7A: `intent@v3.2.json`, `workflow_plan@v3.2.json`, `execution_instruction@v3.2.json`, `tool_output@v3.2.json`. Add fixtures under `schemas/fixtures/` (one good, one bad per schema).
3. Wire Pydantic codegen via `datamodel-code-generator`:
   ```
   datamodel-codegen \
     --input schemas/ \
     --input-file-type jsonschema \
     --output paperclipai/app/contracts/ \
     --output-model-type pydantic_v2.BaseModel \
     --use-schema-description \
     --target-python-version 3.12
   ```
   Add a `make codegen` target and a CI check that fails if `paperclipai/app/contracts/` is dirty after running codegen.
4. Move from `requirements.txt` to `pyproject.toml` managed by `uv`:
   ```
   uv init
   uv add fastapi uvicorn[standard] sse-starlette pydantic[email] \
          sqlalchemy[asyncio] asyncpg alembic redis structlog \
          opentelemetry-instrumentation-fastapi mcp httpx
   uv add --dev pytest pytest-asyncio httpx datamodel-code-generator ruff mypy
   ```
5. Stand up the contract table in Postgres via Alembic:
   ```
   alembic revision -m "create contracts and intents tables"
   ```
   `intents` table: immutable, indexed on `(caller_type, idempotency_key)`. `contracts` table: append-only, FK on `parent_contract_id`, indexed on `(intent_id, created_at)` and `workflow_id`.
6. Add Tool Capability Registry YAML format under `tool-registry/` with one stub entry (e.g., `noop_tool`) so the loader has something to read on boot.

**Acceptance criteria:**
- `make codegen` produces Pydantic v2 models from JSON Schema with zero hand edits.
- `pytest` passes schema round-trip tests: each schema validates a known-good fixture and rejects a known-bad one.
- `alembic upgrade head` creates the contract + intent tables; `alembic downgrade base` is clean.
- Tool registry loader reads the YAML on startup and logs the count.
- The container image built from the new Dockerfile starts and exposes `/health` returning 200.

### Phase 1 — Intent endpoint and 202 path (week 2)

**Outcome:** any caller can `POST /intent`, get a 202 with `intent_id`, and see the intent persisted. No execution yet.

**Steps:**

1. Implement `POST /intent` in `paperclipai/app/api/intent.py`. FastAPI handler validates against the generated `IntentV3_2` Pydantic model (validation is automatic via FastAPI's dependency on Pydantic). De-dup on `(caller_type, idempotency_key)` with a unique constraint at the DB layer. Persist immutably. Return 202 with `intent_id`, `audit_link`, `events_url`, `status_url`.
2. Implement `GET /intent/{id}/status`. Returns intent state + last-known contract.
3. Implement `GET /intent/{id}/events` as SSE using `sse-starlette`. For Phase 1 it can emit a single `accepted` event then close — Phase 2 fills in real events.
4. Wire api-gateway to route `/intent*` to paperclipai. Apply auth (existing api-gateway mechanism). Add a `caller_type` claim to the auth context, populated from the API key's metadata.
5. Drop a synthetic n8n workflow into the n8n instance: HTTP Request node hitting `POST /intent` with a hardcoded payload. Verify 202 returns. Verify a row in the intents table.

**Acceptance criteria:**
- A real n8n workflow successfully POSTs and gets 202 with all four URLs.
- A second POST with the same `(caller_type, idempotency_key)` returns the same `intent_id` (de-dup works).
- An invalid intent (missing `idempotency_key`, bad `caller_type`) returns 422 with a Pydantic-derived error pointing at the offending path.
- The intent row in Postgres is byte-identical to what was submitted (after defaulting/normalization).
- `pytest` integration tests use `httpx.AsyncClient` against the FastAPI app and a Postgres test container.

### Phase 2 — First MCP tool, end-to-end (week 3)

**Outcome:** a single tool runs through the full contract lifecycle. One agent, one workflow, one MCP server. No adaptation yet.

**Steps:**

1. Build the simplest possible MCP server: `mcp-servers/cli/echo-mcp/` in Python, using the official `mcp` SDK. Stdio transport. One tool call: `echo(text: str) → {text: str, length: int}`. Containerize it.
2. Register it in the Tool Capability Registry YAML. Pin its image digest.
3. Build the MCP Client Layer in `paperclipai/app/mcp_client/`. For Phase 2, hardcode stdio launch via `docker run --rm -i <digest>`. Validate input against the Pydantic model derived from `input_schema_ref` before invoke. Validate output against the model derived from `output_schema_ref` after.
4. Build the Execution Planner in its simplest form: given an intent with `requested_outcome: "echo_test"`, produce a one-step Workflow Plan that calls `echo`.
5. Build the orchestration loop as a separate async worker (started via the process manager): read intent → produce plan → persist plan → produce contract (`parent_contract_id` null) → invoke MCP → persist Tool Output → mark intent complete. Use Postgres `LISTEN/NOTIFY` or a polling task table; not a separate broker.
6. Wire SSE events: `contract_started`, `contract_completed`, `completed`. Test SSE from a curl one-liner.
7. Add a callback emitter: if the intent included `callback_url`, POST the final result to it. Test from n8n by setting `callback_url` to an n8n webhook on the same instance.

**Acceptance criteria:**
- `POST /intent` with `requested_outcome: "echo_test"` returns 202 and, within 5 seconds, fires the callback with status `completed`.
- The contract table has one row with the right `tool_name`, `tool_version`, `image_digest`, `parent_contract_id = null`.
- The Tool Output is persisted with `status: "success"` and validates against the output schema.
- Tearing down the echo MCP container mid-flight produces a `failed` contract with a structured error code (groundwork for Phase 4).
- The orchestration worker survives a `SIGTERM` and resumes pending intents on next start.

### Phase 3 — Real LLM tool + real workflow (week 4)

**Outcome:** the lead-qualifier agent's classification step runs end-to-end against a real model.

**Steps:**

1. Build `mcp-servers/llm/llm-router-mcp/` in Python. One tool call: `prompt_with_schema(prompt_template: str, vars: dict, output_schema_ref: str) → validated structured JSON`. Internally routes by `model_class` to Anthropic / OpenAI via their official SDKs. Output validation uses the same Pydantic model paperclipai uses on its side (shared via the `schemas/` tree).
2. Author the lead-qualifier agent under `agents/lead-qualifier/`:
   - `agent.yaml` per §21.4
   - `system_prompt.md`
   - `schemas/lead_intent_input@v1.json`
   - `schemas/lead_intent_output@v1.json`
3. Add a workflow definition `lead_qualification@v1.0.0` whose first step calls `classify_lead_intent` (the LLM MCP tool, `model_class: low_cost_extract`).
4. Update the Execution Planner to resolve `requested_outcome: "qualify_and_respond"` into the lead-qualifier agent + workflow.
5. Stand up Langfuse on the control VPS (if not already). Wire the LLM MCP server to emit traces using the Langfuse Python SDK with the contract's `trace_id`.
6. Run end-to-end from an n8n test workflow that POSTs a synthetic email payload.

**Acceptance criteria:**
- Real classification result arrives via callback, validates against `lead_intent_output@v1`.
- Langfuse shows a trace whose session correlates to the contract's `trace_id`.
- Cost recorded on the Tool Output's `metrics.cost_usd` matches Langfuse's reported cost (within rounding).
- Re-running the exact same intent (same `idempotency_key`) returns the prior result without invoking the model again.

### Phase 4 — Failure Classifier + Adaptive Execution (week 5)

**Outcome:** when a tool fails, paperclipai produces a new contract with `parent_contract_id` set, and recovery is auditable.

**Steps:**

1. Implement the Failure Classifier per §9 in `paperclipai/app/orchestration/classifier.py`. Layer 1 only initially: enumerated codes (`QUOTA_EXCEEDED`, `SCHEMA_VIOLATION`, `UPSTREAM_TIMEOUT`, `AUTH_FAILED`, `RATE_LIMITED`, `MODEL_REFUSED`). Map each to a default strategy (retry / fallback / degrade / escalate / halt) via a Python `Enum` + `match` statement.
2. Implement the four resolvers (Retry, Fallback, Degradation, Escalation).
3. Implement the Termination Guard. Enforce `max_chain_depth ≤ 5` and monotone cost on degrade. Hitting a limit → halt + escalate.
4. Wire the LLM MCP server to deterministically fail on a magic input (e.g., `vars.simulate_quota_exceeded: true`) so we can drive the classifier without burning real quota.
5. Add a fallback model class to the lead-qualifier workflow: primary `low_cost_extract`, fallback `balanced_writer_alt`.
6. Run the end-to-end example from §17 with the simulated failure.

**Acceptance criteria:**
- A simulated `QUOTA_EXCEEDED` produces contract `C3` (failed) and `C3'` (success, `parent_contract_id = C3`).
- The audit chain at `audit_link` shows both contracts with the right ordering.
- A simulated infinite-failure scenario (every model fails) terminates within `max_chain_depth` and emits `failed` with a chain-terminated error.
- The callback to n8n includes `adaptations_applied: 1` and the correct `cost_usd`.

### Phase 5 — HITL via awaiting_approval (week 6)

**Outcome:** the full §17 example runs end-to-end including human approval through n8n.

**Steps:**

1. Implement `POST /intent/{id}/resume` per §6.4. Validate the approval payload against the generated Pydantic model, persist as a new contract, resume the orchestration loop.
2. In the lead-qualifier workflow, mark `step_id: send_email` with `approval_gate: true`.
3. When the planner reaches an approval-gated step, emit `awaiting_approval` on callback + SSE, persist a pending-approval record, suspend the loop.
4. Build an n8n callback workflow that receives `awaiting_approval`, sends a Slack interactive message, and POSTs back to `/intent/{id}/resume` on button click.
5. Implement TTL expiry: an Alembic-defined sweeper task (run via the process manager on a 60s tick) marks expired approvals as `failed` and emits the final callback.

**Acceptance criteria:**
- The full §17 trace runs against real services: email arrives in Gmail, approval Slack message fires, button click resumes the workflow, real send_email and update_odoo MCP calls happen.
- The contract chain shows the approval contract (`A1`) between `C4` and `C6`.
- An expired approval (TTL=60s for testing) terminates correctly with `failed` and an audit-visible reason.
- A second approval attempt for an already-resolved approval returns 409 with a clear error.

### Phase 6 — Action MCP servers (week 7)

**Outcome:** all egress from paperclipai goes through Action MCP servers wrapping n8n webhooks. No direct integration calls in paperclipai code.

**Steps:**

1. Build one Action MCP server per integration we need: `send-email-mcp`, `update-odoo-mcp`, `notify-slack-mcp`. Python, HTTP transport, internally `httpx.post` to a designated n8n webhook.
2. For each, define n8n workflows that the webhook drives — these are the "action recipes" that own the integration SDK.
3. Register all Action MCP servers in the Tool Capability Registry with `declared_side_effects` populated.
4. Audit paperclipai's source for any direct `httpx`/`requests` to external services. There should be exactly zero outside the MCP Client Layer.

**Acceptance criteria:**
- `grep -rE 'gmail|odoo|slack|stripe' paperclipai/app/ --include='*.py'` returns matches only inside `mcp_client/` and tests.
- Every contract that produces an external side effect has a non-empty `declared_side_effects` array, and the corresponding Tool Output's `side_effects_observed` is a subset.
- Disabling the n8n container makes Action MCP calls fail with a structured error (not a hang).

### Phase 7 — Fleet rollout (week 8+)

**Outcome:** the v3.2 stack runs on every client VPS, replacing whatever was there before.

**Steps:**

1. Bake the v3.2 Coolify template: paperclipai, n8n, api-gateway, postgres, redis, plus the registered MCP server containers.
2. Migrate one pilot client VPS first. Run both old and new in parallel for 48 hours, comparing outputs on a small sample of intents.
3. Cut the pilot client over. Monitor Langfuse for 1 week before continuing.
4. Roll out the rest of the fleet via Coolify, one VPS per day.
5. Decommission Flowise (if removed in pre-flight) and any duplicate Odoo services. Remove the loose `/root/*.py` files that were inventoried in pre-flight.

**Acceptance criteria:**
- Every client VPS runs the same set of services with the same versions.
- A single Git push deploys to one VPS via Coolify; redeploying takes < 2 minutes.
- Adding a new client = provision VPS → Coolify add server → apply template → done in under 30 minutes.
- `/root/` on every VPS contains nothing application-related except what Coolify owns.

---

## 2. Anti-patterns to avoid

These are the failure modes the v3.2 design specifically forbids. Watch for them in PRs.

- **Decisions in MCP servers.** No retries, no fallback logic, no "if this fails, try X" in tool code. The MCP server validates input, executes, returns. Adaptive Engine handles everything else.
- **Bypassing the contract.** Any code path that produces an AI output without a corresponding contract row in Postgres is a bug. No "just for testing" shortcuts in production paths.
- **Direct integration calls from paperclipai.** Egress is via Action MCP servers only. Adding `httpx.post('https://api.gmail.com/...')` to paperclipai is an architectural violation.
- **Mutating an existing contract.** Contracts are append-only. Adaptation creates a *new* contract with `parent_contract_id` set. Updating a contract row to record retry results is forbidden.
- **State held in MCP servers.** MCP servers are stateless per invocation. If a tool needs cached state, paperclipai's Memory Interface owns it.
- **Cross-tenant leakage.** One client = one VPS = one Postgres. No "shared" tables across clients. The control VPS holds Langfuse and Coolify only — no per-client business data.
- **Skipping Policy Evaluation.** Every contract goes through the Policy Evaluation Stage, even "obviously safe" ones. The audit value comes from uniformity.
- **Calling paperclipai from anywhere except api-gateway.** Internal services do not bypass the gateway. If a service needs to call paperclipai, it goes through the gateway like any other caller.
- **Hand-editing generated Pydantic models.** Files under `paperclipai/app/contracts/` are codegen output. Edit the JSON Schema source and re-run `make codegen`.
- **Editing live on the VPS.** `worker.py.bak` and the orphan `/root/.git` we saw in pre-flight are the symptoms. Edits happen on a laptop or in a Codespace, get committed, and Coolify deploys. Direct VPS edits are how you end up with state nobody can reproduce.
- **Long-lived branches.** Each phase ships to main. If a phase is taking more than its target week, cut a smaller slice and ship — don't hold a branch.
- **`requirements.txt` regrowing.** Once Phase 0 moves to `pyproject.toml` + `uv`, anything that adds a `requirements.txt` is a regression.

---

## 3. Definition of done (project-level)

The migration is complete when all of the following are true:

1. Every client VPS runs the v3.2 stack from a single Coolify template.
2. Every AI output in production has a contract row, an audit chain, and a Langfuse trace.
3. `agents/lead-qualifier/` (and any other migrated agents) deploys to both paperclipai and platform.claude.com via the adapters in `adapters/`.
4. The four canonical schemas in `schemas/` are the only source of truth for runtime types — Pydantic v2 models are generated, never hand-edited.
5. There is exactly one ingress point (api-gateway) and one decision system (paperclipai) per VPS.
6. Replay works: pick any production intent from the last 30 days; transcript replay reproduces the same outputs.
7. A new client can be onboarded end-to-end (provision → first successful intent) in under 30 minutes.
8. The loose `/root/*.py` files inventoried in pre-flight are either folded into the repo or removed from every VPS.
9. Documentation: this brief is closed out, `ARCHITECTURE.md` is current, the per-VPS runbook lives in the repo.

---

## 4. Working with Claude CLI

Notes for the human running Claude CLI on this brief.

- **Hand it the architecture and this brief together.** Don't paraphrase the architecture in chat — point Claude CLI at the files. `ARCHITECTURE.md` is the source of truth; this brief is the work plan.
- **Run one phase at a time.** Don't ask Claude CLI to "do phases 0–4" in one sitting. Each phase has acceptance criteria for a reason.
- **Make Claude CLI write the tests first.** The acceptance criteria translate cleanly into `pytest` tests. Have those land before the implementation.
- **Resist scope creep into adjacent phases.** If Phase 2 finds a bug that wants to be fixed in Phase 4, write it down in this brief instead of doing it now.
- **Keep the architecture honest.** If implementation reveals that a section of `ARCHITECTURE.md` is wrong or unclear, fix the architecture in the same PR that exposes it. Drift between design and code is the enemy.
- **Run Claude CLI on a laptop checkout, not on the VPS.** The VPS is where deployed code runs; the laptop is where source-of-truth changes happen. The VPS gets updates via `git pull` after Coolify deploys.

---

## 5. Open questions to resolve before Phase 3

These can wait until pre-flight is done, but they need answers before the LLM router ships.

- Which providers are in scope for the LLM router (Anthropic only, or Anthropic + OpenAI + others)?
- Where do API keys live? Coolify env vars per-VPS, or a central secret store proxied through api-gateway?
- What's the per-VPS Langfuse tenant strategy — one project per client, or one project with tags?
- Is there an existing prompt-template store, or do prompts live in the repo as Markdown? (Recommended: repo as Markdown, versioned with the agent.)
- For the lead-qualifier pilot specifically: which client VPS hosts the pilot, and whose Gmail/Odoo are we wired to?

Answer them, then go.
