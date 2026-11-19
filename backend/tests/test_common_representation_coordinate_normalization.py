"""Phase 7.14: canonical PDF-point normalization at build_page_geometry.

PageExtraction keeps native extraction coordinates. PageGeometry boxes are
PDF points relative to the original page rectangle, or withheld when that
mapping cannot be established. These tests do not change OCR settings,
regenerate Phase 7.12 fixtures, or call reconstruction algorithms.
"""
from __future__ import annotations

import copy
import math
from pathlib import Path

import pytest

from app.services.common_representation.adapters import build_page_geometry
from app.services.common_representation.types import PageGeometry, SpatialRegionType
from app.utils.pdf.pymupdf_extractor import PageExtraction

# Phase 7.12 provenance (read-only numbers; fixture files are not modified).
_PDF_WIDTH = 468.0
_PDF_HEIGHT = 612.0
_OCR_WINNER_WIDTH = 936.0
_OCR_WINNER_HEIGHT = 1224.0
_GEOMETRY_SCALE = 2.0
_OCR_INTERNAL = {"text": "Internal Review", "x0": 189.0, "y0": 1139.0, "x1": 319.0, "y1": 1159.0}
_OCR_POLICY = {
    "text": "Policy Manual Running Header",
    "x0": 187.0,
    "y0": 34.0,
    "x1": 444.0,
    "y1": 64.0,
}
_DIGITAL_INTERNAL_Y0 = 568.3250122070312
_MAPPED_INTERNAL = (94.5, 569.5, 159.5, 579.5)
_MAPPED_POLICY = (93.5, 17.0, 222.0, 32.0)

_POINT_WORD = {
    "text": "Hello",
    "x0": 50.0,
    "y0": 100.0,
    "x1": 90.0,
    "y1": 115.0,
    "cy": 107.5,
    "height": 15.0,
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

_PHASE_7_12_AUDIT = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "phase_7_12_text_only_furniture"
    / "provenance"
    / "coordinate_audit.json"
)


def _ocr_page(**overrides):
    payload = {
        "page_number": 2,
        "text": "Hello",
        "method": "ocr",
        "words": [dict(_PIXEL_WORD)],
        "geometry_scale": _GEOMETRY_SCALE,
        "page_width": _PDF_WIDTH,
        "page_height": _PDF_HEIGHT,
        "coordinate_width": _OCR_WINNER_WIDTH,
        "coordinate_height": _OCR_WINNER_HEIGHT,
        "rotation": 0,
        "page_origin_x": 0.0,
        "page_origin_y": 0.0,
        "raster_width": _OCR_WINNER_WIDTH,
        "raster_height": _OCR_WINNER_HEIGHT,
    }
    payload.update(overrides)
    return PageExtraction(**payload)


def _digital_page(**overrides):
    payload = {
        "page_number": 1,
        "text": "Hello",
        "method": "digital",
        "words": [dict(_POINT_WORD)],
        "geometry_scale": 1.0,
        "page_width": 612.0,
        "page_height": 792.0,
        "coordinate_width": 612.0,
        "coordinate_height": 792.0,
    }
    payload.update(overrides)
    return PageExtraction(**payload)


# ---------------------------------------------------------------------------
# 1. Digital identity
# ---------------------------------------------------------------------------


def test_digital_pdf_point_boxes_remain_exactly_unchanged():
    word = dict(_POINT_WORD)
    table_bbox = [48.0, 300.0, 328.0, 348.0]
    page = _digital_page(
        words=[word],
        table_regions=[{"bbox": list(table_bbox), "rows": [["A", "B"]]}],
    )
    geometry = build_page_geometry(page)
    word_region = next(r for r in geometry.regions if r.region_type == SpatialRegionType.WORD)
    table_region = next(r for r in geometry.regions if r.region_type == SpatialRegionType.TABLE)
    cell_region = next(r for r in geometry.regions if r.region_type == SpatialRegionType.CELL)

    assert word_region.bbox == (50.0, 100.0, 90.0, 115.0)
    assert table_region.bbox == (48.0, 300.0, 328.0, 348.0)
    assert cell_region.bbox is None
    assert geometry.coordinate_width == 612.0
    assert geometry.coordinate_height == 792.0
    assert geometry.coordinate_width == geometry.width
    assert geometry.coordinate_height == geometry.height
    assert geometry.geometry_scale == 1.0


