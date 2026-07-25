# ASKa-Piyu production deploy

## 0. One-shot laptop / lab bootstrap (optional)

On a Windows machine with Postgres already running and a Groq key in `backend/.env`:

```bat
python scripts\bootstrap_campus_deploy.py
```

This writes root `.env`, `backend/.env.production`, self-signed TLS for `aska.local`, Flutter `api_base.url`, Android keystore, runs `check_production_env` + Alembic + seeds, and stores passwords in `deploy/BOOTSTRAP_CREDENTIALS.txt` (gitignored). Daily-dev `backend/.env` is left unchanged unless you pass `--apply-production-env`.

For a real campus VPS, still follow §1–§3 with Let's Encrypt and your real hostname.

## 1. Environment

Copy [`backend/.env.example`](backend/.env.example) to `backend/.env` and set:

| Variable | Production value |
|----------|------------------|
| `ASKA_ENV` | `production` |
| `ASKA_DATABASE_URL` | Real Postgres URL |
| `ASKA_DATABASE_INIT_ON_STARTUP` | `false` |
| `ASKA_AUTH_SECRET_KEY` | Strong unique secret (not a placeholder) |
| `ASKA_CORS_ORIGINS` | HTTPS Flutter/web origins (not `*`, not localhost-only) |
| `ASKA_ALLOW_ADMIN_API_KEY` | `false` |
| `ASKA_GROQ_API_KEY` | Required for LLM answers |
| `ASKA_SEED_OFFICE_PASSWORD` | Strong password for seeded office logins (required by office seed in production) |
| `ASKA_KB_REBUILD_DOCUMENT_PATHS` | Handbook/charter PDF paths (see Docker note below) |
| `ASKA_CHROMA_PERSIST_DIR` / `ASKA_DOCUMENTS_PERSIST_DIR` / `ASKA_TICKET_ATTACHMENTS_DIR` | Persistent disks |

## 2. Database + env preflight + seed

```bat
cd backend
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
REM edit .env for production values (including ASKA_SEED_OFFICE_PASSWORD)
python scripts/check_production_env.py
REM Creates tables + additive columns (audience, rag_indexed, ticket KB fields, etc.)
alembic upgrade head
python scripts/seed_admin.py --email admin@your.edu --password "YourStrongPass1"

REM Required: office rows + office staff logins so tickets can route.
REM Without this, a fresh DB may have an admin but no Registrar/ICT/OSAS accounts.
set ASKA_SEED_OFFICE_PASSWORD=YourStrongOfficePass1
python scripts/seed_office_accounts.py
python scripts/seed_office_aliases.py
```

After seeding, office staff can sign in (examples: `registrar@aska.local`, `ict@aska.local`, `osas@aska.local`) with `ASKA_SEED_OFFICE_PASSWORD`. Add more offices later in Admin → Offices, then re-run `seed_office_accounts.py` to create matching logins.

**Docker Compose:** run the same seed commands against the compose DB (from a host venv with `ASKA_DATABASE_URL` pointing at the published Postgres, or):

```bat
docker compose --profile full exec api python scripts/seed_admin.py --email admin@your.edu --password "YourStrongPass1"
docker compose --profile full exec -e ASKA_SEED_OFFICE_PASSWORD=YourStrongOfficePass1 api python scripts/seed_office_accounts.py
docker compose --profile full exec api python scripts/seed_office_aliases.py
```

## 3. Run API (no --reload)

```bat
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
```

Use **one** worker with the bundled Chroma store (multi-worker can lock/corrupt the local SQLite persist dir and doubles in-process rate limits).

Or Docker Compose (Postgres + API + nginx):

**Lab / HTTP only** (port 8080 — tokens are cleartext; do not use on a public campus network):

```bat
copy .env.example .env
REM set a strong POSTGRES_PASSWORD in .env (required; no default)
docker compose --profile full up -d --build
```

**Production / HTTPS** (required so passwords and JWTs are not cleartext):

1. Put `fullchain.pem` + `privkey.pem` in [`deploy/certs/`](deploy/certs/README.md).
2. Start with the TLS overlay (`ports: !override` drops lab `:8080`):

```bat
docker compose --profile full -f docker-compose.yml -f docker-compose.https.yml up -d --build
```

