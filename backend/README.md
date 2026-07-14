# ASKa-Piyu Backend

Python API with **two separate flows** — admin knowledge-base creation and student Q&A.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  ADMIN — Knowledge Base Creation (deployment / policy updates)  │
├─────────────────────────────────────────────────────────────────┤
│  Upload handbook/procedure                                      │
│       ↓                                                         │
│  OCR / PDF extraction (EasyOCR + PyMuPDF)                       │
│       ↓                                                         │
│  Clean text                                                     │
│       ↓                                                         │
│  Chunking                                                       │
│       ↓                                                         │
│  Embeddings (ChromaDB built-in)                                 │
│       ↓                                                         │
│  ChromaDB updated                                               │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  STUDENT — Question Flow (runtime, Flutter app)                 │
├─────────────────────────────────────────────────────────────────┤
│  Student asks question                                          │
│       ↓                                                         │
│  ChromaDB similarity search                                     │
│       ↓                                                         │
│  Retrieve relevant chunks                                       │
│       ↓                                                         │
│  AI generates answer                                            │
│       ↓                                                         │
│  Answer displayed                                               │
│                                                                 │
│  ✗ No OCR   ✗ No document upload                                │
└─────────────────────────────────────────────────────────────────┘
```

## API endpoints

| Flow | Method | Path | Purpose |
|------|--------|------|---------|
| Admin | `POST` | `/admin/knowledge-base/extract` | Preview OCR/text only |
| Admin | `POST` | `/admin/knowledge-base/ingest` | Full pipeline → ChromaDB |
| Student | `POST` | `/student/ask` | RAG question answering |
| — | `GET` | `/health` | Status + chunk count |

### Admin ingest (multipart)

Admin requests must include `X-Admin-Key` matching `ASKA_ADMIN_API_KEY`.

- `file` — PDF or image
- `title` (optional) — display name in KB
- `document_id` + `replace_existing` (optional) — update existing doc

### Knowledge Base taxonomy updates

KB category metadata is written into ChromaDB when documents are ingested. After changing `app/knowledge_base_categories.json` or the taxonomy classification rules, an administrator must reset and re-ingest the knowledge base, or run the rebuild flow, so existing chunks receive the new category and subcategory metadata.

- Reset only: `DELETE /admin/chroma/reset`
- Rebuild configured source documents: `POST /admin/kb/rebuild`
- Re-ingest manually: `POST /admin/knowledge-base/ingest`

### Student ask (JSON)

```json
{ "question": "How do I drop a subject?" }
```

```json
{
  "status": "success",
  "flow": "student_question",
  "question": "How do I drop a subject?",
  "answer": "...",
  "sources": [{ "title": "...", "snippet": "...", "relevance_score": 0.87 }]
}
```

## Setup

```bash
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Docs: http://localhost:8000/docs

### Development office accounts

Public signup creates student accounts only. To seed local office accounts for
ticket workflow testing, configure `ASKA_DATABASE_URL`, then run:

```bash
python scripts/seed_office_accounts.py
```

This idempotently creates `ICT Office`, `Registrar`, and `Office of Student
Affairs`, plus `ict@aska.local`, `registrar@aska.local`, and `osas@aska.local`
with password `office123`.

To enable dynamic Article Planner office grouping, also seed `office_aliases`:

```bash
python scripts/seed_office_aliases.py
```

Runtime matching always loads from PostgreSQL; the seed script only populates
development aliases and must not be treated as hardcoded planner logic.

## Project layout

```
app/
├── routes/
│   ├── admin/knowledge_base.py   # ingest + extract
│   └── student/chat.py           # ask only
├── services/
│   ├── admin/knowledge_base_pipeline.py
│   ├── student/question_service.py
│   ├── document_ingestion.py     # OCR/PDF (admin only)
│   ├── text_cleaner.py
│   ├── chunking.py
│   ├── chroma_store.py
│   └── rag_answer.py
└── utils/ocr, utils/pdf
```

## Configuration (`ASKA_` prefix)

| Variable | Default | Description |
|----------|---------|-------------|
| `ADMIN_API_KEY` | — | Required key for admin extract/ingest |
| `CHROMA_PERSIST_DIR` | `./data/chroma` | Vector DB storage |
| `RAG_TOP_K` | `5` | Chunks retrieved per question |
| `OPENAI_API_KEY` | — | Optional LLM answers |
| `CHUNK_MAX_CHARS` | `1200` | Chunk size |

## Tests

Pytest **always** uses `ASKA_TEST_DATABASE_URL` (database `aska_piyu_test`).
It will abort if the active database is `aska_piyu` or any name that does not end with `_test`.
Destructive cleanup of `published_articles` is refused on non-test databases unless
`ASKA_ALLOW_DESTRUCTIVE_RESET=true`.

```bash
# Create once (conftest also auto-creates aska_piyu_test if missing):
# createdb aska_piyu_test

pytest tests/ -v
```

## Flutter integration

**Admin panel** → `POST /admin/knowledge-base/ingest` with `MultipartFile`

**Student “Ask ASKa-Piyu”** → `POST /student/ask` with JSON body only
