#!/usr/bin/env python3
"""
openclaw-worker — polls paperclip for issues assigned to this agent,
executes each via OpenClaw's embedded agent (--local), reports results back.
"""
import asyncio
import json
import logging
import os
import shutil
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

# ── Configuration ─────────────────────────────────────────────────────────────

def _normalize_api_url(url: str) -> str:
    url = url.rstrip("/").strip()
    return url if url.endswith("/api") else url + "/api"

API_URL         = _normalize_api_url(os.environ["PAPERCLIP_API_URL"])
API_KEY         = os.environ["PAPERCLIP_API_KEY"]
COMPANY_ID      = os.environ["PAPERCLIP_COMPANY_ID"]
AGENT_ID        = os.environ["PAPERCLIP_AGENT_ID"]
OR_KEY          = os.environ.get("OPENROUTER_API_KEY", "")
ANTHROPIC_BASE  = os.environ.get("ANTHROPIC_BASE_URL", "")
AGENT_PROFILE   = os.environ.get("OPENCLAW_AGENT_PROFILE", "executor")
WORK_BASE       = Path(os.environ.get("WORKING_DIR_BASE", "/workspace"))
TASK_TIMEOUT    = int(os.environ.get("TASK_TIMEOUT_SECONDS", "1800"))
POLL_INTERVAL   = int(os.environ.get("POLL_INTERVAL_SECONDS", "10"))

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Accept": "application/json",
    "Content-Type": "application/json",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
    stream=sys.stdout,
)
log = logging.getLogger("openclaw-worker")

# ── HTTP helpers ───────────────────────────────────────────────────────────────

async def _request(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    body: dict | None = None,
    params: dict | None = None,
) -> dict:
    url = f"{API_URL}{path}"
    last_err: Exception | None = None
    for attempt in range(5):
        try:
            r = await client.request(
                method, url,
                json=body, params=params, headers=HEADERS,
            )
            if r.status_code < 500:
                r.raise_for_status()
                return r.json() if r.content else {}
            last_err = httpx.HTTPStatusError(
                f"HTTP {r.status_code}", request=r.request, response=r
            )
            log.warning("%s %s → %d (attempt %d/5)", method, path, r.status_code, attempt + 1)
        except httpx.RequestError as e:
            last_err = e
            log.warning("%s %s network error: %s (attempt %d/5)", method, path, e, attempt + 1)
        await asyncio.sleep(min(2 ** attempt, 30))
    raise RuntimeError(f"{method} {path} failed after 5 attempts: {last_err}")


async def api_get(client: httpx.AsyncClient, path: str, **params) -> dict | list:
    return await _request(client, "GET", path, params={k: v for k, v in params.items() if v is not None})

async def api_post(client: httpx.AsyncClient, path: str, body: dict) -> dict | list:
    return await _request(client, "POST", path, body=body)

async def api_patch(client: httpx.AsyncClient, path: str, body: dict) -> dict | list:
    return await _request(client, "PATCH", path, body=body)

# ── Issue operations ───────────────────────────────────────────────────────────

async def get_agent(client: httpx.AsyncClient) -> dict:
    return await api_get(client, f"/agents/{AGENT_ID}")

async def list_pending(client: httpx.AsyncClient) -> list[dict]:
    data = await api_get(
        client,
        f"/companies/{COMPANY_ID}/issues",
        status="todo",
        assigneeAgentId=AGENT_ID,
    )
    issues: list[dict] = data if isinstance(data, list) else (
        data.get("issues") or data.get("data") or data.get("items") or []
    )
    return sorted(issues, key=lambda i: i.get("createdAt") or "")

async def checkout_issue(client: httpx.AsyncClient, issue_id: str) -> dict:
    return await api_post(client, f"/issues/{issue_id}/checkout", {
        "agentId": AGENT_ID,
        "expectedStatuses": ["todo"],
    })

async def release_issue(client: httpx.AsyncClient, issue_id: str) -> None:
    try:
        await api_post(client, f"/issues/{issue_id}/release", {})
    except Exception as e:
        log.warning("Failed to release issue %s: %s", issue_id, e)

async def mark_in_progress(client: httpx.AsyncClient, issue_id: str) -> None:
    await api_patch(client, f"/issues/{issue_id}", {
        "status": "in_progress",
        "comment": "claimed by openclaw-worker",
    })

