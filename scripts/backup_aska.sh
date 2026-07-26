#!/usr/bin/env bash
# Backup Postgres + Chroma/documents/attachments from Compose full profile.
# Optional encryption: set ASKA_BACKUP_PASSPHRASE (or deploy/BACKUP_PASSPHRASE.txt).
#
# Usage (from repo root):
#   ./scripts/backup_aska.sh
# Cron example:
#   30 2 * * * /opt/ASKa-piyu/scripts/backup_aska.sh >> /var/log/aska-backup.log 2>&1

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/deploy/backups/$STAMP"
mkdir -p "$OUT"

PASS_FILE="$ROOT/deploy/BACKUP_PASSPHRASE.txt"
if [[ -z "${ASKA_BACKUP_PASSPHRASE:-}" && -f "$PASS_FILE" ]]; then
  # First non-comment, non-empty line.
  ASKA_BACKUP_PASSPHRASE="$(grep -v '^[[:space:]]*#' "$PASS_FILE" | sed '/^[[:space:]]*$/d' | head -n1 | tr -d '\r')"
  export ASKA_BACKUP_PASSPHRASE
fi

echo "Backing up Postgres to $OUT/aska_piyu.dump"
docker compose --profile full exec -T postgres \
  pg_dump -U postgres -d aska_piyu -Fc > "$OUT/aska_piyu.dump"

echo "Backing up /data volumes to $OUT/data_volumes.tgz"
docker compose --profile full exec -T api \
  tar -C /data -czf - chroma documents ticket_attachments \
  > "$OUT/data_volumes.tgz"

if [[ -n "${ASKA_BACKUP_PASSPHRASE:-}" ]]; then
  if ! command -v openssl >/dev/null 2>&1; then
    echo "ERROR: ASKA_BACKUP_PASSPHRASE is set but openssl is not installed." >&2
    exit 1
  fi
  echo "Encrypting backup archive (AES-256-CBC + PBKDF2)..."
  tar -C "$OUT" -czf "$OUT/aska_backup_bundle.tgz" aska_piyu.dump data_volumes.tgz
  openssl enc -aes-256-cbc -pbkdf2 -salt \
    -pass env:ASKA_BACKUP_PASSPHRASE \
    -in "$OUT/aska_backup_bundle.tgz" \
    -out "$OUT/aska_backup_bundle.tgz.enc"
  rm -f "$OUT/aska_backup_bundle.tgz" "$OUT/aska_piyu.dump" "$OUT/data_volumes.tgz"
  echo
  echo "Backup OK (encrypted): $OUT/aska_backup_bundle.tgz.enc"
  echo "Decrypt: openssl enc -d -aes-256-cbc -pbkdf2 -pass env:ASKA_BACKUP_PASSPHRASE -in aska_backup_bundle.tgz.enc -out aska_backup_bundle.tgz"
else
  echo
  echo "Backup OK (PLAINTEXT): $OUT"
  echo "WARNING: Set ASKA_BACKUP_PASSPHRASE or create deploy/BACKUP_PASSPHRASE.txt to encrypt."
fi

echo "Copy this folder off the server."
