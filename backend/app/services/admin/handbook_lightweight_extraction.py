"""Heroku-safe, OCR-free structured extraction of the LSPU Student Handbook's
disciplinary-offense table, for app/services/admin/digital_ingestion.py's
review/index job flow.

Deliberately separate from app.utils.pdf.pymupdf_extractor (whose import
graph includes app.utils.ocr.easyocr_engine) and from the "full" local/
Docker pipeline in app/services/admin/knowledge_base_pipeline.py. This
module imports ONLY ``fitz`` (PyMuPDF) at module level, plus a handful of
pure-text helpers from app.services.handbook_policy_processor (which itself
has zero OCR/embedding imports -- confirmed by inspection) -- never
``easyocr``, never ``sentence_transformers``/``torch``. It is safe to import
and call unconditionally on the lightweight Heroku web image.

Table/word-box geometry extraction (``find_tables()``, ``get_text("words")``)
is a pure PyMuPDF operation on a PDF's existing digital content layer; it
never loads an OCR engine or embedding model regardless of page content.
The real safety rule enforced here is a conservative, document-level one,
not a packaging one: this module's entry point,
``extract_structured_handbook_data``, must only ever be called by its
caller (digital_ingestion.process_extraction_preview_job) for a document
that extracted via the pure-digital path -- never one that fell back to the
remote OCR worker. This module does not re-check that itself (it has no
way to -- the OCR decision is made by its caller against the same
page_texts before this is ever invoked); see that call site's guard.
"""
from __future__ import annotations

from dataclasses import dataclass

import fitz  # PyMuPDF

from app.services.handbook_policy_processor import (
    _disciplinary_table_header_row_matches,
    _is_combined_offense_table_header_anchor,
    _is_offense_table_header_anchor,
    is_handbook_policy_text,
)

STATUS_ELIGIBLE = "eligible"
STATUS_ATTEMPTED_NO_MATCH = "attempted_no_match"
STATUS_ERROR = "error"


@dataclass
class LightweightPageExtraction:
    """Minimal structural stand-in for app.utils.pdf.pymupdf_extractor.
    PageExtraction, carrying only the fields
    app.services.handbook_policy_processor's disciplinary-table functions
    actually read (``table_regions``, ``words``, ``text``, ``page_number``).
    Deliberately NOT the real PageExtraction class -- importing that would
    pull in app.utils.ocr.easyocr_engine, which this module's own docstring
    promises never to do. build_handbook_policy_document's ``pdf_pages``
    parameter is duck-typed (no isinstance check), so this is sufficient.
    """

    page_number: int
    text: str
    words: list[dict] | None = None
    table_regions: list[dict] | None = None
    geometry_scale: float = 1.0


def find_candidate_table_pages(page_texts: list[str]) -> list[int]:
    """Cheap, pure-string pre-filter: 1-indexed page numbers whose plain
    text contains the disciplinary-offense table's own repeating header
    anchor line, in either shape PyMuPDF is known to produce for it.

    No PDF access at all -- operates on the exact page_texts already
    produced by digital_ingestion.extract_digital_text_only, so it costs
    nothing beyond a string scan. Deliberately never a hardcoded page
    range: if the table moves in a revised PDF, this still finds it (or
    safely finds nothing, which the caller treats as "no match", never as
    a wrong match).
    """
    candidates: list[int] = []
    for index, text in enumerate(page_texts):
        for raw_line in (text or "").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if _is_offense_table_header_anchor(line) or _is_combined_offense_table_header_anchor(line):
                candidates.append(index + 1)
                break
    return candidates


def _page_word_items(page: "fitz.Page") -> list[dict]:
    """Raw digital-PDF word boxes: text plus x0/y0/x1/y1 in PDF point space.

    Intentionally a narrow duplicate of
    app.utils.pdf.pymupdf_extractor._page_word_items's exact output shape
    (text/x0/y0/x1/y1/cy/height) rather than an import of that module --
    see module docstring. Pure fitz; no OCR involved for a digital PDF's
    own word boxes.
    """
    words = page.get_text("words", sort=True) or []
    items: list[dict] = []
    for word in words:
        if len(word) < 5:
            continue
        x0, y0, x1, y1, text = word[:5]
        text = str(text).strip()
        if not text:
            continue
        items.append(
            {
                "text": text,
                "x0": float(x0),
                "y0": float(y0),
                "x1": float(x1),
                "y1": float(y1),
                "cy": (float(y0) + float(y1)) / 2,
                "height": max(1.0, float(y1) - float(y0)),
            }
        )
    return items


