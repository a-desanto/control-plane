#!/bin/sh
# Nightly pg_dump for all VPS Postgres instances → AWS S3 (cfpa-backups)
# Retention: 7 daily, 4 weekly (Sunday), 3 monthly (1st of month)

DATE=$(date -u +%Y-%m-%d)
DOW=$(date -u +%u)   # 1=Mon … 7=Sun
DOM=$(date -u +%d)   # day of month, zero-padded
TMPDIR=/tmp/backups-${DATE}
FAILURES=0

mkdir -p "$TMPDIR"

log() { printf '[%s] %s\n' "$(date -u +%T)" "$*"; }

dump_pg() {
  name=$1 host=$2 port=$3 user=$4 password=$5 db=$6
  outfile="${TMPDIR}/${name}.pgdump"
  log "Dumping ${name} (${db}@${host}:${port})"
  if PGPASSWORD="$password" pg_dump \
      -h "$host" -p "$port" -U "$user" -d "$db" \
      -Fc --no-password -f "$outfile"; then
    log "  OK — $(du -sh "$outfile" | cut -f1)"
  else
    log "  FAILED — ${name} skipped"
    FAILURES=$((FAILURES + 1))
    rm -f "$outfile"
  fi
}

# ── Dumps ──────────────────────────────────────────────────────────────────────
# host aliases are stable Docker network aliases on the 'coolify' network.
# Three Postgres containers (odoo-r147, odoo-qa3, gwsw) live on isolated service
# networks; run the one-time 'docker network connect' steps in RUNBOOK §6 first.

dump_pg paperclip  paperclip                             54329 paperclip          "$PAPERCLIP_PG_PASSWORD"  paperclip
dump_pg corepg     pf655ouyonydt5llalyj02za              5432  postgres           "$COREPG_PG_PASSWORD"     postgres
dump_pg openclaw   xcn2es4vmn01a1ug0w99vdr3              5432  postgres           "$OPENCLAW_PG_PASSWORD"   openclaw
dump_pg coolify-db coolify-db                            5432  coolify            "$COOLIFY_DB_PG_PASSWORD" coolify
dump_pg odoo-j84s  postgresql-j84scc4g0kwkwwso4kgo4kok  5432  QINhi5ejukBLK7mI  "$ODOO_J84S_PG_PASSWORD"  caring-first-pa
dump_pg odoo-r147  postgresql-r147p2dhkmafaco58b5boxwo   5432  Z23mOdh0KnnVC5rK  "$ODOO_R147_PG_PASSWORD"  caring-first-pa
dump_pg odoo-qa3   postgresql-qa3ernlh747z79f6o5wpmoem   5432  f6LwgPPVs0VQc4Xu  "$ODOO_QA3_PG_PASSWORD"   SekuirTek
dump_pg gwsw       postgresql-gwsw0wcc0co44088swwgkooc   5432  KRLjOZeKr92H8trV  "$GWSW_PG_PASSWORD"       n8n_db

# ── Upload ─────────────────────────────────────────────────────────────────────
log "Uploading to s3:${S3_BUCKET}/daily/${DATE}/"
rclone copy "$TMPDIR/" "s3:${S3_BUCKET}/daily/${DATE}/"

if [ "$DOW" = "7" ]; then
  log "Uploading weekly snapshot (Sunday)"
  rclone copy "$TMPDIR/" "s3:${S3_BUCKET}/weekly/${DATE}/"
fi

if [ "$DOM" = "01" ]; then
  log "Uploading monthly snapshot (1st of month)"
  rclone copy "$TMPDIR/" "s3:${S3_BUCKET}/monthly/${DATE}/"
fi

# ── Retention ─────────────────────────────────────────────────────────────────
# --min-age deletes objects older than N days; keep 7 daily, 4 weekly, 3 monthly
log "Pruning old backups"
rclone delete "s3:${S3_BUCKET}/daily/"   --min-age 8d
rclone delete "s3:${S3_BUCKET}/weekly/"  --min-age 29d
rclone delete "s3:${S3_BUCKET}/monthly/" --min-age 91d

# ── Cleanup ────────────────────────────────────────────────────────────────────
rm -rf "$TMPDIR"

# ── Healthcheck ───────────────────────────────────────────────────────────────
if [ -n "${HEALTHCHECK_PING_URL:-}" ]; then
  curl -fsS --retry 3 "${HEALTHCHECK_PING_URL}?fail_count=${FAILURES}" > /dev/null
  log "Healthcheck pinged (failures=${FAILURES})"
fi

log "Done — ${FAILURES} failure(s)"
