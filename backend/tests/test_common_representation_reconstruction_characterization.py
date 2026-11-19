"""Phase 7.2 real-document characterization of geometric reconstruction.

These tests freeze the reconstruction module's *current* behavior on actual
repository PDFs, including known false associations documented in Phase 7.1.

They are not approval of those false associations. When reconstruction is
later corrected, these expectations must be updated deliberately.

This file does not modify reconstruction, extraction, types, adapters,
thresholds, or production wiring. Geometry is taken from the real PDFs via
the same per-page functions ``extract_pdf`` uses (``_page_word_items`` and
``_extract_table_regions``), on the requested physical page only.

Missing fixtures fail with an explicit "unavailable" error -- they are not
silently skipped.
"""
from __future__ import annotations

import sys
from pathlib import Path

import fitz
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.common_representation.adapters import build_page_geometry  # noqa: E402
from app.services.common_representation.reconstruction import (  # noqa: E402
    _group_words_into_lines,
    _line_intersects_any_table,
    furniture_group_id,
    is_page_furniture_association,
    reconstruct_cross_page_continuation,
    reconstruct_document_associations,
    reconstruct_heading_to_table,
    reconstruct_line_label_continuations,
    reconstruct_page_associations,
    reconstruct_page_furniture,
    reconstruct_table_label_continuations,
)
from app.services.common_representation.types import (  # noqa: E402
    EvidenceOrigin,
    PageGeometry,
    SpatialAssociation,
    SpatialRegion,
    SpatialRegionType,
    SpatialRelationKind,
)
from app.utils.pdf.pymupdf_extractor import (  # noqa: E402
    PageExtraction,
    _extract_table_regions,
    _page_word_items,
)

BACKEND_DIR = Path(__file__).resolve().parents[1]
DOCUMENTS_DIR = BACKEND_DIR / "data" / "documents"

# Prefer the copies already used by Phase 6.21/6.22 tests when present.
_PREFERRED_PARENTS = {
    "Laguna State Polytechnic University-CC_2026-1st Edition.pdf": "da4a1832-7242-4e94-8ba6-bc0b9f2294bf",
    "LSPU Student Handbook.pdf": "d9bf05ce-fcab-4629-ad4c-4f869481189f",
    "LSPU Faculty Manual 2020.pdf": "c67bd8c8-81cd-4c8c-bda1-4f7d2039a406",
    "pipeline_demo_test.pdf": "aaf5619a-8996-43e7-b6c0-af6efcf9f4cc",
}


def _require_pdf(filename: str) -> Path:
    """Resolve a real PDF under data/documents, or fail as unavailable."""
    preferred = DOCUMENTS_DIR / _PREFERRED_PARENTS.get(filename, "") / filename
    if preferred.is_file():
        return preferred
    matches = sorted(
        path for path in DOCUMENTS_DIR.rglob(filename) if path.is_file()
    )
    if not matches:
        pytest.fail(
            f"Characterization fixture unavailable: {filename!r} was not found "
            f"under {DOCUMENTS_DIR}."
        )
    return matches[0]


def _extract_real_page(pdf_path: Path, page_number: int) -> tuple[PageExtraction, tuple[float, float]]:
    """Digital page extraction using production PyMuPDF helpers, not a stub."""
    document = fitz.open(str(pdf_path))
    try:
        if page_number < 1 or page_number > document.page_count:
            pytest.fail(
                f"Characterization fixture unavailable: {pdf_path.name} has no "
                f"physical page {page_number} (page_count={document.page_count})."
            )
        page = document[page_number - 1]
        rect = (float(page.rect.width), float(page.rect.height))
        extraction = PageExtraction(
            page_number=page_number,
            text=page.get_text() or "",
            method="digital",
            words=_page_word_items(page) or None,
            table_regions=_extract_table_regions(page) or None,
            geometry_scale=1.0,
            page_width=rect[0],
            page_height=rect[1],
            coordinate_width=rect[0],
            coordinate_height=rect[1],
        )
        return extraction, rect
    finally:
        document.close()


def _geometry(pdf_path: Path, page_number: int) -> tuple[PageGeometry, tuple[float, float]]:
    extraction, rect = _extract_real_page(pdf_path, page_number)
    return build_page_geometry(extraction), rect


