import pytest
from fastapi.testclient import TestClient

from app.db.session import get_session_factory
from app.main import app
from app.models.db_models import PublishedArticle
from tests.db_helpers import cleanup_all_published_articles

client = TestClient(app)
ADMIN_HEADERS = {"x-admin-key": "test-admin-key"}


@pytest.fixture(autouse=True)
def _admin_key(monkeypatch):
    monkeypatch.setattr("app.routes.admin.knowledge_base.settings.admin_api_key", "test-admin-key")


def _cleanup_all():
    cleanup_all_published_articles()



def test_create_article_reports_similar_article_conflict():
    _cleanup_all()
    session = get_session_factory()()
    try:
        existing = PublishedArticle(
            title="Admission Requirements",
            slug="admission-requirements",
            category="Admissions",
            source_filename="handbook.pdf",
            content="Existing body",
            published=False,
        )
        session.add(existing)
        session.commit()
        existing_id = existing.id
    finally:
        session.close()

    response = client.post(
        "/admin/kb/articles",
        headers=ADMIN_HEADERS,
        json={
            "title": "Admission Requirements",
            "category": "Admissions",
            "source_document": "handbook.pdf",
            "summary": "Short summary",
            "content": "New body",
            "publish_status": False,
        },
    )
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "similar_article_exists"
    assert detail["existing"]["id"] == existing_id

    response = client.post(
        "/admin/kb/articles",
        headers=ADMIN_HEADERS,
        json={
            "title": "Admission Requirements",
            "category": "Admissions",
            "source_document": "handbook.pdf",
            "summary": "Updated summary",
            "content": "Updated body",
            "publish_status": False,
            "update_existing_id": existing_id,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == existing_id
    assert data["summary"] == "Updated summary"

    publish_response = client.post(
        "/admin/kb/articles",
        headers=ADMIN_HEADERS,
        json={
            "title": "Brand New Article",
            "category": "Admissions",
            "source_document": "handbook.pdf",
            "summary": "Summary",
            "content": "Body",
            "publish_status": True,
            "force_create": True,
        },
    )
    assert publish_response.status_code == 200
    assert publish_response.json()["published"] is True

    session = get_session_factory()()
    try:
        rows = session.query(PublishedArticle).all()
        assert len(rows) == 2
    finally:
        session.close()
    _cleanup_all()
