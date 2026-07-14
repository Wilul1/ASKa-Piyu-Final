# ASKa-Piyu — Setup Guide for Teammates

This guide explains how to clone the repo, install everything, and run the project on **Windows** (the usual team setup). Follow the sections in order.

---

## What this project is

ASKa-Piyu has two main parts:

| Folder | Role |
|--------|------|
| `backend/` | FastAPI API: auth, tickets, document OCR/PDF extract, ChromaDB chatbot retrieval, admin KB tools |
| `flutter_app/` | Flutter UI: student home, chatbot, knowledge base, tickets, admin panel |

**Typical flow**

1. Admin uploads a PDF (e.g. Citizen’s Charter) in the Admin panel  
2. Backend extracts/structures text and indexes chunks into **ChromaDB**  
3. Students ask questions in the chatbot; answers come from Chroma + optional Groq AI  
4. Published articles in PostgreSQL power the public Knowledge Base browser  

---

## What you need installed before starting

Install these on your PC:

### 1. Git
- Download: https://git-scm.com/downloads  
- Confirm: `git --version`

### 2. Python 3.11 or 3.12 (recommended)
- Download: https://www.python.org/downloads/  
- During install, check **“Add Python to PATH”**  
- Confirm:

```powershell
python --version
pip --version
```

> Python 3.13 may work, but if dependency installs fail, use 3.12.

### 3. PostgreSQL 14+
- Download: https://www.postgresql.org/download/windows/  
- Remember the password you set for the `postgres` user  
- After install, open **pgAdmin** or `psql` and create two databases:

```sql
CREATE DATABASE aska_piyu;
CREATE DATABASE aska_piyu_test;
```

`aska_piyu` = app data (users, tickets, published articles)  
`aska_piyu_test` = used **only** by pytest (never point app `.env` at the test DB)

### 4. Flutter SDK
- Install guide: https://docs.flutter.dev/get-started/install/windows  
- After install:

```powershell
flutter doctor
flutter --version
```

Fix anything `flutter doctor` marks as critical. For Chrome web:

```powershell
flutter config --enable-web
```

### 5. (Recommended) Chrome
Flutter web demos usually run in Chrome.

### 6. (Optional but recommended) Groq API key
Chat answers are better with Groq. Sign up at https://console.groq.com/ and create an API key.  
Without it, chatbot still runs with extractive/fallback answers.

---

## Clone the repository

```powershell
cd Desktop
git clone <PASTE_GITHUB_REPO_URL_HERE>
cd ASKa-piyu
```

---

## Backend setup

### Step 1 — Create a virtual environment

```powershell
cd backend
python -m venv venv
.\venv\Scripts\activate
```

Your prompt should show `(venv)`.

### Step 2 — Install Python packages

```powershell
pip install --upgrade pip
pip install -r requirements.txt
```

This can take several minutes (EasyOCR / PyTorch-related deps are large).  
**First OCR run later may also download EasyOCR models** — that is normal and can take a while / use disk space.

### Step 3 — Create your `.env` file

`.env` is **not** in Git (secret). Copy the example:

```powershell
copy .env.example .env
```

Open `backend/.env` in an editor and fill it in. Example template:

```env
ASKA_ADMIN_API_KEY=your-shared-admin-key-here
ASKA_CHROMA_PERSIST_DIR=./data/chroma
ASKA_CHROMA_COLLECTION_NAME=aska_knowledge_base
ASKA_RAG_TOP_K=5

ASKA_ENV=development
ASKA_DATABASE_URL=postgresql+psycopg://postgres:YOUR_POSTGRES_PASSWORD@localhost:5432/aska_piyu
ASKA_TEST_DATABASE_URL=postgresql+psycopg://postgres:YOUR_POSTGRES_PASSWORD@localhost:5432/aska_piyu_test
ASKA_ALLOW_DESTRUCTIVE_RESET=false
ASKA_DOCUMENTS_PERSIST_DIR=./data/documents
ASKA_DATABASE_INIT_ON_STARTUP=true

ASKA_AUTH_SECRET_KEY=change-this-to-any-long-random-string
ASKA_AUTH_TOKEN_TTL_MINUTES=1440

ASKA_GROQ_API_KEY=
ASKA_GROQ_MODEL=llama-3.3-70b-versatile
ASKA_GROQ_TIMEOUT_SECONDS=30

ASKA_CORS_ORIGINS=["*"]
```

**Important**
- Replace `YOUR_POSTGRES_PASSWORD` with your real Postgres password  
- Set `ASKA_ADMIN_API_KEY` to any shared team secret (needed by Admin panel)  
- Ask a teammate for a Groq key **privately** — do **not** commit it to GitHub  
- Never commit `backend/.env`

### Step 4 — Seed office test accounts (recommended)

With the venv active and Postgres running:

```powershell
python scripts/seed_office_accounts.py
python scripts/seed_office_aliases.py
```

Default office logins (local only):

| Email | Password | Office |
|-------|----------|--------|
| `ict@aska.local` | `office123` | ICT Office |
| `registrar@aska.local` | `office123` | Registrar |
| `osas@aska.local` | `office123` | Office of Student Affairs |

Students can also **sign up** in the app (signup creates student accounts).

