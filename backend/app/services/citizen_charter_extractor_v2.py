"""Citizen's Charter / Service Process extractor V2 (Phase B).

Reusable, page-based extractor that uses PyMuPDF/OCR word geometry (when
available, see `PageExtraction.words` from Phase A) to reconstruct clean
service records: office/division, classification, transaction type, who may
avail, a 2-column requirements table, and a 5-column step table, plus a
TOTAL fees/processing-time split.

This is a Citizen's Charter / Service Process *document profile* extractor,
not a one-PDF hardcoded parser: service boundaries, table headers, and
column layout are all detected generically from text/geometry signals.

Phase B scope: this module is intentionally standalone. It is not wired
into Generate Articles, `structured_document_parser`, knowledge units, the
public Knowledge Base, or ChromaDB. It only exposes
`extract_citizen_charter_services_v2()` for future integration phases.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.utils.pdf.pymupdf_extractor import PageExtraction

NEEDS_REVIEW = "[NEEDS REVIEW]"

PARSER_STRATEGY_GEOMETRY = "geometry_words_v2"
PARSER_STRATEGY_TEXT_FALLBACK = "text_heuristic_v1_fallback"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class RequirementV2:
    requirement: str
    where_to_secure: str


@dataclass
class StepV2:
    client_step: str
    agency_action: str
    fees: str
    processing_time: str
    person_responsible: str


@dataclass
class CharterServiceV2:
    service_title: str
    office_division: str
    classification: str
    transaction_type: str
    who_may_avail: str
    requirements: list[RequirementV2] = field(default_factory=list)
    steps: list[StepV2] = field(default_factory=list)
    total_fees: str = NEEDS_REVIEW
    total_processing_time: str = NEEDS_REVIEW
    page_start: int | None = None
    page_end: int | None = None
    extraction_quality: str = "low_quality"
    extraction_quality_reason: str = ""
    checklist_blank: bool = False
    parser_debug: dict[str, Any] = field(default_factory=dict)


@dataclass
class _ServiceBlockSpan:
    title: str
    start_idx: int
    end_idx: int  # exclusive, indices into the flattened line list
    page_start: int
    page_end: int
    rejected_fragments: list[str]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def extract_citizen_charter_services_v2(pages: list[PageExtraction]) -> list[CharterServiceV2]:
    """Extract Citizen's Charter / Service Process services from page geometry.

    Accepts `PageExtraction` objects (page_number, text, words, table_regions,
    geometry_scale). When `words` is present, service tables are reconstructed
    using word x/y coordinates (`parser_strategy_used=geometry_words_v2`).
    When `words` is missing, falls back to pipe-delimited text-line heuristics
    (`parser_strategy_used=text_heuristic_v1_fallback`).
    """
    if not pages:
        return []
    flat = _flatten_pages(pages)
    blocks = _detect_service_blocks(flat)
    services = [_build_service_from_block(block, flat) for block in blocks]
    return _merge_title_bound_placeholder_services(services)


# ---------------------------------------------------------------------------
# Page geometry -> flattened lines
# ---------------------------------------------------------------------------


def _flatten_pages(pages: list[PageExtraction]) -> list[dict]:
    flat: list[dict] = []
    for page in pages:
        strategy, lines = _build_page_lines(page)
        for line in lines:
            flat.append(
                {
                    "page": page.page_number,
                    "text": line["text"],
                    "words": line["words"],
                    "strategy": strategy,
                }
            )
    return flat


def _build_page_lines(page: PageExtraction) -> tuple[str, list[dict]]:
    if page.words:
        rows = _cluster_words_by_row(page.words)
        lines: list[dict] = []
        for row in rows:
            ordered = sorted(row, key=lambda w: w["x0"])
            lines.append({"text": _row_words_to_text(ordered), "words": ordered})
        return PARSER_STRATEGY_GEOMETRY, lines

    lines = []
    for raw_line in (page.text or "").splitlines():
        if not raw_line.strip():
            continue
        lines.append({"text": raw_line, "words": None})
    return PARSER_STRATEGY_TEXT_FALLBACK, lines


def _cluster_words_by_row(words: list[dict]) -> list[list[dict]]:
    """Group word boxes into visual rows by Y proximity (self-contained;
    mirrors the Phase A PyMuPDF row-clustering heuristic)."""
    if not words:
        return []
    ordered = sorted(words, key=lambda w: (w.get("cy", 0.0), w.get("x0", 0.0)))
    heights = sorted(w.get("height", 10.0) for w in ordered)
    median_height = heights[len(heights) // 2] if heights else 10.0
    threshold = max(3.0, median_height * 0.65)

    rows: list[list[dict]] = []
    for word in ordered:
        if not rows:
            rows.append([word])
            continue
        current = rows[-1]
        current_y = sum(w.get("cy", 0.0) for w in current) / len(current)
        if abs(word.get("cy", 0.0) - current_y) <= threshold:
            current.append(word)
        else:
            rows.append([word])
    return rows


def _row_words_to_text(words: list[dict]) -> str:
    if not words:
        return ""
    heights = [w.get("height", 10.0) for w in words]
    median_height = sorted(heights)[len(heights) // 2] if heights else 10.0
    gap = max(median_height * 2.0, 18)

    parts: list[str] = []
    previous_x1: float | None = None
    for word in words:
        if previous_x1 is not None and word["x0"] - previous_x1 > gap:
            parts.append("|")
        parts.append(word["text"])
        previous_x1 = word.get("x1", word["x0"])
    return " ".join(parts).strip()


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------


def _normalize_space(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _filled(value: str | None) -> bool:
    text = _normalize_space(value)
    if not text or text == NEEDS_REVIEW:
        return False
    return text.casefold() != "not specified"


# ---------------------------------------------------------------------------
# Service boundary / fragment-title detection
# ---------------------------------------------------------------------------

_FIELD_LABEL_RE = re.compile(
    r"^(?:office\s*(?:/|or)?\s*division|classification|transaction\s+type|type\s+of\s+transaction|"
    r"who\s+may\s+avail|checklist\s+of\s+requirements|where\s+to\s+secure|client\s+steps?|"
    r"agency\s+actions?|fees?(?:\s+to\s+be\s+paid)?|processing\s+time|person\s+responsible|"
    r"total(?:\s+processing\s+time)?|requirements?)\s*:?\s*$",
    re.I,
)

_TRANSACTION_TYPE_VALUE_RE = re.compile(
    r"^(?:g2c|g2b|g2g)\b|government\s+to\s+(?:citizen|business|government)|"
    r"citizen\s+to\s+government|business\s+to\s+government",
    re.I,
)

# Generic, non-institution-specific OCR/table crumbs observed in real Citizen's
# Charter extractions that must never become service titles.
_KNOWN_FRAGMENT_SNIPPETS = (
    "ds review]",
    "interview of reference",
    "once approved, the client prepares the document for application, including",
)

_TIME_ONLY_RE = re.compile(
    r"^\d+(?:\.\d+)?\s*(?:-\s*\d+(?:\.\d+)?)?\s*(?:minutes?|mins?|hours?|hrs?|days?|seconds?)$",
    re.I,
)

_OFFICE_ONLY_RE = re.compile(
    r"^[a-z0-9 .&'\-/]{2,60}\s+(?:office|division|unit|section|department)$",
    re.I,
)
_OFFICE_ONLY_SERVICE_VERB_RE = re.compile(
    r"\b(?:validation|processing|issuance|request|application|enrollment|advis|counsel|"
    r"dropping|completion|circulation|assessment|appraisal|admission)\b",
    re.I,
)

# Imperative / process-row openings that are table client-steps, not service titles.
_STEP_LIKE_TITLE_RE = re.compile(
    r"^(?:present|submit|fill(?:\s+out)?|accomplish|secure|pay|claim|receive|accept|"
    r"evaluate|proceed|wait|return|get|provide|attach|bring|request|apply|sign|verify|"
    r"check|issue|release|endorse|encode|print|photocopy|prepare|review|validate|"
    r"forward|transmit|inform|advise|assist|interview|inspect|record|encode)\b",
    re.I,
)

# Generic narrative blurbs that follow a numbered service heading and must never
# become the service title (e.g. "This process provides description...").
_GENERIC_DESCRIPTION_TITLE_RE = re.compile(
    r"^(?:this\s+process\s+provides|this\s+service\s+provides|"
    r"this\s+includes\s+the\s+process|a\s+service\s+to\s+provide|"
    r"provision\s+of\s+services|to\s+furnish\s+or\s+provide)\b",
    re.I,
)

_TABLE_NOISE_CELL_RE = re.compile(r"^(?:clientele|clients?)$", re.I)

_HEADER_LOOKAHEAD = 18


def _looks_like_generic_description_title(text: str) -> bool:
    cleaned = _normalize_space(text)
    if not cleaned:
        return False
    return bool(_GENERIC_DESCRIPTION_TITLE_RE.match(cleaned))


def _is_table_noise_cell(text: str) -> bool:
    return bool(_TABLE_NOISE_CELL_RE.match(_normalize_space(text)))


def _looks_like_field_or_fragment_line(text: str) -> bool:
    """True for table field labels, OCR crumbs, sentence fragments, page
    numbers, office-only names, or requirement/time-only fragments."""
    cleaned = _normalize_space(text)
    if not cleaned:
        return True
    lower = cleaned.casefold()

    if _FIELD_LABEL_RE.match(lower):
        return True
    if _looks_like_generic_description_title(cleaned):
        return True
    if lower.startswith("secure:") or lower.startswith("secure :"):
        return True
    if _TRANSACTION_TYPE_VALUE_RE.search(lower):
        return True
    if any(snippet in lower for snippet in _KNOWN_FRAGMENT_SNIPPETS):
        return True
    if "[" in cleaned or "]" in cleaned:
        return True
    if "," in cleaned:
        return True
    if re.fullmatch(r"page\s*\d+", lower):
        return True
    if re.fullmatch(r"\d{1,4}", lower):
        return True
    if _TIME_ONLY_RE.match(lower):
        return True
    if cleaned[-1:] in {"/", ";", ":"}:
        return True
    # Full sentence / trailing period usually means a step row, not a title.
    if cleaned.endswith("."):
        return True
    if _STEP_LIKE_TITLE_RE.match(cleaned):
        return True
    if re.search(r"\b(?:and|or|of|the|to|in|for|including|with)\s*$", lower):
        return True
    if cleaned[:1].islower():
        return True
    if _OFFICE_ONLY_RE.match(lower) and not _OFFICE_ONLY_SERVICE_VERB_RE.search(lower):
        return True
    return False


def _has_service_header_cues(idx: int, flat: list[dict]) -> bool:
    """Real Citizen's Charter services open with a full header + table cues.

    Required nearby signals (same service block, not the whole document):
    Office/Division, Classification, Type of Transaction, Who May Avail, and
    either Checklist of Requirements or Client Steps.

    Scanning stops at TOTAL or the next numbered service-looking line so
    mid-table rows cannot borrow the *next* service's header cues.
    """
    pieces: list[str] = []
    end = min(idx + 1 + _HEADER_LOOKAHEAD, len(flat))
    for j in range(idx + 1, end):
        text = re.sub(r"\s*\|\s*", " ", _normalize_space(flat[j]["text"]))
        if not text:
            continue
        if re.match(r"(?i)^total\b", text):
            break
        numbered = re.match(r"^(\d{1,3})[\.\)]\s+(.{2,90})$", text)
        if numbered:
            maybe_title = _normalize_space(numbered.group(2))
            # A following real service heading ends this header window.
            if not _looks_like_field_or_fragment_line(maybe_title) and not _STEP_LIKE_TITLE_RE.match(
                maybe_title
            ):
                break
        pieces.append(text)
    window = " ".join(pieces)
    if not window:
        return False
    has_office = bool(re.search(r"office\s*(?:/|or)?\s*division\s*:", window, flags=re.I))
    has_class = bool(re.search(r"classification\s*:", window, flags=re.I))
    has_txn = bool(
        re.search(r"(?:transaction\s+type|type\s+of\s+transaction)\s*:", window, flags=re.I)
    )
    has_who = bool(re.search(r"who\s+may\s+avail\s*:", window, flags=re.I))
    has_table = bool(
        re.search(r"checklist\s+of\s+requirements", window, flags=re.I)
        or re.search(r"client\s+steps?", window, flags=re.I)
    )
    return has_office and has_class and has_txn and has_who and has_table


def _line_is_heading_candidate(idx: int, flat: list[dict]) -> str | None:
    """Return a cleaned title when line `idx` looks like a valid service heading."""
    raw = _normalize_space(flat[idx]["text"])
    if not raw:
        return None
    text_no_pipes = re.sub(r"\s*\|\s*", " ", raw)

    numbered = re.match(r"^(\d{1,3})[\.\)]\s+(.{2,90})$", text_no_pipes)
    if numbered:
        title = _normalize_space(numbered.group(2))
        if _looks_like_field_or_fragment_line(title) or _looks_like_generic_description_title(title):
            return None
        if not _has_service_header_cues(idx, flat):
            return None
        return title

    if len(text_no_pipes) > 90 or len(text_no_pipes.split()) > 14:
        return None
    if _looks_like_field_or_fragment_line(text_no_pipes):
        return None
    if _looks_like_generic_description_title(text_no_pipes):
        return None
    if not re.match(r"^[A-Z0-9]", text_no_pipes):
        return None

    # Unnumbered heading: same strict header+table cues as numbered services.
    if not _has_service_header_cues(idx, flat):
        return None
    return text_no_pipes


def _find_total_line_index(flat: list[dict], start: int, end: int) -> int | None:
    for idx in range(start, end):
        text_no_pipes = re.sub(r"\s*\|\s*", " ", _normalize_space(flat[idx]["text"]))
        if re.match(r"(?i)^total\b", text_no_pipes):
            return idx
    return None


def _local_rejected_fragments(flat: list[dict], start_idx: int, end_idx: int) -> list[str]:
    """Numbered non-heading lines inside this service block only (not document-wide)."""
    rejected: list[str] = []
    for idx in range(start_idx + 1, end_idx):
        raw = _normalize_space(flat[idx]["text"])
        if not raw:
            continue
        text_no_pipes = re.sub(r"\s*\|\s*", " ", raw)
        if not re.match(r"^\d{1,3}[\.\)]\s+", text_no_pipes):
            continue
        # Keep genuine step/process rows out of rejected — they belong in the table.
        title_part = re.sub(r"^\d{1,3}[\.\)]\s+", "", text_no_pipes).strip()
        if _STEP_LIKE_TITLE_RE.match(title_part) or title_part.endswith("."):
            continue
        if _looks_like_field_or_fragment_line(title_part):
            rejected.append(raw)
    return rejected


def _detect_service_blocks(flat: list[dict]) -> list[_ServiceBlockSpan]:
    """Detect service blocks; numbered headings stay active until the next numbered heading.

    Generic description lines after a numbered title never start a new service.
    """
    heading_indices: list[tuple[int, str, bool]] = []

    for idx in range(len(flat)):
        raw = _normalize_space(flat[idx]["text"])
        if not raw:
            continue
        text_no_pipes = re.sub(r"\s*\|\s*", " ", raw)
        numbered = bool(re.match(r"^(\d{1,3})[\.\)]\s+(.{2,90})$", text_no_pipes))
        title = _line_is_heading_candidate(idx, flat)
        if title:
            heading_indices.append((idx, title, numbered))

    blocks: list[_ServiceBlockSpan] = []
    for i, (start_idx, title, _is_numbered) in enumerate(heading_indices):
        next_start = heading_indices[i + 1][0] if i + 1 < len(heading_indices) else len(flat)
        total_idx = _find_total_line_index(flat, start_idx, next_start)
        end_idx = (total_idx + 1) if total_idx is not None else next_start
        page_start = flat[start_idx]["page"]
        last_idx = max(start_idx, end_idx - 1)
        page_end = flat[last_idx]["page"]
        blocks.append(
            _ServiceBlockSpan(
                title=title,
                start_idx=start_idx,
                end_idx=end_idx,
                page_start=page_start,
                page_end=page_end,
                rejected_fragments=_local_rejected_fragments(flat, start_idx, end_idx),
            )
        )
    return blocks


def _service_is_placeholder_heading(service: CharterServiceV2) -> bool:
    has_body = (
        _filled(service.office_division)
        or _filled(service.who_may_avail)
        or bool(service.requirements)
        or bool(service.steps)
        or bool(service.checklist_blank)
    )
    return (not has_body) or service.extraction_quality == "rag_only"


def _service_has_structured_body(service: CharterServiceV2) -> bool:
    return (
        _filled(service.office_division)
        or bool(service.requirements)
        or bool(service.steps)
        or bool(service.checklist_blank)
    )


def _rebond_service_title(
    service: CharterServiceV2, title: str, *, merge_flag: str
) -> CharterServiceV2:
    quality, reason = _score_extraction_quality(
        service_title=title,
        office_division=service.office_division,
        classification=service.classification,
        transaction_type=service.transaction_type,
        who_may_avail=service.who_may_avail,
        requirements=service.requirements,
        steps=service.steps,
        total_processing_time=service.total_processing_time,
        checklist_blank=service.checklist_blank,
    )
    debug = dict(service.parser_debug or {})
    debug["detected_service_title"] = title
    debug["extraction_quality"] = quality
    debug["extraction_quality_reason"] = reason
    debug["merge"] = merge_flag
    debug["title_bound_to_structured_block"] = True
    return CharterServiceV2(
        service_title=title,
        office_division=service.office_division,
        classification=service.classification,
        transaction_type=service.transaction_type,
        who_may_avail=service.who_may_avail,
        requirements=list(service.requirements),
        steps=list(service.steps),
        total_fees=service.total_fees,
        total_processing_time=service.total_processing_time,
        page_start=service.page_start,
        page_end=service.page_end,
        extraction_quality=quality,
        extraction_quality_reason=reason,
        checklist_blank=service.checklist_blank,
        parser_debug=debug,
    )


def _merge_title_bound_placeholder_services(
    services: list[CharterServiceV2],
) -> list[CharterServiceV2]:
    """Merge placeholder title-only services into the following structured block.

    Example: "4. ID Validation" (empty / rag_only) + description-titled structured
    block → one service titled "ID Validation".
    """
    if len(services) < 2:
        # Still fix a lone generic description title if possible from raw block.
        if len(services) == 1 and _looks_like_generic_description_title(services[0].service_title):
            recovered = _recover_numbered_title_from_debug(services[0])
            if recovered:
                return [
                    _rebond_service_title(
                        services[0], recovered, merge_flag="title_bound_to_structured_block"
                    )
                ]
        return services

    out: list[CharterServiceV2] = []
    i = 0
    while i < len(services):
        cur = services[i]
        if i + 1 < len(services):
            nxt = services[i + 1]
            pages_adjacent = (
                cur.page_start is None
                or nxt.page_start is None
                or abs(int(nxt.page_start) - int(cur.page_start)) <= 1
            )
            if (
                _service_is_placeholder_heading(cur)
                and _service_has_structured_body(nxt)
                and pages_adjacent
                and (
                    _looks_like_generic_description_title(nxt.service_title)
                    or _looks_like_field_or_fragment_line(nxt.service_title)
                    or not _filled(nxt.service_title)
                )
            ):
                out.append(
                    _rebond_service_title(
                        nxt, cur.service_title, merge_flag="title_bound_to_structured_block"
                    )
                )
                i += 2
                continue
        if _looks_like_generic_description_title(cur.service_title):
            recovered = _recover_numbered_title_from_debug(cur)
            if recovered:
                out.append(
                    _rebond_service_title(
                        cur, recovered, merge_flag="title_bound_to_structured_block"
                    )
                )
                i += 1
                continue
        out.append(cur)
        i += 1
    return out


def _recover_numbered_title_from_debug(service: CharterServiceV2) -> str | None:
    raw = str((service.parser_debug or {}).get("raw_service_block") or "")
    for line in raw.splitlines():
        text = _normalize_space(line)
        numbered = re.match(r"^(\d{1,3})[\.\)]\s+(.{2,90})$", text)
        if not numbered:
            continue
        title = _normalize_space(numbered.group(2))
        if _looks_like_generic_description_title(title):
            continue
        if _looks_like_field_or_fragment_line(title) or _STEP_LIKE_TITLE_RE.match(title):
            continue
        return title
    return None


# ---------------------------------------------------------------------------
# Field extraction (Office/Division, Classification, Transaction Type, Who May Avail)
# ---------------------------------------------------------------------------

_OFFICE_FIELD_RE = re.compile(r"office\s*(?:/|or)?\s*division\s*:\s*(.+)$", re.I)
_CLASSIFICATION_FIELD_RE = re.compile(r"classification\s*:\s*(.+)$", re.I)
_TRANSACTION_FIELD_RE = re.compile(
    r"(?:transaction\s+type|type\s+of\s+transaction)\s*:\s*(.+)$", re.I
)
_WHO_FIELD_RE = re.compile(r"who\s+may\s+avail\s*:\s*(.+)$", re.I)


def _extract_field(lines: list[dict], pattern: re.Pattern) -> str:
    for idx, line in enumerate(lines):
        text = re.sub(r"\s*\|\s*", " ", _normalize_space(line["text"]))
        if not text:
            continue
        match = pattern.search(text)
        if not match:
            continue
        value = _normalize_space(match.group(1)).rstrip(" |")
        if value:
            return value
        # Label-only line ("Office / Division:") — take the next non-empty value line.
        for nxt in lines[idx + 1 : idx + 4]:
            nxt_text = re.sub(r"\s*\|\s*", " ", _normalize_space(nxt.get("text")))
            if not nxt_text:
                continue
            if _FIELD_LABEL_RE.match(nxt_text) or _looks_like_field_or_fragment_line(nxt_text):
                break
            if ":" in nxt_text and not re.search(
                r"^(?:office|who|classification|transaction)\b", nxt_text, re.I
            ):
                # Another label:value on next line — prefer the value side when short.
                after = _normalize_space(nxt_text.split(":", 1)[-1])
                if after and not _FIELD_LABEL_RE.match(after):
                    return after
            if not _FIELD_LABEL_RE.match(nxt_text):
                return nxt_text
    return ""


_PRIORITY_VISUAL_DEBUG_TITLES = (
    "ID Validation",
    "Processing of Student ID",
    "ID Processing",
    "LSPU Entrance Examination",
    "Library Circulation Service",
    "Library Reference Assistance",
    "Assessment of Fees",
    "Issuance of Good Moral Certificate",
    "Scholarship and Financial Assistance",
)


def _is_priority_visual_debug_title(title: str) -> bool:
    cleaned = re.sub(r"^\d{1,3}[\.\)]\s*", "", _normalize_space(title)).strip()
    lower = cleaned.casefold()
    for name in _PRIORITY_VISUAL_DEBUG_TITLES:
        if name.casefold() == lower or name.casefold() in lower or lower in name.casefold():
            return True
    return False


# ---------------------------------------------------------------------------
# Column detection / table reconstruction
# ---------------------------------------------------------------------------


def _find_header_row(lines: list[dict], required_patterns: tuple[re.Pattern, ...]) -> int | None:
    for idx, line in enumerate(lines):
        text_no_pipes = re.sub(r"\s*\|\s*", " ", _normalize_space(line["text"]))
        if all(pattern.search(text_no_pipes) for pattern in required_patterns):
            return idx
    return None


def _find_section_end(lines: list[dict], start: int, stop_patterns: tuple[re.Pattern, ...]) -> int:
    for idx in range(start, len(lines)):
        text_no_pipes = re.sub(r"\s*\|\s*", " ", _normalize_space(lines[idx]["text"]))
        if any(pattern.search(text_no_pipes) for pattern in stop_patterns):
            return idx
    return len(lines)


def _column_boundaries_from_header(words: list[dict], column_count: int) -> list[float]:
    """Split header words into `column_count` columns using the largest
    inter-word x-gaps (generic; works for any column count/table width)."""
    ordered = sorted(words, key=lambda w: w["x0"])
    if column_count <= 1 or len(ordered) < column_count:
        return []
    gaps: list[tuple[float, float]] = []
    for i in range(len(ordered) - 1):
        current = ordered[i]
        nxt = ordered[i + 1]
        gap = nxt["x0"] - current.get("x1", current["x0"])
        midpoint = (current.get("x1", current["x0"]) + nxt["x0"]) / 2
        gaps.append((gap, midpoint))
    gaps.sort(key=lambda item: item[0], reverse=True)
    top = gaps[: column_count - 1]
    return sorted(midpoint for _, midpoint in top)


def _column_boundaries_from_body(body_lines: list[dict], column_count: int) -> list[float]:
    """Fallback: infer column midpoints from dense body word x-gaps."""
    xs: list[float] = []
    for line in body_lines:
        for word in line.get("words") or []:
            xs.append(float(word.get("x0", 0.0)))
    if column_count <= 1 or len(xs) < column_count * 2:
        return []
    xs = sorted(xs)
    # Cluster x positions into roughly column_count bands via largest gaps.
    gaps: list[tuple[float, float]] = []
    for i in range(len(xs) - 1):
        gap = xs[i + 1] - xs[i]
        if gap < 8:
            continue
        midpoint = (xs[i] + xs[i + 1]) / 2
        gaps.append((gap, midpoint))
    gaps.sort(key=lambda item: item[0], reverse=True)
    top = gaps[: column_count - 1]
    return sorted(midpoint for _, midpoint in top)


def _assign_words_to_columns(words: list[dict], boundaries: list[float]) -> list[list[dict]]:
    columns: list[list[dict]] = [[] for _ in range(len(boundaries) + 1)]
    if not columns:
        columns = [[]]
    for word in sorted(words, key=lambda w: w["x0"]):
        col = 0
        for boundary in boundaries:
            if word["x0"] >= boundary:
                col += 1
            else:
                break
        col = min(col, len(columns) - 1)
        columns[col].append(word)
    return columns


def _column_text(words: list[dict]) -> str:
    return _normalize_space(" ".join(w["text"] for w in sorted(words, key=lambda w: w["x0"])))


def _row_mean_y(words: list[dict] | None) -> float | None:
    if not words:
        return None
    return sum(float(w.get("cy", 0.0)) for w in words) / max(1, len(words))


def _is_personnel_title_fragment(text: str) -> bool:
    cleaned = _normalize_space(text).rstrip("/").strip()
    if not cleaned:
        return False
    return bool(
        re.fullmatch(
            r"(?:OSAS\s+)?"
            r"(?:Director|Chairperson|Chair|Dean|Associate(?:\s+Dean)?|"
            r"Program(?:\s+Head|\s+Chair(?:person)?)?|Staff|Registrar|Cashier|"
            r"Librarian|Counselor|Officer|Secretary|Records)"
            r"(?:[\s/,]*(?:Director|Chairperson|Chair|Dean|Associate(?:\s+Dean)?|"
            r"Program(?:\s+Head|\s+Chair(?:person)?)?|Staff|Registrar|Cashier|"
            r"Librarian|Counselor|Officer|Secretary|Records))*",
            cleaned,
            flags=re.I,
        )
    )


def _client_looks_unfinished_geometry(text: str) -> bool:
    cleaned = _normalize_space(text)
    if not cleaned:
        return True
    if cleaned.endswith(("-", ",", "/")):
        return True
    if re.search(r"\b(?:the|of|and|or|for|to|by|with|a|an|from|into|certificate)\s*$", cleaned, flags=re.I):
        return True
    # OCR often splits "Accept the validated" / "ID." across rows.
    if not cleaned.endswith(".") and re.search(
        r"\b(?:validated|filled(?:\s+out)?|accomplished|signed|completed|issued|"
        r"required|submitted|accepted|rendered|evaluated)\s*$",
        cleaned,
        flags=re.I,
    ):
        return True
    words = cleaned.split()
    if len(words) <= 2 and not cleaned.endswith("."):
        return True
    return False


def _join_personnel_cells(existing: str, fragment: str) -> str:
    head = _normalize_space(existing).rstrip("/")
    tail = _normalize_space(fragment).lstrip("/").strip()
    if _is_table_noise_cell(tail):
        return head
    if _is_table_noise_cell(head):
        return tail
    # Strip embedded Clientele noise from either side.
    head = _strip_personnel_noise(head)
    tail = _strip_personnel_noise(tail)
    if not head:
        return tail
    if not tail:
        return head
    if tail.casefold() in head.casefold():
        return head
    return _normalize_space(f"{head}/{tail}".replace("//", "/"))


def _strip_personnel_noise(text: str) -> str:
    cleaned = _normalize_space(text)
    if not cleaned:
        return ""
    cleaned = re.sub(r"(?i)(?:^|/)\s*clientele\s*(?=/|$)", "/", cleaned)
    cleaned = cleaned.strip("/").strip()
    cleaned = re.sub(r"/{2,}", "/", cleaned)
    return _normalize_space(cleaned)


def _split_time_and_person_cells(ptime: str, person: str) -> tuple[str, str]:
    """Repair mixed time/personnel cells.

    Examples:
    - '5mins Records' + 'Officer, Staff' → '5mins' / 'Records Officer, Staff'
    - '18 Minutes Director/' + 'Chairperson' → '18 Minutes' / 'Director/Chairperson'
    - 'Program 30 mins' + 'Head/faculty In-charge' → '30 mins' / 'Program Head/faculty In-charge'
    """
    proc = _normalize_space(ptime)
    responsible = _normalize_space(person)
    if not proc:
        return proc, responsible

    # Title BEFORE time: "Program 30 mins"
    title_before = re.match(
        r"^(?P<head>[A-Za-z][\w/]*(?:\s+[A-Za-z][\w/]*){0,2})\s+"
        r"(?P<time>\d+(?:\.\d+)?\s*(?:mins?|minutes?|hours?|hrs?|days?|seconds?))\s*$",
        proc,
        flags=re.I,
    )
    if title_before and not re.fullmatch(
        r"\d+(?:\.\d+)?\s*(?:mins?|minutes?|hours?|hrs?|days?|seconds?)",
        proc,
        flags=re.I,
    ):
        head = _normalize_space(title_before.group("head"))
        if head and not re.fullmatch(
            r"(?:mins?|minutes?|hours?|hrs?|days?|seconds?)", head, flags=re.I
        ):
            proc = _normalize_space(title_before.group("time"))
            if responsible:
                if head.casefold() not in responsible.casefold():
                    responsible = f"{head} {responsible}".replace("  ", " ").strip()
            else:
                responsible = head
            return proc, responsible

    # Time then title head: "5mins Records" / "18 Minutes Director/"
    time_head = re.match(
        r"^(?P<time>\d+(?:\.\d+)?\s*(?:mins?|minutes?|hours?|hrs?|days?|seconds?))"
        r"\s+(?P<head>[A-Za-z][\w/]*?(?:\s+[A-Za-z][\w/]*?){0,3})\s*$",
        proc,
        flags=re.I,
    )
    if time_head and not _TIME_ATOM_RE.fullmatch(proc):
        head = _normalize_space(time_head.group("head"))
        if head and not re.fullmatch(
            r"(?:mins?|minutes?|hours?|hrs?|days?|seconds?)", head, flags=re.I
        ):
            proc = _normalize_space(time_head.group("time"))
            if responsible:
                if head.casefold() not in responsible.casefold():
                    if responsible[:1].islower() or re.match(
                        r"^(?:officer|staff|director|chairperson|dean|head|faculty)\b",
                        responsible,
                        flags=re.I,
                    ):
                        # "Records" + "Officer/Staff" → "Records Officer/Staff"
                        if "/" in responsible and "/" not in head:
                            responsible = f"{head} {responsible}".strip()
                        elif "/" in head:
                            responsible = f"{head.rstrip('/')}/{responsible.lstrip('/')}".replace(
                                "//", "/"
                            )
                        else:
                            responsible = f"{head} {responsible}".strip()
                    else:
                        responsible = f"{head}/{responsible}".replace("//", "/").strip()
            else:
                responsible = head
    return proc, responsible


def _rows_to_columns(
    header_line: dict,
    body_lines: list[dict],
    *,
    column_count: int,
) -> tuple[list[list[str]], list[str], dict[str, Any]]:
    """Convert body lines under `header_line` into `column_count`-wide rows.

    Geometry (word x positions) is the source of truth when available. Flattened
    text/`|` splitting is only used when words are missing.
    """
    rejected: list[str] = []
    rows: list[list[str]] = []
    visual_rows: list[dict[str, Any]] = []
    word_assignments: list[dict[str, Any]] = []

    header_words = header_line.get("words")
    boundaries = (
        _column_boundaries_from_header(header_words, column_count) if header_words else []
    )
    if not boundaries and body_lines:
        boundaries = _column_boundaries_from_body(body_lines, column_count)

    if header_words or any(line.get("words") for line in body_lines):
        for line in body_lines:
            words = line.get("words")
            text = _normalize_space(line["text"])
            y_value = _row_mean_y(words)
            if not words:
                if text:
                    rejected.append(text)
                    visual_rows.append(
                        {
                            "y": y_value,
                            "text": text,
                            "cells": [],
                            "dropped_reason": "no_word_geometry_on_line",
                        }
                    )
                continue
            columns = _assign_words_to_columns(words, boundaries)
            cells = [_column_text(col) for col in columns]
            # Pad if boundaries empty produced one column.
            cells = (cells + [""] * column_count)[:column_count]
            rows.append(cells)
            visual_rows.append({"y": y_value, "text": text, "cells": list(cells), "dropped_reason": None})
            for col_idx, col_words in enumerate(columns):
                for word in col_words:
                    word_assignments.append(
                        {
                            "text": word.get("text"),
                            "x0": word.get("x0"),
                            "y": word.get("cy"),
                            "column": col_idx,
                        }
                    )
    else:
        for line in body_lines:
            text = _normalize_space(line["text"])
            if not text:
                continue
            cells = [cell.strip() for cell in text.split("|")]
            cells = (cells + [""] * column_count)[:column_count]
            rows.append(cells)
            visual_rows.append(
                {
                    "y": None,
                    "text": text,
                    "cells": list(cells),
                    "dropped_reason": "text_pipe_fallback",
                }
            )

    debug = {
        "column_boundaries": boundaries,
        "visual_rows": visual_rows,
        "word_column_assignments": word_assignments[:400],
        "raw_column_rows": [list(row) for row in rows],
    }
    return rows, rejected, debug


def _looks_like_new_step_marker(text: str) -> bool:
    cleaned = _normalize_space(text)
    if not cleaned:
        return False
    if re.match(r"^\d{1,3}[\.\)]\s+\S", cleaned):
        return True
    if re.match(r"^[•●▪◦‣]\s*\S", cleaned):
        return True
    if re.match(r"^[-–—]\s+\S", cleaned):
        return True
    return False


def _looks_like_wrapped_continuation(text: str, previous: str) -> bool:
    """True when `text` looks like a wrap continuation of `previous`, not a new step."""
    current = _normalize_space(text)
    prior = _normalize_space(previous)
    if not current:
        return True
    if not prior:
        return False
    if _looks_like_new_step_marker(current):
        return False
    if current[:1].islower():
        return True
    # Prior clearly unfinished: dangling connector / article / preposition.
    if prior.endswith("-") or prior.endswith(","):
        return True
    if re.search(r"\b(?:the|of|and|or|for|to|by|with|a|an|from|into)\s*$", prior, flags=re.I):
        return True
    if _looks_like_short_client_continuation(current, prior):
        return True
    return False


def _looks_like_short_client_continuation(text: str, previous: str) -> bool:
    """Short trailing tokens like 'ID.' must attach when previous has no terminal period.

    Intentionally narrow: do not treat a new checklist item such as 'Student ID'
    as a wrap of 'Certificate of Registration'.
    """
    current = _normalize_space(text)
    prior = _normalize_space(previous)
    if not current or not prior or prior.endswith("."):
        return False
    if _looks_like_new_step_marker(current):
        return False
    words = current.split()
    if len(words) > 1:
        return False
    if current[:1].islower():
        return True
    # Single short token / noun fragment: "ID." "form." "certificate."
    return bool(re.fullmatch(r"[A-Za-z][\w'-]{0,24}\.?", current))


def _is_meaningful_secondary_cell(value: str) -> bool:
    cleaned = _normalize_space(value)
    if not cleaned:
        return False
    if _looks_like_page_number_fee(cleaned):
        return False
    if cleaned.casefold() in {"n/a", "na", "-", "—", "–"}:
        return True  # still a real fee/time placeholder cell
    return True


def _merge_geometry_column_continuations(rows: list[list[str]]) -> list[list[str]]:
    """Append single-/few-column visual crumbs into the previous logical row.

    Column-aware:
    - client-only → previous client
    - agency-only → previous agency
    - person-only / personnel crumbs → previous person
    A new step starts only when the incoming row has multi-column signals or a
    clear step marker, and previous client is not unfinished.
    """
    if not rows:
        return rows
    out: list[list[str]] = []
    for row in rows:
        cells = (list(row) + ["", "", "", "", ""])[:5]
        client, agency, fees, ptime, person = (_normalize_space(c) for c in cells)
        # Drop lone Clientele / client OCR noise rows (never start a step).
        filled_values = [v for v in (client, agency, fees, ptime, person) if v]
        if filled_values and all(_is_table_noise_cell(v) for v in filled_values):
            continue
        if _is_table_noise_cell(client):
            client = ""
            cells[0] = ""
        if _is_table_noise_cell(person):
            person = ""
            cells[4] = ""
        filled_idx = [i for i, value in enumerate(cells) if _normalize_space(value)]
        if not filled_idx:
            continue
        if not out:
            out.append(cells)
            continue
        prev = out[-1]
        prev_client = _normalize_space(prev[0])
        prev_agency = _normalize_space(prev[1])
        prev_person = _normalize_space(prev[4])
        prev_unfinished = _client_looks_unfinished_geometry(prev_client) or (
            bool(prev_client) and not prev_agency
        )

        # Personnel crumb in ANY single column → person responsible.
        personnel_fragment = ""
        for cand in (client, agency, fees, ptime, person):
            if _is_personnel_title_fragment(cand):
                personnel_fragment = cand
                break
        if personnel_fragment and len(filled_idx) <= 2 and (
            not client or _is_personnel_title_fragment(client)
        ):
            prev[4] = _join_personnel_cells(prev_person, personnel_fragment)
            continue

        # Single-column continuation by geometry column.
        if len(filled_idx) == 1:
            col = filled_idx[0]
            value = _normalize_space(cells[col])
            if col == 0:
                if (
                    prev_unfinished
                    or _looks_like_wrapped_continuation(value, prev_client)
                    or _looks_like_short_client_continuation(value, prev_client)
                ):
                    prev[0] = f"{prev_client} {value}".strip()
                    continue
                # Do not start a bare client-only step while previous lacks agency;
                # keep appending until a multi-column row arrives.
                if not prev_agency:
                    prev[0] = f"{prev_client} {value}".strip()
                    continue
            elif col == 1:
                prev[1] = f"{prev_agency} {value}".strip() if prev_agency else value
                continue
            elif col in (2, 3):
                if not _normalize_space(prev[col]):
                    prev[col] = value
                elif col == 3 and _TIME_ATOM_RE.search(value):
                    prev[col] = value
                else:
                    prev[col] = f"{_normalize_space(prev[col])} {value}".strip()
                continue
            elif col == 4:
                prev[4] = _join_personnel_cells(prev_person, value)
                continue

        # Multi-column continuation while previous client is unfinished:
        # "Present the" / "Certificate of" + "Registration. | Check… | None | …"
        if (
            prev_unfinished
            and client
            and (
                _looks_like_wrapped_continuation(client, prev_client)
                or _looks_like_short_client_continuation(client, prev_client)
                or _client_looks_unfinished_geometry(prev_client)
            )
            and not _looks_like_new_step_marker(client)
        ):
            prev[0] = f"{prev_client} {client}".strip()
            for i, value in enumerate((agency, fees, ptime, person), start=1):
                if value and not _normalize_space(prev[i]):
                    prev[i] = value
                elif value and i in (1,) and _normalize_space(prev[i]):
                    prev[i] = f"{_normalize_space(prev[i])} {value}".strip()
                elif value and i == 4:
                    prev[4] = _join_personnel_cells(_normalize_space(prev[4]), value)
            continue

        # Agency/meta arrives on next visual row while previous has client but no agency.
        if prev_client and not prev_agency and agency and (
            not client
            or _looks_like_wrapped_continuation(client, prev_client)
            or _looks_like_short_client_continuation(client, prev_client)
        ):
            if client:
                prev[0] = f"{prev_client} {client}".strip()
            prev[1] = agency
            for i, value in enumerate((fees, ptime, person), start=2):
                if value and not _normalize_space(prev[i]):
                    prev[i] = value
                elif value and i == 4:
                    prev[4] = _join_personnel_cells(_normalize_space(prev[4]), value)
            continue

        out.append(cells)
    return out


def _merge_wrapped_rows(
    rows: list[list[str]], *, primary_idx: list[int], secondary_idx: list[int]
) -> list[list[str]]:
    """Merge visually-wrapped continuation rows into one logical table row.

    A new logical row starts only when:
    - the primary/client column begins with a step number or bullet marker, or
    - the incoming row has multi-column content that looks like a fresh step
      while the current row already has meaningful secondary values,
    - and the new primary text does not look like a wrapped continuation.
    """
    logical: list[list[str]] = []
    current: list[str] | None = None

    def _cell(row: list[str], idx: int) -> str:
        return row[idx].strip() if idx < len(row) and row[idx] else ""

    def _has_meaningful_secondary(row: list[str]) -> bool:
        return any(
            _is_meaningful_secondary_cell(_cell(row, i)) for i in secondary_idx if i < len(row)
        )

    def _append_cells(target: list[str], source: list[str]) -> None:
        for i, value in enumerate(source):
            text = value.strip()
            if not text:
                continue
            while len(target) <= i:
                target.append("")
            if target[i].strip():
                # Prefer replacing page-number crumbs with real secondary values.
                if i in secondary_idx and _looks_like_page_number_fee(target[i]):
                    target[i] = text
                else:
                    target[i] = f"{target[i]} {text}".strip()
            else:
                target[i] = text

    for row in rows:
        row = list(row)
        if current is None:
            current = row
            continue

        client = _cell(row, 0)
        current_client = _cell(current, 0)
        agency = _cell(row, 1) if 1 in primary_idx or 1 in secondary_idx or len(row) > 1 else ""
        current_has_secondary = _has_meaningful_secondary(current)
        row_has_secondary = _has_meaningful_secondary(row)
        row_has_agency = bool(agency)
        current_has_agency = bool(_cell(current, 1))
        current_complete = current_has_agency and current_has_secondary

        # Personnel-only crumbs (Chairperson/Staff, Program Head) continue the
        # person-responsible cell — never start a new client step.
        current_person = _cell(current, 4) if len(current) > 4 else ""
        personnel_only = bool(
            client
            and not agency
            and not row_has_secondary
            and _is_personnel_title_fragment(client)
        )
        if personnel_only and (
            not current_person or current_person.endswith("/") or current_complete
        ):
            while len(current) < 5:
                current.append("")
            current[4] = _join_personnel_cells(current[4], client)
            continue

        # Never start a new step while the *current* client text is unfinished
        # and the current row is still incomplete. Once the current row already
        # has agency + secondary values, a new client phrase starts a new step.
        if (
            _client_looks_unfinished_geometry(current_client)
            and not current_complete
            and not _looks_like_new_step_marker(client)
        ):
            _append_cells(current, row)
            continue

        explicit_new_step = _looks_like_new_step_marker(client) and bool(current_client)
        continuation = _looks_like_wrapped_continuation(client, current_client)
        looks_like_fresh_step = bool(client) and (
            (row_has_agency and row_has_secondary)
            or (row_has_agency and current_has_secondary and current_has_agency)
            or (row_has_secondary and current_has_secondary and current_has_agency)
            or (current_complete and not continuation)
        )

        if explicit_new_step or (
            looks_like_fresh_step
            and (current_has_secondary or current_complete)
            and not continuation
            and not (
                _client_looks_unfinished_geometry(current_client) and not current_complete
            )
        ):
            logical.append(current)
            current = row
            continue

        _append_cells(current, row)

    if current is not None:
        logical.append(current)
    return logical


def _coalesce_fragment_step_rows(rows: list[list[str]]) -> list[list[str]]:
    """Second pass: fold client-only wrap fragments into the previous incomplete step."""
    if not rows:
        return []
    out: list[list[str]] = []
    for row in rows:
        cells = (list(row) + ["", "", "", "", ""])[:5]
        client, agency, fees, ptime, responsible = (_normalize_space(c) for c in cells)
        if not out:
            out.append(cells)
            continue
        prev = out[-1]
        prev_client = _normalize_space(prev[0])
        prev_agency = _normalize_space(prev[1])
        prev_complete = bool(prev_agency) and any(
            _is_meaningful_secondary_cell(_normalize_space(prev[i])) for i in (2, 3, 4)
        )
        only_client_fragment = bool(client) and not agency and not fees and not ptime and not responsible
        if only_client_fragment and (
            not prev_complete
            or _looks_like_wrapped_continuation(client, prev_client)
            or _looks_like_short_client_continuation(client, prev_client)
            or _client_looks_unfinished_geometry(prev_client)
            or _is_personnel_title_fragment(client)
            or _is_table_noise_cell(client)
        ):
            if _is_table_noise_cell(client):
                continue
            if _is_personnel_title_fragment(client):
                prev[4] = _join_personnel_cells(prev[4], client)
            elif prev_client and (
                _looks_like_wrapped_continuation(client, prev_client)
                or _looks_like_short_client_continuation(client, prev_client)
                or _client_looks_unfinished_geometry(prev_client)
            ):
                prev[0] = f"{prev_client} {client}".strip()
            elif not prev_client:
                prev[0] = client
            else:
                prev[0] = f"{prev_client} {client}".strip()
            continue
        if (
            not client
            and agency
            and not prev_agency
            and (_looks_like_wrapped_continuation(agency, prev_agency) or not prev_complete)
        ):
            prev[1] = agency if not prev_agency else f"{prev_agency} {agency}".strip()
            for i, value in enumerate((fees, ptime, responsible), start=2):
                if value and not _normalize_space(prev[i]):
                    prev[i] = value
            continue
        # Person-only crumb after a complete-looking previous row.
        if (
            not client
            and not agency
            and not fees
            and not ptime
            and responsible
            and (not _normalize_space(prev[4]) or str(prev[4]).endswith("/"))
        ):
            prev[4] = _join_personnel_cells(prev[4], responsible)
            continue
        out.append(cells)
    return out


# Reject fake table rows made only of leftover header tokens (e.g. a repeated
# "BE / TIME / RESPONSIBLE" fragment row from OCR/PDF text extraction).
_FAKE_TOKEN_SET = frozenset(
    {
        "be",
        "time",
        "responsible",
        "paid",
        "fees",
        "processing",
        "client step",
        "client steps",
        "agency action",
        "agency actions",
        "person responsible",
        "checklist of requirements",
        "where to secure",
        "processing time",
        "fees to be paid",
    }
)


def _is_fake_row(cells: tuple[str, ...]) -> bool:
    filled = [cell.strip().casefold() for cell in cells if cell.strip()]
    if not filled:
        return True
    return all(cell in _FAKE_TOKEN_SET for cell in filled)


# ---------------------------------------------------------------------------
# Requirements table (Checklist of Requirements | Where to Secure)
# ---------------------------------------------------------------------------


def _extract_requirements_table(
    lines: list[dict],
) -> tuple[list[RequirementV2], list[str], bool, bool, dict[str, Any]]:
    """Return (requirements, rejected, header_found, checklist_blank, table_debug)."""
    header_idx = _find_header_row(
        lines,
        (
            re.compile(r"checklist\s+of\s+requirements", re.I),
            re.compile(r"where\s+to\s+secure", re.I),
        ),
    )
    if header_idx is None:
        return [], [], False, False, {}

    end_idx = _find_section_end(
        lines,
        header_idx + 1,
        (re.compile(r"client\s+steps?", re.I), re.compile(r"^total\b", re.I)),
    )
    body_lines = lines[header_idx + 1 : end_idx]
    rows, rejected, geo_debug = _rows_to_columns(lines[header_idx], body_lines, column_count=2)
    merged = _merge_geometry_column_continuations(rows)
    merged = _merge_wrapped_rows(merged, primary_idx=[0], secondary_idx=[1])

    requirements: list[RequirementV2] = []
    dropped: list[dict[str, Any]] = []
    for row in merged:
        requirement = _strip_requirement_prefix(_normalize_space(row[0] if len(row) > 0 else ""))
        where = _normalize_space(row[1] if len(row) > 1 else "")
        if _is_fake_row((requirement, where)):
            if requirement or where:
                rejected.append(f"{requirement} | {where}".strip(" |"))
                dropped.append({"row": [requirement, where], "reason": "fake_header_row"})
            continue
        if not requirement:
            continue
        # Truly blank checklist markers ("None", "N/A", "-")
        if requirement.casefold() in {"none", "n/a", "na", "-", "—", "–", "nil"}:
            dropped.append({"row": [requirement, where], "reason": "blank_checklist_marker"})
            continue
        requirement, where = _repair_requirement_where_pair(requirement, where)
        requirements.append(RequirementV2(requirement=requirement, where_to_secure=where or NEEDS_REVIEW))

    checklist_blank = len(requirements) == 0
    debug = {
        **geo_debug,
        "logical_rows_before_finalize": merged,
        "dropped_rows": dropped,
    }
    return requirements, rejected, True, checklist_blank, debug


def _strip_requirement_prefix(text: str) -> str:
    """Remove OCR bullet/dash prefixes such as '⎯ Certificate of Registration'."""
    cleaned = _normalize_space(text)
    cleaned = re.sub(r"^[\s\-–—⎯•●▪◦‣]+", "", cleaned).strip()
    return cleaned


def _strip_step_number_prefix(text: str) -> str:
    """Strip leading table step numbers ('3. Accept…' → 'Accept…')."""
    return re.sub(r"^\d{1,3}[\.\)]\s+", "", _normalize_space(text)).strip()


def _repair_requirement_where_pair(requirement: str, where: str) -> tuple[str, str]:
    """Repair glued / split checklist pairs from OCR column bleeding."""
    req = _strip_requirement_prefix(requirement)
    secure = _normalize_space(where)
    # "NSTP Form NSTP Office" / "Dropping Form Registrar's Office" glued pairs.
    if req and (not secure or secure == NEEDS_REVIEW):
        glued = re.match(
            r"^(?P<req>.+)\s+(?P<office>"
            r"(?:Registrar(?:['’]?s)?\s+Office|Business\s+Affairs\s+Office|"
            r"Cashier(?:['’]?s)?\s+Office|Guidance\s+Office|NSTP\s+Office|"
            r"Dean(?:['’]?s)?\s+Office|OSAS|Library|"
            r"[A-Z][\w&.\-']+(?:\s+[A-Z][\w&.\-']+){0,3}\s+Office)"
            r")\s*$",
            req,
            flags=re.I,
        )
        if glued:
            return _normalize_space(glued.group("req")), _normalize_space(glued.group("office"))
    # "Certificate of Registration Registrar’s" + "Office"
    if req and secure.casefold() == "office":
        frag = re.match(
            r"^(?P<req>.+?)\s+(?P<head>"
            r"Registrar(?:['’]?s)?|Dean(?:['’]?s)?|NSTP|Cashier(?:['’]?s)?|OSAS|Library|"
            r"Business\s+Affairs|Guidance"
            r")\s*$",
            req,
            flags=re.I,
        )
        if frag:
            return (
                _normalize_space(frag.group("req")),
                f"{_normalize_space(frag.group('head'))} Office",
            )
    # "Student ID Business" + "Affairs Office"
    if req and re.search(r"\bBusiness\s*$", req, flags=re.I) and re.match(
        r"^Affairs\s+Office$", secure, flags=re.I
    ):
        return re.sub(r"\s+Business\s*$", "", req, flags=re.I).strip(), "Business Affairs Office"
    # "Certificate of Registration Registrar’s" + "Office" already covered;
    # also "… Registrar's" + empty handled by glued when Office is in req.
    return req, secure


# ---------------------------------------------------------------------------
# Step table (Client Step | Agency Action | Fees | Processing Time | Person Responsible)
# ---------------------------------------------------------------------------


def _extract_steps_table(
    lines: list[dict],
) -> tuple[list[StepV2], list[str], bool, int, dict[str, Any]]:
    header_idx = _find_header_row(
        lines,
        (re.compile(r"client\s+steps?", re.I), re.compile(r"agency\s+actions?", re.I)),
    )
    if header_idx is None:
        return [], [], False, 0, {}

    end_idx = _find_section_end(lines, header_idx + 1, (re.compile(r"^total\b", re.I),))
    body_lines = lines[header_idx + 1 : end_idx]
    rows, rejected, geo_debug = _rows_to_columns(lines[header_idx], body_lines, column_count=5)
    filtered_rows: list[list[str]] = []
    dropped: list[dict[str, Any]] = []
    for row in rows:
        cells = (list(row) + ["", "", "", "", ""])[:5]
        if _is_fake_row(tuple(cells)):
            if any(c.strip() for c in cells):
                rejected.append(" | ".join(filter(None, (_normalize_space(c) for c in cells))))
                dropped.append({"row": cells, "reason": "fake_header_row"})
            continue
        filtered_rows.append(cells)

    # Geometry column continuation first, then wrap/coalesce merges.
    merged = _merge_geometry_column_continuations(filtered_rows)
    merged = _merge_wrapped_rows(merged, primary_idx=[0, 1], secondary_idx=[2, 3, 4])
    merged = _coalesce_fragment_step_rows(merged)
    merged = _merge_geometry_column_continuations(merged)

    steps: list[StepV2] = []
    page_number_fee_hits = 0
    for row in merged:
        cells = (row + ["", "", "", "", ""])[:5]
        client, agency, fees, ptime, responsible = (_normalize_space(c) for c in cells)
        if _is_fake_row((client, agency, fees, ptime, responsible)):
            if any((client, agency, fees, ptime, responsible)):
                rejected.append(
                    " | ".join(filter(None, (client, agency, fees, ptime, responsible)))
                )
                dropped.append({"row": cells, "reason": "fake_header_row_after_merge"})
            continue
        if not client and not agency:
            if responsible and steps:
                steps[-1].person_responsible = _join_personnel_cells(
                    steps[-1].person_responsible, responsible
                )
            continue
        if _is_table_noise_cell(client) and not agency:
            continue
        # Client-only unfinished crumb — keep appending, never hard-drop priority cells.
        if client and not agency and not fees and not ptime and not responsible:
            if _is_personnel_title_fragment(client) and steps:
                steps[-1].person_responsible = _join_personnel_cells(
                    steps[-1].person_responsible, client
                )
                continue
            if steps and (
                _looks_like_wrapped_continuation(client, steps[-1].client_step)
                or _looks_like_short_client_continuation(client, steps[-1].client_step)
                or _client_looks_unfinished_geometry(steps[-1].client_step)
            ):
                steps[-1].client_step = f"{steps[-1].client_step} {client}".strip()
                continue
            # Keep incomplete step so rescue/deep repair can still see geometry cells.
            if _client_looks_unfinished_geometry(client) or not steps:
                steps.append(
                    StepV2(
                        client_step=client,
                        agency_action=NEEDS_REVIEW,
                        fees=NEEDS_REVIEW,
                        processing_time=NEEDS_REVIEW,
                        person_responsible=NEEDS_REVIEW,
                    )
                )
                continue
            rejected.append(client)
            dropped.append({"row": cells, "reason": "client_only_fragment_unmerged"})
            continue
        if _looks_like_page_number_fee(fees):
            page_number_fee_hits += 1
            fees = ""
        ptime, responsible = _split_time_and_person_cells(ptime, responsible)
        client, agency, fees, ptime, responsible = _finalize_step_cells(
            client=client,
            agency=agency,
            fees=fees,
            ptime=ptime,
            responsible=responsible,
            context=f"{client} {agency}",
        )
        # Attach OCR-split trailing nouns ("ID.") onto prior unfinished client.
        if (
            steps
            and client
            and _looks_like_short_client_continuation(client, steps[-1].client_step)
            and not _looks_like_new_step_marker(client)
        ):
            steps[-1].client_step = f"{steps[-1].client_step} {client}".strip()
            if agency and not _filled(steps[-1].agency_action):
                steps[-1].agency_action = agency
            if fees and (
                not _filled(steps[-1].fees) or str(steps[-1].fees) == NEEDS_REVIEW
            ):
                steps[-1].fees = fees
            if ptime and not _filled(steps[-1].processing_time):
                steps[-1].processing_time = ptime
            if responsible and (
                not _filled(steps[-1].person_responsible)
                or str(steps[-1].person_responsible).endswith("/")
            ):
                steps[-1].person_responsible = _join_personnel_cells(
                    steps[-1].person_responsible, responsible
                )
            continue
        steps.append(
            StepV2(
                client_step=client or NEEDS_REVIEW,
                agency_action=agency or NEEDS_REVIEW,
                fees=fees if fees else NEEDS_REVIEW,
                processing_time=ptime or NEEDS_REVIEW,
                person_responsible=responsible if responsible else NEEDS_REVIEW,
            )
        )

    no_step_rows_reason = None
    if not steps:
        no_step_rows_reason = "no_step_rows"
        if not filtered_rows:
            no_step_rows_reason = "no_geometry_or_text_body_rows"
        elif not merged:
            no_step_rows_reason = "all_rows_dropped_during_merge"

    debug = {
        **geo_debug,
        "filtered_column_rows": filtered_rows,
        "logical_rows_before_finalize": merged,
        "dropped_rows": dropped,
        "final_step_count": len(steps),
        "no_step_rows_reason": no_step_rows_reason,
    }
    return steps, rejected, True, page_number_fee_hits, debug


_NONE_FEE_VALUES = frozenset({"none", "n/a", "na", "nil", "free", "no fee", "no fees", "-", "—", "–"})

# Table header crumbs that bleed into fee/time/person cells via OCR column mixups.
_STEP_HEADER_CRUMB_PATTERNS = (
    r"fees?\s+to\s+be\s+paid",
    r"fees?\s+to\s+be",
    r"fees?\s+to",
    r"to\s+be\s+paid",
    r"be\s+paid",
    r"processing\s+time",
    r"processing",
    r"person\s+responsible",
    r"responsible\s+personnel",
    r"responsible",
    r"client\s+steps?",
    r"agency\s+actions?",
    r"\bfees?\b",
    r"\btime\b",
    r"\bperson\b",
    r"\bbe\b",
    r"\bpaid\b",
)


def _strip_table_header_crumbs(value: str) -> str:
    """Remove CLIENT STEPS / FEES TO BE PAID / TIME / RESPONSIBLE crumbs from a cell."""
    cleaned = _normalize_space(value)
    if not cleaned:
        return ""
    # Prefer longest matches first by iterating the ordered patterns repeatedly.
    previous = None
    while previous != cleaned:
        previous = cleaned
        for pattern in _STEP_HEADER_CRUMB_PATTERNS:
            cleaned = re.sub(rf"(?i)(?:^|\s){pattern}(?=\s|$)", " ", cleaned)
        cleaned = _normalize_space(cleaned)
    return cleaned.strip(" /|-–—:")


def _normalize_osas_personnel(value: str, *, context: str = "") -> str:
    """Normalize common OSAS Director/Chairperson/Staff OCR variants.

    Only remaps when the cell or surrounding context is OSAS-related so other
    offices keep their own titles.
    """
    cleaned = _strip_table_header_crumbs(_normalize_space(value))
    cleaned = re.sub(r"\s*/\s*", "/", cleaned)
    cleaned = re.sub(r"/{2,}", "/", cleaned).strip("/")
    blob = f"{cleaned} {context}".casefold()
    if "osas" not in blob and not cleaned.casefold().startswith("osas"):
        return cleaned
    lower = cleaned.casefold().replace(" ", "")
    # Collapse common incomplete OSAS title variants into the full form.
    if re.fullmatch(
        r"osas\s*director(?:/chairperson)?(?:/\s*staff)?|osas\s*director/\s*staff|"
        r"osas\s*director/chairperson/\s*staff",
        cleaned,
        flags=re.I,
    ) or lower in {
        "osasdirector/staff",
        "osasdirector/chairperson/staff",
        "osasdirector/chairperson",
        "osasdirector/",
    }:
        return "OSAS Director/Chairperson/Staff"
    if "osas" in lower and "director" in lower and "staff" in lower:
        return "OSAS Director/Chairperson/Staff"
    return cleaned


def _looks_like_page_number_fee(value: str) -> bool:
    """True when a fee cell is really a page/row number, not a fee amount."""
    cleaned = _normalize_space(value)
    if not cleaned:
        return False
    lower = cleaned.casefold()
    if re.fullmatch(r"page\s*\d{1,4}", lower):
        return True
    # Bare small integers without currency/unit are almost always page crumbs.
    if re.fullmatch(r"\d{1,3}", cleaned):
        return True
    return False


def _normalize_fee(value: str) -> str:
    cleaned = _strip_table_header_crumbs(_normalize_space(value))
    if not cleaned:
        return NEEDS_REVIEW
    if cleaned.casefold() in _NONE_FEE_VALUES:
        return "None"
    if _looks_like_page_number_fee(cleaned):
        return NEEDS_REVIEW
    # Contaminated "BE PAID None" / "FEES TO BE PAID N/A" already stripped — residual None.
    none_token = re.search(r"(?i)\b(none|n\s*/\s*a|n/?a|nil|free)\b", cleaned)
    if none_token and not re.search(r"(?i)\b(?:php|p\s*\d|\d+[.,]\d+)", cleaned):
        return "None"
    return cleaned


def _finalize_step_cells(
    *,
    client: str,
    agency: str,
    fees: str,
    ptime: str,
    responsible: str,
    context: str = "",
) -> tuple[str, str, str, str, str]:
    """Strip header crumbs and normalize fee/time/person before StepV2 creation."""
    client = _strip_step_number_prefix(_normalize_space(client))
    agency = _normalize_space(agency)
    fees = _normalize_fee(fees)
    ptime = _strip_table_header_crumbs(ptime)
    responsible = _normalize_osas_personnel(
        _strip_personnel_noise(_strip_table_header_crumbs(responsible)),
        context=context,
    )
    return client, agency, fees, ptime, responsible


# ---------------------------------------------------------------------------
# TOTAL line parsing (fees vs processing time)
# ---------------------------------------------------------------------------

_TIME_UNIT = r"(?:minutes?|mins?|hours?|hrs?|days?|seconds?)"
_TIME_ATOM_RE = re.compile(
    rf"(?:\d+\s+and\s+(?:1/2|½)|\d+(?:\.\d+)?(?:\s*[-–—]\s*\d+(?:\.\d+)?)?)\s*{_TIME_UNIT}"
    rf"(?:\s+and\s+\d+(?:\.\d+)?\s*{_TIME_UNIT})?",
    re.I,
)
_FEE_VALUE_RE = re.compile(
    r"\b(N\s*/\s*A|N/A|None|Free|Php\s*[\d,.]+(?:/\w+)?|P\s*[\d,.]+(?:/\w+)?|[\d,.]+(?:/\w+)?)\b",
    re.I,
)


def _split_total_line(value: str) -> tuple[str, str]:
    """Split a TOTAL line into (fees, processing_time).

    Examples:
        "None | 4 minutes"        -> ("None", "4 minutes")
        "P30.00/unit 25 minutes"  -> ("P30.00/unit", "25 minutes")
    """
    text = re.sub(r"\s*\|\s*", " ", _normalize_space(value)).strip(" |:-")
    if not text:
        return NEEDS_REVIEW, NEEDS_REVIEW

    fee = NEEDS_REVIEW
    processing = NEEDS_REVIEW

    time_matches = list(_TIME_ATOM_RE.finditer(text))
    if time_matches:
        start, end = time_matches[0].start(), time_matches[0].end()
        for match in time_matches[1:]:
            between = text[end : match.start()]
            if re.fullmatch(r"[\s,;/]+", between or ""):
                end = match.end()
            else:
                break
        processing = _normalize_space(text[start:end]).strip(" ,;/")
        remainder = (text[:start] + " " + text[end:]).strip(" |:-")
    else:
        remainder = text

    fee_match = _FEE_VALUE_RE.search(remainder)
    if fee_match:
        fee = _normalize_space(fee_match.group(1))
    elif remainder and not re.search(r"\b(?:minute|hour|day|second|hr)\b", remainder, flags=re.I):
        cleaned = remainder.strip(" |:-")
        if cleaned:
            fee = cleaned

    return fee or NEEDS_REVIEW, processing or NEEDS_REVIEW


def _extract_total(lines: list[dict]) -> tuple[str, str, str]:
    for line in lines:
        text_no_pipes = re.sub(r"\s*\|\s*", " ", _normalize_space(line["text"]))
        if not re.match(r"(?i)^total\b", text_no_pipes):
            continue
        remainder = re.sub(r"(?i)^total\s*(?:processing\s+time)?\s*:?\s*", "", text_no_pipes).strip()
        fee, processing = _split_total_line(remainder)
        return fee, processing, "total_line_regex"
    return NEEDS_REVIEW, NEEDS_REVIEW, "not_found"


# ---------------------------------------------------------------------------
# Extraction quality scoring
# ---------------------------------------------------------------------------


def _score_extraction_quality(
    *,
    service_title: str,
    office_division: str,
    classification: str,
    transaction_type: str,
    who_may_avail: str,
    requirements: list[RequirementV2],
    steps: list[StepV2],
    total_processing_time: str,
    page_number_fee_hits: int = 0,
    checklist_blank: bool = False,
) -> tuple[str, str]:
    """Return (extraction_quality, extraction_quality_reason).

    extraction_quality is one of: clean, needs_review, low_quality, rag_only.

    Clean is intentionally strict: office + who + a real title + at least one
    complete client/agency step (or requirements plus one complete step), with
    no excessive placeholders and no page-number fees.
    """
    if not _filled(service_title) or _looks_like_field_or_fragment_line(service_title):
        return "low_quality", "fragment_or_missing_title"

    has_office = _filled(office_division)
    has_class_or_txn = _filled(classification) or _filled(transaction_type)
    has_who = _filled(who_may_avail)
    real_requirements = [item for item in requirements if _filled(item.requirement)]
    real_steps = [step for step in steps if _filled(step.client_step) or _filled(step.agency_action)]
    complete_steps = [
        step
        for step in real_steps
        if _filled(step.client_step)
        and _filled(step.agency_action)
        and _filled(step.processing_time)
        and _filled(step.person_responsible)
    ]
    client_agency_steps = [
        step for step in real_steps if _filled(step.client_step) and _filled(step.agency_action)
    ]
    has_processing_time = _filled(total_processing_time) or any(
        _filled(step.processing_time) for step in real_steps
    )

    if (
        not has_office
        and not has_who
        and not has_class_or_txn
        and not real_requirements
        and not real_steps
        and not checklist_blank
    ):
        return "rag_only", "placeholder_only_body"

    if not has_office:
        return "needs_review", "missing_office_division"
    if not (real_requirements or real_steps or (checklist_blank and complete_steps)):
        return "low_quality", "no_requirements_or_steps"
    if not has_who:
        return "needs_review", "missing_who_may_avail"
    if not (has_who or has_class_or_txn):
        return "needs_review", "missing_who_or_classification"
    if page_number_fee_hits > 0:
        return "needs_review", "page_number_used_as_fee"
    if not client_agency_steps:
        return "needs_review", "no_complete_client_agency_step"
    if not complete_steps:
        return "needs_review", "no_complete_step_row"
    if not has_processing_time:
        return "needs_review", "missing_processing_time"

    # Count structured slots that would render as "Not specified" in the article body.
    slots: list[bool] = [has_office, has_who]
    for step in real_steps:
        slots.extend(
            [
                _filled(step.client_step),
                _filled(step.agency_action),
                _filled(step.fees) or str(step.fees or "").casefold() == "none",
                _filled(step.processing_time),
                _filled(step.person_responsible),
            ]
        )
    if slots:
        missing = sum(1 for filled in slots if not filled)
        if missing / len(slots) > 0.25 or missing >= 4:
            return "needs_review", "excessive_not_specified_fields"

    return "clean", "meets_clean_requirements"


# ---------------------------------------------------------------------------
# Service assembly
# ---------------------------------------------------------------------------


def _clean_block_text(text: str) -> str:
    lines = [re.sub(r"\s*\|\s*", " ", _normalize_space(line)) for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _build_service_from_block(block: _ServiceBlockSpan, flat: list[dict]) -> CharterServiceV2:
    lines = flat[block.start_idx : block.end_idx]
    raw_block_text = "\n".join(
        _normalize_space(line["text"]) for line in lines if _normalize_space(line["text"])
    )
    strategies = {line["strategy"] for line in lines}
    parser_strategy_used = (
        PARSER_STRATEGY_GEOMETRY if PARSER_STRATEGY_GEOMETRY in strategies else PARSER_STRATEGY_TEXT_FALLBACK
    )

    office_division = _extract_field(lines, _OFFICE_FIELD_RE)
    classification = _extract_field(lines, _CLASSIFICATION_FIELD_RE)
    transaction_type = _extract_field(lines, _TRANSACTION_FIELD_RE)
    who_may_avail = _extract_field(lines, _WHO_FIELD_RE)

    requirements, req_rejected, req_header_found, checklist_blank, req_table_debug = (
        _extract_requirements_table(lines)
    )
    steps, step_rejected, step_header_found, page_fee_hits, step_table_debug = (
        _extract_steps_table(lines)
    )
    total_fees, total_processing_time, _total_method = _extract_total(lines)
    total_fees = _normalize_fee(total_fees) if total_fees != NEEDS_REVIEW else total_fees

    # Final cell cleanup with office/title context (OSAS personnel, header crumbs).
    osas_context = f"{block.title} {office_division}"
    cleaned_steps: list[StepV2] = []
    for step in steps:
        _client, _agency, fees, ptime, person = _finalize_step_cells(
            client=step.client_step,
            agency=step.agency_action,
            fees=step.fees,
            ptime=step.processing_time,
            responsible=step.person_responsible,
            context=osas_context,
        )
        cleaned_steps.append(
            StepV2(
                client_step=_client or NEEDS_REVIEW,
                agency_action=_agency or NEEDS_REVIEW,
                fees=fees if fees else NEEDS_REVIEW,
                processing_time=ptime or NEEDS_REVIEW,
                person_responsible=person if person else NEEDS_REVIEW,
            )
        )
    steps = cleaned_steps

    if req_header_found and step_header_found:
        table_extraction_method = "requirements_and_steps_tables"
    elif step_header_found:
        table_extraction_method = "steps_table_only"
    elif req_header_found:
        table_extraction_method = "requirements_table_only"
    else:
        table_extraction_method = "no_table_detected"

    quality, reason = _score_extraction_quality(
        service_title=block.title,
        office_division=office_division,
        classification=classification,
        transaction_type=transaction_type,
        who_may_avail=who_may_avail,
        requirements=requirements,
        steps=steps,
        total_processing_time=total_processing_time,
        page_number_fee_hits=page_fee_hits,
        checklist_blank=checklist_blank,
    )

    # Only local block rejects + table rejects from this service's own tables.
    rejected_fragments = [*block.rejected_fragments, *req_rejected, *step_rejected]

    step_row_dicts = [
        {
            "client_step": step.client_step,
            "agency_action": step.agency_action,
            "fees": step.fees,
            "processing_time": step.processing_time,
            "person_responsible": step.person_responsible,
        }
        for step in steps
    ]
    parser_debug: dict[str, Any] = {
        "raw_service_block": raw_block_text,
        "cleaned_service_block": _clean_block_text(raw_block_text),
        "page_start": block.page_start,
        "page_end": block.page_end,
        "detected_service_title": block.title,
        "detected_office": office_division or NEEDS_REVIEW,
        "detected_requirements": [
            {"requirement": item.requirement, "where_to_secure": item.where_to_secure}
            for item in requirements
        ],
        "detected_step_rows": step_row_dicts,
        "detected_step_row_count": len(steps),
        "rejected_fragments": rejected_fragments,
        "extraction_quality": quality,
        "extraction_quality_reason": reason,
        "parser_strategy_used": parser_strategy_used,
        "table_extraction_method": table_extraction_method,
        "checklist_blank": checklist_blank,
        "no_step_rows_reason": step_table_debug.get("no_step_rows_reason"),
    }
    if _is_priority_visual_debug_title(block.title) or not steps:
        parser_debug["visual_table_debug"] = {
            "page_start": block.page_start,
            "page_end": block.page_end,
            "requirements_table": req_table_debug,
            "steps_table": step_table_debug,
            "why_merge_no_step_rows": step_table_debug.get("no_step_rows_reason"),
        }

    return CharterServiceV2(
        service_title=block.title,
        office_division=office_division or NEEDS_REVIEW,
        classification=classification or NEEDS_REVIEW,
        transaction_type=transaction_type or NEEDS_REVIEW,
        who_may_avail=who_may_avail or NEEDS_REVIEW,
        requirements=requirements,
        steps=steps,
        total_fees=total_fees,
        total_processing_time=total_processing_time,
        page_start=block.page_start,
        page_end=block.page_end,
        extraction_quality=quality,
        extraction_quality_reason=reason,
        checklist_blank=checklist_blank,
        parser_debug=parser_debug,
    )
