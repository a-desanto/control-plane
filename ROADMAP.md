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

## Open questions to resolve before scaling beyond one VPS

- **Agent budget tracking:** How do paperclip's per-agent budgets interact with worker-claimed tasks? Verify cost from `openclaw-worker` invocations registers against the `openclaw-agent` budget cap. Check paperclip's billing/cost UI after a few real tasks.
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
