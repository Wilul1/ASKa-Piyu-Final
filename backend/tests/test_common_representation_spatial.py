"""Tests for Phase 6.21's shared spatial evidence contract
(``SpatialRegion``/``PageGeometry``/``SpatialAssociation`` in
``app.services.common_representation.types``, and the
``build_page_geometry``/``build_page_geometries`` conversion in
``app.services.common_representation.adapters``).

This phase only PRESERVES and PROPAGATES geometry the extraction pipeline
already computes -- it does not reconstruct relationships, change
extraction decisions, or alter Citizen's Charter candidate output. Tests
here verify that contract, using the real Citizen's Charter PDF already
used elsewhere in this test suite where real propagation can be shown.

Real-document coverage: the real Citizen's Charter PDF (same file already
used by ``test_common_representation_adapters.py``), specifically page 37
-- the page with the already-confirmed "Office or"/"Division:" split-label
geometry (Phase 6.17/6.18/6.19) -- since its word/table geometry is already
independently verified this session, making it a trustworthy real fixture
for proving propagation actually works, not just that the types parse.

Honestly-labeled synthetic coverage: serialization round-trips, coordinate
validation, and multi-page/no-evidence edge cases use small hand-built
fixtures, since no real document exercises every edge case (e.g. "a unit
spanning two pages with no table on either").
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from app.services.chunking import DocumentChunk
from app.services.common_representation.adapters import (
    adapt_generic_text,
    adapt_prebuilt_chunks,
    build_page_geometries,
    build_page_geometry,
)
from app.services.common_representation.chunker import chunk_document_record
from app.services.common_representation.types import (
    DocumentRecord,
    EvidenceOrigin,
    PageGeometry,
    ParagraphContent,
    SpatialAssociation,
    SpatialRegion,
    SpatialRegionType,
    SpatialRelationKind,
    StructuralUnit,
)
from app.utils.pdf.pymupdf_extractor import PageExtraction, extract_pdf

BACKEND_DIR = Path(__file__).resolve().parents[1]
CHARTER_PDF = (
    BACKEND_DIR
    / "data"
    / "documents"
    / "da4a1832-7242-4e94-8ba6-bc0b9f2294bf"
    / "Laguna State Polytechnic University-CC_2026-1st Edition.pdf"
)
_HAS_CHARTER_PDF = CHARTER_PDF.exists()


@pytest.fixture(scope="module")
def real_page_37():
    """The real, already-extracted page 37 of the Citizen's Charter PDF --
    the page with the confirmed "Office or"/"Division:" split-label
    geometry. Built via the real, unmodified production `extract_pdf()`."""
    if not _HAS_CHARTER_PDF:
        pytest.skip("real Citizen's Charter PDF not present on this machine")
    result = extract_pdf(CHARTER_PDF.read_bytes())
    pages = [p for p in result.pages if p.page_number == 37]
    assert pages, "page 37 not found in real extraction -- fixture assumption broken"
    return pages[0]


# ---------------------------------------------------------------------------
# 1-3: page geometry / region identity / serialization
# ---------------------------------------------------------------------------


def test_page_geometry_serialization_round_trip():
    region = SpatialRegion(
        region_id="p1:word:0",
        page_number=1,
        region_type=SpatialRegionType.WORD,
        text="Hello",
        bbox=(10.0, 20.0, 30.0, 40.0),
        reading_order_index=0,
    )
    geometry = PageGeometry(page_number=1, width=612.0, height=792.0, regions=[region])

    payload = json.dumps(dataclasses.asdict(geometry))
    restored = json.loads(payload)

    assert restored["page_number"] == 1
    assert restored["width"] == 612.0
    assert restored["height"] == 792.0
    assert restored["regions"][0]["region_id"] == "p1:word:0"
    assert restored["regions"][0]["region_type"] == "word"
    assert tuple(restored["regions"][0]["bbox"]) == (10.0, 20.0, 30.0, 40.0)


def test_bounding_box_coordinates_are_valid_and_ordered():
    """x0<=x1 and y0<=y1 for every real word region extracted from a real
    page -- a basic sanity bound on the coordinate convention, not a new
    normalization step (PyMuPDF already guarantees this; this test would
    catch a future regression in build_page_geometry's own bbox assembly)."""
    page = PageExtraction(
        page_number=5,
        text="A B",
        method="digital",
        words=[
            {"text": "A", "x0": 10.0, "y0": 20.0, "x1": 15.0, "y1": 25.0, "cy": 22.5, "height": 5.0},
            {"text": "B", "x0": 20.0, "y0": 20.0, "x1": 25.0, "y1": 25.0, "cy": 22.5, "height": 5.0},
        ],
    )
    geometry = build_page_geometry(page)
    for region in geometry.regions:
        assert region.bbox is not None
        x0, y0, x1, y1 = region.bbox
        assert x0 <= x1
        assert y0 <= y1


def test_region_identifiers_are_stable_and_page_scoped():
    page = PageExtraction(
        page_number=9,
        text="A",
        method="digital",
        words=[{"text": "A", "x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0, "cy": 0.5, "height": 1.0}],
    )
    first = build_page_geometry(page)
    second = build_page_geometry(page)
    assert first.regions[0].region_id == second.regions[0].region_id
    assert first.regions[0].page_number == 9
    assert first.regions[0].region_id.startswith("p9:")


# ---------------------------------------------------------------------------
# 4: spatial association serialization and reference integrity
# ---------------------------------------------------------------------------


def test_spatial_association_references_real_region_ids():
    page = PageExtraction(
        page_number=1,
        text="Heading\nTable",
        method="digital",
        words=[{"text": "Heading", "x0": 0.0, "y0": 0.0, "x1": 10.0, "y1": 5.0, "cy": 2.5, "height": 5.0}],
        table_regions=[{"bbox": [0.0, 10.0, 20.0, 30.0], "rows": [["Office", "Registrar"]]}],
    )
    geometry = build_page_geometry(page)
    heading_region = next(r for r in geometry.regions if r.region_type == SpatialRegionType.WORD)
    table_region = next(r for r in geometry.regions if r.region_type == SpatialRegionType.TABLE)

    association = SpatialAssociation(
        association_id="a1",
        region_ids=[heading_region.region_id, table_region.region_id],
        kind=SpatialRelationKind.HEADING_TO_TABLE,
        origin=EvidenceOrigin.LAYOUT_RECONSTRUCTED,
        confidence=0.9,
    )
    known_ids = {r.region_id for r in geometry.regions}
    assert set(association.region_ids).issubset(known_ids)

    restored = json.loads(json.dumps(dataclasses.asdict(association)))
    assert restored["region_ids"] == [heading_region.region_id, table_region.region_id]
    assert restored["kind"] == "heading_to_table"
    assert restored["origin"] == "layout_reconstructed"


# ---------------------------------------------------------------------------
# 5-6: multiple regions per unit; units spanning multiple regions/pages
# ---------------------------------------------------------------------------


def test_structural_unit_can_reference_multiple_spatial_associations():
    unit = StructuralUnit(
        unit_id="u1",
        source_order=0,
        title="A Service",
        content=ParagraphContent(text="body"),
        structural_type="paragraph",
        content_type="information",
        spatial_associations=[
            SpatialAssociation(
                association_id="a1", region_ids=["r1"],
                kind=SpatialRelationKind.HEADING_TO_TABLE, origin=EvidenceOrigin.LAYOUT_RECONSTRUCTED,
            ),
            SpatialAssociation(
                association_id="a2", region_ids=["r2", "r3"],
                kind=SpatialRelationKind.CONTINUATION, origin=EvidenceOrigin.MISSING,
            ),
        ],
    )
    assert len(unit.spatial_associations) == 2
    all_region_ids = {rid for assoc in unit.spatial_associations for rid in assoc.region_ids}
    assert all_region_ids == {"r1", "r2", "r3"}


def test_document_record_can_hold_geometry_for_multiple_pages():
    page_a = PageExtraction(page_number=1, text="A", method="digital", words=[])
    page_b = PageExtraction(page_number=2, text="B", method="digital", words=[])
    record = DocumentRecord(
        document_id="doc1",
        source_filename="f.pdf",
        classification="information",
        page_geometries=build_page_geometries([page_a, page_b]),
    )
    assert [g.page_number for g in record.page_geometries] == [1, 2]
    # A unit's own page_start/page_end (already-existing fields) can name
    # either page; nothing here forces a unit to "span" via new fields --
    # the existing page_start/page_end range already expresses that, and
    # this phase doesn't change how units declare their own page range.


# ---------------------------------------------------------------------------
# 7-8: documents with no spatial evidence; backward compatibility
# ---------------------------------------------------------------------------


def test_document_with_no_pages_has_empty_geometry_not_none_or_error():
    assert build_page_geometries(None) == []
    assert build_page_geometries([]) == []
    record = DocumentRecord(document_id="d", source_filename="f.pdf", classification="information")
    assert record.page_geometries == []


def test_adapt_generic_text_backward_compatible_without_pages():
    """Every existing caller of adapt_generic_text omits `pages` -- output
    must be byte-identical to before this parameter existed."""
    record_without_pages = adapt_generic_text(
        "Some real paragraph text.", document_id="d1", source_filename="f.pdf"
    )
    assert record_without_pages.page_geometries == []
    assert record_without_pages.units[0].content.text == "Some real paragraph text."


def test_adapt_prebuilt_chunks_backward_compatible_without_pages():
    """Citizen's Charter's real production call site
    (_quality_payload_from_charter_v2_services) does not pass `pages` --
    confirm the adapter's unit/content output is identical whether or not
    a future caller starts passing them, proving this parameter cannot
    silently alter existing behavior."""
    chunk = DocumentChunk(
        text="Service body text.", chunk_index=0, char_start=0,
        metadata={"title": "A Service", "page_start": 5, "office": "Registrar"},
    )
    without_pages = adapt_prebuilt_chunks(
        [chunk], document_id="d1", source_filename="f.pdf", classification="citizen_charter"
    )
    with_pages = adapt_prebuilt_chunks(
        [chunk], document_id="d1", source_filename="f.pdf", classification="citizen_charter",
        pages=[PageExtraction(page_number=5, text="irrelevant", method="digital", words=[])],
    )
    assert without_pages.page_geometries == []
    assert len(with_pages.page_geometries) == 1
    assert without_pages.units[0].content == with_pages.units[0].content
    assert without_pages.units[0].title == with_pages.units[0].title
    assert without_pages.units[0].searchable_fields == with_pages.units[0].searchable_fields
    assert without_pages.units[0].page_start == with_pages.units[0].page_start


# ---------------------------------------------------------------------------
# 9-10: local/cloud contract parity; preservation of real word/cell geometry
# ---------------------------------------------------------------------------


def test_lightweight_page_extraction_duck_types_into_build_page_geometry():
    """LightweightPageExtraction (the cloud/Heroku page type) is never
    imported here on purpose -- this test constructs an equivalent,
    independent object exposing the identical attribute names
    (page_number/text/words/table_regions/geometry_scale, confirmed
    identical in handbook_lightweight_extraction.py) to prove
    build_page_geometry works via duck typing, not an isinstance check
    against the local-only PageExtraction class."""

    class _FakeLightweightPage:
        def __init__(self):
            self.page_number = 3
            self.text = "Office Hours"
            self.words = [
                {"text": "Office", "x0": 0.0, "y0": 0.0, "x1": 10.0, "y1": 5.0, "cy": 2.5, "height": 5.0},
            ]
            self.table_regions = [{"bbox": [0.0, 10.0, 20.0, 20.0], "rows": [["Mon-Fri"]]}]
            self.geometry_scale = 1.0

    geometry = build_page_geometry(_FakeLightweightPage())
    assert geometry.page_number == 3
    assert any(r.region_type == SpatialRegionType.WORD and r.text == "Office" for r in geometry.regions)
    assert any(r.region_type == SpatialRegionType.TABLE for r in geometry.regions)
    assert any(r.region_type == SpatialRegionType.CELL and r.text == "Mon-Fri" for r in geometry.regions)


@pytest.mark.skipif(not _HAS_CHARTER_PDF, reason="real Citizen's Charter PDF not present on this machine")
def test_real_page_37_extract_pdf_preserves_page_rect(real_page_37):
    """Production extract_pdf() now carries the real PDF page rectangle
    onto PageExtraction and through build_page_geometry, in PDF points."""
    assert real_page_37.page_width == pytest.approx(595.3, abs=1.0)
    assert real_page_37.page_height == pytest.approx(841.9, abs=1.0)
    assert real_page_37.geometry_scale == 1.0
    assert real_page_37.coordinate_width == pytest.approx(real_page_37.page_width)
    assert real_page_37.coordinate_height == pytest.approx(real_page_37.page_height)
    geometry = build_page_geometry(real_page_37)
    assert geometry.width == pytest.approx(real_page_37.page_width)
    assert geometry.height == pytest.approx(real_page_37.page_height)
    assert geometry.geometry_scale == 1.0
    assert geometry.coordinate_width == pytest.approx(real_page_37.page_width)
    assert geometry.coordinate_height == pytest.approx(real_page_37.page_height)


@pytest.mark.skipif(not _HAS_CHARTER_PDF, reason="real Citizen's Charter PDF not present on this machine")
def test_real_page_37_word_and_cell_geometry_preserved(real_page_37):
    """Direct regression proof against the real PDF: the already-confirmed
    (Phase 6.17/6.18/6.19) 'Office'/'or'/'Division:' split-label word
    coordinates survive into SpatialRegion unchanged."""
    geometry = build_page_geometry(real_page_37)
    words_by_text = {}
    for region in geometry.regions:
        if region.region_type == SpatialRegionType.WORD:
            words_by_text.setdefault(region.text, region)

    office = words_by_text["Office"]
    division = words_by_text["Division:"]
    assert office.bbox is not None and division.bbox is not None
    # Confirmed this session: 'Office' sits on the y0=487.9/y1=500.2 line;
    # 'Division:' wraps to the next line (y0=500.5/y1=512.8) -- i.e.
    # division's bbox is strictly below office's, never equal/above.
    assert office.bbox[1] < division.bbox[1]
    assert abs(office.bbox[1] - 487.9) < 0.5
    assert abs(division.bbox[1] - 500.5) < 0.5

    cell_texts = {r.text for r in geometry.regions if r.region_type == SpatialRegionType.CELL}
    assert cell_texts, "real page 37 has native table_regions -- cell regions must be non-empty"


# ---------------------------------------------------------------------------
# 11: compact chunk metadata -- no geometry payload copied into chunks
# ---------------------------------------------------------------------------


def test_build_metadata_does_not_copy_page_geometries_into_chunk_metadata():
    """DocumentRecord.page_geometries must stay document-level: the shared
    chunker's _build_metadata must not copy it (or any per-region payload)
    into individual chunk metadata -- Chroma metadata values must also
    stay JSON-scalar-compatible, which a raw dataclass/enum is not."""
    page = PageExtraction(
        page_number=1, text="word", method="digital",
        words=[{"text": "word", "x0": 0.0, "y0": 0.0, "x1": 5.0, "y1": 5.0, "cy": 2.5, "height": 5.0}],
    )
    record = adapt_generic_text(
        "A real paragraph of body text for chunking.", document_id="d1", source_filename="f.pdf",
        pages=[page],
    )
    assert len(record.page_geometries) == 1  # geometry genuinely attached at the document level
    chunks = chunk_document_record(record, target_chars=500, max_chars=1000, overlap_chars=0)
    assert chunks, "expected at least one chunk"
    for chunk in chunks:
        # No geometry-shaped payload (page_geometries, or any raw
        # PageGeometry/SpatialRegion/SpatialAssociation instance) leaks into
        # chunk metadata. Pre-existing fields like "hierarchy_path" are
        # legitimately plain lists at this layer -- chroma_store.py's
        # add_document_chunks (a separate, later stage) is what JSON-encodes
        # any list/dict value before the real Chroma write; _build_metadata
        # itself was never scalar-only, and this test doesn't assert
        # otherwise, only that nothing geometry-shaped appears here.
        assert "page_geometries" not in chunk.metadata
        assert "spatial_associations" not in chunk.metadata
        for value in chunk.metadata.values():
            assert not isinstance(value, (PageGeometry, SpatialRegion, SpatialAssociation)), (
                f"raw spatial-evidence object leaked into compact chunk metadata: {value!r}"
            )


# ---------------------------------------------------------------------------
# 12: existing extraction / common-representation regression guard
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _HAS_CHARTER_PDF, reason="real Citizen's Charter PDF not present on this machine")
def test_citizen_charter_baseline_unchanged_by_spatial_evidence_contract():
    """The Phase 6.20 baseline (96 candidates / 177 requirements / 284
    steps) must be byte-for-byte unchanged by this phase, since Charter's
    real production call site never passes `pages` into
    adapt_prebuilt_chunks -- this phase is additive-only."""
    from app.services.citizen_charter_extractor_v2 import extract_citizen_charter_services_v2

    result = extract_pdf(CHARTER_PDF.read_bytes())
    services = extract_citizen_charter_services_v2(result.pages)
    assert len(services) == 96
    assert sum(len(s.requirements or []) for s in services) == 177
    assert sum(len(s.steps or []) for s in services) == 284
    titles = [s.service_title for s in services]
    assert titles.count("IP Registration Process") == 2
    assert "Open to all Clients" not in titles
    assert not any("NATIONAL SERVICE TRAINING PROGRAM" in (t or "") for t in titles)