async def mark_done(client: httpx.AsyncClient, issue_id: str, summary: str) -> None:
    await api_patch(client, f"/issues/{issue_id}", {
        "status": "done",
        "comment": summary,
    })

async def mark_blocked(client: httpx.AsyncClient, issue_id: str, reason: str) -> None:
    await api_patch(client, f"/issues/{issue_id}", {
        "status": "blocked",
        "comment": reason,
    })

# ── Execution helpers ──────────────────────────────────────────────────────────

def _build_prompt(issue: dict) -> str:
    title = issue.get("title") or ""
    description = (issue.get("description") or "").strip()
    return f"{title}\n\n{description}".strip() if description else title

def _subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    if OR_KEY:
        env["OPENROUTER_API_KEY"] = OR_KEY
    if ANTHROPIC_BASE:
        env["ANTHROPIC_BASE_URL"] = ANTHROPIC_BASE
    return env

async def run_openclaw(work_dir: Path, prompt: str) -> tuple[int, str, str]:
    cmd = [
        "openclaw", "agent",
        "--agent", AGENT_PROFILE,
        "--message", prompt,
        "--local",
        "--thinking", "high",
        "--json",
    ]
    log.info("openclaw: %s (cwd=%s)", " ".join(cmd[:6] + ["..."]), work_dir)
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(work_dir),
            env=_subprocess_env(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(), timeout=float(TASK_TIMEOUT)
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return 124, "", f"openclaw timed out after {TASK_TIMEOUT}s"
        return (
            proc.returncode or 0,
            stdout_b.decode(errors="replace"),
            stderr_b.decode(errors="replace"),
        )
    except FileNotFoundError:
        return 127, "", "openclaw binary not found in PATH"


def _git_clone(repo_url: str, work_dir: Path) -> None:
    result = subprocess.run(
        ["git", "clone", "--depth=1", repo_url, "."],
        cwd=str(work_dir),
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git clone failed: {result.stderr[:500]}")

def _git_diff(work_dir: Path) -> str:
    try:
        stat = subprocess.run(
            ["git", "diff", "--stat"],
            cwd=str(work_dir), capture_output=True, text=True, timeout=30,
        )
        if stat.returncode != 0 or not stat.stdout.strip():
            # Also check untracked files
            new = subprocess.run(
                ["git", "status", "--short"],
                cwd=str(work_dir), capture_output=True, text=True, timeout=30,
            )
            return new.stdout.strip()[:4000] if new.returncode == 0 else ""
        diff = subprocess.run(
            ["git", "diff", "--unified=3"],
            cwd=str(work_dir), capture_output=True, text=True, timeout=30,
        )
        return diff.stdout[:8000]
    except (subprocess.SubprocessError, FileNotFoundError):
        return ""

def _run_tests(work_dir: Path) -> str | None:
    if (work_dir / "pyproject.toml").exists() or (work_dir / "pytest.ini").exists():
        r = subprocess.run(
            ["python3", "-m", "pytest", "--tb=short", "-q"],
            cwd=str(work_dir), capture_output=True, text=True, timeout=300,
        )
        return f"pytest exit={r.returncode}\n{(r.stdout + r.stderr).strip()[-2000:]}"
    if (work_dir / "package.json").exists():
        r = subprocess.run(
            ["npm", "test", "--if-present"],
            cwd=str(work_dir), capture_output=True, text=True, timeout=300,
        )
        return f"npm test exit={r.returncode}\n{(r.stdout + r.stderr).strip()[-2000:]}"
    return None

def _extract_repo_url(issue: dict) -> str | None:
    if url := issue.get("repoUrl"):
        return url
    ws = issue.get("executionWorkspaceSettings") or {}
    if url := ws.get("repoUrl"):
        return url
    return None

def _build_summary(
    issue_id: str, exit_code: int,
    stdout: str, stderr: str,
    diff: str, test_result: str | None,
) -> str:
    out: dict = {
        "worker": "openclaw-worker",
        "issueId": issue_id,
        "exitCode": exit_code,
        "completedAt": datetime.now(timezone.utc).isoformat(),
    }

    if stdout.strip():
        try:
            parsed = json.loads(stdout.strip())
            if isinstance(parsed, dict):
                out["openclaw"] = {
                    k: parsed[k]
                    for k in ("content", "usage", "model", "meta", "stop_reason")
                    if k in parsed
                }
            else:
                out["openclawOutput"] = stdout.strip()[:2000]
        except json.JSONDecodeError:
            out["openclawOutput"] = stdout.strip()[:2000]

    if stderr.strip():
        out["stderr"] = stderr.strip()[-1000:]
    if diff:
        out["diff"] = diff
    if test_result is not None:
        out["tests"] = test_result

    return "```json\n" + json.dumps(out, indent=2) + "\n```"

# ── Task execution ─────────────────────────────────────────────────────────────

async def process_issue(client: httpx.AsyncClient, issue: dict) -> None:
    issue_id: str = issue["id"]
    title: str = issue.get("title", "")
    work_dir = WORK_BASE / issue_id
    work_dir.mkdir(parents=True, exist_ok=True)

    log.info("issue %s: %s", issue_id, title[:100])

    try:
        # Claim atomically
        try:
            await checkout_issue(client, issue_id)
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (409, 422):
                log.info("issue %s already claimed — skipping", issue_id)
                return
            raise
        await mark_in_progress(client, issue_id)

        # Clone repo if the issue specifies one
        repo_url = _extract_repo_url(issue)
        if repo_url:
            log.info("cloning %s", repo_url)
            _git_clone(repo_url, work_dir)

        # Run OpenClaw
        prompt = _build_prompt(issue)
        exit_code, stdout, stderr = await run_openclaw(work_dir, prompt)
        log.info("openclaw exit=%d for issue %s", exit_code, issue_id)

        diff = _git_diff(work_dir)
        test_result = _run_tests(work_dir)
        summary = _build_summary(issue_id, exit_code, stdout, stderr, diff, test_result)

        if exit_code == 0:
            await mark_done(client, issue_id, summary)
            log.info("issue %s → done", issue_id)
        else:
            await mark_blocked(
                client, issue_id,
                f"openclaw exited {exit_code}\n\n{summary}",
            )
            log.warning("issue %s → blocked (exit=%d)", issue_id, exit_code)

    except asyncio.CancelledError:
        log.info("issue %s cancelled — marking blocked", issue_id)
        async with httpx.AsyncClient(timeout=8.0) as c:
            try:
                await mark_blocked(c, issue_id, "worker restarting")
            except Exception:
                pass
        raise

    except Exception as exc:
        log.exception("error processing issue %s", issue_id)
        try:
            await mark_blocked(client, issue_id, f"worker error: {exc}")
        except Exception:
            log.exception("failed to mark issue %s blocked after error", issue_id)

    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

# ── Main loop ──────────────────────────────────────────────────────────────────

async def main() -> None:
    WORK_BASE.mkdir(parents=True, exist_ok=True)

    shutdown = asyncio.Event()
    work_task: asyncio.Task | None = None

    def on_signal() -> None:
        log.info("shutdown signal — draining after current task")
        shutdown.set()
        if work_task and not work_task.done():
            work_task.cancel()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, on_signal)

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Identity check
        try:
            agent = await get_agent(client)
            log.info("identity: %s (%s)", agent.get("name", "?"), agent.get("id", AGENT_ID))
        except Exception as e:
            log.error("identity check failed: %s — check PAPERCLIP_API_KEY / PAPERCLIP_AGENT_ID", e)
            sys.exit(1)

        log.info(
            "polling company=%s agent=%s interval=%ds timeout=%ds",
            COMPANY_ID, AGENT_ID, POLL_INTERVAL, TASK_TIMEOUT,
        )

        while not shutdown.is_set():
            try:
                issues = await list_pending(client)
            except Exception as e:
                log.error("poll failed: %s — backing off 60s", e)
                try:
                    await asyncio.wait_for(shutdown.wait(), timeout=60)
                except asyncio.TimeoutError:
                    pass
                continue

            if not issues:
                try:
                    await asyncio.wait_for(shutdown.wait(), timeout=float(POLL_INTERVAL))
                except asyncio.TimeoutError:
                    pass
                continue

            work_task = asyncio.create_task(process_issue(client, issues[0]))
            try:
                await work_task
            except asyncio.CancelledError:
                break
            finally:
                work_task = None

    log.info("shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
