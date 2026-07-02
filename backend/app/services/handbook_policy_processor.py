"""Logical extraction for handbooks, manuals, and policy PDFs.

This module works after PDF text extraction. It removes recurring layout noise,
detects common policy hierarchy markers, and turns each logical unit into a
reviewable knowledge article. It intentionally avoids institution-specific
values so the same path can process other handbooks/manuals.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.services.text_cleaner import normalize_whitespace, repair_ocr_word_splits


HANDBOOK_POLICY_TYPE = "handbook_policy"
MetadataValue = str | int | list[str] | dict[str, list[str]] | None
MAX_UNIT_WORDS = 1000
KNOWN_CAMPUS_NAMES: tuple[str, ...] = (
    "Sta. Cruz",
    "San Pablo City",
    "Siniloan",
    "Los Baños",
    "All Campuses",
)
_CAMPUS_ALIASES = {
    "sta cruz": "Sta. Cruz",
    "sta. cruz": "Sta. Cruz",
    "santa cruz": "Sta. Cruz",
    "san pablo": "San Pablo City",
    "san pablo city": "San Pablo City",
    "siniloan": "Siniloan",
    "los baños": "Los Baños",
    "los banos": "Los Baños",
    "all campuses": "All Campuses",
}
_OCR_SPLIT_AUDIT_PATTERNS: tuple[tuple[str, str], ...] = (
    ("firsttime", r"\bfirsttime\b"),
    ("cam pus", r"\bcam\s+pus(?:es)?\b"),
    ("Uni versity", r"\buni\s+versit(?:y|ies)\b"),
    ("lim ited", r"\blim\s+ited\b"),
    ("follow ing", r"\bfollow\s+ing\b"),
)

FRONT_MATTER_TITLES = (
    "message of the university president",
    "message from the university president",
    "message of the president",
    "president's message",
    "vision",
    "mission",
    "quality policy",
    "lspu quality policy",
    "prayer",
    "foreword",
    "handbook owner information",
    "owner information",
)

MAJOR_HEADING_PATTERNS = (
    r"\bhistorical\s+development\b",
    r"\bofficials?\b",
    r"\bboard\s+of\b",
    r"\badministrative\s+officials?\b",
    r"\bcurricular\s+offerings?\b",
    r"\bacademic\s+polic(?:y|ies)\b",
    r"\badmission\b",
    r"\bonline\s+admission\b",
    r"\bclassification\s+of\s+students?\b",
    r"\bgrading\s+system\b",
    r"\bretention\s+(?:polic(?:y|ies)|requirements?)\b",
    r"\bscholastic\s+delinquency\b",
    r"\bvalidation\s+requirements?\b",
    r"\battendance\b",
)

PROGRAM_GROUP_RE = re.compile(
    r"^(college|school|institute|graduate studies|senior high school|laboratory school)\b",
    flags=re.I,
)

DEGREE_PREFIX_ABBREVIATIONS: tuple[tuple[str, str], ...] = (
    ("Bachelor of Science", "BS"),
    ("Bachelor of Arts", "BA"),
    ("Bachelor of Elementary Education", "BEEd"),
    ("Bachelor of Secondary Education", "BSEd"),
)

DEGREE_LINE_RE = re.compile(
    r"^(?:[-*]\s*)?(?:"
    r"B(?:S|A|SEd|EEd)\b|"
    r"M(?:S|A)\b|"
    r"PhD\b|"
    r"Juris\s+Doctor\b|"
    r"Doctor\s+of\s+Jurisprudence\b|"
    r"Bachelor\s+of\s+Laws\b|"
    r"Doctor\b|"
    r"Bachelor\b|"
    r"Master\b"
    r")",
    flags=re.I,
)

@dataclass(frozen=True)
class HandbookKnowledgeUnit:
    title: str
    content: str
    raw_text: str
    metadata: dict[str, MetadataValue]

    @property
    def article_text(self) -> str:
        lines = [self.title.strip()]
        path = _format_path(self.metadata)
        if path and _canonical_heading_text(path) != _canonical_heading_text(self.title):
            lines.append(path)
        if self.content.strip():
            lines.append(self.content.strip())
        return "\n\n".join(lines).strip()


@dataclass(frozen=True)
class HandbookPolicyDocument:
    document_type: str
    source_title: str
    doc_no: str | None
    cleaned_text: str
    raw_text: str
    units: list[HandbookKnowledgeUnit] = field(default_factory=list)

    @property
    def formatted_articles(self) -> str:
        return "\n\n---\n\n".join(unit.article_text for unit in self.units).strip()

    def diagnostic_report(self, *, sample_size: int = 10) -> dict:
        return build_handbook_diagnostic_report(self, sample_size=sample_size)


@dataclass
class _Heading:
    level: str
    value: str
    title: str
    page: int
    line_index: int
    inline_body: str = ""


@dataclass
class _Line:
    text: str
    page: int
    is_toc: bool = False


HEADER_FOOTER_LABELS = (
    "institution",
    "doc. no.",
    "doc no.",
    "type",
    "revision no.",
    "revision",
    "title",
    "date",
)


def is_handbook_policy_text(text: str) -> bool:
    """Return True when text has handbook/manual/policy structure signals."""
    if not text.strip():
        return False

    lower = text.lower()
    hierarchy_hits = sum(
        1
        for pattern in (
            r"\bchapter\s+[ivxlcdm\d]+",
            r"\barticle\s+[ivxlcdm\d]+",
            r"\bsec(?:tion)?\.?\s+\d",
            r"\b\d+\.\d+(?:\.\d+)*\b",
            r"\bappendix(?:es)?\b",
        )
        if re.search(pattern, lower, flags=re.I | re.M)
    )
    policy_hits = sum(
        keyword in lower
        for keyword in (
            "handbook",
            "manual",
            "policy",
            "policies",
            "student affairs",
            "admission",
            "requirements",
        )
    )
    label_hits = sum(label in lower for label in HEADER_FOOTER_LABELS)
    return hierarchy_hits >= 2 or (hierarchy_hits >= 1 and policy_hits >= 2) or (policy_hits >= 2 and label_hits >= 2)


def build_handbook_policy_document(
    *,
    raw_text: str,
    page_texts: list[str],
    source_title: str | None = None,
) -> HandbookPolicyDocument:
    lines = _clean_page_lines(page_texts)
    cleaned_text = normalize_whitespace("\n".join(line.text for line in lines))
    metadata = _extract_document_metadata(raw_text, cleaned_text)
    resolved_title = source_title or metadata.get("source_title") or "Untitled handbook/policy"
    doc_no = metadata.get("doc_no")

    units = _build_units(lines, source_title=resolved_title, doc_no=doc_no)
    if not units and cleaned_text:
        filtered_lines = _remove_toc_regions(lines)
        fallback_text = normalize_whitespace("\n".join(line.text for line in filtered_lines))
        if not fallback_text and any(_is_contents_heading(line.text) for line in lines):
            fallback_text = ""
        elif not fallback_text:
            fallback_text = cleaned_text
        if fallback_text:
            units = [
                HandbookKnowledgeUnit(
                    title=resolved_title,
                    content=_knowledge_content(fallback_text),
                    raw_text=fallback_text,
                    metadata={
                        "source_title": resolved_title,
                        "doc_no": doc_no,
                        "document_type": HANDBOOK_POLICY_TYPE,
                        "content_type": "policy",
                        "chapter": None,
                        "article": None,
                        "section": None,
                        "appendix": None,
                        "page_start": filtered_lines[0].page if filtered_lines else (lines[0].page if lines else None),
                        "page_end": filtered_lines[-1].page if filtered_lines else (lines[-1].page if lines else None),
                    },
                )
            ]

    return HandbookPolicyDocument(
        document_type=HANDBOOK_POLICY_TYPE,
        source_title=resolved_title,
        doc_no=doc_no,
        cleaned_text=cleaned_text,
        raw_text=raw_text,
        units=units,
    )


def _clean_page_lines(page_texts: list[str]) -> list[_Line]:
    repeated = _repeated_edge_lines(page_texts)
    cleaned: list[_Line] = []
    for page_number, page in enumerate(page_texts, start=1):
        for raw_line in page.splitlines():
            line = _clean_line(raw_line)
            if not line:
                continue
            if line in repeated:
                continue
            if _is_layout_header_footer(line):
                continue
            cleaned.extend(_Line(text=part, page=page_number) for part in _split_embedded_numbered_headings(line))
    return _merge_wrapped_heading_lines(cleaned)


def _repeated_edge_lines(page_texts: list[str]) -> set[str]:
    counts: dict[str, int] = {}
    for page in page_texts:
        lines = [_clean_line(line) for line in page.splitlines()]
        lines = [line for line in lines if line]
        for candidate in set(lines[:8] + lines[-8:]):
            if _is_probable_content_heading(candidate) and not _is_repeated_layout_heading_candidate(candidate):
                continue
            counts[candidate] = counts.get(candidate, 0) + 1
    threshold = max(2, int(len(page_texts) * 0.5))
    return {line for line, count in counts.items() if count >= threshold}


def _is_repeated_layout_heading_candidate(line: str) -> bool:
    heading = _parse_heading(line)
    return bool(heading and heading.get("level") in {"chapter", "major", "front_matter"})


def _clean_line(line: str) -> str:
    line = line.strip()
    line = re.sub(r"[ \t]+", " ", line)
    line = line.strip(" |")
    line = _repair_ocr_word_breaks(line)
    return line


def _repair_ocr_word_breaks(text: str) -> str:
    return repair_ocr_word_splits(text)


def _split_embedded_numbered_headings(line: str) -> list[str]:
    if len(re.findall(r"\b\d+\.\d+(?:\.\d+)*\.?\s+[A-Z]", line)) < 2:
        return [line]

    markers = [
        match.start()
        for match in re.finditer(r"(?<!\S)\d+\.\d+(?:\.\d+)*\.?\s+(.{2,80}?)(?:\.\s+|$)", line)
        if _looks_like_numbered_definition_title(match.group(1).strip())
    ]
    if len(markers) < 2:
        return [line]

    parts: list[str] = []
    for index, start in enumerate(markers):
        end = markers[index + 1] if index + 1 < len(markers) else len(line)
        part = line[start:end].strip()
        if part:
            parts.append(part)
    prefix = line[: markers[0]].strip()
    return ([prefix] if prefix else []) + parts


def _merge_wrapped_heading_lines(lines: list[_Line]) -> list[_Line]:
    merged: list[_Line] = []
    index = 0
    while index < len(lines):
        current = lines[index]
        if index + 1 < len(lines):
            next_line = lines[index + 1]
            joined = _join_wrapped_heading_text(current.text, next_line.text)
            if joined:
                merged.append(_Line(text=joined, page=current.page, is_toc=current.is_toc or next_line.is_toc))
                index += 2
                continue
        merged.append(current)
        index += 1
    return merged


def _join_wrapped_heading_text(left: str, right: str) -> str | None:
    left = left.strip()
    right = right.strip()
    if not left or not right:
        return None
    if _is_toc_line(left) or _is_toc_line(right):
        return None
    if _has_policy_body_signal(right):
        return None

    if _looks_like_broken_heading_word(left, right):
        candidate = f"{left}{right}"
        if _parse_heading(candidate) or _looks_like_policy_topic(candidate):
            return candidate

    if _starts_with_hierarchy_marker(left) and _looks_like_heading_continuation(right) and _heading_wrap_needed(left, right):
        candidate = normalize_whitespace(f"{left} {right}")
        if _parse_heading(candidate):
            return candidate

    if left.lower().endswith((" and", " of", " for", " to", " in")) and _looks_like_heading_continuation(right):
        candidate = normalize_whitespace(f"{left} {right}")
        if _parse_heading(candidate) or _looks_like_policy_topic(candidate):
            return candidate

    return None


def _heading_wrap_needed(left: str, right: str) -> bool:
    if re.match(r"^(?:and|or|of|for|to|in)\b", right, flags=re.I):
        return True
    parsed = _parse_heading(left)
    title = str(parsed.get("title") or parsed.get("value") or "") if parsed else left
    if parsed and parsed.get("level") in {"article", "section"} and len(right.split()) <= 2 and re.search(r"[/&]", title):
        return True
    return title.lower().endswith((" and", " or", " of", " for", " to", " in"))


def _looks_like_heading_continuation(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if _starts_with_hierarchy_marker(stripped):
        return False
    if len(stripped.split()) > 8:
        return False
    if stripped.endswith((".", ";")):
        return False
    return bool(re.match(r"^[A-Za-z][A-Za-z ,&'()/.-]*$", stripped))


def _looks_like_broken_heading_word(left: str, right: str) -> bool:
    if not re.search(r"[A-Za-z]$", left) or not re.match(r"^[a-z]{2,}\b", right):
        return False
    tail = left.rsplit(" ", 1)[-1]
    if tail.lower() in {"and", "or", "of", "for", "to", "in"}:
        return False
    if _broken_word_remainder_looks_like_body(right):
        return False
    return len(tail) >= 3 and len(right.split()) <= 3


def _broken_word_remainder_looks_like_body(text: str) -> bool:
    match = re.match(r"^[a-z]{2,}\b\s*(.*)$", text.strip(), flags=re.S)
    if not match:
        return False
    remainder = match.group(1).strip()
    if not remainder:
        return False
    return bool(
        re.search(r"\b(?:sec|sect|section)\.?\s*\d", remainder, flags=re.I)
        or re.search(r"\d", remainder)
        or _has_policy_body_signal(remainder)
    )


def _is_layout_header_footer(line: str) -> bool:
    lower = line.lower().strip(" :")
    if _has_form_placeholders(line):
        return False
    if re.fullmatch(r"page\s*:?\s*\d+\s*(?:of|/)\s*\d+", lower):
        return True
    if re.fullmatch(r"\d+\s*(?:of|/)\s*\d+", lower):
        return True
    if re.fullmatch(r"(?:institution|doc\.?\s*no\.?|type|revision\s*no\.?|title|date)\s*:?.*", lower):
        return True
    if any(lower.startswith(f"{label}:") for label in HEADER_FOOTER_LABELS):
        return True
    return False


def _is_probable_content_heading(line: str) -> bool:
    return _parse_heading(line) is not None


def _extract_document_metadata(raw_text: str, cleaned_text: str) -> dict[str, str]:
    combined = f"{raw_text}\n{cleaned_text}"
    metadata: dict[str, str] = {}
    doc_match = re.search(r"\bdoc\.?\s*no\.?\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-/\. ]{3,})", combined, flags=re.I)
    if doc_match:
        metadata["doc_no"] = doc_match.group(1).strip(" |")

    title_match = re.search(r"\btitle\s*[:\-]?\s*([^\n|]{5,})", combined, flags=re.I)
    if title_match:
        metadata["source_title"] = _title_case(title_match.group(1).strip(" |"))
    else:
        handbook_match = re.search(r"^(.{0,80}\b(?:handbook|manual|policy|policies)\b.{0,80})$", cleaned_text, flags=re.I | re.M)
        if handbook_match:
            metadata["source_title"] = _title_case(handbook_match.group(1).strip())
    return metadata


def _build_units(
    lines: list[_Line],
    *,
    source_title: str,
    doc_no: str | None,
) -> list[HandbookKnowledgeUnit]:
    lines = _remove_toc_regions(lines)
    headings: list[tuple[int, _Heading]] = []
    scan_context: dict[str, str | None] = {"chapter": None, "article": None, "section": None}
    for index, line in enumerate(lines):
        heading = _parse_heading(line.text)
        if not heading and _is_graduate_studies_major_heading(line.text, scan_context):
            heading = {"level": "major", "value": "Graduate Studies", "title": "", "inline_body": ""}
        if heading:
            heading = _nest_policy_topic_major_heading(heading, scan_context)
            parsed_heading = _Heading(**heading, page=line.page, line_index=index)
            headings.append((index, parsed_heading))
            _update_context(scan_context, parsed_heading)
    headings = _drop_citation_reference_headings(headings, lines)

    if not headings:
        return []

    units: list[HandbookKnowledgeUnit] = []
    context: dict[str, str | None] = {"chapter": None, "article": None, "section": None}

    for heading_index, (line_index, heading) in enumerate(headings):
        _update_context(context, heading)
        next_line_index = headings[heading_index + 1][0] if heading_index + 1 < len(headings) else len(lines)
        body_lines = lines[line_index + 1 : next_line_index]
        body_lines = _drop_duplicate_heading_lines(body_lines, heading)
        body_parts = [heading.inline_body] if heading.inline_body else []
        body_parts.extend(line.text for line in body_lines)
        body = normalize_whitespace("\n".join(body_parts))
        if not body.strip():
            continue
        if _is_toc_like_block(lines[line_index].text, body):
            continue
        if _is_reference_only_unit(lines[line_index].text, body):
            continue

        page_start = heading.page
        page_end = body_lines[-1].page if body_lines else heading.page
        title = _unit_title(heading)
        title, body = _repair_title_body_word_split(title, body)
        content_type = _content_type(title=title, body=body, heading=heading, context=context)
        appendix = _appendix_label(heading, context)
        content = _knowledge_content(body, content_type=content_type)
        raw_unit_text = normalize_whitespace(f"{lines[line_index].text}\n{body}")
        toc_origin = lines[line_index].is_toc or any(line.is_toc for line in body_lines)
        unit = HandbookKnowledgeUnit(
            title=title,
            content=content,
            raw_text=raw_unit_text,
            metadata={
                "source_title": source_title,
                "doc_no": doc_no,
                "document_type": HANDBOOK_POLICY_TYPE,
                "content_type": content_type,
                "chapter": context["chapter"],
                "article": context["article"],
                "section": context["section"],
                "appendix": appendix,
                "page_start": page_start,
                "page_end": page_end,
                "toc_origin": toc_origin,
            },
        )
        for split_unit in _split_embedded_form_units(unit, body):
            units.extend(_split_oversized_unit(split_unit))

    return _filter_non_knowledge_units(_merge_short_definition_units(units))


def _is_graduate_studies_major_heading(line: str, context: dict[str, str | None]) -> bool:
    if _canonical_heading_text(line) != "graduate studies":
        return False
    current_chapter = _canonical_heading_text(context.get("chapter"))
    if current_chapter and "curricular offerings" in current_chapter:
        return False
    return True


def _nest_policy_topic_major_heading(
    heading: dict[str, str],
    context: dict[str, str | None],
) -> dict[str, str]:
    if heading.get("level") != "major":
        return heading
    current_chapter = _canonical_heading_text(context.get("chapter"))
    if current_chapter not in {"undergraduate academic policies", "graduate studies"}:
        return heading
    value = str(heading.get("value") or "")
    if _is_document_level_major_heading(value):
        return heading
    nested = dict(heading)
    nested["level"] = "section"
    return nested


def _is_document_level_major_heading(value: str) -> bool:
    normalized = _canonical_heading_text(value)
    return normalized in {
        "administrative officials",
        "curricular offerings",
        "graduate studies",
        "undergraduate academic policies",
        "historical development",
    } or "board of" in normalized


def _drop_citation_reference_headings(
    headings: list[tuple[int, _Heading]],
    lines: list[_Line],
) -> list[tuple[int, _Heading]]:
    return [
        (line_index, heading)
        for line_index, heading in headings
        if not _is_citation_reference_heading(line_index, heading, lines)
    ]


def _is_citation_reference_heading(line_index: int, heading: _Heading, lines: list[_Line]) -> bool:
    if heading.level not in {"article", "section"}:
        return False
    current = lines[line_index].text
    next_text = lines[line_index + 1].text if line_index + 1 < len(lines) else ""
    combined = normalize_whitespace(f"{current} {next_text}")

    if re.search(r"\b(?:memo(?:randum)?|ched|deped|bor\s+resolution)\b", combined, flags=re.I):
        return True
    if re.search(r"\bbased\s+on\b", combined, flags=re.I) and re.search(r"\b(?:memo(?:randum)?|ched|deped|bor\s+resolution|article\s+[ivxlcdm]+)\b", combined, flags=re.I):
        return True

    if heading.level == "article" and re.search(r"\b(?:sec|sect|section)\.?\s*\d", combined, flags=re.I):
        if re.search(r"\)", combined) or _looks_like_title_body_word_split(_unit_title(heading), next_text):
            return True

    return False


def _unit_from_parts(
    *,
    title: str,
    content: str,
    raw_text: str,
    metadata: dict[str, MetadataValue],
) -> HandbookKnowledgeUnit:
    return HandbookKnowledgeUnit(
        title=title,
        content=content,
        raw_text=raw_text,
        metadata=metadata,
    )


def _remove_toc_regions(lines: list[_Line]) -> list[_Line]:
    toc_pages = {line.page for line in lines if _is_contents_heading(line.text)}
    if toc_pages:
        lines = [line for line in lines if line.page not in toc_pages]

    result: list[_Line] = []
    in_toc = False
    toc_hits = 0
    toc_page: int | None = None

    for line in lines:
        if _is_contents_heading(line.text):
            in_toc = True
            toc_hits = 0
            toc_page = line.page
            continue

        if in_toc:
            if line.page == toc_page and _looks_like_toc_region_continuation(line.text):
                toc_hits += 1
                continue
            if toc_hits >= 3:
                if _is_probable_content_heading(line.text) and not _is_toc_line(line.text):
                    in_toc = False
                    toc_page = None
                else:
                    result.append(_Line(text=line.text, page=line.page, is_toc=True))
                    continue
            else:
                continue

        if _is_toc_line(line.text):
            continue
        result.append(line)

    return result


def _is_contents_heading(line: str) -> bool:
    return bool(re.fullmatch(r"(table\s+of\s+contents|contents)", line.strip(), flags=re.I))


def _is_toc_line(line: str) -> bool:
    stripped = line.strip()
    if _has_dot_leaders(stripped) and re.search(r"(?:\|\s*)?\d+\s*$", stripped):
        return True
    if re.match(r"^(chapter|article|appendix|sec(?:tion)?\.?|\d+\.\d+)", stripped, flags=re.I) and re.search(r"(?:\.{2,}|\s{2,})\s*\d+\s*$", stripped):
        return True
    if re.match(r"^(chapter|article|appendix|sec(?:tion)?\.?)\s+[A-Z0-9IVXLCDM]+[:\-.]?\s+.+$", stripped, flags=re.I) and re.search(r"(?:\.{2,}|…+|â€¦+)\s*\|?\s*\d+\s*$", stripped):
        return True
    if re.match(r"^[A-Z][A-Za-z0-9 ,&'()/.-]{4,}(?:\.{2,}|\s{2,})\d{1,4}$", stripped):
        return True
    if _looks_like_toc_page_entry(stripped):
        return True
    return False


def _looks_like_toc_region_continuation(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    if _is_toc_line(stripped):
        return True
    if _has_dot_leaders(stripped):
        return True
    if re.match(r"^(article|chapter|appendix|sec(?:tion)?\.?)\s+[A-Z0-9IVXLCDM]+[:\-.]?\s*.*$", stripped, flags=re.I):
        return True
    if re.search(r"(?:^|\s)\|?\s*\d{1,4}$", stripped) and len(stripped.split()) <= 12:
        return True
    if stripped.endswith(",") and len(stripped.split()) <= 8:
        return True
    return False


def _has_dot_leaders(text: str) -> bool:
    return bool(re.search(r"(?:\.{3,}|…{1,}|(?:\.\s*){3,})", text))


def _has_dot_leaders(text: str) -> bool:
    if re.search(r"(?:\.{2,}|(?:\.\s*){2,})", text):
        return True
    return "…" in text or "â€¦" in text


def _looks_like_toc_page_entry(line: str) -> bool:
    if re.match(r"^[-*•]|\(?[A-Za-z0-9]+\)?[\.)]\s+", line):
        return False
    match = re.match(r"^(.{4,90}?)\s+(\d{1,4})$", line)
    if not match:
        return False
    title = match.group(1).strip()
    if re.search(r"[.!?:;|]$", title):
        return False
    if re.search(r"\b(page|year|no\.?|percent|grade|gwa)\b", title, flags=re.I):
        return False
    if re.match(r"^(chapter|article|appendix|sec(?:tion)?\.?)\b", title, flags=re.I):
        return True
    words = title.split()
    if len(words) > 8:
        return False
    title_like = sum(1 for word in words if word[:1].isupper() or word.isupper())
    return len(words) >= 2 and title_like / len(words) >= 0.6


def _looks_like_title_page_reference(line: str) -> bool:
    match = re.fullmatch(r"([A-Z][A-Za-z0-9 ,&'()/.-]{2,90})\s+(\d{1,4})", line.strip())
    if not match:
        return False
    title = match.group(1).strip()
    if re.search(r"[.!?:;|]$", title):
        return False
    if re.search(r"\b(page|year|no\.?|percent|grade|gwa|unit)\b", title, flags=re.I):
        return False
    words = title.split()
    if not (1 <= len(words) <= 8):
        return False
    title_like = sum(1 for word in words if word[:1].isupper() or word.isupper())
    return title_like / len(words) >= 0.6


def _is_toc_like_block(title: str, body: str) -> bool:
    lines = [line.strip() for line in f"{title}\n{body}".splitlines() if line.strip()]
    if not lines:
        return False
    toc_count = sum(1 for line in lines if _is_toc_line(line))
    dot_count = sum(1 for line in lines if _has_dot_leaders(line))
    if _is_contents_heading(lines[0]):
        return True
    return len(lines) >= 4 and (toc_count / len(lines) >= 0.55 or dot_count >= 2)


def _is_reference_only_unit(title: str, body: str) -> bool:
    lines = [line.strip() for line in f"{title}\n{body}".splitlines() if line.strip()]
    if not lines:
        return True
    if any(_has_policy_body_signal(line) for line in lines):
        return False
    reference_count = sum(1 for line in lines if _is_toc_line(line) or _is_hierarchy_or_page_reference(line))
    return reference_count == len(lines)


def _is_hierarchy_or_page_reference(line: str) -> bool:
    stripped = line.strip(" .:-")
    return bool(
        re.fullmatch(r"\d{1,4}", stripped)
        or re.fullmatch(r"(?:chapter|article|appendix|sec(?:tion)?\.?)\s+[A-Z0-9IVXLCDM]+(?:\s*[:\-.]?\s*[A-Za-z ]{1,80})?", stripped, flags=re.I)
        or re.fullmatch(r"[A-Z][A-Za-z ,&'()/.-]{2,80}\s+\d{1,4}", stripped)
        or _looks_like_title_page_reference(line)
    )


def _filter_non_knowledge_units(units: list[HandbookKnowledgeUnit]) -> list[HandbookKnowledgeUnit]:
    return [unit for unit in units if not _is_leaked_toc_or_reference_unit(unit)]


def _is_leaked_toc_or_reference_unit(unit: HandbookKnowledgeUnit) -> bool:
    title = unit.title.strip()
    content = unit.content.strip()
    raw_text = unit.raw_text.strip()
    path = _format_path(unit.metadata)
    if _has_dot_leaders(title):
        return True
    if _is_toc_line(content) or _is_toc_line(raw_text):
        return True
    if _has_standalone_page_number_path_segment(path):
        return True
    if re.fullmatch(r"(?:p(?:age)?\.?\s*)?\d{1,4}", content, flags=re.I):
        return True
    if unit.metadata.get("toc_origin") and _word_count(content) < 35 and re.search(r"\b\d{1,4}\b", f"{title} {content} {raw_text}"):
        return True
    if title.endswith(",") and _word_count(content) < 35 and not _has_strong_policy_body_signal(content):
        return True
    raw_body_lines = _raw_body_lines_without_title(raw_text, title)
    if raw_body_lines and all(_is_hierarchy_or_page_reference(line) for line in raw_body_lines):
        return True
    content_lines = [line.strip() for line in content.splitlines() if line.strip()]
    if content_lines and all(_is_hierarchy_or_page_reference(line) for line in content_lines):
        return True
    if content_lines and not any(_has_policy_body_signal(line) for line in content_lines):
        if all(_is_toc_line(line) or _is_hierarchy_or_page_reference(line) for line in content_lines):
            return True
    return False


def _raw_body_lines_without_title(raw_text: str, title: str) -> list[str]:
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    if lines and _canonical_heading_text(lines[0]).endswith(_canonical_heading_text(title)):
        lines = lines[1:]
    return lines


def _has_standalone_page_number_path_segment(path: str) -> bool:
    return any(re.fullmatch(r"\d{1,4}", part.strip()) for part in path.split(">"))


def _has_policy_body_signal(line: str) -> bool:
    if re.search(r"\b(shall|must|may|should|required|submit|eligible|penalt|fee|grade|percent|deadline|within|before|after|unless|provided|student who|applicant who)\b", line, flags=re.I):
        return True
    if re.search(r"[.;:]", line) and len(line.split()) >= 5:
        return True
    return False


def _has_strong_policy_body_signal(line: str) -> bool:
    return bool(
        re.search(
            r"\b(shall|must|should|required|requirements?|procedure|procedures|eligible|penalt|deadline|fee|grade|submit|comply)\b",
            line,
            flags=re.I,
        )
    )


def _drop_duplicate_heading_lines(body_lines: list[_Line], heading: _Heading) -> list[_Line]:
    if not body_lines:
        return body_lines
    duplicates = {
        _canonical_heading_text(heading.value),
        _canonical_heading_text(heading.title),
        _canonical_heading_text(_heading_label(heading)),
        _canonical_heading_text(_unit_title(heading)),
    }
    index = 0
    while index < len(body_lines) and _canonical_heading_text(body_lines[index].text) in duplicates:
        index += 1
    return body_lines[index:]


def _canonical_heading_text(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def _content_type(
    *,
    title: str,
    body: str,
    heading: _Heading,
    context: dict[str, str | None],
) -> str:
    haystack = f"{title}\n{body}".lower()
    if heading.level == "front_matter":
        if "prayer" in haystack:
            return "prayer"
        return "message"
    if heading.level == "appendix" or "appendix" in (context.get("section") or "").lower():
        if _has_form_placeholders(body) or re.search(r"\b(form|slip|note|pledge|consent)\b", haystack):
            return "form_template"
        return "appendix"
    if _looks_like_program_listing(title, body):
        return "program_listing"
    if re.search(r"\b(requirements?|must submit|shall submit|credentials?)\b", haystack):
        return "requirement"
    if re.search(r"\b(procedure|steps?|process|application)\b", haystack):
        return "procedure"
    if re.search(r"\b(offenses?|violations?|penalt(?:y|ies)|sanctions?|disciplin|unauthorized|unrecognized)\b", haystack):
        return "disciplinary_rule"
    if re.search(r"\b(office|director|dean|contact|located|campus)\b", haystack):
        return "office_information"
    return "policy"


def _appendix_label(heading: _Heading, context: dict[str, str | None]) -> str | None:
    if heading.level == "appendix":
        return _heading_label(heading)
    section = context.get("section")
    if section and section.lower().startswith("appendix"):
        return section
    return None


def _looks_like_program_listing(title: str, body: str) -> bool:
    combined = f"{title}\n{body}"
    if re.search(r"\b(curricular offerings?|programs? offered|degree programs?)\b", combined, flags=re.I):
        return True
    program_hits = len(re.findall(r"\b(?:BS|BA|BSEd|BEEd|MA|MS|PhD|Doctor|Bachelor|Master)\b", combined))
    return program_hits >= 3


def _split_oversized_unit(unit: HandbookKnowledgeUnit) -> list[HandbookKnowledgeUnit]:
    content_type = str(unit.metadata.get("content_type") or "")
    if content_type == "program_listing":
        split = _split_program_listing(unit)
        if split != [unit]:
            return split

    if _word_count(unit.content) <= MAX_UNIT_WORDS:
        return [unit]

    chunks = _split_long_text(unit.content, max_words=MAX_UNIT_WORDS)
    if len(chunks) <= 1:
        return [unit]

    units: list[HandbookKnowledgeUnit] = []
    for index, chunk in enumerate(chunks, start=1):
        metadata = dict(unit.metadata)
        metadata["section"] = metadata.get("section") or unit.title
        units.append(
            HandbookKnowledgeUnit(
                title=f"{unit.title} - Part {index}",
                content=chunk,
                raw_text=unit.raw_text,
                metadata=metadata,
            )
        )
    return units


def _merge_short_definition_units(units: list[HandbookKnowledgeUnit]) -> list[HandbookKnowledgeUnit]:
    merged: list[HandbookKnowledgeUnit] = []
    buffer: list[HandbookKnowledgeUnit] = []

    def flush() -> None:
        nonlocal buffer
        if len(buffer) < 3:
            merged.extend(buffer)
            buffer = []
            return

        first = buffer[0]
        metadata = dict(first.metadata)
        metadata["section"] = first.metadata.get("article") or first.metadata.get("chapter")
        title = _group_title(first)
        content_lines: list[str] = []
        raw_lines: list[str] = []
        for item in buffer:
            content_lines.append(f"{item.title}: {item.content}")
            raw_lines.append(item.raw_text)
        metadata["page_start"] = buffer[0].metadata.get("page_start")
        metadata["page_end"] = buffer[-1].metadata.get("page_end")
        merged.append(
            HandbookKnowledgeUnit(
                title=title,
                content=normalize_whitespace("\n".join(content_lines)),
                raw_text=normalize_whitespace("\n\n".join(raw_lines)),
                metadata=metadata,
            )
        )
        buffer = []

    for unit in units:
        if _is_short_definition_unit(unit) and (
            not buffer or _same_definition_group(buffer[-1], unit)
        ):
            buffer.append(unit)
            continue
        flush()
        if _is_short_definition_unit(unit):
            buffer.append(unit)
        else:
            merged.append(unit)

    flush()
    return merged


def _is_short_definition_unit(unit: HandbookKnowledgeUnit) -> bool:
    if unit.metadata.get("content_type") != "policy":
        return False
    if re.search(r"\bstudent\b", unit.title, flags=re.I):
        return False
    if _word_count(unit.content) > 90:
        return False
    if not unit.metadata.get("section"):
        return False
    if re.search(r"\b(requirement|offense|sanction|penalt|procedure|step)\b", f"{unit.title} {unit.content}", flags=re.I):
        return False
    return bool(re.match(r"^[A-Z][A-Za-z ,'/()-]{2,}$", unit.title))


def _same_definition_group(left: HandbookKnowledgeUnit, right: HandbookKnowledgeUnit) -> bool:
    return (
        left.metadata.get("chapter") == right.metadata.get("chapter")
        and left.metadata.get("article") == right.metadata.get("article")
        and left.metadata.get("content_type") == right.metadata.get("content_type")
    )


def _group_title(unit: HandbookKnowledgeUnit) -> str:
    article = unit.metadata.get("article")
    if isinstance(article, str) and article:
        return article.split(">", 1)[-1].strip()
    chapter = unit.metadata.get("chapter")
    if isinstance(chapter, str) and chapter:
        return chapter.split(">", 1)[-1].strip()
    return unit.title


def _parse_heading(line: str) -> dict[str, str] | None:
    if not _starts_with_hierarchy_marker(line) and (_is_table_style_row(line) or _is_continuation_clause(line)):
        return None

    front_matter = _front_matter_heading(line)
    if front_matter:
        return front_matter

    patterns = (
        ("appendix", r"^(appendix(?:es)?(?:\s+[A-Z0-9IVXLCDM]+)?)\s*[:\-.]?\s*(.*)$"),
        ("chapter", r"^(chapter\s+[A-Z0-9IVXLCDM]+)\s*[:\-.]?\s*(.*)$"),
        ("article", r"^(article\s+[A-Z0-9IVXLCDM]+)\s*[:\-.]?\s*(.*)$"),
        ("section", r"^(sec(?:tion)?\.?\s*\d+(?:\.\d+)*)\.?\s*[:\-.]?\s*(.*)$"),
        ("section", r"^(\d+\.\d+(?:\.\d+)*)(?:\.)?\s+(.+)$"),
    )
    for level, pattern in patterns:
        match = re.match(pattern, line.strip(), flags=re.I)
        if not match:
            continue
        value = re.sub(r"\s+", " ", match.group(1).strip())
        title = re.sub(r"\s+", " ", (match.group(2) or "").strip(" :-"))
        if _is_numeric_table_value(value, title):
            continue
        title, inline_body = _split_inline_definition_title(title)
        if level == "section" and _is_low_confidence_section_title(title, inline_body):
            continue
        return {"level": level, "value": value, "title": title, "inline_body": inline_body}
    major = _major_heading(line)
    if major:
        return major
    topic = _policy_topic_heading(line)
    if topic:
        return topic
    return None


def _starts_with_hierarchy_marker(line: str) -> bool:
    return bool(
        re.match(
            r"^\s*(?:appendix(?:es)?|chapter|article|sec(?:tion)?\.?\s*\d|\d+\.\d+)",
            line,
            flags=re.I,
        )
    )


def _front_matter_heading(line: str) -> dict[str, str] | None:
    normalized = _canonical_heading_text(line)
    for title in FRONT_MATTER_TITLES:
        if normalized == _canonical_heading_text(title):
            return {"level": "front_matter", "value": _title_case(line), "title": "", "inline_body": ""}
    return None


def _major_heading(line: str) -> dict[str, str] | None:
    stripped = line.strip(" :-")
    if _is_table_style_row(stripped) or _is_continuation_clause(stripped):
        return None
    if not stripped or len(stripped.split()) > 8:
        return None
    if not stripped[:1].isupper():
        return None
    if "/" in stripped:
        return None
    if stripped.endswith((".", ";", ",")):
        return None
    if _is_toc_line(stripped):
        return None
    if not any(re.search(pattern, stripped, flags=re.I) for pattern in MAJOR_HEADING_PATTERNS):
        return None
    if re.search(r"\|", stripped):
        return None
    if not _is_title_like_heading(stripped):
        return None
    return {"level": "major", "value": _title_case(stripped), "title": "", "inline_body": ""}


def _policy_topic_heading(line: str) -> dict[str, str] | None:
    if re.match(r"^\s*[-*]", line):
        return None
    stripped = line.strip(" :-")
    if _is_table_style_row(stripped) or _is_continuation_clause(stripped):
        return None
    if PROGRAM_GROUP_RE.match(stripped) or _is_degree_program_line(stripped):
        return None
    if not stripped or len(stripped.split()) > 8:
        return None
    if stripped.endswith((".", ";", ",")):
        return None
    if not _is_title_like_heading(stripped):
        return None
    if not _has_policy_topic_keyword(stripped):
        return None
    return {"level": "section", "value": _title_case(stripped), "title": "", "inline_body": ""}


def _is_title_like_heading(value: str) -> bool:
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", value)
    if not words:
        return False
    stopwords = {"of", "and", "the", "for", "in", "on", "to"}
    title_like = 0
    for word in words:
        if word.lower() in stopwords:
            title_like += 1
        elif word.isupper() or word[:1].isupper():
            title_like += 1
    return title_like / len(words) >= 0.75


def _is_table_style_row(line: str) -> bool:
    stripped = line.strip()
    if "|" in stripped and len([part for part in stripped.split("|") if part.strip()]) >= 2:
        return True
    if re.search(r"\s{2,}", stripped) and len(re.split(r"\s{2,}", stripped)) >= 2:
        return True
    if re.match(
        r"^(?:situation|condition|action|result|status|allowable percentage|grade|gwa|gpa|final grade)\b",
        stripped,
        flags=re.I,
    ) and re.search(
        r"\b(?:action|result|status|probation|retake|repeat|dismissal|warning|required|threshold|less than|below)\b",
        stripped,
        flags=re.I,
    ):
        return True
    return False


def _is_continuation_clause(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if len(stripped.split()) > 12:
        return True
    if re.match(r"^(?:if|when|any|the student|students|a student)\b", stripped, flags=re.I):
        return True
    if re.search(r"\b(?:shall|must|is required to|are required to|is granted|are granted|is dropped|withdraws?|not in residence|registered during|after the first day)\b", stripped, flags=re.I):
        return True
    if re.search(r"\b(?:and|or|but|provided that|subject to|under this rule)\b", stripped, flags=re.I) and not _looks_like_policy_topic(stripped):
        return True
    return False


def _looks_like_policy_topic(value: str) -> bool:
    words = value.split()
    if not (1 <= len(words) <= 8):
        return False
    if _has_policy_topic_keyword(value):
        return True
    return bool(re.fullmatch(r"[A-Z][A-Za-z ,'/()-]{2,60}", value.strip()))


def _has_policy_topic_keyword(value: str) -> bool:
    return bool(
        re.search(
            r"\b(?:requirement|requirements|policy|policies|rule|rules|system|attendance|admission|retention|grading|delinquency|dismissal|validation|classification|procedure|procedures|offense|offenses|sanction|sanctions|violation|violations)\b",
            value,
            flags=re.I,
        )
    )


def _split_inline_definition_title(title: str) -> tuple[str, str]:
    if not title:
        return "", ""
    match = re.match(r"^(.{2,80}?)\.\s+(.+)$", title)
    if match:
        short_title = match.group(1).strip()
        inline_body = match.group(2).strip()
        if len(short_title.split()) <= 8 and not _is_continuation_clause(short_title):
            return short_title, inline_body
    dash_match = re.match(r"^(.{2,80}?)\s+-\s+(.+)$", title)
    if dash_match:
        short_title = dash_match.group(1).strip()
        inline_body = dash_match.group(2).strip()
        if len(short_title.split()) <= 8 and _looks_like_numbered_definition_title(short_title):
            return short_title, inline_body
    return title, ""


def _is_low_confidence_section_title(title: str, inline_body: str) -> bool:
    title = title.strip()
    if not title:
        return False
    if _is_table_style_row(title) or _is_continuation_clause(title):
        return True
    if len(title.split()) > 8 and not inline_body:
        return True
    if inline_body and _is_table_style_row(f"{title} {inline_body}"):
        return True
    return False


def _is_numeric_table_value(value: str, title: str) -> bool:
    marker = value.strip()
    if not re.fullmatch(r"\d+\.\d+(?:\.\d+)*", marker):
        return False
    if re.search(r"[%]|(?:^|[\sA-Z])P\d|₱|\bunit\b|/unit\b", f"{marker} {title}", flags=re.I):
        return True
    if re.fullmatch(r"\d+\.\d{1,2}", marker):
        # GPA/grade values commonly appear as 2.25, 3.0, 5.0 and should stay inside tables.
        return not _looks_like_numbered_definition_title(title)
    if _is_table_style_row(f"{marker} {title}") or _is_continuation_clause(title):
        return True
    return False


def _looks_like_numbered_definition_title(title: str) -> bool:
    if not title:
        return False
    first = re.split(r"\.\s+|\s+-\s+", title, maxsplit=1)[0].strip()
    if _is_table_style_row(first) or _is_continuation_clause(first):
        return False
    if len(first.split()) > 8:
        return False
    if re.search(r"\b(student|requirement|policy|procedure|rule|offense|admission|application|enrollment)\b", first, flags=re.I):
        return True
    return bool(re.match(r"^[A-Z][A-Za-z ,'/()-]{2,}$", first))


def _update_context(context: dict[str, str | None], heading: _Heading) -> None:
    label = _heading_label(heading)
    if heading.level == "chapter":
        context["chapter"] = label
        context["article"] = None
        context["section"] = None
    elif heading.level == "article":
        context["article"] = label
        context["section"] = None
    elif heading.level in {"section", "appendix"}:
        context["section"] = label
    elif heading.level == "front_matter":
        context["chapter"] = None
        context["article"] = None
        context["section"] = label
    elif heading.level == "major":
        context["chapter"] = label
        context["article"] = None
        context["section"] = None


def _heading_label(heading: _Heading) -> str:
    return f"{_title_case(heading.value)}{f' > {_title_case(heading.title)}' if heading.title else ''}"


def _unit_title(heading: _Heading) -> str:
    if heading.title:
        return _title_case(heading.title)
    return _title_case(heading.value)


def _repair_title_body_word_split(title: str, body: str) -> tuple[str, str]:
    split = _title_body_word_split(title, body)
    if not split:
        return title, body

    title_match, body_match, repaired = split
    repaired_title = f"{title[:title_match.start(1)]}{repaired}"
    repaired_body = body[body_match.end(1) :].lstrip()
    return _title_case(repaired_title), repaired_body


def _looks_like_title_body_word_split(title: str, body: str) -> bool:
    return _title_body_word_split(title, body) is not None


def _title_body_word_split(title: str, body: str) -> tuple[re.Match[str], re.Match[str], str] | None:
    if not title.strip() or not body.strip():
        return None
    title_match = re.search(r"([A-Za-z]{3,})$", title.strip())
    body_match = re.match(r"\s*([a-z]{2,})(\b|\W)(.*)$", body, flags=re.S)
    if not title_match or not body_match:
        return None
    left = title_match.group(1)
    right = body_match.group(1)
    candidate = f"{left} {right}"
    repaired = repair_ocr_word_splits(candidate)
    if repaired == candidate or not re.fullmatch(r"[A-Za-z]{5,}", repaired):
        return None
    return title_match, body_match, repaired


def _knowledge_content(text: str, *, content_type: str = "policy") -> str:
    text = _repair_ocr_word_breaks(text)
    if content_type == "form_template":
        return _clean_form_template_content(text)
    if content_type == "program_listing":
        text = _normalize_bullets(text)
        text = _remove_inline_layout_labels(text)
        return normalize_whitespace(text)
    text = _normalize_bullets(text)
    text = _remove_inline_layout_labels(text)
    if _has_table_rows(text):
        return normalize_whitespace(text)
    text = re.sub(r"\n(?=[a-z,;])", " ", text)
    text = re.sub(r"(?<![.!?:;])\n(?!\s*(?:[-*]|\d+[\.)]|\w+\s*:))", " ", text)
    text = normalize_whitespace(text)
    return text


def _split_embedded_form_units(unit: HandbookKnowledgeUnit, raw_body: str) -> list[HandbookKnowledgeUnit]:
    if not _has_form_placeholders(raw_body):
        return [unit]

    lines = [line.strip() for line in raw_body.splitlines() if line.strip()]
    form_indexes = [
        index
        for index, line in enumerate(lines)
        if _extract_placeholder_field(line) or _looks_like_compact_placeholder_field_line(line)
    ]
    if len(form_indexes) < 3:
        return [unit]

    start = max(0, min(form_indexes) - 1)
    if start > 0 and not _looks_like_form_title(lines[start]):
        start = min(form_indexes)
    end = max(form_indexes) + 1
    while end < len(lines) and (
        _extract_placeholder_field(lines[end])
        or _looks_like_compact_placeholder_field_line(lines[end])
        or _looks_like_form_instruction(lines[end])
    ):
        end += 1

    before = lines[:start]
    form_lines = lines[start:end]
    after = lines[end:]
    fields = _extract_form_fields_from_lines(form_lines)
    if len(fields) < 3:
        return [unit]

    units: list[HandbookKnowledgeUnit] = []
    remaining = normalize_whitespace("\n".join(before + after))
    if remaining:
        metadata = dict(unit.metadata)
        units.append(
            HandbookKnowledgeUnit(
                title=unit.title,
                content=_knowledge_content(remaining, content_type=str(metadata.get("content_type") or "policy")),
                raw_text=normalize_whitespace("\n".join([unit.title, remaining])),
                metadata=metadata,
            )
        )

    form_metadata = dict(unit.metadata)
    form_metadata["content_type"] = "form_template"
    form_metadata["section"] = form_metadata.get("section") or unit.title
    form_title = _embedded_form_title(form_lines, fields)
    if form_title == "Form Template" and unit.title != "Form Template":
        form_title = unit.title
    units.append(
        HandbookKnowledgeUnit(
            title=form_title,
            content=_form_content_from_fields(fields, form_lines),
            raw_text=normalize_whitespace("\n".join(form_lines)),
            metadata=form_metadata,
        )
    )
    return units or [unit]


def _looks_like_form_title(line: str) -> bool:
    return bool(re.search(r"\b(form|information|profile|record|template|slip|note|pledge|consent)\b", line, flags=re.I))


def _looks_like_compact_placeholder_field_line(line: str) -> bool:
    return bool(re.search(r"\b[A-Za-z][A-Za-z /()-]{1,40}\s*[:\-]?\s*_{3,}", line))


def _looks_like_form_instruction(line: str) -> bool:
    return bool(re.search(r"\b(signature|sign|date|submit|fill|complete|guardian|parent)\b", line, flags=re.I))


def _extract_form_fields_from_lines(lines: list[str]) -> list[str]:
    fields: list[str] = []
    for line in lines:
        field = _extract_placeholder_field(line)
        if field and field not in fields:
            fields.append(field)
            continue
        for label in _extract_compact_placeholder_fields(line):
            if label not in fields:
                fields.append(label)
    return fields


def _extract_compact_placeholder_fields(line: str) -> list[str]:
    labels: list[str] = []
    for match in re.finditer(r"([A-Za-z][A-Za-z /()-]{1,40})\s*[:\-]?\s*_{3,}", line):
        label = _title_case(match.group(1).strip(" :-"))
        if label and label not in labels:
            labels.append(label)
    return labels


def _embedded_form_title(lines: list[str], fields: list[str]) -> str:
    for line in lines[:3]:
        cleaned = re.sub(r"_{3,}.*", "", line).strip(" :-")
        if _looks_like_form_title(cleaned) and not _extract_placeholder_field(line):
            return _title_case(cleaned)
    field_set = {_canonical_heading_text(field) for field in fields}
    owner_fields = {
        "name",
        "student number",
        "curricular year",
        "college",
        "course",
        "guardian parent",
        "relationship",
        "contact number",
        "address",
        "signature",
        "date",
    }
    if len(field_set & owner_fields) >= 6 and {"name", "student number"} <= field_set:
        return "Handbook Owner Information"
    return "Form Template"


def _form_content_from_fields(fields: list[str], lines: list[str]) -> str:
    output = ["Required Fields:"]
    output.extend(f"- {field}" for field in fields)
    instructions = [
        re.sub(r"_{3,}", "", line).strip()
        for line in lines
        if not _extract_placeholder_field(line)
        and not _looks_like_compact_placeholder_field_line(line)
        and not _looks_like_form_title(line)
    ]
    instructions = [line for line in instructions if line]
    if instructions:
        output.append("")
        output.append("Instructions:")
        output.extend(_normalize_bullets("\n".join(instructions)).splitlines())
    return normalize_whitespace("\n".join(output))


def _has_table_rows(text: str) -> bool:
    return sum(1 for line in text.splitlines() if "|" in line and len(line.split("|")) >= 2) >= 2


def _normalize_bullets(text: str) -> str:
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if re.match(r"^[•●▪]", stripped):
            stripped = "- " + stripped[1:].strip()
        elif re.match(r"^[a-zA-Z]\)\s+", stripped):
            stripped = "- " + stripped[2:].strip()
        elif re.match(r"^\(?\d+\)?[\.)]\s+", stripped):
            stripped = re.sub(r"^\(?(\d+)\)?[\.)]\s+", r"\1. ", stripped)
        lines.append(stripped)
    return "\n".join(lines)


def _remove_inline_layout_labels(text: str) -> str:
    lines = []
    for line in text.splitlines():
        if _is_layout_header_footer(line):
            continue
        lines.append(line)
    return "\n".join(lines)


def _has_form_placeholders(text: str) -> bool:
    return bool(re.search(r"_{3,}|\.{5,}", text))


def _clean_form_template_content(text: str) -> str:
    fields: list[str] = []
    instructions: list[str] = []
    for raw_line in text.splitlines():
        line = _clean_line(raw_line)
        if not line or _is_layout_header_footer(line):
            continue

        field = _extract_placeholder_field(line)
        if field:
            if field not in fields:
                fields.append(field)
            continue

        line = re.sub(r"_{3,}", "[blank]", line)
        line = re.sub(r"\.{5,}", "[blank]", line)
        if "[blank]" not in line:
            instructions.append(line)

    output: list[str] = []
    if fields:
        output.append("Required Fields:")
        output.extend(f"- {field}" for field in fields)
    if instructions:
        if output:
            output.append("")
        output.append("Instructions:")
        output.extend(_normalize_bullets("\n".join(instructions)).splitlines())
    return normalize_whitespace("\n".join(output))


def _extract_placeholder_field(line: str) -> str | None:
    match = re.match(r"^([A-Za-z][A-Za-z0-9 /().,'-]{1,50})\s*[:\-]?\s*(?:_{3,}|\.{5,}|\[blank\])", line)
    if match:
        return _title_case(match.group(1).strip(" :-"))
    match = re.match(r"^(?:_{3,}|\.{5,})\s*([A-Za-z][A-Za-z0-9 /().,'-]{1,50})$", line)
    if match:
        return _title_case(match.group(1).strip(" :-"))
    return None


@dataclass
class _ProgramEntry:
    name: str
    campuses: list[str] = field(default_factory=list)


def _split_program_listing(unit: HandbookKnowledgeUnit) -> list[HandbookKnowledgeUnit]:
    lines = [line.strip() for line in unit.content.splitlines() if line.strip()]
    groups: list[tuple[str, list[str], list[str]]] = []
    current_title: str | None = None
    current_campuses: list[str] = []
    current_lines: list[str] = []
    current_has_programs = False

    for line in lines:
        if PROGRAM_GROUP_RE.match(line):
            if current_title and current_lines:
                groups.append((current_title, current_lines, current_campuses))
            current_title, current_campuses = _parse_program_group_heading(line)
            current_lines = []
            current_has_programs = False
            continue
        if current_title:
            cleaned = re.sub(r"^[\-*]\s*", "", line).strip()
            if _is_degree_program_line(cleaned):
                current_has_programs = True
            elif not current_has_programs:
                current_campuses = _merge_unique(current_campuses, _extract_campuses_from_text(cleaned, allow_bare=True))
            current_lines.append(line)

    if current_title and current_lines:
        groups.append((current_title, current_lines, current_campuses))

    if not groups:
        return [unit]

    split_units: list[HandbookKnowledgeUnit] = []
    for group_title, group_lines, campuses in groups:
        metadata = dict(unit.metadata)
        metadata["content_type"] = "program_listing"
        if campuses:
            metadata["campuses"] = campuses
        program_entries, specializations = _parse_program_entries(group_lines, default_campuses=campuses)
        program_campuses = {
            entry.name: entry.campuses
            for entry in program_entries
            if entry.campuses and entry.campuses != campuses
        }
        if program_campuses:
            metadata["program_campuses"] = program_campuses
        split_units.append(
            HandbookKnowledgeUnit(
                title=f"{unit.title} - {group_title}",
                content=_program_listing_content(
                    group_title,
                    group_lines,
                    campuses=campuses,
                    program_entries=program_entries,
                    specializations=specializations,
                ),
                raw_text=normalize_whitespace(f"{group_title}\n" + "\n".join(group_lines)),
                metadata=metadata,
            )
        )
    return split_units


def _program_listing_content(
    group_title: str,
    lines: list[str],
    *,
    campuses: list[str] | None = None,
    program_entries: list[_ProgramEntry] | None = None,
    specializations: list[str] | None = None,
) -> str:
    if program_entries is None or specializations is None:
        program_entries, specializations = _parse_program_entries(lines, default_campuses=campuses or [])

    programs = [entry.name for entry in program_entries]
    program_campuses = {
        entry.name: entry.campuses
        for entry in program_entries
        if entry.campuses and entry.campuses != (campuses or [])
    }

    output: list[str] = []
    if campuses:
        output.append("Campuses:")
        output.extend(f"- {campus}" for campus in campuses)
    if programs:
        if output:
            output.append("")
        output.append("Programs:")
        output.extend(f"- {program}" for program in programs)
    if program_campuses:
        if output:
            output.append("")
        output.append("Program Campuses:")
        for program, values in program_campuses.items():
            output.append(f"- {program}: {', '.join(values)}")
    if specializations:
        if output:
            output.append("")
        output.append("Specializations:")
        output.extend(f"- {specialization}" for specialization in specializations)
    if output:
        return normalize_whitespace("\n".join(output))
    return group_title


def _parse_program_entries(lines: list[str], *, default_campuses: list[str] | None = None) -> tuple[list[_ProgramEntry], list[str]]:
    entries: list[_ProgramEntry] = []
    specializations: list[str] = []
    in_specializations = False
    in_campus_block = False

    for line in lines:
        cleaned = re.sub(r"^[\-*]\s*", "", line).strip()
        if not cleaned:
            continue
        if _is_campus_label(cleaned):
            in_campus_block = True
            in_specializations = False
            continue
        if _is_specialization_label(cleaned):
            in_specializations = True
            in_campus_block = False
            continue
        if _is_degree_program_line(cleaned):
            program, inline_campuses = _split_program_and_campuses(cleaned)
            inherited_campuses = default_campuses or []
            entries.append(_ProgramEntry(name=_normalize_degree_program(program), campuses=inline_campuses or inherited_campuses))
            in_specializations = False
            in_campus_block = bool(inline_campuses)
            continue
        campuses = [] if in_specializations else _extract_campuses_from_text(cleaned, allow_bare=in_campus_block or bool(entries))
        if campuses:
            if entries:
                current = entries[-1]
                current.campuses = _merge_unique(current.campuses, campuses)
            in_campus_block = True
            in_specializations = False
            continue
        if _is_program_listing_descriptor(cleaned):
            continue
        if in_specializations:
            specializations.append(cleaned)

    return _dedupe_program_entries(entries), specializations


def _dedupe_program_entries(entries: list[_ProgramEntry]) -> list[_ProgramEntry]:
    deduped: list[_ProgramEntry] = []
    by_name: dict[str, _ProgramEntry] = {}
    for entry in entries:
        key = _canonical_heading_text(entry.name)
        if key in by_name:
            existing = by_name[key]
            existing.campuses = _merge_unique(existing.campuses, entry.campuses)
            continue
        copied = _ProgramEntry(name=entry.name, campuses=list(entry.campuses))
        by_name[key] = copied
        deduped.append(copied)
    return deduped


def _parse_program_group_heading(line: str) -> tuple[str, list[str]]:
    return _clean_program_group_title(line), _extract_campuses_from_text(line)


def _clean_program_group_title(line: str) -> str:
    title = re.sub(r"\s+", " ", line).strip(" :-")
    title = re.sub(r"\s*\([A-Z0-9&/ -]{2,12}\)", "", title)
    title = re.sub(r"\s*,\s*.*\bcampus(?:es)?\b.*$", "", title, flags=re.I)
    title = re.sub(r"\s*,?\s*(?:all\s+)?campus(?:es)?\b.*$", "", title, flags=re.I)
    title = re.sub(r"\s+-\s+.*\bcampus(?:es)?\b.*$", "", title, flags=re.I)
    return _title_case(title)


def _is_specialization_label(line: str) -> bool:
    return bool(re.fullmatch(r"speciali[sz]ations?\s*:?", line.strip(), flags=re.I))


def _is_campus_label(line: str) -> bool:
    return bool(re.fullmatch(r"campus(?:es)?\s*:?", line.strip(), flags=re.I))


def _is_program_listing_descriptor(line: str) -> bool:
    if _is_degree_program_line(line):
        return False
    if re.search(r"\bcampus(?:es)?\b", line, flags=re.I):
        return True
    if re.fullmatch(r"(?:programs?|degree programs?|offerings?)\s*:?", line.strip(), flags=re.I):
        return True
    return False


def _split_program_and_campuses(line: str) -> tuple[str, list[str]]:
    cleaned = re.sub(r"^[\-*]\s*", "", line).strip(" :-")
    for pattern in (
        r"^(?P<program>.+?)\s*-\s*(?P<campuses>.+\bcampus(?:es)?\b.*)$",
        r"^(?P<program>.+?)\s*\((?P<campuses>.+\bcampus(?:es)?\b.*?)\)$",
        r"^(?P<program>.+?)\s*,\s*(?P<campuses>.+\bcampus(?:es)?\b.*)$",
    ):
        match = re.match(pattern, cleaned, flags=re.I)
        if match and _is_degree_program_line(match.group("program")):
            campuses = _extract_campuses_from_text(match.group("campuses"), allow_bare=True)
            if campuses:
                return match.group("program").strip(), campuses
    return cleaned, []


def _extract_campuses_from_text(line: str, *, allow_bare: bool = False) -> list[str]:
    text = re.sub(r"^[\-*]\s*", "", line).strip(" :-")
    if _is_degree_program_line(text):
        return []
    if not re.search(r"\bcampus(?:es)?\b", text, flags=re.I):
        if not allow_bare:
            return []
        campus = _normalize_campus_name(text)
        return [campus] if campus and _looks_like_campus_name(campus) else []

    if re.search(r"\ball\s+campus(?:es)?\b", text, flags=re.I):
        return ["All Campuses"]

    title = _clean_program_group_title(text) if PROGRAM_GROUP_RE.match(text) else ""
    if title and re.match(re.escape(title), text, flags=re.I):
        text = re.sub(re.escape(title), "", text, count=1, flags=re.I).strip(" ,-:")

    text = re.sub(r"\([A-Z0-9&/ -]{2,12}\)", "", text).strip(" ,-:")
    text = re.sub(
        r"\b(?:available|offered|conducted|implemented)\s+(?:at|in|on)\b",
        "",
        text,
        flags=re.I,
    ).strip(" ,-:")
    text = re.sub(r"\bcampus(?:es)?\b", "", text, flags=re.I).strip(" ,-:")
    text = re.sub(r"\band\b", ",", text, flags=re.I)

    campuses: list[str] = []
    for part in text.split(","):
        campus = _normalize_campus_name(part)
        if campus and _looks_like_campus_name(campus) and campus not in campuses:
            campuses.append(campus)
    return campuses


def _normalize_campus_name(value: str) -> str:
    campus = re.sub(r"\s+", " ", value).strip(" .:-")
    campus = re.sub(r"^(?:at|in|on)\s+", "", campus, flags=re.I)
    campus = re.sub(r"\s+campus(?:es)?$", "", campus, flags=re.I).strip(" .:-")
    if not campus:
        return ""
    campus = _title_case(campus)
    campus = re.sub(r"\bSta\s+", "Sta. ", campus)
    campus = re.sub(r"\bSt\s+", "St. ", campus)
    return _canonical_campus_name(campus)


def _looks_like_campus_name(value: str) -> bool:
    if not value or _is_degree_program_line(value):
        return False
    if _canonical_campus_name(value) not in KNOWN_CAMPUS_NAMES:
        return False
    if re.search(r"\b(?:bachelor|master|doctor|phd|juris|education|arts|science|teaching|programs?|degree)\b", value, flags=re.I):
        return False
    words = re.findall(r"[^\W\d_][^\W\d_.'-]*", value)
    if not (1 <= len(words) <= 5):
        return False
    return all(word[:1].isupper() or word.lower() in {"of", "the"} for word in words)


def _canonical_campus_name(value: str) -> str:
    key = re.sub(r"[^A-Za-zÀ-ÿ]+", " ", value).strip().lower()
    return _CAMPUS_ALIASES.get(key, value)


def handbook_campus_audit(document: HandbookPolicyDocument) -> dict:
    campus_names: list[str] = []
    program_campus_values: list[str] = []
    invalid_records: list[dict[str, str]] = []

    for unit in document.units:
        metadata = unit.metadata
        for campus in metadata.get("campuses") or []:
            if isinstance(campus, str):
                campus_names.append(campus)
                if campus not in KNOWN_CAMPUS_NAMES:
                    invalid_records.append({"title": unit.title, "field": "campuses", "value": campus})
        program_campuses = metadata.get("program_campuses") or {}
        if isinstance(program_campuses, dict):
            for program, values in program_campuses.items():
                for campus in values or []:
                    if isinstance(campus, str):
                        program_campus_values.append(campus)
                        if campus not in KNOWN_CAMPUS_NAMES:
                            invalid_records.append(
                                {
                                    "title": unit.title,
                                    "field": f"program_campuses.{program}",
                                    "value": campus,
                                }
                            )

    return {
        "known_campuses": list(KNOWN_CAMPUS_NAMES),
        "unique_campus_names": sorted(set(campus_names)),
        "unique_program_campus_values": sorted(set(program_campus_values)),
        "invalid_campus_values": invalid_records,
    }


def handbook_ocr_split_audit(document: HandbookPolicyDocument) -> list[dict[str, str | int]]:
    findings: list[dict[str, str | int]] = []
    for unit_index, unit in enumerate(document.units):
        text = f"{unit.title}\n{unit.content}\n{unit.raw_text}"
        for label, pattern in _OCR_SPLIT_AUDIT_PATTERNS:
            for match in re.finditer(pattern, text, flags=re.I):
                start = max(0, match.start() - 50)
                end = min(len(text), match.end() + 50)
                findings.append(
                    {
                        "unit_index": unit_index,
                        "title": unit.title,
                        "pattern": label,
                        "match": match.group(0),
                        "context": normalize_whitespace(text[start:end]),
                    }
                )
    return findings


def _merge_unique(existing: list[str], incoming: list[str]) -> list[str]:
    merged = list(existing)
    for item in incoming:
        if item not in merged:
            merged.append(item)
    return merged


def _is_degree_program_line(line: str) -> bool:
    return bool(DEGREE_LINE_RE.match(line.strip()))


def _normalize_degree_program(line: str) -> str:
    program = re.sub(r"^[\-*]\s*", "", line).strip()
    program = re.sub(r"\s*\((?:BOR|Board)\b[^)]*\)", "", program, flags=re.I).strip()

    for prefix, abbreviation in DEGREE_PREFIX_ABBREVIATIONS:
        match = re.match(rf"^{re.escape(prefix)}\s+in\s+(.+)$", program, flags=re.I)
        if match:
            return f"{abbreviation} {_title_case(match.group(1).strip())}"

    match = re.match(r"^(B(?:S|A|SEd|EEd))\s+in\s+(.+)$", program, flags=re.I)
    if match:
        return f"{match.group(1)} {_title_case(match.group(2).strip())}"

    return _title_case(program)


def _split_long_text(text: str, *, max_words: int) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    if len(paragraphs) <= 1:
        paragraphs = [part.strip() for part in text.splitlines() if part.strip()]

    chunks: list[str] = []
    current: list[str] = []
    current_words = 0
    for paragraph in paragraphs:
        words = _word_count(paragraph)
        if current and current_words + words > max_words:
            chunks.append(normalize_whitespace("\n".join(current)))
            current = [paragraph]
            current_words = words
        else:
            current.append(paragraph)
            current_words += words
    if current:
        chunks.append(normalize_whitespace("\n".join(current)))
    return chunks


def _word_count(text: str) -> int:
    return len(re.findall(r"\b\S+\b", text))


def build_handbook_diagnostic_report(
    document: HandbookPolicyDocument,
    *,
    sample_size: int = 10,
) -> dict:
    chunks = [
        {
            "index": index,
            "title": unit.title,
            "size_chars": len(unit.article_text),
            "size_words": _word_count(unit.article_text),
            "metadata": dict(unit.metadata),
            "preview": unit.article_text[:500],
        }
        for index, unit in enumerate(document.units)
    ]
    word_sizes = [chunk["size_words"] for chunk in chunks]
    largest = max(chunks, key=lambda chunk: chunk["size_chars"], default=None)
    smallest = min(chunks, key=lambda chunk: chunk["size_chars"], default=None)
    largest_units = sorted(chunks, key=lambda chunk: chunk["size_words"], reverse=True)[:10]
    campus_audit = handbook_campus_audit(document)
    ocr_split_findings = handbook_ocr_split_audit(document)
    return {
        "source_title": document.source_title,
        "doc_no": document.doc_no,
        "document_type": document.document_type,
        "total_knowledge_units": len(document.units),
        "total_chunks": len(chunks),
        "average_chunk_size": round(sum(word_sizes) / len(word_sizes), 2) if word_sizes else 0,
        "largest_chunk_size": max(word_sizes, default=0),
        "smallest_chunk_size": min(word_sizes, default=0),
        "top_10_largest_units": [
            {
                "title": chunk["title"],
                "word_count": chunk["size_words"],
                "content_type": chunk["metadata"].get("content_type"),
            }
            for chunk in largest_units
        ],
        "largest_chunk": largest,
        "smallest_chunk": smallest,
        "sample_chunks": chunks[:sample_size],
        "campus_audit": campus_audit,
        "remaining_ocr_word_splits": ocr_split_findings,
    }


def _format_path(metadata: dict[str, MetadataValue]) -> str:
    parts = [
        str(metadata.get(key))
        for key in ("chapter", "article", "section")
        if metadata.get(key)
    ]
    return " > ".join(parts)


def _title_case(value: str) -> str:
    if not value:
        return value
    value = re.sub(r"\s+", " ", value).strip()
    if value.isupper() or value.islower():
        return re.sub(
            r"[A-Za-z]+",
            lambda match: match.group(0) if match.group(0).isupper() and 2 <= len(match.group(0)) <= 6 else match.group(0).capitalize(),
            value,
        )
    return value
