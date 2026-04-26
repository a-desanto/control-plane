# Intent Contract (v1)

## Endpoint
POST /intent

## Purpose
Unified entry point for all AI decisions.

Used by:
- n8n workflows
- Client-facing applications

## Required Fields
- intent_id
- source
- requested_outcome
- payload
- idempotency_key

## Response
202 Accepted
- intent_id
- status
- status_url
- events_url (optional)

---
This is the only supported way to invoke AI.
