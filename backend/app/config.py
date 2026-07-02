import hashlib
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
    database_init_on_startup: bool = False
    auth_secret_key: str | None = None
    auth_token_ttl_minutes: int = 60 * 24
    chunk_max_chars: int = 1200
    chunk_overlap: int = 150

    # --- Student Q&A (retrieval only; no OCR) ---
    rag_top_k: int = 5
    # Optional: set for LLM-generated answers; otherwise uses extractive RAG template
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    groq_api_key: str | None = None
    groq_model: str = "llama-3.3-70b-versatile"
    groq_timeout_seconds: float = 30.0

    cors_origins: list[str] = ["*"]


settings = Settings()


def admin_key_sha256_prefix() -> str:
    admin_key = settings.admin_api_key or ""
    if not admin_key:
        return ""
    return hashlib.sha256(admin_key.encode("utf-8")).hexdigest()[:8]


def safe_admin_config_diagnostics() -> dict:
    admin_key = settings.admin_api_key or ""
    return {
        "cwd": str(Path.cwd()),
        "dotenv_path": str(DOTENV_PATH),
        "admin_key_loaded": bool(admin_key),
        "admin_key_length": len(admin_key),
        "admin_key_sha256_prefix": admin_key_sha256_prefix(),
        "header_name": "x-admin-key",
    }
