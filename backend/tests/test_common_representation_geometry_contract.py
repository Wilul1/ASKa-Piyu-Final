"""Phase 7.3 geometry-contract tests: page dimensions and coordinate scale.

These tests complete the shared geometry representation so page size and
the extraction coordinate scale are interpretable. They do not change
reconstruction algorithms, thresholds, or production wiring.
"""
from __future__ import annotations

import sys
from pathlib import Path

import fitz
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.services.admin.handbook_lightweight_extraction import (  # noqa: E402
    LightweightPageExtraction,
    reconstruct_page_extractions,
)
from app.services.common_representation.adapters import build_page_geometry  # noqa: E402
from app.services.common_representation.types import PageGeometry  # noqa: E402
from app.utils.pdf.pymupdf_extractor import PageExtraction, extract_pdf  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parents[1]
DOCUMENTS_DIR = BACKEND_DIR / "data" / "documents"

_PREFERRED_PARENTS = {
    "Laguna State Polytechnic University-CC_2026-1st Edition.pdf": "da4a1832-7242-4e94-8ba6-bc0b9f2294bf",
    "LSPU Student Handbook.pdf": "d9bf05ce-fcab-4629-ad4c-4f869481189f",
    "pipeline_demo_test.pdf": "aaf5619a-8996-43e7-b6c0-af6efcf9f4cc",
}

_PIXEL_WORD = {
    "text": "Hello",
    "x0": 100.0,
    "y0": 200.0,
    "x1": 180.0,
    "y1": 230.0,
    "cy": 215.0,
    "height": 30.0,
}
_POINT_WORD = {
    "text": "Hello",
    "x0": 50.0,
    "y0": 100.0,
    "x1": 90.0,
    "y1": 115.0,
    "cy": 107.5,
    "height": 15.0,
}


def _require_pdf(filename: str) -> Path:
    preferred = DOCUMENTS_DIR / _PREFERRED_PARENTS.get(filename, "") / filename
    if preferred.is_file():
        return preferred
    matches = sorted(path for path in DOCUMENTS_DIR.rglob(filename) if path.is_file())
    if not matches:
        pytest.fail(
            f"Geometry-contract fixture unavailable: {filename!r} was not found "
            f"under {DOCUMENTS_DIR}."
        )
    return matches[0]


def _page_rect(pdf_path: Path, page_number: int = 1) -> tuple[float, float]:
    document = fitz.open(str(pdf_path))
    try:
        page = document[page_number - 1]
        return float(page.rect.width), float(page.rect.height)
    finally:
        document.close()


def _make_digital_pdf(width: float, height: float, text: str) -> bytes:
    document = fitz.open()
    try:
        page = document.new_page(width=width, height=height)
        page.insert_text((72, 72), text)
        return document.tobytes()
    finally:
        document.close()


# ---------------------------------------------------------------------------
# A. Digital PDF dimensions from actual Charter and Handbook pages
# ---------------------------------------------------------------------------


