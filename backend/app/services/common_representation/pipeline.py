"""Isolated global PDF layout pipeline.

PDF bytes → existing extract_pdf → build_page_geometry → layout document
→ structure-aware chunks. Not wired to Chroma or ingestion.
"""
from __future__ import annotations

from .adapters import build_page_geometry, build_page_geometries
from .chunker import chunk_document_record
from .layout import LayoutBuild, build_layout_document, inspect_layout
from .types import PageGeometry


def geometries_from_extraction_pages(pages: list) -> list[PageGeometry]:
    """Normalize already-extracted pages. Does not open a PDF."""
    if not pages:
        return []
    return build_page_geometries(pages)


def build_layout_from_extraction(
    pages: list,
    *,
    document_id: str,
    source_filename: str,
) -> LayoutBuild:
    geometries = [build_page_geometry(page) for page in pages]
    return build_layout_document(
        geometries,
        document_id=document_id,
        source_filename=source_filename,
    )


def inspect_pdf_bytes(
    pdf_bytes: bytes,
    *,
    document_id: str,
    source_filename: str,
    target_chars: int = 1200,
    max_chars: int = 1800,
    overlap_chars: int = 150,
) -> dict:
    """Run the global engine on a PDF and return inspectable JSON.

    Uses ``extract_pdf`` as-is. Does not ingest, write Chroma, or modify
    source files.
    """
    from app.utils.pdf.pymupdf_extractor import extract_pdf

    extracted = extract_pdf(pdf_bytes)
    build = build_layout_from_extraction(
        extracted.pages,
        document_id=document_id,
        source_filename=source_filename,
    )
    report = inspect_layout(
        build,
        target_chars=target_chars,
        max_chars=max_chars,
        overlap_chars=overlap_chars,
    )
    report["used_ocr_fallback"] = extracted.used_ocr_fallback
    report["extraction_methods"] = [page.method for page in extracted.pages]
    return report


def chunk_layout(build: LayoutBuild, **kwargs):
    return chunk_document_record(build.document, **kwargs)
