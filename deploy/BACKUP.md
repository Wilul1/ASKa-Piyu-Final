# Backup and restore (Postgres + Chroma)

ASKa-Piyu keeps **two** stores that must stay consistent:

| Store | Compose volume / path | Contents |
|-------|----------------------|----------|
| PostgreSQL | `aska_pgdata` | users, tickets, published FAQs, auth |
| Chroma | `aska_chroma` | RAG vectors for Ask / chatbot |
| Documents | `aska_documents` | original PDFs for citations |
| Attachments | `aska_attachments` | ticket uploads |

Back up **Postgres + Chroma (+ documents)** together. Restoring Postgres alone without Chroma leaves Ask broken for FAQs; restoring Chroma alone without FAQ rows leaves orphan vectors.

## Encryption (required for campus)

Backups contain full PII. Prefer **encrypted** archives:

1. Create a passphrase (or run `python scripts/harden_lab_ops.py`):

```bat
REM Writes deploy\BACKUP_PASSPHRASE.txt (gitignored)
python scripts\harden_lab_ops.py
```

2. Scripts auto-load `deploy/BACKUP_PASSPHRASE.txt`, or set:

```bat
set ASKA_BACKUP_PASSPHRASE=your-long-random-passphrase
```

Encrypted output: `deploy/backups/<stamp>/aska_backup_bundle.tgz.enc`  
(plaintext dump/tarball files are removed after encryption).

Decrypt:

```bash
export ASKA_BACKUP_PASSPHRASE='…'
openssl enc -d -aes-256-cbc -pbkdf2 \
  -pass env:ASKA_BACKUP_PASSPHRASE \
  -in aska_backup_bundle.tgz.enc \
  -out aska_backup_bundle.tgz
tar -xzf aska_backup_bundle.tgz
```

Store the passphrase **separately** from the encrypted backup (password manager / sealed ICT envelope). Never commit `deploy/BACKUP_PASSPHRASE.txt`.

## Backup (Docker Compose `full` profile)

**Windows:**

```bat
REM From repo root. Creates deploy\backups\<timestamp>\
scripts\backup_aska.bat
```

**Linux VPS:**

```bash
chmod +x scripts/backup_aska.sh
./scripts/backup_aska.sh
```

Or manually (plaintext — encrypt before offsite copy):

```bash
STAMP=$(date +%Y%m%d_%H%M%S)
OUT=deploy/backups/$STAMP
mkdir -p "$OUT"

docker compose --profile full exec -T postgres \
  pg_dump -U postgres -d aska_piyu -Fc > "$OUT/aska_piyu.dump"

docker compose --profile full exec -T api \
  tar -C /data -czf - chroma documents ticket_attachments \
  > "$OUT/data_volumes.tgz"
```

Keep copies **off** the VPS (USB, campus NAS, or object storage). Prefer the encrypted `.tgz.enc` file only.

Suggested cron (Linux):

```cron
30 2 * * * /opt/ASKa-piyu/scripts/backup_aska.sh >> /var/log/aska-backup.log 2>&1
```

## Restore

1. Decrypt the bundle (if encrypted) into a working directory with `aska_piyu.dump` + `data_volumes.tgz`.

2. Stop API/nginx (Postgres can stay up for `pg_restore`):

```bash
docker compose --profile full stop api nginx
```

3. Restore Postgres (destroys current app data in `aska_piyu`):

```bash
docker compose --profile full exec -T postgres \
  pg_restore -U postgres -d aska_piyu --clean --if-exists < deploy/backups/<stamp>/aska_piyu.dump
```

4. Restore data volumes into the API container paths:

```bash
docker compose --profile full run --rm --no-deps \
  -v "$(pwd)/deploy/backups/<stamp>/data_volumes.tgz:/backup.tgz:ro" api \
  sh -c 'rm -rf /data/chroma/* /data/documents/* /data/ticket_attachments/* && tar -C /data -xzf /backup.tgz'
```

5. Start services and verify health:

```bash
# Lab HTTP profile (this PC only — never public internet):
docker compose --profile full start api nginx
curl -fsS http://127.0.0.1:8080/health

# Campus HTTPS overlay (ports: !override — no :8080):
docker compose --profile full -f docker-compose.yml -f docker-compose.https.yml start api nginx
curl -fsSk https://127.0.0.1/health
```

6. Spot-check: admin login, public KB article count, Ask a known handbook question.

## Host / non-Docker

- Postgres: `pg_dump -Fc` / `pg_restore` against `ASKA_DATABASE_URL`
- Chroma + PDFs: zip `backend/data/chroma` and `backend/data/documents` (and attachments dir) from the same moment as the dump
- Encrypt the zip with the same passphrase policy before offsite storage

## Retention

Keep at least 7 daily backups and one weekly copy offline. Test a restore on a spare machine before campus go-live.

## Lab vs campus

| Mode | Rule |
|------|------|
| Laptop lab HTTP `:8080` | Local testing only — **do not** publish to campus/public internet |
| Campus go-live | HTTPS overlay + encrypted off-host backups + rotated secrets |
