"""Phase 7.18 standalone digital text-only page-furniture detector.

Does not modify Phase 7.12 fixtures, 7.8 table detection, or continuation
endpoint filtering. Case G continuation join is preserved on purpose.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.services.common_representation.reconstruction import (
    _FOLIO_LIKE_TOKEN_RE,
    _furniture_group_id,
    _text_furniture_group_id,
    _FurnitureCandidate,
    _TextFurnitureCandidate,
    furniture_group_id,
    is_page_furniture_association,
    parse_text_folio_line,
    reconstruct_cross_page_continuation,
    reconstruct_document_associations,
    reconstruct_page_furniture,
    reconstruct_text_page_furniture,
)
from app.services.common_representation.types import (
    EvidenceOrigin,
    PageGeometry,
    SpatialRegion,
    SpatialRegionType,
    SpatialRelationKind,
)

_FIXTURE_JSON = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "phase_7_12_text_only_furniture"
    / "provenance"
    / "digital_extraction.json"
)
_PAGE_W = 468.0
_PAGE_H = 612.0
_REGION_TYPES = {
    "word": SpatialRegionType.WORD,
    "table": SpatialRegionType.TABLE,
    "cell": SpatialRegionType.CELL,
    "block": SpatialRegionType.BLOCK,
}


def _word(page: int, index: int, text: str, x0: float, y0: float, x1: float, y1: float) -> SpatialRegion:
    return SpatialRegion(
        region_id=f"p{page}:word:{index}",
        page_number=page,
        region_type=SpatialRegionType.WORD,
        text=text,
        bbox=(x0, y0, x1, y1),
        reading_order_index=index,
    )


def _table(page: int, bbox: tuple[float, float, float, float], text: str = "cell") -> SpatialRegion:
    return SpatialRegion(
        region_id=f"p{page}:table:0",
        page_number=page,
        region_type=SpatialRegionType.TABLE,
        text=text,
        bbox=bbox,
    )


def _page(number: int, regions: list[SpatialRegion], *, width: float = _PAGE_W, height: float = _PAGE_H) -> PageGeometry:
    return PageGeometry(
        page_number=number,
        width=width,
        height=height,
        rotation=0,
        regions=regions,
        geometry_scale=1.0,
        coordinate_width=width,
        coordinate_height=height,
    )


def _roles(associations):
    return sorted(association.association_id.rsplit(":", 1)[-1] for association in associations)


def _text_ids_for_role(associations, role: str) -> set[str]:
    found: set[str] = set()
    for association in associations:
        if association.association_id.endswith(f":{role}"):
            found.update(association.region_ids)
    return found


def _content_page(number: int, *, folio_text: str, folio_x: float = 220.0) -> PageGeometry:
    hx = 96.0 if number % 2 == 0 else 36.0
    return _page(
        number,
        [
            _word(number, 0, "Policy Manual Running Header", hx, 18.3, hx + 124.0, 30.7),
            _word(number, 1, "Unique body", 48.0, 97.3, 200.0, 111.0),
            _word(number, 2, "Internal Review Copy Only", hx, 568.3, hx + 106.5, 580.7),
            _word(number, 3, folio_text, folio_x, 588.3, folio_x + 8.0, 600.7),
        ],
    )


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def test_folio_like_token_regex_unchanged_from_table_hygiene():
    assert _FOLIO_LIKE_TOKEN_RE.pattern == (
        r"\b(?:[ivxlcdm]+|\d+)(?:\s*(?:of|/)\s*(?:[ivxlcdm]+|\d+))?\b"
    )
    assert _FOLIO_LIKE_TOKEN_RE.search("civil") is not None


@pytest.mark.parametrize(
    "text, current, kind",
    [
        ("1", 1, "arabic"),
        ("12", 12, "arabic"),
        ("ii", 2, "roman"),
        ("iv", 4, "roman"),
        ("xiv", 14, "roman"),
        ("Page 3 of 12", 3, "n_of_m"),
        ("page 4 of 12", 4, "n_of_m"),
        ("3 of 12", 3, "n_of_m"),
        ("3/12", 3, "n_of_m"),
        ("iv of xii", 4, "n_of_m"),
    ],
)
def test_parse_text_folio_line_accepts_supported_shapes(text, current, kind):
    parsed = parse_text_folio_line(text)
    assert parsed is not None
    assert parsed.current == current
    assert parsed.kind == kind
    assert parsed.ambiguous_single_roman is False


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "civil",
        "civic",
        "did",
        "mid",
        "IIII",
        "iix",
        "I. Introduction",
        "1. Introduction",
        "Section Overview",
        "Ordinary body paragraph for content page 2.",
        "2.",
        "(2)",
    ],
)
def test_parse_text_folio_line_rejects_non_folios(text):
    assert parse_text_folio_line(text) is None


@pytest.mark.parametrize("text", ["I", "V", "X", "L", "C", "D", "M", "i", "v", "x"])
def test_parse_text_folio_line_marks_single_character_roman_ambiguous(text):
    parsed = parse_text_folio_line(text)
    assert parsed is not None
    assert parsed.ambiguous_single_roman is True


def test_parse_text_folio_line_empty_string_is_not_roman():
    from app.services.common_representation.reconstruction import _CANONICAL_ROMAN_RE

    assert parse_text_folio_line("") is None
    assert _CANONICAL_ROMAN_RE.fullmatch("") is None


# ---------------------------------------------------------------------------
# Fixture (Phase 7.12 digital provenance, read-only)
# ---------------------------------------------------------------------------


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


def test_fixture_recognizes_header_footer_and_varying_folio():
    pages = _fixture_geometries()
    furniture = reconstruct_text_page_furniture(pages)
    assert _roles(furniture) == ["folio", "footer", "header"]
    header_ids = _text_ids_for_role(furniture, "header")
    footer_ids = _text_ids_for_role(furniture, "footer")
    folio_ids = _text_ids_for_role(furniture, "folio")
    assert "p2:word:0" in header_ids
    assert "p8:word:3" in header_ids
    assert "p2:word:35" in footer_ids
    assert "p2:word:39" in folio_ids
    assert "p8:word:39" in folio_ids
    assert furniture_group_id(furniture[0]) is not None
    assert all(item.origin == EvidenceOrigin.LAYOUT_RECONSTRUCTED for item in furniture)
    assert all(item.confidence == 1.0 for item in furniture)
    assert all(item.kind == SpatialRelationKind.PAGE_FURNITURE for item in furniture)
    assert all("source=word" in (item.note or "") for item in furniture)
    for item in furniture:
        digest = furniture_group_id(item)
        assert digest is not None
        assert item.association_id == f"assoc:furniture:{digest}:{item.association_id.rsplit(':', 1)[-1]}"


def test_fixture_rejects_section_overview_repeated_body_tables_and_lists():
    pages = _fixture_geometries()
    furniture = reconstruct_text_page_furniture(pages)
    member_ids = {rid for group in furniture for rid in group.region_ids}
    assert "p2:word:4" not in member_ids  # Section Overview
    assert "p2:word:13" not in member_ids  # unique body sentence
    assert "p4:word:35" not in member_ids  # table "Item"
    assert "p5:word:25" not in member_ids  # numbered list "1."


def test_fixture_table_furniture_and_hyphen_continuation_unchanged():
    pages = _fixture_geometries()
    assert reconstruct_page_furniture(pages) == []
    assert reconstruct_cross_page_continuation(
        pages[5], pages[6], furniture_region_ids=frozenset()
    ) == []
    document = reconstruct_document_associations(pages)
    table_furniture = [item for item in document if is_page_furniture_association(item)]
    assert table_furniture == []
    xpage = [
        item
        for item in document
        if item.kind == SpatialRelationKind.CONTINUATION
        and item.association_id.startswith("assoc:xpage:")
        and item.origin == EvidenceOrigin.LAYOUT_RECONSTRUCTED
    ]
    assert xpage == []
    text_ids = {item.association_id for item in reconstruct_text_page_furniture(pages)}
    document_ids = {item.association_id for item in document}
    assert text_ids.isdisjoint(document_ids)


# ---------------------------------------------------------------------------
# Numeric adversarial
# ---------------------------------------------------------------------------


def test_varying_last_line_numeric_folios_confirmed():
    pages = [_content_page(n, folio_text=str(n)) for n in range(2, 6)]
    furniture = reconstruct_text_page_furniture(pages)
    assert "folio" in _roles(furniture)
    folio_ids = _text_ids_for_role(furniture, "folio")
    assert "p2:word:3" in folio_ids
    assert "p5:word:3" in folio_ids


def test_all_identical_last_line_numeric_values_remain_indeterminate():
    pages = [_content_page(n, folio_text="2") for n in range(2, 6)]
    furniture = reconstruct_text_page_furniture(pages)
    assert "folio" not in _roles(furniture)
    assert "footer" in _roles(furniture)
    footer_ids = _text_ids_for_role(furniture, "footer")
    assert "p2:word:3" not in footer_ids


def test_mid_page_numeric_lines_rejected():
    pages = []
    for n in range(2, 6):
        pages.append(
            _page(
                n,
                [
                    _word(n, 0, "Policy Manual Running Header", 96.0, 18.3, 220.0, 30.7),
                    _word(n, 1, "Unique body", 48.0, 97.3, 200.0, 111.0),
                    _word(n, 2, str(n), 48.0, 200.0, 56.0, 214.0),
                    _word(n, 3, "continues below.", 48.0, 230.0, 200.0, 244.0),
                    _word(n, 4, "Internal Review Copy Only", 96.0, 568.3, 202.5, 580.7),
                ],
            )
        )
    furniture = reconstruct_text_page_furniture(pages)
    member_ids = {rid for group in furniture for rid in group.region_ids}
    assert "p2:word:2" not in member_ids
    assert "folio" not in _roles(furniture)


def test_numeric_table_values_excluded():
    pages = []
    for n in range(2, 6):
        pages.append(
            _page(
                n,
                [
                    _word(n, 0, "Policy Manual Running Header", 96.0, 18.3, 220.0, 30.7),
                    _word(n, 1, "Unique body", 48.0, 97.3, 200.0, 111.0),
                    _word(n, 2, str(n), 52.0, 302.0, 60.0, 313.0),
                    _table(n, (48.0, 300.0, 328.0, 348.0), text=str(n)),
                    _word(n, 3, "Internal Review Copy Only", 96.0, 568.3, 202.5, 580.7),
                ],
            )
        )
    furniture = reconstruct_text_page_furniture(pages)
    member_ids = {rid for group in furniture for rid in group.region_ids}
    assert "p2:word:2" not in member_ids
    assert "folio" not in _roles(furniture)


def test_numbered_list_lines_rejected():
    pages = []
    for n in range(2, 6):
        pages.append(
            _page(
                n,
                [
                    _word(n, 0, "Policy Manual Running Header", 96.0, 18.3, 220.0, 30.7),
                    _word(n, 1, "1. Introduction", 48.0, 97.3, 160.0, 111.0),
                    _word(n, 2, "Internal Review Copy Only", 96.0, 568.3, 202.5, 580.7),
                    _word(n, 3, str(n), 220.0, 588.3, 228.0, 600.7),
                ],
            )
        )
    furniture = reconstruct_text_page_furniture(pages)
    member_ids = {rid for group in furniture for rid in group.region_ids}
    assert "p2:word:1" not in member_ids


def test_sparse_numeric_only_pages_do_not_independently_confirm():
    pages = [_page(n, [_word(n, 0, str(n), 220.0, 588.3, 228.0, 600.7)]) for n in range(1, 5)]
    assert reconstruct_text_page_furniture(pages) == []


def test_sparse_numeric_page_may_join_already_confirmed_folio_group():
    pages = [_content_page(n, folio_text=str(n)) for n in range(2, 6)]
    pages.append(_page(6, [_word(6, 0, "6", 220.0, 588.3, 228.0, 600.7)]))
    furniture = reconstruct_text_page_furniture(pages)
    folio_ids = _text_ids_for_role(furniture, "folio")
    assert "p2:word:3" in folio_ids
    assert "p6:word:0" in folio_ids


def test_same_column_distant_header_remains_indeterminate():
    pages = []
    for n in range(2, 6):
        pages.append(
            _page(
                n,
                [
                    _word(n, 0, "Policy Manual Running Header", 48.0, 18.3, 172.0, 30.7),
                    _word(n, 1, f"Unique body {n}", 48.0, 97.3, 200.0, 111.0),
                    _word(n, 2, "Internal Review Copy Only", 96.0, 568.3, 202.5, 580.7),
                    _word(n, 3, str(n), 220.0, 588.3, 228.0, 600.7),
                ],
            )
        )
    furniture = reconstruct_text_page_furniture(pages)
    assert "header" not in _roles(furniture)
    assert "footer" in _roles(furniture)


def test_n_of_m_folios_confirmed_when_current_page_varies():
    pages = [_content_page(n, folio_text=f"{n} of 12") for n in range(2, 6)]
    furniture = reconstruct_text_page_furniture(pages)
    assert "folio" in _roles(furniture)


def test_identical_n_of_m_values_remain_indeterminate():
    pages = [_content_page(n, folio_text="3 of 12") for n in range(2, 6)]
    furniture = reconstruct_text_page_furniture(pages)
    assert "folio" not in _roles(furniture)


def test_case_g_aligned_folio_detected_but_continuation_still_joins():
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
    furniture = reconstruct_text_page_furniture(pages)
    assert "folio" in _roles(furniture)
    folio_ids = _text_ids_for_role(furniture, "folio")
    assert "p1:word:2" in folio_ids
    destination = _page(
        2,
        [
            _word(2, 0, "copy of enrolment leftover", 48.0, 90.0, 220.0, 102.0),
            _word(2, 1, "requirements authenticity", 48.0, 103.0, 220.0, 115.0),
        ],
    )
    unfiltered = reconstruct_cross_page_continuation(
        pages[0], destination, furniture_region_ids=frozenset()
    )
    with_word_ids = reconstruct_cross_page_continuation(
        pages[0], destination, furniture_region_ids=frozenset(folio_ids)
    )
    for joins in (unfiltered, with_word_ids):
        confirmed = [
            item
            for item in joins
            if item.origin == EvidenceOrigin.LAYOUT_RECONSTRUCTED
            and item.kind == SpatialRelationKind.CONTINUATION
        ]
        assert len(confirmed) == 1
        assert confirmed[0].note == "Candidate cross-page continuation: '2' -> 'copy of enrolment leftover'"


# ---------------------------------------------------------------------------
# Roman
# ---------------------------------------------------------------------------


def test_canonical_multi_character_roman_folios_confirmed():
    values = ["ii", "iii", "iv", "vi"]
    pages = [_content_page(n, folio_text=values[i]) for i, n in enumerate(range(2, 6))]
    furniture = reconstruct_text_page_furniture(pages)
    assert "folio" in _roles(furniture)


def test_roman_to_arabic_transition_stays_one_folio_group():
    values = ["ii", "iii", "4", "5"]
    pages = [_content_page(n, folio_text=values[i]) for i, n in enumerate(range(2, 6))]
    furniture = reconstruct_text_page_furniture(pages)
    folio_groups = [item for item in furniture if item.association_id.endswith(":folio")]
    assert len(folio_groups) == 1
    assert len(folio_groups[0].region_ids) == 4


def test_ambiguous_single_character_roman_folios_not_confirmed():
    pages = [_content_page(n, folio_text=value) for n, value in zip(range(2, 6), ["I", "V", "X", "L"])]
    furniture = reconstruct_text_page_furniture(pages)
    assert "folio" not in _roles(furniture)


# ---------------------------------------------------------------------------
# Association identity
# ---------------------------------------------------------------------------


def test_header_and_footer_identities_differ():
    pages = [_content_page(n, folio_text=str(n)) for n in range(2, 6)]
    furniture = reconstruct_text_page_furniture(pages)
    header = next(item for item in furniture if item.association_id.endswith(":header"))
    footer = next(item for item in furniture if item.association_id.endswith(":footer"))
    assert furniture_group_id(header) != furniture_group_id(footer)
    assert header.association_id != footer.association_id


def test_word_hash_material_includes_word_and_cannot_match_table_constructor():
    from app.services.common_representation.reconstruction import _Line

    line = _Line(
        text="Policy Manual Running Header",
        x0=96.0,
        y0=18.3,
        x1=220.0,
        y1=30.7,
        word_region_ids=("p2:word:0",),
    )
    word_cluster = [
        _TextFurnitureCandidate(
            page_number=2,
            line=line,
            rel_y0=0.03,
            rel_y1=0.05,
            rel_h=0.02,
            rel_w=0.26,
            letter_tokens=frozenset({"header", "manual", "policy", "running"}),
            establishing=True,
        )
    ]
    table_cluster = [
        _FurnitureCandidate(
            page_number=2,
            table=SpatialRegion(
                region_id="p2:table:0",
                page_number=2,
                region_type=SpatialRegionType.TABLE,
                text="Policy Manual Running Header",
                bbox=(96.0, 18.3, 220.0, 30.7),
            ),
            rel_y0=0.03,
            rel_y1=0.05,
            rel_h=0.02,
            rel_w=0.26,
            n_rows=1,
            n_cols=1,
            tokens=frozenset({"header", "manual", "policy", "running"}),
        )
    ]
    word_id = _text_furniture_group_id(word_cluster, "header")
    table_id = _furniture_group_id(table_cluster, "header")
    assert word_id != table_id
    word_material = "word|0.03|0.02|header,manual,policy,running|header"
    assert hashlib.sha256(word_material.encode("utf-8")).hexdigest()[:12] == word_id
    table_material = "1|1|0.03|0.02|header,manual,policy,running|header"
    assert hashlib.sha256(table_material.encode("utf-8")).hexdigest()[:12] == table_id


def test_folio_identity_distinct_from_repeated_text_footer():
    pages = [_content_page(n, folio_text=str(n)) for n in range(2, 6)]
    furniture = reconstruct_text_page_furniture(pages)
    folio = next(item for item in furniture if item.association_id.endswith(":folio"))
    footer = next(item for item in furniture if item.association_id.endswith(":footer"))
    assert furniture_group_id(folio) != furniture_group_id(footer)
    assert not folio.association_id.endswith(":footer")
    assert not footer.association_id.endswith(":folio")


def test_text_furniture_ids_are_deterministic():
    pages = [_content_page(n, folio_text=str(n)) for n in range(2, 6)]
    first = reconstruct_text_page_furniture(pages)
    second = reconstruct_text_page_furniture(pages)
    assert [item.association_id for item in first] == [item.association_id for item in second]
    assert [item.region_ids for item in first] == [item.region_ids for item in second]


def test_existing_table_furniture_ids_unchanged_on_compact_header_pages():
    from tests.test_common_representation_reconstruction import _page_with_compact_header

    pages = [
        _page_with_compact_header(1, 40.0, "1 of 9", "continuing-", "word on the next page"),
        _page_with_compact_header(2, 62.0, "2 of 9", "another leftover-", "more lowercase wrap"),
        _page_with_compact_header(3, 40.0, "3 of 9", "Complete sentence.", "Body heading"),
    ]
    table_groups = reconstruct_page_furniture(pages)
    assert len(table_groups) == 1
    assert table_groups[0].association_id.startswith("assoc:furniture:")
    assert table_groups[0].association_id.endswith(":header")
    assert furniture_group_id(table_groups[0]) == furniture_group_id(
        reconstruct_page_furniture(pages)[0]
    )
    assert all("table:" in region_id for region_id in table_groups[0].region_ids)
    document = reconstruct_document_associations(pages)
    document_furniture = [item for item in document if is_page_furniture_association(item)]
    assert [item.association_id for item in document_furniture] == [
        item.association_id for item in table_groups
    ]
    text_groups = reconstruct_text_page_furniture(pages)
    assert all(not item.association_id.endswith(":header") or "word" in (item.note or "") for item in text_groups)
    assert {item.association_id for item in text_groups}.isdisjoint(
        {item.association_id for item in table_groups}
    )
