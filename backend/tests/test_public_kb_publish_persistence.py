"""Persistence + priority card visibility for Generate Articles / Public KB."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db.session import get_session_factory
from app.main import app
from app.models.db_models import PublishedArticle
from app.services.admin.article_candidate_generator import (
    _candidate_from_unit,
    _ensure_public_priority_candidates_visible,
    find_matching_published_article,
)
from tests.db_helpers import cleanup_published_articles_by_source

client = TestClient(app)
ADMIN_HEADERS = {"x-admin-key": "test-admin-key"}


@pytest.fixture(autouse=True)
def _admin_key(monkeypatch):
    monkeypatch.setattr(
        "app.routes.admin.knowledge_base.settings.admin_api_key", "test-admin-key"
    )


def _cleanup(filename: str = "citizen-charter-persist.pdf"):
    cleanup_published_articles_by_source(filename)


def test_charter_unit_keeps_extracted_office_without_alias_match():
    unit = {
        "title": "ID Validation",
        "content": "Office / Division\nOSAS",
        "hierarchy_path": "ID Validation",
        "metadata": {
            "parser_document_type": "citizen_charter",
            "source_type": "Citizen's Charter",
            "office": "OSAS",
            "extracted_office": "OSAS",
            "office_division": "OSAS",
            "who_may_avail": "All",
            "charter_candidate_bucket": "recommended",
        },
        "parser_document_type": "citizen_charter",
        "source_type": "Citizen's Charter",
    }
    cand = _candidate_from_unit(unit, filename="citizen-charter-persist.pdf")
    assert cand["office"] == "OSAS"
    assert cand["extracted_office"] == "OSAS"


def test_priority_diagnostics_inject_missing_cards():
    working = {
        "source_filename": "citizen-charter-persist.pdf",
        "_charter_rescue_summary": {
            "priority_service_diagnostics": [
                {
                    "title": "Library Circulation Service",
                    "found": True,
                    "final_bucket": "needs_review",
                }
            ]
        },
        "_charter_rescue_results": [
            {
                "title": "Library Circulation Service",
                "content": (
                    "Overview\nLibrary Circulation Service\n\n"
                    "Office / Division\nUniversity Library"
                ),
                "audience": "student_facing",
                "category": "Library Services",
                "original_bucket": "needs_review",
                "repaired_bucket": "needs_review",
                "rescue_attempted": True,
                "rescue_successful": False,
                "rescue_reasons": [],
                "repair_actions_applied": [],
                "remaining_blockers": ["body_has_not_specified_or_needs_review"],
                "needs_review_reasons": ["body_has_not_specified_or_needs_review"],
                "service_fields": {
                    "office": "University Library",
                    "who_may_avail": "Students",
                    "requirements": [],
                    "steps": [],
                    "checklist_blank": True,
                },
                "service": {"parser_debug": {}},
            }
        ],
    }
    out = _ensure_public_priority_candidates_visible(
        all_candidates=[],
        working_preview=working,
        filename="citizen-charter-persist.pdf",
        db=None,
    )
    assert len(out) == 1
    assert out[0]["title"] == "Library Circulation Service"
    assert out[0]["final_bucket"] == "needs_review"


def test_published_match_section_title_without_filename():
    _cleanup()
    session = get_session_factory()()
    try:
        session.add(
            PublishedArticle(
                title="ID Validation",
                slug="id-validation-persist",
                category="Student Services",
                source_filename="old-name.pdf",
                content=(
                    "Body\n\n----EXTRACTED METADATA----\n"
                    '{"document_type":"citizen_charter","article_type":"service_procedure",'
                    '"source_section":"ID Validation"}'
                ),
                published=True,
            )
        )
        session.commit()
    finally:
        session.close()

    session = get_session_factory()()
    try:
        match = find_matching_published_article(
            session,
            title="ID Validation",
            source_filename="citizen-charter-persist.pdf",
            source_section="ID Validation",
            document_type="citizen_charter",
            article_type="service_procedure",
        )
        assert match is not None
        assert match.title == "ID Validation"
        assert match.published is True
    finally:
        session.close()
    _cleanup("old-name.pdf")
    _cleanup()


def test_publish_writes_published_true_visible_on_public_kb():
    _cleanup()
    create = client.post(
        "/admin/kb/articles",
        headers=ADMIN_HEADERS,
        json={
            "title": "ID Validation",
            "category": "Student Services",
            "summary": "Validate ID.",
            "content": (
                "Overview\nID Validation\n\n----EXTRACTED METADATA----\n"
                '{"document_type":"citizen_charter","article_type":"service_procedure",'
                '"source_section":"ID Validation"}'
            ),
            "source_document": "citizen-charter-persist.pdf",
            "publish_status": True,
            "force_create": True,
        },
    )
    assert create.status_code == 200, create.text
    data = create.json()
    assert data["published"] is True
    assert data["persistence_table"] == "published_articles"
    assert data["persistence_debug"]["published"] is True
    article_id = data["id"]

    public = client.get("/kb/articles?limit=48")
    assert public.status_code == 200
    titles = [item["title"] for item in public.json()["items"]]
    assert "ID Validation" in titles

    categories = client.get("/kb/categories")
    assert categories.status_code == 200
    assert categories.json()["published_article_count"] >= 1

    session = get_session_factory()()
    try:
        match = find_matching_published_article(
            session,
            title="ID Validation",
            source_filename="citizen-charter-persist.pdf",
            source_section="ID Validation",
            document_type="citizen_charter",
            article_type="service_procedure",
        )
        assert match is not None
        assert match.id == article_id
        assert match.published is True
    finally:
        session.close()
    _cleanup()
