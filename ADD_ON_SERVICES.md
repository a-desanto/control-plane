# ADD_ON_SERVICES.md — modular service catalog
Companion to ARCHITECTURE.md, ROADMAP.md, WORKFLOWS.md.
This document defines the add-on service framework — how the platform sells modular, plug-and-play AI services that clients add to a base tier as they need them. Each add-on is a discrete bundle of skills + agents + integrations + workflows + pricing that installs/uninstalls cleanly per-client.
This is the MSP-aligned commercial model. Base bundle + a la carte add-ons = clients pay for what they use, expand as their needs grow, and you have clear upsell paths.

## Why this structure
paperclipai's company_skills system is natively per-company, which means each client can have a different set of skills installed without affecting any other client. Add-ons exploit that. Instead of every client getting all 7 universal workflows whether they need them or not, they get what they pay for.
For the platform: simpler product story, clear upsell paths, modular development.
For the client: lower price to start, ROI clear per add-on, expand on demand.
For the operator: each add-on is its own development unit with its own pricing math.

## Base tier — what every paying client gets
Every client deployment includes the foundational AI ops platform regardless of which add-ons they buy:
CapabilityWhat it doesDocument organization & search (Phase 6 RAG)Indexes the client's documents, exposes natural-language search to agents and usersEmail triage / inbox managementReads inbound emails, classifies urgency, drafts replies for routine threadsOperator-managed onboardingHands-on setup, training, ongoing supportAgent infrastructure1 CEO + 1-2 specialist agents per client, paperclipai-orchestratedObservability + cost guardsLangfuse traces, watchdog cost caps, Discord alertsBackups + DRDaily off-VPS backups (S3 with BAA for compliance clients)Per-VPS isolationDedicated infrastructure per client
Base tier pricing:
TierMonthlyIncludesStarter$499Base + 1 client user + light volume (under 100 docs/day)Pro$1,499Base + up to 5 client users + medium volume + 1 add-on includedEnterprise$4,999Base + unlimited users + heavy volume + 3 add-ons included + SLA
Setup fee: $0-2k depending on tier (low friction).

## Add-on service catalog
Each add-on is priced separately. Clients can have any combination of add-ons installed at any time. Pricing below is monthly recurring; some have per-usage pass-through costs (voice minutes, SMS, etc.).
### 1. Voice Add-on (Retell-powered)
What the client gets: AI voice agents handling inbound calls (after-hours, overflow, primary), making outbound calls (campaigns, follow-ups, reminders), processing voicemails. Industry-quality conversational voice.
Price: $300/mo + $0.10-0.15/min pass-through (volume-based)
Stack additions:

Retell AI account (Healthcare tier for HIPAA clients, Standard otherwise)
Phone number(s) provisioned via Retell
Skills: voice-receptionist, voice-scheduler, voice-message-taker, outbound-caller
Agent: voice-agent (real-time conversational, runs in Retell, callbacks paperclipai)
Workflows: inbound-call, appointment-booking, outbound-campaign

ROI math: replaces $50/hour after-hours answering service. Breakeven at ~6 calls/week of saved labor.
Use cases: medical practices (after-hours intake), real estate (inbound buyer inquiries), home services (booking + dispatch), legal (intake calls).

### 2. Marketing & Social Media Add-on
What the client gets: content generation (blog posts, social posts, newsletters), scheduled posting across platforms, engagement monitoring, performance analytics. Brand-voice tuning per client.
Price: $400/mo (add $200/mo for premium tier with Opus content review)
Stack additions:

Buffer / Hootsuite / native social APIs (Composio handles integration)
Skills: content-writer, social-poster, email-campaigner, brand-voice, analytics-reporter
Agent: marketing-agent (Sonnet for writing, Opus for strategy)
Brand voice document collected at onboarding (anchors agent output to client tone)
Workflows: weekly-content-plan, post-and-engage, monthly-report