def _region_map(geometry: PageGeometry) -> dict[str, SpatialRegion]:
    return {region.region_id: region for region in geometry.regions}


def _assoc_regions(geometry: PageGeometry, association: SpatialAssociation) -> list[SpatialRegion]:
    by_id = _region_map(geometry)
    return [by_id[region_id] for region_id in association.region_ids if region_id in by_id]


def _joined_text(regions: list[SpatialRegion]) -> str:
    return " ".join(region.text for region in regions)


# ---------------------------------------------------------------------------
# Case A — Handbook page 80: running header falsely bound to chrome table
# ---------------------------------------------------------------------------


def _handbook_chrome_and_body_tables(geometry: PageGeometry) -> tuple[SpatialRegion, SpatialRegion]:
    tables = [
        region
        for region in geometry.regions
        if region.region_type == SpatialRegionType.TABLE and region.bbox is not None
    ]
    assert len(tables) >= 2, "handbook disciplinary pages expose header chrome and a body table"
    tables_top_to_bottom = sorted(tables, key=lambda region: region.bbox[1])  # type: ignore[index]
    chrome_table = tables_top_to_bottom[0]
    body_table = tables_top_to_bottom[-1]
    assert "Institution" in (chrome_table.text or "") or "Doc. No" in (chrome_table.text or "")
    assert "Offense" in (body_table.text or "")
    return chrome_table, body_table


def _confirmed_heading_word_text(geometry: PageGeometry, association: SpatialAssociation) -> str:
    return " ".join(
        region.text
        for region in _assoc_regions(geometry, association)
        if region.region_type == SpatialRegionType.WORD
    )


def test_handbook_page_80_running_header_not_associated_with_body_table():
    """CORRECTED (Phase 7.4D).

    The running-header line lives inside the chrome table. Two-dimensional
    eligibility excludes it, so it cannot own the disciplinary body table.
    """
    pdf = _require_pdf("LSPU Student Handbook.pdf")
    geometry, _rect = _geometry(pdf, 80)
    chrome_table, body_table = _handbook_chrome_and_body_tables(geometry)

    headings = reconstruct_heading_to_table(geometry)
    chrome_as_body_heading = []
    for assoc in headings:
        if assoc.kind != SpatialRelationKind.HEADING_TO_TABLE:
            continue
        if body_table.region_id not in assoc.region_ids:
            continue
        word_text = _confirmed_heading_word_text(geometry, assoc)
        if "Student Handbook" in word_text and "Page:" in word_text:
            chrome_as_body_heading.append(assoc)
        if assoc.origin == EvidenceOrigin.LAYOUT_RECONSTRUCTED:
            assert "Student Handbook" not in word_text or "Page:" not in word_text
    assert chrome_as_body_heading == []
    assert all(chrome_table.region_id not in assoc.region_ids for assoc in headings)


@pytest.mark.parametrize("page_number", [78, 79, 80, 81])
def test_handbook_pages_78_to_81_chrome_line_does_not_own_body_table(page_number: int):
    """The repeating chrome table on consecutive disciplinary pages must
    not supply the body table's heading."""
    pdf = _require_pdf("LSPU Student Handbook.pdf")
    geometry, _rect = _geometry(pdf, page_number)
    _chrome_table, body_table = _handbook_chrome_and_body_tables(geometry)
    headings = reconstruct_heading_to_table(geometry)
    for assoc in headings:
        if body_table.region_id not in assoc.region_ids:
            continue
        word_text = _confirmed_heading_word_text(geometry, assoc)
        assert not ("Student Handbook" in word_text and "Page:" in word_text)
        if assoc.origin == EvidenceOrigin.LAYOUT_RECONSTRUCTED:
            assert "Page:" not in word_text


def test_handbook_page_82_article_3_remains_associated_with_its_table():
    """POSITIVE CONTROL (Phase 7.4D).

    `Article 3. Minor Offense` sits outside every table and immediately
    above its genuine body table. Eligibility must not drop it.
    """
    pdf = _require_pdf("LSPU Student Handbook.pdf")
    geometry, _rect = _geometry(pdf, 82)
    headings = [
        assoc
        for assoc in reconstruct_heading_to_table(geometry)
        if assoc.origin == EvidenceOrigin.LAYOUT_RECONSTRUCTED
        and assoc.kind == SpatialRelationKind.HEADING_TO_TABLE
    ]
    match = None
    for assoc in headings:
        word_text = _confirmed_heading_word_text(geometry, assoc)
        if "Article 3. Minor Offense" in word_text:
            match = assoc
            break
    assert match is not None, "Article 3. Minor Offense must remain a confirmed heading-to-table owner"
    tables = [
        region
        for region in _assoc_regions(geometry, match)
        if region.region_type == SpatialRegionType.TABLE
    ]
    assert len(tables) == 1
    assert "Offense" in (tables[0].text or "")
    assert "Institution" not in (tables[0].text or "")


