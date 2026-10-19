"""Citation -> public Knowledge Base article linking (kb_article_id).

Covers the fix for: chatbot citations for published FAQ articles previously
only ever resolved to an (often unrelated, or entirely missing) source PDF,
never to the public `/kb/articles/{id}` page the student could otherwise
browse to. See app.services.article_rag_indexer.gate_kb_article_citations
and question_answering._citation_fields's "kb_article_id" field.
"""

from __future__ import annotations

import uuid

from app.db.session import get_session_factory, initialize_database
from app.models.db_models import PublishedArticle
from app.models.schemas import QACitationSchema, QASourceSchema
from app.services.chroma_store import RetrievedChunk
from app.services.qa.question_answering import _citations_from_sources, _sources_from_chunks
from tests.db_helpers import cleanup_all_published_articles


def _faq_chunk(article_id: str, *, chunk_index: int = 0) -> RetrievedChunk:
    """A FAQ-origin chunk exactly as article_rag_indexer._build_faq_chunks
    stamps it: document_id == faq_document_id(article_id), metadata carries
    article_id/article_type, and source_filename is the synthetic
    "Ticket FAQ (...)" placeholder (no real PDF -- the ticket-resolution-
    origin case where, before this fix, the citation had no link at all).
    """
    return RetrievedChunk(
        document_id=f"faq:{article_id}",
        title="ID Validation FAQ",
        source_filename=f"Ticket FAQ ({article_id})",
        chunk_index=chunk_index,
        text="Present your school ID at the registrar's window to validate it.",
        relevance_score=0.9,
        metadata={
            "document_id": f"faq:{article_id}",
            "article_id": article_id,
            "article_type": "faq",
            "source_section": "ID Validation FAQ",
            "chunk_id": f"faq:{article_id}::{chunk_index}",
        },
    )


def _make_article(*, published: bool, audience: str) -> str:
    """Creates one PublishedArticle row and returns its id."""
    session = get_session_factory()()
    try:
        article = PublishedArticle(
            title="ID Validation FAQ",
            slug=f"id-validation-faq-{uuid.uuid4().hex[:10]}",
            category="Student Services",
            summary="How to validate your school ID.",
            content="Present your school ID at the registrar's window to validate it.",
            audience=audience,
            published=published,
        )
        session.add(article)
        session.commit()
        session.refresh(article)
        return article.id
    finally:
        session.close()


def setup_function(_fn):
    initialize_database()
    cleanup_all_published_articles()


def teardown_function(_fn):
    cleanup_all_published_articles()


def test_faq_citation_includes_kb_article_id_when_published_and_student_visible():
    article_id = _make_article(published=True, audience="student")

    sources = _sources_from_chunks([_faq_chunk(article_id)], user_role="student")
    assert len(sources) == 1
    assert sources[0]["kb_article_id"] == article_id
    # The existing PDF fields stay absent/false for a ticket-resolution FAQ
    # with no real source document -- this fix adds a link, it doesn't
    # fabricate a PDF.
    assert sources[0]["pdf_available"] is False
    assert sources[0]["source_view_url"] is None

    citations = _citations_from_sources(sources)
    assert citations[0]["kb_article_id"] == article_id


def test_faq_citation_includes_kb_article_id_when_audience_is_both():
    article_id = _make_article(published=True, audience="both")

    sources = _sources_from_chunks([_faq_chunk(article_id)], user_role="faculty")
    assert sources[0]["kb_article_id"] == article_id


def test_faq_citation_omits_kb_article_id_when_article_is_unpublished():
    article_id = _make_article(published=False, audience="student")

    sources = _sources_from_chunks([_faq_chunk(article_id)], user_role="student")
    assert sources[0]["kb_article_id"] is None

    citations = _citations_from_sources(sources)
    assert citations[0]["kb_article_id"] is None


def test_faq_citation_omits_kb_article_id_when_audience_restricted_to_faculty():
    article_id = _make_article(published=True, audience="faculty")

    # A faculty-only article's FAQ chunk should never reach this function in
    # production (filter_chunks_for_audience drops it upstream for a
    # student caller) -- this proves the independent re-check here also
    # fails closed even if that upstream filter were ever bypassed.
    sources = _sources_from_chunks([_faq_chunk(article_id)], user_role="student")
    assert sources[0]["kb_article_id"] is None


def test_faq_citation_omits_kb_article_id_when_article_id_does_not_exist():
    sources = _sources_from_chunks(
        [_faq_chunk("nonexistent-article-id")], user_role="student"
    )
    assert sources[0]["kb_article_id"] is None


def test_faq_citation_without_user_role_omits_kb_article_id():
    # user_role is optional (default None) for backward compatibility with
    # any caller that doesn't pass it -- it must never crash, and treating
    # a role-less caller as "student" (the same default _apply_audience_filter
    # and article_visible_for_role already use) keeps the fail-closed
    # posture rather than silently granting broader access.
    article_id = _make_article(published=True, audience="faculty")
    sources = _sources_from_chunks([_faq_chunk(article_id)])
    assert sources[0]["kb_article_id"] is None


def test_non_faq_chunk_never_receives_kb_article_id():
    chunk = RetrievedChunk(
        document_id="some-raw-document-id",
        title="Citizen's Charter",
        source_filename="Citizens_Charter_2026.pdf",
        chunk_index=0,
        text="General information about the charter.",
        relevance_score=0.8,
        metadata={
            "document_id": "some-raw-document-id",
            "article_type": "procedure",
        },
    )
    sources = _sources_from_chunks([chunk], user_role="student")
    assert sources[0]["kb_article_id"] is None


def test_schema_round_trip_preserves_kb_article_id():
    source = QASourceSchema(title="t", path="p", kb_article_id="article-123")
    assert source.model_dump()["kb_article_id"] == "article-123"

    citation = QACitationSchema(citation_id="c-1", kb_article_id="article-123")
    assert citation.model_dump()["kb_article_id"] == "article-123"


def test_schema_kb_article_id_defaults_to_none():
    source = QASourceSchema(title="t", path="p")
    assert source.model_dump()["kb_article_id"] is None

    citation = QACitationSchema(citation_id="c-1")
    assert citation.model_dump()["kb_article_id"] is None