ROI math: replaces $1,500-3,000/mo content marketer or freelancer for SMB.
Use cases: professional services (lawyers, accountants posting expertise content), real estate (listing promotion), home services (review requests + reputation management).

### 3. Sales Outreach Add-on
What the client gets: prospect research, personalized outreach (email/LinkedIn), multi-touch follow-up sequences, meeting booking with discovery questions answered automatically.
Price: $400/mo + email sender/domain warmup costs (~$50-100/mo)
Stack additions:

CRM integration (HubSpot, Salesforce, Attio via Composio)
Apollo or Clay for lead source
Email warmup (Smartlead, Instantly, or similar)
Skills: prospect-researcher, outreach-personalizer, followup-sequencer, meeting-scheduler
Agent: sales-agent (Sonnet for research, mix for personalization)
Workflows: new-lead-research, outreach-sequence, meeting-follow-through

ROI math: replaces $4-6k/mo SDR-as-a-service or $40-80k SDR salary.
Use cases: professional services, B2B SMBs, growth-mode companies in any vertical.

### 4. Customer Support Add-on
What the client gets: ticket triage, draft responses based on knowledge base + past resolutions, escalation routing with full context, SLA monitoring with proactive alerts.
Price: $500/mo + helpdesk integration costs (~varies by helpdesk)
Stack additions:

Helpdesk OAuth (Zendesk, Intercom, HelpScout, Freshdesk via Composio)
Knowledge base ingestion into RAG layer (uses base tier Phase 6)
Skills: inquiry-classifier, response-drafter, escalation-router, sla-monitor
Agent: support-agent (Sonnet for nuanced cases, Haiku for routine triage)
Workflows: triage-on-arrival, auto-respond-faq, escalate-with-context, sla-breach-alert

ROI math: replaces $50k tier-1 support hire or 30 hours/week of owner time.
Use cases: SaaS companies, healthcare practices (patient portal messages), e-commerce, professional services with high inquiry volume.

### 5. Document Workflows Add-on
What the client gets: invoice processing (extract → categorize → file in accounting system), contract intake (extract terms → flag anomalies), form processing (intake forms, applications, registrations).
Price: $300/mo (add $100/mo for vision-heavy work like complex PDFs / scanned docs)
Stack additions:

AWS Textract (under existing AWS BAA)
Accounting system integration (QuickBooks/Xero via Composio or browser-use)
Skills: invoice-extractor, vendor-matcher, anomaly-detector, accounting-filer, intake-form-processor
Agent: document-agent (Sonnet vision for extraction)
Workflows: inbound-invoice, expense-extraction, intake-form-handling

ROI math: replaces 5-15 hours/week of admin labor.
Use cases: all verticals (every business has invoices), accounting firms (client invoice intake), legal (contract intake), medical (intake forms + insurance).

### 6. Vertical Extension Add-ons
Vertical-specific workflows that build on top of base + other add-ons. Designed to layer on rather than replace.
#### Legal Vertical Extension
Price: $500/mo
Includes:

Contract review (clause-by-clause flagging, risk assessment)
Conflict checking against client database
Billable-hours summarization from time entries + calendar
Matter management workflow
Skill: contract-reviewer, conflict-checker, billable-hours-summarizer, matter-manager

Use cases: law firms, in-house legal teams, contract-heavy businesses.
#### Medical Vertical Extension
Price: $600/mo (HIPAA tier required, includes BAA)
Includes:

Intake form processing (PHI-safe)
Appointment reminders (multi-channel, language-appropriate)
Claims status checking via payer portals (browser-use)
Patient communication triage
Skill: intake-processor, appointment-reminder, claims-checker, patient-communication

Use cases: medical practices, dental offices, mental health clinics, specialist practices.
#### Accounting Vertical Extension
Price: $400/mo
Includes:

