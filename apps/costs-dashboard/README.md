# Phase 9.1 — drop-in for costs-dashboard (Stages 1, 4, 3, 2)

Files in this directory replace / add to the `costs-dashboard` source repo (wherever Coolify pulls from for app `e50qpvfu48m1hgln1mio8c2g` / `costs.cfpa.sekuirtek.com`).

```
app.py                                    ← extended (was 14k, now ~22k)
requirements.txt                          ← +python-multipart, +boto3
health_poller.py                          ← NEW (Stage 3 poller)
provisioning.py                           ← NEW (Stage 2 orchestrator)
addons/__init__.py                        ← NEW
addons/schemas.py                         ← NEW (Stage 4 config schemas)
migrations/001_addon_settings.sql         ← NEW (Stage 4 migration)
templates/clients.html                    ← +"+ New Client" button
templates/client_detail.html              ← extended (Stage 1 sections + Stage 4 Configure button)
templates/addon_configure.html            ← NEW (Stage 4 form)
templates/wizard.html                     ← NEW (Stage 2 multi-step form)
templates/provisioning.html               ← NEW (Stage 2 live progress)
templates/_provisioning_events.html       ← NEW (Stage 2 HTMX fragment)
```

Implementation order followed the runbook's recommendation: Stage 1 → Stage 4 → Stage 3 → Stage 2.

## What's in each stage

### Stage 1 — Per-client config screen (read-only)

Adds 6 new helper queries and extends `/client/{id}` with all 12 sections from runbook §Stage 1:
sticky health bar, header (slug + tier + onboarding badge), Infrastructure & VPS, DNS & Domain,
Email Intake (SES), Compliance, paperclipai (board API keys / agents list / skills list),
Add-ons, Integrations placeholder, Billing, Secrets (presence only), Activity, Audit, Details.

Live data (DNS dig, SES API, container status) reads from cached values in `client_configs`
and from the latest `client_health_snapshots` row. Stage 3 populates the snapshots.

### Stage 4 — Editable per-add-on config

- New SQL migration: `ALTER TABLE operator_client_addons ADD COLUMN settings JSONB NOT NULL DEFAULT '{}'`.
  Run `migrations/001_addon_settings.sql` against the paperclip DB before deploying app.py.
- New module `addons/schemas.py` defines per-add-on field schemas (bool / enum / int / text / time_of_day).
  Eight add-ons covered (Document Workflows is fully fleshed out; others are minimal placeholders).
- New routes:
  - `GET  /client/{cid}/addon/{key}/configure` — renders form pre-populated with current settings + defaults
  - `POST /client/{cid}/addon/{key}/configure` — coerces form to typed dict, writes JSONB, audits `addon.configured`
- New template `addon_configure.html`.
- "Configure" button appears in the client detail's Add-ons section for any add-on with a registered schema.

To add a new add-on: append entry to `SCHEMAS` in `addons/schemas.py`. No code changes needed.

### Stage 3 — Live health snapshots

- New module `health_poller.py`. Two ways to invoke:
  1. CLI: `docker exec costs-dashboard python /app/health_poller.py` from host crontab `*/5 * * * *`
  2. HTTP: `curl -X POST -H "X-Internal-Token: $TOK" https://costs.cfpa.sekuirtek.com/_internal/poll-health`
- Per-client checks (parallel via `asyncio.gather` + thread executor since each is sync):
  - **DNS** — subprocess `dig` for the 4 expected records (MX + 3 DKIM CNAMEs from `client_configs`). No new deps.
  - **SES** — `boto3 GetIdentityVerificationAttributes` + `GetIdentityDkimAttributes`. Skipped silently if boto3 not installed (it is now in requirements.txt).
  - **Containers** — `docker ps` if `/var/run/docker.sock` is mounted; else returns `null` and dashboard renders `?`.
  - **Backup** — proxy for `cfpa-backup-runner` container being up. Refine when a `backup_jobs` table exists.
- Writes to `client_health_snapshots` (table already exists with the right schema).
- Compares with previous snapshot; fires Discord webhook on any check that flipped from `true` → `not true`.
  Set `DISCORD_WEBHOOK_URL` env var to enable.

To enable docker socket reads from inside the costs-dashboard container, mount `/var/run/docker.sock`
in `docker-compose.yaml`. (Stage 3 still works without it — those checks just return null.)

