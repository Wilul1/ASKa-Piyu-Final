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
@patch("app.routes.admin.knowledge_base.settings.admin_api_key", "test-admin-key")
@patch(
    "app.routes.admin.knowledge_base._reingest_configured_documents_after_reset",
    return_value={
        "skipped": False,
        "documents_reingested": 1,
        "document_reingest_failed": 0,
        "document_reingest_errors": [],
    },
)
@patch(
    "app.services.article_rag_indexer.reindex_published_faq_articles",
    return_value={
        "faq_reindexed": 2,
        "faq_reindex_failed": 0,
        "faq_reindex_errors": [],
        "published_article_count": 2,
    },
)
@patch("app.services.article_rag_indexer.clear_all_article_rag_flags", return_value=3)
@patch("app.routes.admin.knowledge_base.get_session_factory")
@patch("app.routes.admin.knowledge_base.get_knowledge_base_store")
def test_admin_chroma_reset_endpoint_success(
    mock_get_store,
    mock_get_session_factory,
    mock_clear_flags,
    mock_reindex,
    mock_reingest,
):
    store = mock_get_store.return_value
    store.reset_collection.return_value = {
        "collection": "aska_knowledge_base",
        "vectors_removed": 12,
        "timestamp": "2026-06-28T00:00:00+00:00",
    }
    session = mock_get_session_factory.return_value.return_value

    response = client.delete("/admin/chroma/reset", headers=ADMIN_HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["collection"] == "aska_knowledge_base"
    assert body["articles_rag_flags_cleared"] == 3
    assert body["documents_reingested"] == 1
    assert body["faq_reindexed"] == 2
    assert body["faq_reindex_failed"] == 0
    store.reset_collection.assert_called_once_with()
    mock_clear_flags.assert_called_once_with(session)
    mock_reindex.assert_called_once_with(session)
    mock_reingest.assert_called_once_with()
    session.commit.assert_called_once()


@patch("app.routes.admin.knowledge_base.settings.admin_api_key", "test-admin-key")
def test_admin_chroma_reset_clears_flags_and_reindexes_faqs(monkeypatch):
    """Empty rebuild paths refuse wipe; FAQ-only path clears flags and reindexes."""

    class ResettableStore:
        def __init__(self) -> None:
            self.reset_calls = 0

        def reset_collection(self) -> dict:
            self.reset_calls += 1
            return {
                "collection": "aska_knowledge_base",
                "vectors_removed": 1,
                "timestamp": "2026-06-28T00:00:00+00:00",
            }

    cleared = {"count": 0}
    reindexed = {"count": 0}
    store = ResettableStore()

    def _clear(session):
        cleared["count"] += 1
        return 2

    def _reindex(session):
        reindexed["count"] += 1
        return {
            "faq_reindexed": 2,
            "faq_reindex_failed": 0,
            "faq_reindex_errors": [],
            "published_article_count": 2,
        }

    class _Session:
        def commit(self):
            return None

        def rollback(self):
            return None

        def close(self):
            return None

    monkeypatch.setattr(
        "app.routes.admin.knowledge_base.get_knowledge_base_store",
        lambda: store,
    )
    monkeypatch.setattr(
        "app.routes.admin.knowledge_base.get_session_factory",
        lambda: (lambda: _Session()),
    )
    monkeypatch.setattr(
        "app.services.article_rag_indexer.clear_all_article_rag_flags",
        _clear,
    )
    monkeypatch.setattr(
        "app.services.article_rag_indexer.reindex_published_faq_articles",
        _reindex,
    )
    monkeypatch.setattr(
        "app.routes.admin.knowledge_base._configured_rebuild_document_paths",
        lambda: [],
    )
    monkeypatch.setattr(
        "app.routes.admin.knowledge_base._reingest_configured_documents_after_reset",
        lambda: {
            "skipped": True,
            "documents_reingested": 0,
            "document_reingest_failed": 0,
            "document_reingest_errors": [],
        },
    )

    reset_response = client.delete("/admin/chroma/reset", headers=ADMIN_HEADERS)
    # Empty ASKA_KB_REBUILD_DOCUMENT_PATHS must fail BEFORE wiping Chroma.
    assert reset_response.status_code == 400
    assert "ASKA_KB_REBUILD_DOCUMENT_PATHS" in reset_response.json()["detail"]
    assert store.reset_calls == 0
    assert cleared["count"] == 0
    assert reindexed["count"] == 0

    faq_only = client.delete(
        "/admin/chroma/reset?allow_skip_documents=true",
        headers=ADMIN_HEADERS,
    )
    assert faq_only.status_code == 200
    assert faq_only.json()["success"] is True
    assert faq_only.json()["document_reingest_skipped"] is True
    assert store.reset_calls == 1
    assert cleared["count"] == 1
    assert reindexed["count"] == 1

    # Public browse is Postgres published_articles, not Chroma — reset must not 500.
    articles_response = client.get("/kb/articles")
    assert articles_response.status_code == 200
