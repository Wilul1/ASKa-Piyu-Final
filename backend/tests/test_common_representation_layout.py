"""Global layout builder: geometry → structured document → chunks.

Does not ingest, write Chroma, or modify Phase 7.12 fixtures.
Continuation scoring is asserted unchanged (Case G still joins).
"""
from __future__ import annotations

import json
from pathlib import Path

from app.services.common_representation.chunker import chunk_document_record
from app.services.common_representation.layout import build_layout_document, inspect_layout
from app.services.common_representation.reconstruction import (
    reconstruct_cross_page_continuation,
    reconstruct_document_associations,
    reconstruct_page_furniture,
    reconstruct_text_page_furniture,
)
from app.services.common_representation.types import (
    EvidenceOrigin,
    ListContent,
    PageGeometry,
    ParagraphContent,
    SpatialRegion,
    SpatialRegionType,
    SpatialRelationKind,
    TableContent,
)

_FIXTURE_JSON = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "phase_7_12_text_only_furniture"
    / "provenance"
    / "digital_extraction.json"
)
_REGION_TYPES = {
    "word": SpatialRegionType.WORD,
    "table": SpatialRegionType.TABLE,
    "cell": SpatialRegionType.CELL,
    "block": SpatialRegionType.BLOCK,
}


def _fixture_geometries() -> list[PageGeometry]:
    payload = json.loads(_FIXTURE_JSON.read_text(encoding="utf-8"))
    pages: list[PageGeometry] = []
    for page in payload["pages"]:
        regions: list[SpatialRegion] = []
        for item in page["adapter_regions"]:
            bbox = item.get("bbox")
            regions.append(
                SpatialRegion(
                    region_id=item["region_id"],
                    page_number=page["page_number"],
                    region_type=_REGION_TYPES[item["type"]],
                    text=item["text"],
                    bbox=tuple(bbox) if bbox else None,
                    row=item.get("row"),
                    column=item.get("column"),
                    reading_order_index=item.get("reading_order_index"),
                )
            )
        pages.append(
            PageGeometry(
                page_number=page["page_number"],
                width=page["page_width"],
                height=page["page_height"],
                rotation=0,
                regions=regions,
                geometry_scale=page.get("geometry_scale"),
                coordinate_width=page["coordinate_width"],
                coordinate_height=page["coordinate_height"],
            )
        )
    return pages


def _word(page: int, index: int, text: str, x0: float, y0: float, x1: float, y1: float) -> SpatialRegion:
    return SpatialRegion(
        region_id=f"p{page}:word:{index}",
        page_number=page,
        region_type=SpatialRegionType.WORD,
        text=text,
        bbox=(x0, y0, x1, y1),
        reading_order_index=index,
    )


def _page(number: int, regions: list[SpatialRegion]) -> PageGeometry:
    return PageGeometry(
        page_number=number,
        width=468.0,
        height=612.0,
        regions=regions,
        geometry_scale=1.0,
        coordinate_width=468.0,
        coordinate_height=612.0,
    )


def test_fixture_omits_running_chrome_and_keeps_section_overview():
    pages = _fixture_geometries()
    build = build_layout_document(pages, document_id="fix12", source_filename="fixture.pdf")
    joined = "\n".join(unit.content.text for unit in build.document.units)
    assert "Policy Manual Running Header" not in joined
    assert "Internal Review Copy Only" not in joined
    assert "Section Overview" in joined
    titles = {unit.title for unit in build.document.units if unit.title}
    assert "Section Overview" in titles


def test_fixture_tables_and_numbered_list_are_structured():
    pages = _fixture_geometries()
    build = build_layout_document(pages, document_id="fix12", source_filename="fixture.pdf")
    tables = [unit for unit in build.document.units if isinstance(unit.content, TableContent)]
    lists = [unit for unit in build.document.units if isinstance(unit.content, ListContent)]
    assert tables
    assert any(unit.content.headers == ["Item", "Status", "Notes"] for unit in tables)
    assert lists
    assert any(
        item.text.startswith("1.")
        for unit in lists
        for item in unit.content.items
    )


def test_fixture_folios_are_furniture_not_body_units():
    pages = _fixture_geometries()
    build = build_layout_document(pages, document_id="fix12", source_filename="fixture.pdf")
    folio = next(item for item in build.associations if item.association_id.endswith(":folio"))
    body_ids = {
        rid
        for unit in build.document.units
        for rid in (unit.structured_fields.get("region_ids") or [])
    }
    assert "p2:word:39" in folio.region_ids
    assert "p2:word:39" not in body_ids


