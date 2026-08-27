# ASKa-Piyu — Setup Guide for Groupmates

This guide gets the project running on a new machine from GitHub: what to install, how to configure it, and how to start the backend + Flutter app.

For production hosting, see [`DEPLOY.md`](DEPLOY.md).

---

## What this project is

**ASKa-Piyu** is an LSPU student support platform with:

| Part | Tech | Role |
|------|------|------|
| `backend/` | Python FastAPI | Auth, tickets, KB ingest, ChromaDB RAG, Groq answers |
| `flutter_app/` | Flutter (web/desktop) | Student UI, chatbot, admin panel |

**Two separate data stores (do not mix them up):**

1. **PostgreSQL** — users, offices, tickets, published KB articles, auth
2. **ChromaDB** — document chunks for chatbot retrieval (RAG)

---

## 1. Install these tools first

### Required

| Tool | Version (recommended) | Why | Download |
|------|----------------------|-----|----------|
| **Git** | latest | Clone the repo | https://git-scm.com |
| **Python** | **3.11 or 3.12** (3.13 often works) | Backend API | https://www.python.org/downloads/ |
| **PostgreSQL** | 14+ | App database | https://www.postgresql.org/download/windows/ |
| **Flutter** | stable channel | Frontend app | https://docs.flutter.dev/get-started/install |

### Also useful

| Tool | Why |
|------|-----|
| **VS Code / Cursor** | Edit code |
| **Chrome** | Flutter web (`flutter run -d chrome`) |
| **pgAdmin** (optional) | View PostgreSQL databases |

### Check installs

Open a terminal (PowerShell or Command Prompt):

```bat
git --version
python --version
psql --version
flutter doctor
```

Fix anything `flutter doctor` flags (especially Chrome / Windows desktop toolchain if you need them).

---

## 2. Clone the repository

```bat
cd %USERPROFILE%\Desktop
git clone <YOUR_GITHUB_REPO_URL> ASKa-piyu
cd ASKa-piyu
```

Replace `<YOUR_GITHUB_REPO_URL>` with the real GitHub URL your teammate shared.

Folder layout you should see:

```
ASKa-piyu/
├── backend/          ← FastAPI + Chroma + Postgres
├── flutter_app/      ← Flutter UI
├── scripts/          ← Postgres start, Flutter web build, backup
├── run_project.bat   ← Windows launcher (after setup)
├── SETUP.md          ← this file
└── DEPLOY.md         ← production / Azure VM deploy
```

---

## 3. Set up PostgreSQL

### Recommended — Docker (same password on every laptop)

1. Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) and start it.
2. From the repo root:

```bat
scripts\start_postgres.bat
```

3. `scripts\start_postgres.bat` creates a repo-root `.env` with local password `aska1234` and publishes Postgres to **127.0.0.1:5432** only (via `docker-compose.dev.yml`). Use matching URLs in `backend/.env`:

```env
ASKA_DATABASE_URL=postgresql+psycopg://postgres:aska1234@localhost:5432/aska_piyu
ASKA_TEST_DATABASE_URL=postgresql+psycopg://postgres:aska1234@localhost:5432/aska_piyu_test
```

> Production / VPS: set a strong `POSTGRES_PASSWORD` in repo-root `.env` and run compose **without** `docker-compose.dev.yml` so port 5432 is not published.

### Alternative — install PostgreSQL locally

1. Install PostgreSQL and remember the **postgres** user password.
2. Create two databases (app + tests):

**Option A — pgAdmin:** create databases named `aska_piyu` and `aska_piyu_test`.

**Option B — terminal** (adjust password / path if needed):

```bat
psql -U postgres -c "CREATE DATABASE aska_piyu;"
psql -U postgres -c "CREATE DATABASE aska_piyu_test;"
```

> Pytest **always** uses `aska_piyu_test`. Never point the test URL at `aska_piyu`.

> **ConnectionTimeout / startup failed:** Postgres is not running or the password/port in `.env` is wrong. Fix the DB first — Flutter “Could not load Knowledge Base” is a symptom of that.

---

## 4. Backend setup

### 4.1 Create a virtual environment

```bat
cd backend
python -m venv venv
venv\Scripts\activate
```

Your prompt should show `(venv)`.

### 4.2 Install Python packages

```bat
pip install --upgrade pip
pip install -r requirements.txt
```

This installs FastAPI, Uvicorn, ChromaDB, EasyOCR, PyMuPDF, SQLAlchemy, pytest, etc.

**First EasyOCR run is slow** — it downloads OCR models (can be hundreds of MB). Wait for it once.

### 4.3 Create `backend/.env`

