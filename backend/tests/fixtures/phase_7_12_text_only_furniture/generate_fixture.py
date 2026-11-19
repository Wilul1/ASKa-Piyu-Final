"""Deterministic generator for the Phase 7.12 text-only furniture fixture.

Creates new files only under this directory. Does not modify production
source, existing tests, OCR settings, or application data.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import fitz

DIR = Path(__file__).resolve().parent
PAGE_WIDTH = 468.0
PAGE_HEIGHT = 612.0
FONT = "helv"
HEADER_TEXT = "Policy Manual Running Header"
FOOTER_TEXT = "Internal Review Copy Only"
SECTION_HEADING = "Section Overview"
TITLE = "Controlled Furniture Fixture"
TABLE_HEADER = ("Item", "Status", "Notes")
CONTENT_PAGE_COUNT = 7  # PDF pages 2-8
TOTAL_PAGES = 1 + CONTENT_PAGE_COUNT  # 8
RENDER_ZOOM = 2.0  # matches settings.pdf_ocr_zoom; recorded, not changed

# Intended insert_text baselines (PyMuPDF y is baseline, not box top).
HEADER_Y = 28.0
SECTION_Y = 78.0
BODY_Y0 = 108.0
TABLE_Y0 = 300.0
FOOTER_Y = 578.0
FOLIO_Y = 598.0
TITLE_Y = 200.0
ODD_X = 36.0  # duplex: odd content pages
EVEN_X = 96.0
BODY_X = 48.0
FOLIO_X = 220.0


def _duplex_x(pdf_page_number: int) -> float:
    """Odd PDF pages use ODD_X; even PDF pages use EVEN_X (duplex shift)."""
    return ODD_X if pdf_page_number % 2 == 1 else EVEN_X


def _body_lines(pdf_page_number: int) -> list[str]:
    n = pdf_page_number
    lines = [
        f"Ordinary body paragraph for content page {n}.",
        "This sentence is unique to the page so recurrence is not accidental.",
    ]
    if n == 5:
        lines.extend(
            [
                "1. Record attendance at the start of each session.",
                "2. Submit the weekly summary before the deadline.",
            ]
        )
    elif n == 6:
        lines.append("The applicant must provide-")
    elif n == 7:
        lines.append("ed supporting documents as listed below.")
    else:
        lines.append("Body text continues with a complete sentence on this page.")
    return lines


def _draw_table(page: fitz.Page, x0: float, y0: float) -> None:
    col_w = [70.0, 70.0, 140.0]
    row_h = 16.0
    rows = [
        list(TABLE_HEADER),
        ["Alpha", "Open", "First row"],
        ["Beta", "Closed", "Second row"],
    ]
    width = sum(col_w)
    height = row_h * len(rows)
    page.draw_rect(fitz.Rect(x0, y0, x0 + width, y0 + height), color=(0, 0, 0), width=0.6)
    acc = x0
    for w in col_w[:-1]:
        acc += w
        page.draw_line(fitz.Point(acc, y0), fitz.Point(acc, y0 + height), color=(0, 0, 0), width=0.6)
    for i in range(1, len(rows)):
        y = y0 + i * row_h
        page.draw_line(fitz.Point(x0, y), fitz.Point(x0 + width, y), color=(0, 0, 0), width=0.6)
    for r, row in enumerate(rows):
        acc = x0
        for c, cell in enumerate(row):
            page.insert_text(
                (acc + 4.0, y0 + r * row_h + 11.0),
                cell,
                fontsize=8,
                fontname=FONT,
            )
            acc += col_w[c]


def build_digital_document() -> fitz.Document:
    doc = fitz.open()
    # Page 1: title page. No running header/footer/folio/table.
    title = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    title.insert_text((70.0, TITLE_Y), TITLE, fontsize=16, fontname=FONT)
    title.insert_text(
        (70.0, TITLE_Y + 28.0),
        "Characterization fixture. Not a source document.",
        fontsize=10,
        fontname=FONT,
    )

    for pdf_n in range(2, TOTAL_PAGES + 1):
        page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
        hx = _duplex_x(pdf_n)
        page.insert_text((hx, HEADER_Y), HEADER_TEXT, fontsize=9, fontname=FONT)
        page.insert_text((BODY_X, SECTION_Y), SECTION_HEADING, fontsize=11, fontname=FONT)
        y = BODY_Y0
        for line in _body_lines(pdf_n):
            page.insert_text((BODY_X, y), line, fontsize=10, fontname=FONT)
            y += 16.0
        if pdf_n in (4, 6):
            _draw_table(page, BODY_X, TABLE_Y0)
        page.insert_text((hx, FOOTER_Y), FOOTER_TEXT, fontsize=9, fontname=FONT)
        folio = str(pdf_n - 1)  # 1..7 on content pages; variable
        page.insert_text((FOLIO_X, FOLIO_Y), folio, fontsize=9, fontname=FONT)
    return doc


def _pdf_bytes(doc: fitz.Document) -> bytes:
    return doc.tobytes(deflate=True, garbage=4)


def write_ocr_twin(digital: fitz.Document, dest: Path, png_dir: Path) -> dict:
    png_dir.mkdir(parents=True, exist_ok=True)
    twin = fitz.open()
    rasters = []
    matrix = fitz.Matrix(RENDER_ZOOM, RENDER_ZOOM)
    for index in range(digital.page_count):
        pix = digital[index].get_pixmap(matrix=matrix, alpha=False)
        png_path = png_dir / f"page_{index + 1:02d}_zoom{RENDER_ZOOM:.0f}.png"
        pix.save(str(png_path))
        twin_page = twin.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
        twin_page.insert_image(twin_page.rect, pixmap=pix)
        rasters.append(
            {
                "page_number": index + 1,
                "png": png_path.name,
                "pixmap_width": pix.width,
                "pixmap_height": pix.height,
                "zoom": RENDER_ZOOM,
            }
        )
    twin.save(dest, deflate=True, garbage=4)
    twin.close()
    return {"ocr_twin_pdf": dest.name, "rasters": rasters}


def main() -> None:
    def _word_fingerprint(doc: fitz.Document) -> str:
        parts: list[str] = []
        for index in range(doc.page_count):
            for word in doc[index].get_text("words") or []:
                parts.append(
                    f"{index}:{word[0]:.2f}:{word[1]:.2f}:{word[2]:.2f}:{word[3]:.2f}:{word[4]}"
                )
        return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()

    first = build_digital_document()
    bytes_a = _pdf_bytes(first)
    fp_a = _word_fingerprint(first)
    second = build_digital_document()
    fp_b = _word_fingerprint(second)
    digital_path = DIR / "text_only_furniture_digital.pdf"
    digital_path.write_bytes(bytes_a)
    first.close()
    second.close()

    digital = fitz.open(digital_path)
    try:
        raster_info = write_ocr_twin(
            digital,
            DIR / "text_only_furniture_ocr_twin.pdf",
            DIR / "rasters",
        )
        page_rects = [
            {
                "page_number": i + 1,
                "width": float(digital[i].rect.width),
                "height": float(digital[i].rect.height),
                "rotation": int(digital[i].rotation),
            }
            for i in range(digital.page_count)
        ]
    finally:
        digital.close()

    manifest = {
        "generator": Path(__file__).name,
        "page_width": PAGE_WIDTH,
        "page_height": PAGE_HEIGHT,
        "page_count": TOTAL_PAGES,
        "deterministic_repeat_word_geometry_match": fp_a == fp_b,
        "word_geometry_sha256": fp_a,
        "digital_pdf_bytes_not_stable": True,
        "digital_sha256": hashlib.sha256(bytes_a).hexdigest(),
        "header_text": HEADER_TEXT,
        "footer_text": FOOTER_TEXT,
        "section_heading": SECTION_HEADING,
        "title": TITLE,
        "positions": {
            "header_y_baseline": HEADER_Y,
            "section_y_baseline": SECTION_Y,
            "body_y0_baseline": BODY_Y0,
            "table_y0": TABLE_Y0,
            "footer_y_baseline": FOOTER_Y,
            "folio_y_baseline": FOLIO_Y,
            "title_y_baseline": TITLE_Y,
            "odd_header_footer_x": ODD_X,
            "even_header_footer_x": EVEN_X,
            "body_x": BODY_X,
            "folio_x": FOLIO_X,
        },
        "pages": {
            "1": {
                "role": "title",
                "running_header": False,
                "running_footer": False,
                "folio": False,
                "section_heading": False,
                "native_table": False,
                "expected": "title is not a running header",
            },
            **{
                str(n): {
                    "role": "content",
                    "running_header": True,
                    "running_footer": True,
                    "folio": str(n - 1),
                    "duplex_x": _duplex_x(n),
                    "section_heading": True,
                    "native_table": n in (4, 6),
                    "numbered_items": n == 5,
                    "hyphen_incomplete": n == 6,
                    "hyphen_completion": n == 7,
                }
                for n in range(2, TOTAL_PAGES + 1)
            },
        },
        "expected_classifications": {
            "header": "candidate text-only furniture; not a native table",
            "footer": "candidate text-only furniture; not a native table",
            "folio": "variable page number; 7.4A isolation candidate; not header identity",
            "section_heading": "negative control: repeated body heading, not furniture",
            "table": "negative control: native table with repeated column headings",
            "title": "negative control: one-off top title, not a running header",
        },
        "page_rects": page_rects,
        **raster_info,
    }
    (DIR / "provenance").mkdir(exist_ok=True)
    (DIR / "provenance" / "generation_manifest.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "digital": str(digital_path),
                "sha256": manifest["digital_sha256"],
                "word_geometry_deterministic": manifest[
                    "deterministic_repeat_word_geometry_match"
                ],
            }
        )
    )


if __name__ == "__main__":
    main()
