"""Restore public Knowledge Base visibility after RAG fail-close / Chroma drift."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.db_models import PublishedArticle
from app.services.article_rag_indexer import index_published_article
from app.services.ticket_knowledge import sync_ticket_kb_status

logger = logging.getLogger(__name__)


def _publish_gate(content: str | None) -> str | None:
    # Keep gate rules aligned with admin KB publish (import lazily to avoid cycles).
    from app.routes.admin.knowledge_base import _publish_gate_error

    return _publish_gate_error(content=content)


def restore_public_kb_articles(
    session: Session,
    *,
    republish_drafts: bool = True,
    reindex_stale: bool = True,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Re-index RAG-stale published rows and optionally republish gated drafts.

    Fail-closed publish leaves rows as ``published=false``. This restores them
    when content passes the publish gate and Chroma indexing succeeds.
    """
    report: dict[str, Any] = {
        "dry_run": dry_run,
        "republish_drafts": republish_drafts,
        "reindex_stale": reindex_stale,
        "stale_candidates": 0,
        "stale_reindexed": 0,
        "stale_failed": [],
        "draft_candidates": 0,
        "draft_republished": 0,
        "draft_skipped": [],
        "draft_failed": [],
    }

    if reindex_stale:
        stale_rows = (
            session.query(PublishedArticle)
            .filter(
                PublishedArticle.published.is_(True),
                PublishedArticle.rag_indexed.is_(False),
            )
            .order_by(PublishedArticle.updated_at.desc())
            .all()
        )
        report["stale_candidates"] = len(stale_rows)
        for art in stale_rows:
            item = {"id": art.id, "title": art.title}
            if dry_run:
                continue
            try:
                current = session.get(PublishedArticle, art.id)
                if current is None or not current.published:
                    continue
                index_published_article(session, current)
                session.commit()
                report["stale_reindexed"] += 1
            except Exception as exc:
                session.rollback()
                logger.exception("Failed to reindex stale article %s", art.id)
                report["stale_failed"].append({**item, "error": str(exc)})

    if republish_drafts:
        draft_rows = (
            session.query(PublishedArticle)
            .filter(PublishedArticle.published.is_(False))
            .order_by(PublishedArticle.updated_at.desc())
            .all()
        )
        report["draft_candidates"] = len(draft_rows)
        for art in draft_rows:
            item = {"id": art.id, "title": art.title}
            gate = _publish_gate(art.content)
            if gate:
                report["draft_skipped"].append({**item, "reason": gate})
                continue
            if dry_run:
                continue
            try:
                current = session.get(PublishedArticle, art.id)
                if current is None:
                    continue
                current.published = True
                current.published_at = datetime.now(timezone.utc)
                current.rag_indexed = False
                session.add(current)
                sync_ticket_kb_status(session, current)
                session.commit()
                session.refresh(current)
                index_published_article(session, current)
                session.commit()
                report["draft_republished"] += 1
            except Exception as exc:
                session.rollback()
                # Fail-closed: ensure we did not leave a public ghost.
                current = session.get(PublishedArticle, art.id)
                if current is not None and current.published and not current.rag_indexed:
                    current.published = False
                    current.published_at = None
                    current.rag_indexed = False
                    current.rag_document_id = None
                    sync_ticket_kb_status(session, current)
                    session.add(current)
                    session.commit()
                logger.exception("Failed to republish draft %s", art.id)
                report["draft_failed"].append({**item, "error": str(exc)})

    return report
