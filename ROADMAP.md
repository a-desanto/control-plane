# ROADMAP.md

Current architecture is stable. This file tracks what comes next.

For the current deployed state, see `ARCHITECTURE.md`.
For ops procedures, see `RUNBOOK.md`.

---

## Phase 3C — Enable OpenCode native adapter ✓ DONE

**Status:** Complete (2026-04-28). OpenCode (`opencode-agent`) is live and verified.

- Adapter type: `OpenCode (local)`, using `anthropic/claude-sonnet-4-6` via `ANTHROPIC_BASE_URL=http://openrouter-proxy:4001`
- Smoke test CAR-6 completed: exitCode 0, $0.077, billed via OpenRouter
- No new containers — paperclip's heartbeat drives execution directly
- `codex-agent` was created and deleted: see "Explicitly dropped" section below

**To add an OpenAI-tuned OpenCode agent on demand:** see `RUNBOOK.md §4`.

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

**Open input:** Decide which optional apps (Flowise, activepieces) belong in the base template vs. added per-client.

---

## Open questions to resolve before scaling beyond one VPS

- **Agent budget tracking:** How do paperclip's per-agent budgets interact with worker-claimed tasks? Verify cost from `openclaw-worker` invocations registers against the Code Execution Worker agent's budget cap. Check paperclip's billing/cost UI after a few real tasks.
- **Company portability:** Does paperclip's export feature work cleanly for the openclaw-worker setup, or does each new VPS need manual agent creation + key issuance?
- **OpenRouter key strategy:** Single shared key across fleet, or per-VPS keys for cost isolation and blast-radius control?

---

## Explicitly dropped

**Codex CLI native adapter:** Dropped. The `codex` binary (v0.125.0, installed in paperclip's image) uses OpenAI's **Responses API via WebSocket** (`wss://api.openai.com/v1/responses`). `OPENAI_BASE_URL` redirects REST calls only — WebSocket connections are hardcoded to `api.openai.com`. OpenRouter does not implement the Responses API WebSocket protocol. Result: `codex-agent` exits 1 with `401 Unauthorized` on every heartbeat run.

Re-evaluate if: (a) Codex CLI adds custom WebSocket base URL support, OR (b) OpenRouter implements the Responses API. For OpenAI-model tasks in the meantime, use OpenCode with `openai/gpt-4.1` via OpenRouter (see `RUNBOOK.md §4`).

---

**Holon worker (formerly "Phase 3C"):** Dropped. The original idea was a second worker container implementing a structured issue→PR lifecycle via the Holon protocol. This is unnecessary:

- An OpenClaw worker with a PR-tuned system prompt on the assigned agent handles issue→PR today.
- A specialized executor for one workflow pattern violates the "executors are replaceable" principle — the workflow should be a system prompt configuration, not an architectural component.
- Holon's specific niche is being absorbed by general-purpose agents and GitHub's first-party tooling.
- Adding another external worker with its own operational surface (container, polling loop, error modes) isn't worth it when the existing worker can do the same job.
