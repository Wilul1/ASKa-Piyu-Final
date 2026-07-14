"""Shared Postgres helpers for tests — always gated by destructive DB guards."""

from __future__ import annotations

from app.db.safety import assert_destructive_database_ops_allowed
from app.db.session import get_session_factory
from app.models.db_models import PublishedArticle


def cleanup_all_published_articles() -> None:
    """Delete every published_articles row (test DB only)."""
    assert_destructive_database_ops_allowed()
    session = get_session_factory()()
    try:
        session.query(PublishedArticle).delete()
        session.commit()
    finally:
        session.close()


def cleanup_published_articles_by_source(filename: str) -> None:
    """Delete published_articles rows for one source filename (test DB only)."""
    assert_destructive_database_ops_allowed()
    session = get_session_factory()()
    try:
        session.query(PublishedArticle).filter(
            PublishedArticle.source_filename == filename
        ).delete()
        session.commit()
    finally:
        session.close()