`.env` is **gitignored** (never committed). Copy the example:

```bat
copy .env.example .env
```

Then edit `backend/.env` (Notepad is fine). Use your real Postgres password:

```env
ASKA_ADMIN_API_KEY=change-this-admin-key
ASKA_ENV=development
ASKA_DATABASE_URL=postgresql+psycopg://postgres:YOUR_PASSWORD@localhost:5432/aska_piyu
ASKA_TEST_DATABASE_URL=postgresql+psycopg://postgres:YOUR_PASSWORD@localhost:5432/aska_piyu_test
ASKA_ALLOW_DESTRUCTIVE_RESET=false
ASKA_DOCUMENTS_PERSIST_DIR=./data/documents
ASKA_DATABASE_INIT_ON_STARTUP=true

ASKA_AUTH_SECRET_KEY=change-this-auth-secret
ASKA_AUTH_TOKEN_TTL_MINUTES=480

ASKA_GROQ_API_KEY=
ASKA_GROQ_MODEL=llama-3.3-70b-versatile
ASKA_GROQ_TIMEOUT_SECONDS=30

ASKA_CHROMA_PERSIST_DIR=./data/chroma
ASKA_CHROMA_COLLECTION_NAME=aska_knowledge_base
ASKA_RAG_TOP_K=5
# Prefer explicit origins. For Flutter web use a fixed port:
# flutter run -d chrome --web-port=8080
ASKA_CORS_ORIGINS=["http://localhost:8080","http://127.0.0.1:8080"]
ASKA_ALLOW_ADMIN_API_KEY=true
```

**Important fields:**

| Variable | What to set |
|----------|-------------|
| `ASKA_DATABASE_URL` | Your Postgres password + `aska_piyu` |
| `ASKA_TEST_DATABASE_URL` | Same password + `aska_piyu_test` |
| `ASKA_ADMIN_API_KEY` | Dev/scripts only when `ASKA_ALLOW_ADMIN_API_KEY=true` |
| `ASKA_AUTH_SECRET_KEY` | Long random string (required in production) |
| `ASKA_CORS_ORIGINS` | Explicit browser origins — never `*` in production |
| `ASKA_GROQ_API_KEY` | Optional. Without it, chatbot still works with extractive fallbacks; with it, answers are better via Groq |

Get a free Groq key at https://console.groq.com (optional but recommended for demos).

Ask a teammate privately for keys if the team shares one Groq/admin key. **Do not commit `.env` to GitHub.**

**Production (`ASKA_ENV=production`):** API refuses to start with placeholder secrets, missing auth secret, or CORS `*`. Shared `X-Admin-Key` is off by default — log in as admin instead (or set `ASKA_ALLOW_ADMIN_API_KEY=true` for scripts only). Put reverse-proxy rate limits on `/auth/login`, `/auth/signup`, and `/qa/ask`.

### 4.4 Seed office accounts (recommended)

With venv active and `.env` configured:

```bat
python scripts/seed_office_accounts.py
python scripts/seed_office_aliases.py
```

**Seeded office logins** (set `ASKA_SEED_OFFICE_PASSWORD`; local-dev default is `office123` only when `ASKA_ENV` is not production):

The seed script creates one staff login per office row in PostgreSQL.

Well-known shortcuts:

| Email | Office |
|-------|--------|
| `ict@aska.local` | ICT Office |
| `registrar@aska.local` | Registrar |
| `osas@aska.local` | Office of Student Affairs |
| `admissions@aska.local` | Admission and Testing Services |
| `accounting@aska.local` | Accounting Unit |
| `cashier@aska.local` | Cashier Unit |
| `guidance@aska.local` | Guidance Office |
| `hr@aska.local` | Human Resource Management Office |

Other offices get an email like `college-of-engineering@aska.local`.

Students can register via the app’s signup. Public signup creates **student** accounts only.
Admins can also create office accounts via `POST /auth/office-accounts` (JWT admin required).

### 4.5 Start the backend

```bat
cd backend
venv\Scripts\activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Check:

- Health: http://localhost:8000/health  
- API docs: http://localhost:8000/docs  

Leave this terminal open while you use the app.

---

## 5. Flutter app setup

### 5.1 Get dependencies

Open a **second** terminal:

```bat
cd flutter_app
flutter pub get
```

### 5.2 Run the app (must point at the API)

The app needs the backend URL via `--dart-define`:

**Web (recommended for admin PDF/citation features):**

```bat
flutter run -d chrome --dart-define=ASKA_API_BASE_URL=http://localhost:8000
```

**Windows desktop:**

```bat
flutter run -d windows --dart-define=ASKA_API_BASE_URL=http://localhost:8000
```

If the API base is empty, chat / admin / KB API calls will fail on mobile/desktop.
**Release builds require** `--dart-define=ASKA_API_BASE_URL=…` (the app throws if it is missing).

**Release / production builds** (from project root):

```bat
copy flutter_app\api_base.url.example flutter_app\api_base.url
REM edit flutter_app\api_base.url to your real API origin
scripts\build_flutter_web.bat
scripts\build_flutter_apk.bat
```

Or set `ASKA_API_BASE_URL` in the environment (overrides the file). The build scripts refuse the placeholder `https://api.example.com`.