def test_charter_and_handbook_page_dimensions_reach_page_geometry():
    charter = _require_pdf("Laguna State Polytechnic University-CC_2026-1st Edition.pdf")
    handbook = _require_pdf("LSPU Student Handbook.pdf")
    charter_rect = _page_rect(charter)
    handbook_rect = _page_rect(handbook)

    assert charter_rect[0] == pytest.approx(595.3, abs=1.0)
    assert charter_rect[1] == pytest.approx(841.9, abs=1.0)
    assert handbook_rect[0] == pytest.approx(468.0, abs=1.0)
    assert handbook_rect[1] == pytest.approx(612.0, abs=1.0)
    assert charter_rect != handbook_rect

    charter_page = PageExtraction(
        page_number=1,
        text="charter",
        method="digital",
        words=[dict(_POINT_WORD)],
        geometry_scale=1.0,
        page_width=charter_rect[0],
        page_height=charter_rect[1],
        coordinate_width=charter_rect[0],
        coordinate_height=charter_rect[1],
    )
    handbook_page = PageExtraction(
        page_number=1,
        text="handbook",
        method="digital",
        words=[dict(_POINT_WORD)],
        geometry_scale=1.0,
        page_width=handbook_rect[0],
        page_height=handbook_rect[1],
        coordinate_width=handbook_rect[0],
        coordinate_height=handbook_rect[1],
    )
    charter_geometry = build_page_geometry(charter_page)
    handbook_geometry = build_page_geometry(handbook_page)

    assert charter_geometry.width == pytest.approx(charter_rect[0])
    assert charter_geometry.height == pytest.approx(charter_rect[1])
    assert handbook_geometry.width == pytest.approx(handbook_rect[0])
    assert handbook_geometry.height == pytest.approx(handbook_rect[1])
    assert charter_geometry.geometry_scale == 1.0
    assert handbook_geometry.geometry_scale == 1.0
    assert charter_geometry.coordinate_width == pytest.approx(charter_rect[0])
    assert charter_geometry.coordinate_height == pytest.approx(charter_rect[1])
    assert handbook_geometry.coordinate_width == pytest.approx(handbook_rect[0])
    assert handbook_geometry.coordinate_height == pytest.approx(handbook_rect[1])
    assert charter_geometry.regions[0].bbox == (
        _POINT_WORD["x0"],
        _POINT_WORD["y0"],
        _POINT_WORD["x1"],
        _POINT_WORD["y1"],
    )


def test_extract_pdf_preserves_actual_page_rect_and_digital_scale():
    """Production extract_pdf() copies page.rect; it does not estimate size
    from word boxes or hardcode a Charter/Handbook dimension."""
    letter_bytes = _make_digital_pdf(
        612.0,
        792.0,
        "The student handbook explains enrollment procedures for incoming freshmen.",
    )
    a4_bytes = _make_digital_pdf(
        595.28,
        841.89,
        "The citizen charter lists frontline services offered by university offices.",
    )

    letter = extract_pdf(letter_bytes).pages[0]
    a4 = extract_pdf(a4_bytes).pages[0]

    assert letter.page_width == pytest.approx(612.0)
    assert letter.page_height == pytest.approx(792.0)
    assert a4.page_width == pytest.approx(595.28)
    assert a4.page_height == pytest.approx(841.89)
    assert letter.geometry_scale == 1.0
    assert a4.geometry_scale == 1.0
    assert letter.method == "digital"
    assert a4.method == "digital"
    assert letter.rotation == 0
    assert letter.page_origin_x == 0.0
    assert letter.page_origin_y == 0.0
    assert letter.raster_width is None
    assert letter.raster_height is None
    assert letter.coordinate_width == pytest.approx(612.0)
    assert letter.coordinate_height == pytest.approx(792.0)
    assert a4.coordinate_width == pytest.approx(595.28)
    assert a4.coordinate_height == pytest.approx(841.89)

    letter_geometry = build_page_geometry(letter)
    a4_geometry = build_page_geometry(a4)
    assert letter_geometry.width == pytest.approx(612.0)
    assert letter_geometry.height == pytest.approx(792.0)
    assert a4_geometry.width == pytest.approx(595.28)
    assert a4_geometry.height == pytest.approx(841.89)
    assert letter_geometry.geometry_scale == 1.0
    assert a4_geometry.geometry_scale == 1.0
    assert letter_geometry.coordinate_width == pytest.approx(612.0)
    assert letter_geometry.coordinate_height == pytest.approx(792.0)
    assert a4_geometry.coordinate_width == pytest.approx(595.28)
    assert a4_geometry.coordinate_height == pytest.approx(841.89)


def test_extract_pdf_pipeline_demo_matches_live_page_rect():
    pdf = _require_pdf("pipeline_demo_test.pdf")
    expected = _page_rect(pdf, 1)
    extracted = extract_pdf(pdf.read_bytes()).pages[0]
    assert extracted.page_width == pytest.approx(expected[0])
    assert extracted.page_height == pytest.approx(expected[1])
    geometry = build_page_geometry(extracted)
    assert geometry.width == pytest.approx(expected[0])
    assert geometry.height == pytest.approx(expected[1])
    assert geometry.geometry_scale == 1.0
    assert extracted.coordinate_width == pytest.approx(expected[0])
    assert extracted.coordinate_height == pytest.approx(expected[1])
    assert geometry.coordinate_width == pytest.approx(expected[0])
    assert geometry.coordinate_height == pytest.approx(expected[1])


