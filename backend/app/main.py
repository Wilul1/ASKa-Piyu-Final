from app.utils.console_encoding import configure_console_encoding

configure_console_encoding()

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import (
    DOTENV_PATH,
    is_placeholder_secret,
    openapi_enabled,
    safe_admin_config_diagnostics,
    settings,
)
from app.db.session import get_database_health, initialize_database, safe_database_url
from app.routes.admin.knowledge_base import (
    chroma_router,
    kb_tools_router,
    require_admin_key,
    router as admin_kb_router,
)
from app.routes.announcements import router as announcements_router
from app.routes.auth import router as auth_router
from app.routes.documents import router as documents_router
from app.routes.knowledge_base import router as kb_browser_router
from app.routes.qa import router as qa_router
from app.routes.student.chat import router as student_router
from app.routes.tickets import router as tickets_router

logger = logging.getLogger(__name__)


async def validate_startup_configuration() -> None:
    from app.config import admin_api_key_auth_enabled

    admin_key = settings.admin_api_key or ""
    logger.info("Loaded dotenv: %s", DOTENV_PATH)
    logger.info("Configured admin key: %s", bool(admin_key))
    logger.info("Admin API key auth enabled: %s", admin_api_key_auth_enabled())
    logger.warning(
        "QA/auth/triage rate limits are in-process and do not span multiple workers. "
        "Enforce limits at the reverse proxy in multi-worker production."
    )

    is_production = settings.env == "production"

    if not settings.auth_secret_key:
        msg = "ASKA_AUTH_SECRET_KEY is missing. Login and bearer token authentication are disabled."
        if is_production:
            raise RuntimeError(
                "ASKA_AUTH_SECRET_KEY is required in production. "
                "Set a strong unique secret before starting the API."
            )
        logger.warning(msg)
    elif is_placeholder_secret(settings.auth_secret_key):
        msg = "ASKA_AUTH_SECRET_KEY looks like a development placeholder."
        if is_production:
            raise RuntimeError(f"{msg} Set a strong unique secret before production.")
        logger.warning("%s Rotate before any shared/campus deploy.", msg)

    if admin_api_key_auth_enabled():
        if not admin_key:
            msg = (
                "ASKA_ADMIN_API_KEY is missing. Shared X-Admin-Key auth is enabled "
                "but no key is configured."
            )
            if is_production:
                raise RuntimeError(
                    f"{msg} Set a strong key or set ASKA_ALLOW_ADMIN_API_KEY=false "
                    "to require admin Bearer login only."
                )
            logger.warning("%s Admin key endpoints stay disabled until configured.", msg)
        elif is_placeholder_secret(admin_key):
            msg = "ASKA_ADMIN_API_KEY looks like a development placeholder."
            if is_production:
                raise RuntimeError(f"{msg} Set a strong unique key before production.")
            logger.warning("%s Rotate before any shared/campus deploy.", msg)
    else:
        logger.info(
            "Shared X-Admin-Key auth is disabled (production default). "
            "Admin tools require a logged-in admin Bearer token. "
            "Set ASKA_ALLOW_ADMIN_API_KEY=true only for scripts/CI."
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
            if is_production:
                raise RuntimeError(
                    "ASKA_DATABASE_INIT_ON_STARTUP must be false in production. "
                    "Run `alembic upgrade head` (or a controlled migrate job) before starting the API."
                )
            initialize_database()
            logger.info("PostgreSQL application tables initialized.")
        elif is_production:
            logger.info(
                "Skipping create_all on startup (production). "
                "Ensure migrations were applied with alembic upgrade head."
            )
    elif is_production:
        raise RuntimeError(
            "ASKA_DATABASE_URL is required in production. "
            "Auth, tickets, and knowledge-base features need PostgreSQL."
        )
    else:
        logger.info("ASKA_DATABASE_URL is not configured. PostgreSQL app-data features are disabled.")

    cors_origins = list(settings.cors_origins or [])
    cors_wildcard = any(origin.strip() == "*" for origin in cors_origins)
    if cors_wildcard:
        msg = "ASKA_CORS_ORIGINS uses '*' (any browser origin can call anonymous APIs)."
        if is_production:
            raise RuntimeError(
                f"{msg} Set explicit origins (e.g. https://your-app.example) in production."
            )
        logger.warning("%s Set explicit origins for campus/production deploys.", msg)
    elif not cors_origins and is_production:
        raise RuntimeError(
            "ASKA_CORS_ORIGINS is empty in production. "
            "Set explicit browser origins for your Flutter/web host."
        )
    elif is_production:
        non_local = [
            origin
            for origin in cors_origins
            if origin.strip()
            and "localhost" not in origin.lower()
            and "127.0.0.1" not in origin
        ]
        if not non_local:
            raise RuntimeError(
                "ASKA_CORS_ORIGINS in production only lists localhost/127.0.0.1. "
                "Set your real Flutter/web host origin (e.g. https://aska.example)."
            )


def _warm_embedding_model() -> None:
    """Load the local embedding model in the background so the first /qa/ask
    is not blocked for 20–60s on a cold sentence-transformers download/load.
    Failures are logged only — chat can still fall back later if needed.
    """
    try:
        from app.services.embeddings import get_embedding_function

        get_embedding_function()(["query: warmup"])
        logger.info("Embedding model warm-up complete")
    except Exception:
        logger.exception("Embedding model warm-up failed")


@asynccontextmanager
async def lifespan(_: FastAPI):
    await validate_startup_configuration()
    # Do not block startup/healthchecks on model load.
    asyncio.create_task(asyncio.to_thread(_warm_embedding_model))
    yield


_docs_on = openapi_enabled()
app = FastAPI(
    title=settings.app_title,
    version=settings.app_version,
    lifespan=lifespan,
    docs_url="/docs" if _docs_on else None,
    redoc_url="/redoc" if _docs_on else None,
    openapi_url="/openapi.json" if _docs_on else None,
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

_cors_origins = list(settings.cors_origins or [])
_cors_wildcard = any(origin.strip() == "*" for origin in _cors_origins)
# Flutter web picks a random localhost port each `flutter run`; allow those in
# non-production without listing every port. Production must use explicit
# ASKA_CORS_ORIGINS only (no localhost regex).
_cors_local_origin_regex = (
    None
    if settings.env == "production" or _cors_wildcard
    else r"https?://(localhost|127\.0\.0\.1)(:\d+)?"
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if _cors_wildcard else _cors_origins,
    allow_origin_regex=_cors_local_origin_regex,
    # Browsers reject credentialed requests with Access-Control-Allow-Origin: *
    allow_credentials=not _cors_wildcard,
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
app.include_router(announcements_router)


@app.get("/health")
def health_check() -> dict:
    """Public liveness probe — no KB/config details."""
    return {"status": "ok", "service": "aska-piyu"}


@app.get("/health/database")
def database_health_check(_: None = Depends(require_admin_key)) -> dict:
    return get_database_health()


@app.get("/admin/debug/config")
def admin_debug_config(_: None = Depends(require_admin_key)) -> dict:
    return safe_admin_config_diagnostics()
