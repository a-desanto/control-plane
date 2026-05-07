#!/usr/bin/env python3
"""
Phase 12 Stage 2 — Create document-agent in paperclipai and install
document_workflow skill for Caring First.

Usage:
    python3 phase12_2_create_document_agent.py

Env vars required:
    PAPERCLIP_API_URL   e.g. https://paperclipai.cfpa.sekuirtek.com/api
    PAPERCLIP_API_KEY   board API key (pcp_board_...)
    COMPANY_ID          bd80728d-6755-4b63-a9b9-c0e24526c820

The script is idempotent — safe to re-run. It skips creation if an agent or
skill with the same name already exists.
"""
import json
import os
import sys
from pathlib import Path

import httpx

API_URL    = os.environ.get("PAPERCLIP_API_URL", "https://paperclipai.cfpa.sekuirtek.com/api").rstrip("/")
API_KEY    = os.environ["PAPERCLIP_API_KEY"]
COMPANY_ID = os.environ.get("COMPANY_ID", "bd80728d-6755-4b63-a9b9-c0e24526c820")

SKILL_MD_PATH = Path(__file__).parent.parent / "workers" / "document-processor" / "SKILL.md"

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}


def api(method: str, path: str, **kwargs) -> dict | list:
    url = f"{API_URL}{path}"
    resp = httpx.request(method, url, headers=HEADERS, timeout=30, **kwargs)
    if resp.status_code not in (200, 201):
        print(f"  ERROR {resp.status_code}: {resp.text[:400]}", file=sys.stderr)
        resp.raise_for_status()
    return resp.json() if resp.content else {}


# ── Step 1: Ensure document-agent exists ─────────────────────────────────────

def ensure_agent() -> str:
    agents = api("GET", f"/companies/{COMPANY_ID}/agents")
    for a in (agents if isinstance(agents, list) else []):
        if a.get("name", "").lower() == "document-agent":
            print(f"  agent already exists: {a['id']}")
            return a["id"]

    print("  creating document-agent...")
    agent = api("POST", f"/companies/{COMPANY_ID}/agents", json={
        "name": "document-agent",
        "role": "general",
        "title": "Document Workflow Agent",
        "adapterType": "claude_local",
        "adapterConfig": {
            "instructionsBundleMode": "managed",
            "dangerouslySkipPermissions": True,
            "maxTurnsPerRun": 200,
            "graceSec": 15,
            "timeoutSec": 0,
        },
        "runtimeConfig": {
            "heartbeat": {
                "enabled": False,
                "wakeOnDemand": True,
                "intervalSec": 300,
                "cooldownSec": 10,
                "maxConcurrentRuns": 1,
            }
        },
    })
    agent_id = agent["id"]
    print(f"  created agent: {agent_id}")
    return agent_id


# ── Step 2: Ensure document_workflow skill exists ─────────────────────────────

def ensure_skill() -> str:
    skills = api("GET", f"/companies/{COMPANY_ID}/skills")
    for s in (skills if isinstance(skills, list) else []):
        if s.get("slug") == "document-workflow" or "document_workflow" in s.get("key", ""):
            print(f"  skill already exists: {s['id']}")
            return s["id"]

    skill_content = SKILL_MD_PATH.read_text()

    print("  installing document_workflow skill...")
    # Try creating an inline skill from the SKILL.md content.
    # sourceType 'inline' lets us supply the markdown directly without needing
    # the file mounted inside the paperclipai container.
    try:
        skill = api("POST", f"/companies/{COMPANY_ID}/skills", json={
            "name": "document_workflow",
            "slug": "document-workflow",
            "description": "Query and manage Caring First document intake pipeline",
            "sourceType": "inline",
            "content": skill_content,
            "trustLevel": "markdown_only",
        })
        skill_id = skill["id"]
        print(f"  created skill (inline): {skill_id}")
        return skill_id
    except httpx.HTTPStatusError as e:
        print(f"  inline sourceType not supported ({e.response.status_code}), trying github...")

    # Fallback: reference the SKILL.md in the repo (if paperclipai supports github sourceType)
    try:
        skill = api("POST", f"/companies/{COMPANY_ID}/skills", json={
            "name": "document_workflow",
            "slug": "document-workflow",
            "description": "Query and manage Caring First document intake pipeline",
            "sourceType": "github",
            "sourceLocator": "https://github.com/youorg/control-plane/blob/main/workers/document-processor/SKILL.md",
            "trustLevel": "markdown_only",
        })
        skill_id = skill["id"]
        print(f"  created skill (github): {skill_id}")
        return skill_id
    except httpx.HTTPStatusError as e2:
        print(f"  github sourceType also failed ({e2.response.status_code})")
        print("  MANUAL STEP: install the skill via the paperclipai UI from:")
        print(f"    {SKILL_MD_PATH}")
        return ""


# ── Step 3: Attach skill to agent ─────────────────────────────────────────────

def attach_skill(agent_id: str, skill_key: str) -> None:
    if not skill_key:
        return
    print(f"  attaching skill {skill_key!r} to agent {agent_id}...")
    # Read current desiredSkills from the agent's skill manifest
    current_skills = []
    try:
        data = api("GET", f"/agents/{agent_id}/skills")
        current_skills = data.get("desiredSkills", []) if isinstance(data, dict) else []
    except Exception:
        pass

    if skill_key in current_skills:
        print("  already attached.")
        return

    current_skills.append(skill_key)
    try:
        api("PATCH", f"/agents/{agent_id}", json={"adapterConfig": {"desiredSkills": current_skills}})
        print(f"  attached. agent now has {len(current_skills)} skills.")
    except httpx.HTTPStatusError as e:
        print(f"  attach failed: {e.response.status_code}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f"\nPaperclipAI: {API_URL}")
    print(f"Company:     {COMPANY_ID}\n")

    print("Step 1: document-agent")
    agent_id = ensure_agent()
    print(f"  agent_id = {agent_id}\n")

    print("Step 2: document_workflow skill")
    skill_id = ensure_skill()
    print(f"  skill_id = {skill_id or '(manual install required)'}\n")

    print("Step 3: attach skill to agent")
    skill_key = f"company/{COMPANY_ID}/document-workflow" if skill_id else ""
    attach_skill(agent_id, skill_key)

    print("\nDone. Update document-processor .env:")
    print(f"  BEDROCK_AGENT_ID={agent_id}")
    print(f"  COMPANY_ID={COMPANY_ID}")
    print()
    print("Then deploy the document-processor container:")
    print("  cd workers/document-processor && docker compose up -d --build")


if __name__ == "__main__":
    main()
