# control-plane

Per-client VPS configuration and worker code for the paperclipai platform. paperclip is the brain; this repo defines the executors, proxy, and automation wiring that surround it.

**First time here?** Read [`ARCHITECTURE.md`](ARCHITECTURE.md), then [`RUNBOOK.md`](RUNBOOK.md).

## Docs

| File | What it covers |
|------|----------------|
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Current deployed stack, component UUIDs, execution paths, auth model, LLM routing |
| [`RUNBOOK.md`](RUNBOOK.md) | Env vars, deploy steps, key management, known gotchas |
| [`ROADMAP.md`](ROADMAP.md) | What comes next — Phase 5 (per-VPS template), Phases 6-13 (frontier capabilities), Phases 14-21 (infrastructure layer) |
| [`WORKFLOWS.md`](WORKFLOWS.md) | Universal seven SMB workflows — specs, build order, platform-phase dependencies |
| [`PHASE14_LANGFUSE_RUNBOOK.md`](PHASE14_LANGFUSE_RUNBOOK.md) | Step-by-step deployment runbook for Phase 14 (Langfuse observability + control VPS) |
| [`PHASE6_RAG_RUNBOOK.md`](PHASE6_RAG_RUNBOOK.md) | Step-by-step implementation runbook for Phase 6 (RAG/knowledge layer MVP) |
| [`PIVOT_TO_PAPERCLIP.md`](PIVOT_TO_PAPERCLIP.md) | History: why we decommissioned the custom FastAPI brain |
| [`PLATFORM_READINESS.md`](PLATFORM_READINESS.md) | End-to-end workflow flow + readiness check — what's working, what's blocking, what's deferred |
| [`ADD_ON_SERVICES.md`](ADD_ON_SERVICES.md) | Add-on service catalog — base tier + plug-and-play add-ons + vertical bundles + pricing + install mechanics |
| [`COMPETITIVE_RESEARCH_REPORT.md`](COMPETITIVE_RESEARCH_REPORT.md) | May 2026 competitive landscape research — competitors, pricing, business model critiques |
