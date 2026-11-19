"""Tests for the generic geometric reconstruction layer
(``app.services.common_representation.reconstruction``).

Covers synthetic, controlled geometric cases AND real production
extraction (the real Citizen's Charter PDF), per Phase 6.22's explicit
instruction to test both. The real-PDF cases use Citizen's Charter purely
as a VALIDATION FIXTURE for generic logic -- nothing here imports or
exercises ``citizen_charter_extractor_v2.py``'s own extraction-decision
code, and no assertion here is specific to Charter's domain vocabulary.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.common_representation.reconstruction import (  # noqa: E402
    associations_for_page_range,
    furniture_group_id,
    furniture_region_ids_on_page,
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

REAL_PDF_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "documents"
    / "da4a1832-7242-4e94-8ba6-bc0b9f2294bf"
    / "Laguna State Polytechnic University-CC_2026-1st Edition.pdf"
)


def _word(region_id: str, page: int, text: str, x0: float, y0: float, x1: float, y1: float, order: int) -> SpatialRegion:
    return SpatialRegion(
        region_id=region_id,
        page_number=page,
        region_type=SpatialRegionType.WORD,
        text=text,
        bbox=(x0, y0, x1, y1),
        reading_order_index=order,
    )


def _cell(region_id: str, page: int, text: str, row: int, column: int, table_index: int = 0) -> SpatialRegion:
    # Mirrors the real `build_page_geometry` ID convention exactly
    # (`p{page}:table:{i}:cell:{r}:{c}`) so `reconstruct_table_label_
    # continuations`'s table-grouping-by-ID-prefix logic behaves as it
    # would against real production data, not an arbitrary test string.
    full_id = f"p{page}:table:{table_index}:cell:{row}:{column}:{region_id}"
    return SpatialRegion(
        region_id=full_id,
        page_number=page,
        region_type=SpatialRegionType.CELL,
        text=text,
        row=row,
        column=column,
    )


def _table(region_id: str, page: int, bbox: tuple[float, float, float, float]) -> SpatialRegion:
    return SpatialRegion(
        region_id=region_id,
        page_number=page,
        region_type=SpatialRegionType.TABLE,
        text="",
        bbox=bbox,
    )


# ---------------------------------------------------------------------------
# 1. Aligned label/value reconstruction (synthetic, word-geometry based).
# ---------------------------------------------------------------------------


def test_aligned_split_label_reconstructed_from_word_geometry():
    """Modeled directly on the real page-37 'Office or' / 'Division:'
    split (same left-margin x0, small vertical gap, first line has no
    trailing punctuation, second line ends in ':')."""
    page = PageGeometry(
        page_number=1,
        regions=[
            _word("p1:w0", 1, "Office", 48.3, 487.9, 90.0, 500.2, 0),
            _word("p1:w1", 1, "or", 95.0, 487.9, 110.0, 500.2, 1),
            _word("p1:w2", 1, "Division:", 48.3, 500.5, 120.0, 512.8, 2),
        ],
    )
    associations = reconstruct_line_label_continuations(page)
    strong = [a for a in associations if a.origin == EvidenceOrigin.LAYOUT_RECONSTRUCTED]
    assert len(strong) == 1
    assert set(strong[0].region_ids) == {"p1:w0", "p1:w1", "p1:w2"}
    assert strong[0].confidence is not None and strong[0].confidence >= 2 / 3


# ---------------------------------------------------------------------------
# 2. Multi-column separation -- same-height text in different columns must
#    not be merged into one line or spuriously associated.
# ---------------------------------------------------------------------------


def test_multi_column_text_not_merged_across_columns():
    page = PageGeometry(
        page_number=1,
        regions=[
            # Column 1: two lines, reading order 0-1.
            _word("c1l1", 1, "Column", 40.0, 100.0, 80.0, 112.0, 0),
            _word("c1l2", 1, "Below.", 40.0, 120.0, 80.0, 132.0, 1),
            # Column 2: two lines at the SAME y-heights as column 1,
            # but later in reading order (sort=True already placed all of
            # column 1 before column 2).
            _word("c2l1", 1, "Second", 300.0, 100.0, 340.0, 112.0, 2),
            _word("c2l2", 1, "Text.", 300.0, 120.0, 340.0, 132.0, 3),
        ],
    )
    lines = reconstruct_line_label_continuations(page)
    # Both "Column"/"Below." end in sentence punctuation or lack alignment
    # issues -- but critically, no association should ever link a column-1
    # region to a column-2 region, since they are never adjacent in
    # reading_order_index.
    for assoc in lines:
        ids = set(assoc.region_ids)
        assert not (ids & {"c1l1", "c1l2"} and ids & {"c2l1", "c2l2"})


# ---------------------------------------------------------------------------
# 3. Heading-to-content (table) relationship.
# ---------------------------------------------------------------------------


def test_heading_immediately_above_table_is_associated():
    page = PageGeometry(
        page_number=1,
        regions=[
            _word("h0", 1, "Request", 48.0, 400.0, 90.0, 412.0, 0),
            _word("h1", 1, "of", 95.0, 400.0, 105.0, 412.0, 1),
            _word("h2", 1, "Service", 110.0, 400.0, 150.0, 412.0, 2),
            _table("t0", 1, (40.0, 420.0, 500.0, 600.0)),
        ],
    )
    associations = reconstruct_heading_to_table(page)
    strong = [a for a in associations if a.origin == EvidenceOrigin.LAYOUT_RECONSTRUCTED]
    assert len(strong) == 1
    assert "t0" in strong[0].region_ids
    assert {"h0", "h1", "h2"} <= set(strong[0].region_ids)


def test_heading_to_table_not_associated_when_another_table_intervenes():
    """Two tables on one page: the first table sits between a line and a
    second table -- the second table must NOT claim the line as its own
    heading (uniqueness precondition)."""
    page = PageGeometry(
        page_number=1,
        regions=[
            _word("h0", 1, "Heading", 48.0, 100.0, 90.0, 112.0, 0),
            _table("t0", 1, (40.0, 120.0, 500.0, 200.0)),
            _table("t1", 1, (40.0, 210.0, 500.0, 300.0)),
        ],
    )
    associations = reconstruct_heading_to_table(page)
    for assoc in associations:
        if "t1" in assoc.region_ids:
            assert "h0" not in assoc.region_ids


# ---------------------------------------------------------------------------
# 3b. Heading-to-table eligibility, corridor uniqueness, and ambiguity
#     (Phase 7.4D). Geometry is two-dimensional: positive-area overlap
#     on BOTH axes. Edge-touching is not interior intersection.
# ---------------------------------------------------------------------------


def test_heading_inside_target_table_is_not_a_candidate():
    page = PageGeometry(
        page_number=1,
        regions=[
            _word("inside", 1, "Cell text", 50.0, 150.0, 120.0, 162.0, 0),
            _table("t0", 1, (40.0, 100.0, 500.0, 300.0)),
        ],
    )
    assert reconstruct_heading_to_table(page) == []


def test_heading_inside_another_table_is_not_a_candidate():
    page = PageGeometry(
        page_number=1,
        regions=[
            _word("chrome", 1, "Title: Policy Manual Page: 1", 50.0, 30.0, 280.0, 42.0, 0),
            _table("chrome_tbl", 1, (40.0, 20.0, 400.0, 60.0)),
            _table("body", 1, (40.0, 80.0, 400.0, 300.0)),
        ],
    )
    associations = reconstruct_heading_to_table(page)
    assert all("chrome" not in assoc.region_ids for assoc in associations)
    assert all("Title: Policy Manual" not in (assoc.note or "") for assoc in associations)


def test_handbook_like_chrome_line_cannot_own_body_table():
    """Chrome-table line sits in the header table; body table is below.
    Positive-area containment excludes the chrome line even though it is
    the nearest text above the body table."""
    page = PageGeometry(
        page_number=1,
        regions=[
            _word("c0", 1, "Institution: University", 102.0, 21.0, 250.0, 31.0, 0),
            _word("c1", 1, "Title: Student Handbook Page: 71", 102.0, 55.0, 320.0, 65.0, 1),
            _table("chrome", 1, (36.6, 18.5, 410.5, 69.1)),
            _table("body", 1, (36.6, 74.0, 410.5, 576.0)),
        ],
    )
    associations = reconstruct_heading_to_table(page)
    confirmed = [assoc for assoc in associations if assoc.origin == EvidenceOrigin.LAYOUT_RECONSTRUCTED]
    assert confirmed == []
    assert all("Student Handbook" not in (assoc.note or "") for assoc in associations)


def test_vertically_aligned_side_table_does_not_exclude_heading():
    """A heading that shares y-range with a horizontally separate table
    remains eligible: intersection requires both axes."""
    page = PageGeometry(
        page_number=1,
        regions=[
            _word("h0", 1, "Service heading", 48.0, 100.0, 160.0, 112.0, 0),
            _table("side", 1, (400.0, 90.0, 540.0, 200.0)),
            _table("t0", 1, (40.0, 130.0, 200.0, 280.0)),
        ],
    )
    confirmed = [
        assoc
        for assoc in reconstruct_heading_to_table(page)
        if assoc.origin == EvidenceOrigin.LAYOUT_RECONSTRUCTED
    ]
    assert len(confirmed) == 1
    assert "h0" in confirmed[0].region_ids
    assert "t0" in confirmed[0].region_ids
    assert "side" not in confirmed[0].region_ids


def test_positive_area_overlap_excludes_partially_overlapping_line():
    """A line whose box dips into a table interior (positive area) is
    ineligible, even if most of the line sits above the table."""
    page = PageGeometry(
        page_number=1,
        regions=[
            _word("overlap", 1, "Partial overlap", 48.0, 110.0, 160.0, 125.0, 0),
            _table("t0", 1, (40.0, 120.0, 500.0, 300.0)),
        ],
    )
    assert reconstruct_heading_to_table(page) == []


def test_boundary_touch_at_table_top_remains_eligible():
    """Sharing only the table's top edge is zero-area contact, not
    interior overlap. The line stays a heading candidate."""
    page = PageGeometry(
        page_number=1,
        regions=[
            _word("h0", 1, "Article heading", 48.0, 100.0, 180.0, 120.0, 0),
            _table("t0", 1, (40.0, 120.0, 500.0, 300.0)),
        ],
    )
    confirmed = [
        assoc
        for assoc in reconstruct_heading_to_table(page)
        if assoc.origin == EvidenceOrigin.LAYOUT_RECONSTRUCTED
    ]
    assert len(confirmed) == 1
    assert "h0" in confirmed[0].region_ids


def test_boundary_touch_on_table_side_does_not_exclude_heading():
    """A heading whose right edge merely touches a side table's left
    edge still has no positive-area intersection with that table."""
    page = PageGeometry(
        page_number=1,
        regions=[
            _word("h0", 1, "Heading", 48.0, 100.0, 200.0, 112.0, 0),
            _table("side", 1, (200.0, 90.0, 340.0, 180.0)),
            _table("t0", 1, (40.0, 130.0, 180.0, 260.0)),
        ],
    )
    confirmed = [
        assoc
        for assoc in reconstruct_heading_to_table(page)
        if assoc.origin == EvidenceOrigin.LAYOUT_RECONSTRUCTED
    ]
    assert len(confirmed) == 1
    assert set(confirmed[0].region_ids) >= {"h0", "t0"}


def test_intervening_table_in_spatial_corridor_blocks_association():
    page = PageGeometry(
        page_number=1,
        regions=[
            _word("h0", 1, "Heading", 48.0, 100.0, 160.0, 112.0, 0),
            _table("mid", 1, (40.0, 130.0, 200.0, 180.0)),
            _table("t1", 1, (40.0, 200.0, 200.0, 300.0)),
        ],
    )
    associations = reconstruct_heading_to_table(page)
    for assoc in associations:
        if "t1" in assoc.region_ids:
            assert "h0" not in assoc.region_ids


def test_horizontally_separate_table_does_not_block_corridor():
    page = PageGeometry(
        page_number=1,
        regions=[
            _word("h0", 1, "Right heading", 320.0, 100.0, 450.0, 112.0, 0),
            _table("left", 1, (40.0, 120.0, 180.0, 190.0)),
            _table("right", 1, (300.0, 130.0, 500.0, 280.0)),
        ],
    )
    confirmed = [
        assoc
        for assoc in reconstruct_heading_to_table(page)
        if assoc.origin == EvidenceOrigin.LAYOUT_RECONSTRUCTED
    ]
    assert len(confirmed) == 1
    assert "h0" in confirmed[0].region_ids
    assert "right" in confirmed[0].region_ids
    assert "left" not in confirmed[0].region_ids


def test_target_table_is_not_treated_as_intervening():
    page = PageGeometry(
        page_number=1,
        regions=[
            _word("h0", 1, "Heading", 48.0, 100.0, 160.0, 112.0, 0),
            _table("t0", 1, (40.0, 130.0, 400.0, 280.0)),
        ],
    )
    confirmed = [
        assoc
        for assoc in reconstruct_heading_to_table(page)
        if assoc.origin == EvidenceOrigin.LAYOUT_RECONSTRUCTED
    ]
    assert len(confirmed) == 1
    assert confirmed[0].region_ids[-1] == "t0"


def test_intervening_table_edge_touch_of_corridor_does_not_block():
    """An upper table whose bottom edge coincides with the candidate
    line's bottom does not occupy the open corridor below the line."""
    page = PageGeometry(
        page_number=1,
        regions=[
            _word("h0", 1, "Heading", 48.0, 100.0, 160.0, 112.0, 0),
            _table("above", 1, (200.0, 40.0, 360.0, 112.0)),
            _table("t0", 1, (40.0, 130.0, 180.0, 260.0)),
        ],
    )
    confirmed = [
        assoc
        for assoc in reconstruct_heading_to_table(page)
        if assoc.origin == EvidenceOrigin.LAYOUT_RECONSTRUCTED
    ]
    assert len(confirmed) == 1
    assert "h0" in confirmed[0].region_ids
    assert "t0" in confirmed[0].region_ids


