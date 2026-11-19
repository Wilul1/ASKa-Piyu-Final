"""Generic, document-agnostic geometric reconstruction over the Phase 6.21
spatial evidence contract (``PageGeometry``/``SpatialRegion`` in
:mod:`.types`).

This module ONLY produces :class:`~.types.SpatialAssociation` evidence. It
never rewrites, merges, deletes, or reorders the underlying extracted text,
and nothing downstream is required to treat an association as permission to
do any of those things either -- consistent with ``SpatialAssociation``'s
own docstring ("evidence of a relationship between ... regions ... nothing
... reads a SpatialAssociation as automatic permission to merge, reassign,
or reinterpret content").

Every reconstruction function here operates on already-extracted geometry
(word/table/cell bounding boxes PyMuPDF already returns) -- none of them
call into PyMuPDF themselves, parse a PDF, or add a new dependency. None of
them know anything about Citizen's Charter, Student Handbook, or any other
specific document: every signal used (vertical/horizontal adjacency, shared
left-margin alignment, trailing punctuation shape, column position, same
table/column membership) is a generic layout property any PDF can expose.

Confidence values produced here are a SIMPLE COUNT RATIO of concrete,
named boolean checks this module itself evaluated and documents below --
e.g. 0.67 means "2 of the 3 signals this specific function checks for this
specific candidate were present." It is NOT a calibrated probability, has
not been validated against any labeled outcome set, and must not be read
as "67% likely correct." Treat it only as an ordinal ranking signal within
this module's own output. Page-furniture associations use the same ordinal
rule in all-or-nothing form: ``confidence=1.0`` means the four required
checks (compact, edge, recurrence, template) all passed, not a measured
100% probability of correctness.

Nothing here is wired into any document profile's extraction DECISION
logic (e.g. ``citizen_charter_extractor_v2.py`` is untouched by this
module and does not import it). Associations produced here are exposed for
a shared structural-interpretation stage to consume LATER, if and when
that stage is built -- producing them today is additive and inert on its
own.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from .types import (
    EvidenceOrigin,
    PageGeometry,
    SpatialAssociation,
    SpatialRegion,
    SpatialRegionType,
    SpatialRelationKind,
)

# A line/cell "looks complete" (not an overflow continuation) when it ends
# with a sentence terminator or an explicit label colon. Generic punctuation
# shape, not a phrase/word list.
_SENTENCE_END_RE = re.compile(r"[.!?]\s*$")
_LABEL_COMPLETE_RE = re.compile(r":\s*$")

# Line-initial enumerator token: a list marker at the start of a line, not
# merely a digit or letter that happens to occur in running prose. Covers
# decimal/subsection markers, a single letter, or a parenthesized token,
# each closed by '.' or ')' (or already wrapped in parentheses). Generic
# token shape -- not a document-specific numbering scheme and not a phrase
# list. A wrap line that starts with a quantity ("18 hours...") does not
# match, because the digits are not closed by an enumerator delimiter.
_ENUMERATION_START_RE = re.compile(
    r"^(?:"
    r"\d+(?:\.\d+)*[.)]"
    r"|[A-Za-z][.)]"
    r"|\([0-9A-Za-z]+\)"
    r")(?:\s|$)"
)

# Generic, conservative defaults in PDF point units (1/72 inch), not tuned
# to any one document. Documented limitation (see module report): a
# page-relative or font-size-relative threshold would generalize better
# across very different page sizes/font scales; left as a fixed constant
# here since no current extractor exposes page dimensions reliably enough
# (see PageGeometry.width/height, both optional and usually None today) to
# compute a relative threshold from.
_LINE_ADJACENCY_MAX_GAP = 6.0
_HEADING_TABLE_MAX_GAP = 40.0
_SAME_COLUMN_X0_TOLERANCE = 3.0

# Phase 7.8 page-furniture detection. All four signals below are required
# together; any one of them alone is insufficient (repeated body tables,
# a one-off compact top table, or a first line near the edge must not
# become furniture). Thresholds are page-relative and document-agnostic.
# Observed coverage: Handbook chrome 198/198 and Faculty chrome 106/106
# pass; Charter service tables fail compactness; clusters under 3 pages
# or under half the supplied page list stay unclassified.
_FURNITURE_MAX_REL_HEIGHT = 0.15
_FURNITURE_EDGE_BAND = 0.12
_FURNITURE_REL_TOLERANCE = 0.03
_FURNITURE_WIDTH_TOLERANCE = 0.08
_FURNITURE_TOKEN_JACCARD = 0.7
_FURNITURE_MIN_PAGES = 3
_FURNITURE_MIN_PAGE_COVERAGE = 0.5
_FURNITURE_ASSOCIATION_PREFIX = "assoc:furniture:"
# Generic folio-like tokens (digits or roman numerals, optionally
# "N of M" / "N/M"). Not a phrase list; used only to compare templates
# whose printed page field varies.
_FOLIO_LIKE_TOKEN_RE = re.compile(
    r"\b(?:[ivxlcdm]+|\d+)(?:\s*(?:of|/)\s*(?:[ivxlcdm]+|\d+))?\b",
    re.IGNORECASE,
)
# Detector-local whole-line folio parser (Phase 7.18). Not a replacement
# for ``_FOLIO_LIKE_TOKEN_RE``, which remains table-template hygiene.
# Canonical Roman requires at least one numeral character so "" cannot match.
_CANONICAL_ROMAN_RE = re.compile(
    r"^(?=[IVXLCDM])M{0,3}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$",
    re.IGNORECASE,
)
_ARABIC_WHOLE_RE = re.compile(r"^\d+$")
_AMBIGUOUS_SINGLE_ROMAN = frozenset("ivxlcdm")


def _confidence(signals_met: int, signals_total: int) -> float | None:
    if signals_total <= 0:
        return None
    return round(signals_met / signals_total, 3)


@dataclass(frozen=True)
class _Line:
    """An internal, non-exported grouping of same-row WORD regions into one
    visual line -- a generic, reusable building block (not specific to any
    reconstruction capability above). Built purely from already-captured
    word bounding boxes; never invents a word or coordinate."""

    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    word_region_ids: tuple[str, ...]


def _group_words_into_lines(page: PageGeometry, y_tolerance: float = 2.5) -> list[_Line]:
    """Group WORD regions sharing the same approximate y-position into
    lines, preserving each word's own existing ``reading_order_index`` as
    the grouping/ordering key (never recomputed or re-sorted by this
    function beyond what extraction already determined)."""
    words = [
        r
        for r in page.regions
        if r.region_type == SpatialRegionType.WORD and r.bbox is not None
    ]
    words_sorted = sorted(
        words, key=lambda r: (r.reading_order_index if r.reading_order_index is not None else 0)
    )
    lines: list[_Line] = []
    current: list[SpatialRegion] = []
    current_y0: float | None = None
    for word in words_sorted:
        y0 = word.bbox[1]  # type: ignore[index]
        if current and current_y0 is not None and abs(y0 - current_y0) > y_tolerance:
            lines.append(_build_line(current))
            current = []
            current_y0 = None
        current.append(word)
        if current_y0 is None:
            current_y0 = y0
    if current:
        lines.append(_build_line(current))
    return lines


def _build_line(words: list[SpatialRegion]) -> _Line:
    text = " ".join(w.text for w in words)
    x0 = min(w.bbox[0] for w in words if w.bbox is not None)  # type: ignore[index]
    y0 = min(w.bbox[1] for w in words if w.bbox is not None)  # type: ignore[index]
    x1 = max(w.bbox[2] for w in words if w.bbox is not None)  # type: ignore[index]
    y1 = max(w.bbox[3] for w in words if w.bbox is not None)  # type: ignore[index]
    return _Line(
        text=text,
        x0=x0,
        y0=y0,
        x1=x1,
        y1=y1,
        word_region_ids=tuple(w.region_id for w in words),
    )


def _boxes_overlap_positive_area(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> bool:
    """True when two axis-aligned boxes share a positive-area interior.

    Horizontal and vertical overlap are both required. Edge- or
    corner-touching (overlap length 0 on either axis) is not intersection.
    """
    x_overlap = min(a[2], b[2]) - max(a[0], b[0])
    y_overlap = min(a[3], b[3]) - max(a[1], b[1])
    return x_overlap > 0 and y_overlap > 0


def _line_bbox(line: _Line) -> tuple[float, float, float, float]:
    return (line.x0, line.y0, line.x1, line.y1)


def _line_intersects_any_table(line: _Line, tables: list[SpatialRegion]) -> bool:
    """True when the line's box has positive-area overlap with any table."""
    box = _line_bbox(line)
    return any(
        table.bbox is not None and _boxes_overlap_positive_area(box, table.bbox) for table in tables
    )


