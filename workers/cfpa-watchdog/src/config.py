import os
import re

# ── Core connection ────────────────────────────────────────────────────────────
PAPERCLIP_API_URL    = os.environ["PAPERCLIP_API_URL"].rstrip("/")
PAPERCLIP_API_KEY    = os.environ["PAPERCLIP_API_KEY"]
PAPERCLIP_COMPANY_ID = os.environ["PAPERCLIP_COMPANY_ID"]
DISCORD_WEBHOOK_URL  = os.environ["DISCORD_WEBHOOK_URL"]
HEALTHCHECK_PING_URL = os.environ.get("HEALTHCHECK_PING_URL", "")

# ── Polling ────────────────────────────────────────────────────────────────────
POLL_INTERVAL_SECONDS = int(os.environ.get("POLL_INTERVAL_SECONDS", "60"))

# ── Default thresholds (USD) ───────────────────────────────────────────────────
# Conservative defaults — tune via env vars once real workload data is available.
DEFAULT_PER_MINUTE_MAX_USD = float(os.environ.get("PER_MINUTE_MAX_USD", "1.00"))
DEFAULT_PER_5MIN_MAX_USD   = float(os.environ.get("PER_5MIN_MAX_USD",   "3.00"))
DEFAULT_PER_HOUR_MAX_USD   = float(os.environ.get("PER_HOUR_MAX_USD",   "8.00"))

# ── Per-agent overrides ────────────────────────────────────────────────────────
# Pattern: WATCHDOG_AGENT_<UUID>_PER_HOUR_MAX_USD=20
# Supported suffixes: PER_MINUTE_MAX_USD, PER_5MIN_MAX_USD, PER_HOUR_MAX_USD
_UUID_RE = re.compile(
    r"^WATCHDOG_AGENT_([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
    r"_(PER_MINUTE_MAX_USD|PER_5MIN_MAX_USD|PER_HOUR_MAX_USD)$",
    re.IGNORECASE,
)

def _load_agent_overrides() -> dict[str, dict[str, float]]:
    overrides: dict[str, dict[str, float]] = {}
    for key, val in os.environ.items():
        m = _UUID_RE.match(key)
        if m:
            agent_id = m.group(1).lower()
            threshold = m.group(2).upper()
            overrides.setdefault(agent_id, {})[threshold] = float(val)
    return overrides

AGENT_OVERRIDES: dict[str, dict[str, float]] = _load_agent_overrides()


def thresholds_for(agent_id: str) -> dict[str, float]:
    """Return effective thresholds for an agent, merging defaults with any overrides."""
    base = {
        "PER_MINUTE_MAX_USD": DEFAULT_PER_MINUTE_MAX_USD,
        "PER_5MIN_MAX_USD":   DEFAULT_PER_5MIN_MAX_USD,
        "PER_HOUR_MAX_USD":   DEFAULT_PER_HOUR_MAX_USD,
    }
    base.update(AGENT_OVERRIDES.get(agent_id.lower(), {}))
    return base