# ---------------------------------------------------------------------------
# B. OCR scale preservation (contract test, not a real scanned PDF)
# ---------------------------------------------------------------------------


def test_ocr_geometry_scale_survives_adapter_and_boxes_map_from_coordinate_size():
    """OCR ``geometry_scale`` remains render-zoom provenance. PageGeometry
    boxes are mapped from the winning-image coordinate size into PDF
    points -- not left as pixels and not divided by zoom.
    """
    zoom = float(settings.pdf_ocr_zoom)
    assert zoom != 1.0

    page = PageExtraction(
        page_number=1,
        text="Hello",
        method="ocr",
        words=[dict(_PIXEL_WORD)],
        geometry_scale=zoom,
        page_width=595.28,
        page_height=841.89,
        coordinate_width=1200.0,
        coordinate_height=1697.0,
        rotation=0,
        page_origin_x=0.0,
        page_origin_y=0.0,
        raster_width=1200.0,
        raster_height=1697.0,
    )
    geometry = build_page_geometry(page)

    assert geometry.geometry_scale == pytest.approx(zoom)
    assert geometry.width == pytest.approx(595.28)
    assert geometry.height == pytest.approx(841.89)
    assert geometry.coordinate_width == pytest.approx(595.28)
    assert geometry.coordinate_height == pytest.approx(841.89)
    assert geometry.coordinate_width == geometry.width
    scale_x = 595.28 / 1200.0
    scale_y = 841.89 / 1697.0
    assert geometry.regions[0].bbox == pytest.approx(
        (
            _PIXEL_WORD["x0"] * scale_x,
            _PIXEL_WORD["y0"] * scale_y,
            _PIXEL_WORD["x1"] * scale_x,
            _PIXEL_WORD["y1"] * scale_y,
        )
    )
    # Zoom is not the transform authority.
    assert geometry.regions[0].bbox != pytest.approx(
        (
            _PIXEL_WORD["x0"] / zoom,
            _PIXEL_WORD["y0"] / zoom,
            _PIXEL_WORD["x1"] / zoom,
            _PIXEL_WORD["y1"] / zoom,
        )
    )
    assert geometry.regions[0].bbox != (
        _PIXEL_WORD["x0"],
        _PIXEL_WORD["y0"],
        _PIXEL_WORD["x1"],
        _PIXEL_WORD["y1"],
    )
    # Native extraction boxes stay in winning-image pixels.
    assert page.words[0]["x0"] == _PIXEL_WORD["x0"]
    assert page.coordinate_width == 1200.0


def test_missing_geometry_scale_and_dimensions_remain_unknown():
    class _BarePage:
        page_number = 1
        words = [dict(_POINT_WORD)]
        table_regions = None

    geometry = build_page_geometry(_BarePage())
    assert geometry.width is None
    assert geometry.height is None
    assert geometry.geometry_scale is None
    assert geometry.coordinate_width is None
    assert geometry.coordinate_height is None
    assert geometry.regions[0].bbox == (
        _POINT_WORD["x0"],
        _POINT_WORD["y0"],
        _POINT_WORD["x1"],
        _POINT_WORD["y1"],
    )


def test_invalid_geometry_fields_stay_unknown_rather_than_invented():
    class _BadPage:
        page_number = 1
        words = []
        table_regions = None
        page_width = "not-a-number"
        page_height = object()
        geometry_scale = "zoom"
        coordinate_width = "pixels"
        coordinate_height = object()

    geometry = build_page_geometry(_BadPage())
    assert geometry.width is None
    assert geometry.height is None
    assert geometry.geometry_scale is None
    assert geometry.coordinate_width is None
    assert geometry.coordinate_height is None


