"""Durable storage for original uploaded source documents (PDFs, etc.)."""

from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.config import BACKEND_DIR, settings
from app.models.db_models import SourceDocument

logger = logging.getLogger(__name__)

_UNSAFE_FILENAME = re.compile(r"[^A-Za-z0-9._\- ]+")


def documents_root() -> Path:
    raw = (settings.documents_persist_dir or "./data/documents").strip()
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = BACKEND_DIR / path
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def safe_filename(filename: str | None) -> str:
    name = (filename or "document.pdf").strip() or "document.pdf"
    name = Path(name).name
    cleaned = _UNSAFE_FILENAME.sub("_", name).strip("._ ") or "document.pdf"
    return cleaned[:180]


def build_source_label(
    *,
    original_filename: str,
    title: str | None = None,
    version: str | None = None,
    edition: str | None = None,
    document_type: str | None = None,
) -> str:
    base = (title or "").strip()
    if not base:
        stem = Path(original_filename).stem.replace("_", " ").replace("-", " ").strip()
        base = stem or original_filename
    bits = [base]
    if edition:
        bits.append(edition.strip())
    elif version:
        bits.append(f"v{version.strip()}")
    if document_type and document_type.lower() in {"citizen_charter", "procedure"}:
        # Prefer human label for charter when filename looks like one.
        lower = original_filename.lower()
        if "charter" in lower and "Citizen" not in base and "citizen" not in base.lower():
            bits[0] = "Citizen’s Charter"
            if edition:
                bits = [bits[0], edition.strip()]
            elif version:
                bits = [bits[0], f"v{version.strip()}"]
            else:
                bits = [bits[0]]
                year_match = re.search(r"(20\d{2})", original_filename)
                if year_match:
                    bits.append(year_match.group(1))
    return " ".join(part for part in bits if part).strip()


def source_view_url(document_id: str, page_number: int | None = None) -> str:
    """Build a citation URL that opens the PDF on the cited page.

    Browsers / PDF plugins honor the open-action fragment `#page=N`.
    The `?page=N` query is retained for API metadata and page-only redirects.
    """
    url = f"/documents/{document_id}/source"
    if page_number is not None and int(page_number) > 0:
        page = int(page_number)
        url = f"{url}?page={page}#page={page}"
    return url


def source_page_url(document_id: str, page_number: int | None = None) -> str | None:
    """URL that returns only the cited page as a single-page PDF."""
    if page_number is None or int(page_number) <= 0:
        return None
    return f"/documents/{document_id}/source/page/{int(page_number)}"


def resolve_stored_path(stored_file_path: str) -> Path:
    path = Path(stored_file_path)
    if not path.is_absolute():
        path = documents_root() / path
    return path.resolve()


def persist_uploaded_document(
    file_bytes: bytes,
    *,
    document_id: str | None = None,
    filename: str | None = None,
    content_type: str | None = None,
    document_type: str | None = None,
    title: str | None = None,
    version: str | None = None,
    edition: str | None = None,
    source_label: str | None = None,
    page_count: int | None = None,
    session: Session | None = None,
) -> SourceDocument:
    """Write file bytes to disk and upsert the SourceDocument PostgreSQL row."""
    doc_id = (document_id or str(uuid.uuid4())).strip()
    original = safe_filename(filename)
    relative_dir = Path(doc_id)
    absolute_dir = documents_root() / relative_dir
    absolute_dir.mkdir(parents=True, exist_ok=True)
    absolute_path = absolute_dir / original
    absolute_path.write_bytes(file_bytes)

    # Store path relative to documents root for portability.
    stored_rel = str(relative_dir / original).replace("\\", "/")
    label = (source_label or "").strip() or build_source_label(
        original_filename=original,
        title=title,
        version=version,
        edition=edition,
        document_type=document_type,
    )

    owns_session = session is None
    if owns_session:
        from app.db.session import get_session_factory

        session = get_session_factory()()
    assert session is not None
    try:
        row = session.get(SourceDocument, doc_id)
        if row is None:
            row = SourceDocument(id=doc_id)
            session.add(row)
        row.original_filename = original
        row.stored_file_path = stored_rel
        row.document_type = (document_type or "").strip() or None
        row.source_label = label
        row.version = (version or "").strip() or None
        row.edition = (edition or "").strip() or None
        row.content_type = (content_type or "").strip() or _guess_content_type(original)
        row.byte_size = len(file_bytes)
        row.page_count = page_count
        session.commit()
        session.refresh(row)
        logger.info(
            "Persisted source document id=%s file=%s bytes=%s",
            doc_id,
            stored_rel,
            len(file_bytes),
        )
        return row
    except Exception:
        session.rollback()
        raise
    finally:
        if owns_session:
            session.close()


