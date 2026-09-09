"""Index published FAQ articles into Chroma for chatbot retrieval."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.db.session import get_session_factory
from app.models.db_models import PublishedArticle, utc_now
from app.services.chroma_store import get_knowledge_base_store
from app.services.text_cleaner import split_into_chunks
from app.services.ticket_knowledge import strip_ticket_faq_scaffolding, sync_ticket_kb_status


logger = logging.getLogger(__name__)

# Admin-edited/generated articles append a "----EXTRACTED METADATA----\n{json}"
# debug block after the student-facing body (see article_content_formatter.py),
# and Citizen's Charter articles (build_charter_article_body) separately end
# with a fixed "Source Information / Document: / Service: / Office: / Page:"
# citation footer. Both are already captured structurally in article/chunk
# metadata, so neither belongs in the text that gets embedded/chunked:
# character-count chunking (split_into_chunks below) has no awareness of
# either block's boundaries, so it can land mid-block and produce a chunk
# that is only an unreadable fragment with no real content -- or, if the
# metadata JSON (which can be large and has few natural break points) isn't
# stripped first, swallow everything after it into one oversized chunk.
# Stripping both before chunking (for every article, not one specific
# document) prevents that whole class of degenerate chunks from ever being
# created. Order matters: the metadata block can appear *after* the source
# footer, so it must be removed first or the footer regex's end-of-string
# anchor won't match.
_EMBEDDED_METADATA_MARKER = "----EXTRACTED METADATA----"
_CHARTER_SOURCE_FOOTER_RE = re.compile(
    r"\n{1,2}Source Information\nDocument:[^\n]*\nService:[^\n]*\nOffice:[^\n]*\nPage:[^\n]*\s*\Z"
)


def _strip_charter_source_footer(text: str) -> str:
    cleaned = str(text or "")
    if _EMBEDDED_METADATA_MARKER in cleaned:
        cleaned = cleaned.split(_EMBEDDED_METADATA_MARKER, 1)[0]
    return _CHARTER_SOURCE_FOOTER_RE.sub("", cleaned).rstrip()


def _policy_appendix_from_extracted_metadata(content: str, visible_body: str) -> str:
    """Keep policy that the generator stored only in EXTRACTED METADATA JSON.

    The debug JSON must not be embedded, but ``content_sections`` often holds
    the only copy of a sibling rule (for example Change/Rectification of Grades
    nested under Submission of Grades).
    """
    raw_content = str(content or "")
    if _EMBEDDED_METADATA_MARKER not in raw_content:
        return ""
    raw_json = raw_content.split(_EMBEDDED_METADATA_MARKER, 1)[1].strip()
    try:
        payload = json.loads(raw_json)
    except json.JSONDecodeError:
        return ""
    visible = (visible_body or "").casefold()
    parts: list[str] = []
    for section in payload.get("content_sections") or []:
        if not isinstance(section, dict):
            continue
        heading = str(section.get("heading") or "").strip()
        body = str(section.get("body") or "").strip()
        if not body:
            continue
        if body.casefold().startswith("this article explains"):
            continue
        if body.casefold() in visible:
            continue
        parts.append(f"{heading}\n{body}".strip() if heading else body)
    return "\n\n".join(parts).strip()


class RagIndexOrphanError(RuntimeError):
    """Raised when re-index fails and previous Chroma vectors could not be restored."""

    def __init__(self, message: str, *, article_id: str) -> None:
        super().__init__(message)
        self.article_id = article_id
        self.vectors_orphaned = True
        self.previous_vectors_restored = False


class FaqIndexWriteError(RuntimeError):
    """Raised when a FAQ Chroma write fails (may have restored prior vectors)."""

    def __init__(
        self,
        message: str,
        *,
        article_id: str,
        previous_vectors_restored: bool,
    ) -> None:
        super().__init__(message)
        self.article_id = article_id
        self.previous_vectors_restored = previous_vectors_restored
        self.vectors_orphaned = False


@dataclass(frozen=True)
class _FaqChunk:
    text: str
    chunk_index: int
    char_start: int
    metadata: dict[str, Any]


def faq_document_id(article_id: str) -> str:
    return f"faq:{article_id}"


def infer_rag_audience_from_document(
    *,
    filename: str | None = None,
    title: str | None = None,
    document_type: str | None = None,
) -> str:
    """Infer RAG audience tags for PDF/manual ingest (student | faculty | both)."""
    blob = f"{filename or ''} {title or ''} {document_type or ''}".strip().lower()
    doc_type = (document_type or "").strip().lower()
    # Fail closed: unclear docs default to student (not both) so faculty manuals
    # must match an explicit faculty signal to be faculty-visible.
    if not blob and not doc_type:
        return "student"
    if doc_type in {"faculty_manual", "faculty-manual", "faculty"}:
        return "faculty"
    if doc_type in {"student_handbook", "student-handbook", "student"}:
        return "student"
    if "faculty manual" in blob or "faculty_manual" in blob or "faculty-manual" in blob:
        return "faculty"
    if "lspu faculty" in blob or blob.startswith("faculty ") or " faculty " in f" {blob} ":
        # Prefer faculty when the document name itself is faculty-scoped.
        if "student" not in blob:
            return "faculty"
    if "faculty" in blob and ("manual" in blob or "handbook" in blob or "guide" in blob):
        return "faculty"
    if "student handbook" in blob or "student_handbook" in blob or "student-handbook" in blob:
        return "student"
    if "handbook" in blob and "faculty" not in blob:
        return "student"
    if "citizen" in blob or "charter" in blob:
        return "both"
    return "student"


def cleanup_failed_faq_index(exc: BaseException, article_id: str) -> None:
    """Best-effort Chroma cleanup after a failed FAQ index — never wipe a restore.

    Callers must use this instead of always deleting ``faq:{id}`` after
    ``index_published_article`` raises.
    """
    if getattr(exc, "previous_vectors_restored", False):
        # Prior vectors are back in Chroma; leave them alone.
        return
    if getattr(exc, "vectors_orphaned", False):
        # Orphan path already cleared flags via persist_article_rag_stale.
        best_effort_remove_faq_document(article_id)
        return
    best_effort_remove_faq_document(article_id)


def stamp_chunks_with_audience(chunks: list, audience: str) -> list:
    """Ensure each chunk carries an ``audience`` metadata field.

    Fails loudly if a chunk cannot be tagged — untagged chunks are hidden from
    student/faculty retrieval.
    """
    resolved = (audience or "student").strip().lower() or "student"
    stamped: list = []
    for chunk in chunks:
        meta = getattr(chunk, "metadata", None)
        if isinstance(meta, dict):
            meta.setdefault("audience", resolved)
            stamped.append(chunk)
            continue
        if meta is None:
            try:
                chunk.metadata = {"audience": resolved}
                stamped.append(chunk)
                continue
            except Exception:
                pass
            try:
                stamped.append(
                    type(chunk)(
                        text=chunk.text,
                        chunk_index=chunk.chunk_index,
                        char_start=chunk.char_start,
                        metadata={"audience": resolved},
                    )
                )
                continue
            except TypeError as exc:
                raise ValueError(
                    f"Cannot stamp audience={resolved!r} onto chunk type {type(chunk).__name__}"
                ) from exc
        raise ValueError(
            f"Cannot stamp audience={resolved!r}: chunk metadata is {type(meta).__name__}"
        )
    return stamped


def _build_faq_chunks(article: PublishedArticle) -> list[_FaqChunk]:
    raw_content = article.content or ""
    if (article.kb_origin or "") == "ticket_resolution":
        raw_content = strip_ticket_faq_scaffolding(raw_content, title=article.title)
    visible = _strip_charter_source_footer(raw_content)
    appendix = _policy_appendix_from_extracted_metadata(article.content or "", visible)
    body = "\n\n".join(
        part
        for part in (
            article.title or "",
            article.summary or "",
            visible,
            appendix,
        )
        if (part or "").strip()
    ).strip()
    if not body:
        raise ValueError("Published article has no content to index.")

    raw_chunks = split_into_chunks(body, max_chars=1200, overlap=150)
    chunks = [
        _FaqChunk(
            text=item["text"],
            chunk_index=int(item["chunk_index"]),
            char_start=int(item["char_start"]),
            metadata={
                "source_section": article.title,
                "canonical_topic": article.title,
                "category": article.category or "",
                "office": article.office or "",
                "audience": article.audience or "student",
                "kb_origin": article.kb_origin or "ticket_resolution",
                "source_ticket_id": article.source_ticket_id or "",
                "article_id": article.id,
                "article_type": "faq",
            },
        )
        for item in raw_chunks
        if str(item.get("text") or "").strip()
    ]
    if not chunks:
        raise ValueError("Could not build searchable chunks from the article.")
    return chunks


def index_published_article(session: Session, article: PublishedArticle) -> int:
    """Upsert FAQ chunks for a published article. Returns chunk count.

    Re-index is restore-safe: existing Chroma chunks are snapshotted before delete.
    If the new write fails, the previous vectors are restored when possible.
    """
    store = get_knowledge_base_store()
    document_id = faq_document_id(article.id)
    chunks = _build_faq_chunks(article)
    # Never delete existing vectors unless we successfully snapshotted them (or confirmed none).
    try:
        backup = store.export_document(document_id)
    except Exception as exc:
        logger.exception(
            "Could not snapshot existing Chroma chunks for %s; aborting re-index",
            document_id,
        )
        raise RuntimeError(
            f"Could not snapshot existing Chroma chunks for {document_id}; "
            "re-index aborted to avoid deleting unrecovered vectors."
        ) from exc

    try:
        store.delete_document(document_id)
        count = store.add_document_chunks(
            document_id=document_id,
            title=article.title,
            source_filename=article.source_filename or f"Ticket FAQ ({article.id})",
            document_type="faq",
            chunks=chunks,
            document_metadata={
                "audience": article.audience or "student",
                "kb_origin": article.kb_origin or "ticket_resolution",
                "source_ticket_id": article.source_ticket_id or "",
                "category": article.category or "",
                "office": article.office or "",
            },
        )
    except Exception as exc:
        # Clear any partial write, then put the previous vectors back.
        try:
            store.delete_document(document_id)
        except Exception:
            logger.exception("Failed to clear partial FAQ index for %s", document_id)
        if backup is None:
            # First-time index (nothing to restore).
            raise FaqIndexWriteError(
                str(exc),
                article_id=article.id,
                previous_vectors_restored=False,
            ) from exc
        try:
            store.restore_document_export(backup)
            logger.warning(
                "Restored previous Chroma chunks after failed re-index of %s",
                document_id,
            )
        except Exception as restore_exc:
            logger.exception(
                "CRITICAL: failed to restore Chroma backup for %s after re-index failure",
                document_id,
            )
            if not persist_article_rag_stale(article.id):
                raise RagIndexOrphanError(
                    f"FAQ re-index failed, restore failed ({restore_exc}), and "
                    f"clearing rag_indexed also failed for {article.id}: {exc}",
                    article_id=article.id,
                ) from exc
            raise RagIndexOrphanError(
                f"FAQ re-index failed and previous Chroma vectors could not be restored: {exc}",
                article_id=article.id,
            ) from exc
        raise FaqIndexWriteError(
            str(exc),
            article_id=article.id,
            previous_vectors_restored=True,
        ) from exc

    article.rag_indexed = True
    article.rag_document_id = document_id
    article.chunk_count = count
    article.updated_at = utc_now()
    session.add(article)
    sync_ticket_kb_status(session, article)
    logger.info("Indexed FAQ article %s into Chroma (%s chunks)", article.id, count)
    return count


def persist_article_rag_stale(article_id: str) -> bool:
    """Clear RAG flags in a separate DB transaction (survives caller rollback)."""
    article_id = (article_id or "").strip()
    if not article_id:
        return False
    session_factory = get_session_factory()
    session = session_factory()
    try:
        art = session.get(PublishedArticle, article_id)
        if art is None:
            return False
        art.rag_indexed = False
        art.rag_document_id = None
        art.chunk_count = 0
        art.updated_at = utc_now()
        session.add(art)
        session.commit()
        logger.warning(
            "Marked article %s rag_indexed=false after Chroma orphan/restore failure",
            article_id,
        )
        return True
    except Exception:
        session.rollback()
        logger.exception("Failed to persist stale RAG flags for article %s", article_id)
        return False
    finally:
        session.close()


def remove_published_article_index(session: Session, article: PublishedArticle) -> None:
    store = get_knowledge_base_store()
    document_id = article.rag_document_id or faq_document_id(article.id)
    store.delete_document(document_id)
    article.rag_indexed = False
    article.rag_document_id = None
    article.chunk_count = 0
    article.updated_at = utc_now()
    session.add(article)
    logger.info("Removed FAQ article %s from Chroma", article.id)


def clear_all_article_rag_flags(session: Session) -> int:
    """Mark all published-article RAG flags false after a Chroma collection wipe."""
    rows = (
        session.query(PublishedArticle)
        .filter(
            (PublishedArticle.rag_indexed.is_(True))
            | (PublishedArticle.rag_document_id.isnot(None))
        )
        .all()
    )
    cleared = 0
    for art in rows:
        art.rag_indexed = False
        art.rag_document_id = None
        art.chunk_count = 0
        art.updated_at = utc_now()
        session.add(art)
        cleared += 1
    return cleared


def reindex_stale_published_faq_articles(session: Session) -> dict[str, Any]:
    """Re-index published FAQs that are missing from Chroma (``rag_indexed=false``)."""
    rows = (
        session.query(PublishedArticle)
        .filter(
            PublishedArticle.published.is_(True),
            PublishedArticle.rag_indexed.is_(False),
        )
        .order_by(PublishedArticle.updated_at.desc())
        .all()
    )
    return _reindex_faq_rows(session, rows)


def reindex_published_faq_articles(session: Session) -> dict[str, Any]:
    """Re-index all published FAQ articles into Chroma. Commits per successful article."""
    rows = (
        session.query(PublishedArticle)
        .filter(PublishedArticle.published.is_(True))
        .order_by(PublishedArticle.updated_at.desc())
        .all()
    )
    return _reindex_faq_rows(session, rows)


def _reindex_faq_rows(session: Session, rows: list[PublishedArticle]) -> dict[str, Any]:
    reindexed = 0
    failed: list[dict[str, str]] = []
    for art in rows:
        article_id = art.id
        title = art.title or article_id
        try:
            # Re-load after possible prior rollback in this session.
            current = session.get(PublishedArticle, article_id)
            if current is None or not current.published:
                continue
            index_published_article(session, current)
            session.commit()
            reindexed += 1
        except Exception as exc:
            session.rollback()
            logger.exception("Failed to re-index published FAQ %s after Chroma reset", article_id)
            failed.append(
                {
                    "id": article_id,
                    "title": title,
                    "error": str(exc),
                }
            )
    return {
        "faq_reindexed": reindexed,
        "faq_reindex_failed": len(failed),
        "faq_reindex_errors": failed[:20],
        "published_article_count": len(rows),
    }


def chroma_where_for_audience(user_role: str | None) -> dict[str, object] | None:
    """Chroma pre-filter so faculty queries are not crowded out by student handbook.

    Students keep an unfiltered vector search: missing/legacy audience tags are
    treated as student-visible in ``filter_chunks_for_audience``. Faculty-only
    pre-filter is safe because Faculty Manual chunks are stamped ``faculty``.
    """
    role = (user_role or "student").strip().lower()
    if role != "faculty":
        return None
    return {"audience": {"$in": ["faculty", "both"]}}


def filter_chunks_for_audience(chunks: list, user_role: str | None) -> list:
    """Filter retrieved chunks by account role.

    Missing/legacy audience tags are treated as ``student`` (not faculty) so
    unre-ingested Faculty Manual chunks do not leak to students. Re-ingest with
    audience stamps before launch. Faculty see faculty + both only (not student-only).
    Office/admin see everything.
    """
    role = (user_role or "student").strip().lower()
    if role in {"office", "admin"}:
        return list(chunks)

    if role == "faculty":
        allowed = {"both", "faculty"}
    else:
        allowed = {"both", "student"}

    filtered = []
    for chunk in chunks:
        meta = getattr(chunk, "metadata", None) or {}
        audience = str(meta.get("audience") or meta.get("doc_audience") or "").strip().lower()
        # Legacy Chroma rows: fail closed to student-visible only (not faculty-secret).
        if not audience:
            audience = "student"
        if audience in allowed:
            filtered.append(chunk)
    return filtered


def filter_unpublished_faq_chunks(chunks: list) -> list:
    """Drop FAQ Chroma orphans whose Postgres article is missing or unpublished.

    Defense in depth when Chroma was written but a later DB commit rolled back.
    """
    faq_ids: set[str] = set()
    for chunk in chunks:
        document_id = str(getattr(chunk, "document_id", "") or "").strip()
        meta = getattr(chunk, "metadata", None) or {}
        article_id = str(meta.get("article_id") or "").strip()
        if document_id.startswith("faq:"):
            faq_ids.add(article_id or document_id[4:])
        elif str(meta.get("article_type") or "").strip().lower() == "faq" and article_id:
            faq_ids.add(article_id)

    if not faq_ids:
        return list(chunks)

    published_ids: set[str] = set()
    session_factory = get_session_factory()
    session = session_factory()
    try:
        rows = (
            session.query(PublishedArticle.id)
            .filter(
                PublishedArticle.id.in_(list(faq_ids)),
                PublishedArticle.published.is_(True),
            )
            .all()
        )
        published_ids = {row[0] for row in rows}
    except Exception:
        logger.exception("Failed to verify published FAQ articles; dropping FAQ chunks fail-closed")
        published_ids = set()
    finally:
        session.close()

    kept = []
    for chunk in chunks:
        document_id = str(getattr(chunk, "document_id", "") or "").strip()
        meta = getattr(chunk, "metadata", None) or {}
        article_id = str(meta.get("article_id") or "").strip()
        is_faq = document_id.startswith("faq:") or (
            str(meta.get("article_type") or "").strip().lower() == "faq"
        )
        if not is_faq:
            kept.append(chunk)
            continue
        resolved_id = article_id or (document_id[4:] if document_id.startswith("faq:") else "")
        if resolved_id and resolved_id in published_ids:
            kept.append(chunk)
    return kept


def best_effort_remove_faq_document(article_id: str) -> None:
    """Remove FAQ vectors without touching Postgres (commit-failure cleanup)."""
    document_id = faq_document_id(article_id)
    try:
        get_knowledge_base_store().delete_document(document_id)
    except Exception:
        logger.exception("Best-effort Chroma cleanup failed for %s", document_id)