# ---------------------------------------------------------------------------
# Case B — Faculty Manual page 20: numbered duties as false continuations
# ---------------------------------------------------------------------------


def test_faculty_page_20_numbered_duty_items_are_not_joined():
    """CORRECTED (Phase 7.4B).

    Independently numbered duty items on Faculty Manual page 20 must not
    be associated as continuations of one another. A wrap of the SAME
    item onto an unnumbered following line is a different relationship:
    it may remain an unresolved (MISSING) candidate when only
    incompleteness is present, but it is not a join of two numbered items.
    """
    pdf = _require_pdf("LSPU Faculty Manual 2020.pdf")
    geometry, _rect = _geometry(pdf, 20)
    assert any(
        region.region_type == SpatialRegionType.WORD for region in geometry.regions
    )

    associations = reconstruct_line_label_continuations(geometry)
    duty_prefixes = (
        "3. check computer generated daily time record",
        "4. render a total of forty",
        "5. be allowed to have flexible working hours",
        "6.1. those designated to perform supervisory functions",
        "6.2. those performing mainly auxiliary service",
        "6.3. all other assigned in performing administrative functions",
    )
    independent_pairs = (
        ("3. check computer generated daily time record", "4. render a total of forty"),
        ("4. render a total of forty", "5. be allowed to have flexible working hours"),
        (
            "5. be allowed to have flexible working hours",
            "6.1. those designated to perform supervisory functions",
        ),
        (
            "6.1. those designated to perform supervisory functions",
            "6.2. those performing mainly auxiliary service",
        ),
        (
            "6.2. those performing mainly auxiliary service",
            "6.3. all other assigned in performing administrative functions",
        ),
        (
            "6. perform an eighteen-hour actual teaching load per week, except:",
            "6.1. those designated to perform supervisory functions",
        ),
    )

    for association in associations:
        assert association.kind == SpatialRelationKind.CONTINUATION
        note = association.note or ""
        hits = [prefix for prefix in duty_prefixes if prefix in note]
        assert len(hits) <= 1, (
            "Independent numbered duty items must not be joined as a "
            f"continuation; note paired {hits}: {note}"
        )
        following = note.rsplit(" + ", 1)[-1] if " + " in note else ""
        for prefix in duty_prefixes:
            assert prefix not in following, (
                "A new numbered duty item must not be the continuation "
                f"target of a prior line; found {prefix!r} in {note}"
            )
        for left, right in independent_pairs:
            assert not (left in note and right in note), (
                "Independent numbered duty items must not share a "
                f"continuation association: {left!r} + {right!r} in {note}"
            )

    wrap_of_item_3 = [
        association
        for association in associations
        if "3. check computer generated daily time record" in (association.note or "")
        and "the authorized officer" in (association.note or "").casefold()
    ]
    assert wrap_of_item_3, (
        "Unnumbered overflow of numbered item 3 must remain eligible; "
        "numbering on the first line is not a rejection."
    )
    assert all(association.origin == EvidenceOrigin.MISSING for association in wrap_of_item_3)


# ---------------------------------------------------------------------------
# Case C — Charter page 80: subtitle treated as heading
# ---------------------------------------------------------------------------


