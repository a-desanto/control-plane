# Phase 5.5 — Grafana + Prometheus + Loki (skeleton)

DNS already pre-staged: `grafana.cfpa.sekuirtek.com → 187.77.213.142`. Drop these files at `apps/grafana/` in `a-desanto/control-plane`, then deploy via Coolify (Docker Compose mode).

## What's in this drop

```
docker-compose.yaml      ← Grafana 11.4 + Prometheus 3.0 + Loki 3.3 + node-exporter
prometheus.yml           ← Scrape config: paperclip, paddleocr, bedrock-proxy, node
loki-config.yaml         ← Loki single-node TSDB, 14d retention
```

## Required env vars (set in Coolify)

```
GF_ADMIN_USER       (default: admin)
GF_ADMIN_PASSWORD   (REQUIRED — generate strong, store in secrets manager)
```

## Deploy

1. Copy this dir to `apps/grafana/` in `a-desanto/control-plane`
2. Push
3. In Coolify, create a Docker Compose deploy from `apps/grafana/docker-compose.yaml`
4. Set env vars
5. Set domain on the grafana service to `grafana.cfpa.sekuirtek.com` (Coolify auto-issues TLS)
6. Deploy
7. Login as admin → add Prometheus + Loki as data sources (auto-detected via `/etc/grafana/provisioning/` if you wire it up — not done here)

## What's NOT in this skeleton

- **Three runbook dashboards** (Fleet Overview, Per-Client Drill-Down, Operations) — not yet built. Place dashboard JSONs in `dashboards/` to auto-load.
- **Provisioning datasources** — for auto-add-on-start, drop YAML at `provisioning/datasources/`.
- **Promtail** on each client VPS to ship logs to Loki — not deployed (single-VPS today; add when 2nd VPS onboards).
- **Discord/email alerting** — configure via Grafana UI after deploy.
- **paperclipai/paddleocr/bedrock-proxy /metrics endpoints** — runbook assumes these exist; they may not. Verify before wondering why scrapes fail.
- **node-exporter port 9100** — runs in compose, scraped by prometheus. For per-VPS monitoring across the fleet, deploy node-exporter on each VPS.

## Effort to fully ship per runbook

5-7 days. This skeleton is ~half a day of layout + config; remaining is dashboard authoring + alert wiring + per-VPS rollout (when fleet grows).