# ---------------------------------------------------------------------------
# 2. Live Phase 7.12 OCR dimensions
# ---------------------------------------------------------------------------


def test_phase_7_12_ocr_winner_936x1224_normalizes_by_actual_dimensions():
    page = _ocr_page(words=[dict(_OCR_INTERNAL), dict(_OCR_POLICY)])
    geometry = build_page_geometry(page)

    assert geometry.width == _PDF_WIDTH
    assert geometry.height == _PDF_HEIGHT
    assert geometry.coordinate_width == _PDF_WIDTH
    assert geometry.coordinate_height == _PDF_HEIGHT
    assert geometry.geometry_scale == _GEOMETRY_SCALE

    internal = next(r for r in geometry.regions if r.text.startswith("Internal"))
    policy = next(r for r in geometry.regions if r.text.startswith("Policy"))
    assert internal.bbox == _MAPPED_INTERNAL
    assert policy.bbox == _MAPPED_POLICY
    # Zoom-only mapping would be 189/2 = 94.5 for x0 of Internal (same on
    # this uniform-2x winner) but Policy y0 would be 34/2 = 17, which this
    # independent-axis formula also yields; the authority is still 936x1224
    # not geometry_scale. A mismatched winner is covered separately.
    assert page.coordinate_width == _OCR_WINNER_WIDTH
    assert page.words[0]["x0"] == 189.0


def test_phase_7_12_provenance_numbers_still_match_on_disk():
    """Guard: this phase must not regenerate the 7.12 audit. If the file is
    present, the hardcoded mapping inputs still match it."""
    if not _PHASE_7_12_AUDIT.is_file():
        pytest.skip("Phase 7.12 coordinate_audit.json not present")
    import json

    audit = json.loads(_PHASE_7_12_AUDIT.read_text(encoding="utf-8"))
    assert audit["pdf_width"] == _PDF_WIDTH
    assert audit["pdf_height"] == _PDF_HEIGHT
    assert audit["ocr_coordinate_width"] == _OCR_WINNER_WIDTH
    assert audit["ocr_coordinate_height"] == _OCR_WINNER_HEIGHT
    internal = next(item for item in audit["comparisons"] if item["token"] == "Internal")
    assert internal["ocr"]["x0"] == _OCR_INTERNAL["x0"]
    assert internal["ocr"]["y0"] == _OCR_INTERNAL["y0"]
    assert internal["mapped_ocr_to_pdf"]["x0"] == _MAPPED_INTERNAL[0]
    assert internal["mapped_ocr_to_pdf"]["y0"] == _MAPPED_INTERNAL[1]


# ---------------------------------------------------------------------------
# 3. Synthetic resized OCR winner (geometry_scale is not the transform)
# ---------------------------------------------------------------------------


def test_resized_ocr_winner_uses_coordinate_size_not_geometry_scale():
    winner_w, winner_h = 1234.0, 1613.0  # uniform scale of 936x1224 (1 px rounding)
    page = _ocr_page(
        page_width=468.0,
        page_height=612.0,
        coordinate_width=winner_w,
        coordinate_height=winner_h,
        raster_width=936.0,
        raster_height=1224.0,
        geometry_scale=2.0,
        words=[dict(_PIXEL_WORD)],
    )
    geometry = build_page_geometry(page)
    scale_x = 468.0 / winner_w
    scale_y = 612.0 / winner_h
    assert geometry.regions[0].bbox == pytest.approx(
        (100.0 * scale_x, 200.0 * scale_y, 180.0 * scale_x, 230.0 * scale_y)
    )
    zoom_mapped = (50.0, 100.0, 90.0, 115.0)  # pixel / geometry_scale
    assert geometry.regions[0].bbox != pytest.approx(zoom_mapped)
    assert geometry.coordinate_width == pytest.approx(468.0)
    assert geometry.coordinate_height == pytest.approx(612.0)
    assert geometry.geometry_scale == 2.0
    assert page.coordinate_width == winner_w
    assert page.raster_width == 936.0
    assert page.words[0]["x0"] == 100.0