# ---------------------------------------------------------------------------
# C. Backward compatibility
# ---------------------------------------------------------------------------


def test_page_geometry_construction_without_dimensions_still_works():
    geometry = PageGeometry(page_number=4)
    assert geometry.width is None
    assert geometry.height is None
    assert geometry.geometry_scale is None
    assert geometry.coordinate_width is None
    assert geometry.coordinate_height is None
    assert geometry.regions == []
    assert geometry.rotation == 0


def test_page_extraction_without_optional_dimension_fields_still_works():
    page = PageExtraction(page_number=1, text="x", method="digital")
    assert page.page_width is None
    assert page.page_height is None
    assert page.coordinate_width is None
    assert page.coordinate_height is None
    assert page.geometry_scale == 1.0
    assert page.rotation is None
    assert page.page_origin_x is None
    assert page.raster_width is None
    geometry = build_page_geometry(page)
    assert geometry.width is None
    assert geometry.height is None
    assert geometry.geometry_scale == 1.0
    assert geometry.coordinate_width is None
    assert geometry.coordinate_height is None
    assert geometry.regions == []


def test_digital_geometry_does_not_inherit_ocr_scale():
    page = PageExtraction(
        page_number=1,
        text="Hello",
        method="digital",
        words=[dict(_POINT_WORD)],
        geometry_scale=1.0,
        page_width=612.0,
        page_height=792.0,
        coordinate_width=612.0,
        coordinate_height=792.0,
    )
    geometry = build_page_geometry(page)
    assert geometry.geometry_scale == 1.0
    assert geometry.geometry_scale != float(settings.pdf_ocr_zoom)
    assert geometry.coordinate_width == pytest.approx(612.0)
    assert geometry.coordinate_height == pytest.approx(792.0)
    assert geometry.coordinate_width == geometry.width
    assert geometry.regions[0].bbox == (
        _POINT_WORD["x0"],
        _POINT_WORD["y0"],
        _POINT_WORD["x1"],
        _POINT_WORD["y1"],
    )


def test_ocr_geometry_without_dimensions_is_withheld_not_converted_by_zoom():
    """OCR boxes without page/coordinate dimensions must not enter
    PageGeometry as pixels, and must not be divided by geometry_scale."""
    zoom = float(settings.pdf_ocr_zoom)
    page = PageExtraction(
        page_number=1,
        text="Hello",
        method="ocr",
        words=[dict(_PIXEL_WORD)],
        geometry_scale=zoom,
    )
    geometry = build_page_geometry(page)
    assert geometry.geometry_scale == pytest.approx(zoom)
    assert geometry.width is None
    assert geometry.height is None
    assert geometry.coordinate_width is None
    assert geometry.coordinate_height is None
    assert geometry.regions[0].bbox is None
    assert page.words[0]["x0"] == _PIXEL_WORD["x0"]


def test_lightweight_page_without_rects_stays_unknown():
    page = LightweightPageExtraction(page_number=1, text="x")
    assert page.page_width is None
    assert page.page_height is None
    assert page.coordinate_width is None
    assert page.coordinate_height is None
    assert page.geometry_scale == 1.0
    geometry = build_page_geometry(page)
    assert geometry.width is None
    assert geometry.height is None
    assert geometry.geometry_scale == 1.0
    assert geometry.coordinate_width is None
    assert geometry.coordinate_height is None