def test_single_eligible_heading_still_associated():
    page = PageGeometry(
        page_number=1,
        regions=[
            _word("h0", 1, "Only heading", 48.0, 400.0, 160.0, 412.0, 0),
            _table("t0", 1, (40.0, 420.0, 500.0, 600.0)),
        ],
    )
    confirmed = [
        assoc
        for assoc in reconstruct_heading_to_table(page)
        if assoc.origin == EvidenceOrigin.LAYOUT_RECONSTRUCTED
    ]
    assert len(confirmed) == 1
    assert confirmed[0].confidence == 1.0
    assert "Only heading" in (confirmed[0].note or "")


def test_multiple_eligible_headings_are_not_confirmed_by_nearest():
    """Numbered title and indented subtitle both sit in the distance
    window. Nearest-wins must not confirm the subtitle."""
    page = PageGeometry(
        page_number=1,
        regions=[
            _word("title", 1, "1. Request of colors and security", 72.0, 121.6, 280.0, 137.2, 0),
            _word("sub", 1, "Colors and security", 108.0, 144.3, 220.0, 157.6, 1),
            _table("t0", 1, (41.0, 176.6, 554.0, 467.0)),
        ],
    )
    associations = reconstruct_heading_to_table(page)
    confirmed = [assoc for assoc in associations if assoc.origin == EvidenceOrigin.LAYOUT_RECONSTRUCTED]
    assert confirmed == []
    unresolved = [assoc for assoc in associations if assoc.origin == EvidenceOrigin.MISSING]
    assert len(unresolved) == 1
    note = unresolved[0].note or ""
    assert "1. Request of colors and security" in note
    assert "Colors and security" in note
    assert unresolved[0].confidence is None
    assert "title" in unresolved[0].region_ids
    assert "sub" in unresolved[0].region_ids
    assert "t0" in unresolved[0].region_ids


def test_no_eligible_heading_produces_no_association():
    page = PageGeometry(
        page_number=1,
        regions=[
            _table("t0", 1, (40.0, 100.0, 500.0, 300.0)),
        ],
    )
    assert reconstruct_heading_to_table(page) == []


def test_distant_unique_heading_remains_unresolved():
    """One eligible candidate beyond the distance bound stays MISSING,
    matching the pre-7.4D unresolved behavior."""
    page = PageGeometry(
        page_number=1,
        regions=[
            _word("h0", 1, "Far heading", 48.0, 40.0, 160.0, 52.0, 0),
            _table("t0", 1, (40.0, 120.0, 500.0, 300.0)),
        ],
    )
    associations = reconstruct_heading_to_table(page)
    assert len(associations) == 1
    assert associations[0].origin == EvidenceOrigin.MISSING
    assert associations[0].confidence is None
    assert "Far heading" in (associations[0].note or "")
    assert associations[0].kind == SpatialRelationKind.HEADING_TO_TABLE


# ---------------------------------------------------------------------------
# 4. Table header/cell relationships -- documented as NOT implemented
#    (insufficient evidence: no per-cell bbox, no header-row flag in raw
#    table_regions). This test documents the limitation rather than
#    fabricating a capability.
# ---------------------------------------------------------------------------


def test_no_header_to_cell_association_is_fabricated_without_evidence():
    """An ordinary two-row data table (header word 'Name'/'Office' above
    real data 'Juan'/'Registrar') must NOT be flagged as any kind of
    label-continuation candidate -- neither cell ends in ':', and neither
    row's siblings are empty, so there is genuinely zero evidence of a
    split-label relationship here, not merely weak evidence."""
    page = PageGeometry(
        page_number=1,
        regions=[
            _cell("name_hdr", 1, "Name", 0, 0),
            _cell("office_hdr", 1, "Office", 0, 1),
            _cell("juan", 1, "Juan", 1, 0),
            _cell("registrar", 1, "Registrar", 1, 1),
        ],
    )
    associations = reconstruct_page_associations(page)
    assert associations == []


# ---------------------------------------------------------------------------
# 5. Cross-line continuity (table-cell variant) + 7/8. ambiguous / unrelated.
# ---------------------------------------------------------------------------


def test_table_cell_label_split_across_rows_reconstructed():
    """Modeled on the real page-37 native table_regions rows: column 1 has
    'Office or' then 'Division:' on the next row, with every other column
    in the continuation row empty."""
    page = PageGeometry(
        page_number=1,
        regions=[
            _cell("lbl0", 1, "Office or", 0, 1),
            _cell("val0", 1, "EXTENSION AND TRAINING SERVICES", 0, 3),
            _cell("lbl1", 1, "Division:", 1, 1),
            _cell("val1", 1, "", 1, 3),
        ],
    )
    associations = reconstruct_table_label_continuations(page)
    strong = [a for a in associations if a.origin == EvidenceOrigin.LAYOUT_RECONSTRUCTED]
    assert len(strong) == 1
    texts = {r.text for r in page.regions if r.region_id in strong[0].region_ids}
    assert texts == {"Office or", "Division:"}


def test_ambiguous_cell_pair_marked_unresolved_not_silently_dropped():
    """Only ONE signal present (second cell ends in ':', i.e. looks like a
    label completion) -- but the continuation row's sibling column is NOT
    empty, so it doesn't structurally look like a pure overflow row --
    must be reported as an explicit unresolved/MISSING candidate, not
    promoted to LAYOUT_RECONSTRUCTED and not silently discarded."""
    page = PageGeometry(
        page_number=1,
        regions=[
            _cell("a", 1, "Some label", 0, 0),
            _cell("b", 1, "continues:", 1, 0),
            _cell("sibling", 1, "not empty", 1, 1),
        ],
    )
    associations = reconstruct_table_label_continuations(page)
    assert len(associations) == 1
    assert associations[0].origin == EvidenceOrigin.MISSING


def test_unrelated_nearby_regions_remain_separate():
    """Two complete-looking sentences, vertically adjacent but NOT
    left-aligned and both already ending in periods -- must NOT be
    associated at all (0 signals -> nothing produced)."""
    page = PageGeometry(
        page_number=1,
        regions=[
            _word("a0", 1, "First sentence ends cleanly.", 48.0, 100.0, 220.0, 112.0, 0),
            _word("b0", 1, "Unrelated next paragraph starts here.", 180.0, 115.0, 420.0, 127.0, 1),
        ],
    )
    associations = reconstruct_line_label_continuations(page)
    assert associations == []


# ---------------------------------------------------------------------------
# 5b. Independent numbered content vs. genuine line continuation.
# ---------------------------------------------------------------------------


def test_same_indent_numbered_items_are_not_continued():
    """Two independently numbered items, consistent indentation, small
    gap, both incomplete. Shared-margin + incompleteness would otherwise
    confirm a continuation; the following line opens a new enumerated
    item, so nothing is produced."""
    page = PageGeometry(
        page_number=1,
        regions=[
            _word("a0", 1, "1. First duty remains incomplete", 56.0, 100.0, 280.0, 112.0, 0),
            _word("b0", 1, "2. Second duty also incomplete", 56.0, 113.0, 280.0, 125.0, 1),
        ],
    )
    assert reconstruct_line_label_continuations(page) == []


