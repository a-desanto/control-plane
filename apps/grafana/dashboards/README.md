# Grafana dashboards

| File | Status |
|---|---|
| fleet-overview.json | ✅ — 5 panels: client count, MTD spend, 24h docs, per-client table, cost timeseries |
| per-client-drilldown.json | ✅ — 8 panels with `$company_id` template variable: MTD/agents/24h docs/approvals stats, cost-by-agent, hourly spend, activity, document intake |
| operations.json | ✅ — 9 panels: onboarding status pie, tier pie, pending approvals, failed onboardings, latest health snapshots, operator actions, CPU/RAM/disk timeseries (the last 3 require node-exporter scraping — empty until Phase 5.5 fully deploys) |

These provision automatically on Grafana startup via `provisioning/dashboards/dashboards.yaml` → `/var/lib/grafana/dashboards`. Edit them in the Grafana UI and re-export to JSON to commit changes.

## Authoring tips

- Hand-writing dashboard JSON is painful. Build in Grafana UI → Settings → JSON Model → copy → save here.
- Use the existing `paperclip` datasource for SQL panels, `Prometheus` for system metrics, `Loki` for logs.
- For per-client variables, define `$company_id` as a Grafana template variable querying `SELECT id::text AS __value, name AS __text FROM companies ORDER BY name`.