def test_reconstruct_page_extractions_preserves_rects_and_old_payloads():
    pages = reconstruct_page_extractions(
        ["hello"],
        {
            "table_regions_by_page": {},
            "words_by_page": {},
            "page_rect_by_page": {"1": {"width": 468.0, "height": 612.0}},
        },
    )
    assert pages[0].page_width == pytest.approx(468.0)
    assert pages[0].page_height == pytest.approx(612.0)
    assert pages[0].coordinate_width == pytest.approx(468.0)
    assert pages[0].coordinate_height == pytest.approx(612.0)
    assert pages[0].geometry_scale == 1.0
    geometry = build_page_geometry(pages[0])
    assert geometry.width == pytest.approx(468.0)
    assert geometry.height == pytest.approx(612.0)
    assert geometry.geometry_scale == 1.0
    assert geometry.coordinate_width == pytest.approx(468.0)
    assert geometry.coordinate_height == pytest.approx(612.0)

    legacy = reconstruct_page_extractions(
        ["hello"],
        {"table_regions_by_page": {}, "words_by_page": {}},
    )
    assert legacy[0].page_width is None
    assert legacy[0].page_height is None
    assert legacy[0].coordinate_width is None
    assert legacy[0].coordinate_height is None
    legacy_geometry = build_page_geometry(legacy[0])
    assert legacy_geometry.width is None
    assert legacy_geometry.height is None
    assert legacy_geometry.coordinate_width is None
    assert legacy_geometry.coordinate_height is None


def test_extract_pdf_empty_ocr_fallback_uses_digital_coordinate_space(monkeypatch):
    """If OCR returns no usable text, retained digital words keep PDF-point
    coordinate dimensions and scale 1.0 -- not pixmap pixels."""
    import app.utils.pdf.pymupdf_extractor as extractor

    def fake_ocr(_image):
        return "", [], None

    monkeypatch.setattr(extractor, "extract_ocr_result_from_pil_image", fake_ocr)
    document = fitz.open()
    try:
        page = document.new_page(width=200.0, height=300.0)
        page.insert_text((72, 72), "Hi")
        pdf_bytes = document.tobytes()
    finally:
        document.close()

    extracted = extractor.extract_pdf(pdf_bytes).pages[0]
    assert extracted.method == "digital"
    assert extracted.geometry_scale == 1.0
    assert extracted.page_width == pytest.approx(200.0)
    assert extracted.page_height == pytest.approx(300.0)
    assert extracted.coordinate_width == pytest.approx(200.0)
    assert extracted.coordinate_height == pytest.approx(300.0)
    assert extracted.words
    geometry = build_page_geometry(extracted)
    assert geometry.coordinate_width == pytest.approx(200.0)
    assert geometry.coordinate_height == pytest.approx(300.0)
    assert geometry.geometry_scale == 1.0


def test_extract_pdf_ocr_winner_size_is_not_zoom_or_page_rect(monkeypatch):
    """Contract test: extract_pdf stores the winning OCR image size, not
    page.rect and not zoom * page.rect. EasyOCR is not executed."""
    import app.utils.pdf.pymupdf_extractor as extractor

    winner_size = (1234.0, 1567.0)
    pixel_box = dict(_PIXEL_WORD)

    def fake_ocr(_image):
        return "Hello", [dict(pixel_box)], winner_size

    monkeypatch.setattr(extractor, "extract_ocr_result_from_pil_image", fake_ocr)
    document = fitz.open()
    try:
        page = document.new_page(width=200.0, height=300.0)
        page.insert_text((72, 72), "Hi")
        pdf_bytes = document.tobytes()
    finally:
        document.close()

    extracted = extractor.extract_pdf(pdf_bytes).pages[0]
    assert extracted.method == "ocr"
    assert extracted.geometry_scale == pytest.approx(float(settings.pdf_ocr_zoom))
    assert extracted.page_width == pytest.approx(200.0)
    assert extracted.page_height == pytest.approx(300.0)
    assert extracted.coordinate_width == pytest.approx(1234.0)
    assert extracted.coordinate_height == pytest.approx(1567.0)
    assert extracted.coordinate_width != extracted.page_width
    assert extracted.raster_width != extracted.coordinate_width
    assert extracted.words[0]["x0"] == pixel_box["x0"]
    assert extracted.words[0]["y0"] == pixel_box["y0"]
    geometry = build_page_geometry(extracted)
    # Winner 1234x1567 is not a uniform full-page scale of the original
    # pixmap, so canonical geometry is withheld.
    assert geometry.regions[0].bbox is None
    assert geometry.coordinate_width is None
    assert extracted.words[0]["x0"] == pixel_box["x0"]
    assert extracted.coordinate_width == pytest.approx(1234.0)