### 5.3 Admin panel access

**Preferred:** log in with an **admin** account (Bearer token). Admin KB tools accept that session automatically.

**Optional (local/scripts):** paste `ASKA_ADMIN_API_KEY` into the Admin panel. That key stays **in memory only** for the session (not saved to disk). In production, shared key auth is disabled unless `ASKA_ALLOW_ADMIN_API_KEY=true`.

For Flutter web CORS, pin the port to match `.env`:

```bat
flutter run -d chrome --web-port=8080 --dart-define=ASKA_API_BASE_URL=http://localhost:8000
```

---

## 6. Easy launcher (Windows)

After backend `venv` exists and `.env` is ready, from the **project root**:

```bat
run_project.bat
```

This opens:

1. Backend terminal → Uvicorn on port `8000`
2. Flutter terminal → `flutter run` with `ASKA_API_BASE_URL=http://localhost:8000`

---

## 7. First-time knowledge base (chatbot)

After a fresh clone, Chroma is empty. Chatbot answers need indexed documents.

Typical Citizen’s Charter flow (Admin):

1. Start backend + Flutter.
2. Open **Admin** → upload Citizen’s Charter PDF.
3. **Extract** (OCR/structure preview).
4. **Index for Chatbot Retrieval** (writes many service chunks into Chroma).
5. Ask in chatbot: e.g. *“How do I validate my ID?”*

**Do not** expect Index to only index the active article card / form preview — Charter indexing should produce **many** `service_procedure` chunks (ID Validation, Good Moral, Scholarship, etc.).

Admin stats (`/admin/kb/statistics` or Statistics panel) should show:

- `total_chunks_indexed` **> 1**
- sample service titles
- `chunks_with_page_number` > 0 for PDF page citations

Manual Chroma reset (only when you intend to wipe vectors):

- `DELETE /admin/chroma/reset` (requires admin key)  
- **Does not** auto-run on startup  
- **Does not** delete `published_articles` in PostgreSQL

---

## 8. Running tests (backend)

```bat
cd backend
venv\Scripts\activate
pytest tests/ -v
```

Uses `ASKA_TEST_DATABASE_URL` only (`aska_piyu_test`).

---

## 9. Common problems

| Problem | Fix |
|---------|-----|
| `Backend virtual environment not found` | Create `backend\venv` and `pip install -r requirements.txt` |
| Flutter can’t reach API | Restart Flutter with `--dart-define=ASKA_API_BASE_URL=http://localhost:8000` |
| Admin extract/ingest 401 | Enter matching `ASKA_ADMIN_API_KEY` in Admin UI |
| Postgres connection error | Check password in `.env`, confirm Postgres service is running, DBs exist |
| Chatbot “empty knowledge base” | Extract → Index Charter (or handbook) into Chroma |
| Only 1 weird “Requirement: …” chunk | Restart backend, reset Chroma if needed, Extract full PDF again, then Index |
| EasyOCR / torch install fails | Use Python 3.11–3.12; retry `pip install -r requirements.txt` |
| Port 8000 in use | Stop other Uvicorn processes, or change port and update `ASKA_API_BASE_URL` |
| Login fails | Register a student account, or use seeded office emails |

---

## 10. Team / Git hygiene

**Never commit:**

- `backend/.env` (secrets)
- `backend/venv/`
- `backend/data/` (local Chroma / PDFs)
- `__pycache__`, `.pytest_cache`
- Flutter `build/` folders

**Safe to share privately (not in git):** Groq key, admin key, Postgres password.

Share this file + the GitHub clone URL with your groupmate; they create their own `.env` from `.env.example`.

---

## 11. Quick checklist

- [ ] Git, Python, PostgreSQL, Flutter installed  
- [ ] Repo cloned  
- [ ] Databases `aska_piyu` and `aska_piyu_test` created  
- [ ] `backend/venv` + `pip install -r requirements.txt`  
- [ ] `backend/.env` filled from `.env.example`  
- [ ] Seed office scripts run  
- [ ] Backend running on http://localhost:8000  
- [ ] Flutter run with `ASKA_API_BASE_URL=http://localhost:8000`  
- [ ] Admin key entered in app  
- [ ] (Optional) Groq key set for better chatbot answers  
- [ ] Charter/handbook extracted + indexed for chatbot  

