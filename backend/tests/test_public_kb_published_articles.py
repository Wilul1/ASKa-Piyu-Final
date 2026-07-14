"""Public Knowledge Base serves PostgreSQL published_articles only."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.db.session import get_session_factory
from app.main import app
from app.models.db_models import PublishedArticle
from app.services.chroma_store import RetrievedChunk
from tests.db_helpers import cleanup_all_published_articles

client = TestClient(app)


@pytest.fixture(autouse=True)
def _cleanup_articles():
    cleanup_all_published_articles()
    yield
    cleanup_all_published_articles()


def _add_article(
    *,
    title: str,
    category: str,
    published: bool,
    summary: str = "Short summary",
    content: str = "Article body content",
    office: str | None = "Registrar",
    subcategory: str | None = None,
    source_filename: str | None = "handbook.pdf",
) -> str:
    session = get_session_factory()()
    try:
        article_id = str(uuid.uuid4())
        session.add(
            PublishedArticle(
                id=article_id,
                title=title,
                slug=title.lower().replace(" ", "-"),
                category=category,
                subcategory=subcategory,
                summary=summary,
                content=content,
                office=office,
                source_filename=source_filename,
                published=published,
            )
        )
        session.commit()
        return article_id
    finally:
        session.close()


def test_public_articles_return_only_published():
    published_id = _add_article(
        title="Excuse Slip Policy",
        category="Academic Policies",
        published=True,
        summary="How to request an excuse slip.",
        content="Students may request an excuse slip for valid absences.",
        subcategory="Attendance",
    )
    _add_article(
        title="Draft Excuse Slip",
        category="Academic Policies",
        published=False,
        summary="Draft only",
        content="This draft must not appear publicly.",
    )

    response = client.get("/kb/articles")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert item["id"] == f"pub:{published_id}"
    assert item["title"] == "Excuse Slip Policy"
    assert item["category"] == "Academic Policies"
    assert item["summary"] == "How to request an excuse slip."
    assert item["short_summary"] == "How to request an excuse slip."
    assert item["source_filename"] == "handbook.pdf"
    assert item["office"] == "Registrar"
    assert item["document_type"]
    assert "updated_at" in item
    assert item["id"].startswith("pub:")
    assert "handbook::" not in item["id"]
    assert item.get("chunk_id") in ("", None)


def test_public_articles_exclude_drafts():
    _add_article(title="Published Guide", category="Student Services", published=True)
    _add_article(title="Hidden Draft", category="Student Services", published=False)

    response = client.get("/kb/articles")

    titles = {item["title"] for item in response.json()["items"]}
    assert titles == {"Published Guide"}


def test_public_articles_do_not_return_chroma_chunks(monkeypatch):
    class FakeStore:
        def list_chunks(self):
            return [
                {
                    "id": "handbook::99",
                    "text": "Indexed chunk that must not appear on public KB.",
                    "metadata": {
                        "title": "Chunk Title",
                        "category": "Academic Policies",
                        "subcategory": "Attendance",
                        "source_filename": "handbook.pdf",
                    },
                }
            ]

        def search(self, query: str, *, top_k=None, raw_k=None):
            return [
                RetrievedChunk(
                    document_id="handbook",
                    title="Chunk Title",
                    source_filename="handbook.pdf",
                    chunk_index=99,
                    text="Indexed chunk that must not appear on public KB.",
                    relevance_score=0.99,
                    original_score=0.99,
                    reranked_score=0.99,
                    metadata={
                        "title": "Chunk Title",
                        "category": "Academic Policies",
                        "subcategory": "Attendance",
                    },
                )
            ]

        def get_chunk(self, chunk_id: str):
            return self.list_chunks()[0]

    monkeypatch.setattr(
        "app.routes.knowledge_base.get_knowledge_base_store",
        lambda: FakeStore(),
    )

    list_response = client.get("/kb/articles")
    search_response = client.get("/kb/articles", params={"q": "Indexed chunk"})
    detail_response = client.get("/kb/articles/handbook::99")
    categories_response = client.get("/kb/categories")

    assert list_response.status_code == 200
    assert list_response.json()["total"] == 0
    assert list_response.json()["items"] == []
    assert search_response.status_code == 200
    assert search_response.json()["items"] == []
    assert detail_response.status_code == 404
    assert categories_response.status_code == 200
    assert categories_response.json()["items"] == []


def test_public_article_detail_and_search():
    article_id = _add_article(
        title="Guidance Counseling",
        category="Student Services",
        published=True,
        summary="Counseling support for students.",
        content="Guidance counseling helps students with academic and personal concerns.",
        office="Guidance Office",
        subcategory="Guidance",
    )
    _add_article(
        title="Unpublished Counseling Notes",
        category="Student Services",
        published=False,
        content="Draft counseling notes",
    )

    search = client.get("/kb/articles", params={"q": "counseling"})
    assert search.status_code == 200
    assert search.json()["total"] == 1
    assert search.json()["items"][0]["title"] == "Guidance Counseling"

    office_search = client.get("/kb/articles", params={"q": "Guidance Office"})
    assert office_search.json()["total"] == 1

    detail = client.get(f"/kb/articles/pub:{article_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["title"] == "Guidance Counseling"
    assert "academic and personal concerns" in body["content"]
    assert body["metadata"]["published"] is True

    draft_detail = client.get("/kb/articles/pub:missing-id")
    assert draft_detail.status_code == 404


def test_public_article_title_is_not_replaced_by_category():
    article_id = _add_article(
        title="Retention Requirement",
        category="Academic Policies",
        published=True,
        summary="Rules for academic retention.",
        content="Students must meet retention requirements each semester.",
        subcategory="Retention",
    )

    response = client.get("/kb/articles")
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["id"] == f"pub:{article_id}"
    assert item["title"] == "Retention Requirement"
    assert item["category"] == "Academic Policies"
    assert item["title"] != item["category"]


def test_public_categories_group_published_only():
    _add_article(
        title="Excuse Slip",
        category="Academic Policies",
        published=True,
        subcategory="Attendance",
    )
    _add_article(
        title="Draft Policy",
        category="Academic Policies",
        published=False,
        subcategory="Attendance",
    )
    _add_article(
        title="Scholarship Grants",
        category="Scholarships & Financial Policies",
        published=True,
        subcategory="Grants",
    )

    response = client.get("/kb/categories")
    assert response.status_code == 200
    items = {item["name"]: item for item in response.json()["items"]}
    assert "Academic Policies" in items
    assert items["Academic Policies"]["article_count"] == 1
    assert "Scholarships & Financial Policies" in items
    assert items["Scholarships & Financial Policies"]["article_count"] == 1
