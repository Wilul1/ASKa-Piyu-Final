"""Bulk save-draft / publish for Generate Articles candidates."""

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




def test_bulk_publish_recommended_and_block_unsafe_buckets():
    _cleanup_all()
    response = client.post(
        "/admin/kb/articles/bulk-publish",
        headers=ADMIN_HEADERS,
        json={
            "articles": [
                {
                    "preview_id": "preview-1",
                    "title": "Retention Requirement",
                    "category": "Academic Policies",
                    "summary": "Students must meet retention rules.",
                    "content": "Retention body",
                    "source_document": "handbook.pdf",
                    "planner_bucket": "recommended",
                    "needs_review": False,
                },
                {
                    "preview_id": "preview-2",
                    "title": "Needs Review Topic",
                    "category": "Academic Policies",
                    "summary": "Review me",
                    "content": "Review body",
                    "planner_bucket": "needs_review",
                    "needs_review": True,
                },
                {
                    "preview_id": "preview-3",
                    "title": "Low Quality Topic",
                    "category": "Academic Policies",
                    "summary": "Cleanup",
                    "content": "Low body",
                    "planner_bucket": "low_quality",
                },
                {
                    "preview_id": "preview-4",
                    "title": "RAG Only Topic",
                    "category": "Academic Policies",
                    "summary": "RAG",
                    "content": "RAG body",
                    "planner_bucket": "rag_only",
                },
            ]
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success_count"] == 1
    assert data["failure_count"] == 3
    by_preview = {item["preview_id"]: item for item in data["results"]}
    assert by_preview["preview-1"]["success"] is True
    assert by_preview["preview-1"]["published"] is True
    assert by_preview["preview-2"]["success"] is False
    assert by_preview["preview-2"]["code"] == "bucket_not_allowed"
    assert by_preview["preview-3"]["code"] == "bucket_not_allowed"
    assert by_preview["preview-4"]["code"] == "bucket_not_allowed"

    session = get_session_factory()()
    try:
        rows = session.query(PublishedArticle).all()
        assert len(rows) == 1
        assert rows[0].published is True
        assert rows[0].title == "Retention Requirement"
    finally:
        session.close()


def test_bulk_save_draft_allows_needs_review_blocks_low_quality():
    _cleanup_all()
    response = client.post(
        "/admin/kb/articles/bulk-save-draft",
        headers=ADMIN_HEADERS,
        json={
            "articles": [
                {
                    "preview_id": "preview-a",
                    "title": "Draft Recommended",
                    "category": "Student Services",
                    "summary": "Summary A",
                    "content": "Body A",
                    "planner_bucket": "recommended",
                },
                {
                    "preview_id": "preview-b",
                    "title": "Draft Needs Review",
                    "category": "Student Services",
                    "summary": "Summary B",
                    "content": "Body B",
                    "planner_bucket": "needs_review",
                    "needs_review": True,
                },
                {
                    "preview_id": "preview-c",
                    "title": "Draft Low Quality",
                    "category": "Student Services",
                    "summary": "Summary C",
                    "content": "Body C",
                    "planner_bucket": "low_quality",
                },
            ]
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success_count"] == 2
    assert data["failure_count"] == 1
    successes = [item for item in data["results"] if item["success"]]
    assert all(item["published"] is False for item in successes)

    session = get_session_factory()()
    try:
        rows = session.query(PublishedArticle).all()
        assert len(rows) == 2
        assert all(row.published is False for row in rows)
    finally:
        session.close()

    public = client.get("/kb/articles")
    assert public.status_code == 200
    payload = public.json()
    articles = payload if isinstance(payload, list) else payload.get("articles", [])
    titles = {item.get("title") for item in articles if isinstance(item, dict)}
    assert "Draft Recommended" not in titles
    assert "Draft Needs Review" not in titles


def test_bulk_publish_reports_duplicate_without_failing_batch():
    _cleanup_all()
    session = get_session_factory()()
    try:
        session.add(
            PublishedArticle(
                title="Attendance Policy",
                slug="attendance-policy",
                category="Academic Policies",
                source_filename="handbook.pdf",
                content="Existing",
                published=False,
            )
        )
        session.commit()
    finally:
        session.close()

    response = client.post(
        "/admin/kb/articles/bulk-publish",
        headers=ADMIN_HEADERS,
        json={
            "articles": [
                {
                    "preview_id": "dup",
                    "title": "Attendance Policy",
                    "category": "Academic Policies",
                    "source_document": "handbook.pdf",
                    "summary": "Dup",
                    "content": "Dup body",
                    "planner_bucket": "recommended",
                },
                {
                    "preview_id": "ok",
                    "title": "Excuse Slip",
                    "category": "Academic Policies",
                    "source_document": "handbook.pdf",
                    "summary": "Excuse",
                    "content": "Excuse body",
                    "planner_bucket": "recommended",
                },
            ]
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success_count"] == 1
    assert data["failure_count"] == 1
    by_preview = {item["preview_id"]: item for item in data["results"]}
    assert by_preview["dup"]["code"] == "similar_article_exists"
    assert by_preview["ok"]["success"] is True
    assert by_preview["ok"]["published"] is True


def test_bulk_unpublish_keeps_rows_as_drafts_and_hides_from_public_kb():
    _cleanup_all()
    session = get_session_factory()()
    try:
        first = PublishedArticle(
            title="Public Retention",
            slug="public-retention",
            category="Academic Policies",
            source_filename="student-handbook.pdf",
            content="Retention body",
            published=True,
        )
        second = PublishedArticle(
            title="Public Attendance",
            slug="public-attendance",
            category="Academic Policies",
            source_filename="student-handbook.pdf",
            content="Attendance body",
            published=True,
        )
        session.add_all([first, second])
        session.commit()
        first_id = first.id
        second_id = second.id
    finally:
        session.close()

    public_before = client.get("/kb/articles")
    assert public_before.status_code == 200
    before_payload = public_before.json()
    before_articles = (
        before_payload if isinstance(before_payload, list) else before_payload.get("items", [])
    )
    before_titles = {item.get("title") for item in before_articles if isinstance(item, dict)}
    assert "Public Retention" in before_titles
    assert "Public Attendance" in before_titles

    response = client.post(
        "/admin/kb/articles/bulk-unpublish",
        headers=ADMIN_HEADERS,
        json={"article_ids": [first_id, second_id]},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success_count"] == 2
    assert data["failure_count"] == 0
    assert all(item["published"] is False for item in data["results"])

    session = get_session_factory()()
    try:
        rows = session.query(PublishedArticle).order_by(PublishedArticle.title).all()
        assert len(rows) == 2
        assert all(row.published is False for row in rows)
    finally:
        session.close()

    public_after = client.get("/kb/articles")
    assert public_after.status_code == 200
    after_payload = public_after.json()
    after_articles = (
        after_payload if isinstance(after_payload, list) else after_payload.get("items", [])
    )
    after_titles = {item.get("title") for item in after_articles if isinstance(item, dict)}
    assert "Public Retention" not in after_titles
    assert "Public Attendance" not in after_titles

    admin_list = client.get("/admin/kb/articles", headers=ADMIN_HEADERS)
    assert admin_list.status_code == 200
    admin_titles = {item["title"] for item in admin_list.json()}
    assert "Public Retention" in admin_titles
    assert "Public Attendance" in admin_titles


def test_bulk_save_draft_does_not_unpublish_existing_public_articles():
    _cleanup_all()
    session = get_session_factory()()
    try:
        art = PublishedArticle(
            title="Already Public Service",
            slug="already-public-service",
            category="Student Services",
            source_filename="charter.pdf",
            content="Public body",
            published=True,
        )
        session.add(art)
        session.commit()
        article_id = art.id
    finally:
        session.close()

    response = client.post(
        "/admin/kb/articles/bulk-save-draft",
        headers=ADMIN_HEADERS,
        json={
            "articles": [
                {
                    "preview_id": "preview-published",
                    "existing_article_id": article_id,
                    "title": "Already Public Service",
                    "category": "Student Services",
                    "summary": "Should stay published",
                    "content": "Updated draft attempt",
                    "source_document": "charter.pdf",
                    "planner_bucket": "recommended",
                    "needs_review": False,
                }
            ]
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success_count"] == 0
    assert data["failure_count"] == 1
    assert data["results"][0]["code"] == "already_published"
    assert data["results"][0]["published"] is True

    session = get_session_factory()()
    try:
        row = session.get(PublishedArticle, article_id)
        assert row is not None
        assert row.published is True
        assert row.content == "Public body"
    finally:
        session.close()

    public = client.get("/kb/articles")
    assert public.status_code == 200
    payload = public.json()
    articles = payload if isinstance(payload, list) else payload.get("items", [])
    titles = {item.get("title") for item in articles if isinstance(item, dict)}
    assert "Already Public Service" in titles


def test_create_update_existing_refuses_silent_unpublish():
    _cleanup_all()
    session = get_session_factory()()
    try:
        art = PublishedArticle(
            title="Keep Public",
            slug="keep-public",
            category="Admissions",
            source_filename="handbook.pdf",
            content="Keep me",
            published=True,
        )
        session.add(art)
        session.commit()
        article_id = art.id
    finally:
        session.close()

    response = client.post(
        "/admin/kb/articles",
        headers=ADMIN_HEADERS,
        json={
            "title": "Keep Public",
            "category": "Admissions",
            "summary": "Edited",
            "content": "Edited body",
            "source_document": "handbook.pdf",
            "publish_status": False,
            "update_existing_id": article_id,
        },
    )
    assert response.status_code == 409

    session = get_session_factory()()
    try:
        row = session.get(PublishedArticle, article_id)
        assert row is not None
        assert row.published is True
        assert row.content == "Keep me"
    finally:
        session.close()