def test_charter_page_80_subtitle_not_confirmed_as_table_owner():
    """CORRECTED (Phase 7.4D).

    The numbered service title and the indented subtitle are both eligible
    lines above the NSTP table. Nearest-line selection must not confirm
    `Colors and security` (or the second service's subtitle) as owner.
    """
    pdf = _require_pdf("Laguna State Polytechnic University-CC_2026-1st Edition.pdf")
    geometry, _rect = _geometry(pdf, 80)

    word_blob = " ".join(
        region.text
        for region in geometry.regions
        if region.region_type == SpatialRegionType.WORD
    )
    assert "Request of colors and security" in word_blob
    assert "Colors and security" in word_blob
    assert "Certificate of completion with serial number" in word_blob
    assert any(
        region.region_type == SpatialRegionType.TABLE and region.bbox is not None
        for region in geometry.regions
    )

    confirmed = [
        assoc
        for assoc in reconstruct_heading_to_table(geometry)
        if assoc.origin == EvidenceOrigin.LAYOUT_RECONSTRUCTED
        and assoc.kind == SpatialRelationKind.HEADING_TO_TABLE
    ]
    confirmed_notes = " ".join(assoc.note or "" for assoc in confirmed)
    assert "Colors and security" not in confirmed_notes or "Request of colors" in confirmed_notes
    for assoc in confirmed:
        note = assoc.note or ""
        assert not (
            "Colors and security" in note and "Request of colors" not in note
        )
        assert "Certificate of completion with serial number" not in note or (
            "2. Request of certificate of completion" in note
        )

    for assoc in confirmed:
        word_text = _confirmed_heading_word_text(geometry, assoc)
        assert word_text.strip() != "Colors and security"
        assert word_text.strip() != "Certificate of completion with serial number"


# ---------------------------------------------------------------------------
# Case D — Charter pages 10–11: folio number falsely continued
# ---------------------------------------------------------------------------


def test_charter_pages_10_11_folio_not_joined_to_next_page():
    """CORRECTED (Phase 7.4A).

    Page 10's last grouped line is the printed folio "2", isolated below
    the body. Page 11 starts mid-table with lowercase leftover text.
    Cross-page continuation must not confirm a join from that folio into
    the leftover -- the folio is page furniture, not a content endpoint.
    """
    pdf = _require_pdf("Laguna State Polytechnic University-CC_2026-1st Edition.pdf")
    geometry_10, _rect_10 = _geometry(pdf, 10)
    geometry_11, _rect_11 = _geometry(pdf, 11)

    associations = reconstruct_cross_page_continuation(
        geometry_10, geometry_11, furniture_region_ids=frozenset()
    )
    confirmed = [
        assoc
        for assoc in associations
        if assoc.origin == EvidenceOrigin.LAYOUT_RECONSTRUCTED
        and assoc.kind == SpatialRelationKind.CONTINUATION
    ]

    page_10_ids = {
        region.region_id
        for region in geometry_10.regions
        if region.region_type == SpatialRegionType.WORD
    }
    page_11_ids = {
        region.region_id
        for region in geometry_11.regions
        if region.region_type == SpatialRegionType.WORD
    }
    folio_join = None
    for assoc in confirmed:
        left = [
            region
            for region in _assoc_regions(geometry_10, assoc)
            if region.region_id in page_10_ids
        ]
        right = [
            region
            for region in _assoc_regions(geometry_11, assoc)
            if region.region_id in page_11_ids
        ]
        left_text = _joined_text(left).strip()
        right_text = _joined_text(right)
        if left_text == "2" and "copy of enrolment" in right_text.casefold():
            folio_join = assoc
            break
    assert folio_join is None, (
        "Folio '2' on page 10 must not be joined to leftover "
        "'copy of enrolment' text on page 11."
    )
    assert all(
        _joined_text(
            [region for region in _assoc_regions(geometry_10, assoc) if region.region_id in page_10_ids]
        ).strip()
        != "2"
        for assoc in confirmed
    )


# ---------------------------------------------------------------------------
# Case E — Charter page 37: positive table-cell wrap
# ---------------------------------------------------------------------------