def test_layout_does_not_change_table_furniture_or_hyphen_continuation():
    pages = _fixture_geometries()
    assert reconstruct_page_furniture(pages) == []
    assert reconstruct_cross_page_continuation(
        pages[5], pages[6], furniture_region_ids=frozenset()
    ) == []
    document_assoc = reconstruct_document_associations(pages)
    assert not any(
        item.kind == SpatialRelationKind.CONTINUATION
        and item.origin == EvidenceOrigin.LAYOUT_RECONSTRUCTED
        and item.association_id.startswith("assoc:xpage:")
        for item in document_assoc
    )


def test_case_g_continuation_still_joins_after_layout_build():
    pages = []
    for n in range(1, 5):
        pages.append(
            _page(
                n,
                [
                    _word(n, 0, "to submit the hard", 48.0, 97.3, 300.0, 111.0),
                    _word(n, 1, "copy remains unfinished", 48.0, 113.3, 347.0, 127.0),
                    _word(n, 2, str(n + 1), 48.0, 588.3, 56.0, 600.7),
                ],
            )
        )
    build = build_layout_document(pages, document_id="caseg", source_filename="caseg.pdf")
    assert any(item.association_id.endswith(":folio") for item in build.associations)
    destination = _page(
        2,
        [
            _word(2, 0, "copy of enrolment leftover", 48.0, 90.0, 220.0, 102.0),
            _word(2, 1, "requirements authenticity", 48.0, 103.0, 220.0, 115.0),
        ],
    )
    joins = reconstruct_cross_page_continuation(
        pages[0], destination, furniture_region_ids=frozenset()
    )
    confirmed = [
        item
        for item in joins
        if item.origin == EvidenceOrigin.LAYOUT_RECONSTRUCTED
        and item.kind == SpatialRelationKind.CONTINUATION
    ]
    assert len(confirmed) == 1
    assert confirmed[0].note == "Candidate cross-page continuation: '2' -> 'copy of enrolment leftover'"


def test_heading_persists_across_pages_until_replaced():
    pages = [
        _page(
            1,
            [
                _word(1, 0, "Article 2. Admission Requirements", 48.0, 72.0, 280.0, 86.0),
                _word(1, 1, "Submit the completed application form before the deadline.", 48.0, 110.0, 400.0, 124.0),
            ],
        ),
        _page(
            2,
            [
                _word(2, 0, "Later body paragraph continues on the next page without that heading.", 48.0, 90.0, 400.0, 104.0),
            ],
        ),
        _page(
            3,
            [
                _word(3, 0, "Article 3. Enrolment Procedures", 48.0, 72.0, 250.0, 86.0),
                _word(3, 1, "Pay the assessed fees at the cashier.", 48.0, 110.0, 360.0, 124.0),
            ],
        ),
    ]
    build = build_layout_document(pages, document_id="hier", source_filename="hier.pdf")
    page2 = [unit for unit in build.document.units if unit.page_start == 2]
    page3 = [unit for unit in build.document.units if unit.page_start == 3]
    assert page2
    assert all(unit.title == "Article 2. Admission Requirements" for unit in page2)
    assert page3
    assert any(unit.title == "Article 3. Enrolment Procedures" for unit in page3)
    assert all(unit.title != "Article 2. Admission Requirements" for unit in page3)


def test_numbered_title_is_heading_not_one_item_list():
    page = _page(
        1,
        [
            _word(1, 0, "I. Mandate:", 48.0, 72.0, 140.0, 86.0),
            _word(1, 1, "The university shall provide advanced education in agriculture.", 48.0, 110.0, 400.0, 124.0),
        ],
    )
    build = build_layout_document([page], document_id="mandate", source_filename="mandate.pdf")
    types = [unit.structural_type for unit in build.document.units]
    assert "list" not in types
    paragraph = next(unit for unit in build.document.units if isinstance(unit.content, ParagraphContent))
    assert paragraph.title == "I. Mandate:"
    assert "university shall provide" in paragraph.content.text


def test_phone_number_is_not_a_list():
    page = _page(
        1,
        [
            _word(1, 0, "(049) 304-7000", 48.0, 90.0, 160.0, 104.0),
            _word(1, 1, "Office hours are posted at the registrar.", 48.0, 120.0, 360.0, 134.0),
        ],
    )
    build = build_layout_document([page], document_id="phone", source_filename="phone.pdf")
    assert all(not isinstance(unit.content, ListContent) for unit in build.document.units)