def _heading_table_corridor(
    line: _Line, table_bbox: tuple[float, float, float, float]
) -> tuple[float, float, float, float] | None:
    """Axis-aligned corridor from a candidate line down to a target table.

    Vertical extent is the open gap between the line's bottom and the
    table's top. Horizontal extent is the overlap of their x-ranges --
    the path that stays in both the heading column and the table column.
    ``None`` when that rectangle has no positive area (no x-overlap, or
    the line is not strictly above the table).
    """
    x0 = max(line.x0, table_bbox[0])
    x1 = min(line.x1, table_bbox[2])
    y0 = line.y1
    y1 = table_bbox[1]
    if x1 <= x0 or y1 <= y0:
        return None
    return (x0, y0, x1, y1)


def _intervening_tables(
    line: _Line, target: SpatialRegion, tables: list[SpatialRegion]
) -> list[SpatialRegion]:
    """Other tables whose boxes occupy the candidate-to-target corridor.

    The target itself is never intervening. A horizontally separate table
    that merely shares vertical coordinates with the gap does not occupy
    the corridor unless it also overlaps the corridor in x.
    """
    if target.bbox is None:
        return []
    corridor = _heading_table_corridor(line, target.bbox)
    if corridor is None:
        return []
    found: list[SpatialRegion] = []
    for table in tables:
        if table.region_id == target.region_id or table.bbox is None:
            continue
        if _boxes_overlap_positive_area(table.bbox, corridor):
            found.append(table)
    return found


def _looks_incomplete(text: str) -> bool:
    """True when ``text`` does NOT already end in a sentence terminator or
    an explicit label colon -- i.e. it plausibly continues onto the next
    line/cell rather than standing complete on its own."""
    stripped = text.strip()
    return bool(stripped) and not _SENTENCE_END_RE.search(stripped) and not _LABEL_COMPLETE_RE.search(stripped)


def _looks_like_completion(a_text: str, b_text: str) -> bool:
    """True when ``b_text`` itself ends in a label colon, or the two texts
    joined end in one -- i.e. ``b`` plausibly completes a label ``a``
    started."""
    combined = f"{a_text.strip()} {b_text.strip()}".strip()
    return bool(_LABEL_COMPLETE_RE.search(b_text.strip())) or bool(_LABEL_COMPLETE_RE.search(combined))


def _starts_enumerated_item(text: str) -> bool:
    """True when ``text`` begins with a generic enumeration marker.

    Used as a continuation *precondition*, not as a scored signal: a
    following line that opens a new enumerated item is independently
    supported content, not a wrap of the preceding line. This does not
    treat every line containing digits as a new item, and it does not
    treat every unnumbered line as a wrap.
    """
    stripped = (text or "").strip()
    return bool(stripped) and bool(_ENUMERATION_START_RE.match(stripped))


def _isolated_from_same_page_neighbor(line: _Line, neighbor: _Line | None) -> bool:
    """True when ``line`` is detached from its nearest same-page neighbor
    both vertically and horizontally -- the generic layout signature of
    running page furniture (a folio, a running header) rather than a
    wrapped content line.

    Reuses the module's existing adjacency/column tolerances. A sole line
    on the page has no neighbor and is therefore not classified as
    furniture (insufficient evidence). A numeric line that shares a
    column with adjacent body text is not classified as furniture either
    -- numbered content must remain eligible for continuation.
    """
    if neighbor is None:
        return False
    if line.y0 >= neighbor.y1:
        gap = line.y0 - neighbor.y1
    elif neighbor.y0 >= line.y1:
        gap = neighbor.y0 - line.y1
    else:
        return False
    if gap <= _LINE_ADJACENCY_MAX_GAP:
        return False
    if abs(line.x0 - neighbor.x0) <= _SAME_COLUMN_X0_TOLERANCE:
        return False
    return True


# ---------------------------------------------------------------------------
# A. Region relationship detection -- label/value and continuation pairs.
# ---------------------------------------------------------------------------


