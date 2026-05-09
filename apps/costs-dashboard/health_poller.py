"""Phase 9.1 Stage 3: per-client health snapshot poller.

Two ways to invoke:
1. CLI:  `python health_poller.py` — runs once, polls all active clients, exits.
   Run from host crontab every 5 min:
     */5 * * * * docker exec costs-dashboard python /app/health_poller.py >> /var/log/costs-poller.log 2>&1
2. HTTP: `curl -H "X-Internal-Token: $TOKEN" https://costs.cfpa.sekuirtek.com/_internal/poll-health`
   Triggered by host crontab/systemd.timer if you don't want docker exec.

Outputs go to `client_health_snapshots` and (on degradation) Discord webhook.

Health checks per client:
- DNS: `dig` lookup for the 4 expected records (MX + 3 DKIM CNAMEs from client_configs)
- SES: boto3 `GetIdentityVerificationAttributes` + `GetIdentityDkimAttributes`
- Containers: docker socket if mounted, else returns null and dashboard renders "?"
- Backup: most recent successful backup record (where it lives is TBD per ops — defaults to checking
  cfpa-backup-runner container health if docker socket is available)

If `boto3` is not installed (it's not in costs-dashboard's deps yet), SES check is skipped.
If docker socket isn't mounted, container/backup checks are skipped.
The poller always succeeds even if some checks are unavailable — it just records `null` for those.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any
from urllib import request as _urllib_req
from urllib.error import URLError

import asyncpg


DB_URL = os.environ.get(
    "PAPERCLIP_DB_URL",
    "postgresql://paperclip:paperclip@paperclip:54329/paperclip",
)
AWS_REGION = os.environ.get("AWS_REGION", "us-east-2")
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")
DOCKER_SOCKET = "/var/run/docker.sock"

DIG_TIMEOUT_SECONDS = 4

# Containers we expect to see healthy on the client's VPS. Adjust as the canonical
# stack evolves; for now this matches the runbook's canonical container list.
CANONICAL_CONTAINERS = [
    "paperclip",
    "bedrock-proxy",
    "openclaw-pgvector-db",
    "paddleocr-service",
    "document-processor",
    "document-intake-webhook",
    "cfpa-watchdog",
    "cfpa-backup-runner",
]


# ── DNS check (subprocess dig — no extra deps) ─────────────────────────────

def _dig_lookup(host: str, record_type: str = "A") -> list[str]:
    """Returns the rdata strings for a DNS lookup, or [] on failure."""
    if not shutil.which("dig"):
        return []
    try:
        result = subprocess.run(
            ["dig", "+short", "+time=" + str(DIG_TIMEOUT_SECONDS), record_type, host],
            capture_output=True, text=True, timeout=DIG_TIMEOUT_SECONDS + 2,
        )
        if result.returncode != 0:
            return []
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]
    except (subprocess.TimeoutExpired, OSError):
        return []


def check_dns(slug: str | None, dkim_cnames: list[dict] | None, mx_record: dict | None) -> dict:
    """Returns {ok: bool, mx: {expected, actual, match}, dkim: [...]}."""
    if not slug:
        return {"ok": False, "reason": "no slug configured"}

    out: dict[str, Any] = {"records": []}
    all_ok = True

    if mx_record:
        host = f"{mx_record['host']}.sekuirtek.com" if not mx_record["host"].endswith("sekuirtek.com") else mx_record["host"]
        expected = mx_record["value"]
        actual = _dig_lookup(host, "MX")
        match = any(expected in a for a in actual)
        out["records"].append({"type": "MX", "host": host, "expected": expected, "actual": actual, "match": match})
        if not match:
            all_ok = False
    else:
        all_ok = False

    if dkim_cnames:
        for r in dkim_cnames:
            host = r["name"]
            expected = r["value"]
            actual = _dig_lookup(host, "CNAME")
            match = any(expected.rstrip(".") in a.rstrip(".") for a in actual)
            out["records"].append({"type": "CNAME", "host": host, "expected": expected, "actual": actual, "match": match})
            if not match:
                all_ok = False
    else:
        all_ok = False

    out["ok"] = all_ok
    return out


# ── SES check (boto3 if available) ─────────────────────────────────────────

def check_ses(slug: str | None) -> dict:
    if not slug:
        return {"ok": False, "reason": "no slug configured"}
    try:
        import boto3  # type: ignore
    except ImportError:
        return {"ok": None, "reason": "boto3 not installed"}

    domain = f"{slug}.sekuirtek.com"
    client = boto3.client("ses", region_name=AWS_REGION)
    try:
        v = client.get_identity_verification_attributes(Identities=[domain])
        attr = v["VerificationAttributes"].get(domain, {})
        verified = attr.get("VerificationStatus") == "Success"

        d = client.get_identity_dkim_attributes(Identities=[domain])
        dkim = d["DkimAttributes"].get(domain, {})
        dkim_verified = dkim.get("DkimVerificationStatus") == "Success"

        return {
            "ok": verified and dkim_verified,
            "domain": domain,
            "verification_status": attr.get("VerificationStatus"),
            "dkim_status": dkim.get("DkimVerificationStatus"),
            "dkim_tokens": dkim.get("DkimTokens", []),
        }
    except Exception as e:  # boto3 ClientError or network
        return {"ok": False, "error": str(e)}


# ── Container health (via docker socket if mounted) ───────────────────────

def check_containers() -> dict:
    if not os.path.exists(DOCKER_SOCKET):
        return {"ok": None, "reason": "no docker socket mounted"}
    if not shutil.which("docker"):
        return {"ok": None, "reason": "no docker CLI in container"}

    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}\t{{.Status}}"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return {"ok": False, "error": result.stderr.strip()}
    except (subprocess.TimeoutExpired, OSError) as e:
        return {"ok": False, "error": str(e)}

    statuses: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if "\t" not in line:
            continue
        name, status = line.split("\t", 1)
        statuses[name] = status

    container_results = []
    all_ok = True
    for canonical in CANONICAL_CONTAINERS:
        # Match either exact name or any container name containing the canonical name as a prefix
        # (Coolify-managed containers have UUID-prefix names but reachable via network alias, not container name)
        matched_status = statuses.get(canonical)
        if not matched_status:
            for n, s in statuses.items():
                if canonical in n.lower():
                    matched_status = s
                    break
        is_up = matched_status is not None and matched_status.startswith("Up")
        container_results.append({"name": canonical, "status": matched_status or "missing", "up": is_up})
        if not is_up:
            all_ok = False

    return {"ok": all_ok, "containers": container_results, "running_count": len(statuses)}


def check_backup() -> dict:
    """Backup health = cfpa-backup-runner is up. Refine when a backup-jobs table exists."""
    c = check_containers()
    if c.get("ok") is None:
        return {"ok": None, "reason": c.get("reason")}
    runner = next((x for x in c.get("containers", []) if x["name"] == "cfpa-backup-runner"), None)
    return {"ok": bool(runner and runner["up"]), "runner": runner}


# ── Discord alert ──────────────────────────────────────────────────────────

def post_discord_alert(message: str) -> None:
    if not DISCORD_WEBHOOK:
        return
    try:
        body = json.dumps({"content": message[:1900]}).encode("utf-8")
        req = _urllib_req.Request(DISCORD_WEBHOOK, data=body, headers={"Content-Type": "application/json"})
        _urllib_req.urlopen(req, timeout=5).read()
    except (URLError, OSError):
        pass  # alerting is best-effort


# ── Per-client poll + persist ──────────────────────────────────────────────

async def poll_one_client(conn: asyncpg.Connection, client: dict) -> dict:
    cid = client["company_id"]
    slug = client["slug"]
    dkim = client["dns_dkim_cnames"]
    mx = client["dns_mx_record"]

    # Run blocking checks in threads so we don't stall the asyncio loop
    loop = asyncio.get_running_loop()
    dns_task = loop.run_in_executor(None, check_dns, slug, dkim, mx)
    ses_task = loop.run_in_executor(None, check_ses, slug)
    ctr_task = loop.run_in_executor(None, check_containers)
    bak_task = loop.run_in_executor(None, check_backup)
    dns_r, ses_r, ctr_r, bak_r = await asyncio.gather(dns_task, ses_task, ctr_task, bak_task)

    snap = {
        "dns": dns_r,
        "ses": ses_r,
        "containers": ctr_r,
        "backup": bak_r,
    }

    # Persist
    await conn.execute("""
        INSERT INTO client_health_snapshots
          (client_uuid, dns_ok, ses_verified, containers_ok, backup_ok, snapshot_data)
        VALUES ($1::uuid, $2, $3, $4, $5, $6::jsonb)
    """,
        cid,
        dns_r.get("ok"),
        ses_r.get("ok"),
        ctr_r.get("ok"),
        bak_r.get("ok"),
        json.dumps(snap),
    )

    # Compare with previous snapshot to fire degradation alerts
    prev = await conn.fetchrow("""
        SELECT dns_ok, ses_verified, containers_ok, backup_ok
        FROM client_health_snapshots
        WHERE client_uuid = $1::uuid
        ORDER BY created_at DESC
        OFFSET 1 LIMIT 1
    """, cid)

    if prev:
        regressions = []
        for label, current, previous in (
            ("DNS", dns_r.get("ok"), prev["dns_ok"]),
            ("SES", ses_r.get("ok"), prev["ses_verified"]),
            ("Containers", ctr_r.get("ok"), prev["containers_ok"]),
            ("Backup", bak_r.get("ok"), prev["backup_ok"]),
        ):
            if previous is True and current is not True:
                regressions.append(label)
        if regressions:
            post_discord_alert(
                f"⚠️ Health regression for {client['name']} ({slug}): "
                f"{', '.join(regressions)} dropped. "
                f"https://costs.cfpa.sekuirtek.com/client/{cid}"
            )

    return snap


async def poll_all() -> int:
    conn = await asyncpg.connect(DB_URL)
    try:
        clients = await conn.fetch("""
            SELECT
                cc.company_id::text     AS company_id,
                COALESCE(c.name, '?')   AS name,
                cc.slug,
                cc.dns_dkim_cnames,
                cc.dns_mx_record
            FROM client_configs cc
            LEFT JOIN companies c ON c.id = cc.company_id
            WHERE cc.onboarding_status = 'active'
            ORDER BY cc.created_at
        """)
        results: list[dict] = []
        for c in clients:
            d = dict(c)
            # asyncpg returns JSONB as str depending on codec; normalize
            for k in ("dns_dkim_cnames", "dns_mx_record"):
                v = d.get(k)
                if isinstance(v, str):
                    try:
                        d[k] = json.loads(v)
                    except (json.JSONDecodeError, TypeError):
                        d[k] = None
            results.append(await poll_one_client(conn, d))
        return len(results)
    finally:
        await conn.close()


def main() -> None:
    started = datetime.now(timezone.utc)
    n = asyncio.run(poll_all())
    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    print(json.dumps({
        "event": "poll.complete",
        "clients_polled": n,
        "elapsed_seconds": round(elapsed, 2),
        "timestamp": started.isoformat(),
    }))


if __name__ == "__main__":
    main()
