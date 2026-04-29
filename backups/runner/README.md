# backups/runner

Docker container (alpine + rclone + postgresql16-client + dcron) that runs a
nightly `pg_dump` of every Postgres instance on the VPS and uploads to
Cloudflare R2 bucket `cfpa-backups`.

Retention: 7 daily / 4 weekly (Sundays) / 3 monthly (1st of month).

---

## One-time: connect isolated Postgres containers to the coolify network

Three Postgres containers live on isolated service networks and cannot be reached
by the backup runner until you run:

```bash
docker network connect coolify postgresql-r147p2dhkmafaco58b5boxwo
docker network connect coolify postgresql-qa3ernlh747z79f6o5wpmoem
docker network connect coolify postgresql-gwsw0wcc0co44088swwgkooc
```

**Re-run these after any Coolify redeploy of those services** — a redeploy
recreates the container and loses the manual network attachment.

---

## Required environment variables (set in Coolify app)

| Variable | Value |
|---|---|
| `PAPERCLIP_PG_PASSWORD` | paperclip embedded Postgres password |
| `COREPG_PG_PASSWORD` | pf655ouyonydt5llalyj02za postgres password |
| `OPENCLAW_PG_PASSWORD` | xcn2es4vmn01a1ug0w99vdr3 postgres password |
| `COOLIFY_DB_PG_PASSWORD` | coolify-db postgres password |
| `ODOO_J84S_PG_PASSWORD` | postgresql-j84scc4g0kwkwwso4kgo4kok password |
| `ODOO_R147_PG_PASSWORD` | postgresql-r147p2dhkmafaco58b5boxwo password |
| `ODOO_QA3_PG_PASSWORD` | postgresql-qa3ernlh747z79f6o5wpmoem password |
| `GWSW_PG_PASSWORD` | postgresql-gwsw0wcc0co44088swwgkooc password |
| `R2_ACCESS_KEY_ID` | Cloudflare R2 API token access key |
| `R2_SECRET_ACCESS_KEY` | Cloudflare R2 API token secret key |
| `R2_ENDPOINT` | `https://c5950930891e91329375ab367ef7e870.r2.cloudflarestorage.com` |
| `R2_BUCKET` | `cfpa-backups` |
| `HEALTHCHECK_PING_URL` | (optional) healthcheck.io or BetterStack ping URL |

---

## Deploy in Coolify

1. Create a new Resource → Docker → Build from Dockerfile.
2. Set source to this repo, Dockerfile path: `backups/runner/Dockerfile`.
3. Network: add `coolify` to the connected networks.
4. Set all env vars above as Secret.
5. No ports, no volumes, no Traefik.
6. Deploy.

---

## Restore procedure

```bash
# Download a specific dump from R2:
rclone copy r2:cfpa-backups/daily/YYYY-MM-DD/paperclip.pgdump .

# Restore to a throwaway database:
createdb -U postgres restore_test
pg_restore -h <host> -U <user> -d restore_test paperclip.pgdump

# Verify row counts:
psql -h <host> -U <user> -d restore_test -c '\dt+'
```

Dumps use `-Fc` (custom format, internally compressed). Restore requires
`pg_restore`, not `psql`.
