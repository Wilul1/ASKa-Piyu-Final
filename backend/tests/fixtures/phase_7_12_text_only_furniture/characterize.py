"""Read-only characterization of the Phase 7.12 fixture.

Uses production extraction/adapters/reconstruction without modifying them.
Writes JSON under provenance/ only.
"""
from __future__ import annotations

import hashlib
import json
import sys
import traceback
from pathlib import Path

DIR = Path(__file__).resolve().parent
BACKEND = DIR.parents[2]
sys.path.insert(0, str(BACKEND))

import fitz

from app.config import settings
from app.services.common_representation.adapters import build_page_geometry
from app.services.common_representation.reconstruction import (
    _FURNITURE_EDGE_BAND,
    _FURNITURE_MAX_REL_HEIGHT,
    _LINE_ADJACENCY_MAX_GAP,
    _SAME_COLUMN_X0_TOLERANCE,
    _group_words_into_lines,
    _isolated_from_same_page_neighbor,
    _line_intersects_any_table,
    _page_size,
    _stable_template_tokens,
    furniture_region_ids_on_page,
    reconstruct_cross_page_continuation,
    reconstruct_heading_to_table,
    reconstruct_line_label_continuations,
    reconstruct_page_furniture,
)
from app.services.common_representation.types import SpatialRegionType
from app.utils.pdf.pymupdf_extractor import extract_pdf

DIGITAL_PDF = DIR / "text_only_furniture_digital.pdf"
OCR_TWIN_PDF = DIR / "text_only_furniture_ocr_twin.pdf"
PROVENANCE = DIR / "provenance"


def _region_dump(region) -> dict:
    return {
        "region_id": region.region_id,
        "type": region.region_type.value,
        "text": region.text,
        "bbox": list(region.bbox) if region.bbox is not None else None,
        "row": region.row,
        "column": region.column,
        "reading_order_index": region.reading_order_index,
    }


def _line_dump(line, height: float, tables) -> dict:
    return {
        "text": line.text,
        "bbox": [line.x0, line.y0, line.x1, line.y1],
        "rel_y0": line.y0 / height if height else None,
        "rel_y1": line.y1 / height if height else None,
        "rel_h": (line.y1 - line.y0) / height if height else None,
        "n_words": len(line.word_region_ids),
        "word_region_ids": list(line.word_region_ids),
        "intersects_table": _line_intersects_any_table(line, tables),
        "edge_top": (line.y0 / height) <= _FURNITURE_EDGE_BAND if height else None,
        "edge_bot": (line.y1 / height) >= (1.0 - _FURNITURE_EDGE_BAND) if height else None,
        "compact": ((line.y1 - line.y0) / height) <= _FURNITURE_MAX_REL_HEIGHT if height else None,
        "tokens": sorted(_stable_template_tokens(line.text)),
    }


def _native_page(page: fitz.Page) -> dict:
    words = page.get_text("words", sort=True) or []
    dict_page = page.get_text("dict") or {}
    lines = []
    spans = 0
    for block in dict_page.get("blocks", []):
        for line in block.get("lines") or []:
            text = "".join(s.get("text", "") for s in (line.get("spans") or []))
            lines.append({"text": text, "bbox": line.get("bbox"), "n_spans": len(line.get("spans") or [])})
            spans += len(line.get("spans") or [])
    finder = getattr(page, "find_tables", None)
    tables = []
    if finder is not None:
        try:
            found = finder()
            for table in list(getattr(found, "tables", None) or []):
                tables.append({"bbox": list(table.bbox), "rows": table.extract()})
        except Exception as exc:
            tables.append({"error": str(exc)})
    sample = words[0] if words else None
    return {
        "word_count": len(words),
        "word_tuple_len": len(sample) if sample else None,
        "word_tuple_sample": list(sample) if sample else None,
        "words": [
            {
                "x0": float(w[0]),
                "y0": float(w[1]),
                "x1": float(w[2]),
                "y1": float(w[3]),
                "text": w[4],
                "block_no": w[5] if len(w) > 5 else None,
                "line_no": w[6] if len(w) > 6 else None,
                "word_no": w[7] if len(w) > 7 else None,
            }
            for w in words
        ],
        "dict_blocks": len(dict_page.get("blocks", [])),
        "dict_lines": lines,
        "dict_span_count": spans,
        "find_tables": tables,
        "rect": [float(page.rect.width), float(page.rect.height)],
        "rotation": int(page.rotation),
    }