Client document collection workflow (chasing missing receipts, statements)
Deadline tracking (tax filings, estimated payments, K-1s)
Reconciliation assistance (match bank/credit card to GL)
Year-end / tax prep workflow
Skill: doc-collector, deadline-tracker, reconciler, tax-prep-helper

Use cases: CPA firms, bookkeeping services, financial advisors with bookkeeping component.
#### Home Services Vertical Extension
Price: $400/mo
Includes:

Dispatch logic (job assignment to field techs based on skill, location, availability)
Route optimization for multi-stop days
Customer follow-up (review requests, satisfaction surveys, repeat-service prompts)
Estimate-to-invoice automation
Skill: dispatcher, route-optimizer, customer-follow-up, estimate-to-invoice

Use cases: plumbers, electricians, HVAC, contractors, cleaning services.
#### Real Estate Vertical Extension
Price: $500/mo
Includes:

Listing sync across MLS + portals (Zillow, Realtor.com, etc.)
Lead routing with scoring (hot/warm/cold)
Contract chasing (deadline reminders for inspection, financing, closing)
Transaction coordination workflow
Skill: listing-syncer, lead-router, contract-chaser, transaction-coordinator

Use cases: brokerages, individual agents with team, transaction coordinators.

### 7. Premium Reasoning Add-on
What the client gets: Opus 4.6 (or successor) for tasks requiring deeper reasoning — complex contract analysis, regulatory questions, strategic planning, multi-step problem solving. Higher quality output for the workflows that need it.
Price: $300/mo (covers ~50-100 Opus calls per month, $0.50 per additional call)
Stack additions:

Per-skill model routing rules (some skills upgrade to Opus, others stay on Sonnet)
Skills tagged for premium routing
No new agents — existing agents get smarter on demand

ROI math: for legal contract analysis or strategic decisions, Opus output quality justifies the cost vs. the alternative (hire a senior analyst).
Use cases: legal firms, regulated industries, strategy-intensive businesses.

### 8. Custom Workflow Development Add-on
What the client gets: you (or your team) build a workflow tailored to their specific business need. Not a productized add-on — a one-time engagement with optional ongoing maintenance.
Price: $2,000-5,000 one-time (depending on complexity) + $200/mo maintenance
Stack additions:

Custom skill markdown
Custom workflow YAML
Custom integrations as needed (operator builds these)
Per-client-only deployment (no other clients see it)

Use cases: clients with unique processes that the universal add-ons don't cover. Often becomes a base for a new productized add-on if multiple clients want similar things.

## Vertical bundles — pre-configured packages
For common SMB profiles, pre-bundle add-ons into vertical packages. Easier to sell ("here's the package for medical practices") and gives clear pricing math.
BundleTierAdd-ons includedMonthly PriceMedical Practice BundlePro baseVoice + Document Workflows + Medical Vertical Extension$2,499Legal Firm BundlePro baseDocument Workflows + Legal Vertical Extension + Premium Reasoning$2,799Real Estate Brokerage BundlePro baseVoice + Marketing + Sales Outreach + Real Estate Vertical Extension$2,999Accounting Firm BundlePro baseDocument Workflows + Accounting Vertical Extension + Sales Outreach (off-season)$2,499Home Services BundlePro baseVoice + Marketing + Home Services Vertical Extension$2,499
Bundles are priced ~10% below sum-of-parts to make the bundle obviously the right buy.

## Add-on framework — how installation works
Each add-on is structured as a deployable unit:
```
add-ons/<add-on-name>/
├── README.md                    # What this does, who buys it, ROI math
├── skills/                      # Markdown files for company_skills
│   ├── primary-skill.md
│   └── helper-skills/
├── agents/                      # Agent configurations to provision
│   └── agent-config.json        # Roles, models, budgets, system prompts
├── integrations/                # External service requirements
│   ├── service-a.config         # OAuth, API keys, account refs
│   └── service-b.config
├── workflows/                   # Workflow YAML definitions
│   ├── trigger-a.yaml
│   └── trigger-b.yaml
├── pricing.json                 # Stripe SKU mapping
└── install/                     # Install/uninstall scripts
    ├── install.sh
    └── uninstall.sh
```
### Install flow (one-line operator command)
```bash
./scripts/install-addon.sh \
  --client caring-first \
  --addon voice \
  --tier standard
```
The script orchestrates:

