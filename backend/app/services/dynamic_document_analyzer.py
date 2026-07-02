"""Dynamic structure extraction for mixed university documents.

The analyzer uses document structure signals such as headings, labels, and
tables. It does not hardcode extracted values like office names, service names,
personnel names, dates, or titles.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.services.text_cleaner import clean_ocr_text

NEEDS_REVIEW = "[NEEDS REVIEW]"


@dataclass
class ExtractedTable:
    headers: list[str]
    rows: list[list[str]]


@dataclass
class ExtractedSection:
    level: str
    title: str
    text: str


@dataclass
class DynamicDocument:
    document_kind: str
    confidence: float
    metadata: dict[str, str]
    sections: list[ExtractedSection] = field(default_factory=list)
    tables: list[ExtractedTable] = field(default_factory=list)


STRUCTURAL_LABELS = {
    "title": [r"\btitle\b", r"\bsubject\b"],
    "date": [r"\bdate\b"],
    "recipient": [r"\bto\b", r"\brecipient\b", r"\bfor\b"],
    "sender": [r"\bfrom\b", r"\bsender\b"],
    "office": [r"\boffice\b", r"\boffice\s+or\s+division\b"],
    "service": [r"\bservice\b"],
    "requirements": [r"\brequirements?\b", r"\bchecklist\s+of\s+requirements\b"],
    "steps": [r"\bsteps?\b", r"\bclient\s+steps?\b", r"\bprocedure\b"],
    "table": [r"\|", r"\bprocessing\s+time\b", r"\bresponsible\b"],
    "chapter": [r"\bchapter\s+[ivxlcdm\d]+\b"],
    "article": [r"\barticle\s+[ivxlcdm\d]+\b"],
    "section": [r"\bsection\s+[\dA-ZIVXLCDM][\w\.\-]*\b"],
    "subject": [r"\bsubject\b"],
}


def analyze_document_structure(text: str) -> DynamicDocument:
    cleaned = clean_ocr_text(text)
    kind, confidence = _detect_document_kind(cleaned)
    return DynamicDocument(
        document_kind=kind,
        confidence=confidence,
        metadata=_extract_metadata(cleaned),
        sections=_extract_sections(cleaned),
        tables=_extract_tables(cleaned),
    )


def format_dynamic_document(doc: DynamicDocument, fallback_text: str) -> str:
    if doc.confidence < 0.35:
        return fallback_text

    lines = [f"Document Type: {doc.document_kind}"]

    if doc.metadata:
        lines.append("Metadata:")
        for key, value in doc.metadata.items():
            lines.append(f"  - {key}: {value or NEEDS_REVIEW}")

    if doc.sections:
        lines.append("Sections:")
        for section in doc.sections:
            lines.append(f"  - {section.level}: {section.title}")
            if section.text:
                lines.append(f"    {section.text}")

    if doc.tables:
        lines.append("Tables:")
        for table_index, table in enumerate(doc.tables, start=1):
            lines.append(f"  Table {table_index}:")
            lines.append("    Headers: " + " | ".join(table.headers))
            for row in table.rows:
                lines.append("    Row: " + " | ".join(row))

    formatted = "\n".join(lines).strip()
    return formatted or fallback_text


def _detect_document_kind(text: str) -> tuple[str, float]:
    scores = {
        "citizen_charter": _score(text, ["office", "service", "requirements", "steps", "table"]),
        "handbook_policy": _score(text, ["chapter", "article", "section"]),
        "memo": _score(text, ["date", "recipient", "sender", "subject"]),
        "request_letter": _score(text, ["date", "recipient", "sender"]),
        "form": _score(text, ["table", "date", "title"]),
    }
    kind, raw_score = max(scores.items(), key=lambda item: item[1])
    if raw_score <= 0:
        return "generic_document", 0.0
    return kind, min(raw_score / 5, 1.0)


def _score(text: str, labels: list[str]) -> int:
    return sum(1 for label in labels if _has_label(text, label))


def _has_label(text: str, label: str) -> bool:
    return any(re.search(pattern, text, flags=re.I) for pattern in STRUCTURAL_LABELS.get(label, []))


def _extract_metadata(text: str) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for label in ["title", "date", "recipient", "sender", "office", "service"]:
        value = _extract_labeled_value(text, label)
        if value:
            metadata[label.replace("_", " ").title()] = value
    return metadata


def _extract_labeled_value(text: str, label: str) -> str:
    for pattern in STRUCTURAL_LABELS.get(label, []):
        match = re.search(rf"{pattern}\s*[:\-]?\s*([^\n|]+)", text, flags=re.I)
        if match:
            value = clean_ocr_text(match.group(1)).strip(" |:-")
            if value and not _looks_like_header(value):
                return value
    return ""


def _extract_sections(text: str) -> list[ExtractedSection]:
    heading_pattern = re.compile(
        r"^\s*((?:Chapter|Article|Section)\s+[A-Za-z0-9IVXLCDM\.\-]+)\s*[:\-]?\s*(.*)$",
        flags=re.I | re.M,
    )
    matches = list(heading_pattern.finditer(text))
    sections: list[ExtractedSection] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections.append(
            ExtractedSection(
                level=match.group(1).strip(),
                title=match.group(2).strip() or NEEDS_REVIEW,
                text=text[start:end].strip()[:800],
            )
        )
    return sections


def _extract_tables(text: str) -> list[ExtractedTable]:
    tables: list[ExtractedTable] = []
    current: list[list[str]] = []
    for line in text.splitlines():
        if "|" not in line:
            if current:
                tables.append(_table_from_rows(current))
                current = []
            continue
        cells = [clean_ocr_text(cell.strip()) for cell in line.split("|") if cell.strip()]
        if len(cells) >= 2:
            current.append(cells)
    if current:
        tables.append(_table_from_rows(current))
    return tables


def _table_from_rows(rows: list[list[str]]) -> ExtractedTable:
    return ExtractedTable(headers=rows[0], rows=rows[1:] if len(rows) > 1 else [])


def _looks_like_header(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Z\s]{3,}", value.strip()))
