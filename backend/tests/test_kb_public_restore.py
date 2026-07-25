"""Public KB restore: republish gated drafts + reindex RAG-stale rows."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import initialize_database
from app.models.db_models import PublishedArticle
from app.services.kb_public_restore import restore_public_kb_articles
from app.services.ticket_knowledge import ensure_unique_article_slug


def _session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    initialize_database(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def test_restore_republishes_draft_when_rag_succeeds(monkeypatch):
    sf = _session_factory()
    session = sf()
    art = PublishedArticle(
        title="ID Validation Restore",
        slug=ensure_unique_article_slug(session, "ID Validation Restore"),
        category="Student Services",
        content=(
            "Overview\nID Validation Restore\n\n"
            "Bring a valid school ID to the Registrar for validation."
        ),
        published=False,
        rag_indexed=False,
        audience="both",
    )
    session.add(art)
    session.commit()
    article_id = art.id
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
    art = PublishedArticle(
        title="Draft Dry Run",
        slug=ensure_unique_article_slug(session, "Draft Dry Run"),
        category="Student Services",
        content="Overview\nDraft Dry Run\n\nStudents may request this service at the office.",
        published=False,
        rag_indexed=False,
        audience="both",
    )
    session.add(art)
    session.commit()
    article_id = art.id

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


def _set_rag(article: PublishedArticle) -> None:
    article.rag_indexed = True
    article.rag_document_id = f"faq::{article.id}"
