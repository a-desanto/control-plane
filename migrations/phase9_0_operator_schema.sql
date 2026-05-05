-- Phase 9.0: Operator Dashboard Schema
-- Target DB: paperclip (postgresql://paperclip:paperclip@paperclip:54329/paperclip)
-- Applied: 2026-05-05

-- Add-on state per company. One row per (company, addon_key).
-- addon_key values: 'document_workflows' (Phase 12), future: 'rag_search', 'langfuse_tracing'
CREATE TABLE IF NOT EXISTS operator_client_addons (
    id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id   UUID        NOT NULL REFERENCES companies(id),
    addon_key    TEXT        NOT NULL,
    enabled      BOOLEAN     NOT NULL DEFAULT false,
    installed_at TIMESTAMPTZ,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (company_id, addon_key)
);

CREATE INDEX IF NOT EXISTS operator_client_addons_company_idx
    ON operator_client_addons(company_id);

-- Audit trail of every operator action (toggle add-on, future: pause client, etc.)
CREATE TABLE IF NOT EXISTS operator_audit_log (
    id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    operator_email TEXT        NOT NULL,
    company_id     UUID        REFERENCES companies(id),
    action         TEXT        NOT NULL,
    addon_key      TEXT,
    details        JSONB,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS operator_audit_log_company_idx
    ON operator_audit_log(company_id, created_at DESC);

CREATE INDEX IF NOT EXISTS operator_audit_log_created_idx
    ON operator_audit_log(created_at DESC);

-- Bootstrap: Caring First gets a document_workflows row (disabled until Stage 4 install)
INSERT INTO operator_client_addons (company_id, addon_key, enabled, installed_at)
VALUES (
    'bd80728d-6755-4b63-a9b9-c0e24526c820',
    'document_workflows',
    false,
    NULL
)
ON CONFLICT (company_id, addon_key) DO NOTHING;
