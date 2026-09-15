"""Knowledge Article media: inline images and attachments.

Reuses ``kb_media_dir`` (the ``aska_kb_media`` Docker volume, included in
``scripts/backup_aska.sh`` / ``backup_aska.bat``) rather than inventing a
second filesystem. Metadata lives in ``article_media`` so pending uploads can
be attached, authorized, and cleaned up.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.db_models import ArticleMedia, PublishedArticle, User
from app.services.article_access import assert_kb_editor_may_access_article, load_kb_editor_actor
from app.services.kb_media import ALLOWED_IMAGE_TYPES, MAX_KB_IMAGE_BYTES, _media_root, _safe_stem
from app.services.ticket_attachments import detect_content_type

logger = logging.getLogger(__name__)

KIND_INLINE = "inline_image"
KIND_ATTACHMENT = "attachment"
ALLOWED_KINDS = frozenset({KIND_INLINE, KIND_ATTACHMENT})
ALLOWED_ATTACHMENT_TYPES = {
    **ALLOWED_IMAGE_TYPES,
    "application/pdf": ".pdf",
}
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
PENDING_TTL = timedelta(hours=24)
_STORED_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


class ArticleMediaError(ValueError):
    """Validation failure for article media uploads."""


class ArticleMediaAccessError(PermissionError):
    """Caller is not allowed to touch this media row."""


class ArticleMediaNotFoundError(FileNotFoundError):
    """Media row or file is missing."""


class ArticleMediaFileError(RuntimeError):
    """A media file exists but could not be safely removed from disk.

    Callers must NOT delete the corresponding ``article_media`` row when this
    is raised: the DB row is what keeps a private/pending file out of the
    public ``/kb/media/{stored_filename}`` route (legacy files with no row
    are served publicly for backward compatibility), so dropping the row
    before the file is confirmed gone would turn a still-private file into
    an accidentally public one.
    """


def _ext_for(content_type: str, kind: str) -> str:
    mapping = ALLOWED_IMAGE_TYPES if kind == KIND_INLINE else ALLOWED_ATTACHMENT_TYPES
    return mapping[content_type]


def _max_bytes(kind: str) -> int:
    return MAX_KB_IMAGE_BYTES if kind == KIND_INLINE else MAX_ATTACHMENT_BYTES


def _allowed_types(kind: str) -> dict[str, str]:
    return ALLOWED_IMAGE_TYPES if kind == KIND_INLINE else ALLOWED_ATTACHMENT_TYPES


def media_schema(row: ArticleMedia) -> dict[str, object]:
    return {
        "id": row.id,
        "article_id": row.article_id,
        "kind": row.kind,
        "original_filename": row.original_filename,
        "stored_filename": row.stored_filename,
        "content_type": row.content_type,
        "size_bytes": int(row.size_bytes),
        "url": f"/kb/media/{row.stored_filename}",
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "pending": row.article_id is None,
    }


def save_article_media(
    session: Session,
    *,
    actor: User,
    kind: str,
    filename: str,
    content: bytes,
    claimed_type: str | None = None,
    article: PublishedArticle | None = None,
) -> ArticleMedia:
    kind = (kind or "").strip().lower()
    if kind not in ALLOWED_KINDS:
        raise ArticleMediaError("Media kind must be inline_image or attachment.")
    if actor is None or not getattr(actor, "id", None):
        raise ArticleMediaAccessError("Sign in as admin or office staff to upload article media.")
    if not content:
        raise ArticleMediaError("File is empty.")
    limit = _max_bytes(kind)
    if len(content) > limit:
        label = "5 MB" if kind == KIND_INLINE else "10 MB"
        raise ArticleMediaError(f"File must be {label} or smaller.")

    sniffed = detect_content_type(content)
    allowed = _allowed_types(kind)
    if sniffed is None or sniffed not in allowed:
        if kind == KIND_INLINE:
            raise ArticleMediaError("Only JPG, PNG, WebP, or GIF images are allowed.")
        raise ArticleMediaError("Only JPG, PNG, WebP, GIF, or PDF files are allowed.")

    claimed = (claimed_type or "").split(";")[0].strip().lower()
    if claimed and claimed in allowed and claimed != sniffed:
        raise ArticleMediaError("File content does not match the declared file type.")

    media_id = str(uuid.uuid4())
    ext = _ext_for(sniffed, kind)
    stored = f"{media_id}_{_safe_stem(filename)}{ext}"
    path = _media_root() / stored
    path.write_bytes(content)

    row = ArticleMedia(
        id=media_id,
        article_id=article.id if article is not None else None,
        uploaded_by_user_id=actor.id,
        kind=kind,
        original_filename=(filename or "file")[:255],
        stored_filename=stored,
        content_type=sniffed,
        size_bytes=len(content),
    )
    session.add(row)
    session.flush()
    return row


def get_media(session: Session, media_id: str) -> ArticleMedia:
    row = session.get(ArticleMedia, media_id)
    if row is None:
        raise ArticleMediaNotFoundError("Media not found.")
    return row


def get_media_by_filename(session: Session, stored_filename: str) -> ArticleMedia | None:
    name = Path(stored_filename or "").name
    if not name or not _STORED_NAME_RE.match(name):
        return None
    return (
        session.query(ArticleMedia)
        .filter(ArticleMedia.stored_filename == name)
        .one_or_none()
    )


def _assert_can_manage(session: Session, actor: User | None, row: ArticleMedia) -> None:
    from fastapi import HTTPException

    if actor is None:
        raise ArticleMediaAccessError("Sign in as admin or office staff.")
    role = str(actor.role or "").strip().lower()
    if role == "admin":
        if row.article_id:
            article = session.get(PublishedArticle, row.article_id)
            if article is not None:
                try:
                    assert_kb_editor_may_access_article(session, actor, article)
                except HTTPException as exc:
                    raise ArticleMediaAccessError(str(exc.detail)) from exc
        return
    if role != "office":
        raise ArticleMediaAccessError("Only admin or office staff can manage article media.")
    if row.article_id is None:
        if str(row.uploaded_by_user_id) != str(actor.id):
            raise ArticleMediaAccessError("You can only manage your own unsaved uploads.")
        return
    article = session.get(PublishedArticle, row.article_id)
    if article is None:
        raise ArticleMediaNotFoundError("Article not found.")
    try:
        assert_kb_editor_may_access_article(session, actor, article)
    except HTTPException as exc:
        raise ArticleMediaAccessError(str(exc.detail)) from exc


def _unlink_media_file(stored_filename: str) -> None:
    """Remove a media file from disk, or raise if that cannot be confirmed.

    A file that is already gone counts as success (idempotent — safe to
    retry). A file that exists but fails to delete (permissions, disk I/O,
    a lock held by another process, ...) raises ``ArticleMediaFileError``
    instead of silently continuing: the caller must keep the DB row (and
    therefore keep the file private/protected) until deletion is confirmed.
    """
    from app.services.kb_media import resolve_kb_media_path

    try:
        path = resolve_kb_media_path(stored_filename)
    except FileNotFoundError:
        return
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError as exc:
        logger.exception("Could not delete article media file %s", stored_filename)
        raise ArticleMediaFileError(
            f"Could not delete file {stored_filename!r} from storage."
        ) from exc


def delete_media(session: Session, actor: User | None, media_id: str) -> None:
    """Delete one media row. The file is removed BEFORE the DB row.

    If the file cannot be removed, ``_unlink_media_file`` raises and the DB
    row is left untouched — the media stays exactly as protected/private as
    it was before the delete attempt, instead of becoming an orphaned file
    that ``download_kb_media`` would treat as untracked/legacy and serve
    publicly. Callers can safely retry: a file that is already gone (e.g. a
    prior attempt partially succeeded) is treated as already-deleted.
    """
    row = get_media(session, media_id)
    _assert_can_manage(session, actor, row)
    stored = row.stored_filename
    _unlink_media_file(stored)
    session.delete(row)
    session.flush()


def attach_media_ids(
    session: Session,
    *,
    actor: User | None,
    article: PublishedArticle,
    media_ids: list[str] | None,
) -> None:
    if not media_ids:
        return
    if actor is None:
        raise ArticleMediaAccessError("Sign in as admin or office staff to attach media.")
    seen: set[str] = set()
    for raw_id in media_ids:
        media_id = str(raw_id or "").strip()
        if not media_id or media_id in seen:
            continue
        seen.add(media_id)
        row = session.get(ArticleMedia, media_id)
        if row is None:
            raise ArticleMediaNotFoundError("One of the uploaded files could not be found.")
        if row.article_id and str(row.article_id) != str(article.id):
            raise ArticleMediaAccessError("That file is already attached to another article.")
        if row.article_id is None and str(row.uploaded_by_user_id) != str(actor.id):
            role = str(actor.role or "").strip().lower()
            if role != "admin":
                raise ArticleMediaAccessError("You can only attach files you uploaded.")
        row.article_id = article.id
        session.add(row)
    session.flush()


def attach_inline_filenames(
    session: Session,
    *,
    actor: User | None,
    article: PublishedArticle,
    filenames: list[str],
) -> None:
    if not filenames or actor is None:
        return
    for name in filenames:
        row = get_media_by_filename(session, name)
        if row is None:
            continue
        if row.article_id and str(row.article_id) != str(article.id):
            continue
        if row.article_id is None and str(row.uploaded_by_user_id) != str(actor.id):
            role = str(actor.role or "").strip().lower()
            if role != "admin":
                continue
        row.article_id = article.id
        if row.kind != KIND_INLINE:
            row.kind = KIND_INLINE
        session.add(row)
    session.flush()


def list_article_media(session: Session, article_id: str, *, kind: str | None = None) -> list[ArticleMedia]:
    query = session.query(ArticleMedia).filter(ArticleMedia.article_id == article_id)
    if kind:
        query = query.filter(ArticleMedia.kind == kind)
    return query.order_by(ArticleMedia.created_at.asc()).all()


def cleanup_pending_media(session: Session, *, older_than: timedelta = PENDING_TTL) -> int:
    """Sweep stale (>24h) pending uploads. Never deletes a row before its file is gone."""
    cutoff = datetime.now(timezone.utc) - older_than
    rows = (
        session.query(ArticleMedia)
        .filter(ArticleMedia.article_id.is_(None), ArticleMedia.created_at < cutoff)
        .all()
    )
    removed = 0
    for row in rows:
        try:
            _unlink_media_file(row.stored_filename)
        except ArticleMediaFileError:
            # Leave the row (and its protection) in place; the next sweep retries it.
            continue
        session.delete(row)
        removed += 1
    if removed:
        session.flush()
    return removed


def delete_article_media_files(session: Session, article_id: str) -> None:
    """Remove every media file for an article before the article row is deleted.

    Only removes files here. Deliberately does NOT delete the ``article_media``
    rows: ``PublishedArticle.media`` cascades with ``delete-orphan``, so the
    rows disappear automatically once the caller deletes the article itself.
    If any file fails to delete, this raises and the caller's transaction
    rolls back — the article, its rows, and every already-checked file stay
    exactly as they were, rather than deleting some files/rows and not
    others.
    """
    rows = list_article_media(session, article_id)
    for row in rows:
        _unlink_media_file(row.stored_filename)


def can_publicly_serve(session: Session, row: ArticleMedia, viewer: User | None) -> bool:
    if row.article_id is None:
        if viewer is not None and str(viewer.id) == str(row.uploaded_by_user_id):
            return True
        role = str(getattr(viewer, "role", "") or "").strip().lower()
        return role == "admin"
    article = session.get(PublishedArticle, row.article_id)
    if article is None:
        return False
    if bool(article.published):
        audience = str(getattr(article, "audience", None) or "student").strip().lower() or "student"
        role = str(getattr(viewer, "role", None) or "student").strip().lower()
        if role in {"office", "admin"}:
            return True
        if role == "faculty":
            return audience in {"faculty", "both"}
        return audience in {"student", "both"}
    if viewer is None:
        return False
    try:
        assert_kb_editor_may_access_article(session, viewer, article)
        return True
    except Exception:
        return False


def apply_article_content_and_media(
    session: Session,
    *,
    actor: User | None,
    article: PublishedArticle,
    content: str | None,
    content_format: str | None,
    media_ids: list[str] | None,
    merge_existing: bool = False,
) -> None:
    from app.services.article_content_formatter import merge_article_content_update
    from app.services.article_html import extract_kb_media_filenames, prepare_article_body

    existing_fmt = getattr(article, "content_format", None)
    stored, fmt = prepare_article_body(
        content=content,
        content_format=content_format,
        existing_format=existing_fmt,
    )
    if merge_existing:
        stored = merge_article_content_update(
            article.content, stored, content_format=fmt
        )
    article.content = stored
    article.content_format = fmt
    attach_media_ids(session, actor=actor, article=article, media_ids=media_ids)
    attach_inline_filenames(
        session,
        actor=actor,
        article=article,
        filenames=extract_kb_media_filenames(stored),
    )


def require_editor_actor(session: Session, actor_id: str | None) -> User:
    actor = load_kb_editor_actor(session, actor_id)
    if actor is None:
        raise ArticleMediaAccessError(
            "Sign in as admin or office staff to upload article media."
        )
    return actor