---

## 12. Self-improving knowledge (ticket → FAQ → chatbot)

ASKa-Piyu can grow without developer re-indexing when offices resolve tickets and publish FAQs.

### Production workflow (pilot)

1. Student/faculty asks the chatbot; if unanswered, they submit a ticket.
2. Office staff resolve the ticket with an approved answer.
3. On a **Resolved/Closed** ticket, office clicks **Convert to Knowledge Base** and chooses **Publish now** (or Save draft, then Publish).
4. Publish indexes the FAQ into **Chroma** automatically and lists it in the public Knowledge Base. The next similar question can be answered by the chatbot.
5. Unpublish (from Article Library) removes the FAQ from Chroma and the public KB.

### Roles

| Role | Can convert ticket → draft | Can publish to public KB + Chroma | Retrieval audience |
|------|----------------------------|-----------------------------------|--------------------|
| Office | Assigned tickets only | Yes (own converted FAQs / KB tools) | Full corpus (support) |
| Admin | Yes | Yes | Full corpus |
| Student | No | No | `student` + `both` (+ legacy) |
| Faculty | No | No | `faculty` + `both` (+ legacy) |

Public signup supports **student** accounts only. Faculty/office/admin accounts are admin-created (`POST /auth/faculty-accounts`, `POST /auth/office-accounts`).

### Audience tagging

- Ticket FAQs set `audience` (`student` / `faculty` / `both`) at convert time.
- PDF ingest auto-tags RAG `audience` from filename/title (Faculty Manual → `faculty`, Student Handbook → `student`, Citizen's Charter → `both`). Re-index existing manuals after upgrading so filters apply.
- Publish/unpublish/delete (single + bulk), PATCH, and create-with-publish all commit Postgres **before** Chroma mutations. Failed re-index restores prior FAQ vectors and does **not** wipe them on cleanup. Chatbot QA (`/qa/ask` and `/student/ask`, same pipeline) requires login, drops unpublished `faq:{id}` orphans, filters by audience, and rate-limits asks. Source PDF downloads require login and block students from faculty-only manuals. Bulk article create accepts/infers `audience` (unclear defaults to `student`). After a failed rebuild that wiped Chroma, FAQ `rag_indexed` flags are cleared so Library shows **RAG stale**; use **Reindex all stale**. `GET /admin/debug/config` requires admin auth.
- FAQ re-index snapshots existing Chroma chunks and restores them if the new write fails (avoids empty-vector split-brain).
- Admin Chroma reset clears `rag_indexed` flags, re-ingests PDFs listed in `ASKA_KB_REBUILD_DOCUMENT_PATHS`, then re-indexes published FAQ articles. If that path list is empty/wrong, reset returns `success: false` unless `allow_skip_documents=true` (FAQ-only recovery). Full rebuild sets `success: false` when FAQ re-index fails.
- FAQ re-index aborts if existing vectors cannot be snapshotted (no delete). If restore fails after a failed write, `rag_indexed` is cleared in a separate commit; Article Library shows a **RAG stale** badge/filter and a one-click **Reindex chatbot** action (`POST /admin/kb/articles/{id}/reindex`).
- Article slugs are unique (helper + DB unique index); bulk create/update uses the same unique-slug helper as single create.

### Ops notes (real deployment)

- Keep Postgres and Chroma data directories on persistent volumes; back them up together.
- Bind the API to `0.0.0.0` behind HTTPS; never commit `.env` secrets.
- Set `ASKA_KB_REBUILD_DOCUMENT_PATHS` to the real handbook/charter PDF paths before relying on Chroma reset in production.
- If publish returns a RAG indexing error after the article was marked published, Library shows **RAG stale** — use **Reindex chatbot** (or fix Chroma disk/permissions and retry).
- Pilot SOP: offices resolve tickets and publish FAQs themselves. Admin remains available for system setup, bulk document ingest, and Chroma rebuild.

---

## 13. More docs inside the repo

| File | Contents |
|------|----------|
| `DEPLOY.md` | Production / Azure VM + Docker HTTPS |
| `backend/README.md` | API flows, ingest, tests |
| `backend/.env.example` | All env vars with placeholders |
| `flutter_app/README.md` | Minimal Flutter notes |

If something fails after following this guide, send your groupmate: Python version, `flutter doctor` summary, and the exact error from the backend terminal (redact secrets).