def _extract_table_regions(page: "fitz.Page") -> list[dict]:
    """Best-effort native PyMuPDF table detection for one page.

    Narrow duplicate of
    app.utils.pdf.pymupdf_extractor._extract_table_regions -- see module
    docstring for why this is copied rather than imported.
    """
    finder = getattr(page, "find_tables", None)
    if finder is None:
        return []
    try:
        result = finder()
        tables = list(getattr(result, "tables", None) or [])
    except Exception:
        return []

    regions: list[dict] = []
    for table in tables:
        try:
            bbox = [float(v) for v in table.bbox]
            rows = [
                [str(cell).strip() if cell is not None else "" for cell in row]
                for row in (table.extract() or [])
            ]
        except Exception:
            continue
        regions.append({"bbox": bbox, "rows": rows})
    return regions


def extract_structured_handbook_data(file_bytes: bytes, page_texts: list[str]) -> dict | None:
    """Returns the JSON-serializable ``handbook_structured`` payload for
    this document, or ``None`` if it does not even look like
    handbook-policy text (the cheapest possible negative -- no table/word
    extraction attempted at all in that case).

    Caller contract (enforced by the caller, not here): this must only be
    invoked for a document whose extraction_method is already known to be
    the pure-digital path (never the remote-OCR-worker fallback) -- see
    module docstring.
    """
    full_text = "\n".join(page_texts)
    if not is_handbook_policy_text(full_text):
        return None

    candidate_pages = find_candidate_table_pages(page_texts)
    if not candidate_pages:
        return {
            "status": STATUS_ATTEMPTED_NO_MATCH,
            "candidate_pages": [],
            "matched_pages": [],
            "table_regions_by_page": {},
            "words_by_page": {},
        }

    doc = fitz.open(stream=file_bytes, filetype="pdf")
    try:
        table_regions_by_page: dict[str, list[dict]] = {}
        matched_pages: list[int] = []
        for page_number in candidate_pages:
            index = page_number - 1
            if index < 0 or index >= len(doc):
                continue
            page = doc[index]
            regions = _extract_table_regions(page)
            table_regions_by_page[str(page_number)] = regions
            for table in regions:
                rows = table.get("rows") or []
                if rows and _disciplinary_table_header_row_matches(rows[0]):
                    matched_pages.append(page_number)
                    break

        words_by_page: dict[str, list[dict]] = {}
        for page_number in matched_pages:
            index = page_number - 1
            page = doc[index]
            words_by_page[str(page_number)] = _page_word_items(page)
    finally:
        doc.close()

    status = STATUS_ELIGIBLE if matched_pages else STATUS_ATTEMPTED_NO_MATCH
    return {
        "status": status,
        "candidate_pages": candidate_pages,
        "matched_pages": matched_pages,
        "table_regions_by_page": table_regions_by_page,
        "words_by_page": words_by_page,
    }


def reconstruct_page_extractions(
    page_texts: list[str],
    handbook_structured: dict,
) -> list[LightweightPageExtraction]:
    """Rebuilds the minimal per-page objects
    build_handbook_policy_document(pdf_pages=...) needs, from the
    persisted handbook_structured payload -- never from a re-opened PDF.
    """
    table_regions_by_page = handbook_structured.get("table_regions_by_page") or {}
    words_by_page = handbook_structured.get("words_by_page") or {}
    pages: list[LightweightPageExtraction] = []
    for index, text in enumerate(page_texts):
        page_number = index + 1
        key = str(page_number)
        pages.append(
            LightweightPageExtraction(
                page_number=page_number,
                text=text,
                words=words_by_page.get(key),
                table_regions=table_regions_by_page.get(key),
            )
        )
    return pages
