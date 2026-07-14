"""Regression: tests must not wipe development published_articles."""

from __future__ import annotations

import pytest
from sqlalchemy.engine import make_url

from app.config import settings
from app.db.safety import (
    UnsafeDatabaseOperationError,
    active_database_name,
    assert_destructive_database_ops_allowed,
    assert_test_environment_uses_test_database,
)
from app.db.session import get_engine, get_session_factory, initialize_database
from app.models.db_models import PublishedArticle
from app.services.admin.article_candidate_generator import generate_candidates_from_preview
from tests.db_helpers import cleanup_published_articles_by_source


MARKER_SOURCE = "dev-isolation-guard.pdf"
MARKER_TITLE = "Isolation Guard Published Article"


def test_pytest_uses_aska_piyu_test_not_aska_piyu():
    assert (settings.env or "").lower() == "test"
    assert active_database_name() == "aska_piyu_test"
    assert active_database_name() != "aska_piyu"
    assert make_url(settings.database_url).database == "aska_piyu_test"
    assert str(get_engine().url.database) == "aska_piyu_test"
    assert_test_environment_uses_test_database()


def test_destructive_ops_refuse_non_test_database(monkeypatch):
    monkeypatch.setattr(settings, "allow_destructive_reset", False)
    monkeypatch.setattr(
        settings,
        "database_url",
        "postgresql+psycopg://postgres:x@localhost:5432/aska_piyu",
    )
    with pytest.raises(UnsafeDatabaseOperationError, match="aska_piyu"):
        assert_destructive_database_ops_allowed()


def test_env_test_aborts_when_database_is_not_test(monkeypatch):
    monkeypatch.setattr(settings, "env", "test")
    monkeypatch.setattr(
        settings,
        "database_url",
        "postgresql+psycopg://postgres:x@localhost:5432/aska_piyu",
    )
    with pytest.raises(UnsafeDatabaseOperationError, match="aska_piyu"):
        assert_test_environment_uses_test_database()


def test_extract_generate_reset_preview_do_not_delete_published_articles():
    """
    Insert a published article, run generate/preview flows + create_all init,
    and confirm the row remains (these paths must never wipe published_articles).
    """
    cleanup_published_articles_by_source(MARKER_SOURCE)
    initialize_database()  # create_all only — must not truncate

    session = get_session_factory()()
    try:
        session.add(
            PublishedArticle(
                title=MARKER_TITLE,
                slug="isolation-guard-published-article",
                category="Student Services",
                summary="Must survive generate/extract/reset preview.",
                content="Body that must remain after admin preview flows.",
                source_filename=MARKER_SOURCE,
                published=True,
            )
        )
        session.commit()
        article_id = session.query(PublishedArticle).filter_by(title=MARKER_TITLE).one().id
    finally:
        session.close()

    preview = {
        "success": True,
        "filename": MARKER_SOURCE,
        "knowledge_units": [
            {
                "unit_index": 0,
                "title": "Unrelated Preview Unit",
                "content": (
                    "Students may request assistance for enrollment verification "
                    "through the registrar when documents are complete. " * 3
                ),
                "content_type": "document_chunk",
                "hierarchy_path": "Admissions > Preview",
                "word_count": 40,
                "status": "OK",
                "metadata": {
                    "office": "Registrar",
                    "section_heading": "Unrelated Preview Unit",
                    "document_type": "information",
                },
            }
        ],
        "structured": {"formatted_text": "Unrelated Preview Unit"},
    }
    result = generate_candidates_from_preview(
        preview,
        filename=MARKER_SOURCE,
        max_candidates=5,
        save_mode="preview_only",
    )
    assert isinstance(result, dict)

    # Startup-style init must remain non-destructive.
    initialize_database()

    session = get_session_factory()()
    try:
        row = session.get(PublishedArticle, article_id)
        assert row is not None
        assert row.title == MARKER_TITLE
        assert row.published is True
        assert row.source_filename == MARKER_SOURCE
    finally:
        session.close()

    cleanup_published_articles_by_source(MARKER_SOURCE)
