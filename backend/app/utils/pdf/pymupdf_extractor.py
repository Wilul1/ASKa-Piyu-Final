"""PyMuPDF (fitz) utilities for digital text extraction and scanned-page rendering."""

from __future__ import annotations

from dataclasses import dataclass

import fitz
from PIL import Image

from app.config import settings
from app.utils.ocr.easyocr_engine import extract_text_from_pil_image


@dataclass
class PageExtraction:
    page_number: int
    text: str
    method: str  # "digital" | "ocr"


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
        digital = _extract_layout_text(page).strip()

        if len(digital) >= min_chars:
            pages.append(
                PageExtraction(page_number=index + 1, text=digital, method="digital")
            )
            continue

        pixmap = page.get_pixmap(matrix=matrix, alpha=False)
        image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
        ocr_text = extract_text_from_pil_image(image).strip()

        # Prefer digital remnants merged with OCR when both exist on sparse pages
        if digital and ocr_text:
            combined = f"{digital}\n{ocr_text}".strip()
        else:
            combined = ocr_text or digital

        pages.append(
            PageExtraction(
                page_number=index + 1,
                text=combined,
                method="ocr" if ocr_text or not digital else "digital",
            )
        )

    return pages


def _extract_layout_text(page: fitz.Page) -> str:
    """Extract digital PDF words by visual row so tables keep useful order."""
    words = page.get_text("words", sort=True) or []
    if not words:
        return (page.get_text("text", sort=True) or "").strip()

    items = []
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
                "x1": float(x1),
                "cy": (float(y0) + float(y1)) / 2,
                "height": max(1.0, float(y1) - float(y0)),
            }
        )

    if not items:
        return (page.get_text("text", sort=True) or "").strip()

    items.sort(key=lambda item: (item["cy"], item["x0"]))
    heights = sorted(item["height"] for item in items)
    median_height = heights[len(heights) // 2]
    row_threshold = max(3.0, median_height * 0.65)

    rows: list[list[dict]] = []
    for item in items:
        if not rows:
            rows.append([item])
            continue

        current = rows[-1]
        current_y = sum(cell["cy"] for cell in current) / len(current)
        if abs(item["cy"] - current_y) <= row_threshold:
            current.append(item)
        else:
            rows.append([item])

    lines: list[str] = []
    for row in rows:
        row.sort(key=lambda item: item["x0"])
        column_gap = max(median_height * 2.0, 18)

        parts: list[str] = []
        previous_x1: float | None = None
        for item in row:
            if previous_x1 is not None and item["x0"] - previous_x1 > column_gap:
                parts.append("|")
            parts.append(item["text"])
            previous_x1 = item["x1"]

        line = " ".join(parts).strip()
        if line:
            lines.append(line)

    return "\n".join(lines)