def test_charter_page_37_office_or_division_table_cell_continuation_still_observed():
    """POSITIVE CONTROL.

    Native table cells on Charter page 37 still reconstruct 'Office or' +
    'Division:' as a confirmed same-column continuation.
    """
    pdf = _require_pdf("Laguna State Polytechnic University-CC_2026-1st Edition.pdf")
    geometry, _rect = _geometry(pdf, 37)

    cells = [
        region
        for region in geometry.regions
        if region.region_type == SpatialRegionType.CELL
    ]
    office_cells = [cell for cell in cells if cell.text.strip() == "Office or"]
    division_cells = [cell for cell in cells if cell.text.strip() == "Division:"]
    assert office_cells and division_cells
    assert all(cell.bbox is None for cell in office_cells + division_cells)

    associations = reconstruct_table_label_continuations(geometry)
    confirmed = [
        assoc
        for assoc in associations
        if assoc.origin == EvidenceOrigin.LAYOUT_RECONSTRUCTED
        and assoc.kind == SpatialRelationKind.CONTINUATION
    ]
    match = None
    for assoc in confirmed:
        texts = {region.text.strip() for region in _assoc_regions(geometry, assoc)}
        if texts == {"Office or", "Division:"}:
            match = assoc
            break
    assert match is not None, "Expected the real page-37 Office or / Division: cell continuation"
    assert match.confidence == 1.0
    assert match.origin == EvidenceOrigin.LAYOUT_RECONSTRUCTED
    endpoints = _assoc_regions(geometry, match)
    assert {cell.page_number for cell in endpoints} == {37}
    rows = sorted(cell.row for cell in endpoints if cell.row is not None)
    columns = {cell.column for cell in endpoints if cell.column is not None}
    assert len(columns) == 1
    assert len(rows) == 2 and rows[1] == rows[0] + 1

    word_path = reconstruct_line_label_continuations(geometry)
    for assoc in word_path:
        texts = {region.text.strip() for region in _assoc_regions(geometry, assoc)}
        assert not ({"Office", "or", "Division:"} <= texts or {"Office or", "Division:"} <= texts)


# ---------------------------------------------------------------------------
# Case F — Narrative control
# ---------------------------------------------------------------------------


def test_pipeline_demo_narrative_pages_currently_produce_no_associations():
    """POSITIVE EMPTY CONTROL.

    The synthetic narrative demo has complete sentences and no tables.
    Current reconstruction produces no page or cross-page associations.
    """
    pdf = _require_pdf("pipeline_demo_test.pdf")
    page_1, _rect_1 = _geometry(pdf, 1)
    page_2, _rect_2 = _geometry(pdf, 2)

    assert reconstruct_page_associations(page_1) == []
    assert reconstruct_page_associations(page_2) == []
    assert reconstruct_cross_page_continuation(
        page_1, page_2, furniture_region_ids=frozenset()
    ) == []


# ---------------------------------------------------------------------------
# Case G — Page-size contrast is now preserved on PageGeometry
# ---------------------------------------------------------------------------


def test_charter_and_handbook_page_rects_reach_page_geometry():
    """Phase 7.3 geometry contract: Charter and Handbook page rectangles
    differ, and PageGeometry now carries those actual dimensions (not
    estimates, not a hardcoded size). Reconstruction behavior is unchanged.
    """
    charter = _require_pdf("Laguna State Polytechnic University-CC_2026-1st Edition.pdf")
    handbook = _require_pdf("LSPU Student Handbook.pdf")
    charter_geometry, charter_rect = _geometry(charter, 1)
    handbook_geometry, handbook_rect = _geometry(handbook, 1)

    assert charter_rect[0] == pytest.approx(595.3, abs=1.0)
    assert charter_rect[1] == pytest.approx(841.9, abs=1.0)
    assert handbook_rect[0] == pytest.approx(468.0, abs=1.0)
    assert handbook_rect[1] == pytest.approx(612.0, abs=1.0)
    assert charter_rect != handbook_rect

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


def _page_tables(geometry: PageGeometry) -> list[SpatialRegion]:
    return [
        region
        for region in geometry.regions
        if region.region_type == SpatialRegionType.TABLE and region.bbox is not None
    ]


def _table_contained_word_ids(geometry: PageGeometry) -> set[str]:
    tables = _page_tables(geometry)
    contained: set[str] = set()
    for line in _group_words_into_lines(geometry):
        if _line_intersects_any_table(line, tables):
            contained.update(line.word_region_ids)
    return contained


# ---------------------------------------------------------------------------
# Case H — Charter page 11 table-aware line continuation (Phase 7.6)
# ---------------------------------------------------------------------------


