-- Phase 12 Stage 1.5 — Multi-method document intake schema
-- Applied 2026-05-05
--
-- Target 1: paperclip DB (postgresql://paperclip:...)
--   CREATE TABLE client_configs
--
-- Target 2: client_knowledge DB (postgresql://client_knowledge:...)
--   ALTER TABLE document_intake — relax source_type CHECK
--   ALTER TABLE document_intake — add notes JSONB column

-- ═══════════════════════════════════════════════════════════════
-- paperclip DB changes
-- ═══════════════════════════════════════════════════════════════

-- Per-client configuration: intake methods, email aliases, tier, etc.
-- Intentionally separate from companies so operator config doesn't
-- pollute the core user/company schema.
CREATE TABLE IF NOT EXISTS client_configs (
    id                    UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id            UUID        NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    tier                  TEXT        NOT NULL DEFAULT 'standard'
                                      CHECK (tier IN ('standard', 'compliance-hipaa')),
    intake_methods        JSONB       NOT NULL DEFAULT '["email"]',
    -- Each element: "email" | "web_upload" | "drive_watch" | "manual"
    intake_email_address  TEXT,
    -- e.g. caringfirst@docs.cfpa.sekuirtek.com
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (company_id)
);

CREATE INDEX IF NOT EXISTS client_configs_company_idx ON client_configs(company_id);

-- Caring First bootstrap row
INSERT INTO client_configs (company_id, tier, intake_methods, intake_email_address)
VALUES (
    'bd80728d-6755-4b63-a9b9-c0e24526c820',
    'standard',
    '["email"]',
    'caringfirst@docs.cfpa.sekuirtek.com'
)
ON CONFLICT (company_id) DO UPDATE
    SET intake_methods       = EXCLUDED.intake_methods,
        intake_email_address = EXCLUDED.intake_email_address,
        updated_at           = now();


-- ═══════════════════════════════════════════════════════════════
-- client_knowledge DB changes  (run separately against that DB)
-- ═══════════════════════════════════════════════════════════════

-- Relax source_type CHECK to allow 'email_forwarded' alongside the
-- existing 's3_drop', 'email', 'manual' values.
-- (ALTER TABLE ... DROP CONSTRAINT is the clean path in Postgres.)
-- Run this block in the client_knowledge DB connection.
--
-- ALTER TABLE document_intake DROP CONSTRAINT IF EXISTS document_intake_source_type_check;
-- ALTER TABLE document_intake ADD CONSTRAINT document_intake_source_type_check
--     CHECK (source_type IN ('s3_drop', 'email', 'email_forwarded', 'manual'));
--
-- Add notes column for email metadata (sender, subject, body excerpt).
-- ALTER TABLE document_intake ADD COLUMN IF NOT EXISTS notes JSONB;
-- GRANT SELECT, INSERT, UPDATE, DELETE ON document_intake TO client_knowledge;
-- (grant already exists; included for completeness)
