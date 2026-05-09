-- Phase 9.1 Stage 4: per-add-on configurable settings
-- Run against the paperclipai DB (postgresql://paperclip:paperclip@paperclip:54329/paperclip)
-- Idempotent.

ALTER TABLE operator_client_addons
  ADD COLUMN IF NOT EXISTS settings JSONB NOT NULL DEFAULT '{}'::jsonb;

COMMENT ON COLUMN operator_client_addons.settings IS
  'Per-add-on user-editable configuration. Schema is enforced by the costs-dashboard app per addon_key.';
