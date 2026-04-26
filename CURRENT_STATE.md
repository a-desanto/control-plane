# Current Runtime State (Initial)

This document describes how the architecture maps to the current VPS,
prior to refactoring.

## Live Components

- api-gateway: running from /root/api-gateway
- intent workers: /root/intent-worker, /root/intent_worker.py
- workflow API: /root/workflow-api
- orchestration: mixed legacy (to be migrated to n8n)
- deployment: manual / docker-compose (transitioning to Coolify)

## Notes

- This is a transitional state.
- Architecture in ARCHITECTURE.md is the target.
- Changes proceed incrementally.