def reconstruct_line_label_continuations(page: PageGeometry) -> list[SpatialAssociation]:
    """Candidate label-continuation pairs reconstructed from WORD-level
    geometry of ordinary flowing text -- e.g. a label whose second half
    wraps onto its own line. Lines that intersect a native table region
    are ineligible; table-cell continuation is a separate function.

    Evidence signals evaluated per adjacent line pair (a, b), b following a:
    1. Table membership: neither ``a`` nor ``b`` may have a positive-area
       bounding-box intersection with any TABLE region on the page.
       Table-contained text is not ordinary prose continuation; the
       table-cell path owns reconstructable cell wraps. Edge-touching a
       table is not interior overlap. A horizontally separate table does
       not exclude a line. This is a PRECONDITION on both endpoints.
    2. Vertical adjacency: the gap between a's bottom and b's top is small
       (<= ``_LINE_ADJACENCY_MAX_GAP``) -- i.e. they are visually one
       wrapped unit, not separated by a paragraph gap. This signal is a
       PRECONDITION: pairs failing it are not considered candidates at all
       (no association, strong or unresolved, is produced).
    3. Independent enumerated start on ``b``: if ``b`` begins with a
       generic enumeration marker, ``b`` is a new content item, not a wrap
       of ``a``. This is also a PRECONDITION -- no association is produced
       (not even ``MISSING``). Numbering on ``a`` is not used this way:
       an enumerated line may still wrap onto an unnumbered overflow line
       when the remaining signals support it.
    4. Shared left margin: both lines start at approximately the same x0
       (<= ``_SAME_COLUMN_X0_TOLERANCE``) -- consistent with a label
       wrapping under itself, not a new, differently-indented paragraph.
    5. ``a`` looks incomplete (no trailing sentence/label punctuation).
    6. ``b`` (or the combined text) looks like a label completion (ends in
       ':').

    Of signals 4-6 (preconditions 1-3 are mandatory), >=2 produces a
    ``LAYOUT_RECONSTRUCTED`` association; exactly 1 produces a ``MISSING``
    (unresolved/ambiguous) association so the near-miss stays visible
    rather than silently vanishing; 0 produces nothing."""
    lines = _group_words_into_lines(page)
    tables = [
        region
        for region in page.regions
        if region.region_type == SpatialRegionType.TABLE and region.bbox is not None
    ]
    associations: list[SpatialAssociation] = []
    for a, b in zip(lines, lines[1:]):
        if _line_intersects_any_table(a, tables) or _line_intersects_any_table(b, tables):
            continue  # table-contained text is not ordinary line continuation
        gap = b.y0 - a.y1
        if gap < 0 or gap > _LINE_ADJACENCY_MAX_GAP:
            continue  # precondition failed -- not even a weak candidate
        if _starts_enumerated_item(b.text):
            continue  # b is independently numbered content, not a wrap of a
        signals = 0
        if abs(a.x0 - b.x0) <= _SAME_COLUMN_X0_TOLERANCE:
            signals += 1
        if _looks_incomplete(a.text):
            signals += 1
        if _looks_like_completion(a.text, b.text):
            signals += 1
        total = 3
        if signals == 0:
            continue
        origin = EvidenceOrigin.LAYOUT_RECONSTRUCTED if signals >= 2 else EvidenceOrigin.MISSING
        note = (
            f"Candidate label continuation: {a.text!r} + {b.text!r}"
            if signals >= 2
            else f"Weak/ambiguous candidate (insufficient evidence, left unresolved): {a.text!r} + {b.text!r}"
        )
        associations.append(
            SpatialAssociation(
                association_id=f"assoc:line:{a.word_region_ids[0]}:{b.word_region_ids[0]}",
                region_ids=[*a.word_region_ids, *b.word_region_ids],
                kind=SpatialRelationKind.CONTINUATION,
                origin=origin,
                confidence=_confidence(signals, total),
                note=note,
            )
        )
    return associations


def reconstruct_table_label_continuations(page: PageGeometry) -> list[SpatialAssociation]:
    """Candidate label-continuation pairs reconstructed from native TABLE
    cell geometry: a cell and the next row's cell in the SAME column,
    where the first looks like an incomplete label.

    Evidence signals per adjacent same-column cell pair (a at row r, b at
    row r+1), both non-empty (precondition). Note that "``a`` has no
    trailing punctuation" is deliberately NOT counted as a signal here --
    nearly every short table cell (e.g. an ordinary "Name"/"Office" header
    word) lacks trailing punctuation, so that alone is not discriminating
    evidence and would otherwise flag ordinary unrelated header/data rows
    as false "weak" candidates (caught by this module's own test suite):
    1. ``b`` (or the combined text) looks like a label completion (ends
       in ':').
    2. Every OTHER column in row r+1 is non-empty-checked and found empty
       -- consistent with row r+1 being an overflow/continuation row
       rather than a fresh row of its own independent data.

    Both signals produces ``LAYOUT_RECONSTRUCTED``; exactly 1 produces
    ``MISSING`` (unresolved); 0 produces nothing at all (not even a weak
    candidate -- e.g. an ordinary two-row data pair with neither signal
    is not evidence of anything). Never fabricates a cell boundary --
    only inspects cells the extractor already produced."""
    cells = [r for r in page.regions if r.region_type == SpatialRegionType.CELL]
    if not cells:
        return []

    def _table_id(region_id: str) -> str:
        return region_id.split(":cell:")[0]

    by_table_col: dict[tuple[str, int], dict[int, SpatialRegion]] = {}
    by_table_row: dict[tuple[str, int], list[SpatialRegion]] = {}
    for cell in cells:
        if cell.row is None or cell.column is None:
            continue
        table_id = _table_id(cell.region_id)
        by_table_col.setdefault((table_id, cell.column), {})[cell.row] = cell
        by_table_row.setdefault((table_id, cell.row), []).append(cell)

    associations: list[SpatialAssociation] = []
    for (table_id, column), rows_by_index in by_table_col.items():
        for row_index, a in rows_by_index.items():
            b = rows_by_index.get(row_index + 1)
            if b is None or not a.text.strip() or not b.text.strip():
                continue
            signals = 0
            if _looks_like_completion(a.text, b.text):
                signals += 1
            siblings = [c for c in by_table_row.get((table_id, row_index + 1), []) if c.column != column]
            if siblings and all(not c.text.strip() for c in siblings):
                signals += 1
            total = 2
            if signals == 0:
                continue
            origin = EvidenceOrigin.LAYOUT_RECONSTRUCTED if signals >= 2 else EvidenceOrigin.MISSING
            note = (
                f"Candidate table-cell label continuation: {a.text!r} + {b.text!r}"
                if signals >= 2
                else f"Weak/ambiguous candidate (insufficient evidence, left unresolved): {a.text!r} + {b.text!r}"
            )
            associations.append(
                SpatialAssociation(
                    association_id=f"assoc:cell:{a.region_id}:{b.region_id}",
                    region_ids=[a.region_id, b.region_id],
                    kind=SpatialRelationKind.CONTINUATION,
                    origin=origin,
                    confidence=_confidence(signals, total),
                    note=note,
                )
            )
    return associations


# ---------------------------------------------------------------------------
# B/E. Heading-to-table association via vertical proximity + uniqueness.
# ---------------------------------------------------------------------------