def test_differently_indented_numbered_items_are_not_continued():
    """A nested enumerated item is still a new item, even when hanging
    indent plus incompleteness would previously emit an unresolved
    continuation."""
    page = PageGeometry(
        page_number=1,
        regions=[
            _word("a0", 1, "6. Outer duty remains incomplete", 56.0, 100.0, 280.0, 112.0, 0),
            _word("b0", 1, "6.1. Nested duty also incomplete", 74.0, 113.0, 300.0, 125.0, 1),
        ],
    )
    assert reconstruct_line_label_continuations(page) == []


def test_lettered_and_parenthesized_enumerators_are_independent_items():
    """The independent-item check is a generic enumerator token shape,
    not a single decimal scheme and not a phrase list."""
    lettered = PageGeometry(
        page_number=1,
        regions=[
            _word("a0", 1, "a. First lettered item stays incomplete", 56.0, 100.0, 300.0, 112.0, 0),
            _word("b0", 1, "b. Second lettered item also incomplete", 56.0, 113.0, 300.0, 125.0, 1),
        ],
    )
    parenthesized = PageGeometry(
        page_number=1,
        regions=[
            _word("c0", 1, "(1) First parenthesized item stays incomplete", 56.0, 200.0, 320.0, 212.0, 0),
            _word("d0", 1, "(2) Second parenthesized item also incomplete", 56.0, 213.0, 320.0, 225.0, 1),
        ],
    )
    assert reconstruct_line_label_continuations(lettered) == []
    assert reconstruct_line_label_continuations(parenthesized) == []


def test_unnumbered_genuine_continuation_still_reconstructed():
    """Unnumbered wrap with shared margin, incomplete first line, and
    label completion -- the existing positive line-continuation shape
    must remain confirmed."""
    page = PageGeometry(
        page_number=1,
        regions=[
            _word("a0", 1, "Please refer to the", 70.0, 200.0, 180.0, 212.0, 0),
            _word("b0", 1, "attached schedule:", 70.0, 213.0, 190.0, 225.0, 1),
        ],
    )
    strong = [
        assoc
        for assoc in reconstruct_line_label_continuations(page)
        if assoc.origin == EvidenceOrigin.LAYOUT_RECONSTRUCTED
    ]
    assert len(strong) == 1
    assert "Please refer to the" in (strong[0].note or "")
    assert "attached schedule:" in (strong[0].note or "")


def test_wrapped_numbered_item_unnumbered_overflow_remains_eligible():
    """A numbered item whose following line is NOT independently numbered
    remains a continuation candidate. Numbering on the first line is not
    a rejection. Hanging overflow with only the incompleteness signal is
    left unresolved rather than confirmed or discarded."""
    page = PageGeometry(
        page_number=1,
        regions=[
            _word("a0", 1, "1. Submit the completed form to", 56.0, 100.0, 280.0, 112.0, 0),
            _word("b0", 1, "the records office for stamping", 74.0, 113.0, 300.0, 125.0, 1),
        ],
    )
    associations = reconstruct_line_label_continuations(page)
    assert len(associations) == 1
    assert associations[0].kind == SpatialRelationKind.CONTINUATION
    assert associations[0].origin == EvidenceOrigin.MISSING
    note = associations[0].note or ""
    assert "1. Submit the completed form to" in note
    assert "the records office for stamping" in note


def test_leading_quantity_is_not_treated_as_an_enumerator():
    """A wrap line starting with a quantity ('18 hours...') contains
    digits but is not an enumeration marker. It must remain eligible,
    unlike a true '2.' / '6.1.' item start."""
    page = PageGeometry(
        page_number=1,
        regions=[
            _word("a0", 1, "4. render forty hours exclusive of time for", 56.0, 100.0, 300.0, 112.0, 0),
            _word("b0", 1, "18 hours of which shall be actual teaching", 74.0, 113.0, 320.0, 125.0, 1),
        ],
    )
    associations = reconstruct_line_label_continuations(page)
    assert len(associations) == 1
    assert "18 hours of which shall be actual teaching" in (associations[0].note or "")
    assert associations[0].origin == EvidenceOrigin.MISSING


def test_numbered_item_with_aligned_label_completion_still_reconstructed():
    """Numbering on the first line does not block a genuine wrap that
    also shares a column and completes a label."""
    page = PageGeometry(
        page_number=1,
        regions=[
            _word("a0", 1, "3. Office or", 48.3, 487.9, 120.0, 500.2, 0),
            _word("b0", 1, "Division:", 48.3, 500.5, 120.0, 512.8, 1),
        ],
    )
    strong = [
        assoc
        for assoc in reconstruct_line_label_continuations(page)
        if assoc.origin == EvidenceOrigin.LAYOUT_RECONSTRUCTED
    ]
    assert len(strong) == 1
    assert set(strong[0].region_ids) == {"a0", "b0"}


def test_ambiguous_adjacent_complete_lines_are_not_force_associated():
    """Same left margin, vertically adjacent, but both lines already
    complete -- exactly one signal (shared margin). Left unresolved,
    not promoted to LAYOUT_RECONSTRUCTED and not silently discarded."""
    page = PageGeometry(
        page_number=1,
        regions=[
            _word("a0", 1, "The first sentence is already complete.", 56.0, 100.0, 300.0, 112.0, 0),
            _word("b0", 1, "The second sentence is also complete.", 56.0, 113.0, 300.0, 125.0, 1),
        ],
    )
    associations = reconstruct_line_label_continuations(page)
    assert len(associations) == 1
    assert associations[0].origin == EvidenceOrigin.MISSING
    assert associations[0].kind == SpatialRelationKind.CONTINUATION


# ---------------------------------------------------------------------------
# 5b. Table-aware ordinary line continuation (Phase 7.6).
#     Table-contained lines are ineligible for the WORD-geometry path;
#     reconstructable cell wraps remain the table-cell path's job.
# ---------------------------------------------------------------------------


def test_ordinary_prose_continuation_still_reconstructs_when_no_table_intersects():
    """Two aligned incomplete/completion lines with no table on the page
    still form a confirmed ordinary continuation."""
    page = PageGeometry(
        page_number=1,
        regions=[
            _word("a0", 1, "Office", 48.0, 100.0, 90.0, 112.0, 0),
            _word("a1", 1, "or", 95.0, 100.0, 110.0, 112.0, 1),
            _word("b0", 1, "Division:", 48.0, 113.0, 140.0, 125.0, 2),
        ],
    )
    associations = reconstruct_line_label_continuations(page)
    assert len(associations) == 1
    assert associations[0].kind == SpatialRelationKind.CONTINUATION
    assert associations[0].origin == EvidenceOrigin.LAYOUT_RECONSTRUCTED
    assert set(associations[0].region_ids) == {"a0", "a1", "b0"}


def test_source_line_inside_table_cannot_initiate_ordinary_continuation():
    """A wrap-shaped pair is excluded when the source line intersects a
    table, even if the target line is outside every table."""
    page = PageGeometry(
        page_number=1,
        regions=[
            _word("a0", 1, "Office or", 50.0, 100.0, 140.0, 112.0, 0),
            _word("b0", 1, "Division:", 50.0, 113.5, 140.0, 125.5, 1),
            _table("t0", 1, (40.0, 90.0, 200.0, 112.5)),
        ],
    )
    associations = reconstruct_line_label_continuations(page)
    assert associations == []


def test_target_line_inside_table_cannot_receive_ordinary_continuation():
    """A wrap-shaped pair is excluded when the target line intersects a
    table, even if the source line is outside every table."""
    page = PageGeometry(
        page_number=1,
        regions=[
            _word("a0", 1, "Office or", 50.0, 100.0, 140.0, 112.0, 0),
            _word("b0", 1, "Division:", 50.0, 114.0, 140.0, 126.0, 1),
            _table("t0", 1, (40.0, 113.5, 200.0, 160.0)),
        ],
    )
    associations = reconstruct_line_label_continuations(page)
    assert associations == []


def test_vertical_only_table_overlap_does_not_exclude_ordinary_continuation():
    """A table sharing the lines' y-range but not their x-range is not
    table-containment. The pair remains eligible."""
    page = PageGeometry(
        page_number=1,
        regions=[
            _word("a0", 1, "Office or", 50.0, 100.0, 140.0, 112.0, 0),
            _word("b0", 1, "Division:", 50.0, 113.0, 140.0, 125.0, 1),
            _table("side", 1, (300.0, 90.0, 500.0, 140.0)),
        ],
    )
    associations = reconstruct_line_label_continuations(page)
    assert len(associations) == 1
    assert associations[0].origin == EvidenceOrigin.LAYOUT_RECONSTRUCTED
    assert set(associations[0].region_ids) == {"a0", "b0"}


def test_horizontal_only_table_overlap_does_not_exclude_ordinary_continuation():
    """A table sharing the lines' x-range but not their y-range is not
    table-containment. The pair remains eligible."""
    page = PageGeometry(
        page_number=1,
        regions=[
            _word("a0", 1, "Office or", 50.0, 100.0, 140.0, 112.0, 0),
            _word("b0", 1, "Division:", 50.0, 113.0, 140.0, 125.0, 1),
            _table("below", 1, (40.0, 200.0, 200.0, 300.0)),
        ],
    )
    associations = reconstruct_line_label_continuations(page)
    assert len(associations) == 1
    assert associations[0].origin == EvidenceOrigin.LAYOUT_RECONSTRUCTED
    assert set(associations[0].region_ids) == {"a0", "b0"}


def test_positive_area_table_intersection_excludes_ordinary_continuation():
    """Interior overlap on both axes excludes the pair even when wrap
    signals would otherwise confirm it."""
    page = PageGeometry(
        page_number=1,
        regions=[
            _word("a0", 1, "Office or", 50.0, 100.0, 140.0, 112.0, 0),
            _word("b0", 1, "Division:", 50.0, 113.0, 140.0, 125.0, 1),
            _table("t0", 1, (40.0, 90.0, 200.0, 140.0)),
        ],
    )
    associations = reconstruct_line_label_continuations(page)
    assert associations == []


