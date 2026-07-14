import pytest

from app.services.admin.article_candidate_generator import generate_candidates_from_preview
from app.db.session import get_session_factory
from app.models.db_models import PublishedArticle
from tests.db_helpers import cleanup_all_published_articles


@pytest.fixture(autouse=True)
def _deterministic_taxonomy_classification(monkeypatch):
    monkeypatch.setattr(
        "app.services.knowledge_taxonomy.settings.groq_api_key",
        None,
    )


def _cleanup_all():
    cleanup_all_published_articles()




def test_information_section_generates_preview_only_by_default():
    _cleanup_all()
    preview = {
        "knowledge_units": [
            {
                "unit_index": 0,
                "title": "Registrar Office Hours",
                "content": "The registrar office is open from 8am to 5pm. Walk-in services available.",
                "content_type": "document_chunk",
                "hierarchy_path": "Office > Registrar",
                "word_count": 20,
                "status": "OK",
                "metadata": {"office": "Registrar", "section_heading": "Office Hours", "document_type": "information"},
            }
        ],
        "structured": {"formatted_text": "Registrar Office Hours"},
    }

    result = generate_candidates_from_preview(preview, filename="sample.txt")
    assert isinstance(result, dict)
    assert result.get("saved_count") == 0
    assert result.get("preview_count", 0) >= 0
    session = get_session_factory()()
    try:
        rows = session.query(PublishedArticle).filter(PublishedArticle.source_filename == "sample.txt").all()
        assert rows == []
    finally:
        session.close()
    _cleanup_all()


def test_duplicate_candidates_are_skipped_only_when_saving_drafts():
    _cleanup_all()
    preview = {
        "knowledge_units": [
            {
                "unit_index": 0,
                "title": "Form A",
                "content": (
                    "Content A is long enough to be saved as a draft article candidate. "
                    "Students must submit the form requirements and follow the procedure steps. "
                )
                * 4,
                "content_type": "document_chunk",
                "hierarchy_path": "Forms > A",
                "word_count": 50,
                "status": "OK",
                "metadata": {"document_type": "form"},
            },
        ],
        "structured": {"formatted_text": "Form A"},
    }
    first = generate_candidates_from_preview(preview, filename="form.pdf", save_mode="save_drafts")
    second = generate_candidates_from_preview(preview, filename="form.pdf", save_mode="save_drafts")
    assert isinstance(first, dict)
    assert isinstance(second, dict)
    assert first["saved_count"] >= 1
    assert second.get("skipped_duplicate_count", 0) >= 1
    _cleanup_all()
