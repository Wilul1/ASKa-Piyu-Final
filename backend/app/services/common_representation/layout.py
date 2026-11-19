"""Global layout document builder.

Turns ordered ``PageGeometry`` into a ``DocumentRecord`` using the existing
reconstruction producers. Source WORD/TABLE/CELL regions are not rewritten.
Continuation scoring is unchanged: WORD furniture is evidence for unit
construction, not an endpoint filter.

Not called from ingestion.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .chunker import chunk_document_record
from .reconstruction import (
    _ENUMERATION_START_RE,
    _HEADING_TABLE_MAX_GAP,
    _LINE_ADJACENCY_MAX_GAP,
    _SENTENCE_END_RE,
    _group_words_into_lines,
    _line_intersects_any_table,
    _looks_incomplete,
    _starts_enumerated_item,
    associations_for_page_range,
    is_page_furniture_association,
    reconstruct_document_associations,
    reconstruct_text_page_furniture,
)
from .types import (
    Completeness,
    DocumentRecord,
    EvidenceOrigin,
    ExtractionDiagnostics,
    ListContent,
    ListItem,
    PageGeometry,
    ParagraphContent,
    RecognitionDiagnostics,
    SpatialAssociation,
    SpatialRegion,
    SpatialRegionType,
    StructuralUnit,
    TableCell,
    TableContent,
)

_BULLET_START_RE = re.compile(r"^(?:[-*•·]|\u2013|\u2014)\s+\S")
_HEADING_MAX_WORDS = 8
_NUMBERED_HEADING_MAX_WORDS = 16
# Stacked display lines (large cover tokens) can overlap slightly, so a
# small negative gap is still adjacency -- not a new block.
_OVERLAP_WRAP_MIN_GAP = -4.0
_SPARSE_PAGE_MAX_LINES = 8
# A page whose content lines are PREDOMINANTLY TOC-shaped (enumerator +
# dot-leaders/space + trailing 1-3 digit page number) is a table-of-contents
# page, not body content under whatever heading happens to be on the stack.
# Shape/cluster-based only -- no phrase, title, or page-number special case.
_TOC_PAGE_MIN_LINES = 3
_TOC_PAGE_MIN_RATIO = 0.6
# Trailing page number after leaders or a space: TOC shape, not a heading.
_TOC_TRAILING_PAGE_RE = re.compile(
    r"(?:[.\u00b7\u2022\u2024\u2026\u2219]{2,}|\s)\d{1,3}$"
)
_ROMAN_SECTION_RE = re.compile(r"^[IVXLCDM]+\.\s", re.IGNORECASE)
_ARABIC_SECTION_RE = re.compile(r"^\d+[.)]\s")
_SIMPLE_SECTION_ENUM_RE = re.compile(
    r"^(?:"
    r"[IVXLCDM]+\."
    r"|\d+[.)]"
    r")\s+\S",
    re.IGNORECASE,
)
_OUTLINE_ENUM_RE = re.compile(r"^\d+\.\d+")


@dataclass(frozen=True)
class LayoutBuild:
    """Inspectable result of the global layout builder."""

    document: DocumentRecord
    associations: list[SpatialAssociation]
    furniture_region_ids: frozenset[str]


def build_layout_document(
    pages: list[PageGeometry],
    *,
    document_id: str,
    source_filename: str,
) -> LayoutBuild:
    """Rebuild a structured document from already-normalized page geometry."""
    pages_sorted = sorted(pages, key=lambda page: page.page_number)
    table_and_page = reconstruct_document_associations(pages_sorted)
    text_furniture = reconstruct_text_page_furniture(pages_sorted)
    associations = [*table_and_page, *text_furniture]
    furniture_ids = _confirmed_furniture_ids(associations)
    region_pages = {
        region.region_id: page.page_number
        for page in pages_sorted
        for region in page.regions
    }

    units: list[StructuralUnit] = []
    source_order = 0
    heading_stack: list[tuple[int, str]] = []
    for page in pages_sorted:
        page_units, heading_stack = _units_for_page(
            page,
            furniture_ids=furniture_ids,
            heading_stack=heading_stack,
            source_order_start=source_order,
        )
        for unit in page_units:
            unit.spatial_associations = associations_for_page_range(
                associations, region_pages, unit.page_start, unit.page_end
            )
            units.append(unit)
        source_order += len(page_units)

    document = DocumentRecord(
        document_id=document_id,
        source_filename=source_filename,
        classification="information",
        classification_reason="global_layout",
        source_metadata={
            "engine": "global_layout",
            "association_count": str(len(associations)),
            "furniture_region_count": str(len(furniture_ids)),
        },
        units=units,
        page_geometries=pages_sorted,
    )
    return LayoutBuild(
        document=document,
        associations=associations,
        furniture_region_ids=furniture_ids,
    )


def inspect_layout(
    build: LayoutBuild,
    *,
    target_chars: int = 1200,
    max_chars: int = 1800,
    overlap_chars: int = 150,
) -> dict:
    """JSON-serializable structure, associations, and chunks for review."""
    chunks = chunk_document_record(
        build.document,
        target_chars=target_chars,
        max_chars=max_chars,
        overlap_chars=overlap_chars,
    )
    return {
        "document_id": build.document.document_id,
        "source_filename": build.document.source_filename,
        "engine": "global_layout",
        "page_count": len(build.document.page_geometries),
        "furniture_region_count": len(build.furniture_region_ids),
        "units": [_inspect_unit(unit) for unit in build.document.units],
        "associations": [
            {
                "association_id": item.association_id,
                "kind": item.kind.value,
                "origin": item.origin.value,
                "confidence": item.confidence,
                "note": item.note,
                "region_ids": list(item.region_ids),
            }
            for item in build.associations
        ],
        "chunks": [
            {
                "chunk_index": chunk.chunk_index,
                "text": chunk.text,
                "metadata": dict(chunk.metadata or {}),
            }
            for chunk in chunks
        ],
    }


def _confirmed_furniture_ids(associations: list[SpatialAssociation]) -> frozenset[str]:
    found: set[str] = set()
    for association in associations:
        if not is_page_furniture_association(association):
            continue
        if association.origin != EvidenceOrigin.LAYOUT_RECONSTRUCTED:
            continue
        found.update(association.region_ids)
    return frozenset(found)


def _units_for_page(
    page: PageGeometry,
    *,
    furniture_ids: frozenset[str],
    heading_stack: list[tuple[int, str]],
    source_order_start: int,
) -> tuple[list[StructuralUnit], list[tuple[int, str]]]:
    tables = [
        region
        for region in page.regions
        if region.region_type == SpatialRegionType.TABLE and region.bbox is not None
    ]
    content_tables = [table for table in tables if table.region_id not in furniture_ids]
    lines = [
        line
        for line in _group_words_into_lines(page)
        if not any(rid in furniture_ids for rid in line.word_region_ids)
        and not _line_intersects_any_table(line, tables)
    ]
    events = _reading_order_events(lines, content_tables)
    units: list[StructuralUnit] = []
    stack = list(heading_stack)
    pending: list = []
    order = source_order_start
    sparse = _is_sparse_display_page(lines, content_tables)
    toc_page = _is_toc_page(lines)

    def flush_lines() -> None:
        nonlocal stack, order
        if not pending:
            return
        built, stack = _units_from_line_run(
            pending,
            page_number=page.page_number,
            heading_stack=stack,
            source_order_start=order,
            sparse=sparse,
            toc_page=toc_page,
        )
        units.extend(built)
        order += len(built)
        pending.clear()

    for event in events:
        if event[0] == "table":
            flush_lines()
            table_unit = _table_unit(
                page,
                event[1],
                heading=None if toc_page else _current_title(stack),
                hierarchy_path=[] if toc_page else _hierarchy_path(stack),
                source_order=order,
            )
            if table_unit is not None:
                units.append(table_unit)
                order += 1
            continue
        pending.append(event[1])
    flush_lines()
    return units, stack


def _reading_order_events(lines, tables: list[SpatialRegion]) -> list[tuple]:
    events: list[tuple] = [("line", line, line.y0, line.x0) for line in lines]
    for table in tables:
        events.append(("table", table, table.bbox[1], table.bbox[0]))
    events.sort(key=lambda item: (item[2], item[3]))
    return [(kind, payload) for kind, payload, _y, _x in events]


def _units_from_line_run(
    lines,
    *,
    page_number: int,
    heading_stack: list[tuple[int, str]],
    source_order_start: int,
    sparse: bool = False,
    toc_page: bool = False,
) -> tuple[list[StructuralUnit], list[tuple[int, str]]]:
    blocks = _split_line_blocks(lines, sparse=sparse)
    units: list[StructuralUnit] = []
    stack = list(heading_stack)
    order = source_order_start
    index = 0
    pending_heading_block: list | None = None

    def current_heading() -> str | None:
        return None if toc_page else _current_title(stack)

    def current_hierarchy() -> list[str]:
        return [] if toc_page else _hierarchy_path(stack)

    def heading_ids() -> list[str]:
        if not pending_heading_block:
            return []
        return [rid for line in pending_heading_block for rid in line.word_region_ids]

    def emit_heading_if_orphaned(upcoming_level: int | None = None) -> None:
        nonlocal pending_heading_block, order
        if pending_heading_block is None:
            return
        # If the upcoming heading will NEST under the pending one (strictly
        # higher level number -- see ``_push_heading``), the pending
        # heading's own text is not actually lost by skipping this standalone
        # duplicate: it survives, verbatim, in ``hierarchy_path``/``title`` on
        # every real content unit that follows under it (verified against the
        # real Citizen's Charter corpus: a level-1 "III. ACCOUNTING OFFICE"
        # immediately followed by a level-2 numbered service produces a
        # standalone orphan unit whose entire text duplicates its own title,
        # while the very next real unit already carries
        # ``hierarchy_path=["III. ACCOUNTING OFFICE", "1. ..."]`` -- a pure,
        # zero-information duplicate). Only skip in this one proven-safe
        # case; a same-or-lower-level follower REPLACES the pending heading
        # on the stack (it would otherwise vanish from every subsequent
        # unit's hierarchy_path entirely), so it is still emitted exactly as
        # before -- this preserves the project's standing "never discard
        # extracted source text" rule for every other case.
        if (
            upcoming_level is not None
            and stack
            and upcoming_level > stack[-1][0]
        ):
            pending_heading_block = None
            return
        units.append(
            _paragraph_unit(
                pending_heading_block,
                page_number=page_number,
                heading=current_heading(),
                hierarchy_path=current_hierarchy(),
                source_order=order,
                extra_region_ids=[],
            )
        )
        order += 1
        pending_heading_block = None

    while index < len(blocks):
        block = blocks[index]
        nxt = blocks[index + 1] if index + 1 < len(blocks) else None
        previous = blocks[index - 1] if index else None
        # On a TOC page, no block is treated as a heading -- it is neither
        # pushed onto the (page-spanning) stack nor styled as its own
        # heading unit; every line stays ordinary list/paragraph content
        # under no title. This is the page-level complement to the
        # existing per-line ``_looks_like_toc_line`` check.
        if not toc_page and (
            _is_numbered_heading_block(block, nxt) or _is_heading_block(block, nxt, previous)
        ):
            title = _join_wrapped_text(block)
            emit_heading_if_orphaned(upcoming_level=_heading_level(title))
            stack = _push_heading(stack, title)
            pending_heading_block = block
            index += 1
            continue
        extra_ids = heading_ids()
        pending_heading_block = None
        if _is_list_block(block):
            units.append(
                _list_unit(
                    block,
                    page_number=page_number,
                    heading=current_heading(),
                    hierarchy_path=current_hierarchy(),
                    source_order=order,
                    extra_region_ids=extra_ids,
                )
            )
            order += 1
            index += 1
            continue
        collected = list(block)
        while index + 1 < len(blocks):
            following = blocks[index + 1]
            following_next = blocks[index + 2] if index + 2 < len(blocks) else None
            if not toc_page and (
                _is_numbered_heading_block(following, following_next)
                or _is_heading_block(following, following_next, collected)
            ):
                break
            if _is_list_block(following):
                break
            if not _block_continues(collected, following):
                break
            collected.extend(following)
            index += 1
        units.append(
            _paragraph_unit(
                collected,
                page_number=page_number,
                heading=current_heading(),
                hierarchy_path=current_hierarchy(),
                source_order=order,
                extra_region_ids=extra_ids,
            )
        )
        order += 1
        index += 1
    emit_heading_if_orphaned()
    return units, stack


def _split_line_blocks(lines, *, sparse: bool = False) -> list[list]:
    if not lines:
        return []
    blocks: list[list] = [[lines[0]]]
    for previous, line in zip(lines, lines[1:]):
        if _should_join_lines(previous, line, sparse=sparse):
            blocks[-1].append(line)
            continue
        blocks.append([line])
    return blocks


def _should_join_lines(previous, line, *, sparse: bool) -> bool:
    gap = line.y0 - previous.y1
    prev_list = _is_list_line(previous)
    this_list = _is_list_line(line)
    adjacent = _OVERLAP_WRAP_MIN_GAP <= gap <= _LINE_ADJACENCY_MAX_GAP
    same_kind = prev_list == this_list
    if adjacent and same_kind:
        return True
    # Numbered titles wrap onto a non-enumerated continuation line.
    if adjacent and previous.text.rstrip().endswith("-"):
        return True
    if prev_list and this_list:
        return True
    if sparse and not prev_list and not this_list and gap >= _OVERLAP_WRAP_MIN_GAP:
        return True
    return False


def _is_sparse_display_page(lines, tables: list[SpatialRegion]) -> bool:
    """Cover/identity pages: few unenumerated lines separated by display gaps."""
    if tables or not lines or len(lines) > _SPARSE_PAGE_MAX_LINES:
        return False
    if any(
        _is_list_line(line) or _SIMPLE_SECTION_ENUM_RE.match(line.text.strip())
        for line in lines
    ):
        return False
    return any(
        (lines[index].y0 - lines[index - 1].y1) > _HEADING_TABLE_MAX_GAP
        for index in range(1, len(lines))
    )


def _is_toc_page(lines) -> bool:
    """A page whose non-empty lines are predominantly TOC-shaped (enumerator
    plus dot-leaders/space plus a trailing 1-3 digit page number).

    Cluster-based on the PAGE as a whole, not a single-line check -- a page
    with a handful of incidental TOC-looking lines amid real body prose is
    not reclassified, only a page that is actually an index/listing. No
    phrase, title, institution, or page-number special case: purely the
    existing generic ``_looks_like_toc_line`` shape test applied per line,
    aggregated.
    """
    texts = [line.text.strip() for line in lines if line.text.strip()]
    if len(texts) < _TOC_PAGE_MIN_LINES:
        return False
    toc_like = sum(1 for text in texts if _looks_like_toc_line(text))
    return (toc_like / len(texts)) >= _TOC_PAGE_MIN_RATIO


def _block_continues(collected, following) -> bool:
    """Join leftover wrap lines after heading classification, without swallowing headings."""
    if not collected or not following:
        return False
    gap = following[0].y0 - collected[-1].y1
    if gap < _OVERLAP_WRAP_MIN_GAP or gap > _HEADING_TABLE_MAX_GAP:
        return False
    previous_text = collected[-1].text.rstrip()
    next_text = following[0].text.strip()
    if not previous_text or not next_text:
        return False
    if previous_text.endswith("-"):
        return True
    return next_text[:1].islower()


def _join_wrapped_text(block) -> str:
    parts: list[str] = []
    for line in block:
        text = line.text.strip()
        if not text:
            continue
        if parts and parts[-1].endswith("-"):
            parts[-1] = parts[-1][:-1] + text
        else:
            parts.append(text)
    return " ".join(parts)


def _block_is_hyphen_wrap(block) -> bool:
    return len(block) > 1 and any(line.text.rstrip().endswith("-") for line in block[:-1])


def _current_title(stack: list[tuple[int, str]]) -> str | None:
    return stack[-1][1] if stack else None


def _hierarchy_path(stack: list[tuple[int, str]]) -> list[str]:
    return [title for _, title in stack]


def _heading_level(text: str) -> int:
    stripped = text.strip()
    if _ROMAN_SECTION_RE.match(stripped):
        return 1
    if _ARABIC_SECTION_RE.match(stripped) and not _OUTLINE_ENUM_RE.match(stripped):
        return 2
    return 3


def _push_heading(stack: list[tuple[int, str]], title: str) -> list[tuple[int, str]]:
    level = _heading_level(title)
    return [item for item in stack if item[0] < level] + [(level, title)]


def _looks_like_heading_rest(rest: str) -> bool:
    """Numbered titles are short and title-like; wrapped sentences are not.

    Generic token shape only: a short lowercase closer such as ``of`` / ``a``
    is wrap leftover, and a run of mostly lowercase words is body prose.
    """
    words = rest.split()
    if not words:
        return False
    last = words[-1].strip("\"'“”()[]")
    if last and last.islower() and len(last) <= 3:
        return False
    alpha = [word for word in words if word[:1].isalpha()]
    if len(alpha) >= 4:
        capped = sum(1 for word in alpha if word[:1].isupper())
        if capped < len(alpha) / 2:
            return False
    return True


def _is_fully_parenthetical(text: str) -> bool:
    """True when the ENTIRE string is one balanced parenthesized unit, e.g.
    ``"(LSPU Code, 2020)"`` -- a citation/reference, not a heading.

    Not merely "starts with ( and ends with )": ``"(a) and (b)"`` also has
    that shape, but its first ``(`` closes well before the string ends, so
    it is two separate parenthetical fragments joined by prose, not one
    wrapped unit. Pure bracket-matching shape, no phrase or keyword list.
    """
    stripped = text.strip()
    if len(stripped) < 2 or stripped[0] != "(" or stripped[-1] != ")":
        return False
    depth = 0
    for index, char in enumerate(stripped):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index == len(stripped) - 1
    return False


def _looks_like_toc_line(text: str) -> bool:
    stripped = text.strip()
    if not stripped or not _TOC_TRAILING_PAGE_RE.search(stripped):
        return False
    body = _TOC_TRAILING_PAGE_RE.sub("", stripped).rstrip(" .")
    if not body:
        return False
    if ".." in stripped or "\u2026" in stripped:
        return True
    return bool(
        _SIMPLE_SECTION_ENUM_RE.match(stripped) or _starts_enumerated_item(stripped)
    )


def _is_list_line(line) -> bool:
    stripped = line.text.strip()
    if not _parenthetical_list_marker_allowed(stripped):
        return False
    return _starts_enumerated_item(stripped) or bool(_BULLET_START_RE.match(stripped))


def _parenthetical_list_marker_allowed(text: str) -> bool:
    """Reject phone-like '(049) 304-7000' while keeping '(a)' / '(1)' items."""
    match = re.match(r"^\(([0-9A-Za-z]+)\)(?:\s|$)", text)
    if match is None:
        return True
    inner = match.group(1)
    if len(inner) > 3:
        return False
    return sum(char.isdigit() for char in inner) < 3


def _is_list_block(block) -> bool:
    return bool(block) and all(_is_list_line(line) for line in block)


def _is_numbered_heading_block(block, following) -> bool:
    """A lone top-level enumerated title above body is a heading, not a list.

    Nested outline markers such as ``1.1`` / ``2.6.3`` stay list/body content.
    Hyphen-wrapped titles may span two lines and still count as one heading.
    """
    if following is None:
        return False
    if len(block) != 1 and not _block_is_hyphen_wrap(block):
        return False
    if _is_list_block(following):
        return False
    stripped = _join_wrapped_text(block)
    if _looks_like_toc_line(stripped):
        return False
    if _OUTLINE_ENUM_RE.match(stripped):
        return False
    if not _SIMPLE_SECTION_ENUM_RE.match(stripped):
        return False
    if not _parenthetical_list_marker_allowed(stripped):
        return False
    rest = _ENUMERATION_START_RE.sub("", stripped, count=1).strip()
    if not rest or rest.endswith(";") or rest.endswith(","):
        return False
    words = rest.split()
    if len(words) > _NUMBERED_HEADING_MAX_WORDS:
        return False
    return _looks_like_heading_rest(rest)


def _is_heading_block(block, following, previous=None) -> bool:
    if following is None:
        return False
    if len(block) != 1 and not _block_is_hyphen_wrap(block):
        return False
    if any(_is_list_line(line) for line in block):
        return False
    if previous and _looks_incomplete(previous[-1].text):
        return False
    stripped = _join_wrapped_text(block).strip("\"'“”")
    if _looks_like_toc_line(stripped):
        return False
    if _is_fully_parenthetical(stripped):
        return False
    if stripped.endswith((":", ";", ",")) or _SENTENCE_END_RE.search(stripped):
        return False
    words = stripped.split()
    if not words or len(words) > _HEADING_MAX_WORDS:
        return False
    if len(words) == 1 and len(words[0]) < 8:
        return False
    nxt = following[0]
    gap = nxt.y0 - block[-1].y1
    return gap > _LINE_ADJACENCY_MAX_GAP


def _with_heading(text: str, heading: str | None) -> str:
    body = text.strip()
    if heading and heading not in body:
        return f"{heading}\n\n{body}"
    return body


def _paragraph_unit(
    block,
    *,
    page_number: int,
    heading: str | None,
    hierarchy_path: list[str],
    source_order: int,
    extra_region_ids: list[str] | None = None,
) -> StructuralUnit:
    body = _join_wrapped_text(block)
    region_ids = [*(extra_region_ids or []), *[rid for line in block for rid in line.word_region_ids]]
    return StructuralUnit(
        unit_id=f"layout:p{page_number}:para:{source_order}",
        source_order=source_order,
        title=heading,
        content=ParagraphContent(text=_with_heading(body, heading)),
        structural_type="paragraph",
        content_type="information",
        hierarchy_path=list(hierarchy_path),
        page_start=page_number,
        page_end=page_number,
        extraction_diagnostics=ExtractionDiagnostics(completeness=Completeness.COMPLETE),
        recognition_diagnostics=RecognitionDiagnostics(),
        evidence_origin=EvidenceOrigin.VERBATIM_SOURCE,
        structured_fields={"region_ids": region_ids},
    )


def _list_ordinal(text: str) -> str | None:
    match = _ENUMERATION_START_RE.match(text.strip())
    if not match:
        return None
    token = match.group(0).strip()
    return token.rstrip() or None


def _list_unit(
    block,
    *,
    page_number: int,
    heading: str | None,
    hierarchy_path: list[str],
    source_order: int,
    extra_region_ids: list[str] | None = None,
) -> StructuralUnit:
    items = [
        ListItem(text=line.text.strip(), ordinal=_list_ordinal(line.text))
        for line in block
        if line.text.strip()
    ]
    ordered = any(item.ordinal for item in items)
    rendered = "\n".join(item.text for item in items)
    region_ids = [*(extra_region_ids or []), *[rid for line in block for rid in line.word_region_ids]]
    return StructuralUnit(
        unit_id=f"layout:p{page_number}:list:{source_order}",
        source_order=source_order,
        title=heading,
        content=ListContent(text=_with_heading(rendered, heading), items=items, ordered=ordered),
        structural_type="list",
        content_type="information",
        hierarchy_path=list(hierarchy_path),
        page_start=page_number,
        page_end=page_number,
        extraction_diagnostics=ExtractionDiagnostics(completeness=Completeness.COMPLETE),
        recognition_diagnostics=RecognitionDiagnostics(),
        evidence_origin=EvidenceOrigin.VERBATIM_SOURCE,
        structured_fields={"region_ids": region_ids},
    )


def _table_unit(
    page: PageGeometry,
    table: SpatialRegion,
    *,
    heading: str | None,
    hierarchy_path: list[str],
    source_order: int,
) -> StructuralUnit | None:
    content = _table_content(page, table)
    if content is None:
        return None
    if heading:
        content = TableContent(
            text=_with_heading(content.text, heading),
            headers=content.headers,
            rows=content.rows,
        )
    return StructuralUnit(
        unit_id=f"layout:p{page.page_number}:table:{source_order}",
        source_order=source_order,
        title=heading,
        content=content,
        structural_type="table",
        content_type="information",
        hierarchy_path=list(hierarchy_path),
        page_start=page.page_number,
        page_end=page.page_number,
        extraction_diagnostics=ExtractionDiagnostics(completeness=Completeness.COMPLETE),
        recognition_diagnostics=RecognitionDiagnostics(
            uncertain_table_structure=True if content.headers else None
        ),
        evidence_origin=EvidenceOrigin.VERBATIM_SOURCE,
        structured_fields={
            "region_ids": [table.region_id],
            "table_header_source": "first_row" if content.headers else "none",
        },
    )


def _table_content(page: PageGeometry, table: SpatialRegion) -> TableContent | None:
    prefix = f"{table.region_id}:cell:"
    cells = [
        region
        for region in page.regions
        if region.region_type == SpatialRegionType.CELL and region.region_id.startswith(prefix)
    ]
    if cells:
        by_row: dict[int, dict[int, SpatialRegion]] = {}
        for cell in cells:
            if cell.row is None or cell.column is None:
                continue
            by_row.setdefault(cell.row, {})[cell.column] = cell
        if not by_row:
            return None
        max_col = max(col for row in by_row.values() for col in row)
        row_indices = sorted(by_row)
        headers: list[str] = []
        data_indices = row_indices
        if len(row_indices) >= 2:
            first = by_row[row_indices[0]]
            headers = [first[col].text if col in first else "" for col in range(max_col + 1)]
            data_indices = row_indices[1:]
        rows = [
            [
                TableCell(
                    text=by_row[row_i][col].text if col in by_row[row_i] else "",
                    row=row_i,
                    column=col,
                    is_header=False,
                    evidence_origin=EvidenceOrigin.VERBATIM_SOURCE,
                )
                for col in range(max_col + 1)
            ]
            for row_i in data_indices
        ]
        header_line = " | ".join(headers)
        body = "\n".join(" | ".join(cell.text for cell in row) for row in rows)
        text = "\n".join(part for part in (header_line, body) if part)
        return TableContent(text=text, headers=headers, rows=rows)

    lines = [line for line in (table.text or "").split("\n") if line.strip()]
    if not lines:
        return None
    parsed = [[part.strip() for part in line.split("|")] for line in lines]
    headers = parsed[0] if len(parsed) >= 2 else []
    data = parsed[1:] if headers else parsed
    rows = [
        [
            TableCell(
                text=value,
                row=index + (1 if headers else 0),
                column=col,
                is_header=False,
                evidence_origin=EvidenceOrigin.VERBATIM_SOURCE,
            )
            for col, value in enumerate(row)
        ]
        for index, row in enumerate(data)
    ]
    return TableContent(text="\n".join(lines), headers=headers, rows=rows)


def _inspect_unit(unit: StructuralUnit) -> dict:
    content = unit.content
    payload: dict = {
        "unit_id": unit.unit_id,
        "structural_type": unit.structural_type,
        "title": unit.title,
        "hierarchy_path": list(unit.hierarchy_path),
        "page_start": unit.page_start,
        "page_end": unit.page_end,
        "content_kind": getattr(content, "kind", None),
        "text": content.text,
        "association_ids": [item.association_id for item in unit.spatial_associations],
        "region_ids": list(unit.structured_fields.get("region_ids") or []),
    }
    if isinstance(content, ListContent):
        payload["items"] = [{"ordinal": item.ordinal, "text": item.text} for item in content.items]
        payload["ordered"] = content.ordered
    if isinstance(content, TableContent):
        payload["headers"] = list(content.headers)
        payload["row_count"] = len(content.rows)
        payload["table_header_source"] = unit.structured_fields.get("table_header_source")
    return payload
