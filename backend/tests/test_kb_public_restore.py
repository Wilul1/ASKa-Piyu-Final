"""Public KB restore: republish gated drafts + reindex RAG-stale rows."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import initialize_database
from app.models.db_models import PublishedArticle
from app.services.kb_public_restore import restore_public_kb_articles
from app.services.ticket_knowledge import _COMPLETION_MARKER, ensure_unique_article_slug

_COMPLETE_BODY = (
    "Overview\nFaculty teaching load\n\n"
    "Full-time faculty generally carry eighteen units per semester unless an "
    "overload is approved by the campus director per the Faculty Manual."
)
_INCOMPLETE_MSG = "requires staff completion"


def _session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    initialize_database(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def _set_rag(article: PublishedArticle) -> None:
    article.rag_indexed = True
    article.rag_document_id = f"faq::{article.id}"


def _add_draft(
    session,
    *,
    title: str,
    content: str,
    kb_origin: str = "document",
    needs_manual_completion: bool = False,
) -> str:
    art = PublishedArticle(
        title=title,
        slug=ensure_unique_article_slug(session, title),
        category="Student Services",
        content=content,
        published=False,
        rag_indexed=False,
        audience="both",
        kb_origin=kb_origin,
        needs_manual_completion=needs_manual_completion,
    )
    session.add(art)
    session.commit()
    return art.id


def test_restore_republishes_draft_when_rag_succeeds(monkeypatch):
    sf = _session_factory()
    session = sf()
    article_id = _add_draft(
        session,
        title="ID Validation Restore",
        content=(
            "Overview\nID Validation Restore\n\n"
            "Bring a valid school ID to the Registrar for validation."
        ),
    )
    session.close()

    monkeypatch.setattr(
        "app.services.kb_public_restore.index_published_article",
        lambda session, article: (_set_rag(article) or 2),
    )

    session = sf()
    report = restore_public_kb_articles(
        session,
        republish_drafts=True,
        reindex_stale=False,
        dry_run=False,
    )
    assert report["draft_candidates"] == 1
    assert report["draft_republished"] == 1
    art = session.get(PublishedArticle, article_id)
    assert art is not None
    assert art.published is True
    assert art.rag_indexed is True
    session.close()


def test_restore_dry_run_does_not_publish():
    sf = _session_factory()
    session = sf()
    article_id = _add_draft(
        session,
        title="Draft Dry Run",
        content="Overview\nDraft Dry Run\n\nStudents may request this service at the office.",
    )

    report = restore_public_kb_articles(
        session,
        republish_drafts=True,
        reindex_stale=True,
        dry_run=True,
    )
    assert report["dry_run"] is True
    assert report["draft_candidates"] == 1
    assert report["draft_republished"] == 0
    art = session.get(PublishedArticle, article_id)
    assert art is not None
    assert art.published is False
    session.close()


def test_restore_a_ticket_flag_only_blocked(monkeypatch):
    sf = _session_factory()
    session = sf()
    original = _COMPLETE_BODY
    article_id = _add_draft(
        session,
        title="Restore Ticket Flag Only",
        content=original,
        kb_origin="ticket_resolution",
        needs_manual_completion=True,
    )
    monkeypatch.setattr(
        "app.services.kb_public_restore.index_published_article",
        lambda session, article: (_set_rag(article) or 2),
    )
    report = restore_public_kb_articles(
        session,
        republish_drafts=True,
        reindex_stale=False,
        dry_run=False,
    )
    assert report["draft_republished"] == 1
    art = session.get(PublishedArticle, article_id)
    assert art is not None
    assert art.published is True
    assert art.content == original
    session.close()


def test_restore_b_ticket_marker_only_allowed(monkeypatch):
    sf = _session_factory()
    session = sf()
    original = f"{_COMPLETE_BODY}\n\n{_COMPLETION_MARKER}"
    article_id = _add_draft(
        session,
        title="Restore Ticket Marker Only",
        content=original,
        kb_origin="ticket_resolution",
        needs_manual_completion=False,
    )
    monkeypatch.setattr(
        "app.services.kb_public_restore.index_published_article",
        lambda session, article: (_set_rag(article) or 2),
    )
    report = restore_public_kb_articles(
        session,
        republish_drafts=True,
        reindex_stale=False,
        dry_run=False,
    )
    assert report["draft_republished"] == 1
    art = session.get(PublishedArticle, article_id)
    assert art is not None
    assert art.published is True
    assert art.content == original
    session.close()


def test_restore_c_ticket_both_cleared_allowed(monkeypatch):
    sf = _session_factory()
    session = sf()
    article_id = _add_draft(
        session,
        title="Restore Ticket Complete",
        content=_COMPLETE_BODY,
        kb_origin="ticket_resolution",
        needs_manual_completion=False,
    )
    monkeypatch.setattr(
        "app.services.kb_public_restore.index_published_article",
        lambda session, article: (_set_rag(article) or 2),
    )
    report = restore_public_kb_articles(
        session,
        republish_drafts=True,
        reindex_stale=False,
        dry_run=False,
    )
    assert report["draft_republished"] == 1
    art = session.get(PublishedArticle, article_id)
    assert art is not None
    assert art.published is True
    assert art.needs_manual_completion is False
    assert _COMPLETION_MARKER not in (art.content or "")
    session.close()


def test_restore_d_non_ticket_behavior_preserved(monkeypatch):
    sf = _session_factory()
    session = sf()
    article_id = _add_draft(
        session,
        title="Restore Non-ticket Handbook",
        content=_COMPLETE_BODY,
        kb_origin="document",
        needs_manual_completion=False,
    )
    monkeypatch.setattr(
        "app.services.kb_public_restore.index_published_article",
        lambda session, article: (_set_rag(article) or 2),
    )
    report = restore_public_kb_articles(
        session,
        republish_drafts=True,
        reindex_stale=False,
        dry_run=False,
    )
    assert report["draft_republished"] == 1
    art = session.get(PublishedArticle, article_id)
    assert art is not None
    assert art.published is True
    session.close()


def test_restore_e_incomplete_ticket_draft_can_republish(monkeypatch):
    sf = _session_factory()
    session = sf()
    original = f"Partial ticket draft with reusable office steps.\n\n{_COMPLETION_MARKER}"
    article_id = _add_draft(
        session,
        title="Restore Ticket Incomplete Allowed",
        content=original,
        kb_origin="ticket_resolution",
        needs_manual_completion=True,
    )
    monkeypatch.setattr(
        "app.services.kb_public_restore.index_published_article",
        lambda session, article: (_set_rag(article) or 2),
    )
    dry_report = restore_public_kb_articles(
        session,
        republish_drafts=True,
        reindex_stale=False,
        dry_run=True,
    )
    assert dry_report["draft_republished"] == 0
    art = session.get(PublishedArticle, article_id)
    assert art is not None
    assert art.published is False

    report = restore_public_kb_articles(
        session,
        republish_drafts=True,
        reindex_stale=False,
        dry_run=False,
    )
    assert report["draft_republished"] == 1
    art = session.get(PublishedArticle, article_id)
    assert art is not None
    assert art.published is True
    assert art.content == original
    assert art.kb_origin == "ticket_resolution"
    session.close()
