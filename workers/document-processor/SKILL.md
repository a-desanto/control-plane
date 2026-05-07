# document_workflow

Gives you read-only visibility into Caring First's document intake pipeline and
lets you query, interpret, and report on processed documents.

## What this is

Documents land in S3 (or via email) → document-intake-webhook creates a
`document_intake` row → document-processor picks it up, runs OCR, classifies,
and populates `invoices`, `contracts`, or `intake_forms`.

## Status lifecycle

```
received → ocr_pending → ocr_done → classified → done
                                                 ↘ failed
```

| Status | Meaning |
|---|---|
| received | Landed, waiting for processor to pick up |
| ocr_pending | Processor claimed it, OCR in flight |
| ocr_done | OCR complete, classification next |
| classified | doc_type set, extraction in flight |
| done | Fully extracted; check invoices/contracts/intake_forms |
| failed | Error stored in metadata.error |

## How to query (use the client-knowledge MCP tool)

### Recent intake

```sql
SELECT id, source_type, source_uri, status, doc_type, created_at
FROM document_intake
WHERE company_id = 'bd80728d-6755-4b63-a9b9-c0e24526c820'
ORDER BY created_at DESC
LIMIT 20;
```

### Count by status (pipeline health)

```sql
SELECT status, COUNT(*) AS n
FROM document_intake
WHERE company_id = 'bd80728d-6755-4b63-a9b9-c0e24526c820'
GROUP BY status ORDER BY n DESC;
```

### Failed documents with error details

```sql
SELECT id, source_uri, metadata->>'error' AS error, created_at
FROM document_intake
WHERE company_id = 'bd80728d-6755-4b63-a9b9-c0e24526c820'
  AND status = 'failed'
ORDER BY created_at DESC;
```

### Extracted invoices

```sql
SELECT di.source_uri, i.vendor_name, i.invoice_number,
       i.invoice_date, i.total_amount, i.currency
FROM invoices i
JOIN document_intake di ON di.id = i.document_intake_id
WHERE i.company_id = 'bd80728d-6755-4b63-a9b9-c0e24526c820'
ORDER BY i.created_at DESC LIMIT 10;
```

### Extracted intake forms (HIPAA — patient names only for authorized use)

```sql
SELECT di.source_uri, f.form_type, f.patient_name, f.date_of_service
FROM intake_forms f
JOIN document_intake di ON di.id = f.document_intake_id
WHERE f.company_id = 'bd80728d-6755-4b63-a9b9-c0e24526c820'
ORDER BY f.created_at DESC LIMIT 10;
```

## OCR routing rules (for audit questions)

- **Standard tier**: PaddleOCR primary; Textract fallback if mean_confidence < 0.80
- **HIPAA tier + intake_form**: always Textract (no PaddleOCR, PHI sensitivity)
- **HIPAA tier + other**: Textract fallback if mean_confidence < 0.85

The `metadata` column on each `document_intake` row records which path was taken
(`ocr_source: "paddleocr" | "textract"`) and the confidence score.

## How to request reprocessing of a failed document

To requeue a failed row for reprocessing:

```sql
UPDATE document_intake
SET status = 'received', metadata = NULL, doc_type = NULL, updated_at = NOW()
WHERE id = '<uuid>';
```

The processor will pick it up on the next poll cycle.

## Company context

- **Company**: Caring First (`bd80728d-6755-4b63-a9b9-c0e24526c820`)
- **Tier**: standard (check `client_configs.tier` for current value)
- **Intake email**: `intake@cfpa.sekuirtek.com`
- **S3 bucket**: `cfpa-doc-intake-bd80728d`