### Step 5 — Start the API

```powershell
cd backend
.\venv\Scripts\activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Check:
- Health: http://localhost:8000/health  
- Swagger docs: http://localhost:8000/docs  

Leave this terminal open while using the app.

---

## Flutter app setup

Open a **second** terminal:

```powershell
cd flutter_app
flutter pub get
```

### Run on Chrome (usual for this team)

You **must** pass the backend URL:

```powershell
flutter run -d chrome --dart-define=ASKA_API_BASE_URL=http://localhost:8000
```

### Or use the Windows launcher

From the project root (after backend `venv` exists):

```powershell
.\run_project.bat
```

That opens two terminals: backend on port `8000`, Flutter with the same API URL.

### Admin key in the UI

In the Admin panel, paste the same value as `ASKA_ADMIN_API_KEY` from `backend/.env`.  
The app stores it in browser local storage for the session.

---

## First-time knowledge base (chatbot) setup

Empty Chroma = chatbot cannot answer policy questions. After backend + Flutter are running:

1. Log in / open **Admin**  
2. Upload a source PDF (e.g. Citizen’s Charter)  
3. Run **Extract** (wait for OCR/structuring — large PDFs take time)  
4. Click **Index for Chatbot Retrieval**  
5. Check admin KB statistics:
   - `total_chunks_indexed` should be **more than 1** for a full Charter  
   - Sample titles should include real services (e.g. ID Validation), not only a “Requirement: …” form card  

Optional later:
- **Generate Articles** → review → publish selected articles for the public Knowledge Base  
- Chatbot retrieval uses **Chroma**; public KB browse uses **published articles in Postgres** — they are separate

### Manual Chroma reset (if indexing looks wrong)

Only when an admin intentionally wants a clean vector DB:

- Use the admin Chroma reset action, **or**  
- `DELETE /admin/chroma/reset` with header `X-Admin-Key: <your admin key>`

Then re-extract and re-index.  
Do **not** expect an automatic Chroma wipe on every app startup.

---

## Optional: run backend tests

```powershell
cd backend
.\venv\Scripts\activate
pytest tests/ -q
```

Pytest always uses `ASKA_TEST_DATABASE_URL` (`aska_piyu_test`).  
It will refuse to wipe production-like DBs unless you set destructive flags (leave those off).

---

## Project layout (quick map)

```
ASKa-piyu/
├── backend/
│   ├── app/                 # FastAPI application code
│   ├── scripts/             # seed_office_accounts.py, etc.
│   ├── tests/
│   ├── requirements.txt
│   ├── .env.example         # copy → .env (local secrets)
│   └── data/                # chroma + document files (local, created at runtime)
├── flutter_app/
│   └── lib/                 # Dart screens / services
├── run_project.bat          # start backend + Flutter together
├── PROJECT_MEMORY.md        # architecture notes for the team
└── SETUP_GUIDE.md           # this file
```

---

## Common problems

| Problem | Fix |
|---------|-----|
| `Backend virtual environment not found` | Create `backend\venv` and `pip install -r requirements.txt` |
| Flutter can’t reach API / CORS / empty calls | Backend must be on `8000`, and Flutter must use `--dart-define=ASKA_API_BASE_URL=http://localhost:8000` |
| Admin actions return 401/403 | Enter matching `ASKA_ADMIN_API_KEY` in the Admin panel |
| DB connection errors | Postgres running? Correct password in `ASKA_DATABASE_URL`? Databases `aska_piyu` / `aska_piyu_test` exist? |
| Chatbot says knowledge base empty | Index a document in Admin (Chroma is empty until ingest) |
| Only 1 weird “Requirement: …” chunk | Re-extract full PDF, then Index again; check stats sample titles |
| OCR / EasyOCR very slow first time | Normal; models download once |
| `.env` missing after clone | Expected — copy from `.env.example` and fill values |
| Python package install fails on 3.13 | Install Python 3.12 and recreate `venv` |

---

## Security / GitHub hygiene

**Do commit**
- Code, `requirements.txt`, `.env.example`, docs  

**Do not commit**
- `backend/.env`  
- API keys, passwords, auth secrets  
- Local `venv/`, `__pycache__/`, Flutter build folders, large personal PDFs with private data (unless the team agrees)

Share secrets with teammates via a private channel (chat/password manager), not in the public repo.

---

## Minimum “it works” checklist

- [ ] PostgreSQL has `aska_piyu` and `aska_piyu_test`  
- [ ] `backend/.env` created from `.env.example`  
- [ ] `pip install -r requirements.txt` inside `venv` succeeded  
- [ ] `uvicorn` runs and http://localhost:8000/docs opens  
- [ ] `flutter pub get` succeeded  
- [ ] Flutter run with `ASKA_API_BASE_URL=http://localhost:8000`  
- [ ] Admin key entered in UI  
- [ ] At least one document indexed → chatbot answers a known question  

---

## Where to read next

- `backend/README.md` — API / architecture detail  
- `PROJECT_MEMORY.md` — team architecture and “do not break” rules  
- http://localhost:8000/docs — interactive API explorer while backend is running  

If something fails, paste the **exact terminal error** (and whether Postgres / uvicorn / Flutter is the failing piece) to the group chat.
