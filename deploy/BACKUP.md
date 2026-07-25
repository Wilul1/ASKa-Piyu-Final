# Backup and restore (Postgres + Chroma)

ASKa-Piyu keeps **two** stores that must stay consistent:

| Store | Compose volume / path | Contents |
|-------|----------------------|----------|
| PostgreSQL | `aska_pgdata` | users, tickets, published FAQs, auth |
| Chroma | `aska_chroma` | RAG vectors for Ask / chatbot |
| Documents | `aska_documents` | original PDFs for citations |
| Attachments | `aska_attachments` | ticket uploads |

Back up **Postgres + Chroma (+ documents)** together. Restoring Postgres alone without Chroma leaves Ask broken for FAQs; restoring Chroma alone without FAQ rows leaves orphan vectors.

## Backup (Docker Compose `full` profile)

```bat
REM From repo root. Creates deploy\backups\<timestamp>\
scripts\backup_aska.bat
```

Or manually:

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

Keep copies off the VPS (USB, campus NAS, or object storage).

## Restore

1. Stop API/nginx (Postgres can stay up for `pg_restore`):

```bat
docker compose --profile full stop api nginx
```

2. Restore Postgres (destroys current app data in `aska_piyu`):

```bash
docker compose --profile full exec -T postgres \
  pg_restore -U postgres -d aska_piyu --clean --if-exists < deploy/backups/<stamp>/aska_piyu.dump
```

3. Restore data volumes into the API container paths:

```bash
docker compose --profile full run --rm --no-deps -v "$(pwd)/deploy/backups/<stamp>/data_volumes.tgz:/backup.tgz:ro" api \
  sh -c 'rm -rf /data/chroma/* /data/documents/* /data/ticket_attachments/* && tar -C /data -xzf /backup.tgz'
```

4. Start services and verify:

```bat
docker compose --profile full start api nginx
curl -fsS http://127.0.0.1:8080/health
```

5. Spot-check: admin login, public KB article count, Ask a known handbook question.

## Host / non-Docker

- Postgres: `pg_dump -Fc` / `pg_restore` against `ASKA_DATABASE_URL`
- Chroma + PDFs: zip `backend/data/chroma` and `backend/data/documents` (and attachments dir) from the same moment as the dump

## Retention

Keep at least 7 daily backups and one weekly copy offline. Test a restore on a spare machine before campus go-live.
