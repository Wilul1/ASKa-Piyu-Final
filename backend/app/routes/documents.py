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
    resolve_stored_path,
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


def _load_source_row(document_id: str, user: User) -> tuple[SourceDocument, Path]:
    row = get_source_document(document_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Source document not found")
    _assert_can_view_source(user, row)
    try:
        path = resolve_stored_path(row.stored_file_path)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Source document not found") from exc
    if not path.is_file():
        raise HTTPException(
            status_code=404,
            detail="Stored source file is missing on disk. Re-ingest the document.",
        )
    return row, path


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
    row, path = _load_source_row(document_id, current_user)

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

    return FileResponse(
        path=str(path),
        media_type=row.content_type or "application/pdf",
        filename=safe_filename,
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

    row, path = _load_source_row(document_id, current_user)
    page_end = end if end is not None and end >= page_number else page_number

    try:
        page_bytes = extract_citation_pages_pdf(
            path,
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
    row, _path = _load_source_row(document_id, current_user)
    return DocumentSourceMetaSchema(**source_document_payload(row, page_number=page))
