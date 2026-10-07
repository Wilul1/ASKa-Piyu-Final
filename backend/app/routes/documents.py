"""Authenticated document source endpoints for citation-grounded PDF viewing."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response

from app.models.db_models import SourceDocument, User
from app.models.schemas import DocumentSourceMetaSchema
from app.services.article_rag_indexer import infer_rag_audience_from_document
from app.services.auth import get_current_user
from app.services.citation_pdf import extract_citation_pages_pdf
from app.services.document_storage import (
    get_source_document,
    is_source_pdf_resolvable,
    resolve_pdf_source,
    source_document_payload,
)

router = APIRouter(prefix="/documents", tags=["Source Documents"])


def _assert_can_view_source(user: User, row: SourceDocument) -> None:
    """Faculty-only PDFs: admin + faculty only."""
    role = (user.role or "student").strip().lower()
    if role == "admin":
        return
    audience = infer_rag_audience_from_document(
        filename=row.original_filename,
        title=row.source_label,
        document_type=row.document_type,
    )
    if audience == "faculty" and role != "faculty":
        raise HTTPException(
            status_code=403,
            detail="This source document is restricted to faculty accounts.",
        )


def _load_source_row(document_id: str, user: User) -> SourceDocument:
    """Resolve and authorize a citation's source row.

    Serving priority is local-file-first, then durable ``pdf_data`` in
    Postgres (see :func:`resolve_pdf_source`) -- callers get back only the
    authorized row here; which bytes to stream is decided at the call site
    via :func:`resolve_pdf_source`, never an arbitrary client-supplied path.
    """
    row = get_source_document(document_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Source document not found")
    _assert_can_view_source(user, row)
    if not is_source_pdf_resolvable(row):
        raise HTTPException(
            status_code=404,
            detail="Stored source file is missing on disk. Re-ingest the document.",
        )
    return row


@router.get(
    "/{document_id}/source",
    summary="Open the original uploaded source PDF for a citation",
    response_model=None,
)
def get_document_source(
    document_id: str,
    page: int | None = Query(default=None, ge=1, description="1-based page to open"),
    meta: bool = Query(
        default=False,
        description="When true, return JSON viewer metadata instead of the PDF bytes",
    ),
    current_user: User = Depends(get_current_user),
):
    row = _load_source_row(document_id, current_user)

    payload = source_document_payload(row, page_number=page)
    if meta:
        return DocumentSourceMetaSchema(**payload)

    safe_label = (row.source_label or row.original_filename or "source").encode(
        "ascii", "replace"
    ).decode("ascii")
    safe_filename = (row.original_filename or "document.pdf").encode(
        "ascii", "replace"
    ).decode("ascii")
    headers = {
        "X-Document-Id": row.id,
        "X-Source-Label": safe_label,
        "Content-Disposition": f'inline; filename="{safe_filename}"',
    }
    if page is not None:
        headers["X-Source-Page"] = str(page)

    # Serving priority: (A) existing valid local file, (B) durable pdf_data
    # in Postgres, (C) handled above as a 404 by _load_source_row.
    source = resolve_pdf_source(row)
    if isinstance(source, Path):
        return FileResponse(
            path=str(source),
            media_type=row.content_type or "application/pdf",
            filename=safe_filename,
            headers=headers,
        )
    return Response(
        content=source,
        media_type=row.content_type or "application/pdf",
        headers=headers,
    )


@router.get(
    "/{document_id}/source/page/{page_number}",
    summary="Return the cited page range as a focused PDF clip",
    response_model=None,
)
def get_document_source_page(
    document_id: str,
    page_number: int,
    end: int | None = Query(
        default=None,
        ge=1,
        description="Inclusive end page when the cited section spans multiple pages",
    ),
    section: str | None = Query(
        default=None,
        max_length=240,
        description="Cited section title — crops away neighboring services on the page",
    ),
    current_user: User = Depends(get_current_user),
):
    if page_number < 1:
        raise HTTPException(status_code=400, detail="page_number must be >= 1")

    row = _load_source_row(document_id, current_user)
    page_end = end if end is not None and end >= page_number else page_number

    try:
        source = resolve_pdf_source(row)
        page_bytes = extract_citation_pages_pdf(
            source,
            page_start=page_number,
            page_end=page_end,
            section_title=(section or "").strip() or None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail=f"Unable to extract page {page_number} from source PDF.",
        ) from exc

    safe_filename = (row.original_filename or "document.pdf").encode(
        "ascii", "replace"
    ).decode("ascii")
    stem = Path(safe_filename).stem
    if page_end > page_number:
        page_name = f"{stem}-pages-{page_number}-{page_end}.pdf"
    else:
        page_name = f"{stem}-page-{page_number}.pdf"
    headers = {
        "X-Document-Id": row.id,
        "X-Source-Page": str(page_number),
        "X-Source-Page-End": str(page_end),
        "X-Source-Page-Only": "true",
        "Content-Disposition": f'inline; filename="{page_name}"',
    }
    return Response(
        content=page_bytes,
        media_type="application/pdf",
        headers=headers,
    )


@router.get(
    "/{document_id}/source/meta",
    response_model=DocumentSourceMetaSchema,
    summary="JSON metadata for the frontend PDF viewer",
)
def get_document_source_meta(
    document_id: str,
    page: int | None = Query(default=None, ge=1),
    current_user: User = Depends(get_current_user),
) -> DocumentSourceMetaSchema:
    row = _load_source_row(document_id, current_user)
    return DocumentSourceMetaSchema(**source_document_payload(row, page_number=page))
