"""Tests for regenerate ↔ published_articles stable-key matching."""

from __future__ import annotations

from app.db.session import get_session_factory
from app.models.db_models import PublishedArticle
from app.services.admin.article_candidate_generator import (
    _annotate_existing_article_match,
    find_matching_published_article,
)
from tests.db_helpers import cleanup_published_articles_by_source


def _cleanup():
    cleanup_published_articles_by_source("citizen-charter-match.pdf")


def test_published_id_validation_matched_after_regenerate_keys():
    _cleanup()
    session = get_session_factory()()
    try:
        art = PublishedArticle(
            title="ID Validation",
            slug="id-validation",
            category="Student Services",
            source_filename="citizen-charter-match.pdf",
            content=(
                "Overview\nThis service provides assistance for ID Validation.\n\n"
                "----EXTRACTED METADATA----\n"
                '{"document_type":"citizen_charter","article_type":"service_procedure",'
                '"source_section":"ID Validation"}'
            ),
            published=True,
        )
        session.add(art)
        session.commit()
        article_id = art.id
    finally:
        session.close()

    session = get_session_factory()()
    try:
        match = find_matching_published_article(
            session,
            title="ID Validation",
            source_filename="citizen-charter-match.pdf",
            source_section="ID Validation",
            document_type="citizen_charter",
            article_type="service_procedure",
        )
        assert match is not None
        assert match.id == article_id
        assert match.published is True

        preview = _annotate_existing_article_match(
            {
                "title": "ID Validation",
                "source_filename": "citizen-charter-match.pdf",
                "source_section": "ID Validation",
                "document_type": "citizen_charter",
                "article_type": "service_procedure",
                "publish_allowed": True,
            },
            db=session,
        )
        assert preview["existing_article_id"] == article_id
        assert preview["existing_published"] is True
        assert preview["already_published"] is True
        assert preview["publish_allowed"] is False
        assert preview["publish_safety_state"] == "published"
    finally:
        session.close()
    _cleanup()


def test_charter_filename_basename_and_numbered_title_still_match():
    """Regenerate with path prefix / numbered title must still hit published row."""
    from app.services.admin.article_candidate_generator import (
        _apply_final_bucket,
        _preserve_published_match_flags,
    )

    _cleanup()
    session = get_session_factory()()
    try:
        session.add(
            PublishedArticle(
                title="ID Validation",
                slug="id-validation-basename",
                category="Student Services",
                source_filename="citizen-charter-match.pdf",
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
            title="4. ID Validation",
            source_filename=r"uploads\citizen-charter-match.pdf",
            source_section="ID Validation",
            document_type="citizen_charter",
            article_type="service_procedure",
        )
        assert match is not None
        preview = _annotate_existing_article_match(
            {
                "title": "4. ID Validation",
                "source_filename": r"uploads/citizen-charter-match.pdf",
                "source_section": "ID Validation",
                "document_type": "citizen_charter",
                "article_type": "service_procedure",
                "publish_allowed": True,
                "charter_candidate_bucket": "recommended",
            },
            db=session,
        )
        assert preview["already_published"] is True
        assert preview["publish_allowed"] is False
        _apply_final_bucket(preview, "recommended")
        assert preview["already_published"] is True
        assert preview["publish_allowed"] is False
        _preserve_published_match_flags(preview)
        assert preview["publish_safety_state"] == "published"
    finally:
        session.close()
    _cleanup()


def test_publish_all_skips_already_published_annotation():
    """Candidates annotated already_published must not stay publish_allowed."""
    _cleanup()
    session = get_session_factory()()
    try:
        session.add(
            PublishedArticle(
                title="Signing of Semestral Clearances",
                slug="signing-semestral",
                category="Student Services",
                source_filename="citizen-charter-match.pdf",
                content="Body\n\n----EXTRACTED METADATA----\n"
                '{"document_type":"citizen_charter","article_type":"service_procedure"}',
                published=True,
            )
        )
        session.commit()
    finally:
        session.close()

    session = get_session_factory()()
    try:
        preview = _annotate_existing_article_match(
            {
                "title": "Signing of Semestral Clearances",
                "source_filename": "citizen-charter-match.pdf",
                "document_type": "citizen_charter",
                "article_type": "service_procedure",
                "publish_allowed": True,
            },
            db=session,
        )
        assert preview["already_published"] is True
        assert preview["publish_allowed"] is False
    finally:
        session.close()
    _cleanup()