def reconstruct_heading_to_table(page: PageGeometry) -> list[SpatialAssociation]:
    """Associate a text line with a TABLE region below it from geometry
    already on ``PageGeometry`` -- never by assuming the nearest line is
    a heading.

    Eligibility (precondition): the line is strictly above the table
    (``line.y1 <= table.y0``, so a top-edge touch remains eligible),
    shares a positive-width column with the target (horizontal overlap),
    AND its bounding box has no positive-area intersection with ANY table
    on the page. Text inside the target table, or inside another table
    (running-header chrome, table-internal cells), cannot own a table.
    Edge-touching a table is not interior overlap. A side table that
    only shares the line's y-range does not by itself exclude the line.

    Intervening table (precondition): another table blocks the pair only
    when its box has positive-area intersection with the candidate-to-
    target corridor (vertical gap × horizontal overlap of the line and
    the target). A horizontally separate table that merely shares y-
    coordinates with the gap does not block. The target itself is never
    intervening.

    Selection among remaining eligible lines:
    * zero -- no association.
    * one -- existing distance behavior: gap ``<= _HEADING_TABLE_MAX_GAP``
      yields ``LAYOUT_RECONSTRUCTED``; a farther unique pair yields
      ``MISSING`` (unresolved), not a silent drop.
    * more than one inside the distance bound -- do not confirm the
      nearest line at confidence 1.0. One ``MISSING`` association records
      the unresolved set. Multiple candidates all beyond the bound are
      withheld (no defensible single unresolved owner).
    """
    lines = _group_words_into_lines(page)
    tables = [r for r in page.regions if r.region_type == SpatialRegionType.TABLE and r.bbox is not None]
    associations: list[SpatialAssociation] = []
    for table in tables:
        table_top = table.bbox[1]  # type: ignore[index]
        eligible: list[_Line] = []
        for line in lines:
            if line.y1 > table_top:
                continue
            if min(line.x1, table.bbox[2]) - max(line.x0, table.bbox[0]) <= 0:  # type: ignore[index]
                continue  # no shared column with this target
            if _line_intersects_any_table(line, tables):
                continue
            if _intervening_tables(line, table, tables):
                continue
            eligible.append(line)
        if not eligible:
            continue
        within = [line for line in eligible if (table_top - line.y1) <= _HEADING_TABLE_MAX_GAP]
        beyond = [line for line in eligible if (table_top - line.y1) > _HEADING_TABLE_MAX_GAP]
        if len(within) == 1:
            chosen = within[0]
            gap = table_top - chosen.y1
            associations.append(
                SpatialAssociation(
                    association_id=f"assoc:heading:{chosen.word_region_ids[0]}:{table.region_id}",
                    region_ids=[*chosen.word_region_ids, table.region_id],
                    kind=SpatialRelationKind.HEADING_TO_TABLE,
                    origin=EvidenceOrigin.LAYOUT_RECONSTRUCTED,
                    confidence=1.0,
                    note=(
                        f"Nearest line above table, no intervening table "
                        f"(gap={gap:.1f}pt): {chosen.text!r}"
                    ),
                )
            )
            continue
        if len(within) > 1:
            region_ids = [rid for line in within for rid in line.word_region_ids]
            texts = "; ".join(repr(line.text) for line in within)
            associations.append(
                SpatialAssociation(
                    association_id=f"assoc:heading:ambiguous:{table.region_id}",
                    region_ids=[*region_ids, table.region_id],
                    kind=SpatialRelationKind.HEADING_TO_TABLE,
                    origin=EvidenceOrigin.MISSING,
                    confidence=None,
                    note=(
                        "Multiple eligible heading lines above table, left "
                        f"unresolved: {texts}"
                    ),
                )
            )
            continue
        if len(beyond) == 1:
            chosen = beyond[0]
            gap = table_top - chosen.y1
            associations.append(
                SpatialAssociation(
                    association_id=f"assoc:heading:{chosen.word_region_ids[0]}:{table.region_id}",
                    region_ids=[*chosen.word_region_ids, table.region_id],
                    kind=SpatialRelationKind.HEADING_TO_TABLE,
                    origin=EvidenceOrigin.MISSING,
                    confidence=None,
                    note=(
                        "Nearest-and-unique, but gap exceeds generic bound "
                        f"(gap={gap:.1f}pt), left unresolved: {chosen.text!r}"
                    ),
                )
            )
    return associations


# ---------------------------------------------------------------------------
# C2. Recurring page furniture -- evidence only, never source-text deletion.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _FurnitureCandidate:
    page_number: int
    table: SpatialRegion
    rel_y0: float
    rel_y1: float
    rel_h: float
    rel_w: float
    n_rows: int
    n_cols: int
    tokens: frozenset[str]


def _page_size(page: PageGeometry) -> tuple[float, float] | None:
    """Return (width, height) in the region's coordinate space, or None.

    Prefers width/height. Falls back to coordinate_width/height when both
    are present. Never estimates size from word boxes.
    """
    width = page.width if page.width else page.coordinate_width
    height = page.height if page.height else page.coordinate_height
    if width is None or height is None or width <= 0 or height <= 0:
        return None
    return (float(width), float(height))


def _table_shape(page: PageGeometry, table: SpatialRegion) -> tuple[int, int]:
    prefix = f"{table.region_id}:cell:"
    rows: set[int] = set()
    cols: set[int] = set()
    for region in page.regions:
        if region.region_type != SpatialRegionType.CELL:
            continue
        if not region.region_id.startswith(prefix):
            continue
        if region.row is not None:
            rows.add(region.row)
        if region.column is not None:
            cols.add(region.column)
    if rows and cols:
        return (len(rows), len(cols))
    text_rows = [line for line in (table.text or "").split("\n") if line.strip()]
    n_rows = len(text_rows)
    n_cols = max((len(line.split("|")) for line in text_rows), default=0)
    return (n_rows, n_cols)


def _stable_template_tokens(text: str) -> frozenset[str]:
    """Letter tokens remaining after generic folio-like numbers are removed."""
    cleaned = _FOLIO_LIKE_TOKEN_RE.sub(" ", text or "")
    return frozenset(re.findall(r"[a-z]+", cleaned.casefold()))


def _token_jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _is_compact_edge_table(rel_y0: float, rel_y1: float, rel_h: float) -> bool:
    if rel_h <= 0 or rel_h > _FURNITURE_MAX_REL_HEIGHT:
        return False
    at_top = rel_y0 <= _FURNITURE_EDGE_BAND
    at_bottom = rel_y1 >= (1.0 - _FURNITURE_EDGE_BAND)
    return at_top or at_bottom


def _furniture_candidates(page: PageGeometry) -> list[_FurnitureCandidate]:
    size = _page_size(page)
    if size is None:
        return []
    width, height = size
    found: list[_FurnitureCandidate] = []
    for region in page.regions:
        if region.region_type != SpatialRegionType.TABLE or region.bbox is None:
            continue
        x0, y0, x1, y1 = region.bbox
        rel_h = (y1 - y0) / height
        rel_y0 = y0 / height
        rel_y1 = y1 / height
        rel_w = (x1 - x0) / width
        if not _is_compact_edge_table(rel_y0, rel_y1, rel_h):
            continue
        n_rows, n_cols = _table_shape(page, region)
        found.append(
            _FurnitureCandidate(
                page_number=page.page_number,
                table=region,
                rel_y0=rel_y0,
                rel_y1=rel_y1,
                rel_h=rel_h,
                rel_w=rel_w,
                n_rows=n_rows,
                n_cols=n_cols,
                tokens=_stable_template_tokens(region.text),
            )
        )
    return found


def _same_furniture_geometry(a: _FurnitureCandidate, b: _FurnitureCandidate) -> bool:
    if a.n_rows != b.n_rows or a.n_cols != b.n_cols:
        return False
    if abs(a.rel_y0 - b.rel_y0) > _FURNITURE_REL_TOLERANCE:
        return False
    if abs(a.rel_h - b.rel_h) > _FURNITURE_REL_TOLERANCE:
        return False
    if abs(a.rel_w - b.rel_w) > _FURNITURE_WIDTH_TOLERANCE:
        return False
    return _token_jaccard(a.tokens, b.tokens) >= _FURNITURE_TOKEN_JACCARD


