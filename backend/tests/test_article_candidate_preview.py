import pytest

from app.db.session import get_session_factory
from app.models.db_models import PublishedArticle
from app.services.admin.article_candidate_generator import generate_candidates_from_preview
from tests.db_helpers import cleanup_all_published_articles


@pytest.fixture(autouse=True)
def _deterministic_taxonomy_classification(monkeypatch):
    monkeypatch.setattr(
        "app.services.knowledge_taxonomy.settings.groq_api_key",
        None,
    )


def _cleanup_all():
    cleanup_all_published_articles()




def _sample_preview(title: str = "Admission Requirements") -> dict:
    return {
        "knowledge_units": [
            {
                "unit_index": 0,
                "title": title,
                "content": "Students must submit the following documents and complete the listed steps before enrollment. Requirements and procedure for admission." * 2,
                "content_type": "document_chunk",
                "hierarchy_path": "Admissions > Requirements",
                "word_count": 70,
                "status": "OK",
                "metadata": {
                    "office": "Registrar",
                    "section_heading": title,
                    "document_type": "information",
                },
            }
        ],
        "structured": {"formatted_text": title},
    }


def test_generate_preview_does_not_insert_rows():
    _cleanup_all()
    result = generate_candidates_from_preview(_sample_preview(), filename="sample.txt")
    assert result["save_mode"] == "preview_only"
    assert result["saved_count"] == 0
    assert result["preview_count"] >= 1
    preview_items = (
        result["recommended_candidates"]
        or result["overflow_candidates"]
        or result["needs_review_candidates"]
    )
    assert preview_items
    assert preview_items[0]["id"].startswith("preview-")
    assert result["recommended_candidates"][0]["is_preview"] is True

    session = get_session_factory()()
    try:
        rows = session.query(PublishedArticle).filter(
            PublishedArticle.source_filename == "sample.txt"
        ).all()
        assert rows == []
    finally:
        session.close()
    _cleanup_all()


def test_save_drafts_mode_still_persists_rows():
    _cleanup_all()
    result = generate_candidates_from_preview(
        _sample_preview(),
        filename="draft.txt",
        save_mode="save_drafts",
    )
    assert result["save_mode"] == "save_drafts"
    assert result["saved_count"] >= 1

    session = get_session_factory()()
    try:
        rows = session.query(PublishedArticle).filter(
            PublishedArticle.source_filename == "draft.txt"
        ).all()
        assert len(rows) >= 1
        assert all(row.published is False for row in rows)
    finally:
        session.close()
    _cleanup_all()


def test_preview_generation_does_not_skip_existing_duplicates():
    _cleanup_all()
    session = get_session_factory()()
    try:
        session.add(
            PublishedArticle(
                title="Registrar Office Hours",
                slug="registrar-office-hours",
                category="General Information",
                source_filename="sample.txt",
                content="Existing draft",
                published=False,
            )
        )
        session.commit()
    finally:
        session.close()

    result = generate_candidates_from_preview(_sample_preview(), filename="sample.txt")
    assert result["skipped_duplicate_count"] == 0
    assert result["preview_count"] >= 1

    session = get_session_factory()()
    try:
        rows = session.query(PublishedArticle).filter(
            PublishedArticle.source_filename == "sample.txt"
        ).all()
        assert len(rows) == 1
    finally:
        session.close()
    _cleanup_all()