def test_synthetic_heading_paragraph_and_list():
    page = _page(
        1,
        [
            _word(1, 0, "Admission Requirements", 48.0, 72.0, 200.0, 86.0),
            _word(1, 1, "Submit the completed application form before the deadline.", 48.0, 110.0, 400.0, 124.0),
            _word(1, 2, "1. Original transcript of records", 48.0, 140.0, 300.0, 154.0),
            _word(1, 3, "2. Certified copy of diploma", 48.0, 160.0, 300.0, 174.0),
        ],
    )
    build = build_layout_document([page], document_id="syn", source_filename="syn.pdf")
    types = [unit.structural_type for unit in build.document.units]
    assert "paragraph" in types
    assert "list" in types
    paragraph = next(unit for unit in build.document.units if isinstance(unit.content, ParagraphContent))
    assert paragraph.title == "Admission Requirements"
    assert paragraph.content.text.startswith("Admission Requirements")
    listed = next(unit for unit in build.document.units if isinstance(unit.content, ListContent))
    assert len(listed.content.items) == 2
    assert listed.content.ordered is True


def test_inspect_layout_includes_chunks_with_provenance():
    pages = _fixture_geometries()
    build = build_layout_document(pages, document_id="fix12", source_filename="fixture.pdf")
    report = inspect_layout(build)
    assert report["page_count"] == 8
    assert report["units"]
    assert report["chunks"]
    assert report["engine"] == "global_layout"
    chunk = report["chunks"][0]
    assert "text" in chunk
    assert chunk["metadata"].get("document_id") == "fix12"
    table_chunks = [
        item for item in report["chunks"] if item["metadata"].get("structural_type") == "table"
    ]
    assert table_chunks
    assert all("Section Overview" in item["text"] for item in table_chunks)
    assert all("Item | Status | Notes" in item["text"] for item in table_chunks)
    chunks = chunk_document_record(build.document)
    assert len(chunks) == len(report["chunks"])
    assert all(
        chunk.metadata.get("page_start") is not None or chunk.metadata.get("completeness")
        for chunk in chunks
    )


def test_text_furniture_still_not_in_document_association_entry_point():
    pages = _fixture_geometries()
    document_assoc = reconstruct_document_associations(pages)
    text = reconstruct_text_page_furniture(pages)
    assert text
    assert {item.association_id for item in text}.isdisjoint(
        {item.association_id for item in document_assoc}
    )


def test_overlapping_cover_year_joins_edition_line():
    page = _page(
        1,
        [
            _word(1, 0, "2021", 215.2, 516.8, 280.0, 548.3),
            _word(1, 1, "EDITION", 215.8, 547.9, 300.0, 561.4),
            _word(
                1,
                2,
                "Approved pursuant to Board Resolution No. 111, series of 2021",
                163.6,
                563.3,
                400.0,
                573.5,
            ),
        ],
    )
    build = build_layout_document([page], document_id="cover", source_filename="cover.pdf")
    texts = [unit.content.text for unit in build.document.units]
    assert not any(text.strip() == "2021" for text in texts)
    joined = " ".join(texts)
    assert "2021" in joined
    assert "EDITION" in joined
    assert "Board Resolution No. 111" in joined
    assert len(build.document.units) == 1


def test_sparse_cover_keeps_identity_and_does_not_persist():
    pages = [
        _page(
            1,
            [
                _word(1, 0, "Laguna State Polytechnic University", 155.0, 434.7, 400.0, 454.7),
                _word(1, 1, "2026 (1st EDITION)", 283.0, 664.9, 420.0, 699.1),
            ],
        ),
        _page(
            2,
            [
                _word(
                    2,
                    0,
                    "The university shall provide advanced education in agriculture.",
                    48.0,
                    110.0,
                    400.0,
                    124.0,
                ),
            ],
        ),
    ]
    build = build_layout_document(pages, document_id="idcover", source_filename="idcover.pdf")
    page1 = [unit for unit in build.document.units if unit.page_start == 1]
    page2 = [unit for unit in build.document.units if unit.page_start == 2]
    assert len(page1) == 1
    assert "Laguna State Polytechnic University" in page1[0].content.text
    assert "2026 (1st EDITION)" in page1[0].content.text
    assert page2
    assert all(unit.title != "Laguna State Polytechnic University" for unit in page2)