def test_boundary_only_table_contact_does_not_exclude_ordinary_continuation():
    """Edge-touch is not positive-area intersection. A line whose right
    edge equals a table's left edge, or whose bottom equals a table's
    top, remains eligible for ordinary continuation."""
    x_touch = PageGeometry(
        page_number=1,
        regions=[
            _word("a0", 1, "Office or", 50.0, 100.0, 140.0, 112.0, 0),
            _word("b0", 1, "Division:", 50.0, 113.0, 140.0, 125.0, 1),
            _table("right", 1, (140.0, 90.0, 280.0, 140.0)),
        ],
    )
    y_touch = PageGeometry(
        page_number=1,
        regions=[
            _word("a0", 1, "Office or", 50.0, 100.0, 140.0, 112.0, 0),
            _word("b0", 1, "Division:", 50.0, 113.0, 140.0, 125.0, 1),
            _table("below", 1, (40.0, 125.0, 200.0, 220.0)),
        ],
    )
    for page in (x_touch, y_touch):
        associations = reconstruct_line_label_continuations(page)
        assert len(associations) == 1
        assert associations[0].kind == SpatialRelationKind.CONTINUATION
        assert associations[0].origin == EvidenceOrigin.LAYOUT_RECONSTRUCTED
        assert set(associations[0].region_ids) == {"a0", "b0"}


def test_every_table_on_the_page_is_considered_for_line_eligibility():
    """The first table on the page does not contain the lines; a later
    table does. Exclusion must still fire -- membership is not nearest-
    table or first-table only."""
    page = PageGeometry(
        page_number=1,
        regions=[
            _word("a0", 1, "Office or", 220.0, 100.0, 320.0, 112.0, 0),
            _word("b0", 1, "Division:", 220.0, 113.0, 320.0, 125.0, 1),
            _table("left", 1, (40.0, 200.0, 180.0, 300.0)),
            _table("right", 1, (200.0, 90.0, 360.0, 140.0)),
        ],
    )
    associations = reconstruct_line_label_continuations(page)
    assert associations == []


def test_horizontally_separate_table_does_not_exclude_ordinary_continuation():
    """A table in another column must not suppress a wrap that never
    intersects it."""
    page = PageGeometry(
        page_number=1,
        regions=[
            _word("a0", 1, "Office or", 50.0, 100.0, 140.0, 112.0, 0),
            _word("b0", 1, "Division:", 50.0, 113.0, 140.0, 125.0, 1),
            _table("other", 1, (300.0, 80.0, 500.0, 250.0)),
        ],
    )
    associations = reconstruct_line_label_continuations(page)
    assert len(associations) == 1
    assert associations[0].origin == EvidenceOrigin.LAYOUT_RECONSTRUCTED
    assert "other" not in associations[0].region_ids
    assert set(associations[0].region_ids) == {"a0", "b0"}


def test_table_cell_continuation_unchanged_when_word_path_is_excluded():
    """The same-column cell wrap still reconstructs. Table-contained
    WORD lines that look like the same wrap do not reappear on the
    ordinary line-continuation path."""
    page = PageGeometry(
        page_number=1,
        regions=[
            _word("w0", 1, "Office", 50.0, 100.0, 90.0, 112.0, 0),
            _word("w1", 1, "or", 95.0, 100.0, 120.0, 112.0, 1),
            _word("w2", 1, "Division:", 50.0, 113.0, 140.0, 125.0, 2),
            _table("t0", 1, (40.0, 90.0, 500.0, 200.0)),
            _cell("lbl0", 1, "Office or", 0, 1),
            _cell("val0", 1, "EXTENSION AND TRAINING SERVICES", 0, 3),
            _cell("lbl1", 1, "Division:", 1, 1),
            _cell("val1", 1, "", 1, 3),
        ],
    )
    line_assocs = reconstruct_line_label_continuations(page)
    assert line_assocs == []

    cell_assocs = reconstruct_table_label_continuations(page)
    strong = [a for a in cell_assocs if a.origin == EvidenceOrigin.LAYOUT_RECONSTRUCTED]
    assert len(strong) == 1
    assert strong[0].kind == SpatialRelationKind.CONTINUATION
    texts = {region.text for region in page.regions if region.region_id in strong[0].region_ids}
    assert texts == {"Office or", "Division:"}

    word_ids = {"w0", "w1", "w2"}
    for assoc in reconstruct_page_associations(page):
        if assoc.kind == SpatialRelationKind.CONTINUATION:
            assert not (set(assoc.region_ids) & word_ids)


def test_numbered_items_remain_independent_beside_an_unrelated_table():
    """7.4B enumerator safeguard is unchanged when a horizontally
    separate table is also present on the page."""
    page = PageGeometry(
        page_number=1,
        regions=[
            _word("a0", 1, "3. Submit the request form", 56.0, 140.0, 280.0, 152.0, 0),
            _word("b0", 1, "4. Pay the corresponding fee", 56.0, 153.0, 280.0, 165.0, 1),
            _table("side", 1, (400.0, 80.0, 540.0, 220.0)),
        ],
    )
    associations = reconstruct_line_label_continuations(page)
    assert associations == []


def test_unresolved_ordinary_continuation_remains_unresolved_beside_unrelated_table():
    """Insufficient-evidence adjacent complete lines stay MISSING. A
    horizontally separate table does not suppress or promote them."""
    page = PageGeometry(
        page_number=1,
        regions=[
            _word("a0", 1, "The first sentence is already complete.", 56.0, 100.0, 300.0, 112.0, 0),
            _word("b0", 1, "The second sentence is also complete.", 56.0, 113.0, 300.0, 125.0, 1),
            _table("side", 1, (400.0, 80.0, 540.0, 200.0)),
        ],
    )
    associations = reconstruct_line_label_continuations(page)
    assert len(associations) == 1
    assert associations[0].origin == EvidenceOrigin.MISSING
    assert associations[0].kind == SpatialRelationKind.CONTINUATION
    assert set(associations[0].region_ids) == {"a0", "b0"}


# ---------------------------------------------------------------------------
# 6. Cross-page continuity.
# ---------------------------------------------------------------------------


def test_cross_page_continuation_requires_both_signals():
    page_a = PageGeometry(
        page_number=1,
        regions=[_word("a0", 1, "continuing-", 48.0, 700.0, 100.0, 712.0, 0)],
    )
    page_b = PageGeometry(
        page_number=2,
        regions=[_word("b0", 2, "word on the next page", 48.0, 60.0, 200.0, 72.0, 0)],
    )
    associations = reconstruct_cross_page_continuation(
        page_a, page_b, furniture_region_ids=frozenset()
    )
    strong = [a for a in associations if a.origin == EvidenceOrigin.LAYOUT_RECONSTRUCTED]
    assert len(strong) == 1


def test_cross_page_continuation_not_joined_on_one_signal_alone():
    """Last line looks complete (ends with a period) even though the next
    page's first word is lowercase -- only 1 of 2 signals -- must not be
    promoted to a confirmed association."""
    page_a = PageGeometry(
        page_number=1,
        regions=[_word("a0", 1, "This sentence ends completely.", 48.0, 700.0, 200.0, 712.0, 0)],
    )
    page_b = PageGeometry(
        page_number=2,
        regions=[_word("b0", 2, "lowercase start anyway", 48.0, 60.0, 200.0, 72.0, 0)],
    )
    associations = reconstruct_cross_page_continuation(
        page_a, page_b, furniture_region_ids=frozenset()
    )
    assert all(a.origin != EvidenceOrigin.LAYOUT_RECONSTRUCTED for a in associations)


def test_no_cross_page_join_with_no_supporting_signal():
    page_a = PageGeometry(
        page_number=1,
        regions=[_word("a0", 1, "Complete sentence.", 48.0, 700.0, 200.0, 712.0, 0)],
    )
    page_b = PageGeometry(
        page_number=2,
        regions=[_word("b0", 2, "New Heading Starts", 48.0, 60.0, 200.0, 72.0, 0)],
    )
    assert reconstruct_cross_page_continuation(
        page_a, page_b, furniture_region_ids=frozenset()
    ) == []


def test_isolated_folio_is_not_a_cross_page_continuation_source():
    """A short last line detached from the body (large vertical gap and a
    different left margin) is page furniture, not a continuation source --
    even when the next page starts lowercase. Not a phrase or document
    rule: the same isolation test applies to any such line."""
    page_a = PageGeometry(
        page_number=1,
        regions=[
            _word("a0", 1, "to submit the hard", 64.0, 748.0, 180.0, 760.0, 0),
            _word("a1", 1, "2", 296.0, 780.0, 304.0, 793.0, 1),
        ],
    )
    page_b = PageGeometry(
        page_number=2,
        regions=[
            _word("b0", 2, "copy of enrolment leftover", 64.0, 90.0, 220.0, 102.0, 0),
            _word("b1", 2, "requirements authenticity", 64.0, 103.0, 220.0, 115.0, 1),
        ],
    )
    associations = reconstruct_cross_page_continuation(
        page_a, page_b, furniture_region_ids=frozenset()
    )
    assert associations == []


def test_isolated_running_header_is_not_a_cross_page_continuation_target():
    """An isolated first line on the next page is furniture, not a
    continuation target, even if it is lowercase and the previous page
    ended mid-phrase."""
    page_a = PageGeometry(
        page_number=1,
        regions=[
            _word("a0", 1, "an unfinished phrase", 48.0, 688.0, 200.0, 700.0, 0),
            _word("a1", 1, "that still continues", 48.0, 702.0, 200.0, 714.0, 1),
        ],
    )
    page_b = PageGeometry(
        page_number=2,
        regions=[
            _word("b0", 2, "draft", 250.0, 18.0, 290.0, 30.0, 0),
            _word("b1", 2, "continued body text here", 48.0, 80.0, 220.0, 92.0, 1),
        ],
    )
    associations = reconstruct_cross_page_continuation(
        page_a, page_b, furniture_region_ids=frozenset()
    )
    assert associations == []


def test_same_column_numbered_body_line_remains_eligible_for_continuation():
    """A numbered body line that stays in column with the line above it is
    not page furniture. Incomplete + lowercase still confirms."""
    page_a = PageGeometry(
        page_number=1,
        regions=[
            _word("a0", 1, "2 Earlier item remains here", 48.0, 666.0, 220.0, 678.0, 0),
            _word("a1", 1, "3 Continue the procedure", 48.0, 680.0, 220.0, 692.0, 1),
        ],
    )
    page_b = PageGeometry(
        page_number=2,
        regions=[_word("b0", 2, "on the following page", 48.0, 60.0, 220.0, 72.0, 0)],
    )
    associations = reconstruct_cross_page_continuation(
        page_a, page_b, furniture_region_ids=frozenset()
    )
    strong = [a for a in associations if a.origin == EvidenceOrigin.LAYOUT_RECONSTRUCTED]
    assert len(strong) == 1
    assert "3 Continue the procedure" in (strong[0].note or "")


