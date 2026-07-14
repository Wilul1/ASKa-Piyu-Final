"""Low Quality → manual review draft workflow (no direct publish)."""

import json

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




def test_low_quality_direct_publish_is_blocked():
    _cleanup_all()
    body = (
        "Office / Division\nUniversity Clinic\n\n"
        "Who May Avail\nStudents\n\n"
        "----EXTRACTED METADATA----\n"
        + json.dumps(
            {
                "planner_bucket": "low_quality",
                "source_section": "Health > Clinic",
                "document_type": "citizen_charter",
                "article_type": "procedure",
            },
            indent=2,
        )
    )
    response = client.post(
        "/admin/kb/articles",
        headers=ADMIN_HEADERS,
        json={
            "title": "Routine Medical Services",
            "category": "Student Services",
            "summary": "Clinic services",
            "content": body,
            "source_document": "citizens_charter.pdf",
            "source_section": "Health > Clinic",
            "document_type": "citizen_charter",
            "planner_bucket": "low_quality",
            "publish_status": True,
            "force_create": True,
        },
    )
    assert response.status_code == 400
    assert "cannot be published directly" in response.json()["detail"].lower()

    session = get_session_factory()()
    try:
        assert session.query(PublishedArticle).count() == 0
    finally:
        session.close()


def test_low_quality_can_save_as_draft_after_manual_edit():
    _cleanup_all()
    corrected = (
        "Overview\nRoutine medical and dental services for students.\n\n"
        "Office / Division\nUniversity Clinic\n\n"
        "Who May Avail\nBonafide students\n\n"
        "Requirements\n- Valid school ID\n\n"
        "Steps\n"
        "1. Client Step: Present ID at the clinic\n"
        "   Agency Action: Verify records\n"
        "   Fees: None\n"
        "   Processing Time: 15 minutes\n"
        "   Person Responsible: Clinic staff\n\n"
        "----EXTRACTED METADATA----\n"
        + json.dumps(
            {
                "planner_bucket": "needs_review",
                "final_bucket": "needs_review",
                "manual_review_from_low_quality": True,
                "original_bucket": "low_quality",
                "review_status": "manually_corrected_draft",
                "needs_review": True,
                "source_section": "Health > Clinic",
                "document_type": "citizen_charter",
                "article_type": "procedure",
                "source_filename": "citizens_charter.pdf",
            },
            indent=2,
        )
    )
    response = client.post(
        "/admin/kb/articles",
        headers=ADMIN_HEADERS,
        json={
            "title": "Routine Medical Services",
            "category": "Student Services",
            "summary": "Clinic walk-in services.",
            "content": corrected,
            "office": "University Clinic",
            "source_document": "citizens_charter.pdf",
            "source_section": "Health > Clinic",
            "document_type": "citizen_charter",
            "planner_bucket": "needs_review",
            "needs_review": True,
            "publish_status": False,
            "force_create": True,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["published"] is False
    assert data["source_filename"] == "citizens_charter.pdf"
    assert data["source_section"] == "Health > Clinic"
    assert data["document_type"] == "citizen_charter"
    assert data["article_type"] == "procedure"
    content = data["content"] or ""
    assert "manual_review_from_low_quality" in content
    assert "manually_corrected_draft" in content
    assert '"original_bucket": "low_quality"' in content or '"original_bucket":"low_quality"' in content.replace(
        " ", ""
    )

    # Still cannot publish while placeholders remain in a low_quality-tagged body.
    dirty = client.post(
        "/admin/kb/articles",
        headers=ADMIN_HEADERS,
        json={
            "title": "Dirty Low Quality",
            "category": "Student Services",
            "summary": "Needs cleanup",
            "content": "Office\nNot specified\n\n----EXTRACTED METADATA----\n"
            + json.dumps({"planner_bucket": "low_quality"}),
            "planner_bucket": "low_quality",
            "publish_status": True,
            "force_create": True,
        },
    )
    assert dirty.status_code == 400

    # After clean draft save, publish from draft/review is allowed.
    article_id = data["id"]
    publish = client.post(
        f"/admin/kb/articles/{article_id}/publish",
        headers=ADMIN_HEADERS,
    )
    assert publish.status_code == 200
    assert publish.json()["published"] is True

    public = client.get("/kb/articles")
    assert public.status_code == 200
    titles = [item.get("title") for item in public.json().get("items", public.json().get("articles", []))]
    # Public list shape may vary; assert draft row is now published in DB.
    session = get_session_factory()()
    try:
        row = session.get(PublishedArticle, article_id)
        assert row is not None
        assert row.published is True
    finally:
        session.close()


def test_bulk_publish_all_recommended_excludes_low_quality():
    _cleanup_all()
    response = client.post(
        "/admin/kb/articles/bulk-publish",
        headers=ADMIN_HEADERS,
        json={
            "articles": [
                {
                    "preview_id": "lq-1",
                    "title": "LQ Service",
                    "category": "Student Services",
                    "summary": "Cleanup",
                    "content": "Clean body without placeholders",
                    "planner_bucket": "low_quality",
                }
            ]
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success_count"] == 0
    assert data["failure_count"] == 1
    assert data["results"][0]["code"] == "bucket_not_allowed"
