"""Tests for the minimal Heroku backend adaptation:

- Chroma local/cloud backend selection (chroma_store._build_chroma_client)
- credentials never logged/emitted
- DATABASE_URL normalization + ASKA_DATABASE_URL precedence / fallback
- embedding backend dispatcher remains compatible (regression guard)
- app imports successfully even with torch/sentence-transformers/easyocr
  treated as unavailable
- ingestion-disabled guard behavior
"""
import logging
from unittest.mock import MagicMock, patch

import pytest

from app.config import Settings
from app.services.chroma_store import _build_chroma_client
from app.services.ingestion_runtime import INGESTION_UNAVAILABLE_MESSAGE, ingestion_available


# --- A/B. Chroma backend selection ------------------------------------------


def test_local_backend_uses_persistent_client():
    fake_persistent = MagicMock(return_value="persistent-client-instance")
    with patch("app.services.chroma_store.settings") as mock_settings:
        mock_settings.chroma_backend = "local"
        mock_settings.chroma_persist_dir = "./data/chroma"
        with patch("chromadb.PersistentClient", fake_persistent) as mock_pc:
            with patch("chromadb.CloudClient") as mock_cc:
                result = _build_chroma_client()
    mock_pc.assert_called_once()
    mock_cc.assert_not_called()
    assert result == "persistent-client-instance"


def test_cloud_backend_uses_cloud_client_with_configured_credentials():
    fake_cloud = MagicMock(return_value="cloud-client-instance")
    with patch("app.services.chroma_store.settings") as mock_settings:
        mock_settings.chroma_backend = "cloud"
        mock_settings.chroma_api_key = "fake-key-for-test-only"
        mock_settings.chroma_tenant = "fake-tenant"
        mock_settings.chroma_database = "fake-db"
        with patch("chromadb.CloudClient", fake_cloud) as mock_cc:
            with patch("chromadb.PersistentClient") as mock_pc:
                result = _build_chroma_client()
    mock_cc.assert_called_once_with(
        api_key="fake-key-for-test-only", tenant="fake-tenant", database="fake-db",
    )
    mock_pc.assert_not_called()
    assert result == "cloud-client-instance"


def test_backend_name_is_case_insensitive():
    with patch("app.services.chroma_store.settings") as mock_settings:
        mock_settings.chroma_backend = "Cloud"
        mock_settings.chroma_api_key = "k"
        mock_settings.chroma_tenant = "t"
        mock_settings.chroma_database = "d"
        with patch("chromadb.CloudClient") as mock_cc:
            _build_chroma_client()
    mock_cc.assert_called_once()


def test_backend_defaults_to_local_when_unset():
    """The Settings field's own default -- independent of any .env -- proves
    "local" is the real default, mirroring the embedding-backend test."""
    assert Settings.model_fields["chroma_backend"].default == "local"


# --- C. Credentials never emitted -------------------------------------------

FAKE_SECRET = "chroma-fake-secret-for-testing-only-9f8e7d"


def test_cloud_client_failure_never_logs_credentials(caplog):
    with patch("app.services.chroma_store.settings") as mock_settings:
        mock_settings.chroma_backend = "cloud"
        mock_settings.chroma_api_key = FAKE_SECRET
        mock_settings.chroma_tenant = "t"
        mock_settings.chroma_database = "d"
        with patch("chromadb.CloudClient", side_effect=RuntimeError(f"auth failed for {FAKE_SECRET}")):
            with caplog.at_level(logging.DEBUG):
                with pytest.raises(RuntimeError):
                    _build_chroma_client()
    for record in caplog.records:
        assert FAKE_SECRET not in record.getMessage()


def test_build_chroma_client_source_never_formats_api_key_into_a_log_call():
    """Static check: _build_chroma_client has no logger.*() call referencing
    chroma_api_key at all -- the only place the key is used is the direct
    CloudClient(api_key=...) constructor argument."""
    import inspect
    from app.services import chroma_store

    src = inspect.getsource(chroma_store._build_chroma_client)
    assert "logger." not in src
    assert "print(" not in src