This serves HTTP→HTTPS redirect on port 80 and TLS on 443 ([`deploy/nginx.https.conf`](deploy/nginx.https.conf)). Point Flutter / `ASKA_CORS_ORIGINS` at `https://your-host` (or `https://your-host:8443` if you set `HTTPS_PORT`).

Postgres is **not** published to the host (API reaches it as `postgres:5432` on the Docker network). Do **not** attach `docker-compose.dev.yml` on a VPS — that overlay binds `127.0.0.1:5432` for local laptop development only.

## 4. Reverse proxy rate limits

Compose nginx already applies auth/QA rate limits. The API also enforces in-process limits on `/auth/login`, `/auth/signup`, and Ask endpoints as a safety net when uvicorn is exposed without nginx (still prefer the `full` profile or an edge proxy for multi-worker deploys). Set `ASKA_TRUST_PROXY=true` only behind a trusted proxy so limits use `X-Forwarded-For`. For an external proxy, also see [`deploy/nginx-rate-limits.conf`](deploy/nginx-rate-limits.conf) or [`deploy/Caddyfile.rate-limits.example`](deploy/Caddyfile.rate-limits.example).

## 5. Restore public KB articles (after RAG fail-close)

If publish/create left articles as drafts because Chroma indexing failed, or Ask is broken for `rag_indexed=false` published rows:

```bat
cd backend
python scripts/restore_public_kb_articles.py
python scripts/restore_public_kb_articles.py --apply
```

Dry-run first. `--apply` republishes gated drafts and re-indexes RAG-stale published FAQs. Inspect counts with `python scripts/inspect_kb_articles.py`.

## 6. Knowledge base audience tags (BE-05)

Untagged legacy chunks are treated as **student**-visible only. Prefer one of:

**A. Stamp in place (no wipe):**

```bat
cd backend
python scripts/stamp_legacy_audience.py --dry-run
python scripts/stamp_legacy_audience.py
```

**B. Full rebuild** (maintenance window): set `ASKA_KB_REBUILD_DOCUMENT_PATHS`, then `POST /admin/kb/rebuild`.

In Docker Compose the API stores PDFs on the `aska_documents` volume at `/data/documents` (not `./data/documents` inside the image). You can still list host-style paths like `./data/documents/<id>/handbook.pdf` in `.env` — rebuild remaps the `data/documents/` suffix onto `ASKA_DOCUMENTS_PERSIST_DIR`. Prefer explicit container paths when possible:

```env
ASKA_DOCUMENTS_PERSIST_DIR=/data/documents
ASKA_KB_REBUILD_DOCUMENT_PATHS=/data/documents/<id>/LSPU Student Handbook.pdf;/data/documents/<id>/LSPU Faculty Manual 2020.pdf
```

## 7. Flutter release

```bat
copy flutter_app\api_base.url.example flutter_app\api_base.url
REM edit flutter_app\api_base.url to https://api.your.edu
scripts\build_flutter_web.bat

REM Android: applicationId / iOS bundle id is ph.edu.lspu.aska_piyu
REM Create a release keystore + flutter_app\android\key.properties
REM (see flutter_app\android\key.properties.example) — do not use the debug keystore.
scripts\build_flutter_apk.bat
REM Play Store upload:
scripts\build_flutter_aab.bat
```

Or `set ASKA_API_BASE_URL=https://api.your.edu` before the build scripts. Release builds require `https://` (override for local http only with `ASKA_ALLOW_INSECURE_API_URL=true`). Android release includes `INTERNET` in the main manifest. Local-only debug-signed APKs/AABs: `set ASKA_ALLOW_DEBUG_RELEASE_SIGNING=true`.

## 8. Health

- `GET /health`
- Log in as the seeded admin; confirm OpenAPI/`/docs` is off.
- Log in as a seeded office account; confirm Assigned Tickets opens (proves offices were seeded).

## 9. Backups

Back up Postgres **and** Chroma/documents together — see [`deploy/BACKUP.md`](deploy/BACKUP.md) and `scripts\backup_aska.bat`.

## 10. TLS renewal

After Let's Encrypt is in place, schedule [`scripts/renew_letsencrypt_certs.sh`](scripts/renew_letsencrypt_certs.sh) (see [`deploy/certs/README.md`](deploy/certs/README.md)).