def test_charter_page_11_table_contained_lines_are_not_ordinary_continuations():
    """Phase 7.5 observed 35 confirmed ordinary line-continuations among
    51 lines on Charter page 11, 50 of which intersected a native table.

    After 7.6, no table-contained line may participate in the ordinary
    line-continuation path. Remaining non-table lines are inspected
    independently; excluded table-internal wraps are not re-created as
    word-path associations.
    """
    pdf = _require_pdf("Laguna State Polytechnic University-CC_2026-1st Edition.pdf")
    geometry, _rect = _geometry(pdf, 11)
    tables = _page_tables(geometry)
    lines = _group_words_into_lines(geometry)
    intersecting = [line for line in lines if _line_intersects_any_table(line, tables)]
    outside = [line for line in lines if not _line_intersects_any_table(line, tables)]

    assert len(lines) == 51
    assert len(intersecting) == 50
    assert len(outside) == 1

    contained_ids = _table_contained_word_ids(geometry)
    line_assocs = reconstruct_line_label_continuations(geometry)
    for assoc in line_assocs:
        assert assoc.kind == SpatialRelationKind.CONTINUATION
        assert set(assoc.region_ids).isdisjoint(contained_ids)

    confirmed = [a for a in line_assocs if a.origin == EvidenceOrigin.LAYOUT_RECONSTRUCTED]
    unresolved = [a for a in line_assocs if a.origin == EvidenceOrigin.MISSING]
    assert confirmed == []
    assert unresolved == []

    # The only non-table line is the isolated bottom folio, below the
    # native table and with no non-table neighbor. It is not a wrap of
    # table-internal procedure text.
    folio = outside[0]
    assert folio.text.strip() == "3"
    assert folio.y0 > max(table.bbox[3] for table in tables)

    cell_assocs = reconstruct_table_label_continuations(geometry)
    # Current cell-path signals (colon completion + empty sibling
    # columns) do not reconstruct the table-internal wraps previously
    # claimed by the word path. Leaving them unresolved is required;
    # this phase does not invent replacements.
    assert cell_assocs == []


@pytest.mark.parametrize("page_number", [78, 79, 80, 81, 82])
def test_handbook_chrome_table_lines_are_not_ordinary_line_continuations(page_number: int):
    """Repeating Handbook chrome lives inside native tables. Phase 7.6
    must not interpret those lines as ordinary prose continuation, and
    must not invent new word-path wraps from chrome or body tables.
    Cross-page furniture is out of scope.
    """
    pdf = _require_pdf("LSPU Student Handbook.pdf")
    geometry, _rect = _geometry(pdf, page_number)
    contained_ids = _table_contained_word_ids(geometry)
    for assoc in reconstruct_line_label_continuations(geometry):
        assert assoc.kind == SpatialRelationKind.CONTINUATION
        assert set(assoc.region_ids).isdisjoint(contained_ids)


@pytest.fixture(scope="module")
def handbook_pages() -> list[PageGeometry]:
    return _all_geometries(_require_pdf("LSPU Student Handbook.pdf"))


@pytest.fixture(scope="module")
def faculty_pages() -> list[PageGeometry]:
    return _all_geometries(_require_pdf("LSPU Faculty Manual 2020.pdf"))


@pytest.fixture(scope="module")
def charter_pages() -> list[PageGeometry]:
    return _all_geometries(_require_pdf("Laguna State Polytechnic University-CC_2026-1st Edition.pdf"))


def _all_geometries(pdf_path: Path) -> list[PageGeometry]:
    document = fitz.open(str(pdf_path))
    pages: list[PageGeometry] = []
    try:
        for index in range(document.page_count):
            page = document[index]
            rect = (float(page.rect.width), float(page.rect.height))
            extraction = PageExtraction(
                page_number=index + 1,
                text=page.get_text() or "",
                method="digital",
                words=_page_word_items(page) or None,
                table_regions=_extract_table_regions(page) or None,
                geometry_scale=1.0,
                page_width=rect[0],
                page_height=rect[1],
                coordinate_width=rect[0],
                coordinate_height=rect[1],
            )
            pages.append(build_page_geometry(extraction))
    finally:
        document.close()
    return pages


def _xpage_pairs(pages: list[PageGeometry], furniture_ids: set[str]):
    for left, right in zip(pages, pages[1:]):
        for assoc in reconstruct_cross_page_continuation(
            left, right, furniture_region_ids=furniture_ids
        ):
            yield left.page_number, right.page_number, assoc


# ---------------------------------------------------------------------------
# Case I — Phase 7.8 page furniture and cross-page endpoints
# ---------------------------------------------------------------------------


