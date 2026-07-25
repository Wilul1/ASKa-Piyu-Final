#!/usr/bin/env bash
# Backup Postgres + Chroma/documents/attachments from Compose full profile.
# Usage (from repo root, or via absolute path):
#   ./scripts/backup_aska.sh
# Cron example:
#   30 2 * * * /opt/ASKa-piyu/scripts/backup_aska.sh >> /var/log/aska-backup.log 2>&1

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/deploy/backups/$STAMP"
mkdir -p "$OUT"

echo "Backing up Postgres to $OUT/aska_piyu.dump"
docker compose --profile full exec -T postgres \
  pg_dump -U postgres -d aska_piyu -Fc > "$OUT/aska_piyu.dump"

echo "Backing up /data volumes to $OUT/data_volumes.tgz"
docker compose --profile full exec -T api \
  tar -C /data -czf - chroma documents ticket_attachments \
  > "$OUT/data_volumes.tgz"

echo
echo "Backup OK: $OUT"
echo "Copy this folder off the server."
