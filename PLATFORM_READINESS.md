# PLATFORM_READINESS.md — end-to-end flow + readiness check
Companion to ARCHITECTURE.md, ROADMAP.md, WORKFLOWS.md.
This document traces a complete workflow lifecycle through the platform — from trigger to audit — with the readiness status of each component. It exists to answer one question: "Is the infrastructure complete enough that we can shift focus from platform-building to workflow development?"
The answer today (2026-05-02): almost — three concrete gaps remaining. See the "Critical gaps" section below.

## End-to-end workflow flow
Every workflow on the platform follows this lifecycle. The status legend marks each stage:

✅ Working today
⏳ In progress
⚠️ Partial — workaround exists
❌ Not yet built

```
┌───────────────────────────────────────────────────────────────────────┐
│ 1. TRIGGER                                                             │
│  ├─ End-client UI form submission              ❌ Phase 9 not built   │
│  ├─ External webhook (email, Cal, payment)     ⚠️ via n8n today,      │
│  │                                                no paperclip native  │
│  ├─ Scheduled timer (heartbeat-on-interval)    ✅ Disabled by default  │
│  └─ Operator manual ping (paperclip-mcp)       ✅ Working              │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   ▼
┌───────────────────────────────────────────────────────────────────────┐
│ 2. WAKE                                                                │
│  ├─ paperclipai receives event                 ✅ Working              │
│  ├─ creates wakeup_request                     ✅ Working              │
│  ├─ assigns / checks-out to agent              ✅ Working              │
│  └─ injects PAPERCLIP_WAKE_PAYLOAD env vars    ✅ Working              │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   ▼
┌───────────────────────────────────────────────────────────────────────┐
│ 3. AGENT CONTEXT LOADING                                               │
│  ├─ Adapter starts (Claude CLI/OpenCode/etc)   ✅ Working              │
│  ├─ Loads skill markdown (company_skills)      ✅ Working              │
│  ├─ Loads PARA memory ($AGENT_HOME)            ✅ Optional skill       │
│  ├─ Receives wake payload                      ✅ Working              │
│  ├─ Restores session_id (resumable adapters)   ✅ Working              │
│  └─ Has access to RAG search                   ❌ Phase 6 S2+S3 TODO   │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   ▼
┌───────────────────────────────────────────────────────────────────────┐
│ 4. AGENT EXECUTION                                                     │
│  ├─ LLM call via openrouter-proxy → OpenRouter ✅ Working today        │
│  │   (post-HIPAA: bedrock-proxy → Bedrock)     ❌ Migration TODO       │
│  ├─ MCP tool calls:                                                    │
│  │   ├─ paperclip-mcp (ops)                    ✅ Working              │
│  │   ├─ Gmail / Calendar / Granola             ✅ Connected            │
│  │   ├─ Notion / Indeed                        ✅ Connected            │
│  │   ├─ client-knowledge-mcp (RAG)             ❌ Phase 6 Stage 3      │
│  │   ├─ Composio (300+ SaaS)                   ❌ Not integrated       │
│  │   ├─ Browserbase (browser automation)       ❌ Phase 7              │
│  │   └─ Vertical-specific MCPs                 ❌ Per-vertical         │
│  ├─ openclaw-worker (code execution path B)    ✅ Working              │
│  ├─ Multi-agent delegation                     ❌ Phase 10             │
│  └─ Approval gates / HITL                      ⚠️ Basic via paperclip  │
│                                                   approvals; full      │
│                                                   review-gate Phase 10 │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   ▼
┌───────────────────────────────────────────────────────────────────────┐
│ 5. SIDE EFFECTS                                                        │
│  ├─ Updates issues in paperclip                ✅ Working              │
│  ├─ Posts comments in paperclip                ✅ Working              │
│  ├─ Sends email (Gmail via MCP)                ✅ Connected            │
│  ├─ Files in CRM / accounting                  ❌ Needs Composio       │
│  ├─ Schedules calls (Cal.com / Calendar)       ⚠️ Calendar via MCP     │
│  ├─ Voice callback / outbound calls            ❌ Phase 13 / Retell    │
│  └─ External webhook fires                     ✅ via n8n              │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   ▼
┌───────────────────────────────────────────────────────────────────────┐
│ 6. COMPLETION                                                          │
│  ├─ heartbeat_run row written                  ✅ Working              │
│  ├─ Token usage / cost calculated              ✅ Working              │
│  ├─ cost_event emitted                         ✅ Working              │
│  ├─ Langfuse trace finalized                   ✅ Working (PR #22)     │
│  ├─ Watchdog evaluates threshold               ✅ Working              │
│  └─ Run audit trail in DB                      ✅ Working              │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   ▼
┌───────────────────────────────────────────────────────────────────────┐
│ 7. NOTIFICATION                                                        │
│  ├─ Activity feed update for end-client        ❌ Phase 9 + 17         │
│  ├─ Daily digest email to client owner         ❌ Phase 17             │
│  ├─ Push notification (mobile)                 ❌ Phase 17             │
│  ├─ SMS for urgent items                       ❌ Phase 17             │
│  ├─ Discord alert to operator (Tony)           ✅ Watchdog/Coolify     │
│  └─ Slack alert to client team                 ❌ Phase 17 / Composio  │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   ▼
┌───────────────────────────────────────────────────────────────────────┐
│ 8. EVAL / AUDIT                                                        │
│  ├─ Langfuse trace queryable                   ✅ Working              │
│  ├─ heartbeat_run_events archived              ✅ Working              │
│  ├─ Eval suite regression test                 ❌ Phase 8              │
│  ├─ Per-workflow cost reporting                ⚠️ paperclip-mcp has    │
│  │                                                billing-period only; │
│  │                                                DB query fallback OK │
│  └─ Compliance audit log                       ❌ Phase 18             │
└───────────────────────────────────────────────────────────────────────┘
```

