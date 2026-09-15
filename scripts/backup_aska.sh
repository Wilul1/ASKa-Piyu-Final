#!/usr/bin/env bash
# Backup Postgres + Chroma/documents/attachments/kb_media from Compose full profile.
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
if ! docker compose --profile full exec -T postgres \
  pg_dump -U postgres -d aska_piyu -Fc > "$OUT/aska_piyu.dump"; then
  echo "ERROR: pg_dump failed. Is 'docker compose --profile full' running?" >&2
  exit 1
fi

echo "Confirming kb_media volume is mounted on the api container..."
if ! docker compose --profile full exec -T api test -d /data/kb_media; then
  echo "ERROR: /data/kb_media does not exist on the api container. Aborting backup" \
       "rather than silently skipping article/KB media files." >&2
  exit 1
fi

echo "Backing up /data volumes (chroma, documents, ticket_attachments, kb_media) to $OUT/data_volumes.tgz"
if ! docker compose --profile full exec -T api \
  tar -C /data -czf - chroma documents ticket_attachments kb_media \
  > "$OUT/data_volumes.tgz"; then
  echo "ERROR: data volume tar failed." >&2
  exit 1
fi

echo "Verifying kb_media is actually present in the archive..."
if ! tar -tzf "$OUT/data_volumes.tgz" >/dev/null; then
  echo "ERROR: $OUT/data_volumes.tgz is not a readable/valid tar archive." >&2
  exit 1
fi

# Empty kb_media is valid, but the directory itself must still be in the archive.
# Read the full listing with awk (do not use grep -q here): under pipefail,
# grep -q exits at the first match and tar then SIGPIPEs, which looks like
# "kb_media missing" even when the archive is complete.
if ! tar -tzf "$OUT/data_volumes.tgz" | awk '
  $0 == "kb_media" || $0 == "kb_media/" || index($0, "kb_media/") == 1 { found = 1 }
  END { exit found ? 0 : 1 }
'; then
  echo "ERROR: $OUT/data_volumes.tgz does not contain kb_media. Refusing to report success." >&2
  echo "KB_MEDIA_BACKUP_OK=NO" >&2
  exit 1
fi

KB_MEDIA_SOURCE_COUNT="$(
  docker compose --profile full exec -T api \
    sh -c 'cd /data/kb_media && find . -type f | wc -l' | tr -dc '0-9'
)"
KB_MEDIA_SOURCE_COUNT="${KB_MEDIA_SOURCE_COUNT:-0}"
KB_MEDIA_ARCHIVE_COUNT="$(
  tar -tzf "$OUT/data_volumes.tgz" \
    | { grep '^kb_media/' || true; } \
    | { grep -v '/$' || true; } \
    | wc -l \
    | tr -dc '0-9'
)"
KB_MEDIA_ARCHIVE_COUNT="${KB_MEDIA_ARCHIVE_COUNT:-0}"

if [[ "$KB_MEDIA_SOURCE_COUNT" != "$KB_MEDIA_ARCHIVE_COUNT" ]]; then
  echo "ERROR: kb_media backup verification failed:" \
       "source has $KB_MEDIA_SOURCE_COUNT file(s)," \
       "archive has $KB_MEDIA_ARCHIVE_COUNT file(s). Refusing to report success." >&2
  echo "KB_MEDIA_BACKUP_OK=NO" >&2
  exit 1
fi
# An empty kb_media volume (0 files) is fine as long as source and archive agree.
echo "kb_media verification OK: $KB_MEDIA_SOURCE_COUNT file(s) present in both source and archive."

if [[ -n "${ASKA_BACKUP_PASSPHRASE:-}" ]]; then
  if ! command -v openssl >/dev/null 2>&1; then
    echo "ERROR: ASKA_BACKUP_PASSPHRASE is set but openssl is not installed." >&2
    exit 1
  fi
  echo "Encrypting backup archive (AES-256-CBC + PBKDF2)..."
  if ! tar -C "$OUT" -czf "$OUT/aska_backup_bundle.tgz" aska_piyu.dump data_volumes.tgz; then
    echo "ERROR: failed to create backup bundle tar." >&2
    exit 1
  fi
  if ! openssl enc -aes-256-cbc -pbkdf2 -salt \
    -pass env:ASKA_BACKUP_PASSPHRASE \
    -in "$OUT/aska_backup_bundle.tgz" \
    -out "$OUT/aska_backup_bundle.tgz.enc"; then
    echo "ERROR: openssl encryption failed." >&2
    exit 1
  fi
  rm -f "$OUT/aska_backup_bundle.tgz" "$OUT/aska_piyu.dump" "$OUT/data_volumes.tgz"
  FINAL_ARCHIVE="$OUT/aska_backup_bundle.tgz.enc"
  echo
  echo "Backup OK (encrypted): $FINAL_ARCHIVE"
  echo "Decrypt: openssl enc -d -aes-256-cbc -pbkdf2 -pass env:ASKA_BACKUP_PASSPHRASE -in aska_backup_bundle.tgz.enc -out aska_backup_bundle.tgz"
else
  FINAL_ARCHIVE="$OUT/data_volumes.tgz"
  echo
  echo "Backup OK (PLAINTEXT): $OUT"
  echo "WARNING: Set ASKA_BACKUP_PASSPHRASE or create deploy/BACKUP_PASSPHRASE.txt to encrypt."
fi

echo "KB_MEDIA_FILES=$KB_MEDIA_SOURCE_COUNT"
echo "KB_MEDIA_BACKUP=$FINAL_ARCHIVE"
echo "KB_MEDIA_BACKUP_OK=YES"
echo "Copy this folder off the server."
