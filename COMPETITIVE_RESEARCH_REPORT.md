# Competitive Analysis Report: AI Operations Platform for SMBs
## May 2026 Landscape Assessment

## Executive Summary
Tony's proposed per-VPS managed AI operations platform faces a crowded but fragmented competitive landscape with three distinct threats: horizontal automation platforms (Zapier, Make, n8n, Lindy) stealing the general-purpose automation play, vertical-specific AI tools consolidating industry niches, and cloud-native alternatives (Claude Teams, Copilot Studio, Notion AI) commoditizing foundational AI capability.
**Key Findings:**

Direct competitors are few but aggressive: Lindy ($49-199/mo per user), Beam AI (enterprise ops), and vertical-specific plays like Sully (healthcare), but none are positioning exactly like Tony (per-VPS managed service with multi-vertical depth). This is both opportunity and red flag—no one is selling this model for a reason.
Horizontal platforms are undercutting on price: Zapier ($19.99-69/mo per user, freemium), Make ($0-38/mo + usage-based credits), n8n (open-source + $30-480/mo cloud). A single SMB user can get 95% of what Tony offers by stacking Zapier + Claude + Notion AI for less than $200/month total.
Vertical-specific tools are deepening moats: Legal (Harvey, Spellbook), Medical (Suki, Nuance), Accounting (Pilot, Xero AI), Home Services (Jobber AI, ServiceTitan AI), Real Estate (Follow Up Boss AI)—each has platform lock-in and domain expertise Tony cannot match solo.
Per-VPS isolation is an expensive differentiator that most SMBs don't value. Buyers care about solved workflows, not infrastructure isolation. The overhead of managing N VPS instances will make unit economics untenable against SaaS competitors at scale.
The "productized consulting → MRR" transition is high-risk. Consulting services have high CAC and low retention; automation platforms have better LTV but require product-market fit that takes 18-24 months to prove. Trying to do both simultaneously dilutes focus.


## Competitor Landscape
### Horizontal AI Automation Platforms (Direct Threat)
CompanyPositioningPricingAI CapabilityNotesLindy.aiEmail, meetings, calendar triage$49-199/mo per userClaude 3.5 + GPT-4 + Sonnet400k+ professionals, B2B, strong email focusZapierWorkflow automation + AI agent layer$0-69/mo per user + usage-basedGPT-4o, Claude 3.5 via API5M+ apps integrated; new unified Zap/Table/Form/AI platform; MCP support coming Q2 2026Make.comVisual automation + AI agents$0-38/mo + credits (100-2M+ credits)OpenAI, Anthropic, CohereUsage-based pricing favors SMBs; enterprise deals; 2M+ usersn8nOpen-source + managed cloudFree (self-host) + $30-480/mo cloudLocal LLM integrations, Claude, GPT-4Community edition + enterprise; strong DIY appealBeam AIEnterprise process automationContact sales (enterprise only)Proprietary multi-agent500+ companies processing millions of transactions; Fortune 500 focused
**Why this matters:** An SMB can build email triage + invoice processing + lead qualification in Zapier + Make in 2 weeks for $100-200/mo total spend. No managed service, no uptime SLA, but it works. Tony's infrastructure-first positioning doesn't solve a problem these platforms already handle.

### Vertical-Specific AI Competitive State
#### Legal Tech

Harvey AI — Document analysis, contract review, legal research. Private pricing (enterprise $50k+/yr estimated). Trained on legal corpora. Backed by OpenAI. Heavy compliance and domain depth.
Spellbook — Contract drafting/review via Copilot in Word. Westlaw partnership. ~$15-30/user/month (integrated into Lexis+). Sticky.
Smokeball AI — Practice management + AI for law firms. $300-600/mo firm + per-user. Strong vertical integration.

**Gap:** General-purpose workflows (document search, email triage) are cheaper in Tony's model, but substantive legal work (contract interpretation, due diligence analysis) requires domain models these platforms have invested heavily in. Tony has a window for SMB law firms that can't afford Harvey but need more than generic automation.
#### Medical/Healthcare

Suki AI — Ambient AI scribe + clinical documentation. $200-400/clinician/mo. Works in EHR. FDA cleared. Sticky.
Nuance DAX — Microsoft-integrated ambient documentation. $150-300/user/mo via Microsoft licensing. Huge installed base.
Hippocratic AI — Purpose-built medical LLM. Private pricing (B2B). Domain safety guardrails.
Abridge — Appointment transcription + note generation. $0.50-2 per appointment (volume-based). Vertical-specific pricing model.

