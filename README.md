# ASKa-Piyu

Campus knowledge-base chatbot and ticketing (Flutter + FastAPI + PostgreSQL + Chroma).

- Local setup: [SETUP.md](SETUP.md)
- Production deploy: [DEPLOY.md](DEPLOY.md)

## Quick local start

```bat
scripts\start_postgres.bat
cd backend && venv\Scripts\activate && uvicorn app.main:app --reload --port 8000
cd flutter_app && flutter run --dart-define=ASKA_API_BASE_URL=http://localhost:8000
```

Or use `run_project.bat` from the repo root.