def is_source_file_available(row: SourceDocument | None) -> bool:
    if row is None:
        return False
    try:
        path = resolve_stored_path(row.stored_file_path)
    except Exception:
        return False
    return path.is_file()


def get_source_document(document_id: str, session: Session | None = None) -> SourceDocument | None:
    owns_session = session is None
    if owns_session:
        from app.db.session import get_session_factory

        session = get_session_factory()()
    assert session is not None
    try:
        return session.get(SourceDocument, document_id)
    finally:
        if owns_session:
            session.close()


def resolve_citation_document(
    document_id: str | None,
    *,
    session: Session | None = None,
) -> SourceDocument | None:
    """Return SourceDocument only when the DB row and stored PDF both exist."""
    doc_id = (document_id or "").strip()
    if not doc_id:
        return None
    row = get_source_document(doc_id, session=session)
    if not is_source_file_available(row):
        return None
    return row


def citation_readiness_for_document_id(document_id: str | None) -> dict[str, Any]:
    doc_id = (document_id or "").strip()
    if not doc_id:
        return {
            "document_id": None,
            "source_documents_row": False,
            "pdf_stored": False,
            "level2_citation_ready": False,
            "message": "PDF source unavailable. Re-index this document to enable PDF viewing.",
        }
    row = get_source_document(doc_id)
    has_row = row is not None
    pdf_ok = is_source_file_available(row)
    ready = has_row and pdf_ok
    return {
        "document_id": doc_id,
        "source_documents_row": has_row,
        "pdf_stored": pdf_ok,
        "level2_citation_ready": ready,
        "original_filename": row.original_filename if row else None,
        "source_label": row.source_label if row else None,
        "message": None
        if ready
        else "PDF source unavailable. Re-index this document to enable PDF viewing.",
    }


def find_source_document_by_filename(
    filename: str | None,
    session: Session | None = None,
) -> SourceDocument | None:
    name = safe_filename(filename)
    if not name:
        return None
    owns_session = session is None
    if owns_session:
        from app.db.session import get_session_factory

        session = get_session_factory()()
    assert session is not None
    try:
        exact = (
            session.query(SourceDocument)
            .filter(SourceDocument.original_filename == name)
            .order_by(SourceDocument.uploaded_at.desc())
            .first()
        )
        if exact is not None:
            return exact
        # Soft match on stem for renamed uploads.
        stem = Path(name).stem.lower()
        rows = session.query(SourceDocument).order_by(SourceDocument.uploaded_at.desc()).all()
        for row in rows:
            if Path(row.original_filename).stem.lower() == stem:
                return row
            if stem and stem in (row.original_filename or "").lower():
                return row
            if stem and stem in (row.source_label or "").lower():
                return row
        return None
    finally:
        if owns_session:
            session.close()


def source_document_payload(
    row: SourceDocument,
    *,
    page_number: int | None = None,
) -> dict[str, Any]:
    return {
        "document_id": row.id,
        "original_filename": row.original_filename,
        "stored_file_path": row.stored_file_path,
        "document_type": row.document_type,
        "source_label": row.source_label,
        "version": row.version,
        "edition": row.edition,
        "content_type": row.content_type or "application/pdf",
        "byte_size": row.byte_size,
        "page_count": row.page_count,
        "page_number": page_number,
        "page_width": row.page_width,
        "page_height": row.page_height,
        "uploaded_at": row.uploaded_at.isoformat() if row.uploaded_at else None,
        "source_view_url": source_view_url(row.id, page_number),
        "source_page_url": source_page_url(row.id, page_number),
        "open_fragment": f"#page={int(page_number)}" if page_number else None,
    }


def _guess_content_type(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        return "application/pdf"
    if suffix in {".png"}:
        return "image/png"
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix in {".tif", ".tiff"}:
        return "image/tiff"
    return "application/octet-stream"
