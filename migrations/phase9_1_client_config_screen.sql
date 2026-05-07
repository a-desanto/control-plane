-- Phase 9.1 — Per-client config screen schema additions
-- Target DB: paperclipai (postgresql://paperclip:paperclip@paperclip:54329/paperclip)

-- ── Extend client_configs ────────────────────────────────────────────────────

ALTER TABLE client_configs
    ADD COLUMN IF NOT EXISTS slug                    TEXT UNIQUE,
    ADD COLUMN IF NOT EXISTS onboarding_status       TEXT NOT NULL DEFAULT 'active'
        CHECK (onboarding_status IN ('provisioning','awaiting_dns','awaiting_ses_verification','active','failed','archived')),
    ADD COLUMN IF NOT EXISTS onboarding_started_at   TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS onboarding_completed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS ses_identity_status     TEXT
        CHECK (ses_identity_status IN ('pending','verified','failed',NULL)),
    ADD COLUMN IF NOT EXISTS ses_receipt_rule_name   TEXT,
    ADD COLUMN IF NOT EXISTS s3_intake_bucket        TEXT,
    ADD COLUMN IF NOT EXISTS sns_intake_topic_arn    TEXT,
    ADD COLUMN IF NOT EXISTS dns_dkim_cnames         JSONB,
    ADD COLUMN IF NOT EXISTS dns_mx_record           JSONB,
    ADD COLUMN IF NOT EXISTS board_api_keys_count    INT DEFAULT 0,
    ADD COLUMN IF NOT EXISTS agents_count            INT DEFAULT 0,
    ADD COLUMN IF NOT EXISTS skills_installed_count  INT DEFAULT 0;

-- Backfill known values for Caring First
UPDATE client_configs
SET
    slug                  = 'cfpa',
    onboarding_status     = 'active',
    onboarding_completed_at = NOW(),
    s3_intake_bucket      = 'cfpa-doc-intake-bd80728d',
    sns_intake_topic_arn  = 'arn:aws:sns:us-east-2:678051794702:cfpa-document-intake-events',
    ses_receipt_rule_name = 'cfpa-sekuirtek-com-intake',
    dns_mx_record         = '{"host": "cfpa", "value": "inbound-smtp.us-east-2.amazonaws.com", "verified": true}'::jsonb
WHERE company_id = 'bd80728d-6755-4b63-a9b9-c0e24526c820';

-- ── client_onboarding_events ─────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS client_onboarding_events (
    id          BIGSERIAL    PRIMARY KEY,
    client_uuid UUID         NOT NULL REFERENCES client_configs(company_id) ON DELETE CASCADE,
    step_name   TEXT         NOT NULL,
    status      TEXT         NOT NULL
        CHECK (status IN ('started','in_progress','completed','failed','awaiting_operator')),
    message     TEXT,
    payload     JSONB        DEFAULT '{}',
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS client_onboarding_events_client_idx
    ON client_onboarding_events (client_uuid, created_at DESC);

-- ── client_health_snapshots (Stage 3 prep) ───────────────────────────────────

CREATE TABLE IF NOT EXISTS client_health_snapshots (
    id              BIGSERIAL    PRIMARY KEY,
    client_uuid     UUID         NOT NULL REFERENCES client_configs(company_id) ON DELETE CASCADE,
    dns_ok          BOOLEAN,
    ses_verified    BOOLEAN,
    containers_ok   BOOLEAN,
    backup_ok       BOOLEAN,
    snapshot_data   JSONB,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS client_health_snapshots_client_idx
    ON client_health_snapshots (client_uuid, created_at DESC);
