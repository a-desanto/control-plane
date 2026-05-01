# WORKFLOWS.md — universal seven SMB workflows

**Companion to** `ARCHITECTURE.md` (target architecture v3.3) and `ROADMAP.md` (Phase 12).

This document specifies the seven universal SMB workflows that ship with every paperclipai client deployment, regardless of vertical. Each workflow is documented with: trigger, required data sources, required integrations, agent skills, MVP scope, full scope, and the platform phase dependencies it relies on.

**Build sequence** is at the bottom — the order to ship workflows in (which is *not* the order they're listed, because the listed order is by familiarity, while the build order is by dependency).

---

## 1. Lead qualification

**What the SMB owner gets:** every inbound lead — from web forms, email, Cal.com bookings, referrals, social DMs — gets triaged automatically. Real leads are surfaced with context and a draft response; junk is filtered; urgent leads are flagged immediately.

**Trigger:** new lead source event (form submission, email matching pattern, Cal.com webhook, manual paste).

**Data sources:**
- Inbound lead (form payload, email body, booking record)
- Past lead history (RAG)
- Customer database / CRM (browser-use or API)

**Integrations required:**
- Form / lead source (Typeform, Calendly, Cal.com, native web form)
- Email (Gmail or Microsoft 365)
- CRM (Salesforce, HubSpot, Attio, or vertical-specific — varies per client)

**Agent skills:** lead-classifier, lead-responder, CRM-updater, follow-up-scheduler.

**MVP scope (v1):**
- Agent reads incoming lead payload
- Classifies: real / probable / junk
- Scores urgency (1-5) based on intent signals
- Drafts a tailored response using RAG over past wins
- Surfaces to owner for approval (Phase 17 notification)

**Full scope (v2):**
- Auto-replies on routine patterns (e.g. "thanks, here's our scheduling link")
- Schedules discovery calls via Cal.com
- Logs to CRM with full context
- Reminds owner about follow-ups at appropriate intervals
- Maintains a "lead heat" dashboard

**Platform phases required:**
- Phase 6 (RAG) — historical lead context
- Phase 7 (browser-use) — for non-API CRMs
- Phase 15 (OAuth) — for Gmail / CRM auth
- Phase 17 (notifications) — for owner approval

---

## 2. Email / inbox management

**What the SMB owner gets:** an agent that reads every incoming email, triages by urgency and intent, drafts responses for routine threads, and surfaces a daily digest of what matters. The owner reads 10 emails a day instead of 100.

**Trigger:** new email received (IMAP push or Gmail/M365 webhook).

**Data sources:**
- Email content + thread history
- Sender history (RAG over past emails with this contact)
- Calendar (for scheduling-aware responses)

**Integrations required:**
- Gmail or Microsoft 365
- Calendar (Google or Outlook)

**Agent skills:** email-triager, email-drafter, email-archiver, daily-digest-writer.

**MVP scope (v1):**
- Triage every incoming email: urgency, intent, suggested action
- Daily digest at 7am: "5 urgent, 12 awaiting response, 30 informational, 50 archived"
- Flag anything time-sensitive via push notification

**Full scope (v2):**
- Draft replies for routine threads (owner approves with one tap)
- Schedule follow-ups for sent emails awaiting response
- Auto-archive promotional / spam
- Escalate via SMS if time-sensitive and owner not responsive
- Cross-link related threads ("this is the third email about Project X")

**Platform phases required:**
- Phase 15 (OAuth) — Gmail/M365
- Phase 17 (notifications) — push + SMS for urgent
- Phase 6 (RAG) — sender history, related thread linking

---

## 3. Invoice processing

**What the SMB owner gets:** invoices that arrive via email (PDF attachments) or scanned uploads get extracted, categorized, and filed into the accounting system automatically. Owner reviews exceptions only.

**Trigger:** email containing invoice PDF, manual upload to drop zone, or scheduled accounting-system poll.

**Data sources:**
- Invoice document (PDF, image, email body)
- Vendor history (RAG)
- Accounting system records (existing vendors, categories, GL codes)

**Integrations required:**
- Email (for incoming invoices)
- Drive / Dropbox (for stored invoices)
- Accounting system: QuickBooks, Xero, Drake, FreshBooks, Wave (browser-use for those without good APIs)

**Agent skills:** invoice-extractor, vendor-matcher, anomaly-detector, accounting-filer.

**MVP scope (v1):**
- Extract: vendor name, invoice number, date, due date, line items, total, tax
- Categorize: match to known vendor or flag as new
- Anomaly detection: flag duplicates, unusual amounts, missing tax info
- Surface for owner approval before filing

**Full scope (v2):**
- Auto-file in accounting system once approved (QuickBooks/Xero etc. via browser-use)
- Track payment status; send payment reminders to vendor or owner
- Reconcile against bank feed
- End-of-month report: spend by category, by vendor, vs budget

**Platform phases required:**
- Phase 6 (RAG) — vendor history
- Phase 7 (browser-use) — accounting system filing
- Phase 15 (OAuth) — email/Drive access
- Phase 17 (notifications) — anomaly alerts

---

## 4. Document organization & search

**What the SMB owner gets:** every document the business has — contracts, proposals, customer files, regulatory filings, internal memos — is indexed and searchable in natural language. "Find the NDA we signed with Acme in 2023" returns the right file with the right paragraph highlighted.

**Trigger:** continuous (background ingestion); on-demand search query.

**Data sources:**
- Drive (Google or OneDrive)
- Dropbox / Box
- Email attachments
- Manual uploads via end-client UI

**Integrations required:**
- Drive / OneDrive
- Dropbox / Box (optional)
- Email (for attachment extraction)

**Agent skills:** document-ingester, document-searcher, document-tagger, expiration-watcher.

**MVP scope (v1):**
- Background ingestion of all documents from connected sources
- Chunked embeddings stored in `client_document_chunks`
- Per-document ACLs
- Natural-language search exposed as MCP tool `search_client_knowledge`
- Citations in answers (which doc, which page)

**Full scope (v2):**
- Proactive surfacing: "you have a contract with [vendor] expiring in 30 days"
- Auto-tagging by client / project / compliance category
- Document version tracking ("you have 3 versions of this NDA — here's the diff")
- Expiration / renewal reminders via notifications
- Topic clustering ("you have 47 documents about Project X — here's a summary")

**Platform phases required:**
- Phase 6 (RAG) — **this workflow IS Phase 6 in production form**
- Phase 15 (OAuth) — Drive/Dropbox/Box auth
- Phase 17 (notifications) — expiration reminders

**Note:** this is the foundation workflow — almost every other workflow benefits from this layer being in place. Build first.

---

## 5. Meeting notes + follow-up tracking

**What the SMB owner gets:** every meeting (sales call, internal sync, customer check-in) gets ingested as a transcript, decisions and action items are extracted automatically, and follow-ups are tracked to completion. No more "I forgot what we agreed on."

**Trigger:** meeting transcript arrives (Granola, Otter, Fireflies, manual upload).

**Data sources:**
- Meeting transcript
- Calendar event (for context: who attended, meeting purpose)
- CRM record (if customer-facing)
- RAG over past meetings with same attendees

**Integrations required:**
- Meeting recorder (Granola, Otter, Fireflies, Zoom AI Companion, etc.)
- Calendar (Google/Outlook)
- CRM (for customer meetings)

**Agent skills:** meeting-summarizer, action-item-extractor, decision-logger, follow-up-tracker.

**MVP scope (v1):**
- Ingest transcript on arrival
- Generate 3-bullet summary
- Extract action items with owner + deadline
- Create paperclip issues for each action item, assigned to right person
- Log decisions in a searchable index

**Full scope (v2):**
- Remind attendees of their commitments (notifications + email)
- Link related docs ("you mentioned the proposal — here it is")
- Update CRM with key takeaways for customer meetings
- Pattern detection: "you've discussed [topic] in 3 of the last 5 meetings — should this be a project?"

**Platform phases required:**
- Phase 6 (RAG) — past meeting context
- Phase 7 (browser-use) — for non-API CRMs
- Phase 15 (OAuth) — calendar/CRM
- Phase 17 (notifications) — follow-up reminders
- Meeting recorder integration (Granola MCP exists; Otter/Fireflies via API)

---

## 6. Customer support triage

**What the SMB owner gets:** every customer inquiry — email, web form, helpdesk ticket — gets categorized, prioritized, routed, and the routine cases get drafted responses. The owner spends time on judgment calls, not first-line triage.

**Trigger:** new ticket / inquiry (email matching pattern, helpdesk webhook, web form submission).

**Data sources:**
- Inquiry content + customer history
- RAG over past resolutions ("how did we handle this last time?")
- Knowledge base / FAQ
- Customer LTV / tier data

**Integrations required:**
- Helpdesk: Zendesk, Intercom, HelpScout, Freshdesk (API or browser-use)
- Email
- CRM (for customer context)

**Agent skills:** inquiry-classifier, response-drafter, escalation-router, sla-monitor.

**MVP scope (v1):**
- Categorize each inquiry: issue type, urgency, customer tier
- Suggest routing (which team member or queue)
- Draft initial response based on past resolutions
- Surface for owner approval before sending

**Full scope (v2):**
- Auto-resolve FAQ-class inquiries (with confidence threshold)
- Escalate judgment cases with full context bundle ("here's the history, here's what we did last time, here's what's different now")
- Track SLA: alert if response time approaching threshold
- End-of-week support quality dashboard

**Platform phases required:**
- Phase 6 (RAG) — past resolutions
- Phase 7 (browser-use) — for non-API helpdesks
- Phase 15 (OAuth) — email/helpdesk auth
- Phase 17 (notifications) — SLA breach alerts
- Phase 10 (multi-agent) — for the "draft + critic + send" review-gate pattern on customer-facing replies

---

## 7. Scheduling / appointment workflows

**What the SMB owner gets:** appointments are coordinated end-to-end — booking requests get processed, calendar conflicts checked, confirmations sent, reminders fired, no-shows followed up, rescheduling negotiated. The calendar runs itself.

**Trigger:** booking request (Cal.com webhook, email pattern, web form), calendar event change.

**Data sources:**
- Calendar (current bookings, working hours, focus blocks)
- Customer record (CRM)
- Past appointment history

**Integrations required:**
- Calendar: Google, Outlook
- Booking tool: Cal.com (has good MCP), Calendly, Acuity, vertical-specific (browser-use for last category)
- Phone / SMS for reminders (Twilio)

**Agent skills:** booking-processor, conflict-resolver, reminder-sender, no-show-handler.

**MVP scope (v1):**
- Process booking requests, check conflicts, send confirmations
- 24-hour and 1-hour appointment reminders (email + SMS)
- Owner sees daily appointment list

**Full scope (v2):**
- Handle rescheduling negotiation conversationally (over email or SMS)
- Follow up on no-shows with rescheduling offer
- Optimize calendar: enforce buffer time, protect focus blocks, batch similar appointments
- Multi-system sync (Cal.com + Google Calendar + CRM all stay consistent)
- Voice handling for phone-based booking (Phase 13)

**Platform phases required:**
- Phase 7 (browser-use) — vertical-specific schedulers
- Phase 11 (event-driven wakes) — calendar webhooks
- Phase 15 (OAuth) — calendar
- Phase 17 (notifications) — reminders
- Phase 13 (voice) — for full scope

---

## Build sequence

Workflows depend on each other and on platform phases. Build in this order:

| Order | Workflow | Why now | Blocks |
|-------|----------|---------|--------|
| 1 | **Document organization & search** (#4) | This IS Phase 6 in production form. Foundation for almost everything else — every other workflow benefits from RAG over client docs. | Everything |
| 2 | **Email / inbox management** (#2) | High-frequency value, lowest integration complexity. Needs Phase 15 (OAuth) but no browser-use. Validates the notification layer (Phase 17). | Lead qual, support triage |
| 3 | **Meeting notes + follow-ups** (#5) | Medium complexity, very high perceived value. Granola MCP exists; calendar OAuth comes from #2. Demonstrates multi-source ingestion working. | Lead qual (partial) |
| 4 | **Lead qualification** (#1) | Builds on #2 (email) + #4 (RAG over past leads). Direct revenue lever for SMB clients (more leads → more revenue → easy ROI math). | — |
| 5 | **Invoice processing** (#3) | Needs Phase 7 (browser-use) for the full version. Ship MVP after #4 and gate full scope on browser-use shipping. | — |
| 6 | **Scheduling** (#7) | Needs Phase 7 + 11 (events) + 17 (SMS). Higher integration overhead but huge value once shipped. | — |
| 7 | **Customer support triage** (#6) | Most complex — needs Phase 10 (multi-agent review gate) for safe customer-facing automation. Ship last. | — |

This sequence is approximately one workflow per month for an experienced operator with the platform phases in flight. Adjust based on which existing client pulls hardest on which workflow.

---

## Cross-cutting requirements

Every shipped workflow must include:

- **Eval suite** (Phase 8) — at least 50 historical cases with expected outcomes; regression score on every prompt change
- **Approval gate by default** for any action that touches the outside world (sends email, books appointment, files invoice). Owner can later opt to auto-approve specific patterns once trust is established.
- **Activity feed entry** — every workflow run is visible in the end-client UI (Phase 9) with: what triggered it, what the agent did, what the outcome was, what cost was incurred.
- **Cost reporting** — per-workflow cost rolled up monthly so the SMB owner sees ROI ("this workflow saved 14 hours and cost $42 last month").

---

## Vertical extensions (deferred)

Each universal workflow has vertical-specific variants. Examples:

- **Lead qualification → legal:** add conflict-of-interest check against client database
- **Lead qualification → medical:** add insurance verification step
- **Invoice processing → accounting:** add GL coding rules per client
- **Document search → legal:** privilege-flagging on documents under attorney-client communication
- **Document search → medical:** PHI redaction for non-HIPAA-trained users

Vertical extensions ship per-client when the universal version is in place and the client has a specific need. Do not build vertical extensions speculatively.

---

## What this document is NOT

- Not a build plan — see `ROADMAP.md` Phase 12 for build effort and acceptance criteria.
- Not architecture — see `ARCHITECTURE.md` Target architecture section for the platform phases each workflow depends on.
- Not exhaustive — these are the *universal* workflows. Vertical-specific workflows live elsewhere (TBD as they ship).