def characterize_digital() -> dict:
    pdf_bytes = DIGITAL_PDF.read_bytes()
    extracted = extract_pdf(pdf_bytes)
    native_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages_out = []
    geometries = []
    try:
        for ext, native_page in zip(extracted.pages, native_doc):
            geom = build_page_geometry(ext)
            geometries.append(geom)
            tables = [
                r
                for r in geom.regions
                if r.region_type == SpatialRegionType.TABLE and r.bbox is not None
            ]
            height = geom.height or geom.coordinate_height or 0.0
            lines = _group_words_into_lines(geom)
            line_rows = [_line_dump(ln, height, tables) for ln in lines]
            isolated = []
            for i, ln in enumerate(lines):
                neighbor = None
                if i == 0 and len(lines) > 1:
                    neighbor = lines[1]
                elif i == len(lines) - 1 and len(lines) > 1:
                    neighbor = lines[-2]
                if neighbor is not None:
                    isolated.append(
                        {
                            "text": ln.text,
                            "isolated": _isolated_from_same_page_neighbor(ln, neighbor),
                            "neighbor": neighbor.text,
                        }
                    )
            header_words = [w for w in (ext.words or []) if "Policy" in w.get("text", "") or "Manual" in w.get("text", "") or "Running" in w.get("text", "") or "Header" in w.get("text", "")]
            footer_words = [w for w in (ext.words or []) if w.get("text", "") in {"Internal", "Review", "Copy", "Only"}]
            pages_out.append(
                {
                    "page_number": ext.page_number,
                    "method": ext.method,
                    "page_width": ext.page_width,
                    "page_height": ext.page_height,
                    "coordinate_width": ext.coordinate_width,
                    "coordinate_height": ext.coordinate_height,
                    "geometry_scale": ext.geometry_scale,
                    "geometry_page_size": _page_size(geom),
                    "extraction_words": ext.words,
                    "extraction_table_regions": ext.table_regions,
                    "adapter_regions": [_region_dump(r) for r in geom.regions],
                    "region_type_counts": {
                        t.value: sum(1 for r in geom.regions if r.region_type == t)
                        for t in SpatialRegionType
                    },
                    "reconstructed_lines": line_rows,
                    "isolation_endpoints": isolated,
                    "heading_to_table": [
                        {
                            "id": a.association_id,
                            "kind": a.kind.value,
                            "origin": a.origin.value,
                            "note": a.note,
                            "region_ids": a.region_ids,
                        }
                        for a in reconstruct_heading_to_table(geom)
                    ],
                    "line_continuations": [
                        {
                            "id": a.association_id,
                            "origin": a.origin.value,
                            "note": a.note,
                        }
                        for a in reconstruct_line_label_continuations(geom)
                    ],
                    "native": _native_page(native_page),
                    "header_words_extraction": header_words,
                    "footer_words_extraction": footer_words,
                }
            )
    finally:
        native_doc.close()

    furniture = reconstruct_page_furniture(geometries)
    xpage = []
    for a, b in zip(geometries, geometries[1:]):
        assocs = reconstruct_cross_page_continuation(
            a, b, furniture_region_ids=frozenset()
        )
        xpage.append(
            {
                "pages": [a.page_number, b.page_number],
                "associations": [
                    {
                        "id": x.association_id,
                        "kind": x.kind.value,
                        "origin": x.origin.value,
                        "note": x.note,
                        "region_ids": x.region_ids,
                    }
                    for x in assocs
                ],
            }
        )
    membership = [
        {
            "page": g.page_number,
            "furniture_region_ids_on_page": list(
                furniture_region_ids_on_page(g, furniture)
            ),
        }
        for g in geometries
    ]
    return {
        "used_ocr_fallback": extracted.used_ocr_fallback,
        "page_count": len(extracted.pages),
        "pages": pages_out,
        "reconstruct_page_furniture": [
            {
                "id": a.association_id,
                "kind": a.kind.value,
                "origin": a.origin.value,
                "region_ids": a.region_ids,
                "note": a.note,
                "confidence": a.confidence,
            }
            for a in furniture
        ],
        "cross_page_unfiltered": xpage,
        "membership_against_table_furniture": membership,
        "settings": {
            "pdf_ocr_zoom": settings.pdf_ocr_zoom,
            "min_chars_per_page_for_digital_pdf": settings.min_chars_per_page_for_digital_pdf,
            "ocr_preprocess_enabled": settings.ocr_preprocess_enabled,
            "ocr_min_dimension": settings.ocr_min_dimension,
            "ocr_max_dimension": settings.ocr_max_dimension,
            "ocr_compare_original": settings.ocr_compare_original,
        },
        "thresholds": {
            "line_grouping_y_tolerance_pt": 2.5,
            "line_adjacency_max_gap_pt": _LINE_ADJACENCY_MAX_GAP,
            "same_column_x0_tolerance_pt": _SAME_COLUMN_X0_TOLERANCE,
            "furniture_edge_band": _FURNITURE_EDGE_BAND,
            "furniture_max_rel_height": _FURNITURE_MAX_REL_HEIGHT,
        },
    }