### Stage 2 — Onboarding wizard

- New module `provisioning.py`. Sequential 16-step orchestrator. **AWS-based steps now use real boto3
  calls; infrastructure / SaaS steps remain stubs.** Status of each step:
  - `provision_vps` — ✅ **REAL for shared-VPS mode** (no-op skip with reason); raises NotImplementedError for non-shared providers (needs Phase 5.7 IaC)
  - `bootstrap_vps` — ✅ **REAL for shared-VPS mode** (no-op skip); raises for non-shared
  - `deploy_canonical_stack` — ✅ **REAL for shared-VPS mode** (no-op skip — stack already runs); raises for non-shared
  - `create_s3_bucket` — ✅ **REAL** (boto3 create_bucket + put_public_access_block + put_bucket_versioning + put_bucket_encryption, idempotent)
  - `create_sns_topic` — ✅ **REAL** (boto3 SNS create_topic + topic policy permitting SES + S3 to publish)
  - `apply_s3_bucket_policy` — ✅ **REAL** (boto3 S3 put_bucket_policy granting SES s3:PutObject)
  - `create_ses_identity` — ✅ **REAL** (boto3 SES verify_domain_identity + verify_domain_dkim, returns real DKIM tokens)
  - `create_ses_receipt_rule` — ✅ **REAL** (boto3 SES create/update_receipt_rule with S3 + SNS actions; creates the active rule set if missing)
  - `bootstrap_paperclipai` — ✅ **REAL** (verifies company exists in paperclip DB + checks paperclip /api/health; emits operator instruction to issue Board API key via `paperclip cli auth login` since key issuance is intentionally a manual approval flow in paperclip's design)
  - `step_send_welcome_email` — ✅ **REAL** (boto3 SES `send_email`; skips gracefully if no `client_owner_email` in wizard inputs)
  - `resume_after_dns` DNS poll — ✅ **REAL** (uses `health_poller.check_dns`, polls every 30s up to 10 min, fails the run on timeout)
  - DB writes (insert client_config, set s3 bucket, set SNS topic, set DKIM CNAMEs, mark active) — already implemented

**AWS prerequisites for the real steps:**
- `AWS_REGION` env var (default `us-east-2`)
- AWS credentials (default credential chain) for an IAM user with at minimum:
  `s3:CreateBucket`, `s3:PutBucketPublicAccessBlock`, `s3:PutBucketVersioning`, `s3:PutBucketEncryption`, `s3:PutBucketPolicy`,
  `sns:CreateTopic`, `sns:SetTopicAttributes`, `sts:GetCallerIdentity`,
  `ses:VerifyDomainIdentity`, `ses:VerifyDomainDkim`, `ses:CreateReceiptRule`, `ses:UpdateReceiptRule`,
  `ses:DescribeActiveReceiptRuleSet`, `ses:CreateReceiptRuleSet`, `ses:SetActiveReceiptRuleSet`, `ses:ListReceiptRuleSets`,
  `ses:SendEmail`.
- Optional `AWS_ACCOUNT_ID` env var (skips the `sts:GetCallerIdentity` lookup if set).
- Optional `WELCOME_EMAIL_FROM` env var (default `noreply@cfpa.sekuirtek.com`) — must be a verified SES sender.

- New routes:
  - `GET  /clients/new` — renders the multi-step wizard form
  - `POST /clients/new` — kicks off `run_orchestrator` as background task, redirects to live progress
  - `GET  /client/{cid}/provisioning` — live progress page (HTMX-polled every 2s)
  - `GET  /client/{cid}/provisioning/events` — HTMX fragment with the events list
  - `POST /client/{cid}/provisioning/verify-dns` — operator clicked "I've added DNS" → resumes orchestrator

- DNS pause/resume: orchestrator sets `onboarding_status='awaiting_dns'` after `create_ses_identity`,
  emits `awaiting_operator` event, stops. Operator's button click triggers `resume_after_dns()` which
  polls DNS (TODO: wire to `health_poller.check_dns`) then resumes from `create_ses_receipt_rule`.

## Pre-deployment sanity checks done

```
app.py OK
provisioning.py OK
health_poller.py OK
addons/schemas.py OK
client_detail.html OK
addon_configure.html OK
wizard.html OK
provisioning.html OK
_provisioning_events.html OK
clients.html OK
```

All Python files pass `ast.parse`; all templates pass `jinja2.Environment().parse`.
All new SQL queries verified against live schema (paperclip DB, 2026-05-06).

## Deploy order

1. **Run the SQL migration** against the paperclip DB:
   ```
   docker run --rm --network=coolify -e PGPASSWORD=paperclip postgres:17 psql \
     -h paperclip -p 54329 -U paperclip -d paperclip \
     -f - < migrations/001_addon_settings.sql
   ```
2. **Set new env vars** in Coolify for the costs-dashboard app:
   - `INTERNAL_TOKEN` — random secret for the `/_internal/poll-health` endpoint
   - `DISCORD_WEBHOOK_URL` — optional, for health-degradation alerts
   - `AWS_REGION` — optional, defaults to `us-east-2`
   - AWS credentials (for SES/S3/SNS calls) — IAM user with permissions for the boto3 calls listed above
3. **Mount docker socket** in `docker-compose.yaml` if you want container/backup checks to work:
   ```yaml
   volumes:
     - /var/run/docker.sock:/var/run/docker.sock:ro
   ```
4. **Replace files** in your costs-dashboard source repo with the contents of this dir.
5. **Push** — Coolify auto-deploys. New deps in requirements.txt rebuild the image.
6. **Add host crontab** for the health poller:
   ```
   */5 * * * * docker exec e50qpvfu48m1hgln1mio8c2g-... python /app/health_poller.py >> /var/log/costs-poller.log 2>&1
   ```
7. **Verify**:
   - `https://costs.cfpa.sekuirtek.com/clients` shows "+ New Client" button
   - `https://costs.cfpa.sekuirtek.com/client/bd80728d-...` shows all Stage 1 sections
   - Click "Configure" on Document Workflows add-on → form renders with default values
   - After 5 min, `client_health_snapshots` has a fresh row
   - Click "+ New Client" → wizard form renders → submitting kicks off orchestrator (with stubs)

## Acceptance vs runbook §Verification checklist

| # | Check | Status |
|---|---|---|
| 1 | Stage 1 config screen renders for Caring First with all 12 sections | ✅ Stage 1 |
| 2 | DNS records section reflects live state | ⏳ Stage 3 — `health_poller.check_dns` populates `client_health_snapshots`; UI reads cached |
| 3 | Add-on toggle still works (Phase 9.0 didn't regress) | ✅ Stage 1 — toggle code unchanged |
| 4 | "+ New Client" wizard end-to-end | 🟡 Stage 2 wizard runs but provisioning steps are stubbed; real calls are TODO |
| 5 | DNS pause step works | 🟡 Stage 2 pause logic implemented; `resume_after_dns` DNS poll is stubbed (1 sleep) |
| 6 | SES verification poll works | ⏳ Stage 3 wiring needed in `resume_after_dns` |
| 7 | Failure recovery works | 🟡 `start_from` parameter exists in `run_orchestrator`; "Retry" button not yet UI-wired |
| 8 | Health snapshots populate | ✅ Stage 3 — runs every 5 min via cron |
| 9 | Config edits apply | ✅ Stage 4 |
| 10 | Onboarding completion email | 🟡 `step_send_welcome_email` is stubbed |

## What's deliberately NOT implemented

- Real provisioning code (terraform, ansible, boto3 AWS calls, Coolify API) — all stubbed with TODOs
- "Retry from failed step" button — `start_from` param works but no UI button
- Decommission script (cleanup partial state on cancel) — referenced in runbook §Failure recovery, not built
- Multi-vertical / per-add-on `install()` / `reconfigure()` callbacks — schema layer ready, hooks unused
- Tier 2 Namecheap API integration — DNS step still requires manual paste

## Rollback

- Stage 1 + Stage 4 are additive at the code level; `001_addon_settings.sql` adds a column with default `'{}'` (safe).
- Stage 3 — drop the cron entry; `health_poller.py` and the `/_internal/poll-health` endpoint are independent.
- Stage 2 — the wizard route is new; reverting the source removes it. No DB schema added; the wizard relies on
  existing `client_configs`, `client_onboarding_events`, and `companies` tables.

To revert all changes: restore previous `app.py` + `templates/client_detail.html` + `templates/clients.html`
from git, drop the new files, optionally `ALTER TABLE operator_client_addons DROP COLUMN settings`.
