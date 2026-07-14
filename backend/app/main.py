from app.utils.console_encoding import configure_console_encoding

configure_console_encoding()

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import DOTENV_PATH, admin_key_sha256_prefix, safe_admin_config_diagnostics, settings
from app.db.session import get_database_health, initialize_database, safe_database_url
from app.routes.admin.knowledge_base import chroma_router, kb_tools_router, router as admin_kb_router
from app.routes.auth import router as auth_router
from app.routes.documents import router as documents_router
from app.routes.knowledge_base import router as kb_browser_router
from app.routes.qa import router as qa_router
from app.routes.student.chat import router as student_router
from app.routes.tickets import router as tickets_router

logger = logging.getLogger(__name__)


async def validate_startup_configuration() -> None:
    admin_key = settings.admin_api_key or ""
    logger.info("Loaded dotenv: %s", DOTENV_PATH)
    logger.info("Configured admin key: %s", bool(admin_key))
    logger.info("Admin key length: %s", len(admin_key))
    logger.info("Admin key sha256 prefix: %s", admin_key_sha256_prefix())
    if not admin_key:
        logger.warning(
            "ASKA_ADMIN_API_KEY is missing. Admin endpoints are disabled until the key is configured."
        )
    if settings.groq_model and not settings.groq_api_key:
        logger.warning(
            "Groq model %s is configured, but ASKA_GROQ_API_KEY is missing. "
            "POST /qa/ask will return a graceful generation error until the key is set.",
            settings.groq_model,
        )
    if settings.database_url:
        logger.info("PostgreSQL application database configured: %s", safe_database_url(settings.database_url))
        if settings.database_init_on_startup:
            initialize_database()
            logger.info("PostgreSQL application tables initialized.")
    else:
        logger.info("ASKA_DATABASE_URL is not configured. PostgreSQL app-data features are disabled.")
    if not settings.auth_secret_key:
        logger.warning("ASKA_AUTH_SECRET_KEY is missing. Login and bearer token authentication are disabled.")


@asynccontextmanager
async def lifespan(_: FastAPI):
    await validate_startup_configuration()
    yield


app = FastAPI(
    title=settings.app_title,
    version=settings.app_version,
    lifespan=lifespan,
    description="""
ASKa-Piyu has **two separate flows**:

### 1. Admin — Knowledge base creation
`POST /admin/knowledge-base/ingest` — Upload handbook/policy → OCR/PDF extract → clean → chunk → ChromaDB

`POST /admin/knowledge-base/extract` — Preview extraction only (no indexing)

Used at deployment, policy updates, and maintenance.

### 2. Student — Question answering
`POST /student/ask` — Question → ChromaDB search → AI answer

**No OCR. No document upload.** Knowledge must be prepared beforehand.
""",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(admin_kb_router)
app.include_router(kb_tools_router)
app.include_router(chroma_router)
app.include_router(kb_browser_router)
app.include_router(documents_router)
app.include_router(qa_router)
app.include_router(student_router)
app.include_router(tickets_router)
app.include_router(auth_router)


@app.get("/health")
def health_check() -> dict:
    from app.services.chroma_store import get_knowledge_base_store

    store = get_knowledge_base_store()
    return {
        "status": "ok",
        "service": "aska-piyu",
        "knowledge_base_chunks": store.chunk_count,
        "flows": {
            "admin": "/admin/knowledge-base/ingest",
            "student": "/student/ask",
            "qa": "/qa/ask",
        },
    }


@app.get("/health/database")
def database_health_check() -> dict:
    return get_database_health()


@app.get("/admin/debug/config")
def admin_debug_config() -> dict:
    return safe_admin_config_diagnostics()