## Status summary
### ✅ Working today (no work needed)
The agent runtime, paperclipai orchestration, observability, cost controls, and basic SaaS integrations through existing MCPs (Gmail, Calendar, Granola, Notion) — the heartbeat → agent → tool → completion → audit pipeline works end-to-end. This is a real, functioning platform that produces real outputs and tracks real cost.
### ❌ Critical gaps — must close before workflow ship
These three gaps prevent the platform from being a "workflow factory." Total effort: ~3-4 days.
GapWhat it blocksEffortPhase 6 Stage 2 — ingestion workerAny workflow needing RAG over client data (5 of 7 universal workflows)1-1.5 daysPhase 6 Stage 3 — retrieval MCP serverSame as above — pairs with Stage 21-1.5 daysComposio MCP integrationMost Phase 12 workflows touching SaaS tools beyond Gmail/Calendar/Granola/Notion~half day setup, more for production tuning
Without Phase 6 Stages 2-3, agents can't search client documents, can't reference past communications, can't pull vendor history for invoice processing. The "intelligently search past data" capability is the foundation of every workflow that needs to know the client's world.
Without Composio, every workflow needs custom OAuth + API integration per service. With it, agents have ~300 SaaS tools available via one MCP — massive shortcut.
### ⚠️ Partial — workarounds exist, not blocking first workflow
GapCurrent workaroundWhen to fully buildEnd-client UI (Phase 9)Workflows output via email/Slack/Discord; operator views state via paperclipai admin UIBefore client #2 onboardsNotifications (Phase 17)Workflows send email via Gmail MCP; SMS/push not availablePhase 9 ships → Phase 17 neededEvent-driven wakes (Phase 11)n8n receives webhooks, creates issues in paperclip via RESTWhen sub-30s response time matters for a specific workflowMulti-agent collaboration (Phase 10)Single-agent-per-task works for MVPWhen customer-facing actions need critic-agent reviewApproval gatesBasic paperclip approvals existPhase 10 review-gate pattern is more sophisticatedPer-window cost reportingpaperclip-mcp get_cost_summary is billing-period onlyDB query fallback works (RUNBOOK §8 + §10)
### 🟡 HIPAA migration items — deferred until after pilot conversion
Not blocking workflow development on Hostinger with synthetic/non-PHI data. Required before PHI ingestion (per ROADMAP.md Phase 19 compliance gate):

bedrock-proxy build (replaces openrouter-proxy)
AWS account + Bedrock model access
S3 backup migration (replaces R2)
Linode/AWS VPS migration (for medical clients only)
BAA chain documentation (Phase 19 deliverable)
Retell AI integration (Phase 13 voice — replaces from-scratch build)
opencode-free-agent → Bedrock Llama 3.1 70B swap

### 🟢 Optional / nice-to-have
These improve the platform but don't block workflow ship:

