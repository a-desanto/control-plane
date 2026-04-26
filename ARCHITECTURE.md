# Deterministic Agent Control Plane Architecture

## Status
CANONICAL — v3.2

This document is the governing architecture for this system.
All services, agents, tools, and workflows MUST conform to it.

---

## Core Invariants

1. api-gateway is the ONLY external ingress.
2. n8n handles automation and integrations.
3. paperclipai is the ONLY AI decision service.
4. All AI calls go through POST /intent.
5. Execution never makes decisions.
6. Adaptation is always a new decision.
7. Agents never coordinate directly.
8. All tools are MCP servers.
9. All execution is governed by explicit contracts.
10. State is owned by paperclipai.
11. Coolify is the ONLY deployment mechanism.

---

## Final Rule

paperclipai decides.
MCP tools execute.
n8n automates.
api-gateway guards.
Postgres remembers.
Coolify deploys.