# ---------------------------------------------------------------------------
# 4. Independent X/Y scale
# ---------------------------------------------------------------------------


def test_x_and_y_scales_are_applied_independently():
    """Pixmap integer rounding makes sx and sy differ slightly; both are used.

    An anisotropic raster (not a full-page scale of page.rect) is withheld
    elsewhere -- this case is the observed Charter-like 1 px rounding.
    """
    page_w, page_h = 595.28, 841.89
    raster_w, raster_h = 1191.0, 1684.0
    page = _ocr_page(
        page_width=page_w,
        page_height=page_h,
        coordinate_width=raster_w,
        coordinate_height=raster_h,
        raster_width=raster_w,
        raster_height=raster_h,
        geometry_scale=2.0,
        words=[{"text": "A", "x0": 100.0, "y0": 200.0, "x1": 180.0, "y1": 240.0}],
    )
    geometry = build_page_geometry(page)
    scale_x = page_w / raster_w
    scale_y = page_h / raster_h
    assert scale_x != scale_y
    assert geometry.regions[0].bbox == pytest.approx(
        (100.0 * scale_x, 200.0 * scale_y, 180.0 * scale_x, 240.0 * scale_y)
    )
    uniform = (scale_x + scale_y) / 2.0
    assert geometry.regions[0].bbox != pytest.approx(
        (100.0 * uniform, 200.0 * uniform, 180.0 * uniform, 240.0 * uniform)
    )


# ---------------------------------------------------------------------------
# 5. Native extraction preservation
# ---------------------------------------------------------------------------


def test_normalization_does_not_mutate_page_extraction():
    native_word = dict(_OCR_INTERNAL)
    native_table = {"bbox": [10.0, 20.0, 30.0, 40.0], "rows": [["x"]]}
    page = _ocr_page(words=[native_word], table_regions=[native_table])
    word_id = id(page.words[0])
    table_id = id(page.table_regions[0])
    bbox_id = id(page.table_regions[0]["bbox"])
    before = copy.deepcopy(
        {
            "words": page.words,
            "table_regions": page.table_regions,
            "page_width": page.page_width,
            "page_height": page.page_height,
            "coordinate_width": page.coordinate_width,
            "coordinate_height": page.coordinate_height,
            "geometry_scale": page.geometry_scale,
            "method": page.method,
        }
    )

    geometry = build_page_geometry(page)

    assert id(page.words[0]) == word_id
    assert id(page.table_regions[0]) == table_id
    assert id(page.table_regions[0]["bbox"]) == bbox_id
    assert page.words == before["words"]
    assert page.table_regions == before["table_regions"]
    assert page.coordinate_width == 936.0
    assert page.coordinate_height == 1224.0
    assert page.method == "ocr"
    assert geometry.regions[0].bbox == _MAPPED_INTERNAL
    assert geometry.coordinate_width == _PDF_WIDTH


# ---------------------------------------------------------------------------
# 6. Canonical output contract
# ---------------------------------------------------------------------------


def test_normalized_coordinate_dimensions_match_pdf_page():
    page = _ocr_page()
    geometry = build_page_geometry(page)
    assert geometry.width == _PDF_WIDTH
    assert geometry.height == _PDF_HEIGHT
    assert geometry.coordinate_width == geometry.width
    assert geometry.coordinate_height == geometry.height
    assert geometry.coordinate_width != page.coordinate_width


# ---------------------------------------------------------------------------
# 7-8. Missing / zero / negative / non-finite dimensions
# ---------------------------------------------------------------------------


