import hashlib
import json
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parents[1]
DOTENV_PATH = BACKEND_DIR / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ASKA_", env_file=DOTENV_PATH, extra="ignore")

    app_title: str = "ASKa-Piyu API"
    app_version: str = "0.2.0"

    # --- Document extraction (admin flow only) ---
    min_chars_per_page_for_digital_pdf: int = 40
    pdf_ocr_zoom: float = 2.0
    easyocr_languages: list[str] = ["en"]
    easyocr_gpu: bool = False
    ocr_preprocess_enabled: bool = True
    ocr_compare_original: bool = True
    ocr_min_dimension: int = 1200
    ocr_max_dimension: int = 2600
    ocr_contrast_factor: float = 1.45
    ocr_threshold_enabled: bool = False
    ocr_threshold_value: int = 180
    max_upload_bytes: int = 50 * 1024 * 1024

    # --- Knowledge base (ChromaDB) ---
    admin_api_key: str | None = None
    chroma_persist_dir: str = "./data/chroma"
    chroma_collection_name: str = "aska_knowledge_base"
    kb_categories_path: str = "knowledge_base_categories.json"
    kb_rebuild_document_paths: str | None = None
    ticket_store_path: str = "./data/tickets.json"
    database_url: str | None = None
    test_database_url: str | None = None
    database_init_on_startup: bool = False
    # development | test | production — when env=test, active DB must end with _test
    env: str = "development"
    # Explicit override for DROP/TRUNCATE/DELETE helpers (never needed for normal tests)
    allow_destructive_reset: bool = False
    # Durable storage for original uploaded PDFs (citation / source viewer)
    documents_persist_dir: str = "./data/documents"
    ticket_attachments_dir: str = "./data/ticket_attachments"
    auth_secret_key: str | None = None
    # Shorter default reduces stolen-token window (no server-side revoke list).
    auth_token_ttl_minutes: int = 60 * 8
    chunk_max_chars: int = 1200
    chunk_overlap: int = 150
    # Local sentence-embedding model for Chroma retrieval (multilingual: handles
    # English/Tagalog/Taglish student phrasing). Ignored when env=test, which
    # always uses Chroma's bundled default embedding to keep tests fast/offline.
    embedding_model_name: str = "intfloat/multilingual-e5-small"
    embedding_device: str = "cpu"

    # --- Student Q&A (retrieval only; no OCR) ---
    rag_top_k: int = 5
    # Optional: set for LLM-generated answers; otherwise uses extractive RAG template
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    # These "groq_" names are historical. The QA answer generator and the LLM-
    # assisted taxonomy classifier both call an OpenAI-compatible chat
    # completions endpoint, controlled by llm_base_url below — groq_api_key /
    # groq_model just hold whatever credential/model that endpoint expects
    # (Groq, GitHub Models, OpenAI, Azure OpenAI, etc.), not necessarily Groq's.
    groq_api_key: str | None = None
    groq_model: str = "llama-3.3-70b-versatile"
    groq_timeout_seconds: float = 30.0
    # Chat-completions endpoint to call. Defaults to Groq's OpenAI-compatible
    # endpoint; override (together with groq_api_key/groq_model) to point at a
    # different OpenAI-compatible provider, e.g. GitHub Models
    # (https://models.github.ai/inference/chat/completions).
    llm_base_url: str = "https://api.groq.com/openai/v1/chat/completions"
    # Optional extra headers some providers require beyond Authorization/
    # Content-Type (e.g. GitHub Models needs Accept + X-GitHub-Api-Version).
    # JSON object string, e.g. '{"X-GitHub-Api-Version": "2022-11-28"}'.
    llm_extra_headers_json: str | None = None

    cors_origins: list[str] = [
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "http://localhost:64833",
        "http://127.0.0.1:64833",
    ]
    # None = auto (enabled outside production). Set true/false to override.
    # In production, prefer admin Bearer login; keep true only for scripts/CI.
    allow_admin_api_key: bool | None = None
    # None = auto (enabled unless env=production). Set true/false to override.
    expose_openapi: bool | None = None
    # When true, rate limits use X-Real-IP (preferred) or the right-most
    # X-Forwarded-For hop. Only enable behind a trusted reverse proxy
    # (Compose nginx). Never trust the left-most XFF (client-spoofable).
    trust_proxy: bool = False
    # Public /auth/signup. Set false to force admin-created student accounts.
    allow_public_signup: bool = True
    # Comma-separated email domains allowed for public signup (e.g. "lspu.edu.ph").
    # Empty/None = any domain.
    signup_allowed_email_domains: str | None = None
    # When set, public signup requires a matching invite_code in the request body.
    signup_invite_code: str | None = None


settings = Settings()


_PLACEHOLDER_SECRET_MARKERS = (
    "change-me",
    "change-this",
    "aska-piyu-dev",
    "aska-dev",
    "dev-secret",
    "replace-me",
)


def llm_extra_headers() -> dict[str, str]:
    """Parse ASKA_LLM_EXTRA_HEADERS_JSON into a header dict, ignoring bad input."""
    raw = (settings.llm_extra_headers_json or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {str(k): str(v) for k, v in parsed.items()}


def is_placeholder_secret(value: str | None) -> bool:
    text = (value or "").strip().lower()
    if not text:
        return True
    return any(marker in text for marker in _PLACEHOLDER_SECRET_MARKERS)


def openapi_enabled() -> bool:
    if settings.expose_openapi is not None:
        return bool(settings.expose_openapi)
    return settings.env != "production"


def admin_api_key_auth_enabled() -> bool:
    """Whether shared X-Admin-Key auth is accepted.

    Production defaults to Bearer-only admin unless ASKA_ALLOW_ADMIN_API_KEY=true.
    """
    if settings.allow_admin_api_key is not None:
        return bool(settings.allow_admin_api_key)
    return settings.env != "production"


def admin_key_sha256_prefix() -> str:
    admin_key = settings.admin_api_key or ""
    if not admin_key:
        return ""
    return hashlib.sha256(admin_key.encode("utf-8")).hexdigest()[:8]


def safe_admin_config_diagnostics() -> dict:
    """Minimal ops diagnostics — no filesystem paths or secret material."""
    admin_key = settings.admin_api_key or ""
    return {
        "env": settings.env,
        "admin_key_loaded": bool(admin_key),
        "admin_key_configured_length": len(admin_key) if admin_key else 0,
        "admin_api_key_auth_enabled": admin_api_key_auth_enabled(),
        "openapi_enabled": openapi_enabled(),
        "cors_origin_count": len(settings.cors_origins or []),
        "header_name": "x-admin-key",
    }
