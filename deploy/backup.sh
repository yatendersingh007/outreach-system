#!/usr/bin/env bash
# Nightly Postgres backup for the outreach DB with 14-day rotation.
#
# Install (as root):
#   cp deploy/backup.sh /opt/outreach-system/deploy/backup.sh
#   chmod +x /opt/outreach-system/deploy/backup.sh
#   mkdir -p /opt/backups && chown outreach:outreach /opt/backups
#   # add the cron line (see bottom) to the outreach user's crontab:
#   crontab -u outreach -e
#
set -euo pipefail

BACKUP_DIR="/opt/backups"
DB_NAME="${DB_NAME:-outreach}"
DB_USER="${DB_USER:-postgres}"
RETENTION_DAYS=14
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="${BACKUP_DIR}/outreach_${STAMP}.sql.gz"

mkdir -p "${BACKUP_DIR}"

# pg_dump the whole database, gzip it. PGPASSWORD or ~/.pgpass provides auth.
pg_dump -U "${DB_USER}" -d "${DB_NAME}" --no-owner --no-privileges | gzip > "${OUT}"
echo "wrote ${OUT}"

# Rotate: delete backups older than RETENTION_DAYS.
find "${BACKUP_DIR}" -name 'outreach_*.sql.gz' -type f -mtime "+${RETENTION_DAYS}" -delete
echo "rotated: kept last ${RETENTION_DAYS} days"

# ---------------------------------------------------------------------------
# Crontab line (runs 02:30 nightly). Add via `crontab -u outreach -e`:
#   30 2 * * * PGPASSWORD='...' DB_NAME=outreach DB_USER=postgres /opt/outreach-system/deploy/backup.sh >> /opt/backups/backup.log 2>&1
# ---------------------------------------------------------------------------