def test_ocr_missing_coordinate_dimensions_withhold_boxes():
    page = _ocr_page(coordinate_width=None, coordinate_height=None)
    geometry = build_page_geometry(page)
    assert geometry.width == _PDF_WIDTH
    assert geometry.height == _PDF_HEIGHT
    assert geometry.coordinate_width is None
    assert geometry.coordinate_height is None
    assert geometry.regions[0].bbox is None
    assert page.words[0]["x0"] == _PIXEL_WORD["x0"]


def test_ocr_missing_page_dimensions_withhold_boxes():
    page = _ocr_page(page_width=None, page_height=None)
    geometry = build_page_geometry(page)
    assert geometry.width is None
    assert geometry.height is None
    assert geometry.coordinate_width is None
    assert geometry.coordinate_height is None
    assert geometry.regions[0].bbox is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("page_width", 0.0),
        ("page_height", -612.0),
        ("coordinate_width", 0.0),
        ("coordinate_height", -1.0),
        ("page_width", math.inf),
        ("page_height", math.nan),
        ("coordinate_width", -math.inf),
        ("coordinate_height", math.nan),
    ],
)
def test_invalid_dimensions_withhold_ocr_boxes(field, value):
    page = _ocr_page(**{field: value})
    geometry = build_page_geometry(page)
    assert geometry.regions[0].bbox is None
    assert geometry.coordinate_width is None
    assert geometry.coordinate_height is None
    assert page.words[0]["y0"] == _PIXEL_WORD["y0"]


def test_unparseable_dimension_withholds_ocr_boxes():
    page = _ocr_page()
    page.coordinate_width = "pixels"
    geometry = build_page_geometry(page)
    assert geometry.regions[0].bbox is None
    assert geometry.coordinate_width is None


def test_digital_boxes_passthrough_when_page_size_is_unknown():
    """Digital PDF-point boxes remain usable when dimensions were never
    captured. This is not OCR pixel space."""
    page = PageExtraction(
        page_number=1,
        text="Hello",
        method="digital",
        words=[dict(_POINT_WORD)],
    )
    geometry = build_page_geometry(page)
    assert geometry.width is None
    assert geometry.coordinate_width is None
    assert geometry.regions[0].bbox == (50.0, 100.0, 90.0, 115.0)


def test_invalid_digital_dimensions_withhold_rather_than_claim_canonical_space():
    page = _digital_page(page_width=0.0, page_height=792.0, coordinate_width=0.0, coordinate_height=792.0)
    geometry = build_page_geometry(page)
    assert geometry.regions[0].bbox is None
    assert geometry.width is None
    assert geometry.coordinate_width is None


# ---------------------------------------------------------------------------
# 9. Relative geometry vs digital fixture
# ---------------------------------------------------------------------------


def test_normalized_ocr_footer_relative_position_matches_digital_band():
    page = _ocr_page(words=[dict(_OCR_INTERNAL)])
    geometry = build_page_geometry(page)
    x0, y0, x1, y1 = geometry.regions[0].bbox
    rel_y0 = y0 / geometry.height
    digital_rel_y0 = _DIGITAL_INTERNAL_Y0 / _PDF_HEIGHT

    assert 0.0 < rel_y0 < 1.0
    assert rel_y0 == pytest.approx(569.5 / 612.0)
    # Phrase-vs-word AABB residual is about 1.2 pt (~0.002 relative).
    assert abs(rel_y0 - digital_rel_y0) < 0.01
    assert rel_y0 != pytest.approx(1139.0 / 612.0)  # the 7.12 helper defect


def test_normalized_ocr_header_relative_position_is_near_top():
    page = _ocr_page(words=[dict(_OCR_POLICY)])
    geometry = build_page_geometry(page)
    rel_y0 = geometry.regions[0].bbox[1] / geometry.height
    assert rel_y0 == pytest.approx(17.0 / 612.0)
    assert rel_y0 < 0.05


# ---------------------------------------------------------------------------
# Rotation / origin limitations (only behavior the implementation can prove)
# ---------------------------------------------------------------------------


