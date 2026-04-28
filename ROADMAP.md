# ROADMAP.md

Current architecture is stable. This file tracks what comes next.

For the current deployed state, see `ARCHITECTURE.md`.
For ops procedures, see `RUNBOOK.md`.

---

## Phase 3C — Holon worker (Path C)

**What:** A second worker container that implements issue→PR automation. Where openclaw-worker (Path B) executes a task and reports a summary, the Holon worker would: clone the repo, apply changes via Holon's structured code-change protocol, open a pull request, and link it back to the paperclip issue.

**Status:** Not started.

**Depends on:** openclaw-worker pattern (done) — Holon worker would follow the same poll/claim/execute/report loop with a different executor.

---

## Phase 4 — OpenClaw Gateway native adapter

**What:** paperclip is building a native OpenClaw Gateway adapter. When it ships, workers running OpenClaw can register directly as paperclip adapters instead of being polled workers. This eliminates the need for `openclaw-worker` as a separate container.

**Status:** Blocked on upstream (paperclip product roadmap). The openclaw-worker agent UI dropdown in paperclip already shows adapter-type options — watch for OpenClaw Gateway to appear there.

**When this lands:** Create an agent in paperclip with adapter type set to OpenClaw Gateway, point it at the OpenClaw instance URL, delete `openclaw-worker`. The issue queue and paperclip integration remain unchanged.

---

## Phase 5 — Per-VPS Coolify template for new clients

**What:** Export the current VPS state (paperclipai + openrouter-proxy + openclaw-worker + n8n + Flowise + activepieces) as a Coolify template. Document the onboarding steps: provision VPS → apply template → set env vars → bootstrap paperclip → issue first API key → verify health.

**Status:** Not started.

**Input needed:** Decide which optional apps (Flowise, activepieces) belong in the base template versus being added per-client.

---

## Phase 6 — Hermes/OpenCode/Codex agents

**What:** paperclip already supports these as native adapter types. No worker container needed — just create agents in paperclip's UI with the appropriate adapter type (`Hermes Agent (local)`, `OpenCode`, `Codex`, etc.) and configure the adapter URL.

**Status:** Optional. Low effort once the adapter is running; effort is standing up the adapter service itself.

---

## Open questions

| Question | Status |
|----------|--------|
| How do paperclip's per-agent budgets interact with worker-claimed tasks? Does cost from `openclaw-worker` invocations register against the Code Execution Worker agent's budget cap? | Unverified — check paperclip's billing/cost UI after a few real tasks run |
| Should Flowise and activepieces be in the per-client base template (Phase 5) or added on demand? | Undecided |
