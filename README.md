# control-plane

Per-client VPS configuration and worker code for the paperclipai platform. paperclip is the brain; this repo defines the executors, proxy, and automation wiring that surround it.

**First time here?** Read [`ARCHITECTURE.md`](ARCHITECTURE.md), then [`RUNBOOK.md`](RUNBOOK.md).

## Docs

| File | What it covers |
|------|----------------|
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Current deployed stack, component UUIDs, execution paths, auth model, LLM routing |
| [`RUNBOOK.md`](RUNBOOK.md) | Env vars, deploy steps, key management, known gotchas |
| [`ROADMAP.md`](ROADMAP.md) | What comes next (Holon worker, OpenClaw native adapter, per-VPS template) |
| [`PIVOT_TO_PAPERCLIP.md`](PIVOT_TO_PAPERCLIP.md) | History: why we decommissioned the custom FastAPI brain |