def test_nonzero_rotation_withholds_geometry_instead_of_guessing_a_transform():
    page = _ocr_page(rotation=90)
    geometry = build_page_geometry(page)
    assert geometry.rotation == 90
    assert geometry.regions[0].bbox is None
    assert geometry.coordinate_width is None
    assert geometry.coordinate_height is None
    assert geometry.width == 468.0
    assert geometry.height == 612.0
    assert page.words[0]["x0"] == _PIXEL_WORD["x0"]


def test_direct_page_geometry_still_allows_omitted_dimensions():
    geometry = PageGeometry(page_number=4)
    assert geometry.width is None
    assert geometry.coordinate_width is None
    assert geometry.regions == []
    assert geometry.rotation == 0


# ---------------------------------------------------------------------------
# Phase 7.14B: missing/unsupported OCR preconditions withhold geometry
# ---------------------------------------------------------------------------


def test_missing_rotation_metadata_withholds_ocr_geometry():
    page = _ocr_page(rotation=None)
    assert page.rotation is None
    geometry = build_page_geometry(page)
    assert geometry.regions[0].bbox is None
    assert geometry.coordinate_width is None
    assert page.words[0]["x0"] == _PIXEL_WORD["x0"]


def test_missing_origin_metadata_withholds_ocr_geometry():
    page = _ocr_page(page_origin_x=None, page_origin_y=None)
    geometry = build_page_geometry(page)
    assert geometry.regions[0].bbox is None
    assert page.coordinate_width == _OCR_WINNER_WIDTH


def test_nonzero_origin_withholds_ocr_geometry():
    page = _ocr_page(page_origin_x=50.0, page_origin_y=0.0)
    geometry = build_page_geometry(page)
    assert geometry.regions[0].bbox is None


def test_missing_original_raster_withholds_ocr_geometry():
    page = _ocr_page(raster_width=None, raster_height=None)
    geometry = build_page_geometry(page)
    assert geometry.regions[0].bbox is None


def test_anisotropic_winner_is_not_full_page_representation():
    page = _ocr_page(coordinate_width=1234.0, coordinate_height=1567.0)
    geometry = build_page_geometry(page)
    assert geometry.regions[0].bbox is None
    assert page.coordinate_width == 1234.0


def test_axis_swapped_winner_is_withheld():
    page = _ocr_page(coordinate_width=1224.0, coordinate_height=936.0)
    geometry = build_page_geometry(page)
    assert geometry.regions[0].bbox is None


def test_ocr_word_and_table_bboxes_normalize_together():
    page = _ocr_page(
        words=[dict(_OCR_INTERNAL)],
        table_regions=[{"bbox": [100.0, 200.0, 300.0, 400.0], "rows": [["A"]]}],
    )
    geometry = build_page_geometry(page)
    word = next(r for r in geometry.regions if r.region_type == SpatialRegionType.WORD)
    table = next(r for r in geometry.regions if r.region_type == SpatialRegionType.TABLE)
    cell = next(r for r in geometry.regions if r.region_type == SpatialRegionType.CELL)
    assert word.bbox == _MAPPED_INTERNAL
    assert table.bbox == (50.0, 100.0, 150.0, 200.0)
    assert cell.bbox is None


def test_malformed_bbox_does_not_invalidate_sibling_regions():
    page = _ocr_page(
        words=[
            dict(_OCR_INTERNAL),
            {"text": "bad"},
            dict(_OCR_POLICY),
        ]
    )
    geometry = build_page_geometry(page)
    assert geometry.regions[0].bbox == _MAPPED_INTERNAL
    assert geometry.regions[1].bbox is None
    assert geometry.regions[1].text == "bad"
    assert geometry.regions[2].bbox == _MAPPED_POLICY


def test_legacy_ocr_page_extraction_defaults_are_unknown():
    page = PageExtraction(page_number=1, text="Hello", method="ocr", words=[dict(_PIXEL_WORD)])
    assert page.rotation is None
    assert page.page_origin_x is None
    assert page.page_origin_y is None
    assert page.raster_width is None
    assert page.raster_height is None
    geometry = build_page_geometry(page)
    assert geometry.regions[0].bbox is None
    assert page.words[0]["x0"] == _PIXEL_WORD["x0"]