def test_incomplete_line_without_hyphen_still_continues_when_next_starts_lowercase():
    """Positive control: ordinary mid-sentence wrap, no hyphen, no furniture."""
    page_a = PageGeometry(
        page_number=1,
        regions=[_word("a0", 1, "The applicant must submit a", 48.0, 700.0, 220.0, 712.0, 0)],
    )
    page_b = PageGeometry(
        page_number=2,
        regions=[_word("b0", 2, "certified true copy", 48.0, 60.0, 200.0, 72.0, 0)],
    )
    associations = reconstruct_cross_page_continuation(
        page_a, page_b, furniture_region_ids=frozenset()
    )
    strong = [a for a in associations if a.origin == EvidenceOrigin.LAYOUT_RECONSTRUCTED]
    assert len(strong) == 1


# ---------------------------------------------------------------------------
# 6b. Recurring page furniture (Phase 7.8 / 7.10).
# ---------------------------------------------------------------------------


def _header_rows(page_field: str) -> list[list[str]]:
    return [
        ["Label:", "Alpha", "Code:", "X1"],
        ["Kind:", "Manual", "Rev:", "Zero"],
        ["Name:", "Sample", "When:", page_field],
    ]


def _compact_header_regions(
    page_number: int,
    x0: float,
    page_field: str,
    table_index: int = 0,
) -> list[SpatialRegion]:
    """Compact top table plus in-table header words, then a body line.

    Geometry is page-relative for a 400x600 page: y0=15, y1=55 (rel_h=0.067,
    rel_y0=0.025). Horizontal x0 may shift (duplex). No institution names.
    """
    table_id = f"p{page_number}:table:{table_index}"
    rows = _header_rows(page_field)
    text = "\n".join(" | ".join(row) for row in rows)
    regions: list[SpatialRegion] = [
        SpatialRegion(
            region_id=table_id,
            page_number=page_number,
            region_type=SpatialRegionType.TABLE,
            text=text,
            bbox=(x0, 15.0, x0 + 300.0, 55.0),
        )
    ]
    order = 0
    y = 18.0
    for row_i, row in enumerate(rows):
        x = x0 + 4.0
        for col_i, cell in enumerate(row):
            regions.append(
                SpatialRegion(
                    region_id=f"{table_id}:cell:{row_i}:{col_i}",
                    page_number=page_number,
                    region_type=SpatialRegionType.CELL,
                    text=cell,
                    row=row_i,
                    column=col_i,
                )
            )
            for token in cell.split():
                regions.append(
                    _word(
                        f"p{page_number}:hw{order}",
                        page_number,
                        token,
                        x,
                        y,
                        x + 36.0,
                        y + 8.0,
                        order,
                    )
                )
                order += 1
                x += 40.0
        y += 12.0
    return regions


def _page_with_compact_header(
    page_number: int,
    x0: float,
    page_field: str,
    body_last: str,
    body_first: str | None = None,
) -> PageGeometry:
    regions = _compact_header_regions(page_number, x0, page_field)
    header_words = [r for r in regions if r.region_type == SpatialRegionType.WORD]
    next_order = len(header_words)
    if body_first is not None:
        regions.append(
            _word(
                f"p{page_number}:bf",
                page_number,
                body_first,
                48.0,
                80.0,
                220.0,
                92.0,
                next_order,
            )
        )
        next_order += 1
    regions.append(
        _word(
            f"p{page_number}:bp",
            page_number,
            "Earlier body remains in column",
            48.0,
            526.0,
            240.0,
            538.0,
            next_order,
        )
    )
    next_order += 1
    regions.append(
        _word(
            f"p{page_number}:bl",
            page_number,
            body_last,
            48.0,
            540.0,
            240.0,
            552.0,
            next_order,
        )
    )
    return PageGeometry(
        page_number=page_number,
        width=400.0,
        height=600.0,
        coordinate_width=400.0,
        coordinate_height=600.0,
        regions=regions,
    )


def _page_with_compact_footer(page_number: int, page_field: str, body_last: str) -> PageGeometry:
    """Body lines above a compact bottom table so the last grouped lines are furniture."""
    table_id = f"p{page_number}:table:footer"
    rows = _header_rows(page_field)
    text = "\n".join(" | ".join(row) for row in rows)
    regions: list[SpatialRegion] = [
        SpatialRegion(
            region_id=table_id,
            page_number=page_number,
            region_type=SpatialRegionType.TABLE,
            text=text,
            bbox=(40.0, 540.0, 340.0, 575.0),
        )
    ]
    order = 0
    y = 544.0
    for row_i, row in enumerate(rows):
        x = 44.0
        for col_i, cell in enumerate(row):
            regions.append(
                SpatialRegion(
                    region_id=f"{table_id}:cell:{row_i}:{col_i}",
                    page_number=page_number,
                    region_type=SpatialRegionType.CELL,
                    text=cell,
                    row=row_i,
                    column=col_i,
                )
            )
            for token in cell.split():
                regions.append(
                    _word(
                        f"p{page_number}:fw{order}",
                        page_number,
                        token,
                        x,
                        y,
                        x + 36.0,
                        y + 8.0,
                        order,
                    )
                )
                order += 1
                x += 40.0
        y += 10.0
    regions.append(
        _word(
            f"p{page_number}:bp",
            page_number,
            "Earlier body remains in column",
            48.0,
            500.0,
            240.0,
            512.0,
            order,
        )
    )
    order += 1
    regions.append(
        _word(
            f"p{page_number}:bl",
            page_number,
            body_last,
            48.0,
            514.0,
            240.0,
            526.0,
            order,
        )
    )
    return PageGeometry(
        page_number=page_number,
        width=400.0,
        height=600.0,
        coordinate_width=400.0,
        coordinate_height=600.0,
        regions=regions,
    )


def _furniture_assoc(
    group_id: str,
    subtype: str,
    region_ids: list[str],
    *,
    kind: SpatialRelationKind = SpatialRelationKind.PAGE_FURNITURE,
    origin: EvidenceOrigin = EvidenceOrigin.LAYOUT_RECONSTRUCTED,
) -> SpatialAssociation:
    return SpatialAssociation(
        association_id=f"assoc:furniture:{group_id}:{subtype}",
        region_ids=region_ids,
        kind=kind,
        origin=origin,
        confidence=1.0,
        note="explanatory only; not identity",
    )


def test_recurring_compact_header_table_is_furniture_with_machine_readable_group():
    pages = [
        _page_with_compact_header(1, 40.0, "1 of 9", "continuing-", "word on the next page"),
        _page_with_compact_header(2, 62.0, "2 of 9", "another leftover-", "more lowercase wrap"),
        _page_with_compact_header(3, 40.0, "3 of 9", "Complete sentence.", "Body heading"),
    ]
    furniture = reconstruct_page_furniture(pages)
    assert len(furniture) == 1
    group = furniture[0]
    assert is_page_furniture_association(group)
    assert furniture_group_id(group) is not None
    assert group.kind == SpatialRelationKind.PAGE_FURNITURE
    assert group.origin == EvidenceOrigin.LAYOUT_RECONSTRUCTED
    assert group.confidence == 1.0
    assert set(group.region_ids) == {"p1:table:0", "p2:table:0", "p3:table:0"}
    assert group.association_id.startswith("assoc:furniture:")
    assert ":header" in group.association_id
    # Source tables are referenced, not rewritten.
    assert pages[0].regions[0].region_type == SpatialRegionType.TABLE
    assert pages[0].regions[0].text != ""


def test_cross_page_furniture_ids_are_keyword_only_and_required():
    import inspect

    param = inspect.signature(reconstruct_cross_page_continuation).parameters[
        "furniture_region_ids"
    ]
    assert param.kind is inspect.Parameter.KEYWORD_ONLY
    assert param.default is inspect.Parameter.empty
    page_a = PageGeometry(
        page_number=1,
        regions=[_word("a0", 1, "continuing-", 48.0, 700.0, 100.0, 712.0, 0)],
    )
    page_b = PageGeometry(
        page_number=2,
        regions=[_word("b0", 2, "word on the next page", 48.0, 60.0, 200.0, 72.0, 0)],
    )
    with pytest.raises(TypeError):
        reconstruct_cross_page_continuation(page_a, page_b)


def test_furniture_on_both_pages_is_excluded_from_endpoints():
    pages = [
        _page_with_compact_header(1, 40.0, "1 of 9", "continuing-", None),
        _page_with_compact_header(2, 62.0, "2 of 9", "Complete sentence.", "word on the next page"),
        _page_with_compact_header(3, 40.0, "3 of 9", "Another complete sentence.", "Later body"),
    ]
    furniture_ids = set(reconstruct_page_furniture(pages)[0].region_ids)
    recovered = reconstruct_cross_page_continuation(
        pages[0], pages[1], furniture_region_ids=furniture_ids
    )
    assert len(recovered) == 1
    assert recovered[0].origin == EvidenceOrigin.LAYOUT_RECONSTRUCTED
    assert recovered[0].kind == SpatialRelationKind.CONTINUATION
    assert "continuing-" in (recovered[0].note or "")
    assert "word on the next page" in (recovered[0].note or "")
    assert "Label:" not in (recovered[0].note or "")


def test_furniture_only_on_destination_page_is_excluded():
    page_a = PageGeometry(
        page_number=1,
        width=400.0,
        height=600.0,
        regions=[
            _word("a0", 1, "Earlier body remains in column", 48.0, 526.0, 240.0, 538.0, 0),
            _word("a1", 1, "continuing-", 48.0, 540.0, 240.0, 552.0, 1),
        ],
    )
    page_b = _page_with_compact_header(
        2, 62.0, "2 of 9", "Complete sentence.", "word on the next page"
    )
    furniture_ids = {region.region_id for region in page_b.regions if region.region_type == SpatialRegionType.TABLE}
    associations = reconstruct_cross_page_continuation(
        page_a, page_b, furniture_region_ids=furniture_ids
    )
    assert len(associations) == 1
    assert associations[0].origin == EvidenceOrigin.LAYOUT_RECONSTRUCTED
    note = associations[0].note or ""
    assert "continuing-" in note
    assert "word on the next page" in note
    assert "Label:" not in note


def test_furniture_only_on_source_page_is_excluded_from_endpoint():
    page_a = _page_with_compact_footer(1, "1 of 9", "continuing-")
    page_b = PageGeometry(
        page_number=2,
        width=400.0,
        height=600.0,
        regions=[_word("b0", 2, "word on the next page", 48.0, 60.0, 200.0, 72.0, 0)],
    )
    furniture_ids = {region.region_id for region in page_a.regions if region.region_type == SpatialRegionType.TABLE}
    associations = reconstruct_cross_page_continuation(
        page_a, page_b, furniture_region_ids=furniture_ids
    )
    assert len(associations) == 1
    assert associations[0].origin == EvidenceOrigin.LAYOUT_RECONSTRUCTED
    note = associations[0].note or ""
    assert "continuing-" in note
    assert "word on the next page" in note
    assert "Label:" not in note


