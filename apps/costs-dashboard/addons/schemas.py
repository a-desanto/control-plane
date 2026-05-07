"""Per-add-on config schemas.

Each schema describes the form fields the operator can edit and the validation/defaults applied
on save. Schema-driven so adding a new add-on means only adding an entry here + an optional
reconfigure() callback.

Field types:
- bool        → checkbox
- text        → single-line text input
- enum        → dropdown (requires `choices`)
- time_of_day → "HH:MM" 24h
- int         → number input (requires `min`/`max`)
"""

from typing import Any


SCHEMAS: dict[str, dict] = {
    "document_workflows": {
        "title": "Document Workflows",
        "fields": [
            {
                "key": "vision_heavy",
                "label": "Vision-heavy mode (+$100/mo)",
                "type": "bool",
                "default": False,
                "help": "Enable for medical/legal clients with high volume of scanned PDFs and image-heavy docs.",
            },
            {
                "key": "ocr_routing",
                "label": "OCR routing strategy",
                "type": "enum",
                "choices": [
                    ("paddleocr_primary", "PaddleOCR primary, Textract fallback (recommended)"),
                    ("textract_only",     "Textract only (HIPAA tier)"),
                    ("paddleocr_only",    "PaddleOCR only (no fallback — testing only)"),
                ],
                "default": "paddleocr_primary",
                "help": "HIPAA-tier clients should use textract_only. Standard tier should use paddleocr_primary.",
            },
            {
                "key": "ocr_confidence_threshold",
                "label": "PaddleOCR confidence threshold for fallback",
                "type": "int",
                "min": 50,
                "max": 99,
                "default": 80,
                "help": "Below this mean confidence (0-99), document-processor falls back to Textract.",
            },
            {
                "key": "daily_digest",
                "label": "Send daily digest email to client owner",
                "type": "bool",
                "default": True,
            },
            {
                "key": "digest_time",
                "label": "Digest delivery time (UTC)",
                "type": "time_of_day",
                "default": "16:00",
                "help": "Time of day (UTC) the daily digest is sent.",
            },
        ],
    },

    "voice": {
        "title": "Voice (Retell)",
        "fields": [
            {
                "key": "provider",
                "label": "Voice provider",
                "type": "enum",
                "choices": [("retell", "Retell")],
                "default": "retell",
            },
            {
                "key": "default_voice_persona",
                "label": "Default voice persona ID",
                "type": "text",
                "default": "",
                "help": "Retell agent ID to use for outbound calls. See Retell dashboard.",
            },
            {
                "key": "business_hours_only",
                "label": "Restrict to business hours",
                "type": "bool",
                "default": True,
            },
        ],
    },

    "marketing_social": {
        "title": "Marketing & Social",
        "fields": [
            {"key": "enabled_channels", "label": "Enabled channels (comma-separated)", "type": "text", "default": "buffer,linkedin"},
        ],
    },

    "sales_outreach": {
        "title": "Sales Outreach",
        "fields": [
            {"key": "daily_send_cap", "label": "Max outreach messages per day", "type": "int", "min": 0, "max": 500, "default": 50},
        ],
    },

    "customer_support": {
        "title": "Customer Support",
        "fields": [
            {"key": "auto_reply", "label": "Auto-reply to incoming tickets", "type": "bool", "default": False},
        ],
    },

    "vertical_extensions": {
        "title": "Vertical Extensions",
        "fields": [
            {"key": "active_vertical", "label": "Active vertical", "type": "enum",
             "choices": [("medical", "Medical"), ("legal", "Legal"), ("accounting", "Accounting"),
                         ("home_services", "Home Services"), ("real_estate", "Real Estate")],
             "default": "medical"},
        ],
    },

    "premium_reasoning": {
        "title": "Premium Reasoning (Opus)",
        "fields": [
            {"key": "model", "label": "Reasoning model", "type": "enum",
             "choices": [("claude-opus-4-7", "Claude Opus 4.7 (1M ctx)"),
                         ("claude-opus-4-6", "Claude Opus 4.6")],
             "default": "claude-opus-4-7"},
        ],
    },

    "custom_workflow": {
        "title": "Custom Workflow",
        "fields": [
            {"key": "engagement_notes", "label": "Engagement notes", "type": "text", "default": ""},
        ],
    },
}


def get_schema(addon_key: str) -> dict | None:
    return SCHEMAS.get(addon_key)


def coerce_field(field: dict, raw: str | list[str] | None) -> Any:
    """Coerce a raw form value into the typed Python value, falling back to default."""
    t = field["type"]
    default = field.get("default")
    if raw is None or raw == "":
        return default
    if isinstance(raw, list):
        raw = raw[0] if raw else None
        if raw is None:
            return default
    if t == "bool":
        return raw in ("on", "true", "1", True)
    if t == "int":
        try:
            v = int(raw)
        except (TypeError, ValueError):
            return default
        if "min" in field and v < field["min"]:
            v = field["min"]
        if "max" in field and v > field["max"]:
            v = field["max"]
        return v
    if t == "enum":
        valid = {c[0] for c in field.get("choices", [])}
        return raw if raw in valid else default
    if t == "time_of_day":
        # Lightweight HH:MM check
        if isinstance(raw, str) and len(raw) == 5 and raw[2] == ":":
            try:
                h, m = int(raw[:2]), int(raw[3:])
                if 0 <= h < 24 and 0 <= m < 60:
                    return raw
            except ValueError:
                pass
        return default
    # text or unknown
    return str(raw)


def coerce_settings(addon_key: str, form: dict[str, Any]) -> dict:
    """Apply schema to a posted form dict; returns the cleaned settings dict to store as JSONB."""
    schema = get_schema(addon_key)
    if not schema:
        return {}
    result: dict[str, Any] = {}
    for field in schema["fields"]:
        # bool checkboxes don't get submitted when unchecked; explicit False default
        if field["type"] == "bool":
            result[field["key"]] = field["key"] in form
        else:
            result[field["key"]] = coerce_field(field, form.get(field["key"]))
    return result


def merge_with_defaults(addon_key: str, stored: dict | None) -> dict:
    """Return current settings filled in with schema defaults where missing."""
    schema = get_schema(addon_key)
    if not schema:
        return stored or {}
    out: dict[str, Any] = {}
    stored = stored or {}
    for field in schema["fields"]:
        out[field["key"]] = stored.get(field["key"], field.get("default"))
    return out