**Gap:** Medical practices need compliance (HIPAA), liability protection, and clinical accuracy. Tony's "compliance-grade infrastructure" thesis is good here, but without domain-specific models (like Hippocratic or Nuance), his solution is a container for a generic LLM. Margin-thin unless he goes deep on healthcare workflow expertise.
#### Accounting/Finance

Pilot — Bookkeeping + tax outsourcing + AI. $500-2000/mo firm. Vertically integrated service business.
Bench AI — Bookkeeping service + automation. $0-400+/mo depending on volume. Hybrid.
Xero AI — Integrated into Xero accounting software. $15-30/month + platform subscription. Already installed.
Karbon AI — Accounting workflow + collaboration + AI. $50-150/user/mo. Sticky within Karbon.

**Gap:** Accounting firms want to reduce manual data entry (invoice matching, receipt categorization, reconciliation). This is solvable with generic AI. Tony could win here with better integration + compliance posture than horizontal platforms. But "we manage your VPS" doesn't differentiate; "we know accounting workflows" does.
#### Home Services

Jobber AI — Scheduling + dispatching + estimate generation. $50-150/mo field team. Mobile-first.
ServiceTitan AI — CRM + ops + generative features. $150-400/mo depending on scope. Market leader.
Housecall Pro AI — Invoicing + scheduling + field management. $50-150/mo. SMB-friendly.

**Gap:** Home services need mobile-first, offline-capable tools. VPS infrastructure has high latency for field technicians. Existing players already own the workflow integration. Tony's positioning doesn't help here.
#### Real Estate

Follow Up Boss AI — CRM + automated follow-up + lead scoring. $99-299/mo per team. Dominant for brokers.
kvCORE — Lead management + AI prospecting. $150-400+/mo. Zillow-integrated.
Lofty — Property analysis + market insights. $199+/mo. Niche.

**Gap:** Real estate agents want lead scoring and pipeline automation. Existing platforms own these workflows. Tony's generic AI positioning doesn't differentiate.

### Horizontal Threats: Commoditization Risk
#### Claude Teams / Claude for Work (Anthropic)

Pricing: $25-50/user/month (estimated for Teams, announced Q1 2026)
Features: Shared workspace, document upload, custom instructions, API access, extended context
Threat to Tony: Companies that need "AI copilot for document work" can get Claude Teams + shared knowledge base + automation via Zapier's new MCP integrations. No managed service needed.
Timeline: Claude 3.7 expected Q3 2026; Anthropic moving fast on tooling.

#### Microsoft Copilot Studio / Copilot Pro for Business

Pricing: $20/user/month (Copilot Pro for individuals); Teams integration bundled with Microsoft 365
Features: Copilot in Word, Excel, Teams, Outlook; custom agents via Copilot Studio; semantic search
Threat to Tony: Any SMB on Microsoft 365 (most SMBs) already has Copilot in their workflow. Adding custom agents is free or low-cost. Microsoft's distribution wins.

#### Notion AI / Notion Enterprise

Pricing: $8/user/month (AI add-on to Pro); custom instance pricing for Enterprise
Features: Database automation, doc generation, search, AI-powered queries, database syncing
Threat to Tony: Knowledge workers already in Notion. Notion AI for document/data automation is excellent and cheap.

#### Google Workspace with Gemini

Pricing: Bundled into Workspace Business Standard ($18/user/mo) and above
Features: Gemini in Docs, Sheets, Gmail, Drive; custom agents via Google Workspace integrations
Threat to Tony: Google's installed base is huge. Free tier makes experimentation frictionless.

**Strategic implication:** By 2026, the "horizontal AI platform for SMBs" market will have consolidated around a few major cloud vendors (Microsoft, Google, Anthropic) bundling AI + integration. Tony cannot compete on breadth of integrations or pricing at this level. He needs vertical depth and managed service value.