def _cluster_furniture(candidates: list[_FurnitureCandidate]) -> list[list[_FurnitureCandidate]]:
    parent = list(range(len(candidates)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    for i, left in enumerate(candidates):
        for j in range(i + 1, len(candidates)):
            if _same_furniture_geometry(left, candidates[j]):
                union(i, j)
    groups: dict[int, list[_FurnitureCandidate]] = {}
    for i, candidate in enumerate(candidates):
        groups.setdefault(find(i), []).append(candidate)
    return list(groups.values())


def _furniture_subtype(cluster: list[_FurnitureCandidate]) -> str:
    top = all(member.rel_y0 <= _FURNITURE_EDGE_BAND for member in cluster)
    bottom = all(member.rel_y1 >= (1.0 - _FURNITURE_EDGE_BAND) for member in cluster)
    if top and not bottom:
        return "header"
    if bottom and not top:
        return "footer"
    return "unknown"


def _furniture_group_id(cluster: list[_FurnitureCandidate], subtype: str) -> str:
    """Content-addressed reconstruction-run identifier, not a persistent key.

    Guarantees (confirmed from this function):
    - Deterministic for identical prototype inputs.
    - Derived from the lowest ``(page_number, region_id)`` member, rounded
      relative geometry, that member's token set, and subtype -- not from
      notes and not from the full member list.
    - Not scoped to a document identifier; two documents with the same
      prototype shape/tokens/band can produce the same digest.
    - Not guaranteed stable when the supplied page subset changes the
      prototype member, nor unique across distinct groups in the
      cryptographic sense (12 hex chars, truncated SHA-256).
    - Not suitable as a durable cross-run catalog key.
    """
    prototype = sorted(cluster, key=lambda m: (m.page_number, m.table.region_id))[0]
    material = "|".join(
        [
            str(prototype.n_rows),
            str(prototype.n_cols),
            f"{round(prototype.rel_y0, 2):.2f}",
            f"{round(prototype.rel_h, 2):.2f}",
            ",".join(sorted(prototype.tokens)),
            subtype,
        ]
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:12]
    return digest


def is_page_furniture_association(association: SpatialAssociation) -> bool:
    """True for a Phase 7.8/7.10 page-furniture recurrence group.

    Requires both ``kind is PAGE_FURNITURE`` and an ``association_id``
    starting with ``assoc:furniture:``. Identity is not read from ``note``.
    """
    return (
        association.kind == SpatialRelationKind.PAGE_FURNITURE
        and association.association_id.startswith(_FURNITURE_ASSOCIATION_PREFIX)
    )


def furniture_group_id(association: SpatialAssociation) -> str | None:
    """Machine-readable recurrence-group digest, or None if not furniture.

    See ``_furniture_group_id`` for uniqueness and stability limits. The
    value is parsed from ``association_id``, never from ``note``.
    """
    if not is_page_furniture_association(association):
        return None
    rest = association.association_id[len(_FURNITURE_ASSOCIATION_PREFIX) :]
    return rest.split(":", 1)[0] or None


def furniture_region_ids_on_page(
    page: PageGeometry,
    associations: list[SpatialAssociation],
) -> tuple[str, ...]:
    """Furniture member region IDs that actually exist on ``page``.

    Membership is resolved by matching ``SpatialAssociation.region_ids``
    against ``page.regions`` by ``region_id``. Adapter ID formatting is
    not parsed. Multiple furniture groups on the same page are included.
    Unrelated kinds, missing associations, empty pages, and member IDs
    that are not present on ``page`` are omitted. Result is sorted and
    unique.
    """
    page_ids = {region.region_id for region in page.regions}
    if not page_ids:
        return ()
    found: set[str] = set()
    for association in associations:
        if not is_page_furniture_association(association):
            continue
        if association.origin != EvidenceOrigin.LAYOUT_RECONSTRUCTED:
            continue
        for region_id in association.region_ids:
            if region_id in page_ids:
                found.add(region_id)
    return tuple(sorted(found))


def reconstruct_page_furniture(pages: list[PageGeometry]) -> list[SpatialAssociation]:
    """High-confidence recurring page furniture across ``pages``.

    Operates on compact, edge-adjacent TABLE regions. Emits one
    ``SpatialAssociation`` per recurrence group with
    ``kind=PAGE_FURNITURE``. Identity is ``association_id``
    (``assoc:furniture:{group_id}:{header|footer|unknown}``), never
    ``note``. ``confidence=1.0`` is the deterministic acceptance policy
    (all required checks passed), not a calibrated probability. Source
    WORD/TABLE/CELL regions are not modified. Ambiguous clusters produce
    nothing.
    """
    pages_sorted = sorted(pages, key=lambda p: p.page_number)
    n_pages = len(pages_sorted)
    if n_pages < _FURNITURE_MIN_PAGES:
        return []
    candidates: list[_FurnitureCandidate] = []
    for page in pages_sorted:
        candidates.extend(_furniture_candidates(page))
    associations: list[SpatialAssociation] = []
    for cluster in _cluster_furniture(candidates):
        page_numbers = {member.page_number for member in cluster}
        coverage = len(page_numbers) / n_pages
        if len(page_numbers) < _FURNITURE_MIN_PAGES:
            continue
        if coverage < _FURNITURE_MIN_PAGE_COVERAGE:
            continue
        subtype = _furniture_subtype(cluster)
        group_id = _furniture_group_id(cluster, subtype)
        members = sorted(cluster, key=lambda m: (m.page_number, m.table.region_id))
        region_ids = [member.table.region_id for member in members]
        associations.append(
            SpatialAssociation(
                association_id=f"{_FURNITURE_ASSOCIATION_PREFIX}{group_id}:{subtype}",
                region_ids=region_ids,
                kind=SpatialRelationKind.PAGE_FURNITURE,
                origin=EvidenceOrigin.LAYOUT_RECONSTRUCTED,
                # 1.0 = all four required checks passed (compact, edge,
                # recurrence, template). Not a calibrated probability.
                confidence=1.0,
                note=(
                    f"Page furniture recurrence group {group_id} ({subtype}): "
                    f"{len(region_ids)} tables on {len(page_numbers)}/{n_pages} pages "
                    f"(coverage={coverage:.3f}); signals=compact+edge+recurrence+template"
                ),
            )
        )
    return associations


# ---------------------------------------------------------------------------
# C2b. Text-only (WORD) page furniture -- standalone producer.
# Does not modify table detection, continuation endpoints, or source text.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _FolioParse:
    """Detector-local whole-line folio parse. ``current`` is the page field."""

    kind: str
    current: int
    total: int | None
    ambiguous_single_roman: bool


@dataclass(frozen=True)
class _TextFurnitureCandidate:
    page_number: int
    line: _Line
    rel_y0: float
    rel_y1: float
    rel_h: float
    rel_w: float
    letter_tokens: frozenset[str]
    establishing: bool
    folio: _FolioParse | None = None


def _letter_tokens_no_folio_strip(text: str) -> frozenset[str]:
    """Letter tokens of ``text`` without stripping numeric/folio fields."""
    return frozenset(re.findall(r"[a-z]+", (text or "").casefold()))


def _roman_to_int(text: str) -> int | None:
    if not _CANONICAL_ROMAN_RE.fullmatch(text or ""):
        return None
    values = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    total = 0
    previous = 0
    for char in reversed(text.upper()):
        value = values[char]
        if value < previous:
            total -= value
        else:
            total += value
            previous = value
    return total


def _parse_folio_unit(text: str) -> tuple[int, bool] | None:
    """Return ``(value, ambiguous_single_roman)`` or ``None``."""
    raw = (text or "").strip()
    if not raw:
        return None
    if _ARABIC_WHOLE_RE.fullmatch(raw):
        return int(raw), False
    if not _CANONICAL_ROMAN_RE.fullmatch(raw):
        return None
    value = _roman_to_int(raw)
    if value is None:
        return None
    ambiguous = raw.casefold() in _AMBIGUOUS_SINGLE_ROMAN and len(raw) == 1
    return value, ambiguous


def parse_text_folio_line(text: str) -> _FolioParse | None:
    """Parse a whole grouped line as a folio. Empty input is not a folio.

    Detector-local. Does not use ``_FOLIO_LIKE_TOKEN_RE``.
    """
    raw = (text or "").strip()
    if not raw:
        return None
    rest = raw
    if rest.casefold().startswith("page "):
        rest = rest[5:].strip()
        if not rest:
            return None
    of_parts = re.split(r"\s+of\s+", rest, maxsplit=1, flags=re.IGNORECASE)
    if len(of_parts) == 2:
        return _folio_parse_pair(of_parts[0], of_parts[1], kind="n_of_m")
    if "/" in rest:
        left, right = rest.split("/", 1)
        return _folio_parse_pair(left, right, kind="n_of_m")
    unit = _parse_folio_unit(rest)
    if unit is None:
        return None
    current, ambiguous = unit
    kind = "arabic" if _ARABIC_WHOLE_RE.fullmatch(rest.strip()) else "roman"
    return _FolioParse(
        kind=kind,
        current=current,
        total=None,
        ambiguous_single_roman=ambiguous,
    )


def _folio_parse_pair(left: str, right: str, *, kind: str) -> _FolioParse | None:
    left_parsed = _parse_folio_unit(left.strip())
    right_parsed = _parse_folio_unit(right.strip())
    if left_parsed is None or right_parsed is None:
        return None
    current, left_ambiguous = left_parsed
    total, right_ambiguous = right_parsed
    return _FolioParse(
        kind=kind,
        current=current,
        total=total,
        ambiguous_single_roman=left_ambiguous or right_ambiguous,
    )


def _enumerator_with_remaining_content(text: str) -> bool:
    if not _starts_enumerated_item(text):
        return False
    return bool(_letter_tokens_no_folio_strip(text))


def _non_table_lines(page: PageGeometry) -> list[_Line]:
    tables = [
        region
        for region in page.regions
        if region.region_type == SpatialRegionType.TABLE and region.bbox is not None
    ]
    return [
        line
        for line in _group_words_into_lines(page)
        if not _line_intersects_any_table(line, tables)
    ]


def _text_line_geometry(
    line: _Line, width: float, height: float
) -> tuple[float, float, float, float]:
    rel_y0 = line.y0 / height
    rel_y1 = line.y1 / height
    rel_h = (line.y1 - line.y0) / height
    rel_w = (line.x1 - line.x0) / width
    return rel_y0, rel_y1, rel_h, rel_w


def _same_text_furniture_geometry(
    left: _TextFurnitureCandidate,
    right: _TextFurnitureCandidate,
    *,
    require_text: bool,
) -> bool:
    if abs(left.rel_y0 - right.rel_y0) > _FURNITURE_REL_TOLERANCE:
        return False
    if abs(left.rel_h - right.rel_h) > _FURNITURE_REL_TOLERANCE:
        return False
    if abs(left.rel_w - right.rel_w) > _FURNITURE_WIDTH_TOLERANCE:
        return False
    if not require_text:
        return True
    if left.line.text.casefold() == right.line.text.casefold():
        return True
    return _token_jaccard(left.letter_tokens, right.letter_tokens) >= _FURNITURE_TOKEN_JACCARD


def _cluster_text_furniture(
    candidates: list[_TextFurnitureCandidate],
    *,
    require_text: bool,
) -> list[list[_TextFurnitureCandidate]]:
    parent = list(range(len(candidates)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            parent[root_right] = root_left

    for i, first in enumerate(candidates):
        for j in range(i + 1, len(candidates)):
            if _same_text_furniture_geometry(first, candidates[j], require_text=require_text):
                union(i, j)
    groups: dict[int, list[_TextFurnitureCandidate]] = {}
    for i, candidate in enumerate(candidates):
        groups.setdefault(find(i), []).append(candidate)
    return list(groups.values())


def _text_furniture_group_id(cluster: list[_TextFurnitureCandidate], role: str) -> str:
    """Content-addressed WORD furniture digest. Includes ``word`` and role."""
    prototype = sorted(
        cluster, key=lambda member: (member.page_number, member.line.word_region_ids[0])
    )[0]
    material = "|".join(
        [
            "word",
            f"{round(prototype.rel_y0, 2):.2f}",
            f"{round(prototype.rel_h, 2):.2f}",
            ",".join(sorted(prototype.letter_tokens)),
            role,
        ]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:12]


def _meets_text_recurrence(page_numbers: set[int], n_pages: int) -> bool:
    if n_pages < _FURNITURE_MIN_PAGES:
        return False
    if len(page_numbers) < _FURNITURE_MIN_PAGES:
        return False
    return (len(page_numbers) / n_pages) >= _FURNITURE_MIN_PAGE_COVERAGE


def _make_text_candidate(
    page_number: int,
    line: _Line,
    width: float,
    height: float,
    *,
    establishing: bool,
    folio: _FolioParse | None = None,
) -> _TextFurnitureCandidate:
    rel_y0, rel_y1, rel_h, rel_w = _text_line_geometry(line, width, height)
    return _TextFurnitureCandidate(
        page_number=page_number,
        line=line,
        rel_y0=rel_y0,
        rel_y1=rel_y1,
        rel_h=rel_h,
        rel_w=rel_w,
        letter_tokens=_letter_tokens_no_folio_strip(line.text),
        establishing=establishing,
        folio=folio,
    )


def _collect_text_furniture_candidates(
    pages: list[PageGeometry],
) -> tuple[
    list[_TextFurnitureCandidate],
    list[_TextFurnitureCandidate],
    list[_TextFurnitureCandidate],
    list[_TextFurnitureCandidate],
    list[_TextFurnitureCandidate],
    list[_TextFurnitureCandidate],
]:
    """Return establishing and sparse-join pools for header, footer, folio."""
    headers: list[_TextFurnitureCandidate] = []
    headers_sparse: list[_TextFurnitureCandidate] = []
    footers: list[_TextFurnitureCandidate] = []
    footers_sparse: list[_TextFurnitureCandidate] = []
    folios: list[_TextFurnitureCandidate] = []
    folios_sparse: list[_TextFurnitureCandidate] = []
    for page in pages:
        size = _page_size(page)
        if size is None:
            continue
        width, height = size
        lines = _non_table_lines(page)
        if not lines:
            continue
        first = lines[0]
        first_neighbor = lines[1] if len(lines) > 1 else None
        first_detached = _isolated_from_same_page_neighbor(first, first_neighbor)
        header_candidate = _make_text_candidate(
            page.page_number,
            first,
            width,
            height,
            establishing=first_detached,
        )
        if first_detached:
            headers.append(header_candidate)
        elif first_neighbor is None:
            headers_sparse.append(header_candidate)

        last = lines[-1]
        last_folio = parse_text_folio_line(last.text)
        last_is_folio_shape = (
            last_folio is not None
            and not last_folio.ambiguous_single_roman
            and not _enumerator_with_remaining_content(last.text)
        )
        last_two = lines[-2:] if len(lines) >= 2 else lines[-1:]
        for index, line in enumerate(last_two):
            global_index = len(lines) - len(last_two) + index
            inward = lines[global_index - 1] if global_index > 0 else None
            detached = _isolated_from_same_page_neighbor(line, inward)
            parsed = parse_text_folio_line(line.text)
            folio_shaped = parsed is not None
            if folio_shaped:
                continue
            candidate = _make_text_candidate(
                page.page_number,
                line,
                width,
                height,
                establishing=detached,
            )
            if detached:
                footers.append(candidate)
            elif inward is None:
                footers_sparse.append(candidate)

        # Folio: last non-table line, including footer/folio stack.
        if last_is_folio_shape:
            inward = lines[-2] if len(lines) > 1 else None
            rel_y0, rel_y1, rel_h, rel_w = _text_line_geometry(last, width, height)
            in_bottom_band = rel_y1 >= (1.0 - _FURNITURE_EDGE_BAND)
            if in_bottom_band:
                candidate = _make_text_candidate(
                    page.page_number,
                    last,
                    width,
                    height,
                    establishing=inward is not None,
                    folio=last_folio,
                )
                if inward is not None:
                    folios.append(candidate)
                else:
                    folios_sparse.append(candidate)
    return headers, headers_sparse, footers, footers_sparse, folios, folios_sparse


def _emit_text_furniture_groups(
    establishing: list[_TextFurnitureCandidate],
    sparse: list[_TextFurnitureCandidate],
    *,
    role: str,
    n_pages: int,
    require_text: bool,
    require_folio_variation: bool,
) -> list[SpatialAssociation]:
    associations: list[SpatialAssociation] = []
    for cluster in _cluster_text_furniture(establishing, require_text=require_text):
        establishing_pages = {member.page_number for member in cluster}
        if not _meets_text_recurrence(establishing_pages, n_pages):
            continue
        if require_folio_variation:
            values = {member.folio.current for member in cluster if member.folio is not None}
            if len(values) < 2:
                continue
        members = list(cluster)
        for extra in sparse:
            if extra.page_number in {member.page_number for member in members}:
                continue
            if any(
                _same_text_furniture_geometry(extra, member, require_text=require_text)
                for member in cluster
            ):
                if require_folio_variation and extra.folio is None:
                    continue
                members.append(extra)
        page_numbers = {member.page_number for member in members}
        members.sort(key=lambda member: (member.page_number, member.line.word_region_ids[0]))
        region_ids = [rid for member in members for rid in member.line.word_region_ids]
        group_id = _text_furniture_group_id(cluster, role)
        associations.append(
            SpatialAssociation(
                association_id=f"{_FURNITURE_ASSOCIATION_PREFIX}{group_id}:{role}",
                region_ids=region_ids,
                kind=SpatialRelationKind.PAGE_FURNITURE,
                origin=EvidenceOrigin.LAYOUT_RECONSTRUCTED,
                confidence=1.0,
                note=(
                    f"Text page furniture recurrence group {group_id} ({role}): "
                    f"{len(members)} lines on {len(page_numbers)}/{n_pages} pages "
                    f"(coverage={len(page_numbers) / n_pages:.3f}); "
                    f"source=word; signals=role+recurrence"
                    + ("" if role == "folio" else "+detached")
                    + ("" if role != "folio" else "+folio-parse+variation")
                ),
            )
        )
    return associations


def reconstruct_text_page_furniture(pages: list[PageGeometry]) -> list[SpatialAssociation]:
    """High-confidence recurring text-only page furniture across ``pages``.

    Operates on WORD grouped lines. Emits ``PAGE_FURNITURE`` associations
    with ``assoc:furniture:{group_id}:{header|footer|folio}``. Identity
    hashes include ``word`` and the structural role so they cannot collide
    with table furniture IDs or merge top/bottom groups. Source regions
    are not modified. Ambiguous candidates produce nothing.

    Standalone: not consulted by ``reconstruct_cross_page_continuation``.
    """
    pages_sorted = sorted(pages, key=lambda page: page.page_number)
    n_pages = len(pages_sorted)
    if n_pages < _FURNITURE_MIN_PAGES:
        return []
    (
        headers,
        headers_sparse,
        footers,
        footers_sparse,
        folios,
        folios_sparse,
    ) = _collect_text_furniture_candidates(pages_sorted)
    associations: list[SpatialAssociation] = []
    associations.extend(
        _emit_text_furniture_groups(
            headers,
            headers_sparse,
            role="header",
            n_pages=n_pages,
            require_text=True,
            require_folio_variation=False,
        )
    )
    associations.extend(
        _emit_text_furniture_groups(
            footers,
            footers_sparse,
            role="footer",
            n_pages=n_pages,
            require_text=True,
            require_folio_variation=False,
        )
    )
    associations.extend(
        _emit_text_furniture_groups(
            folios,
            folios_sparse,
            role="folio",
            n_pages=n_pages,
            require_text=False,
            require_folio_variation=True,
        )
    )
    return associations


def _furniture_tables_on_page(
    page: PageGeometry, furniture_region_ids: set[str] | frozenset[str]
) -> list[SpatialRegion]:
    if not furniture_region_ids:
        return []
    return [
        region
        for region in page.regions
        if region.region_id in furniture_region_ids
        and region.region_type == SpatialRegionType.TABLE
        and region.bbox is not None
    ]


def _content_lines(
    lines: list[_Line], furniture_tables: list[SpatialRegion]
) -> list[_Line]:
    if not furniture_tables:
        return lines
    return [line for line in lines if not _line_intersects_any_table(line, furniture_tables)]


# ---------------------------------------------------------------------------
# C. Cross-page continuity -- deliberately conservative (AND, not OR).
# ---------------------------------------------------------------------------


def reconstruct_cross_page_continuation(
    page_a: PageGeometry,
    page_b: PageGeometry,
    *,
    furniture_region_ids: set[str] | frozenset[str],
) -> list[SpatialAssociation]:
    """Candidate continuation between content endpoints of adjacent pages.

    ``furniture_region_ids`` is required and keyword-only so an unfiltered
    call cannot be mistaken for the document-level protected path
    (``reconstruct_document_associations``). Pass the member IDs produced
    by ``reconstruct_page_furniture`` (or the union of
    ``furniture_region_ids_on_page`` over the adjacent pages). Pass an
    empty set only when no furniture members should be excluded -- that
    is explicit unfiltered endpoint selection, not the protected path.

    Default endpoints are the last grouped line of ``page_a`` and the
    first grouped line of ``page_b``. Every grouped line that intersects a
    named furniture TABLE region on its own page is skipped and the
    nearest remaining content line is used instead. Isolated-neighbor
    (Phase 7.4A) and two-signal scoring are otherwise unchanged.

    Scoring requires BOTH supporting signals, not just one:

    1. The last content line of ``page_a`` does not end in a sentence
       terminator or label colon (looks incomplete).
    2. The first content line of ``page_b`` starts with a lowercase
       letter, OR the last content line of ``page_a`` ends with a hyphen.

    Precondition: neither endpoint may be isolated from its nearest
    remaining same-page *content* neighbor by more than
    ``_LINE_ADJACENCY_MAX_GAP`` while also failing to share that
    neighbor's left margin.

    Only when the precondition holds and BOTH signals hold is a
    (``LAYOUT_RECONSTRUCTED``) association produced; one-signal-only
    cases are reported as ``MISSING`` (unresolved) rather than silently
    dropped OR auto-joined; zero signals, a furniture endpoint, or no
    remaining content line produce nothing."""
    lines_a = _content_lines(
        _group_words_into_lines(page_a),
        _furniture_tables_on_page(page_a, furniture_region_ids),
    )
    lines_b = _content_lines(
        _group_words_into_lines(page_b),
        _furniture_tables_on_page(page_b, furniture_region_ids),
    )
    if not lines_a or not lines_b:
        return []
    last = lines_a[-1]
    first = lines_b[0]
    previous_a = lines_a[-2] if len(lines_a) > 1 else None
    next_b = lines_b[1] if len(lines_b) > 1 else None
    if _isolated_from_same_page_neighbor(last, previous_a) or _isolated_from_same_page_neighbor(
        first, next_b
    ):
        return []
    signals = 0
    if _looks_incomplete(last.text):
        signals += 1
    first_stripped = first.text.strip()
    if first_stripped and (first_stripped[0].islower() or last.text.rstrip().endswith("-")):
        signals += 1
    total = 2
    if signals == 0:
        return []
    origin = EvidenceOrigin.LAYOUT_RECONSTRUCTED if signals == total else EvidenceOrigin.MISSING
    note = (
        f"Candidate cross-page continuation: {last.text!r} -> {first.text!r}"
        if signals == total
        else f"Only one supporting signal (insufficient, left unresolved): {last.text!r} -> {first.text!r}"
    )
    return [
        SpatialAssociation(
            association_id=f"assoc:xpage:{last.word_region_ids[0]}:{first.word_region_ids[0]}",
            region_ids=[*last.word_region_ids, *first.word_region_ids],
            kind=SpatialRelationKind.CONTINUATION,
            origin=origin,
            confidence=_confidence(signals, total),
            note=note,
        )
    ]


# ---------------------------------------------------------------------------
# D. Table header/cell relationships -- NOT implemented, documented gap.
# ---------------------------------------------------------------------------
#
# Deliberately not implemented in this phase: the project's existing table
# extraction (``pymupdf_extractor.py::_extract_table_regions``, confirmed by
# direct reading) captures only each table's own overall bounding box, never
# per-cell bounding boxes, and raw ``table_regions`` rows carry no explicit
# "this row is a header" flag. A reliable, document-agnostic header/cell
# association would need one of: (a) per-cell geometry (not currently
# extracted), or (b) a text-shape heuristic for "looks like a header row"
# confident enough not to misfire on an ordinary short first data row --
# neither is available with enough evidence today to produce this capability
# without guessing. Per the user's explicit instruction ("If the available
# production evidence is insufficient for a particular reconstruction
# capability, document the limitation rather than fabricating a solution"),
# this is reported as a limitation, not implemented speculatively.


# ---------------------------------------------------------------------------
# E. Structural integration entry points.
# ---------------------------------------------------------------------------


def reconstruct_page_associations(page: PageGeometry) -> list[SpatialAssociation]:
    """Run every single-page reconstruction capability and return the
    combined associations (both confirmed and explicitly-unresolved)."""
    return [
        *reconstruct_table_label_continuations(page),
        *reconstruct_line_label_continuations(page),
        *reconstruct_heading_to_table(page),
    ]


def reconstruct_document_associations(pages: list[PageGeometry]) -> list[SpatialAssociation]:
    """Run per-page reconstruction for every page, plus document-level
    page-furniture evidence and cross-page continuation between each
    adjacent pair, in page order. Pure function of its input list -- does
    not consult or alter any document-specific profile, and produces the
    identical output regardless of which document type ``pages`` came
    from. Furniture evidence does not rewrite source regions; it only
    excludes high-confidence furniture lines as cross-page endpoints.
    This is the protected document-level path: furniture member IDs are
    collected per page via ``furniture_region_ids_on_page`` and passed
    explicitly into ``reconstruct_cross_page_continuation``."""
    pages_sorted = sorted(pages, key=lambda p: p.page_number)
    furniture = reconstruct_page_furniture(pages_sorted)
    furniture_ids = set()
    for page in pages_sorted:
        furniture_ids.update(furniture_region_ids_on_page(page, furniture))
    associations: list[SpatialAssociation] = list(furniture)
    for page in pages_sorted:
        associations.extend(reconstruct_page_associations(page))
    for page_a, page_b in zip(pages_sorted, pages_sorted[1:]):
        associations.extend(
            reconstruct_cross_page_continuation(
                page_a, page_b, furniture_region_ids=furniture_ids
            )
        )
    return associations


def associations_for_page_range(
    associations: list[SpatialAssociation],
    all_pages_by_region: dict[str, int],
    page_start: int | None,
    page_end: int | None,
) -> list[SpatialAssociation]:
    """Coarse, page-scoped attribution of document-level associations to one
    structural unit's page range. This is an HONEST APPROXIMATION, not a
    precise region-to-unit mapping: the document-specific adapters that
    build ``StructuralUnit`` objects today (``adapt_handbook_document`` etc.)
    do not retain which exact spatial regions contributed to a given unit's
    text, since that link was already lost by the time flattened text
    reaches them. An association is attributed to a unit only when every
    region it references falls within [page_start, page_end] (inclusive);
    a unit with no page range (``page_start is None``) never receives any
    association this way, rather than guessing document-wide applicability."""
    if page_start is None:
        return []
    end = page_end if page_end is not None else page_start
    result = []
    for assoc in associations:
        pages_touched = {all_pages_by_region.get(rid) for rid in assoc.region_ids}
        if None in pages_touched:
            continue
        if all(page_start <= p <= end for p in pages_touched):  # type: ignore[operator]
            result.append(assoc)
    return result
