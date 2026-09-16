"""Admin article create/update rejects blank title or body and persists nothing."""

from __future__ import annotations

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
    monkeypatch.setattr(
        "app.routes.admin.knowledge_base.settings.admin_api_key",
        "test-admin-key",
    )
    cleanup_all_published_articles()
    yield
    cleanup_all_published_articles()


def _count_articles() -> int:
    session = get_session_factory()()
    try:
        return session.query(PublishedArticle).count()
    finally:
        session.close()


def _post(title: str, content: str, **extra):
    return client.post(
        "/admin/kb/articles",
        headers=ADMIN_HEADERS,
        json={
            "title": title,
            "category": "Student Services",
            "content": content,
            "publish_status": False,
            "force_create": True,
            **extra,
        },
    )


def test_create_rejects_blank_title_or_body_without_persisting():
    cases = [
        {"title": "", "content": "Students request a certificate."},
        {"title": "   ", "content": "Students request a certificate."},
        {"title": "Good Moral Certificate", "content": ""},
        {"title": "Good Moral Certificate", "content": "   \n\t  "},
        {"title": "", "content": ""},
        {"title": "   ", "content": "   "},
        {
            "title": "Good Moral Certificate",
            "content": "<p> </p>",
            "content_format": "html",
        },
    ]
    for payload in cases:
        extra = {key: value for key, value in payload.items() if key not in {"title", "content"}}
        response = _post(payload["title"], payload["content"], **extra)
        assert response.status_code == 422, payload
        assert _count_articles() == 0


def test_create_accepts_image_only_html_draft():
    response = _post(
        "Lab map",
        '<p><img src="/kb/media/lab.png" alt="lab"></p>',
        content_format="html",
    )
    assert response.status_code == 200
    assert response.json()["published"] is False
    assert _count_articles() == 1


def test_create_accepts_valid_draft_and_trims_title():
    response = _post("  Good Moral Certificate  ", "Students request a certificate.")
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Good Moral Certificate"
    assert body["published"] is False
    assert body["content"] == "Students request a certificate."
    assert _count_articles() == 1


def test_update_rejects_blank_fields_and_keeps_the_saved_article():
    created = _post("Good Moral Certificate", "Students request a certificate.")
    assert created.status_code == 200
    article_id = created.json()["id"]

    blanks = [
        {"title": ""},
        {"title": "   "},
        {"content": ""},
        {"content": "  \n  "},
        {"content": "<p></p>", "content_format": "html"},
    ]
    for payload in blanks:
        response = client.patch(
            f"/admin/kb/articles/{article_id}",
            headers=ADMIN_HEADERS,
            json=payload,
        )
        assert response.status_code == 422, payload
        session = get_session_factory()()
        try:
            row = session.get(PublishedArticle, article_id)
            assert row is not None
            assert row.title == "Good Moral Certificate"
            assert row.content == "Students request a certificate."
        finally:
            session.close()

    updated = client.patch(
        f"/admin/kb/articles/{article_id}",
        headers=ADMIN_HEADERS,
        json={
            "title": "Updated Good Moral Certificate",
            "content": "Updated certificate instructions.",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["title"] == "Updated Good Moral Certificate"
    assert updated.json()["content"] == "Updated certificate instructions."
    assert updated.json()["published"] is False