def test_no_furniture_preserves_ordinary_cross_page_continuation():
    page_a = PageGeometry(
        page_number=1,
        regions=[_word("a0", 1, "continuing-", 48.0, 700.0, 100.0, 712.0, 0)],
    )
    page_b = PageGeometry(
        page_number=2,
        regions=[_word("b0", 2, "word on the next page", 48.0, 60.0, 200.0, 72.0, 0)],
    )
    associations = reconstruct_cross_page_continuation(
        page_a, page_b, furniture_region_ids=frozenset()
    )
    strong = [a for a in associations if a.origin == EvidenceOrigin.LAYOUT_RECONSTRUCTED]
    assert len(strong) == 1
    assert "continuing-" in (strong[0].note or "")
    assert "word on the next page" in (strong[0].note or "")


def test_explicit_empty_furniture_set_is_not_the_document_level_path():
    """frozenset() is explicit unfiltered endpoint selection.

    It is distinguishable from omitting the argument (TypeError) and from
    ``reconstruct_document_associations`` (which supplies member IDs).
    Chrome on B remains the first grouped line under this unfiltered call.
    """
    pages = [
        _page_with_compact_header(1, 40.0, "1 of 9", "continuing-", None),
        _page_with_compact_header(2, 62.0, "2 of 9", "Complete sentence.", "word on the next page"),
        _page_with_compact_header(3, 40.0, "3 of 9", "Another complete sentence.", "Later body"),
    ]
    unfiltered = reconstruct_cross_page_continuation(
        pages[0], pages[1], furniture_region_ids=frozenset()
    )
    protected = reconstruct_document_associations(pages)
    wraps = [
        a
        for a in protected
        if a.kind == SpatialRelationKind.CONTINUATION
        and a.origin == EvidenceOrigin.LAYOUT_RECONSTRUCTED
        and a.association_id.startswith("assoc:xpage:")
    ]
    assert len(unfiltered) == 1
    assert "Label:" in (unfiltered[0].note or "") or "Alpha" in (unfiltered[0].note or "")
    assert len(wraps) == 1
    assert "word on the next page" in (wraps[0].note or "")
    assert "Label:" not in (wraps[0].note or "")


def test_furniture_membership_one_group_spanning_several_pages():
    pages = [
        PageGeometry(
            page_number=n,
            regions=[
                SpatialRegion(
                    region_id=f"hdr-{n}",
                    page_number=n,
                    region_type=SpatialRegionType.TABLE,
                    text="",
                    bbox=(10.0, 10.0, 200.0, 40.0),
                )
            ],
        )
        for n in (1, 2, 3)
    ]
    group = _furniture_assoc("abc123", "header", ["hdr-1", "hdr-2", "hdr-3"])
    assert furniture_region_ids_on_page(pages[1], [group]) == ("hdr-2",)
    assert furniture_region_ids_on_page(pages[0], [group]) == ("hdr-1",)


def test_furniture_membership_two_groups_on_one_page():
    page = PageGeometry(
        page_number=4,
        regions=[
            SpatialRegion(
                region_id="page4-header",
                page_number=4,
                region_type=SpatialRegionType.TABLE,
                text="",
                bbox=(10.0, 10.0, 200.0, 40.0),
            ),
            SpatialRegion(
                region_id="page4-footer",
                page_number=4,
                region_type=SpatialRegionType.TABLE,
                text="",
                bbox=(10.0, 540.0, 200.0, 570.0),
            ),
            _word("page4-body", 4, "body", 48.0, 80.0, 120.0, 92.0, 0),
        ],
    )
    header = _furniture_assoc("aaa", "header", ["p1-h", "page4-header", "p7-h"])
    footer = _furniture_assoc("bbb", "footer", ["p1-f", "page4-footer", "p7-f"])
    assert furniture_region_ids_on_page(page, [header, footer]) == (
        "page4-footer",
        "page4-header",
    )


def test_furniture_membership_page_with_no_furniture():
    page = PageGeometry(
        page_number=2,
        regions=[
            SpatialRegion(
                region_id="body-table",
                page_number=2,
                region_type=SpatialRegionType.TABLE,
                text="",
                bbox=(40.0, 80.0, 360.0, 400.0),
            )
        ],
    )
    other_page_group = _furniture_assoc("aaa", "header", ["hdr-1", "hdr-3"])
    assert furniture_region_ids_on_page(page, [other_page_group]) == ()
    assert furniture_region_ids_on_page(page, []) == ()


def test_furniture_membership_empty_page():
    page = PageGeometry(page_number=1, regions=[])
    group = _furniture_assoc("aaa", "header", ["hdr-1", "hdr-2"])
    assert furniture_region_ids_on_page(page, [group]) == ()


def test_furniture_membership_omits_ids_not_on_supplied_page():
    page = PageGeometry(
        page_number=2,
        regions=[
            SpatialRegion(
                region_id="hdr-2",
                page_number=2,
                region_type=SpatialRegionType.TABLE,
                text="",
                bbox=(10.0, 10.0, 200.0, 40.0),
            )
        ],
    )
    group = _furniture_assoc("aaa", "header", ["hdr-1", "hdr-2", "ghost-id"])
    assert furniture_region_ids_on_page(page, [group]) == ("hdr-2",)


def test_furniture_membership_ignores_unrelated_association_kind():
    page = PageGeometry(
        page_number=1,
        regions=[_word("w0", 1, "body", 48.0, 80.0, 120.0, 92.0, 0)],
    )
    unrelated = SpatialAssociation(
        association_id="assoc:xpage:w0:w1",
        region_ids=["w0"],
        kind=SpatialRelationKind.CONTINUATION,
        origin=EvidenceOrigin.LAYOUT_RECONSTRUCTED,
        confidence=1.0,
    )
    other_kind_furniture_prefix = _furniture_assoc(
        "aaa", "header", ["w0"], kind=SpatialRelationKind.OTHER
    )
    assert furniture_region_ids_on_page(page, [unrelated]) == ()
    assert furniture_region_ids_on_page(page, [other_kind_furniture_prefix]) == ()
    assert is_page_furniture_association(other_kind_furniture_prefix) is False


def test_furniture_group_id_is_deterministic_and_not_a_persistent_key():
    pages = [
        _page_with_compact_header(1, 40.0, "1 of 9", "continuing-", "word on the next page"),
        _page_with_compact_header(2, 62.0, "2 of 9", "another leftover-", "more lowercase wrap"),
        _page_with_compact_header(3, 40.0, "3 of 9", "Complete sentence.", "Body heading"),
    ]
    first = reconstruct_page_furniture(pages)
    second = reconstruct_page_furniture(pages)
    assert len(first) == 1
    assert furniture_group_id(first[0]) == furniture_group_id(second[0])
    assert first[0].association_id == second[0].association_id
    # Same prototype on a disjoint page list still yields the same digest:
    # the identifier is not document-scoped.
    shifted = [
        _page_with_compact_header(10, 40.0, "1 of 9", "continuing-", "word on the next page"),
        _page_with_compact_header(11, 62.0, "2 of 9", "another leftover-", "more lowercase wrap"),
        _page_with_compact_header(12, 40.0, "3 of 9", "Complete sentence.", "Body heading"),
    ]
    other_doc = reconstruct_page_furniture(shifted)
    assert furniture_group_id(other_doc[0]) == furniture_group_id(first[0])
    from app.services.common_representation.reconstruction import (
        _FurnitureCandidate,
        _furniture_group_id,
    )

    def _cand(tokens: frozenset[str], page_number: int, region_id: str) -> _FurnitureCandidate:
        return _FurnitureCandidate(
            page_number=page_number,
            table=SpatialRegion(
                region_id=region_id,
                page_number=page_number,
                region_type=SpatialRegionType.TABLE,
                text="",
                bbox=(10.0, 10.0, 200.0, 40.0),
            ),
            rel_y0=0.02,
            rel_y1=0.08,
            rel_h=0.06,
            rel_w=0.75,
            n_rows=3,
            n_cols=8,
            tokens=tokens,
        )

    cluster_a = [_cand(frozenset({"label", "kind", "name"}), 1, "t1")]
    cluster_b = [_cand(frozenset({"label", "kind", "name", "extra"}), 1, "t1")]
    assert _furniture_group_id(cluster_a, "header") != _furniture_group_id(cluster_b, "header")


def test_union_find_clusters_transitive_even_when_endpoints_do_not_match():
    """A~B and B~C with A≁C still become one cluster.

    Jaccard: A={1..7} vs B={2..8} = 0.75; B vs C={3..9} = 0.75;
    A vs C = 5/9 ≈ 0.556 < 0.70. Union-find therefore can place
    pairwise-dissimilar endpoints in the same furniture group.
    This characterizes current clustering; it does not change it.
    """
    from app.services.common_representation.reconstruction import (
        _FurnitureCandidate,
        _cluster_furniture,
        _token_jaccard,
    )

    def _cand(page_number: int, tokens: frozenset[str], region_id: str) -> _FurnitureCandidate:
        return _FurnitureCandidate(
            page_number=page_number,
            table=SpatialRegion(
                region_id=region_id,
                page_number=page_number,
                region_type=SpatialRegionType.TABLE,
                text="",
                bbox=(10.0, 10.0, 200.0, 40.0),
            ),
            rel_y0=0.02,
            rel_y1=0.08,
            rel_h=0.06,
            rel_w=0.75,
            n_rows=3,
            n_cols=8,
            tokens=tokens,
        )

    candidate_a = _cand(1, frozenset(str(i) for i in range(1, 8)), "table-a")
    candidate_b = _cand(2, frozenset(str(i) for i in range(2, 9)), "table-b")
    candidate_c = _cand(3, frozenset(str(i) for i in range(3, 10)), "table-c")
    assert _token_jaccard(candidate_a.tokens, candidate_b.tokens) >= 0.70
    assert _token_jaccard(candidate_b.tokens, candidate_c.tokens) >= 0.70
    assert _token_jaccard(candidate_a.tokens, candidate_c.tokens) < 0.70
    clusters = _cluster_furniture([candidate_a, candidate_b, candidate_c])
    assert len(clusters) == 1
    assert {member.table.region_id for member in clusters[0]} == {
        "table-a",
        "table-b",
        "table-c",
    }


