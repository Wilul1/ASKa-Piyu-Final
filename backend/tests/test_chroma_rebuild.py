from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)
ADMIN_HEADERS = {"X-Admin-Key": "test-admin-key"}


class RebuildStore:
    def __init__(self, events: list[str] | None = None) -> None:
        self.events = events if events is not None else []
        self.chunks: list[dict] = []

    def reset_collection(self) -> dict:
        self.events.append("reset")
        self.chunks.clear()
        return {
            "collection": "aska_knowledge_base",
            "vectors_removed": 2,
            "timestamp": "2026-06-28T00:00:00+00:00",
        }

    def list_chunks(self) -> list[dict]:
        return list(self.chunks)


def _source_file(tmp_path, name: str = "handbook.pdf"):
    path = tmp_path / name
    path.write_bytes(b"%PDF test handbook")
    return path


def _ingest_result(chunks: int = 2):
    return SimpleNamespace(
        chunks_indexed=chunks,
        validation_report={
            "suspicious_units_count": 1,
            "toc_like_units_count": 2,
            "invalid_campus_values": [{"title": "Unit", "field": "campus", "value": "Unknown"}],
        },
        chunk_preview=[
            {
                "metadata": {
                    "category": "Academic Policies",
                    "subcategory": "Registration",
                    "responsible_office": "Registrar",
                    "campus": "Sta. Cruz",
                }
            },
            {
                "metadata": {
                    "category": "Technical Support",
                    "subcategory": "Account Recovery",
                    "office": "ICT Office",
                    "campus": "Siniloan",
                }
            },
        ],
    )


@patch("app.routes.admin.knowledge_base.settings.admin_api_key", "test-admin-key")
@patch("app.routes.admin.knowledge_base.settings.chroma_collection_name", "aska_knowledge_base")
@patch("app.routes.admin.knowledge_base.get_knowledge_base_store")
@patch("app.routes.admin.knowledge_base.ingest_document_into_knowledge_base")
def test_admin_kb_rebuild_success_response(mock_ingest, mock_get_store, tmp_path):
    source = _source_file(tmp_path)
    mock_get_store.return_value = RebuildStore()
    mock_ingest.return_value = _ingest_result(chunks=486)

    with patch("app.routes.admin.knowledge_base.settings.kb_rebuild_document_paths", str(source)):
        response = client.post("/admin/kb/rebuild", headers=ADMIN_HEADERS)

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["message"] == "Knowledge base rebuilt successfully."
    assert data["collection"] == "aska_knowledge_base"
    assert data["documents_processed"] == 1
    assert data["chunks_created"] == 486
    assert data["categories"] == 2
    assert data["campuses"] == 2
    assert data["suspicious_units"] == 1
    assert data["toc_like_units"] == 2
    assert data["unique_categories"] == ["Academic Policies", "Technical Support"]
    assert data["unique_subcategories"] == ["Account Recovery", "Registration"]
    assert data["unique_offices"] == ["ICT Office", "Registrar"]
    assert data["unique_campuses"] == ["Siniloan", "Sta. Cruz"]


@patch("app.routes.admin.knowledge_base.settings.admin_api_key", "test-admin-key")
@patch("app.routes.admin.knowledge_base.get_knowledge_base_store")
@patch("app.routes.admin.knowledge_base.ingest_document_into_knowledge_base")
def test_admin_kb_rebuild_resets_before_indexing(mock_ingest, mock_get_store, tmp_path):
    events: list[str] = []
    source = _source_file(tmp_path)
    mock_get_store.return_value = RebuildStore(events)

    def ingest(*args, **kwargs):
        events.append("ingest")
        return _ingest_result(chunks=1)

    mock_ingest.side_effect = ingest

    with patch("app.routes.admin.knowledge_base.settings.kb_rebuild_document_paths", str(source)):
        response = client.post("/admin/kb/rebuild", headers=ADMIN_HEADERS)

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert events == ["reset", "ingest"]


