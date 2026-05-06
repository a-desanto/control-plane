# Phase 12 — Document Workflows Runbook

**Last updated:** 2026-05-05  
**Status:** Stage 1 — DONE 2026-05-05. Stage 1.5 — IN PROGRESS 2026-05-05 (SES receipt rule pending admin credential run). Stage 2 (PaddleOCR + document-agent) — Substage A complete (paddleocr-service deployed).

---

## Overview

Document intake pipeline for Caring First (and eventually all clients). Documents land in S3 drop buckets, trigger SNS events, the webhook sidecar records each intake row in client_knowledge DB, and the document-agent (Stage 2) runs OCR + classification.

### OCR Architecture

- **Canonical:** PaddleOCR (self-hosted, no per-call cost)
- **Fallback:** AWS Textract (pay-per-use, for documents PaddleOCR can't handle cleanly)
- PaddleOCR and Textract are **Stage 2** — not deployed in Stage 1

---

## Stage 1 — Inbound Trigger Path (DONE 2026-05-05)

Stage 1 establishes the inbound trigger path: S3 → SNS → webhook handler → DB row. No OCR or classification happens yet.

### What was built

| Component | Location | Status |
|-----------|----------|--------|
| DB schema (4 tables + bucket map) | `migrations/phase12_document_intake_schema.sql` | Applied to `xcn2es4vmn01a1ug0w99vdr3` |
| S3 drop bucket | `cfpa-doc-intake-bd80728d` us-east-2 | **Pending: needs admin AWS credentials** |
| SNS topic | `cfpa-document-intake-events` | **Pending: runs after bucket creation** |
| Webhook sidecar | `workers/document-intake-webhook/` | Running: container `document-intake-webhook` |
| Traefik routing | Priority-200 rule | Live: routes `paperclipai.cfpa.sekuirtek.com/api/webhooks/document-intake` to sidecar |

### Pending actions (Step 2 blocker)

The `backup-runner-srv1408380` IAM user doesn't have `s3:CreateBucket`. Run these scripts with admin credentials:

```bash
# 1. Create bucket + extend IAM
AWS_ADMIN_ACCESS_KEY_ID=<key> AWS_ADMIN_SECRET_ACCESS_KEY=<secret> \
  python3 scripts/phase12_create_s3_bucket.py

# 2. Wire SNS (after bucket exists)
python3 scripts/phase12_setup_sns.py

# 3. Watch for SNS SubscriptionConfirmation auto-confirm
docker logs -f document-intake-webhook
```

---

## Database schema

Applied to `xcn2es4vmn01a1ug0w99vdr3` (client_knowledge pgvector DB, pg18).  
Migration file: `migrations/phase12_document_intake_schema.sql`

### Tables

#### `document_intake`
Central intake registry. Every inbound document gets one row.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | gen_random_uuid() |
| company_id | UUID NOT NULL | Links to paperclipai company |
| source_type | TEXT | 's3_drop' \| 'email' \| 'manual' |
| source_uri | TEXT | e.g. `s3://cfpa-doc-intake-bd80728d/invoices/foo.pdf` |
| raw_pdf_s3_key | TEXT | Object key within the bucket |
| status | TEXT | 'received' → 'ocr_pending' → 'ocr_done' → 'classified' → 'done' \| 'failed' |
| doc_type | TEXT | Null until classified: 'invoice' \| 'contract' \| 'intake_form' \| 'unknown' |
| metadata | JSONB | Arbitrary structured metadata |
| created_at | TIMESTAMPTZ | |
| updated_at | TIMESTAMPTZ | |

#### `invoices`
Extracted invoice data. Populated by Stage 2 document-agent after OCR.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| document_intake_id | UUID FK → document_intake | CASCADE delete |
| company_id | UUID | |
| vendor_name | TEXT | |
| invoice_number | TEXT | |
| invoice_date | DATE | |
| due_date | DATE | |
| total_amount | NUMERIC(12,2) | |
| currency | TEXT | Default 'USD' |
| line_items | JSONB | Array of line item objects |
| raw_extracted | JSONB | Raw OCR extraction output |

#### `contracts`
Extracted contract data. Populated by Stage 2 document-agent after OCR.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| document_intake_id | UUID FK → document_intake | CASCADE delete |
| company_id | UUID | |
| contract_type | TEXT | e.g. 'service_agreement', 'nda', 'lease' |
| parties | JSONB | Array of party objects {name, role} |
| effective_date | DATE | |
| expiry_date | DATE | |
| value_amount | NUMERIC(12,2) | |
| currency | TEXT | Default 'USD' |
| key_clauses | JSONB | Extracted key clause summaries |
| raw_extracted | JSONB | Raw OCR extraction output |

#### `intake_forms`
Extracted intake form data. Populated by Stage 2 document-agent after OCR.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| document_intake_id | UUID FK → document_intake | CASCADE delete |
| company_id | UUID | |
| form_type | TEXT | e.g. 'new_patient', 'insurance', 'hipaa' |
| patient_name | TEXT | |
| date_of_service | DATE | |
| fields | JSONB | Keyed field extraction results |
| raw_extracted | JSONB | Raw OCR extraction output |

#### `bucket_company_map`
Maps S3 bucket names to company UUIDs.

| Column | Type | Notes |
|--------|------|-------|
| bucket_name | TEXT PK | e.g. 'cfpa-doc-intake-bd80728d' |
| company_id | UUID | |
| created_at | TIMESTAMPTZ | |

Seeded: `cfpa-doc-intake-bd80728d` → `bd80728d-6755-4b63-a9b9-c0e24526c820` (Caring First)

---

## S3 Drop Bucket

| Setting | Value |
|---------|-------|
| Bucket | `cfpa-doc-intake-bd80728d` |
| Region | us-east-2 |
| Versioning | Enabled |
| Encryption | SSE-S3 (AES-256) |
| Public access | Blocked (all 4 settings) |
| IAM | backup-runner-srv1408380: PutObject + GetObject + ListBucket |

**Naming convention for new client buckets:** `cfpa-doc-intake-<first-8-chars-of-company-uuid>`

---

## SNS Topic

| Setting | Value |
|---------|-------|
| Topic name | `cfpa-document-intake-events` |
| Topic ARN | `arn:aws:sns:us-east-2:678051794702:cfpa-document-intake-events` |
| Region | us-east-2 |
| Subscriptions | HTTPS → `https://paperclipai.cfpa.sekuirtek.com/api/webhooks/document-intake` |
| S3 triggers | `s3:ObjectCreated:*` on `cfpa-doc-intake-bd80728d` |

---

## Webhook Sidecar

**Container:** `document-intake-webhook`  
**Source:** `workers/document-intake-webhook/`  
**URL:** `https://paperclipai.cfpa.sekuirtek.com/api/webhooks/document-intake`  
**Traefik priority:** 200 (overrides paperclipai's catch-all)

### Behavior

1. **SubscriptionConfirmation**: auto-confirms by fetching `SubscribeURL`
2. **Notification (S3 PUT)**: verifies SNS signature → parses S3 event → resolves `company_id` from `bucket_company_map` → INSERTs `document_intake` row with `status='received'`
3. **Test event** (0 records): acknowledges with `{ok:true, processed:0}`

### Environment variables

| Variable | Required | Notes |
|----------|----------|-------|
| `CKDB_URL` | Yes | `postgresql://client_knowledge:<pass>@openclaw-pgvector-db:5432/client_knowledge` |
| `PORT` | No | Default 4010 |
| `LOG_LEVEL` | No | Default 'info' |
| `SNS_SKIP_SIGNATURE_VERIFY` | No | Set 'true' for local testing only |

---

## Stage 1.5 — Multi-method Document Intake (IN PROGRESS 2026-05-05)

Adds email forwarding as the primary non-S3 intake path. Architecture is extensible: all paths funnel documents into the same S3 bucket, triggering the existing SNS → webhook pipeline.

### Intake interfaces

| Path | Method | Status |
|------|--------|--------|
| Path 1 | **Email forwarding via AWS SES** | ✅ live (SES receipt rule + webhook MIME handler) |
| Path 2 | Web upload form (Phase 9 end-client UI) | planned |
| Path 3 | Drive/Dropbox watch via Nango (Phase 15) | planned |

### How email forwarding works

```
Email → intake@cfpa.sekuirtek.com
  └─ SES receipt rule (cfpa-inbound / cfpa-sekuirtek-com-intake)
       └─ S3: s3://cfpa-doc-intake-bd80728d/inbox/<message-id>
            └─ S3 ObjectCreated event → SNS → webhook
                 └─ webhook: fetch .eml, parse MIME, extract attachments
                      └─ S3: email-attachments/<message-id>/<filename>
                           └─ document_intake row (source_type='email_forwarded')
```

### Per-client email address pattern

Each client gets one email alias on their own subdomain:

| Client | Email | Bucket |
|--------|-------|--------|
| Caring First | `intake@cfpa.sekuirtek.com` | `cfpa-doc-intake-bd80728d` |
| *Next client* | `intake@<client-subdomain>.sekuirtek.com` | `cfpa-doc-intake-<first-8-of-uuid>` |

**Onboarding checklist for new client email intake:**
1. Add MX record: `Host: <client-subdomain>` → `inbound-smtp.us-east-2.amazonaws.com` (priority 10)
2. Add SES domain verification TXT record (from AWS Console → SES → Verified identities)
3. Wait for `VerificationStatus=Success` (usually 5–30 min)
4. Run `scripts/phase12_1_5_ses_setup.py` with admin creds, updating `DOMAIN`, `BUCKET`, `RULE_NAME` constants
5. UPDATE `client_configs SET intake_email_address = 'intake@<subdomain>.sekuirtek.com'` for the company

### Schema additions (applied 2026-05-05)

**paperclip DB:**
- `client_configs` table created (company_id, tier, intake_methods JSONB, intake_email_address)
- Caring First seeded: `intake_methods=["email"]`, `intake_email_address='intake@cfpa.sekuirtek.com'`

**client_knowledge DB:**
- `document_intake.source_type` CHECK updated to include `'email_forwarded'`
- `document_intake.notes JSONB` column added (stores sender, subject, body excerpt, message_id)

### SES infrastructure (cfpa.sekuirtek.com)

| Resource | Value |
|----------|-------|
| Verified domain | `cfpa.sekuirtek.com` (Verified + DKIM) |
| SES rule set | `cfpa-inbound` (active) |
| Receipt rule | `cfpa-sekuirtek-com-intake` |
| Recipients | `cfpa.sekuirtek.com` (matches all @cfpa.sekuirtek.com) |
| S3 destination | `s3://cfpa-doc-intake-bd80728d/inbox/` |
| Bucket policy | `AllowSESInboundPuts` statement added |

### Smoke test

```bash
# Forward any email with a PDF attachment to: intake@cfpa.sekuirtek.com
# Then verify:
docker exec document-intake-webhook node -e "
const { Pool } = require('pg');
const pool = new Pool({ connectionString: process.env.CKDB_URL });
pool.query(\"SELECT id, source_type, source_uri, raw_pdf_s3_key, status, created_at FROM document_intake WHERE source_type='email_forwarded' ORDER BY created_at DESC LIMIT 5\")
  .then(r => { r.rows.forEach(row => console.log(JSON.stringify(row))); pool.end(); })
  .catch(e => { console.error(e.message); pool.end(); });
"
```

---

## Stage 2 — OCR + Document Agent (NEXT)

Stage 2 adds:
- PaddleOCR service (Docker container, GPU optional)
- Textract fallback (AWS SDK, pay-per-page)
- document-agent: picks up `status='received'` rows, runs OCR, classifies, updates rows and populates `invoices`/`contracts`/`intake_forms`
- Status flow: `received` → `ocr_pending` → `ocr_done` → `classified` → `done`

---

## End-to-end smoke test (run after Stage 1 S3 + SNS are live)

```bash
# Drop a test PDF (set AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY in env first)
python3 -c "
import boto3, os
s3 = boto3.client('s3', region_name='us-east-2')
s3.put_object(Bucket='cfpa-doc-intake-bd80728d', Key='test/test.pdf', Body=b'%PDF-1.4 test')
print('uploaded')
"

# Wait ~60s, then verify DB row
docker exec xcn2es4vmn01a1ug0w99vdr3 psql -U postgres -d client_knowledge -c "
SELECT id, company_id, source_type, source_uri, status, created_at
FROM document_intake
WHERE company_id = 'bd80728d-6755-4b63-a9b9-c0e24526c820'
ORDER BY created_at DESC LIMIT 1;"

# Expected: one row, source_type='s3_drop', status='received', created_at within last minute
```
