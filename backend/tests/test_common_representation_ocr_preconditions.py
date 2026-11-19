"""Phase 7.14B: OCR geometry preconditions through extract_pdf → adapter.

In-memory PDFs only. Does not regenerate Phase 7.12 fixtures, change OCR
settings, or implement rotation/crop mapping.
"""
from __future__ import annotations

import fitz
import pytest

from app.config import settings
from app.services.common_representation.adapters import build_page_geometry
from app.utils.pdf.pymupdf_extractor import PageExtraction, extract_pdf

_PIXEL_WORD = {
    "text": "Hello",
    "x0": 100.0,
    "y0": 200.0,
    "x1": 180.0,
    "y1": 230.0,
    "cy": 215.0,
    "height": 30.0,
}


def _sparse_pdf_bytes(*, width: float = 200.0, height: float = 300.0, rotation: int = 0) -> bytes:
    document = fitz.open()
    try:
        page = document.new_page(width=width, height=height)
        page.insert_text((20, 40), "Hi")
        if rotation:
            page.set_rotation(rotation)
        return document.tobytes()
    finally:
        document.close()


def test_extract_pdf_digital_records_explicit_rotation_and_origin():
    pdf_bytes = _make_digital_enough_text()
    page = extract_pdf(pdf_bytes).pages[0]
    assert page.method == "digital"
    assert page.rotation == 0
    assert page.page_origin_x == 0.0
    assert page.page_origin_y == 0.0
    assert page.raster_width is None
    assert page.raster_height is None
    geometry = build_page_geometry(page)
    assert geometry.coordinate_width == pytest.approx(page.page_width)
    if page.words:
        native = (
            page.words[0]["x0"],
            page.words[0]["y0"],
            page.words[0]["x1"],
            page.words[0]["y1"],
        )
        assert geometry.regions[0].bbox == native


def _make_digital_enough_text() -> bytes:
    document = fitz.open()
    try:
        page = document.new_page(width=612.0, height=792.0)
        page.insert_text(
            (72, 72),
            "The student handbook explains enrollment procedures for incoming freshmen.",
        )
        return document.tobytes()
    finally:
        document.close()


def test_extract_pdf_ocr_records_raster_distinct_from_anisotropic_winner(monkeypatch):
    import app.utils.pdf.pymupdf_extractor as extractor

    def fake_ocr(image):
        return "Hello", [dict(_PIXEL_WORD)], (1234.0, 1567.0)

    monkeypatch.setattr(extractor, "extract_ocr_result_from_pil_image", fake_ocr)
    extracted = extractor.extract_pdf(_sparse_pdf_bytes()).pages[0]
    assert extracted.method == "ocr"
    assert extracted.rotation == 0
    assert extracted.page_origin_x == 0.0
    assert extracted.page_origin_y == 0.0
    assert extracted.raster_width == pytest.approx(200.0 * float(settings.pdf_ocr_zoom), abs=1.0)
    assert extracted.raster_height == pytest.approx(300.0 * float(settings.pdf_ocr_zoom), abs=1.0)
    assert extracted.coordinate_width == 1234.0
    assert extracted.raster_width != extracted.coordinate_width
    geometry = build_page_geometry(extracted)
    assert geometry.regions[0].bbox is None
    assert extracted.words[0]["x0"] == 100.0


def test_extract_pdf_supported_ocr_winner_matching_raster_normalizes(monkeypatch):
    import app.utils.pdf.pymupdf_extractor as extractor

    captured = {}

    def fake_ocr(image):
        width, height = image.size
        captured["size"] = (float(width), float(height))
        return "Hello", [dict(_PIXEL_WORD)], (float(width), float(height))

    monkeypatch.setattr(extractor, "extract_ocr_result_from_pil_image", fake_ocr)
    extracted = extractor.extract_pdf(_sparse_pdf_bytes()).pages[0]
    assert extracted.method == "ocr"
    assert extracted.rotation == 0
    assert extracted.page_origin_x == 0.0
    assert extracted.raster_width == captured["size"][0]
    assert extracted.coordinate_width == captured["size"][0]
    geometry = build_page_geometry(extracted)
    scale_x = extracted.page_width / extracted.coordinate_width
    scale_y = extracted.page_height / extracted.coordinate_height
    assert geometry.regions[0].bbox == pytest.approx(
        (100.0 * scale_x, 200.0 * scale_y, 180.0 * scale_x, 230.0 * scale_y)
    )
    assert geometry.coordinate_width == pytest.approx(extracted.page_width)
    assert geometry.coordinate_height == pytest.approx(extracted.page_height)
    assert extracted.words[0]["x0"] == 100.0
    assert extracted.coordinate_width == captured["size"][0]


def test_extract_pdf_uniformly_resized_winner_still_normalizes(monkeypatch):
    import app.utils.pdf.pymupdf_extractor as extractor

    def fake_ocr(image):
        width, height = image.size
        return "Hello", [dict(_PIXEL_WORD)], (float(width) * 1.5, float(height) * 1.5)

    monkeypatch.setattr(extractor, "extract_ocr_result_from_pil_image", fake_ocr)
    extracted = extractor.extract_pdf(_sparse_pdf_bytes()).pages[0]
    assert extracted.coordinate_width == pytest.approx(extracted.raster_width * 1.5)
    geometry = build_page_geometry(extracted)
    scale_x = extracted.page_width / extracted.coordinate_width
    scale_y = extracted.page_height / extracted.coordinate_height
    assert geometry.regions[0].bbox == pytest.approx(
        (100.0 * scale_x, 200.0 * scale_y, 180.0 * scale_x, 230.0 * scale_y)
    )


def test_extract_pdf_axis_swapped_winner_withholds(monkeypatch):
    import app.utils.pdf.pymupdf_extractor as extractor

    def fake_ocr(image):
        width, height = image.size
        return "Hello", [dict(_PIXEL_WORD)], (float(height), float(width))

    monkeypatch.setattr(extractor, "extract_ocr_result_from_pil_image", fake_ocr)
    extracted = extractor.extract_pdf(_sparse_pdf_bytes()).pages[0]
    geometry = build_page_geometry(extracted)
    assert geometry.regions[0].bbox is None
    assert extracted.words[0]["x0"] == 100.0


def test_extract_pdf_rotated_page_records_rotation_and_withholds_ocr(monkeypatch):
    import app.utils.pdf.pymupdf_extractor as extractor

    def fake_ocr(image):
        width, height = image.size
        return "Hello", [dict(_PIXEL_WORD)], (float(width), float(height))

    monkeypatch.setattr(extractor, "extract_ocr_result_from_pil_image", fake_ocr)
    extracted = extractor.extract_pdf(_sparse_pdf_bytes(rotation=90)).pages[0]
    assert extracted.method == "ocr"
    assert extracted.rotation == 90
    geometry = build_page_geometry(extracted)
    assert geometry.regions[0].bbox is None
    assert geometry.coordinate_width is None
    assert extracted.words[0]["x0"] == 100.0


def test_manually_constructed_ocr_page_cannot_impersonate_verified_zero_rotation():
    page = PageExtraction(
        page_number=1,
        text="Hello",
        method="ocr",
        words=[dict(_PIXEL_WORD)],
        page_width=200.0,
        page_height=300.0,
        coordinate_width=400.0,
        coordinate_height=600.0,
        geometry_scale=2.0,
    )
    assert page.rotation is None
    geometry = build_page_geometry(page)
    assert geometry.regions[0].bbox is None