def test_handbook_chrome_is_furniture_and_false_joins_are_removed(handbook_pages):
    """Handbook top chrome (198 pages, duplex x-shift, variable page field)
    is one recurrence group. Previously confirmed Institution: joins must
    not remain LAYOUT_RECONSTRUCTED. Source tables are referenced, not
    deleted.
    """
    pages = handbook_pages
    assert len(pages) == 198
    furniture = reconstruct_page_furniture(pages)
    assert len(furniture) == 1
    group = furniture[0]
    assert is_page_furniture_association(group)
    assert furniture_group_id(group)
    assert group.kind == SpatialRelationKind.PAGE_FURNITURE
    assert group.origin == EvidenceOrigin.LAYOUT_RECONSTRUCTED
    assert group.confidence == 1.0
    assert ":header" in group.association_id
    assert len(group.region_ids) == 198
    furniture_ids = set(group.region_ids)

    by_id = {region.region_id: region for page in pages for region in page.regions}
    heights = []
    x0s = []
    for region_id in group.region_ids:
        table = by_id[region_id]
        assert table.region_type == SpatialRegionType.TABLE
        assert table.bbox is not None
        heights.append(table.bbox[3] - table.bbox[1])
        x0s.append(table.bbox[0])
        page_h = next(p.height for p in pages if p.page_number == table.page_number)
        assert page_h
        assert (table.bbox[3] - table.bbox[1]) / page_h <= 0.15
    assert max(heights) - min(heights) < 2.0
    assert max(x0s) - min(x0s) > 10.0  # duplex gutter shift
    # Variable page metadata: member texts are not all identical.
    texts = {by_id[rid].text for rid in group.region_ids}
    assert len(texts) > 1

    confirmed_to_chrome = []
    for a, b, assoc in _xpage_pairs(pages, furniture_ids):
        if assoc.origin != EvidenceOrigin.LAYOUT_RECONSTRUCTED:
            continue
        if "Institution:" in (assoc.note or ""):
            confirmed_to_chrome.append((a, b, assoc.note))
    assert confirmed_to_chrome == []

    # Body table on p80 is not furniture.
    p80 = next(p for p in pages if p.page_number == 80)
    body_tables = [
        r
        for r in p80.regions
        if r.region_type == SpatialRegionType.TABLE
        and r.bbox is not None
        and r.region_id not in furniture_ids
    ]
    assert body_tables
    assert any("Section/Title/Definition" in (t.text or "") for t in body_tables)


def test_handbook_p31_p32_genuine_wrap_recovers_under_chrome(handbook_pages):
    pages = handbook_pages
    furniture_ids = set(reconstruct_page_furniture(pages)[0].region_ids)
    p31 = next(p for p in pages if p.page_number == 31)
    p32 = next(p for p in pages if p.page_number == 32)
    associations = reconstruct_cross_page_continuation(
        p31, p32, furniture_region_ids=furniture_ids
    )
    assert len(associations) == 1
    assert associations[0].origin == EvidenceOrigin.LAYOUT_RECONSTRUCTED
    note = associations[0].note or ""
    assert "provid-" in note
    assert "ed such subjects" in note
    assert "Institution:" not in note


def test_handbook_document_level_path_recovers_p31_p32(handbook_pages):
    """Protected path: reconstruct_document_associations, not a two-arg call."""
    associations = reconstruct_document_associations(handbook_pages)
    wraps = [
        assoc
        for assoc in associations
        if assoc.kind == SpatialRelationKind.CONTINUATION
        and assoc.origin == EvidenceOrigin.LAYOUT_RECONSTRUCTED
        and assoc.association_id.startswith("assoc:xpage:")
        and "provid-" in (assoc.note or "")
        and "ed such subjects" in (assoc.note or "")
    ]
    assert len(wraps) == 1
    assert "Institution:" not in (wraps[0].note or "")
    furniture = [a for a in associations if is_page_furniture_association(a)]
    assert len(furniture) == 1
    assert furniture[0].kind == SpatialRelationKind.PAGE_FURNITURE
    institution_joins = [
        assoc
        for assoc in associations
        if assoc.origin == EvidenceOrigin.LAYOUT_RECONSTRUCTED
        and "Institution:" in (assoc.note or "")
        and assoc.association_id.startswith("assoc:xpage:")
    ]
    assert institution_joins == []