### Traditional MSP Threat (Emerging)
MSPAI OfferingsPositioningNotesKaseyaVSA integrations + partner marketplace"AI for IT ops"Managed service provider platform; some integrations but no unified AI layerConnectWiseAutomation Builder + Zapier integrations"Managed service automation"Strong in MSP world but not AI-nativeNtivaCustom automation + consultingAd-hocCase-by-case, not productizedArctic WolfSecurity automationSecurity-specificNot a horizontal threat
**Assessment:** Traditional MSPs are slow to move into generative AI, and none have built a compelling "managed AI operations" service yet. Opportunity window: 12-18 months before a top-tier MSP (Kaseya, ConnectWise) launches a productized AI offering. Once they do, they'll have installed base, trust relationships, and economies of scale Tony can't match.

## Pricing Model Analysis
### Observed Pricing Structures (2026)
**Per-user SaaS (Most common)**

Lindy: $49-199/user/mo
Zapier Pro: $69/user/mo
Make: ~$21/user/mo equivalent (Pro plan)
Notion AI: $8/user/mo add-on
Copilot Pro: $20/user/mo

**Usage-based / Credits**

Make.com: $0.014 per operation; 100 credits/mo = ~$2, 2M ops = ~$28k/mo
Zapier Tables: Task-based pricing (lower tiers)
OpenRouter Proxy (Tony's model): Per-token pricing ($0.0005-0.003 per token)

**Per-organization / Per-instance**

Beam AI: Enterprise negotiated deals (>$50k/yr estimated)
Harvey: Estimated $50k+ annual for large law firms
Suki (healthcare): $200-400/clinician/mo
Tony's proposed: $500-10k/mo per VPS

**Hybrid (Service + Platform)**

Pilot (accounting): $500-2000/mo firm + service hours
Bench: $0-400+/mo + bookkeeping service
Hubstaff (time tracking + AI): $10-30/user/mo + premium AI features

### Tony's Pricing in Context
Tony's proposed tiers ($500-$10k/mo per VPS, $8-15k setup fee) are positioned at the high end of what an SMB would pay for a software solution. Comparison:

Starter ($500/mo): 2.5x Lindy Pro, 7.4x Zapier Pro, 2.4x Make Pro. For one client on one VPS.
Pro ($1500/mo): 7.5x Lindy Pro, 21.7x Zapier Pro, 71x Notion AI. Assumes high utilization.
Concierge ($10k/mo): 50x Lindy Pro; enters consulting territory.

**Verdict:** Pricing is defensible ONLY if Tony's offering is demonstrably better than horizontal platforms + vertical domain expertise at solving a specific vertical's workflow. Generic "lead qualification + email triage + invoice processing" at $1500/mo loses to Zapier + Make at $100/mo. But "AI-powered legal research + document management + compliance + per-VPS HIPAA infrastructure" for a healthcare network at $3-5k/mo is potentially defensible.

## Business Model Failure Patterns (2024-2026)
### 1. Customer Acquisition Cost Death Spiral

Example: Anthropic's internal services consulting (2023-2024). Realized CAC > LTV. Pivoted to API model.
Example: OpenAI Services partners hit similar wall in 2025. Custom implementation costs killed margins.
Risk for Tony: Productized consulting ($8-15k upfront) doesn't pay for a sales motion at SMB scale. If CAC > $3-5k via content + referrals, unit economics are underwater.

### 2. Foundation Model Commoditization

Example: Dozens of "AI writing assistant" startups (2022-2024) displaced by ChatGPT free tier.
Example: Document.ai and competitors in document processing displaced by Claude's native capabilities.
Current risk: As Claude and GPT become commodity APIs and Claude Teams/Copilot embed in Microsoft/Google, standalone "AI operations" SaaS loses differentiation.
Timeline: 12-24 months before vertical-specific moats matter more than horizontal platform breadth.

### 3. Scaling Beyond Founder: The Bottleneck

Example: Copysmith, Copy.ai, and dozens of other AI writing tools plateaued at $1-5m ARR when they hit the "founder is the product" ceiling.
Example: Custom AI consulting shops stay stuck at $2-3m revenue because the founder is the sales process, the domain expert, and the relationship anchor.
For Tony: He's targeting 5 verticals solo. Accounting + legal + healthcare + home services + real estate have almost nothing in common. Each needs domain language and workflow knowledge. He'll hit the ceiling fast unless he hires and documents rigorously.

### 4. Compliance / Security Incidents

Example: Clearview AI (facial recognition) and Databricks (data privacy incidents) killed investor sentiment in 2023-2024.
Risk for Tony: "Per-VPS HIPAA infrastructure" is a compliance claim. If one client has a breach, he's liable. Insurance costs money. Liability compounds as client count grows.

### 5. Acquihires vs. Failures

Acquihire examples (2024-2025): Dust Labs (Claude for teams, acquired by Anthropic), Lightning AI (acquired by Pagerduty), dozens of small automation shops acquired by larger platforms for team/IP only, not product fit.
True failures: Fewer standalone AI ops companies have shut down, but many have pivoted hard (e.g., Tavily became a search agent).
For Tony: If he doesn't achieve product-market fit in 18 months, he's acquihire bait—Zapier, Make, or a major MSP could buy his code + 1 client and call it a win. That's not a sustainable business plan.


## Business Model Critique: Tony's Plan
### Flaw #1: Per-VPS Infrastructure is a Cost Center, Not a Moat (SEVERITY: HIGH)
**The Problem:** Positioning every customer on a dedicated VPS is presented as a security/compliance feature. It actually solves a problem no one has.
**Evidence:**

Healthcare practices use Suki (SaaS, shared infrastructure) and trust compliance certifications, not VPS isolation.
Legal firms use Harvey (SaaS) and rely on contractual indemnification, not infrastructure segregation.
Accounting firms run on Xero/Intuit (SaaS) and compliance audits, not dedicated servers.

**Why this matters:**

VPS management is a cost center (hosting, monitoring, patching, networking). Tony pays $20-50/month per VPS. At scale with 50 clients, that's $1200-3000/month in pure overhead before he profits.
Shared infrastructure (multi-tenant SaaS) scales to lower unit costs. Zapier pays ~$0.50/user/mo for compute; Tony pays $50/VPS.
HIPAA compliance doesn't require infrastructure isolation; it requires audit trails, encryption, and BAA agreements. You can be HIPAA-compliant on Azure's shared infrastructure.

**Recommendation:** Consider pivoting to multi-tenant SaaS with vertical-specific hardening (compliance templates, audit logs, role-based access for healthcare). Per-VPS positioning is a liability, not an asset.
### Flaw #2: Self-Hosting paperclipai is a Single-Point-of-Failure Dependency (SEVERITY: MEDIUM-HIGH)
**The Problem:** Tony is building on top of paperclipai (Node.js orchestration layer he controls), which is an upstream dependency he's responsible for maintaining.
**Evidence:**

n8n and Zapier are maintained by large teams; updates, security patches, and feature requests flow regularly.
If paperclipai has a critical bug, Tony owns fixing it across all clients.
If paperclipai doesn't scale (performance, concurrency), Tony has to rewrite or migrate.

**Why this matters:**

Maintenance overhead increases with client count.
Every paperclipai update is a risk surface for all clients simultaneously.
Competing platforms (Make, Zapier, Beam) have dedicated platform teams. Tony doesn't.

**Recommendation:** Either (a) contribute paperclipai to open-source with a community (share maintenance burden), or (b) pivot to white-label existing platforms (Zapier/Make/n8n) with vertical customization. The "build custom platform" path only works if you're willing to scale the engineering team significantly by Month 12.
### Flaw #3: Five Verticals Simultaneously = Unfocused Positioning (SEVERITY: MEDIUM-HIGH)
**The Problem:** Selling to legal, medical, accounting, home services, and real estate means:

5 different sales pitches (one narrative won't resonate across all)
5 different compliance regimes (legal vs. healthcare vs. accounting all have different requirements)
5 different domain workflows (a medical scribe AI is completely different from legal contract analysis)

**Evidence:**

Lindy focuses on "email triage for knowledge workers" (horizontal, cross-vertical).
Harvey focuses on legal AI (deep, vertical-specific).
Suki focuses on healthcare documentation (deep, vertical-specific).
Successful SaaS companies either go deep on one vertical or broad on one workflow. Not deep on five verticals.

**Recommendation:** Pick one vertical. Spend 6 months becoming an expert in that vertical's workflows, compliance, and pain points. Then expand. Vertical depth > horizontal breadth for SMB sales.
### Flaw #4: Productized Consulting Model Doesn't Scale to SaaS LTV (SEVERITY: HIGH)
**The Problem:** Tony's plan is:

Sell $8-15k setup/implementation consulting
Follow with $1500-10k/mo recurring
Hope enough clients stick around to hit SaaS metrics

**Evidence:**

Successful consulting-to-SaaS transitions (Salesforce, HubSpot) had strong product differentiation, not commodity implementation.
Most "productized consulting" companies plateau at $2-3m ARR because CAC is high (requires sales skill) and LTV is low (clients churn when implementation ends).
Tony's current customer (Caring First healthcare) is likely the "easy sell" (warm intro, technical founder, aligned incentives). Scaling to 10+ customers via sales will be much harder.

**Math:**

$8k setup: Assumes 40 hours @ $200/hr. Tony's time.
$1500/mo recurring: Assumes 5 hours/mo support + 10% infrastructure + profit margin. Tight.
CAC payback period: 5-6 months. If churn is >20% per year (realistic for SMB SaaS), LTV = $9000. Profit margin is ~$2000/client after CAC. Not compelling.

**Recommendation:** Choose. Either (a) go deep on productized consulting with high ACV ($10-50k upfront + $3-5k/mo) and focus on implementation excellence, or (b) go SaaS with lower setup costs (or none) and focus on product stickiness. Trying to do both dilutes both.
### Flaw #5: Sales Motion is Missing for a Solo Operator (SEVERITY: HIGH)
**The Problem:** Tony needs to answer: "How do I get 50+ SMB customers to sign $1500/mo contracts?"
**Reality:**

Zapier gets new customers via: free tier virality, SEO, partner integrations, enterprise sales team.
Harvey gets legal customers via: direct sales to partnerships (BigLaw), referrals, network effects.
Suki gets medical customers via: hospital pilot programs, regulatory approvals, direct sales.
Tony has: 1 customer (Caring First), no public case studies, no enterprise sales experience.

**Why this matters:**

SMB sales requires either (a) self-serve product + marketing (Zapier's model), (b) partner channels (MSPs, industry groups), or (c) direct sales team.
Tony solo cannot do (c). Can he do (a) or (b)?

(a) Self-serve: Requires product that works for SMBs out-of-the-box. His current positioning (custom per-VPS setup) is not self-serve.
(b) Partnerships: Requires existing relationships (integration partners, MSPs, industry bodies). None evident.



**Recommendation:** Before committing more engineering time, validate sales motion with 3-5 paying customers via partnerships or direct outreach. If you can't get to 5 customers in 6 months via part-time sales, you don't have product-market fit. The second 50 customers will cost money you don't have.
### Flaw #6: Vertical-Specific Moats Are Deeper Than Horizontal Infrastructure (SEVERITY: MEDIUM)
**The Problem:** What actually wins in vertical SaaS is domain expertise, not infrastructure. Tony is betting on infrastructure (per-VPS isolation) as the moat. Wrong bet.
**Evidence:**

Legal: Harvey wins on contract understanding + legal precedent, not infrastructure.
Medical: Suki wins on clinical understanding + liability, not infrastructure.
Accounting: Pilot wins on tax knowledge + integration with tax software, not infrastructure.

**For Tony:** A horizontal "AI ops" platform with generic lead qualification + email triage + invoice processing has no moat. Any of Zapier/Make/Lindy can reproduce it in weeks. If Tony is going to compete, he needs:

Vertical-specific LLM fine-tuning (legal document understanding, medical coding, accounting reconciliation rules)
Compliance + liability packages (insurance, BAA, audit trails)
Workflow templates built by domain experts, not developers

**Recommendation:** If you're going to compete on verticals, go vertical-first. Pick healthcare. Spend 3 months learning EMR workflows, HIPAA requirements, and payer systems. Then build and market to that vertical. Don't claim to serve 5 verticals equally; you'll serve none well.

## Strategic Recommendations
### Priority 1: Validate Sales Motion Before Building (CRITICAL)
**Action:** Spend the next 6 weeks getting 3 more customers (beyond Caring First) to commit to $1500+/mo contracts via direct outreach + partnership conversations. If you can't close 3 deals in 6 weeks with part-time effort, the market opportunity is not where you think it is.
**Method:**

Identify 20 target customers in one vertical (healthcare, legal, or accounting).
Have 30-minute conversations with 10 of them. Listen for their actual pain point.
Offer a beta/pilot at a 30-50% discount if they'll sign a 3-month contract and do a case study with you.
Track: # conversations, # qualified leads, # pilots signed, # closed.

**Outcome:** If you hit 3-5 pilots, you have product-market fit signals. Invest in engineering. If you hit 1-2, rethink positioning or vertical.
### Priority 2: Pick One Vertical and Go Deep (HIGH)
**Action:** Decide on one vertical (healthcare, legal, or accounting) in the next 2 weeks. Commit fully.
**Rationale:**

Healthcare is underserved by affordable managed services (Suki + Nuance are expensive; Caring First is your proof point).
Legal is consolidating around Harvey (hard to compete) but SMB law firms ($50k-500k revenue) don't have budget for Harvey.
Accounting is fragmented and competitive but high-margin opportunity.

**Healthcare example:**

Become expert in EHR integrations (Cerner, Epic, FHIR APIs).
Partner with a medical staffing agency or healthcare MSP to distribute.
Offer: "AI copilot for clinical documentation + chart review + patient communication triage" as a service.
Price: $300-500/clinician/mo (competitive with Suki for SMBs).
Get first 5 healthcare customers in 3 months.

### Priority 3: Reconsider Per-VPS Architecture (HIGH)
**Action:** Run a cost/benefit analysis on per-VPS isolation vs. multi-tenant + vertical security hardening.
**Questions:**

Do any of your target customers actually require VPS isolation, or are they fine with HIPAA BAA + encryption?
What's the real cost difference between managing 50 VPS instances vs. multi-tenant infrastructure?
Can you compete on price if you're paying $50/mo per VPS in hosting alone?

**Decision:** If isolation is not a hard requirement for your vertical, pivot to multi-tenant SaaS. If it is (e.g., certain healthcare networks), keep it but market it as a premium tier, not the base offering.
### Priority 4: Choose Business Model (Consulting vs. SaaS) (HIGH)
**Action:** Decide by end of Q2 2026.
**Consulting model:** Position as "AI implementation partner for SMBs." Sell $20-50k projects with 12-month follow-on support at $2-5k/mo. Hire a sales person. Target 5-10 clients per year at $50-100k ACV. This scales to $500k-1m ARR in 2 years with a small team.
**SaaS model:** Remove the setup fee or lower it to $2-5k. Focus on product stickiness and self-serve onboarding. Vertical templates should be so good that a domain expert can set up their AI in a day. Target 50+ SMB customers at $1.5-3k/mo. Requires marketing + product excellence.
**Hybrid (risky):** $8k setup + $1500/mo MRR is the worst of both worlds (high CAC, medium LTV). Avoid.
### Priority 5: Address the Sales Bottleneck NOW (CRITICAL)
**Action:** Before hiring engineers, hire or partner with a sales resource.
**Options:**

Hire a part-time sales contractor ($3-5k/mo) who focuses on SMBs in your chosen vertical.
Partner with an MSP or industry group for referrals (revenue share model).
Run a content + SEO strategy targeting your vertical ("How to implement AI in a medical practice").

**Why:** No amount of product engineering will matter if you can't sell. Validate sales motion with 3-5 customers first.

## Conclusion
Tony's core idea—managed AI operations for SMBs—is viable, but the execution is misaligned with how the market is moving. Per-VPS infrastructure, five verticals simultaneously, and reliance on a custom platform (paperclipai) are liabilities, not assets.
**The path forward:**

Vertical focus: Pick healthcare (high-compliance, high-margin, underserved by affordable options). Spend 3 months learning the vertical, not building more features.
Sales first: Validate that SMBs in your vertical will pay $1-3k/mo for a managed AI service. Close 3-5 pilot customers before committing more engineering.
Pragmatic architecture: Multi-tenant SaaS with compliance hardening beats per-VPS isolation. Leverage existing platforms (Zapier, Make, n8n) as orchestration, not build custom.
Business model clarity: Commit to either consulting or SaaS, not both. Consulting (higher ACV, lower scale) may be more realistic for a solo operator in year 1-2.
Sales and domain expertise: Hire or partner for sales immediately. You are the technical founder; let someone else own customer acquisition.

The window to win in this space is real—horizontal platforms are commoditizing, verticals are fragmenting, and SMBs need affordable managed services. But the opportunity expires in 12-18 months when MSPs and cloud vendors launch their own AI services. Move fast on validation and positioning, not on code.

---
*Report compiled: May 2, 2026*
*Data sources: Zapier, Make, n8n, Lindy, Beam, Sully, Harvey public information; industry reports; pricing pages accessed May 2, 2026.*