def test_furniture_recognition_thresholds_unchanged_from_phase_7_8():
    from app.services.common_representation import reconstruction as rec

    assert rec._FURNITURE_MAX_REL_HEIGHT == 0.15
    assert rec._FURNITURE_EDGE_BAND == 0.12
    assert rec._FURNITURE_MIN_PAGES == 3
    assert rec._FURNITURE_MIN_PAGE_COVERAGE == 0.5
    assert rec._FURNITURE_REL_TOLERANCE == 0.03
    assert rec._FURNITURE_WIDTH_TOLERANCE == 0.08
    assert rec._FURNITURE_TOKEN_JACCARD == 0.7


def test_document_associations_skip_entire_furniture_region_not_one_line():
    pages = [
        _page_with_compact_header(1, 40.0, "1 of 9", "continuing-", None),
        _page_with_compact_header(2, 40.0, "2 of 9", "Complete sentence.", "word on the next page"),
        _page_with_compact_header(3, 40.0, "3 of 9", "Done.", "Later body"),
    ]
    associations = reconstruct_document_associations(pages)
    furniture = [a for a in associations if is_page_furniture_association(a)]
    assert len(furniture) == 1
    wraps = [
        a
        for a in associations
        if a.kind == SpatialRelationKind.CONTINUATION
        and a.origin == EvidenceOrigin.LAYOUT_RECONSTRUCTED
        and a.association_id.startswith("assoc:xpage:")
    ]
    assert len(wraps) == 1
    assert "word on the next page" in (wraps[0].note or "")
    assert "Kind:" not in (wraps[0].note or "")
    assert "Name:" not in (wraps[0].note or "")


def test_tall_repeated_body_table_is_not_furniture():
    """Repeated body templates (Charter-like) are tall and must not classify."""
    pages = []
    for n in (1, 2, 3):
        tid = f"p{n}:table:0"
        rows = [["Office or", "Division:"], ["Client steps", "Agency actions"]]
        regions = [
            SpatialRegion(
                region_id=tid,
                page_number=n,
                region_type=SpatialRegionType.TABLE,
                text="\n".join(" | ".join(r) for r in rows),
                bbox=(40.0, 70.0, 360.0, 520.0),
            ),
            _word(f"p{n}:w0", n, "Office or", 48.0, 80.0, 120.0, 92.0, 0),
            _word(f"p{n}:w1", n, "Division:", 48.0, 95.0, 140.0, 107.0, 1),
        ]
        for ri, row in enumerate(rows):
            for ci, cell in enumerate(row):
                regions.append(
                    SpatialRegion(
                        region_id=f"{tid}:cell:{ri}:{ci}",
                        page_number=n,
                        region_type=SpatialRegionType.CELL,
                        text=cell,
                        row=ri,
                        column=ci,
                    )
                )
        pages.append(
            PageGeometry(
                page_number=n,
                width=400.0,
                height=600.0,
                coordinate_width=400.0,
                coordinate_height=600.0,
                regions=regions,
            )
        )
    assert reconstruct_page_furniture(pages) == []


def test_compact_top_table_on_one_page_is_not_furniture():
    pages = [
        _page_with_compact_header(1, 40.0, "1 of 9", "Complete sentence.", "Body"),
        PageGeometry(
            page_number=2,
            width=400.0,
            height=600.0,
            regions=[_word("b0", 2, "Only body text here.", 48.0, 80.0, 220.0, 92.0, 0)],
        ),
        PageGeometry(
            page_number=3,
            width=400.0,
            height=600.0,
            regions=[_word("c0", 3, "More body text here.", 48.0, 80.0, 220.0, 92.0, 0)],
        ),
    ]
    assert reconstruct_page_furniture(pages) == []


def test_ambiguous_low_coverage_recurrence_stays_unclassified():
    """Three compact similar tables inside a longer document stay below
    the half-page coverage threshold and must not become furniture."""
    pages = [
        _page_with_compact_header(1, 40.0, "1 of 9", "Complete.", "Body"),
        _page_with_compact_header(2, 40.0, "2 of 9", "Complete.", "Body"),
        _page_with_compact_header(3, 40.0, "3 of 9", "Complete.", "Body"),
    ]
    for n in range(4, 8):
        pages.append(
            PageGeometry(
                page_number=n,
                width=400.0,
                height=600.0,
                regions=[_word(f"p{n}:w", n, "Ordinary body line.", 48.0, 80.0, 220.0, 92.0, 0)],
            )
        )
    assert reconstruct_page_furniture(pages) == []


def test_missing_furniture_on_one_page_does_not_break_remaining_group():
    pages = [
        _page_with_compact_header(1, 40.0, "1 of 9", "continuing-", None),
        PageGeometry(
            page_number=2,
            width=400.0,
            height=600.0,
            coordinate_width=400.0,
            coordinate_height=600.0,
            regions=[
                _word("b0", 2, "word on the next page", 48.0, 80.0, 220.0, 92.0, 0),
                _word("b1", 2, "Complete sentence.", 48.0, 540.0, 220.0, 552.0, 1),
            ],
        ),
        _page_with_compact_header(3, 40.0, "3 of 9", "Done.", "later"),
        _page_with_compact_header(4, 62.0, "4 of 9", "Done.", "later"),
        _page_with_compact_header(5, 40.0, "5 of 9", "Done.", "later"),
        _page_with_compact_header(6, 40.0, "6 of 9", "Done.", "later"),
    ]
    furniture = reconstruct_page_furniture(pages)
    assert len(furniture) == 1
    assert "p2:table:0" not in furniture[0].region_ids
    assert {rid for rid in furniture[0].region_ids} >= {"p1:table:0", "p3:table:0", "p4:table:0"}


def test_pages_without_furniture_keep_ordinary_cross_page_continuation():
    pages = [
        PageGeometry(
            page_number=1,
            width=400.0,
            height=600.0,
            regions=[_word("a0", 1, "The applicant must submit a", 48.0, 540.0, 220.0, 552.0, 0)],
        ),
        PageGeometry(
            page_number=2,
            width=400.0,
            height=600.0,
            regions=[_word("b0", 2, "certified true copy", 48.0, 80.0, 200.0, 92.0, 0)],
        ),
        PageGeometry(
            page_number=3,
            width=400.0,
            height=600.0,
            regions=[_word("c0", 3, "Later heading", 48.0, 80.0, 200.0, 92.0, 0)],
        ),
    ]
    assert reconstruct_page_furniture(pages) == []
    wraps = [
        a
        for a in reconstruct_document_associations(pages)
        if a.kind == SpatialRelationKind.CONTINUATION
        and a.origin == EvidenceOrigin.LAYOUT_RECONSTRUCTED
    ]
    assert len(wraps) == 1
    assert "certified true copy" in (wraps[0].note or "")


def test_different_page_dimensions_use_relative_geometry():
    """The same relative top band on a taller page still clusters."""
    pages = []
    for n, height, x0 in ((1, 600.0, 40.0), (2, 600.0, 60.0), (3, 840.0, 40.0)):
        scale = height / 600.0
        table_id = f"p{n}:table:0"
        rows = _header_rows(f"{n} of 9")
        y1 = 15.0 * scale + 40.0 * scale
        regions = [
            SpatialRegion(
                region_id=table_id,
                page_number=n,
                region_type=SpatialRegionType.TABLE,
                text="\n".join(" | ".join(row) for row in rows),
                bbox=(x0, 15.0 * scale, x0 + 300.0, y1),
            )
        ]
        for ri, row in enumerate(rows):
            for ci, cell in enumerate(row):
                regions.append(
                    SpatialRegion(
                        region_id=f"{table_id}:cell:{ri}:{ci}",
                        page_number=n,
                        region_type=SpatialRegionType.CELL,
                        text=cell,
                        row=ri,
                        column=ci,
                    )
                )
        pages.append(
            PageGeometry(
                page_number=n,
                width=400.0,
                height=height,
                coordinate_width=400.0,
                coordinate_height=height,
                regions=regions,
            )
        )
    furniture = reconstruct_page_furniture(pages)
    assert len(furniture) == 1
    assert set(furniture[0].region_ids) == {"p1:table:0", "p2:table:0", "p3:table:0"}


def test_unresolved_body_to_body_continuation_is_not_promoted_by_furniture():
    """Incomplete last line + uppercase next content stays MISSING."""
    pages = [
        _page_with_compact_header(1, 40.0, "1 of 9", "Policies and procedures for", None),
        _page_with_compact_header(2, 40.0, "2 of 9", "Complete sentence.", "Students must attend"),
        _page_with_compact_header(3, 40.0, "3 of 9", "Done.", "Later"),
    ]
    furniture_ids = set(reconstruct_page_furniture(pages)[0].region_ids)
    associations = reconstruct_cross_page_continuation(
        pages[0], pages[1], furniture_region_ids=furniture_ids
    )
    assert len(associations) == 1
    assert associations[0].origin == EvidenceOrigin.MISSING
    assert "Students must attend" in (associations[0].note or "")


# ---------------------------------------------------------------------------
# 9. Missing/incomplete geometry.
# ---------------------------------------------------------------------------


def test_cell_without_bbox_handled_safely():
    """Table cells never carry a bbox today (documented gap) -- reconstruction
    must still work from row/column/text alone, not crash or require bbox.
    No sibling column exists in this single-column table, so only the
    completion-ending signal is available -- one signal -> MISSING, still
    produced (not silently dropped), confirming bbox is genuinely not
    required for this capability to function at all."""
    page = PageGeometry(
        page_number=1,
        regions=[
            _cell("a", 1, "Office or", 0, 0),
            _cell("b", 1, "Division:", 1, 0),
        ],
    )
    assert page.regions[0].bbox is None
    associations = reconstruct_table_label_continuations(page)
    assert len(associations) == 1
    assert associations[0].origin == EvidenceOrigin.MISSING


def test_empty_page_geometry_produces_no_associations():
    page = PageGeometry(page_number=1, regions=[])
    assert reconstruct_page_associations(page) == []
    assert reconstruct_document_associations([page]) == []


def test_document_with_no_pages_is_backward_compatible():
    assert reconstruct_document_associations([]) == []


# ---------------------------------------------------------------------------
# 10. Multiple regions contributing to one logical unit.
# ---------------------------------------------------------------------------


def test_multi_word_line_association_references_every_word():
    page = PageGeometry(
        page_number=1,
        regions=[
            _word("w0", 1, "Office", 48.3, 487.9, 80.0, 500.2, 0),
            _word("w1", 1, "or", 85.0, 487.9, 95.0, 500.2, 1),
            _word("w2", 1, "EXTENSION", 100.0, 487.9, 160.0, 500.2, 2),
            _word("w3", 1, "Division:", 48.3, 500.5, 120.0, 512.8, 3),
        ],
    )
    associations = reconstruct_line_label_continuations(page)
    strong = [a for a in associations if a.origin == EvidenceOrigin.LAYOUT_RECONSTRUCTED]
    assert len(strong) == 1
    assert set(strong[0].region_ids) == {"w0", "w1", "w2", "w3"}