def test_hyphenated_numbered_heading_is_completed():
    page = _page(
        1,
        [
            _word(1, 0, "VIII. Program on Awards and Incen-", 38.9, 110.9, 400.0, 135.6),
            _word(1, 1, "tives for Service Excellence (PRAISE)", 38.9, 135.6, 400.0, 160.4),
            _word(
                1,
                2,
                "In line with the Revised Policies on Employee Suggestions.",
                74.9,
                173.9,
                400.0,
                187.4,
            ),
        ],
    )
    build = build_layout_document([page], document_id="praise", source_filename="praise.pdf")
    titles = [unit.title for unit in build.document.units if unit.title]
    assert titles
    assert all(not (title or "").endswith("Incen-") for title in titles)
    assert any("Incentives" in (title or "") and "PRAISE" in (title or "") for title in titles)
    body = next(unit for unit in build.document.units if isinstance(unit.content, ParagraphContent))
    assert "In line with the Revised Policies" in body.content.text
    assert "Incentives for Service Excellence (PRAISE)" in body.content.text


def test_toc_page_number_line_is_not_a_heading():
    pages = [
        _page(
            1,
            [
                _word(
                    1,
                    0,
                    "1. Request for quarterly/semi-annual/annual data 47",
                    84.0,
                    94.9,
                    400.0,
                    108.3,
                ),
                _word(
                    1,
                    1,
                    "XII. GENERAL SERVICES UNIT ............................................................ 48",
                    72.0,
                    127.0,
                    400.0,
                    140.3,
                ),
            ],
        ),
        _page(
            2,
            [
                _word(
                    2,
                    0,
                    "Maintenance of buildings follows the posted schedule.",
                    48.0,
                    110.0,
                    400.0,
                    124.0,
                ),
            ],
        ),
    ]
    build = build_layout_document(pages, document_id="toc", source_filename="toc.pdf")
    titles = {unit.title for unit in build.document.units if unit.title}
    assert "1. Request for quarterly/semi-annual/annual data 47" not in titles
    assert not any(title and title.endswith(" 48") for title in titles)
    page2 = [unit for unit in build.document.units if unit.page_start == 2]
    assert page2
    assert all(
        unit.title != "1. Request for quarterly/semi-annual/annual data 47" for unit in page2
    )
    joined = "\n".join(unit.content.text for unit in build.document.units)
    assert "Request for quarterly/semi-annual/annual data 47" in joined
    assert "GENERAL SERVICES UNIT" in joined


def test_numbered_sentence_fragment_is_not_a_heading():
    page = _page(
        1,
        [
            _word(
                1,
                0,
                "3. The professor /instructor shall share with parents the responsibility of",
                48.0,
                72.0,
                420.0,
                86.0,
            ),
            _word(
                1,
                1,
                "guiding students toward the completion of their program.",
                48.0,
                110.0,
                400.0,
                124.0,
            ),
        ],
    )
    build = build_layout_document([page], document_id="frag", source_filename="frag.pdf")
    assert all(
        not (unit.title or "").startswith("3. The professor")
        for unit in build.document.units
    )
    joined = "\n".join(unit.content.text for unit in build.document.units)
    assert "shall share with parents the responsibility of" in joined
    assert "guiding students toward the completion" in joined


def test_nested_outline_marker_is_not_a_heading():
    page = _page(
        1,
        [
            _word(1, 0, "4.5. Retention of student records", 48.0, 72.0, 300.0, 86.0),
            _word(1, 1, "Records remain in the registrar for five years.", 48.0, 110.0, 400.0, 124.0),
        ],
    )
    build = build_layout_document([page], document_id="outline", source_filename="outline.pdf")
    assert all(unit.title != "4.5. Retention of student records" for unit in build.document.units)


