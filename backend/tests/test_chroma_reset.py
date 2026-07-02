import logging
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.services.chroma_store import KnowledgeBaseStore


client = TestClient(app)
ADMIN_HEADERS = {"X-Admin-Key": "test-admin-key"}


class FakeCollection:
    def __init__(self, count: int = 0, *, raises_on_count: bool = False) -> None:
        self._count = count
        self.raises_on_count = raises_on_count

    def count(self) -> int:
        if self.raises_on_count:
            raise RuntimeError("collection does not exist")
        return self._count


class FakeChromaClient:
    def __init__(self, *, delete_raises: Exception | None = None) -> None:
        self.delete_raises = delete_raises
        self.deleted_names: list[str] = []
        self.created_names: list[str] = []
        self.created_collection = FakeCollection(0)

    def delete_collection(self, *, name: str) -> None:
        self.deleted_names.append(name)
        if self.delete_raises is not None:
            raise self.delete_raises

    def get_or_create_collection(self, *, name: str, metadata: dict) -> FakeCollection:
        self.created_names.append(name)
        return self.created_collection


def _store(client: FakeChromaClient, collection: FakeCollection) -> KnowledgeBaseStore:
    store = object.__new__(KnowledgeBaseStore)
    store._client = client
    store._collection = collection
    return store


@patch("app.services.chroma_store.settings.chroma_collection_name", "test_collection")
def test_reset_collection_deletes_existing_collection(caplog):
    caplog.set_level(logging.INFO)
    fake_client = FakeChromaClient()
    store = _store(fake_client, FakeCollection(7))

    result = store.reset_collection()

    assert fake_client.deleted_names == ["test_collection"]
    assert result["collection"] == "test_collection"
    assert result["vectors_removed"] == 7
    assert "collection=test_collection" in caplog.text
    assert "vectors_removed=7" in caplog.text
    assert "timestamp=" in caplog.text


@patch("app.services.chroma_store.settings.chroma_collection_name", "missing_collection")
def test_reset_collection_ignores_missing_collection_delete_error():
    fake_client = FakeChromaClient(delete_raises=RuntimeError("Collection does not exist"))
    store = _store(fake_client, FakeCollection(raises_on_count=True))

    result = store.reset_collection()

    assert fake_client.deleted_names == ["missing_collection"]
    assert fake_client.created_names == ["missing_collection"]
    assert result["collection"] == "missing_collection"
    assert result["vectors_removed"] is None


@patch("app.services.chroma_store.settings.chroma_collection_name", "empty_collection")
def test_reset_collection_recreates_empty_collection():
    fake_client = FakeChromaClient()
    store = _store(fake_client, FakeCollection(3))

    store.reset_collection()

    assert store.chunk_count == 0
    assert store._collection is fake_client.created_collection


@patch("app.routes.admin.knowledge_base.settings.admin_api_key", "test-admin-key")
@patch("app.routes.admin.knowledge_base.get_knowledge_base_store")
def test_admin_chroma_reset_endpoint_success(mock_get_store):
    store = mock_get_store.return_value
    store.reset_collection.return_value = {
        "collection": "aska_knowledge_base",
        "vectors_removed": 12,
        "timestamp": "2026-06-28T00:00:00+00:00",
    }

    response = client.delete("/admin/chroma/reset", headers=ADMIN_HEADERS)

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "message": "Chroma knowledge base has been reset.",
        "collection": "aska_knowledge_base",
    }
    store.reset_collection.assert_called_once_with()


@patch("app.routes.admin.knowledge_base.settings.admin_api_key", "test-admin-key")
def test_kb_articles_empty_after_admin_chroma_reset(monkeypatch):
    class ResettableStore:
        chunk_count = 1

        def __init__(self) -> None:
            self.chunks = [
                {
                    "id": "doc::0",
                    "text": "Enrollment requires registration.",
                    "metadata": {
                        "title": "Handbook",
                        "category": "Academic Policies",
                        "subcategory": "Registration",
                    },
                }
            ]

        def reset_collection(self) -> dict:
            self.chunks = []
            self.chunk_count = 0
            return {
                "collection": "aska_knowledge_base",
                "vectors_removed": 1,
                "timestamp": "2026-06-28T00:00:00+00:00",
            }

        def list_chunks(self) -> list[dict]:
            return list(self.chunks)

    store = ResettableStore()
    monkeypatch.setattr("app.routes.admin.knowledge_base.get_knowledge_base_store", lambda: store)
    monkeypatch.setattr("app.routes.knowledge_base.get_knowledge_base_store", lambda: store)

    reset_response = client.delete("/admin/chroma/reset", headers=ADMIN_HEADERS)
    articles_response = client.get("/kb/articles")

    assert reset_response.status_code == 200
    assert articles_response.status_code == 200
    assert articles_response.json()["total"] == 0
    assert articles_response.json()["items"] == []