Phase 14B Loki + Grafana (operational observability beyond Langfuse's LLM-side coverage)
Phase 8 eval suite (needed before scaling past first workflow, not blocking it)
Phase 18 data lifecycle (HIPAA prerequisite)
Phase 19 compliance posture (HIPAA prerequisite)
Phase 20 onboarding bootstrap (for client #2+ self-serve)
Phase 21 billing automation (for client #2+)


## Verification scenario — declaring "infrastructure complete"
The platform is ready to be a workflow factory when this end-to-end test passes:
**Test scenario:**

Operator says to Claude CLI: "Create a test workflow — when an email arrives matching pattern X, agent Y reads it, searches client knowledge for related documents, drafts a response, and posts a draft comment back to the issue for human approval. Run a test with synthetic data."

Required components for the test to pass:
#ComponentStatus1Trigger (paperclip-mcp creates issue with email payload)✅2Wake (paperclipai assigns to agent)✅3Agent context loading (skills + memory)✅4Agent searches knowledge (search_client_knowledge MCP)❌ Phase 6 S2+S35Agent drafts response (LLM call via proxy)✅6Agent posts comment (paperclip-mcp tool call)✅7Run finalizes (heartbeat_run, cost_event, Langfuse trace)✅8Watchdog evaluates threshold✅
Five of eight components ready. The three blocking are exactly the critical-gap punch list: Phase 6 Stage 2, Phase 6 Stage 3, and Composio (for the broader Phase 12 workflows beyond this specific test).

## Recommended sequence to "complete"
### Day 1-2: Phase 6 Stage 2 (ingestion worker)

Resume the paused PR scaffold from the prior session
Update embedding provider per current architecture (OpenAI text-embedding-3-large via OpenRouter for Hostinger build phase; will swap to Bedrock Cohere at HIPAA migration cutover — runbook covers both paths)
Land code-review PR, then deploy via Coolify
Verify with synthetic test event end-to-end (push to Redis queue, observe row in client_documents + chunks with embeddings)

### Day 3-4: Phase 6 Stage 3 (retrieval MCP server)

Build the client-knowledge-mcp server exposing search_client_knowledge(query, scope, k) per PHASE6_RAG_RUNBOOK.md Stage 3
Register with paperclipai's MCP config
Install client_knowledge skill in company_skills table for Caring First
Verify an agent can search for the test document ingested in Phase 6 Stage 2 and return citations

### Day 5: Composio integration

Sign up for Composio account, save API key to vault
Configure connections for Gmail, Drive, Calendar, Slack, HubSpot at minimum (the SaaS tools touched by the universal seven workflows)
Deploy Composio MCP server (or use their hosted endpoint)
Register with paperclipai's MCP config
Verify an agent can call composio.gmail.send_email or similar

### Day 6: End-to-end verification
Run the verification scenario above with synthetic data. If it passes:

Update this doc's verification table — flip the three ❌ to ✅
Declare infrastructure complete
Shift focus to first workflow build (recommend Document Search since it IS the RAG layer in production form)


## What "infrastructure complete" actually means
It does NOT mean the architecture is finished. It means: all infrastructure that blocks a workflow from being built has been resolved. Specifically:

✅ Agents can run on heartbeat triggers
✅ Agents have observability (Langfuse traces)
✅ Agents have cost guardrails (watchdog + per-agent budgets)
✅ Agents have skills system (paperclipai company_skills)
⏳ Agents can ingest and retrieve client documents (Phase 6 Stages 2+3 — TODO)
⏳ Agents can call common SaaS tools (Composio — TODO)
✅ Operator can manage agents conversationally (paperclip-mcp)
✅ Backups exist (R2 today, S3 at HIPAA migration)

Five of eight done. Knock out the three remaining and the platform shifts from "build mode" to "workflow factory mode."
The deferred items (Phase 7 browser automation, Phase 9 end-client UI, Phase 10 multi-agent, Phase 11 event-driven wakes, Phase 13 voice, Phase 14B observability, Phase 17 notifications, Phase 18-21) are real architectural work but none of them block writing the first workflow. They get built when a specific workflow demands them, not speculatively.
This is the difference between "platform development" (you've been doing this for 2+ months) and "workflow development with the platform" (where you should be by end of this week).

## What this doc is NOT

Not a build guide — see ROADMAP.md for phase-by-phase plans, PHASE6_RAG_RUNBOOK.md for Stage 2-3 specifics
Not architecture — see ARCHITECTURE.md
Not exhaustive of every component — focused on the workflow critical path
Not static — update as components ship; flip ❌ to ✅