Insert skills into company_skills for the client's company_id
Provision agents in paperclipai (with appropriate model, budget caps via watchdog)
Configure integrations — walks operator (or client UI eventually) through OAuth / API key setup
Create workflows — enables the trigger logic, registers webhooks
Update billing — adds the SKU to Stripe subscription, prorates first month
Notify the client — "Voice agent is now active"
Update operator dashboard — flag the add-on as installed for ongoing monitoring

### Uninstall flow (same script in reverse)
```bash
./scripts/install-addon.sh --client caring-first --addon voice --uninstall
```

Disable workflows + webhooks
Pause/remove agents
Soft-delete skills (keep for 30 days, then purge)
Revoke OAuth tokens
Update billing (cancel SKU, prorate)
Notify client


### Adding a new add-on (the operator's perspective)
To productize a new add-on:

Build it once for a paying client as a custom workflow
Document it in the add-on framework structure
Generalize the skills — remove client-specific names, parameterize
Add to catalog in this doc + price it
Test install/uninstall on a fresh test client
Sell it as a standalone add-on

Most add-ons start as custom workflow development that gets productized after 2-3 clients want similar things.

## Discovery-driven upselling
The plug-and-play structure enables natural upsell paths. Each base-tier client generates signals about what add-on they need next:

High inbound call volume observed in their email/calendar → suggest Voice add-on
Manual social media posts observed → suggest Marketing add-on
Aging support tickets in their helpdesk → suggest Customer Support add-on
Complex legal/medical/financial questions in workflows → suggest Premium Reasoning add-on
Repeated similar custom requests → suggest Vertical Extension add-on

Operator runs monthly review with each client showing usage data + suggested add-ons + ROI math. Upsell becomes value-driven, not pushy.

## Pricing summary table
ItemTypeMonthlyBase — StarterRequired$499Base — ProRequired$1,499Base — EnterpriseRequired$4,999Voice (Retell)Add-on+$300Marketing & SocialAdd-on+$400Sales OutreachAdd-on+$400Customer SupportAdd-on+$500Document WorkflowsAdd-on+$300Legal Vertical ExtensionAdd-on+$500Medical Vertical ExtensionAdd-on+$600Accounting Vertical ExtensionAdd-on+$400Home Services Vertical ExtensionAdd-on+$400Real Estate Vertical ExtensionAdd-on+$500Premium Reasoning (Opus)Add-on+$300Custom Workflow DevelopmentAdd-on$2-5k one-time + $200/moMedical Practice BundleBundle (~10% off)$2,499Legal Firm BundleBundle (~10% off)$2,799Real Estate Brokerage BundleBundle (~10% off)$2,999Accounting Firm BundleBundle (~10% off)$2,499Home Services BundleBundle (~10% off)$2,499
Cost-of-goods-sold (your AI infrastructure cost per client) typically lands at 20-30% of revenue per add-on. Healthy MSP margins.

## What this doc is NOT

Not architecture — see ARCHITECTURE.md
Not a roadmap — see ROADMAP.md Phases 12, 13, and 21
Not a sales script — operator extracts the value props per client conversation
Not exhaustive — add-ons get added as you productize new things from custom client work


## Roadmap implication
This doc reframes Phase 12 (Workflow library) from "build the universal seven for all clients" to "build base tier + add-on service catalog + vertical bundles." See ROADMAP.md for updated Phase 12 / Phase 13 (voice as Retell add-on, not from-scratch build).
The first add-on to productize: whichever one your existing clients ask for first. Don't build add-ons speculatively. Build them when a paying client demands the capability, then generalize.