@patch("app.routes.admin.knowledge_base.settings.admin_api_key", "test-admin-key")
@patch("app.routes.admin.knowledge_base.get_knowledge_base_store")
@patch("app.routes.admin.knowledge_base.ingest_document_into_knowledge_base")
def test_admin_kb_rebuild_reuses_existing_ingestion_pipeline(mock_ingest, mock_get_store, tmp_path):
    source = _source_file(tmp_path, "student_handbook.pdf")
    mock_get_store.return_value = RebuildStore()
    mock_ingest.return_value = _ingest_result(chunks=1)

    with patch("app.routes.admin.knowledge_base.settings.kb_rebuild_document_paths", str(source)):
        response = client.post("/admin/kb/rebuild", headers=ADMIN_HEADERS)

    assert response.status_code == 200
    mock_ingest.assert_called_once()
    call = mock_ingest.call_args
    assert call.args[0] == b"%PDF test handbook"
    assert call.kwargs["filename"] == "student_handbook.pdf"
    assert call.kwargs["content_type"] == "application/pdf"
    assert call.kwargs["title"] == "student_handbook"


@patch("app.routes.admin.knowledge_base.settings.admin_api_key", "test-admin-key")
@patch("app.routes.admin.knowledge_base.get_knowledge_base_store")
@patch("app.routes.admin.knowledge_base.ingest_document_into_knowledge_base")
def test_admin_kb_rebuild_failed_ingestion_returns_success_false(mock_ingest, mock_get_store, tmp_path):
    source = _source_file(tmp_path)
    mock_get_store.return_value = RebuildStore()
    mock_ingest.side_effect = RuntimeError("ingest exploded")

    with patch("app.routes.admin.knowledge_base.settings.kb_rebuild_document_paths", str(source)):
        response = client.post("/admin/kb/rebuild", headers=ADMIN_HEADERS)

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False
    assert data["stage"] == "ingest"
    assert data["reset_completed"] is True
    assert "ingest exploded" in data["error"]


@patch("app.routes.admin.knowledge_base.settings.admin_api_key", "test-admin-key")
def test_admin_kb_rebuild_requires_admin_authorization(tmp_path):
    source = _source_file(tmp_path)

    with patch("app.routes.admin.knowledge_base.settings.kb_rebuild_document_paths", str(source)):
        response = client.post("/admin/kb/rebuild")

    assert response.status_code == 401


@patch("app.routes.admin.knowledge_base.settings.admin_api_key", "test-admin-key")
@patch("app.routes.admin.knowledge_base.get_knowledge_base_store")
@patch("app.routes.admin.knowledge_base.ingest_document_into_knowledge_base")
def test_kb_articles_available_after_rebuild_with_test_fixture(mock_ingest, mock_get_store, monkeypatch, tmp_path):
    source = _source_file(tmp_path)
    store = RebuildStore()
    mock_get_store.return_value = store

    def ingest(*args, **kwargs):
        store.chunks.append(
            {
                "id": "doc::0",
                "text": "Students shall enroll during the official enrollment period.",
                "metadata": {
                    "document_id": "doc",
                    "title": "Student Handbook",
                    "source_filename": "handbook.pdf",
                    "category": "Academic Policies",
                    "subcategory": "Registration",
                    "responsible_office": "Registrar",
                    "page": 1,
                },
            }
        )
        return _ingest_result(chunks=1)

    mock_ingest.side_effect = ingest
    monkeypatch.setattr("app.routes.knowledge_base.get_knowledge_base_store", lambda: store)

    with patch("app.routes.admin.knowledge_base.settings.kb_rebuild_document_paths", str(source)):
        rebuild_response = client.post("/admin/kb/rebuild", headers=ADMIN_HEADERS)
    articles_response = client.get("/kb/articles")

    assert rebuild_response.status_code == 200
    assert rebuild_response.json()["success"] is True
    assert articles_response.status_code == 200
    assert articles_response.json()["total"] > 0
    assert articles_response.json()["items"][0]["category"] == "Academic Policies"