def characterize_ocr() -> dict:
    pdf_bytes = OCR_TWIN_PDF.read_bytes()
    try:
        extracted = extract_pdf(pdf_bytes)
    except Exception as exc:
        return {
            "live_ocr_ran": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
    pages = []
    for ext in extracted.pages:
        geom = build_page_geometry(ext)
        word_lens = [len(str(w.get("text", "")).split()) for w in (ext.words or [])]
        pages.append(
            {
                "page_number": ext.page_number,
                "method": ext.method,
                "page_width": ext.page_width,
                "page_height": ext.page_height,
                "coordinate_width": ext.coordinate_width,
                "coordinate_height": ext.coordinate_height,
                "geometry_scale": ext.geometry_scale,
                "geometry_page_size": _page_size(geom),
                "table_regions": ext.table_regions,
                "word_count": len(ext.words or []),
                "words": ext.words,
                "phrase_vs_word": {
                    "detections": len(word_lens),
                    "multi_token_detections": sum(1 for n in word_lens if n > 1),
                    "single_token_detections": sum(1 for n in word_lens if n == 1),
                },
                "text_excerpt": (ext.text or "")[:500],
                "region_type_counts": {
                    t.value: sum(1 for r in geom.regions if r.region_type == t)
                    for t in SpatialRegionType
                },
                "reconstructed_lines": [
                    {
                        "text": ln.text,
                        "bbox": [ln.x0, ln.y0, ln.x1, ln.y1],
                    }
                    for ln in _group_words_into_lines(geom)
                ],
            }
        )
    return {
        "live_ocr_ran": True,
        "used_ocr_fallback": extracted.used_ocr_fallback,
        "pages": pages,
    }


def coordinate_audit(digital: dict, ocr: dict) -> dict:
    if not ocr.get("live_ocr_ran"):
        return {"live_ocr_available": False, "reason": ocr.get("error") or "ocr did not run"}
    # Compare page 2 header tokens.
    dpage = next(p for p in digital["pages"] if p["page_number"] == 2)
    opage = next(p for p in ocr["pages"] if p["page_number"] == 2)
    pdf_w, pdf_h = dpage["page_width"], dpage["page_height"]
    pix_w = 468.0 * float(settings.pdf_ocr_zoom)
    pix_h = 612.0 * float(settings.pdf_ocr_zoom)
    probes = ["Policy", "Internal", "Section", "Ordinary"]
    comparisons = []
    dwords = dpage["extraction_words"] or []
    owords = opage["words"] or []
    for token in probes:
        dmatch = next((w for w in dwords if token.lower() in str(w.get("text", "")).lower()), None)
        omatch = next((w for w in owords if token.lower() in str(w.get("text", "")).lower()), None)
        item = {"token": token, "digital": dmatch, "ocr": omatch}
        if dmatch and omatch:
            dx = (dmatch["x1"] - dmatch["x0"]) or 1.0
            dy = (dmatch["y1"] - dmatch["y0"]) or 1.0
            item["ratios"] = {
                "x0_ocr_over_digital": omatch["x0"] / dmatch["x0"] if dmatch["x0"] else None,
                "y0_ocr_over_digital": omatch["y0"] / dmatch["y0"] if dmatch["y0"] else None,
                "width_ocr_over_digital": (omatch["x1"] - omatch["x0"]) / dx,
                "height_ocr_over_digital": (omatch["y1"] - omatch["y0"]) / dy,
            }
            item["expected_if_zoom_only"] = {
                "x0": dmatch["x0"] * settings.pdf_ocr_zoom,
                "y0": dmatch["y0"] * settings.pdf_ocr_zoom,
                "x1": dmatch["x1"] * settings.pdf_ocr_zoom,
                "y1": dmatch["y1"] * settings.pdf_ocr_zoom,
            }
            cw = opage["coordinate_width"]
            ch = opage["coordinate_height"]
            item["expected_if_coord_over_pdf"] = {
                "scale_x": (cw / pdf_w) if cw and pdf_w else None,
                "scale_y": (ch / pdf_h) if ch and pdf_h else None,
            }
            if cw and pdf_w:
                sx, sy = cw / pdf_w, ch / pdf_h
                item["mapped_ocr_to_pdf"] = {
                    "x0": omatch["x0"] / sx,
                    "y0": omatch["y0"] / sy,
                    "x1": omatch["x1"] / sx,
                    "y1": omatch["y1"] / sy,
                }
                item["delta_mapped_minus_digital"] = {
                    "x0": omatch["x0"] / sx - dmatch["x0"],
                    "y0": omatch["y0"] / sy - dmatch["y0"],
                }
            ps = opage["geometry_page_size"]
            item["relative_y0_using_page_size_helper"] = (
                omatch["y0"] / ps[1] if ps else None
            )
            item["relative_y0_using_coordinate_height"] = (
                omatch["y0"] / ch if ch else None
            )
            item["relative_y0_digital"] = dmatch["y0"] / pdf_h if pdf_h else None
        comparisons.append(item)
    return {
        "live_ocr_available": True,
        "page_number": 2,
        "pdf_width": pdf_w,
        "pdf_height": pdf_h,
        "geometry_scale": opage["geometry_scale"],
        "ocr_coordinate_width": opage["coordinate_width"],
        "ocr_coordinate_height": opage["coordinate_height"],
        "ocr_page_width": opage["page_width"],
        "ocr_page_height": opage["page_height"],
        "page_size_helper": opage["geometry_page_size"],
        "nominal_render_at_zoom": [pix_w, pix_h],
        "comparisons": comparisons,
        "table_regions_on_ocr_page": opage["table_regions"],
        "ocr_method": opage["method"],
    }


def fake_ocr_contract_experiment() -> dict:
    """Supplemental: not live OCR. Replays geometry-contract fake boxes."""
    from app.utils.pdf.pymupdf_extractor import PageExtraction

    winner = (1234.0, 1567.0)
    box = {
        "text": "Policy",
        "x0": 100.0,
        "y0": 40.0,
        "x1": 180.0,
        "y1": 55.0,
        "cy": 47.5,
        "height": 15.0,
    }
    ext = PageExtraction(
        page_number=1,
        text="Policy",
        method="ocr",
        words=[box],
        geometry_scale=float(settings.pdf_ocr_zoom),
        page_width=468.0,
        page_height=612.0,
        coordinate_width=winner[0],
        coordinate_height=winner[1],
    )
    geom = build_page_geometry(ext)
    helper = _page_size(geom)
    rel_helper = box["y0"] / helper[1] if helper else None
    rel_coord = box["y0"] / winner[1]
    return {
        "label": "synthetic_fake_ocr_coordinate_contract_only",
        "not_live_ocr": True,
        "page_width": geom.width,
        "page_height": geom.height,
        "coordinate_width": geom.coordinate_width,
        "coordinate_height": geom.coordinate_height,
        "geometry_scale": geom.geometry_scale,
        "page_size_helper": helper,
        "box": box,
        "rel_y0_if_using_page_size_helper": rel_helper,
        "rel_y0_if_using_coordinate_height": rel_coord,
        "mismatch": helper is not None and helper[1] == 612.0,
    }


def main() -> None:
    PROVENANCE.mkdir(exist_ok=True)
    digital = characterize_digital()
    (PROVENANCE / "digital_extraction.json").write_text(
        json.dumps(digital, indent=2, default=str), encoding="utf-8"
    )
    ocr = characterize_ocr()
    (PROVENANCE / "ocr_extraction.json").write_text(
        json.dumps(ocr, indent=2, default=str), encoding="utf-8"
    )
    audit = coordinate_audit(digital, ocr)
    audit["synthetic_fake_ocr"] = fake_ocr_contract_experiment()
    (PROVENANCE / "coordinate_audit.json").write_text(
        json.dumps(audit, indent=2, default=str), encoding="utf-8"
    )
    summary = {
        "digital_method_pages": [p["method"] for p in digital["pages"]],
        "digital_furniture_groups": len(digital["reconstruct_page_furniture"]),
        "ocr_live": ocr.get("live_ocr_ran"),
        "ocr_methods": [p.get("method") for p in ocr.get("pages", [])] if ocr.get("live_ocr_ran") else ocr.get("error"),
    }
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
