-- Phase 12 Document Workflow schema
-- Applied to xcn2es4vmn01a1ug0w99vdr3 (client_knowledge DB)

SET search_path = public;

-- document_intake: central intake registry for every document entering the system
CREATE TABLE IF NOT EXISTS document_intake (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id      UUID        NOT NULL,
    source_type     TEXT        NOT NULL CHECK (source_type IN ('s3_drop', 'email', 'manual')),
    source_uri      TEXT        NOT NULL,
    raw_pdf_s3_key  TEXT,
    status          TEXT        NOT NULL DEFAULT 'received'
                                CHECK (status IN ('received', 'ocr_pending', 'ocr_done', 'classified', 'done', 'failed')),
    doc_type        TEXT        CHECK (doc_type IN ('invoice', 'contract', 'intake_form', 'unknown')),
    metadata        JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS document_intake_company_id_idx  ON document_intake (company_id);
CREATE INDEX IF NOT EXISTS document_intake_status_idx      ON document_intake (status);
CREATE INDEX IF NOT EXISTS document_intake_created_at_idx  ON document_intake (created_at DESC);

-- invoices: extracted invoice data (Stage 2 OCR agent populates)
CREATE TABLE IF NOT EXISTS invoices (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    document_intake_id  UUID        NOT NULL REFERENCES document_intake(id) ON DELETE CASCADE,
    company_id          UUID        NOT NULL,
    vendor_name         TEXT,
    invoice_number      TEXT,
    invoice_date        DATE,
    due_date            DATE,
    total_amount        NUMERIC(12, 2),
    currency            TEXT        DEFAULT 'USD',
    line_items          JSONB,
    raw_extracted       JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS invoices_company_id_idx          ON invoices (company_id);
CREATE INDEX IF NOT EXISTS invoices_document_intake_id_idx  ON invoices (document_intake_id);

-- contracts: extracted contract data (Stage 2 OCR agent populates)
CREATE TABLE IF NOT EXISTS contracts (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    document_intake_id  UUID        NOT NULL REFERENCES document_intake(id) ON DELETE CASCADE,
    company_id          UUID        NOT NULL,
    contract_type       TEXT,
    parties             JSONB,
    effective_date      DATE,
    expiry_date         DATE,
    value_amount        NUMERIC(12, 2),
    currency            TEXT        DEFAULT 'USD',
    key_clauses         JSONB,
    raw_extracted       JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS contracts_company_id_idx          ON contracts (company_id);
CREATE INDEX IF NOT EXISTS contracts_document_intake_id_idx  ON contracts (document_intake_id);

-- intake_forms: extracted form data (Stage 2 OCR agent populates)
CREATE TABLE IF NOT EXISTS intake_forms (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    document_intake_id  UUID        NOT NULL REFERENCES document_intake(id) ON DELETE CASCADE,
    company_id          UUID        NOT NULL,
    form_type           TEXT,
    patient_name        TEXT,
    date_of_service     DATE,
    fields              JSONB,
    raw_extracted       JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS intake_forms_company_id_idx          ON intake_forms (company_id);
CREATE INDEX IF NOT EXISTS intake_forms_document_intake_id_idx  ON intake_forms (document_intake_id);

-- bucket_company_map: maps S3 drop-bucket names to company UUIDs
CREATE TABLE IF NOT EXISTS bucket_company_map (
    bucket_name TEXT        PRIMARY KEY,
    company_id  UUID        NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Seed the Caring First bucket mapping
INSERT INTO bucket_company_map (bucket_name, company_id)
VALUES ('cfpa-doc-intake-bd80728d', 'bd80728d-6755-4b63-a9b9-c0e24526c820')
ON CONFLICT (bucket_name) DO NOTHING;

-- Grant client_knowledge user full access to new tables
GRANT SELECT, INSERT, UPDATE, DELETE ON document_intake   TO client_knowledge;
GRANT SELECT, INSERT, UPDATE, DELETE ON invoices          TO client_knowledge;
GRANT SELECT, INSERT, UPDATE, DELETE ON contracts         TO client_knowledge;
GRANT SELECT, INSERT, UPDATE, DELETE ON intake_forms      TO client_knowledge;
GRANT SELECT, INSERT, UPDATE, DELETE ON bucket_company_map TO client_knowledge;