# ---------------------------------------------------------------------------
# 11. Preservation of original source evidence.
# ---------------------------------------------------------------------------


def test_original_regions_untouched_by_reconstruction():
    page = PageGeometry(
        page_number=1,
        regions=[
            _word("w0", 1, "Office", 48.3, 487.9, 80.0, 500.2, 0),
            _word("w1", 1, "Division:", 48.3, 500.5, 120.0, 512.8, 1),
        ],
    )
    before = list(page.regions)
    reconstruct_page_associations(page)
    assert page.regions == before  # frozen dataclasses, unchanged by reference and by value
    assert page.regions[0].text == "Office"
    assert page.regions[1].text == "Division:"


# ---------------------------------------------------------------------------
# 12. Provenance and ambiguity propagation -- covered by the MISSING-origin
#     tests above (test_ambiguous_cell_pair_..., test_cross_page_... one-
#     signal test); one more explicit check:
# ---------------------------------------------------------------------------


def test_confidence_is_a_documented_ratio_not_fabricated():
    page = PageGeometry(
        page_number=1,
        regions=[
            _word("w0", 1, "Office", 48.3, 487.9, 80.0, 500.2, 0),
            _word("w1", 1, "Division:", 48.3, 500.5, 120.0, 512.8, 1),
        ],
    )
    [assoc] = [a for a in reconstruct_line_label_continuations(page) if a.origin == EvidenceOrigin.LAYOUT_RECONSTRUCTED]
    # 3 of 3 signals: aligned x0, incomplete first line, completion-looking second.
    assert assoc.confidence == 1.0


# ---------------------------------------------------------------------------
# 13. Reference integrity.
# ---------------------------------------------------------------------------


def test_every_association_region_id_resolves_to_a_real_region():
    page = PageGeometry(
        page_number=1,
        regions=[
            _word("w0", 1, "Office", 48.3, 487.9, 80.0, 500.2, 0),
            _word("w1", 1, "Division:", 48.3, 500.5, 120.0, 512.8, 1),
            _table("t0", 1, (40.0, 520.0, 500.0, 600.0)),
        ],
    )
    known_ids = {r.region_id for r in page.regions}
    for assoc in reconstruct_page_associations(page):
        for rid in assoc.region_ids:
            assert rid in known_ids


def test_associations_for_page_range_only_includes_fully_contained_regions():
    pages = [
        PageGeometry(page_number=1, regions=[_word("p1w", 1, "a", 0, 0, 10, 10, 0)]),
        PageGeometry(page_number=2, regions=[_word("p2w", 2, "b", 0, 0, 10, 10, 0)]),
    ]
    all_regions_by_page = {"p1w": 1, "p2w": 2}
    from app.services.common_representation.types import SpatialAssociation, SpatialRelationKind

    cross_page = SpatialAssociation(
        association_id="x",
        region_ids=["p1w", "p2w"],
        kind=SpatialRelationKind.CONTINUATION,
        origin=EvidenceOrigin.LAYOUT_RECONSTRUCTED,
    )
    same_page = SpatialAssociation(
        association_id="y",
        region_ids=["p1w"],
        kind=SpatialRelationKind.CONTINUATION,
        origin=EvidenceOrigin.LAYOUT_RECONSTRUCTED,
    )
    result = associations_for_page_range([cross_page, same_page], all_regions_by_page, page_start=1, page_end=1)
    assert same_page in result
    assert cross_page not in result  # spans beyond the unit's own page range


def test_associations_for_page_range_empty_when_unit_has_no_page_start():
    from app.services.common_representation.types import SpatialAssociation, SpatialRelationKind

    assoc = SpatialAssociation(
        association_id="z", region_ids=["x"], kind=SpatialRelationKind.CONTINUATION, origin=EvidenceOrigin.LAYOUT_RECONSTRUCTED
    )
    assert associations_for_page_range([assoc], {"x": 1}, page_start=None, page_end=None) == []


# ---------------------------------------------------------------------------
# 14. Local/cloud contract compatibility -- a bare duck-typed object (no
#     import of either real page-extraction class) must build/reconstruct
#     identically, mirroring Phase 6.21's own compatibility test pattern.
# ---------------------------------------------------------------------------


def test_reconstruction_works_identically_from_duck_typed_page_object():
    from app.services.common_representation.adapters import build_page_geometry

    class _FakeLightweightPage:
        page_number = 7
        words = [
            {"text": "Office", "x0": 48.3, "y0": 487.9, "x1": 80.0, "y1": 500.2},
            {"text": "Division:", "x0": 48.3, "y0": 500.5, "x1": 120.0, "y1": 512.8},
        ]
        table_regions = []

    geometry = build_page_geometry(_FakeLightweightPage())
    associations = reconstruct_page_associations(geometry)
    strong = [a for a in associations if a.origin == EvidenceOrigin.LAYOUT_RECONSTRUCTED]
    assert len(strong) == 1


# ---------------------------------------------------------------------------
# 15. Backward compatibility -- see test_document_with_no_pages_is_backward_compatible
#     and test_empty_page_geometry_produces_no_associations above.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 16. No geometry duplication in Chroma chunk metadata -- reconstruction.py
#     is never imported by chunker.py/_build_metadata, confirmed structurally.
# ---------------------------------------------------------------------------


def test_reconstruction_module_not_imported_by_chunk_metadata_builder():
    import app.services.common_representation.chunker as chunker_module

    assert "reconstruction" not in (chunker_module.__dict__.get("__loader__").name if False else "")
    # Direct, stronger check: the chunker module's own source must not
    # reference this module at all.
    import inspect

    source = inspect.getsource(chunker_module)
    assert "reconstruction" not in source
    assert "SpatialAssociation" not in source
    assert "PageGeometry" not in source


# ---------------------------------------------------------------------------
# Generic-across-document-types proof: an analogous split-label pattern in
# two structurally different, unrelated synthetic "documents" produces the
# same kind of reconstruction, with no document-specific branching anywhere
# in the reconstruction code (verified by inspection -- this test proves
# behavioral parity, not just absence of a Charter string).
# ---------------------------------------------------------------------------


def test_same_reconstruction_behavior_across_unrelated_document_shapes():
    charter_like = PageGeometry(
        page_number=1,
        regions=[
            _word("c0", 1, "Office", 48.3, 487.9, 80.0, 500.2, 0),
            _word("c1", 1, "Division:", 48.3, 500.5, 120.0, 512.8, 1),
        ],
    )
    memo_like = PageGeometry(
        page_number=1,
        regions=[
            _word("m0", 1, "Reference", 70.0, 200.0, 110.0, 212.0, 0),
            _word("m1", 1, "Number:", 70.0, 212.5, 130.0, 224.5, 1),
        ],
    )
    charter_assocs = [a for a in reconstruct_line_label_continuations(charter_like) if a.origin == EvidenceOrigin.LAYOUT_RECONSTRUCTED]
    memo_assocs = [a for a in reconstruct_line_label_continuations(memo_like) if a.origin == EvidenceOrigin.LAYOUT_RECONSTRUCTED]
    assert len(charter_assocs) == 1
    assert len(memo_assocs) == 1
    assert charter_assocs[0].kind == memo_assocs[0].kind == memo_assocs[0].kind


# ---------------------------------------------------------------------------
# Real production pipeline validation (Citizen's Charter as a VALIDATION
# FIXTURE, not the design spec) -- skipped gracefully if the fixture PDF is
# unavailable in a given environment, per existing project test conventions.
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not REAL_PDF_PATH.exists(), reason="Real Citizen's Charter PDF fixture not present in this environment")
def test_real_page_37_split_label_reconstructed_from_actual_extraction():
    from app.services.common_representation.adapters import build_page_geometry
    from app.utils.pdf.pymupdf_extractor import extract_pdf

    pdf_bytes = REAL_PDF_PATH.read_bytes()
    result = extract_pdf(pdf_bytes)
    page37 = next(p for p in result.pages if p.page_number == 37)
    geometry = build_page_geometry(page37)

    word_assocs = reconstruct_line_label_continuations(geometry)
    found_office_division_on_word_path = any(
        any("Office" in geometry.regions[_idx(geometry, rid)].text for rid in a.region_ids)
        and any("Division:" in geometry.regions[_idx(geometry, rid)].text for rid in a.region_ids)
        for a in word_assocs
    )
    assert not found_office_division_on_word_path, (
        "Table-contained 'Office'/'Division:' words must not be ordinary line continuations"
    )

    cell_assocs = [a for a in reconstruct_table_label_continuations(geometry) if a.origin == EvidenceOrigin.LAYOUT_RECONSTRUCTED]
    found_office_division_on_cell_path = any(
        any("Office or" in geometry.regions[_idx(geometry, rid)].text for rid in a.region_ids)
        and any("Division:" in geometry.regions[_idx(geometry, rid)].text for rid in a.region_ids)
        for a in cell_assocs
    )
    assert found_office_division_on_cell_path, (
        "Expected the real page-37 'Office or'/'Division:' cell continuation to remain"
    )


def _idx(geometry: PageGeometry, region_id: str) -> int:
    for i, region in enumerate(geometry.regions):
        if region.region_id == region_id:
            return i
    raise AssertionError(f"region_id {region_id!r} not found")


@pytest.mark.skipif(not REAL_PDF_PATH.exists(), reason="Real Citizen's Charter PDF fixture not present in this environment")
def test_citizen_charter_baseline_unchanged_by_reconstruction_module_existing():
    """Confirms this phase changed NOTHING about Citizen's Charter's own
    extraction output -- reconstruction.py is never imported by
    citizen_charter_extractor_v2.py, so this is expected to hold trivially,
    but verified directly rather than assumed."""
    from app.services.citizen_charter_extractor_v2 import extract_citizen_charter_services_v2
    from app.utils.pdf.pymupdf_extractor import extract_pdf

    pdf_bytes = REAL_PDF_PATH.read_bytes()
    result = extract_pdf(pdf_bytes)
    services = extract_citizen_charter_services_v2(result.pages)
    assert len(services) == 96
    total_reqs = sum(len(s.requirements or []) for s in services)
    total_steps = sum(len(s.steps or []) for s in services)
    assert total_reqs == 177
    assert total_steps == 284
    titles = [s.service_title for s in services]
    assert titles.count("IP Registration Process") == 2
    assert "Open to all Clients" not in titles
    assert not any("NATIONAL SERVICE TRAINING PROGRAM" in (t or "") for t in titles)
