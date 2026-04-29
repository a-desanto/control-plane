"""
cfpa-watchdog — per-agent spend-velocity kill-switch.

Poll paperclip's cost API every POLL_INTERVAL_SECONDS. If any active agent
exceeds a rolling-window threshold, pause it and fire a Discord alert.
"""
import asyncio
import sys
from datetime import datetime, timedelta, timezone

import httpx
import structlog

from .config import (
    PAPERCLIP_API_URL,
    PAPERCLIP_API_KEY,
    PAPERCLIP_COMPANY_ID,
    DISCORD_WEBHOOK_URL,
    HEALTHCHECK_PING_URL,
    POLL_INTERVAL_SECONDS,
    thresholds_for,
)

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer(),
    ]
)
log = structlog.get_logger()

HEADERS = {
    "Authorization": f"Bearer {PAPERCLIP_API_KEY}",
    "Content-Type": "application/json",
}

# Windows the watchdog checks each cycle.
WINDOWS = [
    ("1m",  1),
    ("5m",  5),
    ("60m", 60),
]
WINDOW_ENV_KEY = {
    "1m":  "PER_MINUTE_MAX_USD",
    "5m":  "PER_5MIN_MAX_USD",
    "60m": "PER_HOUR_MAX_USD",
}

# In-memory: agents this process instance has paused. Cleared on restart.
# Maps agent_id → window label that triggered the pause.
_paused_by_watchdog: dict[str, str] = {}


async def fetch_agents(client: httpx.AsyncClient) -> list[dict]:
    """Return all active (non-paused, non-terminated) agents for the company."""
    resp = await client.get(
        f"{PAPERCLIP_API_URL}/api/companies/{PAPERCLIP_COMPANY_ID}/agents",
        headers=HEADERS,
    )
    resp.raise_for_status()
    agents = resp.json()
    return [a for a in agents if a.get("status") not in ("paused", "terminated", "pending_approval")]


async def fetch_cost_by_agent(
    client: httpx.AsyncClient, minutes: int, now: datetime
) -> dict[str, float]:
    """
    Fetch aggregate cost per agent for the last `minutes` minutes.
    Returns {agent_id: cost_usd}.
    """
    since = now - timedelta(minutes=minutes)
    resp = await client.get(
        f"{PAPERCLIP_API_URL}/api/companies/{PAPERCLIP_COMPANY_ID}/costs/by-agent",
        headers=HEADERS,
        params={
            "from": since.isoformat(),
            "to": now.isoformat(),
        },
    )
    resp.raise_for_status()
    rows = resp.json()
    return {
        row["agentId"]: row["costCents"] / 100.0
        for row in rows
        if row.get("agentId")
    }


async def pause_agent(client: httpx.AsyncClient, agent_id: str) -> bool:
    """POST /api/agents/:id/pause. Returns True on success."""
    try:
        resp = await client.post(
            f"{PAPERCLIP_API_URL}/api/agents/{agent_id}/pause",
            headers=HEADERS,
        )
        resp.raise_for_status()
        return True
    except Exception as exc:
        log.error("pause_failed", agent_id=agent_id, error=str(exc))
        return False


async def send_discord_alert(
    client: httpx.AsyncClient,
    agent_id: str,
    agent_name: str,
    window_label: str,
    actual_usd: float,
    threshold_usd: float,
) -> None:
    window_desc = {"1m": "1 minute", "5m": "5 minutes", "60m": "1 hour"}[window_label]
    message = (
        f"🚨 **Agent paused by watchdog**\n"
        f"**Agent:** {agent_name} (`{agent_id}`)\n"
        f"**Threshold breached:** ${threshold_usd:.2f} per {window_desc}\n"
        f"**Actual spend:** ${actual_usd:.4f} in last {window_desc}\n"
        f"**Next step:** Investigate in paperclip, then resume via "
        f"`POST /api/agents/{agent_id}/resume` or the UI."
    )
    try:
        resp = await client.post(
            DISCORD_WEBHOOK_URL,
            json={"content": message},
            timeout=10,
        )
        resp.raise_for_status()
    except Exception as exc:
        # Don't crash — agent is already paused, alert is best-effort.
        log.warning("discord_alert_failed", agent_id=agent_id, error=str(exc))


