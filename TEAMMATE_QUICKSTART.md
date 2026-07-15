# ASKa-Piyu — Teammate Quick Start (Windows)

Your groupmate’s error means **PostgreSQL is not running** on their PC (`ConnectionTimeout` to `localhost:5432`). Copying `.env` alone is not enough — each machine needs its own database service.

Published articles and chatbot data live in **that machine’s** Postgres + Chroma folders. A new clone starts empty until they seed and/or publish, or restore a DB dump.

---

## Fastest path (Docker — recommended)

### 1. Install once
- **Docker Desktop** — https://www.docker.com/products/docker-desktop/
- **Python 3.11 or 3.12**
- **Flutter** (stable)
- **Git**

### 2. Clone and start Postgres

```bat
cd %USERPROFILE%\Desktop
git clone <REPO_URL> ASKa-Piyu-Final
cd ASKa-Piyu-Final
scripts\start_postgres.bat
```

Keep Docker Desktop running whenever you develop.

### 3. Backend `.env`

```bat
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Edit `backend\.env` so DB matches Docker defaults:

```env
ASKA_DATABASE_URL=postgresql+psycopg://postgres:aska1234@localhost:5432/aska_piyu
ASKA_TEST_DATABASE_URL=postgresql+psycopg://postgres:aska1234@localhost:5432/aska_piyu_test
ASKA_DATABASE_INIT_ON_STARTUP=true
ASKA_ADMIN_API_KEY=change-this-admin-key
ASKA_AUTH_SECRET_KEY=change-this-auth-secret
ASKA_GROQ_API_KEY=your_groq_key_here
ASKA_GROQ_MODEL=llama-3.3-70b-versatile
```

Share Groq / admin keys **privately** (chat). Never commit `.env` to GitHub.

### 4. Seed offices

```bat
cd backend
venv\Scripts\activate
python scripts/seed_office_accounts.py
python scripts/seed_office_aliases.py
```

Office password for seeded staff: `office123`

### 5. Run

```bat
cd ..
run_project.bat
```

Or separately:

```bat
cd backend
venv\Scripts\activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

```bat
cd flutter_app
flutter run -d chrome --dart-define=ASKA_API_BASE_URL=http://localhost:8000
```

---

## Why KB / chatbot fail

| Symptom | Cause | Fix |
|---------|--------|-----|
| Backend exits: `ConnectionTimeout` / `localhost:5432` | Postgres not running | `scripts\start_postgres.bat` or start local Postgres service |
| Flutter: “Could not load Knowledge Base…” | Backend never started | Fix DB, then start Uvicorn; click Retry |
| Chatbot weak / generation error | Missing `ASKA_GROQ_API_KEY` in **their** `backend/.env` | Add key, restart backend |
| No published articles | Fresh empty database | Admin must ingest + publish on that PC, or restore a dump |
| Wrong password in `.env` | Copied someone else’s Postgres password | Use `aska1234` with Docker, or your local Postgres password |

---

## Without Docker

1. Install PostgreSQL for Windows.
2. Create databases `aska_piyu` and `aska_piyu_test`.
3. Put **your** password into `ASKA_DATABASE_URL`.
4. Start the **PostgreSQL** Windows service before the backend.

---

## Sharing demo data (optional)

`.env` does **not** copy published articles. To share demo KB/tickets:

```bat
pg_dump -U postgres aska_piyu > aska_piyu_demo.sql
```

Teammate:

```bat
psql -U postgres -d aska_piyu -f aska_piyu_demo.sql
```

Chroma RAG files are under `backend/data/chroma` — zip that folder only if you also need the same chatbot index.

---

## Checklist before asking for help

- [ ] Docker Desktop running **or** local Postgres service running  
- [ ] `scripts\start_postgres.bat` succeeded (or `psql -U postgres -c "\l"` works)  
- [ ] `backend/.env` exists (not only `.env.example`)  
- [ ] DB URL password matches Docker (`aska1234`) or local Postgres  
- [ ] Backend terminal shows `Application startup complete` (not `startup failed`)  
- [ ] Flutter uses `http://localhost:8000`  
- [ ] Groq key set if chatbot demo needs it  