def test_toc_page_does_not_inherit_prior_heading_but_stack_survives_it():
    """Real, quantified Phase 6.22-handoff failure: Citizen's Charter
    ``IV. Service Pledge:`` incorrectly titled 87 units on pages 3-8,
    including TOC listing lines such as
    ``1. Request for quarterly/semi-annual/annual data 47``.

    Page-level, shape-based fix: a page whose lines are PREDOMINANTLY
    TOC-shaped must not inherit the previously active heading as a parent
    (the TOC is an index, not body content under that section) -- but the
    heading stack itself must survive the TOC page unchanged, so real
    content immediately afterward still correctly inherits it.
    """
    pages = [
        _page(
            1,
            [
                _word(1, 0, "IV. Service Pledge:", 48.0, 72.0, 260.0, 86.0),
                _word(
                    1,
                    1,
                    "We commit to serve every client with fairness and efficiency.",
                    48.0,
                    110.0,
                    420.0,
                    124.0,
                ),
            ],
        ),
        _page(
            2,
            [
                _word(
                    2,
                    0,
                    "1. Request for quarterly/semi-annual/annual data 47",
                    84.0,
                    72.0,
                    400.0,
                    86.0,
                ),
                _word(
                    2,
                    1,
                    "2. Issuance of certified true copies of documents ......................... 48",
                    84.0,
                    94.0,
                    400.0,
                    108.0,
                ),
                _word(
                    2,
                    2,
                    "3. Processing of scholarship applications and renewals 49",
                    84.0,
                    116.0,
                    400.0,
                    130.0,
                ),
            ],
        ),
        _page(
            3,
            [
                _word(
                    3,
                    0,
                    "Clients may file a complaint at the office of the day if service standards are not met.",
                    48.0,
                    110.0,
                    420.0,
                    124.0,
                ),
            ],
        ),
    ]
    build = build_layout_document(pages, document_id="charter-toc", source_filename="charter.pdf")
    page2_units = [unit for unit in build.document.units if unit.page_start == 2]
    page3_units = [unit for unit in build.document.units if unit.page_start == 3]
    assert page2_units
    assert page3_units
    # The TOC page's own units must not carry the pre-TOC heading as title.
    assert all(unit.title != "IV. Service Pledge:" for unit in page2_units)
    # No TOC listing line is itself promoted into a title either.
    assert all(
        not (unit.title or "").startswith("1. Request for quarterly")
        for unit in build.document.units
    )
    # The stack survives the TOC page untouched: real content right after
    # it still correctly inherits the same, still-active section heading.
    assert any(unit.title == "IV. Service Pledge:" for unit in page3_units)
    # No source text is discarded -- it only loses the (wrong) title.
    joined = "\n".join(unit.content.text for unit in build.document.units)
    assert "Request for quarterly/semi-annual/annual data 47" in joined
    assert "Issuance of certified true copies" in joined
    assert "Clients may file a complaint" in joined


def test_fully_parenthetical_citation_is_not_a_heading():
    """Real, quantified Phase 6.22-handoff failure: Faculty Manual
    ``(LSPU Code, 2020)`` incorrectly titled 41 units on pages 66-70,
    with the following policy body (e.g. Teacher's Leave) inheriting that
    citation as its title.

    Shape-based fix: a heading candidate whose ENTIRE text is one balanced
    parenthesized unit is a citation/reference, not a real heading --
    independent of the specific words inside the parentheses.
    """
    page = _page(
        1,
        [
            _word(1, 0, "(LSPU Code, 2020)", 48.0, 72.0, 180.0, 86.0),
            _word(
                1,
                1,
                "Teacher's Leave. A full-time faculty member is entitled to leave credits.",
                48.0,
                110.0,
                420.0,
                124.0,
            ),
        ],
    )
    build = build_layout_document([page], document_id="faculty-paren", source_filename="faculty.pdf")
    assert all(unit.title != "(LSPU Code, 2020)" for unit in build.document.units)
    joined = "\n".join(unit.content.text for unit in build.document.units)
    assert "(LSPU Code, 2020)" in joined
    assert "Teacher's Leave" in joined


def test_fully_parenthetical_heading_rule_is_generic_not_phrase_specific():
    """Same shape rule, a wholly different parenthetical phrase -- proves
    this is not a hardcoded check for the one real Faculty Manual citation."""
    page = _page(
        1,
        [
            _word(1, 0, "(Board Resolution No. 55, s. 2019)", 48.0, 72.0, 260.0, 86.0),
            _word(
                1,
                1,
                "Research Incentive Grant. Faculty who publish receive a cash award.",
                48.0,
                110.0,
                420.0,
                124.0,
            ),
        ],
    )
    build = build_layout_document([page], document_id="faculty-paren-2", source_filename="faculty2.pdf")
    assert all(unit.title != "(Board Resolution No. 55, s. 2019)" for unit in build.document.units)