def test_handbook_p78_p80_body_to_content_remains_unresolved(handbook_pages):
    """Skipping chrome must not promote the previously MISSING pairs."""
    pages = handbook_pages
    furniture_ids = set(reconstruct_page_furniture(pages)[0].region_ids)
    for a_n, b_n in ((78, 79), (79, 80)):
        left = next(p for p in pages if p.page_number == a_n)
        right = next(p for p in pages if p.page_number == b_n)
        associations = reconstruct_cross_page_continuation(
            left, right, furniture_region_ids=furniture_ids
        )
        for assoc in associations:
            assert "Institution:" not in (assoc.note or "")
            assert assoc.origin != EvidenceOrigin.LAYOUT_RECONSTRUCTED


def test_faculty_chrome_is_furniture_and_false_joins_are_removed(faculty_pages):
    pages = faculty_pages
    assert len(pages) == 106
    furniture = reconstruct_page_furniture(pages)
    assert len(furniture) == 1
    group = furniture[0]
    assert is_page_furniture_association(group)
    assert group.kind == SpatialRelationKind.PAGE_FURNITURE
    assert len(group.region_ids) == 106
    furniture_ids = set(group.region_ids)
    confirmed_to_chrome = []
    for a, b, assoc in _xpage_pairs(pages, furniture_ids):
        if assoc.origin != EvidenceOrigin.LAYOUT_RECONSTRUCTED:
            continue
        if "Institution:" in (assoc.note or ""):
            confirmed_to_chrome.append((a, b, assoc.note))
    assert confirmed_to_chrome == []


def test_faculty_p29_p30_genuine_wrap_recovers_under_chrome(faculty_pages):
    pages = faculty_pages
    furniture_ids = set(reconstruct_page_furniture(pages)[0].region_ids)
    p29 = next(p for p in pages if p.page_number == 29)
    p30 = next(p for p in pages if p.page_number == 30)
    associations = reconstruct_cross_page_continuation(
        p29, p30, furniture_region_ids=furniture_ids
    )
    assert len(associations) == 1
    assert associations[0].origin == EvidenceOrigin.LAYOUT_RECONSTRUCTED
    note = associations[0].note or ""
    assert "The La-" in note
    assert "guna State Polytechnic University" in note
    assert "Institution:" not in note


def test_faculty_p1_p2_remains_unresolved_after_furniture_skip(faculty_pages):
    pages = faculty_pages
    furniture_ids = set(reconstruct_page_furniture(pages)[0].region_ids)
    associations = reconstruct_cross_page_continuation(
        pages[0], pages[1], furniture_region_ids=furniture_ids
    )
    for assoc in associations:
        assert "Institution:" not in (assoc.note or "")
        assert assoc.origin != EvidenceOrigin.LAYOUT_RECONSTRUCTED


def test_charter_service_tables_and_page_11_are_not_furniture(charter_pages):
    pages = charter_pages
    furniture = reconstruct_page_furniture(pages)
    furniture_ids = {rid for group in furniture for rid in group.region_ids}
    p11 = next(p for p in pages if p.page_number == 11)
    p11_tables = [
        r.region_id
        for r in p11.regions
        if r.region_type == SpatialRegionType.TABLE
    ]
    assert p11_tables
    assert set(p11_tables).isdisjoint(furniture_ids)
    for page in pages:
        for region in page.regions:
            if region.region_type != SpatialRegionType.TABLE:
                continue
            text = (region.text or "").casefold()
            if "office or division" in text or "classification:" in text:
                assert region.region_id not in furniture_ids


def test_charter_pages_10_11_folio_safeguard_still_holds_with_furniture(charter_pages):
    pages = charter_pages
    furniture_ids = {rid for group in reconstruct_page_furniture(pages) for rid in group.region_ids}
    p10 = next(p for p in pages if p.page_number == 10)
    p11 = next(p for p in pages if p.page_number == 11)
    associations = reconstruct_cross_page_continuation(
        p10, p11, furniture_region_ids=furniture_ids
    )
    confirmed = [
        a
        for a in associations
        if a.origin == EvidenceOrigin.LAYOUT_RECONSTRUCTED
    ]
    for assoc in confirmed:
        assert "copy of enrolment" not in (assoc.note or "").casefold()
    # Folio 2 must not appear as a confirmed source.
    assert all("'2'" not in (a.note or "") for a in confirmed)