# --- D/E/F. Database URL normalization / fallback / precedence --------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("postgres://u:p@h:5432/d", "postgresql+psycopg://u:p@h:5432/d"),
        ("postgresql://u:p@h:5432/d", "postgresql+psycopg://u:p@h:5432/d"),
        ("postgresql+psycopg://u:p@h:5432/d", "postgresql+psycopg://u:p@h:5432/d"),
        (None, None),
    ],
)
def test_database_url_scheme_normalization(raw, expected, monkeypatch):
    monkeypatch.delenv("ASKA_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    if raw is not None:
        monkeypatch.setenv("ASKA_DATABASE_URL", raw)
    s = Settings(_env_file=None)
    assert s.database_url == expected


def test_database_url_fallback_to_heroku_var(monkeypatch):
    monkeypatch.delenv("ASKA_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@h:5432/herokudb")
    s = Settings(_env_file=None)
    assert s.database_url == "postgresql+psycopg://u:p@h:5432/herokudb"


def test_askA_database_url_takes_precedence_over_heroku_var(monkeypatch):
    monkeypatch.setenv("ASKA_DATABASE_URL", "postgres://u:p@h:5432/primary")
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@h:5432/shouldnotbeused")
    s = Settings(_env_file=None)
    assert s.database_url == "postgresql+psycopg://u:p@h:5432/primary"


def test_chroma_credentials_load_without_aska_prefix(monkeypatch):
    monkeypatch.setenv("CHROMA_API_KEY", "k")
    monkeypatch.setenv("CHROMA_TENANT", "t")
    monkeypatch.setenv("CHROMA_DATABASE", "d")
    s = Settings(_env_file=None)
    assert s.chroma_api_key == "k"
    assert s.chroma_tenant == "t"
    assert s.chroma_database == "d"


# --- G. Embedding backend dispatcher regression guard ------------------------


def test_embedding_backend_dispatcher_still_works():
    """Regression guard: the Chroma backend change must not have disturbed
    the existing, already-tested embedding backend dispatcher."""
    from app.services.embeddings import get_embedding_function, E5EmbeddingFunction

    get_embedding_function.cache_clear()
    try:
        with patch("app.services.embeddings.settings.embedding_backend", "local"):
            ef = get_embedding_function()
        assert isinstance(ef, E5EmbeddingFunction)
    finally:
        get_embedding_function.cache_clear()


# --- H. App import without local ML packages --------------------------------


def test_app_imports_with_torch_sentence_transformers_easyocr_unavailable():
    """Simulates the lightweight Heroku image: these four packages are not
    importable. app.main must still import cleanly (no module-level import
    anywhere in the app actually requires them -- confirmed by a full-tree
    grep during the audit; this test guards that fact going forward).

    Restores the original sys.modules entries afterward (in a finally) so
    other tests in this process keep referencing the same module objects
    they imported at collection time -- without this, a later test's
    `patch("app.services.ingestion_runtime.find_spec", ...)`-style target
    would silently patch a *different* (newly re-imported) module instance
    than the one this test file's own top-level imports are bound to.
    """
    import builtins
    import sys

    blocked = {"torch", "torchvision", "sentence_transformers", "easyocr"}
    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        root = name.split(".")[0]
        if root in blocked:
            raise ModuleNotFoundError(f"No module named '{root}' (simulated absence)")
        return real_import(name, *args, **kwargs)

    saved_modules = {
        name: mod for name, mod in sys.modules.items() if name == "app" or name.startswith("app.")
    }
    for mod_name in list(saved_modules):
        del sys.modules[mod_name]

    try:
        with patch.object(builtins, "__import__", guarded_import):
            import app.main  # noqa: F401 -- import succeeding is the assertion
    finally:
        for mod_name in list(sys.modules):
            if mod_name == "app" or mod_name.startswith("app."):
                del sys.modules[mod_name]
        sys.modules.update(saved_modules)


# --- I. Ingestion-disabled behavior ------------------------------------------


def test_ingestion_available_true_when_packages_present():
    ingestion_available.cache_clear()
    try:
        assert ingestion_available() is True
    finally:
        ingestion_available.cache_clear()


def test_ingestion_available_false_when_packages_missing():
    ingestion_available.cache_clear()
    try:
        with patch("app.services.ingestion_runtime.find_spec", return_value=None):
            assert ingestion_available() is False
    finally:
        ingestion_available.cache_clear()


@patch("app.routes.admin.knowledge_base.settings.admin_api_key", "test-admin-key")
def test_admin_extract_uses_lightweight_path_when_ingestion_unavailable():
    """/extract no longer 503s when local easyocr/sentence-transformers are
    unavailable (e.g. the Heroku web dyno) -- it now calls
    build_lightweight_preview (PyMuPDF + optional remote OCR worker) and
    returns 200 with the same ExtractDocumentResponse shape the Flutter
    Extract & Structure UI already understands. See
    app.services.admin.digital_ingestion.build_lightweight_preview."""
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    ingestion_available.cache_clear()
    lightweight_result = {
        "document_type": "information",
        "raw_text": "hello world",
        "cleaned_text": "hello world",
        "review_text": "hello world",
        "extracted_text": "hello world",
        "page_count": 1,
        "extraction_method": "pymupdf_digital",
        "structuring_method": "generic_chunking",
        "pipeline_stages": [],
        "structured": {"fields": [], "formatted_text": "hello world"},
    }
    try:
        with (
            patch("app.routes.admin.knowledge_base.ingestion_available", return_value=False),
            patch(
                "app.routes.admin.knowledge_base.build_lightweight_preview",
                return_value=lightweight_result,
            ) as mock_preview,
        ):
            response = client.post(
                "/admin/knowledge-base/extract",
                headers={"X-Admin-Key": "test-admin-key"},
                files={"file": ("test.pdf", b"%PDF-1.4 fake", "application/pdf")},
            )
        assert response.status_code == 200
        assert response.json()["extraction_method"] == "pymupdf_digital"
        mock_preview.assert_called_once()
    finally:
        ingestion_available.cache_clear()


@patch("app.routes.admin.knowledge_base.settings.admin_api_key", "test-admin-key")
def test_admin_ingest_uses_lightweight_path_when_ingestion_unavailable():
    """/ingest no longer 503s when local easyocr/sentence-transformers are
    unavailable -- it now calls build_lightweight_publish (which uses
    publish_new_version(), never delete_by_source_filename()+add()) and
    returns 200 with the same IngestKnowledgeBaseResponse shape. See
    app.services.admin.digital_ingestion.build_lightweight_publish."""
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    ingestion_available.cache_clear()
    lightweight_result = {
        "document_id": "doc-123",
        "document_type": "information",
        "source_filename": "test.pdf",
        "title": "test",
        "chunks_indexed": 3,
        "page_count": 1,
        "extraction_method": "pymupdf_digital",
        "structuring_method": "generic_chunking",
        "pipeline_stages": [],
        "extracted_text_preview": "hello world",
        "structured": {"fields": [], "formatted_text": "hello world"},
    }
    try:
        with (
            patch("app.routes.admin.knowledge_base.ingestion_available", return_value=False),
            patch(
                "app.routes.admin.knowledge_base.build_lightweight_publish",
                return_value=lightweight_result,
            ) as mock_publish,
        ):
            response = client.post(
                "/admin/knowledge-base/ingest",
                headers={"X-Admin-Key": "test-admin-key"},
                files={"file": ("test.pdf", b"%PDF-1.4 fake", "application/pdf")},
                data={"title": "test", "reviewed_text": "hello world"},
            )
        assert response.status_code == 200
        assert response.json()["document_id"] == "doc-123"
        mock_publish.assert_called_once()
        _, kwargs = mock_publish.call_args
        assert kwargs["reviewed_text"] == "hello world"
    finally:
        ingestion_available.cache_clear()


@patch("app.routes.admin.knowledge_base.settings.admin_api_key", "test-admin-key")
def test_admin_extract_never_calls_lightweight_path_when_ingestion_available():
    """Regression guard: local/Docker (ingestion_available()==True) must
    keep using the existing local extract_document_preview pipeline
    byte-for-byte -- the lightweight branch must be unreachable there."""
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    ingestion_available.cache_clear()
    try:
        with (
            patch("app.routes.admin.knowledge_base.ingestion_available", return_value=True),
            patch("app.routes.admin.knowledge_base.build_lightweight_preview") as mock_preview,
            patch("app.routes.admin.knowledge_base.extract_document_preview") as mock_legacy,
        ):
            mock_legacy.return_value = {
                "document_type": "information",
                "document_profile": None,
                "admin_selected_document_type": None,
                "parser_document_type": None,
                "source_type": None,
                "raw_text": "hello",
                "cleaned_text": "hello",
                "review_text": "hello",
                "extracted_text": "hello",
                "page_count": 1,
                "extraction_method": "pymupdf_digital",
                "structuring_method": "generic_chunking",
                "pipeline_stages": [],
                "structured": {"fields": [], "formatted_text": "hello"},
            }
            response = client.post(
                "/admin/knowledge-base/extract",
                headers={"X-Admin-Key": "test-admin-key"},
                files={"file": ("test.pdf", b"%PDF-1.4 fake", "application/pdf")},
            )
        assert response.status_code == 200
        mock_legacy.assert_called_once()
        mock_preview.assert_not_called()
    finally:
        ingestion_available.cache_clear()


@patch("app.routes.admin.knowledge_base.settings.admin_api_key", "test-admin-key")
def test_admin_ingest_never_calls_lightweight_path_when_ingestion_available():
    """Same regression guard for /ingest: local/Docker keeps using
    ingest_document_into_knowledge_base (delete_by_source_filename + add)
    unchanged -- this change does not retrofit that pipeline."""
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    ingestion_available.cache_clear()
    try:
        with (
            patch("app.routes.admin.knowledge_base.ingestion_available", return_value=True),
            patch("app.routes.admin.knowledge_base.build_lightweight_publish") as mock_publish,
            patch("app.routes.admin.knowledge_base.ingest_document_into_knowledge_base") as mock_legacy,
        ):
            mock_legacy.return_value = type(
                "FakeResult",
                (),
                {
                    "document_id": "legacy-doc-1",
                    "document_type": "information",
                    "source_filename": "test.pdf",
                    "title": "test",
                    "chunks_indexed": 1,
                    "page_count": 1,
                    "extraction_method": "pymupdf_digital",
                    "extracted_text_preview": "hello",
                    "structured": {"fields": [], "formatted_text": "hello"},
                    "structuring_method": "generic_chunking",
                    "pipeline_stages": [],
                    "diagnostic_report": None,
                    "validation_report": None,
                    "detected_document_type": None,
                    "knowledge_units": [],
                    "chunk_preview": [],
                    "kb_statistics": None,
                },
            )()
            response = client.post(
                "/admin/knowledge-base/ingest",
                headers={"X-Admin-Key": "test-admin-key"},
                files={"file": ("test.pdf", b"%PDF-1.4 fake", "application/pdf")},
            )
        assert response.status_code == 200
        assert response.json()["document_id"] == "legacy-doc-1"
        mock_legacy.assert_called_once()
        mock_publish.assert_not_called()
    finally:
        ingestion_available.cache_clear()


@patch("app.routes.admin.knowledge_base.settings.admin_api_key", "test-admin-key")
def test_admin_rebuild_returns_503_when_ingestion_unavailable():
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    ingestion_available.cache_clear()
    try:
        with patch("app.routes.admin.knowledge_base.ingestion_available", return_value=False):
            response = client.post(
                "/admin/kb/rebuild",
                headers={"X-Admin-Key": "test-admin-key"},
            )
        assert response.status_code == 503
        assert response.json()["detail"] == INGESTION_UNAVAILABLE_MESSAGE
    finally:
        ingestion_available.cache_clear()