def test_two_separate_parentheticals_on_one_line_are_not_rejected_as_a_unit():
    """Boundary case: ``"(a) and (b)"`` starts with ``(`` and ends with
    ``)`` but is two separate parenthetical fragments joined by prose, not
    one wrapped citation -- the fully-parenthetical shape check must not
    misfire on this and swallow a genuine two-item reference."""
    page = _page(
        1,
        [
            _word(1, 0, "See subsections (a) and (b) of this article for the complete list.", 48.0, 72.0, 420.0, 86.0),
            _word(1, 1, "Each subsection defines a distinct disciplinary category.", 48.0, 110.0, 420.0, 124.0),
        ],
    )
    build = build_layout_document([page], document_id="paren-pair", source_filename="pair.pdf")
    joined = "\n".join(unit.content.text for unit in build.document.units)
    assert "See subsections (a) and (b)" in joined


def test_heading_immediately_nested_by_sub_heading_is_not_duplicated_as_orphan():
    """Real, quantified defect (chunk-quality evaluation): a chapter/office
    heading with no body of its own, immediately followed by a numbered
    sub-heading (no body between them), used to be emitted BOTH as its own
    standalone unit whose entire text duplicates its own title AND as the
    first entry of ``hierarchy_path`` on every real unit beneath it --
    confirmed on the real Citizen's Charter corpus: "III. ACCOUNTING OFFICE"
    (Roman, level 1) directly followed by "1. Request for Refund Payment"
    (Arabic, level 2) produced a zero-information duplicate chunk. Since the
    sub-heading NESTS (level 2 > level 1 -- see ``_push_heading``), the
    parent's text already survives verbatim in the child's own
    ``hierarchy_path``, so the standalone duplicate must not be emitted."""
    page = _page(
        1,
        [
            _word(1, 0, "III. ACCOUNTING OFFICE", 48.0, 72.0, 220.0, 86.0),
            _word(1, 1, "1. Request for Refund Payment", 48.0, 100.0, 260.0, 114.0),
            _word(1, 2, "This includes the process on refund of payment is being done.", 48.0, 128.0, 420.0, 142.0),
        ],
    )
    build = build_layout_document([page], document_id="nest", source_filename="nest.pdf")
    texts = [unit.content.text for unit in build.document.units]
    assert "III. ACCOUNTING OFFICE" not in texts, (
        "parent heading must not survive as its own zero-information duplicate chunk"
    )
    child = next(unit for unit in build.document.units if "Request for Refund Payment" in unit.content.text)
    assert child.hierarchy_path == ["III. ACCOUNTING OFFICE", "1. Request for Refund Payment"], (
        "parent heading text must still be recoverable via the child's own hierarchy_path"
    )


def test_sibling_heading_with_no_body_still_preserves_prior_heading_text():
    """Counterpart to the nesting test above: when the FOLLOWING heading is
    the SAME level (a sibling, not a child), it REPLACES the pending
    heading on the stack rather than nesting under it -- the pending
    heading's text would vanish from every subsequent unit's
    hierarchy_path entirely if not emitted as its own standalone unit, so
    this case must keep emitting it exactly as before. Confirmed against
    the real Citizen's Charter corpus: "III. ACCOUNTING OFFICE" followed by
    the sibling "IV. SECURITY MANAGEMENT OFFICE", also with no body
    directly beneath either heading's own appearance."""
    page = _page(
        1,
        [
            _word(1, 0, "III. ACCOUNTING OFFICE", 48.0, 72.0, 220.0, 86.0),
            _word(1, 1, "IV. SECURITY MANAGEMENT OFFICE", 48.0, 100.0, 260.0, 114.0),
            _word(1, 2, "This office handles campus security concerns and services.", 48.0, 128.0, 420.0, 142.0),
        ],
    )
    build = build_layout_document([page], document_id="sibling", source_filename="sibling.pdf")
    texts = [unit.content.text for unit in build.document.units]
    assert "III. ACCOUNTING OFFICE" in texts, (
        "a heading replaced by a same-level sibling must still be preserved as its own unit -- "
        "its text would otherwise be discarded entirely, violating the project's "
        "standing 'never discard extracted source text' rule"
    )
    body = next(
        unit for unit in build.document.units if "security concerns and services" in unit.content.text
    )
    assert body.hierarchy_path == ["IV. SECURITY MANAGEMENT OFFICE"]
    assert "III. ACCOUNTING OFFICE" not in body.hierarchy_path
