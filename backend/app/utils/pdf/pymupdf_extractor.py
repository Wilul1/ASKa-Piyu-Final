"""PyMuPDF (fitz) utilities for digital text extraction and scanned-page rendering."""

from __future__ import annotations

from dataclasses import dataclass

import fitz
from PIL import Image

from app.config import settings
from app.utils.ocr.easyocr_engine import extract_text_and_boxes_from_pil_image


@dataclass
class PageExtraction:
    page_number: int
    text: str
    method: str  # "digital" | "ocr"
    words: list[dict] | None = None  # word boxes: text, x0, y0, x1, y1, cy, height
    table_regions: list[dict] | None = None  # PyMuPDF native table detection, if any
    geometry_scale: float = 1.0  # multiply words coords by 1/geometry_scale for PDF points


@dataclass
class PdfExtractionResult:
    pages: list[PageExtraction]
    used_ocr_fallback: bool

    @property
    def full_text(self) -> str:
        parts: list[str] = []
        for page in self.pages:
            if page.text.strip():
                parts.append(page.text.strip())
        return "\n\n".join(parts)


def extract_pdf(pdf_bytes: bytes) -> PdfExtractionResult:
    """
    Extract text from a multi-page PDF.

    Per page: use the text layer when sufficient; otherwise render and OCR.
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        pages = _extract_pages_hybrid(doc)
        used_ocr = any(p.method == "ocr" for p in pages)
        return PdfExtractionResult(pages=pages, used_ocr_fallback=used_ocr)
    finally:
        doc.close()


def _extract_pages_hybrid(doc: fitz.Document) -> list[PageExtraction]:
    zoom = settings.pdf_ocr_zoom
    matrix = fitz.Matrix(zoom, zoom)
    pages: list[PageExtraction] = []
    min_chars = settings.min_chars_per_page_for_digital_pdf

    for index in range(len(doc)):
        page = doc[index]
        word_items = _page_word_items(page)
        digital = _extract_layout_text(page, word_items=word_items).strip()

        if len(digital) >= min_chars:
            pages.append(
                PageExtraction(
                    page_number=index + 1,
                    text=digital,
                    method="digital",
                    words=word_items or None,
                    table_regions=_extract_table_regions(page) or None,
                    geometry_scale=1.0,
                )
            )
            continue

        pixmap = page.get_pixmap(matrix=matrix, alpha=False)
        image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
        ocr_text, ocr_boxes = extract_text_and_boxes_from_pil_image(image)
        ocr_text = ocr_text.strip()

        # Prefer digital remnants merged with OCR when both exist on sparse pages
        if digital and ocr_text:
            combined = f"{digital}\n{ocr_text}".strip()
        else:
            combined = ocr_text or digital

        if ocr_text:
            page_words: list[dict] | None = ocr_boxes or None
            scale = float(zoom) if zoom else 1.0
        elif digital:
            page_words = word_items or None
            scale = 1.0
        else:
            page_words = None
            scale = 1.0

        pages.append(
            PageExtraction(
                page_number=index + 1,
                text=combined,
                method="ocr" if ocr_text or not digital else "digital",
                words=page_words,
                geometry_scale=scale,
            )
        )

    return pages


def _page_word_items(page: fitz.Page) -> list[dict]:
    """Raw digital-PDF word boxes: text plus x0/y0/x1/y1 in PDF point space."""
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


def _extract_table_regions(page: fitz.Page) -> list[dict]:
    """Best-effort native PyMuPDF table detection. Returns [] if unavailable."""
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


def _cluster_rows(items: list[dict]) -> list[list[dict]]:
    """Group word items into visual table/text rows by Y proximity."""
    if not items:
        return []

    ordered = sorted(items, key=lambda item: (item["cy"], item["x0"]))
    heights = sorted(item["height"] for item in ordered)
    median_height = heights[len(heights) // 2]
    row_threshold = max(3.0, median_height * 0.65)

    rows: list[list[dict]] = []
    for item in ordered:
        if not rows:
            rows.append([item])
            continue

        current = rows[-1]
        current_y = sum(cell["cy"] for cell in current) / len(current)
        if abs(item["cy"] - current_y) <= row_threshold:
            current.append(item)
        else:
            rows.append([item])

    return rows


def _rows_to_text(rows: list[list[dict]]) -> str:
    """Render clustered rows into pipe-delimited lines so columns stay visible."""
    if not rows:
        return ""

    all_heights = sorted(cell["height"] for row in rows for cell in row)
    median_height = all_heights[len(all_heights) // 2] if all_heights else 10.0

    lines: list[str] = []
    for row in rows:
        ordered_row = sorted(row, key=lambda item: item["x0"])
        column_gap = max(median_height * 2.0, 18)

        parts: list[str] = []
        previous_x1: float | None = None
        for item in ordered_row:
            if previous_x1 is not None and item["x0"] - previous_x1 > column_gap:
                parts.append("|")
            parts.append(item["text"])
            previous_x1 = item["x1"]

        line = " ".join(parts).strip()
        if line:
            lines.append(line)

    return "\n".join(lines)


def _extract_layout_text(page: fitz.Page, *, word_items: list[dict] | None = None) -> str:
    """Extract digital PDF words by visual row so tables keep useful order."""
    items = word_items if word_items is not None else _page_word_items(page)
    if not items:
        return (page.get_text("text", sort=True) or "").strip()

    text = _rows_to_text(_cluster_rows(items))
    return text or (page.get_text("text", sort=True) or "").strip()