async def ping_healthcheck(client: httpx.AsyncClient, *, fail: bool = False) -> None:
    if not HEALTHCHECK_PING_URL:
        return
    url = HEALTHCHECK_PING_URL if not fail else f"{HEALTHCHECK_PING_URL}/fail"
    try:
        await client.get(url, timeout=5)
    except Exception as exc:
        log.warning("healthcheck_ping_failed", error=str(exc))


async def poll_cycle(client: httpx.AsyncClient) -> None:
    now = datetime.now(timezone.utc)

    agents = await fetch_agents(client)
    active_ids = {a["id"] for a in agents}

    # Remove any watchdog-paused agents that the user manually resumed.
    stale = [aid for aid in _paused_by_watchdog if aid not in active_ids]
    for aid in stale:
        log.info("agent_manually_resumed", agent_id=aid)
        del _paused_by_watchdog[aid]

    # Fetch cost windows in parallel.
    costs_by_window: dict[str, dict[str, float]] = {}
    window_tasks = {
        label: fetch_cost_by_agent(client, minutes, now)
        for label, minutes in WINDOWS
    }
    for label, coro in window_tasks.items():
        costs_by_window[label] = await coro

    paused_this_cycle: list[str] = []

    for agent in agents:
        agent_id   = agent["id"]
        agent_name = agent.get("name", agent_id)

        if agent_id in _paused_by_watchdog:
            continue  # Already paused by us; don't re-alert

        thresholds = thresholds_for(agent_id)

        for label, _ in WINDOWS:
            env_key       = WINDOW_ENV_KEY[label]
            threshold_usd = thresholds[env_key]
            actual_usd    = costs_by_window[label].get(agent_id, 0.0)

            if actual_usd > threshold_usd:
                log.warning(
                    "threshold_breached",
                    agent_id=agent_id,
                    agent_name=agent_name,
                    window=label,
                    actual_usd=round(actual_usd, 6),
                    threshold_usd=threshold_usd,
                )

                paused_ok = await pause_agent(client, agent_id)
                if paused_ok:
                    _paused_by_watchdog[agent_id] = label
                    paused_this_cycle.append(agent_id)
                    log.warning(
                        "agent_paused",
                        agent_id=agent_id,
                        agent_name=agent_name,
                        window=label,
                        actual_usd=round(actual_usd, 6),
                        threshold_usd=threshold_usd,
                    )
                    await send_discord_alert(
                        client, agent_id, agent_name, label, actual_usd, threshold_usd
                    )
                break  # One pause per agent per cycle; don't multi-alert windows

    log.info(
        "cycle_complete",
        agents_active=len(agents),
        agents_paused_this_cycle=len(paused_this_cycle),
        watchdog_paused_total=len(_paused_by_watchdog),
    )


async def main() -> None:
    log.info(
        "watchdog_starting",
        poll_interval_seconds=POLL_INTERVAL_SECONDS,
        company_id=PAPERCLIP_COMPANY_ID,
    )

    async with httpx.AsyncClient(timeout=30) as client:
        # Startup: scan for already-paused agents to avoid re-pausing them.
        try:
            resp = await client.get(
                f"{PAPERCLIP_API_URL}/api/companies/{PAPERCLIP_COMPANY_ID}/agents",
                headers=HEADERS,
            )
            resp.raise_for_status()
            all_agents = resp.json()
            already_paused = [a["id"] for a in all_agents if a.get("status") == "paused"]
            log.info("startup_scan", agents_total=len(all_agents), already_paused=len(already_paused))
        except Exception as exc:
            log.error("startup_scan_failed", error=str(exc))

        while True:
            try:
                await poll_cycle(client)
                await ping_healthcheck(client)
            except httpx.HTTPStatusError as exc:
                log.error(
                    "cycle_http_error",
                    status=exc.response.status_code,
                    url=str(exc.request.url),
                    error=str(exc),
                )
                await ping_healthcheck(client, fail=True)
            except httpx.RequestError as exc:
                log.error("cycle_request_error", error=str(exc))
                await ping_healthcheck(client, fail=True)
            except Exception as exc:
                log.error("cycle_unexpected_error", error=str(exc), exc_info=True)
                await ping_healthcheck(client, fail=True)

            await asyncio.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
