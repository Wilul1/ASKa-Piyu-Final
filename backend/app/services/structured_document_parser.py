"""Dynamic-ish structured extraction for ASKa-Piyu OCR results.

This parser avoids relying on one fixed header list. It uses flexible section
signals, service boundary detection, and conservative fallbacks. When the text is
unclear, fields are marked as [NEEDS REVIEW] instead of inventing data.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict, field
from typing import Any

from app.services.text_cleaner import clean_ocr_text

NEEDS_REVIEW = "[NEEDS REVIEW]"


@dataclass
class DocumentField:
    label: str
    field_type: str
    value: str | None = None
    items: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"label": self.label, "field_type": self.field_type}
        if self.field_type == "list":
            data["items"] = self.items
        else:
            data["value"] = self.value or ""
        return data


@dataclass
class StructuredDocument:
    fields: list[DocumentField]
    formatted_text: str


@dataclass
class Requirement:
    requirement: str = NEEDS_REVIEW
    where_to_secure: str = NEEDS_REVIEW


@dataclass
class Step:
    client_step: str = NEEDS_REVIEW
    agency_action: str = NEEDS_REVIEW
    fees: str = NEEDS_REVIEW
    processing_time: str = NEEDS_REVIEW
    responsible_personnel: str = NEEDS_REVIEW


@dataclass
class ServiceRecord:
    office: str = NEEDS_REVIEW
    service: str = NEEDS_REVIEW
    classification: str = NEEDS_REVIEW
    transaction_type: str = NEEDS_REVIEW
    who_may_avail: str = NEEDS_REVIEW
    requirements: list[Requirement] | None = None
    steps: list[Step] | None = None
    total_processing_time: str = NEEDS_REVIEW
    total_fees: str = NEEDS_REVIEW
    parser_debug: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["requirements"] = [asdict(r) for r in (self.requirements or [])]
        d["steps"] = [asdict(s) for s in (self.steps or [])]
        if not d.get("parser_debug"):
            d.pop("parser_debug", None)
        return d


@dataclass
class FormRecord:
    document_type: str = "requirement"
    display_document_type: str = "Requirement / Form Document"
    office: str = NEEDS_REVIEW
    office_detection_source: str = "unknown"
    form_title: str = NEEDS_REVIEW
    form_name: str = NEEDS_REVIEW
    form_code: str = NEEDS_REVIEW
    revision: str = NEEDS_REVIEW
    date: str = NEEDS_REVIEW
    sections: list[str] = field(default_factory=list)
    fields: list[str] = field(default_factory=list)
    options: dict[str, list[str]] = field(default_factory=dict)
    options_or_services: list[str] = field(default_factory=list)
    requirements: list[str] = field(default_factory=list)
    related_services: list[str] = field(default_factory=list)
    how_to_fill_out: list[str] = field(default_factory=list)
    source_document: str = ""
    preview_file_path: str = ""
    raw_extracted_text: str = ""
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify_document_type(text: str) -> str:
    cleaned = clean_ocr_text(text)
    if not cleaned.strip():
        return "unknown"

    form_score = _form_signal_score(cleaned)
    scores = {
        "citizen_charter": _classification_score(
            cleaned,
            [
                r"\bOffice\s*(?:or)?\s*Division\b",
                r"\bClient\s+Steps\b",
                r"\bAgency\s+Actions\b",
                r"\bProcessing\s+Time\b",
                r"\bChecklist\s+of\s+Requirements\b",
                r"\bWho\s+May\s+Avail\b",
            ],
        ),
        "form": _classification_score(
            cleaned,
            [
                r"\b[A-Z]{2,}(?:[-\s]+[A-Z]{2,})*[-\s]+(?:SF|FM|FR|FORM|F)[-\s]*\d{2,4}\b",
                r"\b(?:Application|Request|Requisition|Evaluation|Registration|Clearance)\s+Form\b",
                r"\bForm\s*(?:No\.?|Code|Number)\b",
                r"\bREV\.?\s*\d+\b",
                r"\b(?:Approved|Requested|Requestor|Applicant|Signature)\b",
                r"(?:\[[ xX/]\]|\(\s*[xX/ ]?\s*\)|â˜|â˜‘|â–¡|â– )",
            ],
        ),
        "memo": _classification_score(
            cleaned,
            [r"\bMemorandum\b", r"\bTo\s*:", r"\bFrom\s*:", r"\bSubject\s*:", r"\bDate\s*:"],
        ),
        "handbook_policy": _classification_score(
            cleaned,
            [r"\bChapter\s+[IVXLCDM\d]+\b", r"\bArticle\s+[IVXLCDM\d]+\b", r"\bSection\s+[\dIVXLCDM]+\b", r"\bPolicy\b"],
        ),
    }

    if form_score >= 3 and scores["citizen_charter"] < 4:
        return "form"
    if scores["citizen_charter"] >= 3 and form_score < 3:
        return "citizen_charter"
    if scores["form"] >= 2 and scores["citizen_charter"] < 3:
        return "form"
    if scores["memo"] >= 3:
        return "memo"
    if scores["handbook_policy"] >= 2:
        return "handbook_policy"

    kind, score = max(scores.items(), key=lambda item: item[1])
    return kind if score >= 2 else "unknown"


def _classification_score(text: str, patterns: list[str]) -> int:
    return sum(1 for pattern in patterns if re.search(pattern, text, flags=re.I))


def _form_signal_score(text: str) -> int:
    score = 0
    if _extract_form_code(text) != NEEDS_REVIEW:
        score += 3
    if re.search(r"\b[A-Za-z][A-Za-z /&-]{2,}\s+(?:Form|Request|Application)\b", text, flags=re.I):
        score += 2
    if re.search(r"\b(?:Request|Application)\s+Form\b", text, flags=re.I):
        score += 2
    if re.search(r"\b(?:Services?|Items?|Assistance)\s+Needed\b", text, flags=re.I):
        score += 1
    if re.search(
        r"\b(?:Requester|Event|Service|Compliance|Approval|Requirements?)\s+"
        r"(?:Information|Report|Assessment|Acknowledgement|Approval|Requirements?)\b",
        text,
        flags=re.I,
    ):
        score += 2
    if re.search(r"(?:\[[ xX/]\]|\(\s*[xX/ ]?\s*\)|☐|☑|□|■)", text):
        score += 1
    if re.search(r"\b(?:Requested|Received|Approved)\s+By\b|\bSignature\b", text, flags=re.I):
        score += 1
    return score


def _first(patterns: list[str], text: str, default: str = NEEDS_REVIEW) -> str:
    for pat in patterns:
        m = re.search(pat, text, flags=re.I | re.S)
        if m:
            value = re.sub(r"\s+", " ", m.group(1)).strip(" |:-\n\t")
            if value:
                return value
    return default


def _office_based_service_blocks(clean: str) -> list[str]:
    """Legacy split on Office or Division / Service labels."""
    boundary_label = r"Office\s*(?:or)?\s*Division" if re.search(
        r"\bOffice\s*(?:or)?\s*Division\s*:",
        clean,
        flags=re.I,
    ) else r"Service"
    marked = re.sub(
        rf"(?=\n?\s*{boundary_label}\s*:)",
        "\n---SERVICE---\n",
        clean,
        flags=re.I,
    )
    parts = [p.strip() for p in marked.split("---SERVICE---") if p.strip()]
    if boundary_label.startswith("Office") and len(parts) > 1:
        merged: list[str] = []
        for index, part in enumerate(parts):
            if index == 0:
                if not _only_title_context(part):
                    merged.append(part)
                continue
            context = _title_context(parts[index - 1])
            merged.append(f"{context}\n{part}".strip() if context else part)
        parts = merged
    return parts or [clean]


def _is_probable_charter_service_start(line: str, following: str) -> bool:
    """True when a line looks like a numbered/plain service heading before charter fields."""
    stripped = line.strip()
    if not stripped or "|" in stripped or len(stripped) > 100:
        return False
    if re.search(
        r"\b(Office\s*(?:or)?\s*Division|Classification|Who May Avail|Checklist|CLIENT\s+STEPS|"
        r"Agency\s+Actions|Type of Transaction|Total\s*:|Where to Secure)\b",
        stripped,
        flags=re.I,
    ):
        return False
    numbered = re.match(r"^(\d{1,3})[\.\)]\s+(.+)$", stripped)
    candidate = numbered.group(2).strip() if numbered else stripped
    cleaned = _clean_service_title(stripped if numbered else candidate)
    if not cleaned:
        return False
    try:
        from app.services.citizen_charter_services import is_noise_service_title

        if is_noise_service_title(cleaned):
            return False
    except Exception:
        pass
    window = following[:800]
    if re.search(r"\bOffice\s*(?:or)?\s*Division\s*:", window, flags=re.I):
        return True
    # Part-2/3 continuations may restart with the same heading then Client Steps.
    if numbered and re.search(
        r"\b(?:CLIENT\s+STEPS|Checklist\s+of\s+Requirements|Agency\s+Actions)\b",
        window,
        flags=re.I,
    ):
        return True
    return False


def _charter_heading_service_blocks(clean: str) -> list[str]:
    """Split Citizen's Charter text so each block is one service heading → next heading."""
    lines = clean.splitlines()
    starts: list[int] = []
    for index, line in enumerate(lines):
        following = "\n".join(lines[index + 1 : index + 14])
        if _is_probable_charter_service_start(line, following):
            # Avoid duplicate starts for the same heading cluster.
            if starts and index - starts[-1] <= 1:
                continue
            starts.append(index)
    if len(starts) < 2:
        return []
    blocks: list[str] = []
    for idx, start in enumerate(starts):
        end = starts[idx + 1] if idx + 1 < len(starts) else len(lines)
        block = "\n".join(lines[start:end]).strip()
        if block:
            blocks.append(block)
    return blocks


def _service_blocks(text: str, *, document_type: str | None = None) -> list[str]:
    """Split text into services using charter headings when possible, else office labels."""
    clean = clean_ocr_text(text)
    if document_type == "citizen_charter" and re.search(
        r"(?m)^\s*\d{1,3}[\.\)]\s+\S+",
        clean,
    ):
        heading_blocks = _charter_heading_service_blocks(clean)
        if len(heading_blocks) >= 2:
            return heading_blocks
    return _office_based_service_blocks(clean)


def _only_title_context(text: str) -> bool:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return bool(lines) and len(lines) <= 3 and not any("|" in line for line in lines)


def _title_context(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    candidates: list[str] = []
    for line in reversed(lines[-6:]):
        if _is_header_noise(line) or "|" in line:
            continue
        if re.search(r"\bTotal\s*:", line, flags=re.I):
            break
        if re.search(r"\b(CLIENT STEPS|Checklist of Requirements|Where to Secure)\b", line, flags=re.I):
            continue
        candidates.insert(0, line)
        if len(candidates) >= 2:
            break
    return "\n".join(candidates)


def _extract_service_name(block: str) -> str:
    # Require a delimiter so "Service Pledge" is not treated as Service: Pledge.
    explicit = _first(
        [
            r"Service\s*[:\-]\s*([^\n|]+)",
            r"^\s*Service\s+([A-Z][^\n|]{2,80})$",
        ],
        block,
        default="",
    )
    explicit = _clean_service_title(explicit)
    if explicit:
        return explicit
    return _infer_service_title(block)


def _infer_service_title(block: str) -> str:
    lines = [line.strip() for line in block.splitlines() if line.strip()]
    boundary_index = next(
        (
            index
            for index, line in enumerate(lines)
            if re.search(r"\b(Office\s*(?:or)?\s*Division|Classification|Transaction\s+Type|Type\s+Transaction)\b", line, flags=re.I)
        ),
        len(lines),
    )
    candidates = lines[:boundary_index]
    # Prefer the heading closest to Office/Division (last valid title), so document
    # cover lines like "Citizen's Charter" do not win over the real service name.
    numbered: list[str] = []
    plain: list[str] = []
    for line in candidates:
        title = _clean_service_title(line)
        if not title:
            continue
        if re.match(r"^\d+[\.\)]\s*\S+", line):
            numbered.append(title)
        else:
            plain.append(title)
    if numbered:
        return numbered[-1]
    if plain:
        return plain[-1]
    return NEEDS_REVIEW


def _clean_service_title(value: str) -> str:
    original = value.strip()
    value = clean_ocr_text(value).strip(" |:-.")
    value = re.sub(r"^\d+[\.\)]\s*", "", value).strip(" |:-.")
    if not value or value == NEEDS_REVIEW:
        return ""
    # Reject page numbers / numeric-only titles (13, 72, 00, etc.).
    if re.fullmatch(r"\d{1,4}", value):
        return ""
    if len(value) > 90 or "|" in value:
        return ""
    if _is_header_noise(value) or _is_header_fragment(value):
        return ""
    if re.search(
        r"\b(Office|Classification|Transaction|Who May Avail|Checklist|CLIENT STEPS|Total|Type of Transaction)\b",
        value,
        flags=re.I,
    ):
        return ""
    if original.endswith("."):
        return ""
    # Reject continuation / sentence fragments and tiny generic crumbs.
    lower = value.casefold()
    if re.match(r"^(?:this service|administrators? can|efficiently)\b", lower):
        return ""
    if re.fullmatch(
        r"(?:equipment|exit|services?|and technical staff|technical staff|staff|page)",
        lower,
    ):
        return ""
    if re.search(r"\b(?:administration|facilitation|interpretation|conduct|processing|issuance)\b", value, flags=re.I):
        # Allow concise service titles that start with Issuance/Processing.
        if not re.match(r"^(?:Issuance|Processing|Completion|Dropping|Enrollment)\b", value, flags=re.I):
            return ""
    # Prefer concise headings; descriptive sentences are less reliable service names.
    if len(value.split()) > 12:
        return ""
    try:
        from app.services.citizen_charter_services import (
            is_noise_service_title,
            strip_service_part_suffix,
        )

        value = strip_service_part_suffix(value)
        if is_noise_service_title(value):
            return ""
    except Exception:
        pass
    return value


def _extract_office(block: str) -> str:
    """Extract Office/Division value without capturing the label remnant."""
    patterns = [
        # Handle cleaner/label normalizer inserting ":" before a pipe.
        r"Office\s*(?:or)?\s*Division\s*:\s*\|?\s*([^|\n]+)",
        r"Office\s*(?:or)?\s*Division\s*\|\s*([^|\n]+)",
        r"(?m)^Office\s*(?:or)?\s*Division\s*$\n\s*([^|\n]+)",
        r"Office\s*(?:or)?\s*Division\s+([A-Z][^|\n]{2,90})",
    ]
    for pat in patterns:
        match = re.search(pat, block, flags=re.I | re.S)
        if not match:
            continue
        value = clean_ocr_text(match.group(1)).strip(" |:-\n\t")
        value = re.sub(r"\b(?:Classification|Who May Avail|Checklist|Service)\b.*$", "", value, flags=re.I)
        value = value.strip(" |:-")
        if _looks_like_office_value(value):
            return value

    # Fallback: Office: <name> only when it is not the charter "Office or Division" label.
    bare = re.search(r"(?m)^Office\s*[:\-]\s*([^|\n]+)$", block, flags=re.I)
    if bare:
        value = clean_ocr_text(bare.group(1)).strip(" |:-")
        if _looks_like_office_value(value):
            return value
    return NEEDS_REVIEW


def _looks_like_office_value(value: str) -> bool:
    if not value or value == NEEDS_REVIEW:
        return False
    lower = value.casefold().strip()
    if lower in {
        "or division",
        "division",
        "office",
        "office or division",
        "office / division",
        "office/division",
    }:
        return False
    if _is_header_noise(value) or _is_header_fragment(value):
        return False
    if not _looks_like_field_value(value):
        return False
    if re.search(r"\b(?:client steps?|agency actions?|checklist|who may avail)\b", lower):
        return False
    return True


def _extract_who_may_avail(block: str) -> str:
    table_like = re.search(
        r"Who\s+May\s+Avail\s*:\s*Checklist\s+of\s+Requirements.*?\|\s*([^|\n]+?)(?:\s+I?7o)?\s*(?:\|\s*Where\s+to\s+Secure|\n|$)",
        block,
        flags=re.I | re.S,
    )
    if table_like:
        value = _clean_who_value(table_like.group(1))
        if _looks_like_field_value(value):
            return value

    patterns = [
        r"Who\s+May\s+Avail\s*[:\|\-]?\s*(.+?)(?=\bChecklist\s+of\s+Requirements\b|\bData Privacy\b|\bCLIENT\s+STEPS\b|$)",
        r"\bWho\s*\|\s*(.+?)(?=\bChecklist\s+of\s+Requirements\b|\bData Privacy\b|\bCLIENT\s+STEPS\b|$)",
    ]
    value = _first(patterns, block, default="")
    value = _clean_who_value(value)
    if _looks_like_field_value(value):
        return value
    recovered = _recover_who_may_avail(block)
    return recovered if _looks_like_field_value(recovered) else NEEDS_REVIEW


def _recover_who_may_avail(block: str) -> str:
    lines = [clean_ocr_text(line.strip()) for line in block.splitlines() if line.strip()]
    for index, line in enumerate(lines):
        if not re.search(r"\bWho\s+(?:May\s+Avail)?\b", line, flags=re.I):
            continue
        same_line = _clean_who_value(
            re.sub(r"\bWho\s+(?:May\s+Avail)?\s*[:\|\-]?", "", line, flags=re.I)
        )
        if _looks_like_who_value(same_line):
            return same_line
        if index + 1 < len(lines):
            next_line = lines[index + 1]
            if _looks_like_who_value(next_line):
                return _clean_who_value(next_line)
    return ""


def _looks_like_who_value(value: str) -> bool:
    if not _looks_like_field_value(value):
        return False
    if "|" in value:
        return False
    if re.search(r"\b(Checklist|Requirement|Where to Secure|Client Steps|Agency|Processing Time)\b", value, flags=re.I):
        return False
    return len(value.split()) <= 12


def _clean_who_value(value: str) -> str:
    value = clean_ocr_text(value, remove_table_headers=True)
    value = re.sub(r"\bChecklist\s+of\s+Requirements\b.*$", "", value, flags=re.I | re.S)
    value = re.sub(r"\bWhere\s+to\s+Secure\b.*$", "", value, flags=re.I | re.S)
    value = re.sub(r"\bI?7o\b", "", value, flags=re.I)
    value = value.strip(" |:-")
    return value


def _looks_like_field_value(value: str) -> bool:
    if not value or value == NEEDS_REVIEW:
        return False
    if _is_header_noise(value):
        return False
    alpha_count = sum(1 for char in value if char.isalpha())
    return alpha_count >= 3


def _extract_requirements(block: str) -> list[Requirement]:
    table_requirements = _extract_requirement_table(block)
    if table_requirements:
        return table_requirements

    recovered_requirements = _recover_requirement_rows(block)
    if recovered_requirements:
        return recovered_requirements

    match = re.search(
        r"(?:Requirements?|Checklist\s+of\s+Requirements)\s*:\s*(.+?)(?:\bSteps\s*:|\bClient\s+Steps\b|\bProcessing\s+Time\s*:|\bTotal\s*:|$)",
        block,
        flags=re.I | re.S,
    )
    if not match:
        return [Requirement()]

    body = clean_ocr_text(match.group(1), remove_table_headers=True)
    where = _first([r"Where\s+to\s+Secure\s*:\s*([^\n;]+)"], body)
    items = _split_items(body)
    if not items:
        return [Requirement(where_to_secure=where)]
    return [Requirement(requirement=item, where_to_secure=where) for item in items]


def _recover_requirement_rows(block: str) -> list[Requirement]:
    """Recover requirement rows only inside Citizen Charter requirement zones."""
    if not _looks_like_citizen_charter_block(block):
        return []

    requirement_zone = _requirement_zone(block)
    if not requirement_zone:
        return []

    requirements: list[Requirement] = []
    for line in requirement_zone.splitlines():
        line = clean_ocr_text(line.strip())
        if not line or "|" not in line or _is_header_noise(line):
            continue
        cells = [clean_ocr_text(cell.strip(" |")) for cell in line.split("|") if cell.strip()]
        if len(cells) < 2:
            continue
        requirement = _clean_requirement_value(cells[0], role="requirement")
        where = _clean_requirement_value(cells[1], role="where")
        if _looks_like_requirement_row(requirement, where):
            requirements.append(
                Requirement(
                    requirement=requirement,
                    where_to_secure=where or NEEDS_REVIEW,
                )
            )
    return requirements


def _looks_like_citizen_charter_block(block: str) -> bool:
    signals = [
        r"\bOffice\s*(?:or)?\s*Division\b",
        r"\bCLIENT\s+STEPS\b",
        r"\bProcessing\s+Time\b",
        r"\bResponsible\s+Person",
    ]
    return sum(1 for pattern in signals if re.search(pattern, block, flags=re.I)) >= 2


def _requirement_zone(block: str) -> str:
    start = re.search(
        r"(?:Checklist\s+of\s+Requirements|Requirements?|Where\s+to\s+Secure)",
        block,
        flags=re.I,
    )
    if not start:
        return ""
    end = re.search(r"\bCLIENT\s+STEPS\b|\bSteps\s*:", block[start.end():], flags=re.I)
    zone_end = start.end() + end.start() if end else len(block)
    return block[start.start():zone_end]


def _looks_like_requirement_row(requirement: str, where: str) -> bool:
    if not requirement or _is_header_noise(requirement) or _is_header_fragment(requirement):
        return False
    if not where:
        return False
    if not _is_allowed_secure_source(where) and (
        _is_header_noise(where) or _is_header_fragment(where)
    ):
        return False
    if re.fullmatch(r"\d{1,2}[\.\)]?", requirement.strip()):
        return False
    if re.search(r"\b(Client Step|Agency|Processing Time|Responsible|Total|Fees?)\b", requirement, flags=re.I):
        return False
    if re.search(r"\b(minutes?|hours?|days?|N/A|Php|Free)\b", f"{requirement} {where}", flags=re.I):
        return False
    if len(requirement.split()) > 14 or len(where.split()) > 10:
        return False
    return True


def _extract_requirement_table(block: str) -> list[Requirement]:
    match = re.search(
        r"Checklist\s+of\s+Requirements\s*(?:\|\s*)?(?:Where\s+to\s+Secure)?\s*(.+?)(?:\bCLIENT\s+STEPS\b|\bSteps\s*:|\bTotal\s*:|$)",
        block,
        flags=re.I | re.S,
    )
    if not match:
        return []

    body = clean_ocr_text(match.group(1), remove_table_headers=True)
    requirements: list[Requirement] = []
    for line in body.splitlines():
        line = line.strip(" |")
        if not line or "|" not in line:
            continue
        if _is_header_noise(line):
            continue
        cells = [clean_ocr_text(cell.strip(" |")) for cell in line.split("|") if cell.strip()]
        if len(cells) < 2:
            continue
        requirement = _clean_requirement_value(cells[0], role="requirement")
        where = _clean_requirement_value(cells[1], role="where")
        if not requirement or _is_header_fragment(requirement) or _is_header_noise(requirement):
            continue
        if where and not _is_allowed_secure_source(where) and (
            _is_header_fragment(where) or _is_header_noise(where)
        ):
            where = ""
        if re.fullmatch(r"\d{1,2}[\.\)]?", requirement.strip()):
            continue
        if re.search(r"\b(Client Step|Agency|Processing Time|Responsible|Total|Fees?)\b", requirement, flags=re.I):
            continue
        requirements.append(
            Requirement(
                requirement=requirement,
                where_to_secure=where or NEEDS_REVIEW,
            )
        )

    return requirements


_SECURE_SOURCE_ALLOWLIST = frozenset(
    {
        "client",
        "applicant",
        "requesting party",
        "student",
        "students",
    }
)


def _is_allowed_secure_source(value: str) -> bool:
    return clean_ocr_text(str(value or "")).strip(" |:-").casefold() in _SECURE_SOURCE_ALLOWLIST


def _clean_requirement_value(value: str, *, role: str = "requirement") -> str:
    value = clean_ocr_text(value, remove_table_headers=True).strip(" |:-")
    value = re.sub(r"^(?:Checklist\s+of\s+Requirements|Where\s+to\s+Secure)\s*", "", value, flags=re.I)
    value = value.strip(" |:-")
    if role == "where" and _is_allowed_secure_source(value):
        return value
    if _is_header_fragment(value) or _is_header_noise(value):
        return ""
    if re.fullmatch(r"\d{1,2}[\.\)]?", value):
        return ""
    return value


def _split_items(text: str) -> list[str]:
    text = re.sub(r"Where\s+to\s+Secure\s*:?\s*[^\n;]*", " ", text, flags=re.I)
    numbered = list(re.finditer(r"(?<!\w)(\d{1,2})[\.\)]\s+", text))
    raw_items: list[str] = []
    if numbered:
        for index, marker in enumerate(numbered):
            start = marker.end()
            end = numbered[index + 1].start() if index + 1 < len(numbered) else len(text)
            raw_items.append(text[start:end])
    else:
        raw_items = re.split(r"[\n;]+", text)

    items: list[str] = []
    for item in raw_items:
        cleaned = clean_ocr_text(item.strip(" -:,;"), remove_table_headers=True)
        if len(cleaned) >= 3 and cleaned != NEEDS_REVIEW:
            items.append(cleaned)
    return items


def _extract_steps(block: str, service: str) -> list[Step]:
    table_steps = _extract_table_steps(block)
    if table_steps:
        return table_steps

    explicit = _extract_explicit_steps(block)
    if explicit:
        return explicit
    return [Step()]


def _extract_table_steps(block: str) -> list[Step]:
    match = re.search(
        r"CLIENT\s+STEPS\s*(?:\|.*?)?\n(.+?)(?:\n\s*Total\s*:|\n\s*Office\s+or\s+Division\s*:|\n\s*Service\s*:|$)",
        block,
        flags=re.I | re.S,
    )
    if not match:
        return []

    body = match.group(1)
    # Stop before the next Citizen's Charter service heading, not ordinary numbered rows.
    trimmed_lines: list[str] = []
    body_lines = body.splitlines()
    for index, line in enumerate(body_lines):
        following = "\n".join(body_lines[index + 1 : index + 12])
        if index > 0 and _is_probable_charter_service_start(line, following):
            break
        trimmed_lines.append(line)

    lines = [
        clean_ocr_text(line.strip())
        for line in trimmed_lines
        if line.strip() and not _is_header_noise(line.strip())
    ]
    rows = _reconstruct_step_rows(lines)
    steps: list[Step] = []
    for line in rows:
        if _is_header_noise(line) or _is_header_fragment(line):
            continue
        if "|" in line:
            cells = [clean_ocr_text(cell.strip(" |"), remove_table_headers=True) for cell in line.split("|")]
            cells = [cell for cell in cells if cell]
            step = _step_from_cells(cells)
            if step:
                steps.append(step)
            continue

        # Numbered non-pipe rows: treat remaining text as client step only when substantial.
        numbered = re.match(r"^(\d{1,2})[\.\)]\s+(.+)$", line.strip())
        if numbered:
            client = _clean_step_cell(numbered.group(2))
            if client and not _is_header_fragment(client) and len(client) >= 8:
                steps.append(Step(client_step=client))
            continue

        if steps:
            continuation = clean_ocr_text(line, remove_table_headers=True)
            if continuation and not _is_header_noise(continuation) and not _is_header_fragment(continuation):
                last = steps[-1]
                last.agency_action = _join_parts(last.agency_action, continuation)

    return steps


def _reconstruct_step_rows(lines: list[str]) -> list[str]:
    rows: list[str] = []
    current = ""
    for line in lines:
        if _is_header_noise(line) or _is_header_fragment(line):
            continue
        # Stop reconstructing when TOTAL appears.
        if re.match(r"^Total\b", line.strip(), flags=re.I):
            break
        if _starts_new_step_row(line):
            if current:
                rows.append(current)
            current = line
        else:
            current = _append_row_continuation(current, line)
    if current:
        rows.append(current)
    return rows


def _starts_new_step_row(line: str) -> bool:
    stripped = line.strip()
    # Numbered charter rows always start a new step, even without pipes.
    if re.match(r"^\d{1,2}[\.\)]\s+\S+", stripped):
        return not _is_header_noise(stripped) and not _is_header_fragment(stripped)
    if "|" not in stripped:
        return False
    cells = [cell.strip() for cell in stripped.split("|") if cell.strip()]
    if len(cells) < 2:
        return False
    first = cells[0]
    if not first:
        return False
    if first[0].islower():
        return False
    if _is_header_noise(first) or _is_header_fragment(first):
        return False
    if _is_header_noise(stripped):
        return False
    return True


def _append_row_continuation(current: str, line: str) -> str:
    if not current:
        return line
    if _is_header_noise(line) or _is_header_fragment(line):
        return current
    if "|" in line and "|" in current:
        current_cells = [cell.strip() for cell in current.split("|")]
        continuation_cells = [cell.strip() for cell in line.split("|")]
        for index, value in enumerate(continuation_cells):
            if not value or _is_header_fragment(value):
                continue
            if index < len(current_cells):
                current_cells[index] = _join_parts(current_cells[index], value)
            else:
                current_cells.append(value)
        return " | ".join(current_cells)
    if "|" in current:
        current_cells = [cell.strip() for cell in current.split("|")]
        if len(current_cells) >= 2:
            current_cells[1] = _join_parts(current_cells[1], line)
            return " | ".join(current_cells)
    return f"{current} {line}".strip()


def _is_continuation_row(cells: list[str]) -> bool:
    if not cells:
        return False
    first = cells[0].strip()
    if not first:
        return True
    return first[0].islower()


def _merge_continuation_cells(step: Step, cells: list[str]) -> None:
    if not cells:
        return
    step.client_step = _join_parts(step.client_step, _clean_step_cell(cells[0]))
    if len(cells) >= 2:
        step.agency_action = _join_parts(step.agency_action, _clean_step_cell(cells[1]))
    if len(cells) >= 3:
        time_value, responsible = _split_time_and_personnel(cells[2])
        if step.processing_time == NEEDS_REVIEW and time_value != NEEDS_REVIEW:
            step.processing_time = time_value
        if step.responsible_personnel == NEEDS_REVIEW and responsible != NEEDS_REVIEW:
            step.responsible_personnel = responsible


def _step_from_cells(cells: list[str]) -> Step | None:
    if len(cells) < 2:
        return None

    # Drop residual header fragments before mapping columns.
    cells = [_clean_step_cell(cell) for cell in cells]
    cells = [cell for cell in cells if cell and cell != NEEDS_REVIEW]
    if len(cells) < 2:
        return None
    if _is_fake_header_step_cells(cells):
        return None

    client_step = cells[0]
    agency_action = cells[1]
    fees = NEEDS_REVIEW
    processing_time = NEEDS_REVIEW
    responsible = NEEDS_REVIEW

    if len(cells) >= 5:
        agency_action, fee_from_action = _split_fee_from_action(agency_action)
        fees = cells[2] if cells[2] != NEEDS_REVIEW else fee_from_action
        processing_time, responsible = _split_time_and_personnel(" ".join(cells[3:]))
    elif len(cells) == 4:
        agency_action, fee_from_action = _split_fee_from_action(agency_action)
        fee_from_cell = _fee_value(cells[2])
        fees = fee_from_cell or fee_from_action
        processing_time, responsible = _split_time_and_personnel(cells[3])
    elif len(cells) == 3:
        agency_action, fee_from_action = _split_fee_from_action(agency_action)
        fee_from_cell = _fee_value(cells[2])
        fees = fee_from_cell or fee_from_action
        if not fee_from_cell:
            processing_time, responsible = _split_time_and_personnel(cells[2])

    row_text = " ".join(cells)
    agency_action, leading_time, leading_responsible = _split_leading_time_personnel_action(agency_action)
    if processing_time == NEEDS_REVIEW and leading_time != NEEDS_REVIEW:
        processing_time = leading_time
    if responsible == NEEDS_REVIEW and leading_responsible != NEEDS_REVIEW:
        responsible = leading_responsible
    processing_time, responsible = _complete_time_and_personnel(
        row_text=row_text,
        processing_time=processing_time,
        responsible=responsible,
    )

    client_step = _clean_step_cell(client_step)
    agency_action = _remove_known_step_fragments(
        _clean_step_cell(agency_action),
        fees,
        processing_time,
        responsible,
    )
    fees = _clean_step_cell(fees)
    processing_time = _clean_step_cell(processing_time)
    responsible = _clean_step_cell(responsible)

    if not client_step or _is_header_noise(client_step) or _is_header_fragment(client_step):
        return None
    if _is_header_fragment(agency_action) and _is_header_fragment(responsible):
        return None

    return Step(
        client_step=client_step,
        agency_action=agency_action or NEEDS_REVIEW,
        fees=fees or NEEDS_REVIEW,
        processing_time=processing_time or NEEDS_REVIEW,
        responsible_personnel=responsible or NEEDS_REVIEW,
    )


def _split_fee_from_action(value: str) -> tuple[str, str]:
    match = re.search(r"\b(N\s*/\s*A|N/A|n/a|None|Free|Php\s*[\d,.]+|P\s*[\d,.]+)\b", value, flags=re.I)
    if not match:
        return value, NEEDS_REVIEW
    action = " ".join(
        part.strip(" |,-")
        for part in [value[: match.start()], value[match.end() :]]
        if part.strip(" |,-")
    )
    fee = clean_ocr_text(match.group(1).strip())
    return action, fee


def _fee_value(value: str) -> str:
    _, fee = _split_fee_from_action(value)
    return "" if fee == NEEDS_REVIEW else fee


def _split_time_and_personnel(value: str) -> tuple[str, str]:
    value = clean_ocr_text(value, remove_table_headers=True).strip(" |:-")
    if not value:
        return NEEDS_REVIEW, NEEDS_REVIEW

    time_pattern = _time_pattern()
    match = re.search(time_pattern, value, flags=re.I)
    if not match:
        responsible = _clean_step_cell(value)
        return NEEDS_REVIEW, responsible if _looks_like_field_value(responsible) else NEEDS_REVIEW

    time_value = value[match.start() : match.end()].strip()
    before = value[: match.start()].strip(" |,-")
    after = value[match.end() :].strip(" |,-")
    responsible = " ".join(part for part in [before, after] if part)
    responsible = _clean_step_cell(responsible)
    return clean_ocr_text(time_value), responsible or NEEDS_REVIEW


def _complete_time_and_personnel(
    *,
    row_text: str,
    processing_time: str,
    responsible: str,
) -> tuple[str, str]:
    row_text = clean_ocr_text(row_text, remove_table_headers=True)
    time_value, nearby_responsible = _split_time_and_personnel(row_text)
    if processing_time == NEEDS_REVIEW and time_value != NEEDS_REVIEW:
        processing_time = time_value
    elif _time_lacks_number(processing_time):
        numbered_time = _find_numbered_time(row_text, processing_time)
        if numbered_time:
            processing_time = numbered_time

    if responsible == NEEDS_REVIEW and nearby_responsible != NEEDS_REVIEW:
        responsible = nearby_responsible

    return processing_time, responsible


def _time_pattern() -> str:
    return (
        r"\b(?:(?:\d+\s*(?:-\s*\d+)?|\d+\s+and\s+1/2|and\s+1/2)\s*)?"
        r"(?:minutes?|mins?|hours?|hrs?|days?)\b"
    )


def _time_lacks_number(value: str) -> bool:
    if not value or value == NEEDS_REVIEW:
        return False
    return bool(re.fullmatch(r"(?:minutes?|mins?|hours?|hrs?|days?)", value, flags=re.I))


def _find_numbered_time(row_text: str, current_time: str) -> str:
    unit_match = re.search(r"(minutes?|mins?|hours?|hrs?|days?)", current_time, flags=re.I)
    if not unit_match:
        return ""
    unit = unit_match.group(1)
    match = re.search(
        rf"(?<!page\s)(?<!section\s)(?<!article\s)\b(?:\d+\s*(?:-\s*\d+)?|\d+\s+and\s+1/2|and\s+1/2)\s*{unit}\b",
        row_text,
        flags=re.I,
    )
    return clean_ocr_text(match.group(0)) if match else ""


def _split_leading_time_personnel_action(value: str) -> tuple[str, str, str]:
    value = clean_ocr_text(value, remove_table_headers=True).strip(" |:-")
    match = re.match(rf"({_time_pattern()})\s+(.+)$", value, flags=re.I)
    if not match:
        return value, NEEDS_REVIEW, NEEDS_REVIEW

    time_value = clean_ocr_text(match.group(1))
    remainder = match.group(2).strip(" |,-")
    responsible, action = _split_responsible_prefix(remainder)
    return action or NEEDS_REVIEW, time_value, responsible or NEEDS_REVIEW


def _split_responsible_prefix(value: str) -> tuple[str, str]:
    tokens = value.split()
    if not tokens:
        return "", ""

    role_tokens = {
        "staff",
        "personnel",
        "counselor",
        "officer",
        "coordinator",
        "director",
        "head",
        "assistant",
        "adviser",
        "advisers",
    }
    prefix: list[str] = []
    for token in tokens:
        normalized = re.sub(r"[^A-Za-z]", "", token).lower()
        if token[:1].isupper() or normalized in role_tokens:
            prefix.append(token)
            if normalized in role_tokens:
                break
            continue
        break

    if not prefix:
        return "", value
    return " ".join(prefix), " ".join(tokens[len(prefix):])


def _remove_known_step_fragments(
    value: str,
    fees: str,
    processing_time: str,
    responsible: str,
) -> str:
    cleaned = value
    for fragment in [fees, processing_time, responsible]:
        if fragment and fragment != NEEDS_REVIEW:
            cleaned = re.sub(re.escape(fragment), " ", cleaned, flags=re.I)
    cleaned = clean_ocr_text(cleaned, remove_table_headers=True).strip(" |,-")
    return cleaned or NEEDS_REVIEW


def _clean_step_cell(value: str) -> str:
    value = clean_ocr_text(value, remove_table_headers=True)
    value = value.strip(" |:-")
    value = re.sub(r"^\d{1,2}[\.\)]\s+", "", value).strip(" |:-")
    if _is_header_fragment(value):
        return ""
    return value


def _join_parts(first: str, second: str) -> str:
    if not first or first == NEEDS_REVIEW:
        return second
    if not second:
        return first
    return f"{first} {second}".strip()


_HEADER_FRAGMENT_TOKENS = frozenset({
    "BE",
    "TIME",
    "RESPONSIBLE",
    "PAID",
    "ACTIONS",
    "STEPS",
    "PERSON",
    "PROCESSING",
    "FEES",
    "CLIENT",
    "AGENCY",
    "TO",
    "TOBE",
    "TOBEPAID",
    "FEESTOBE",
    "FEESTOBEPAID",
    "CLIENTSTEPS",
    "AGENCYACTIONS",
    "PROCESSINGTIME",
    "PERSONRESPONSIBLE",
    "RESPONSIBLEPERSON",
    "RESPONSIBLEPERSONNEL",
})


def _is_header_fragment(value: str) -> bool:
    """True for residual table-header crumbs like BE / TIME / RESPONSIBLE."""
    cleaned = clean_ocr_text(str(value or ""), remove_table_headers=True).strip(" |:-.")
    if not cleaned:
        return False
    compact = re.sub(r"[^A-Z0-9]", "", cleaned.upper())
    if compact in _HEADER_FRAGMENT_TOKENS:
        return True
    # Very short all-caps crumbs from mangled headers.
    if len(cleaned.split()) <= 2 and compact in {
        "BE", "TIME", "RESPONSIBLE", "PAID", "ACTIONS", "STEPS", "PERSON", "FEES", "CLIENT", "AGENCY"
    }:
        return True
    return bool(
        re.fullmatch(
            r"(?:client\s+steps?|agency\s+actions?|fees?(?:\s+to\s+be(?:\s+paid)?)?|"
            r"processing(?:\s+time)?|person(?:\s+responsible)?|responsible(?:\s+personnel)?|"
            r"to\s+be(?:\s+paid)?)",
            cleaned,
            flags=re.I,
        )
    )


def _is_fake_header_step_cells(cells: list[str]) -> bool:
    meaningful = [cell for cell in cells if cell and cell != NEEDS_REVIEW]
    if not meaningful:
        return True
    fragment_hits = sum(1 for cell in meaningful if _is_header_fragment(cell))
    if fragment_hits >= max(2, len(meaningful) - 1):
        return True
    joined = " ".join(meaningful).casefold()
    if re.search(r"\bbe\b", joined) and re.search(r"\btime\b", joined) and re.search(
        r"\bresponsible\b", joined
    ):
        return True
    return False


def _is_header_noise(value: str) -> bool:
    """True for charter table header cells — not for pipe-delimited data rows.

    Do not call is_noise_service_title here: that helper rejects titles containing
    '|', which would drop every valid CLIENT STEPS / requirements table row.
    """
    if _is_header_fragment(value):
        return True
    compact = re.sub(r"[^A-Z]", "", value.upper())
    if not compact:
        return False
    header_tokens = {
        "CLIENTSTEPS",
        "AGENCYACTIONS",
        "ACTIONSPAID",
        "FEESTOBEPAID",
        "FEESTOBE",
        "PROCESSINGTIME",
        "RESPONSIBLEPERSON",
        "RESPONSIBLEPERSONNEL",
        "PERSONRESPONSIBLE",
        "CHECKLISTOFREQUIREMENTS",
        "WHERETOSECURE",
        "TYPEOFTRANSACTION",
        "WHOMAYAVAIL",
        "OFFICEORDIVISION",
    }
    if compact in header_tokens or any(token in compact for token in header_tokens):
        return True
    return False


def _extract_explicit_steps(block: str) -> list[Step]:
    match = re.search(
        r"\bSteps\s*:\s*(.+?)(?:Processing\s+Time\s*:|Responsible\s+Personnel\s*:|Total\s*:|$)",
        block,
        flags=re.I | re.S,
    )
    if not match:
        return []

    body = re.sub(r"\s+", " ", match.group(1)).strip()
    processing_time = _first([r"Processing\s+Time\s*:\s*([^\n]+)"], block)
    responsible = _first([r"Responsible\s+Personnel\s*:\s*([^\n]+)", r"Person\s+Responsible\s*:\s*([^\n]+)"], block)
    markers = list(re.finditer(r"(?<!\w)(\d{1,2})[\.\)]\s+", body))
    if not markers:
        return [Step(client_step=body, processing_time=processing_time, responsible_personnel=responsible)] if body else []

    steps: list[Step] = []
    for index, marker in enumerate(markers):
        start = marker.end()
        end = markers[index + 1].start() if index + 1 < len(markers) else len(body)
        value = clean_ocr_text(body[start:end].strip(" ;,"), remove_table_headers=True)
        lowered = value.lower()
        if value and len(value) >= 8 and "fiica" not in lowered and "fica or" not in lowered:
            if not _is_header_fragment(value):
                steps.append(Step(client_step=value, processing_time=processing_time, responsible_personnel=responsible))
    return steps


def _extract_total(block: str, service: str) -> str:
    """Return total processing time; store fees separately via _parse_total_line when needed."""
    explicit = _first(
        [
            r"Total\s*[:\|]?\s*([^\n]+)",
            r"Processing\s+Time\s*:\s*([^\n]+)",
        ],
        block,
        default="",
    )
    if not explicit:
        return NEEDS_REVIEW
    _fees, processing = _parse_total_line(explicit)
    return processing if processing != NEEDS_REVIEW else explicit


def _parse_total_line(value: str) -> tuple[str, str]:
    """Split TOTAL line into (fees, processing_time)."""
    text = clean_ocr_text(value, remove_table_headers=True).strip(" |:-")
    if not text:
        return NEEDS_REVIEW, NEEDS_REVIEW

    # TOTAL: None | 4 minutes
    # TOTAL:P30.00/unit 25 minutes
    # TOTAL None 15 minutes
    # TOTAL: 1-3 days, 1 hr and 45 minutes
    fee = NEEDS_REVIEW
    processing = NEEDS_REVIEW

    time_unit = r"(?:minutes?|mins?|hours?|hrs?|days?|seconds?)"
    time_atom = (
        rf"(?:\d+\s+and\s+1/2|\d+(?:\.\d+)?(?:\s*-\s*\d+(?:\.\d+)?)?)\s*{time_unit}"
        rf"(?:\s+and\s+\d+(?:\.\d+)?\s*{time_unit})?"
    )
    time_matches = list(re.finditer(time_atom, text, flags=re.I))
    if time_matches:
        start = time_matches[0].start()
        end = time_matches[0].end()
        for match in time_matches[1:]:
            between = text[end : match.start()]
            if re.fullmatch(r"[\s,;/|]+", between or ""):
                end = match.end()
            else:
                break
        processing = clean_ocr_text(text[start:end]).strip(" ,;/")
        remainder = (text[:start] + " " + text[end:]).strip(" |:-")
    else:
        remainder = text

    fee_match = re.search(
        r"\b(N\s*/\s*A|N/A|n/a|None|Free|Php\s*[\d,.]+(?:/\w+)?|P\s*[\d,.]+(?:/\w+)?|"
        r"[\d,.]+(?:/\w+)?)\b",
        remainder,
        flags=re.I,
    )
    if fee_match:
        fee = clean_ocr_text(fee_match.group(1)).strip()
    elif remainder and not re.search(r"\b(?:minute|hour|day|second|hr)\b", remainder, flags=re.I):
        # leftover non-time text may still be a fee token like "None"
        cleaned = remainder.strip(" |:-")
        if cleaned and not _is_header_fragment(cleaned):
            fee = cleaned

    return fee or NEEDS_REVIEW, processing or NEEDS_REVIEW


def parse_form_document(text: str, *, source_document: str = "", preview_file_path: str = "") -> dict[str, Any]:
    cleaned = clean_ocr_text(text)
    office, office_detection_source = _extract_form_office(cleaned)
    form_title = _extract_form_name(cleaned)
    fields = _extract_form_fields(cleaned)
    options = _extract_form_options(cleaned)
    options_or_services = _flatten_form_options(options)
    record = FormRecord(
        office=office,
        office_detection_source=office_detection_source,
        form_title=form_title,
        form_name=form_title,
        form_code=_extract_form_code(cleaned),
        revision=_extract_revision(cleaned),
        date=_extract_form_date(cleaned),
        sections=_extract_form_sections(cleaned),
        fields=fields,
        options=options,
        options_or_services=options_or_services,
        requirements=_requirements_from_form_fields(fields),
        related_services=list(options_or_services),
        how_to_fill_out=_how_to_fill_out(fields, options_or_services),
        source_document=source_document,
        preview_file_path=preview_file_path,
        raw_extracted_text=cleaned,
        warnings=_duplicate_form_warnings(cleaned),
    )
    return {
        "status": "success",
        "document_type": "requirement",
        "display_document_type": "Requirement / Form Document",
        "form": record.to_dict(),
        "cleaned_text": cleaned,
    }


def _extract_form_office(text: str) -> tuple[str, str]:
    labeled = _first([
        r"(?:Office|Department|Unit|Division)\s*[:\-]\s*([^\n|]+)",
    ], text, default="")
    if _looks_like_field_value(labeled) and not _is_fillable_field_label(labeled):
        return labeled, "extracted_from_document"

    for line in _clean_lines(text)[:12]:
        candidate = _office_header_candidate(line)
        if candidate:
            return candidate, "extracted_from_document"

    return NEEDS_REVIEW, "unknown"


def _office_header_candidate(line: str) -> str:
    cleaned = _trim_form_value(line)
    if not cleaned:
        return ""
    if re.search(r"\b(?:Office|Department|Division|Unit|Services?)\b", cleaned, flags=re.I):
        if (
            not _is_fillable_field_line(cleaned)
            and not _is_footer_or_copy_line(cleaned)
            and not _clean_form_title(cleaned)
        ):
            return _title_case_preserving_acronyms(cleaned)

    words = re.findall(r"[A-Za-z]+", cleaned)
    if 2 <= len(words) <= 8 and re.search(r"\b(?:Services?|Office|Department|Division|Unit)\b", cleaned, flags=re.I):
        if not _is_fillable_field_line(cleaned) and not _clean_form_title(cleaned):
            return _title_case_preserving_acronyms(cleaned)
    return ""


def _extract_form_name(text: str) -> str:
    labeled = _first([
        r"(?:Form\s*Name|Title)\s*[:\-]\s*([^\n|]+)",
    ], text, default="")
    labeled = _clean_form_title(labeled)
    if labeled:
        return labeled

    lines = _clean_lines(text)
    for line in lines:
        candidate = _clean_form_title(line)
        if candidate and _is_strong_form_title(candidate):
            return candidate

    for index, line in enumerate(lines):
        if not re.search(r"\bForm\b", line, flags=re.I):
            continue
        candidates = []
        for start in range(max(0, index - 3), index + 1):
            title_lines = [
                candidate
                for candidate in lines[start : index + 1]
                if _looks_like_form_title_line(candidate)
            ]
            if title_lines:
                candidates.append(" ".join(title_lines))
        for candidate_text in sorted(candidates, key=len, reverse=True):
            candidate = _clean_form_title(candidate_text)
            if candidate:
                return candidate

    for line in lines:
        candidate = _clean_form_title(line)
        if candidate:
            return candidate
    return NEEDS_REVIEW


def _looks_like_form_title_line(line: str) -> bool:
    value = _trim_form_value(line)
    if not value or len(value) > 80:
        return False
    if (
        _is_fillable_field_line(value)
        or _is_footer_or_copy_line(value)
        or _is_form_boilerplate(value)
        or _is_office_header_line(value)
        or _is_government_location_header(value)
    ):
        return False
    if re.search(r"\b(?:Form Code|Document Code|REV|Revision|Date|Page)\b", value, flags=re.I):
        return False
    if re.search(r"[_\[\]☐☑□■|:]", value):
        return False
    return bool(re.search(r"[A-Za-z]{3,}", value))


def _clean_form_title(line: str) -> str:
    line = _trim_form_value(line)
    line = _strip_government_location_title_prefix(line)
    line = re.sub(r"\b(?:Republic of the Philippines|State Polytechnic University)\b", " ", line, flags=re.I)
    line = re.sub(r"\b[A-Z]{2,}(?:[-\s]+[A-Z]{2,})*[-\s]+(?:SF|FM|FR|FORM|F)[-\s]*\d{2,4}\b", " ", line, flags=re.I)
    line = re.sub(r"\bREV\.?\s*\d+\b", " ", line, flags=re.I)
    line = re.sub(r"\b(?:Page|Date)\s*[:\-].*$", " ", line, flags=re.I)
    line = normalize_inline_spaces(line)
    if not line or len(line) > 90:
        return ""
    if re.search(r"\b(?:Application|Request|Requisition|Evaluation|Registration|Clearance|Information|Access)\b.*\bForm\b", line, flags=re.I):
        return _title_case_preserving_acronyms(line)
    if re.match(r"^Request\s+for\b", line, flags=re.I):
        return _title_case_preserving_acronyms(line)
    if re.search(r"\b[A-Za-z][A-Za-z /&-]{2,}\s+(?:Request|Application)\b$", line, flags=re.I):
        return _title_case_preserving_acronyms(line)
    return ""


def _is_strong_form_title(value: str) -> bool:
    if not re.search(r"\b(?:Assistance\s+Request|Request|Application)\s+Form\b", value, flags=re.I):
        return False
    return len(value.split()) > 2


def _strip_government_location_title_prefix(value: str) -> str:
    if not _is_government_location_header(value):
        return value
    match = re.search(
        r"\b([A-Z]{2,}\s+[A-Za-z][A-Za-z ]{2,}?(?:Request|Application|Assistance)\s+Form)\b",
        value,
    )
    return match.group(1) if match else value


def _extract_form_code(text: str) -> str:
    standard_code = re.search(
        r"\b([A-Z]{2,8})[-\s]+([A-Z0-9]{2,8})[-\s]+S[F5][-\s]*(\d{3})\b",
        clean_ocr_text(text),
        flags=re.I,
    )
    if standard_code:
        return f"{standard_code.group(1).upper()}-{standard_code.group(2).upper()}-SF-{standard_code.group(3)}"

    patterns = [
        r"\b([A-Z]{2,8}(?:[-\s]+[A-Z0-9]{2,8}){0,3}[-\s]+(?:SF|FM|FR|FORM|F)[-\s]*\d{2,4})\b",
        r"\b((?:SF|FM|FR|FORM|F)[-\s]*\d{2,4})\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if match:
            return _normalize_code_value(match.group(1))
    return NEEDS_REVIEW


def _normalize_code_value(value: str) -> str:
    code = clean_ocr_text(value).upper()
    code = re.sub(r"\s+", "-", code)
    code = re.sub(r"-+", "-", code).strip("-")
    code = re.sub(r"\b5F\b", "SF", code)
    code = re.sub(r"-(?:0O|O0|OO)(\d)\b", r"-00\1", code)
    code = re.sub(r"-([A-Z]+)-0O(\d)\b", r"-\1-00\2", code)
    return code


def _extract_revision(text: str) -> str:
    explicit = _first([r"\b(REV\.?\s*\d+)\b", r"\bRevision\s*[:\-]?\s*([A-Za-z0-9\.\- ]+)"], text, default="")
    if explicit:
        return explicit
    for line in _clean_lines(text):
        if _extract_form_code(line) != NEEDS_REVIEW and re.search(r"\bAcv\b", line, flags=re.I):
            return "REV. 0"
    return NEEDS_REVIEW


def _extract_form_date(text: str) -> str:
    return _first([
        r"\bDate\s*[:\-]\s*([0-3]?\d\s+[A-Za-z]+\s+\d{4})",
        r"\bDate\s*[:\-]\s*([A-Za-z]+\s+[0-3]?\d,?\s+\d{4})",
        r"\b([0-3]?\d\s+[A-Za-z]+\s+\d{4})\b",
        r"\b([A-Za-z]+\s+[0-3]?\d,?\s+\d{4})\b",
        r"\b([A-Za-z]+\s+\d{4})\b",
    ], text)


def _extract_form_sections(text: str) -> list[str]:
    sections: list[str] = []
    form_name = _extract_form_name(text)
    for line in _clean_lines(text):
        candidate = _normalize_form_section_candidate(_trim_form_value(line).strip(" :-"))
        if (
            _is_footer_or_copy_line(candidate)
            or _is_same_text(candidate, form_name)
            or _is_office_header_line(candidate)
            or _is_form_title_fragment(candidate, form_name)
            or _is_fillable_field_label(candidate)
        ):
            continue
        if re.match(r"^(?:[IVXLCDM]+\.?|[A-Z]\.|\d+\.)\s+[A-Z][A-Za-z /&-]{2,}$", candidate):
            section = re.sub(r"^(?:[IVXLCDM]+\.?|[A-Z]\.|\d+\.)\s+", "", candidate)
            if _looks_like_form_section_heading(section):
                sections.append(_title_case_preserving_acronyms(section))
        elif _looks_like_form_section_heading(candidate):
            sections.append(_title_case_preserving_acronyms(candidate))
    return _unique_preserve_order(sections)


def _looks_like_form_section_heading(value: str) -> bool:
    if re.search(r"\b(?:Services?|Items?|Assistance)\s+Requested\b$", value, flags=re.I):
        return True
    if (
        _is_form_boilerplate(value)
        or _is_footer_or_copy_line(value)
        or _is_office_header_line(value)
        or _is_fillable_field_label(value)
        or re.search(r"\bForm\b", value, flags=re.I)
    ):
        return False
    if ":" in value or "|" in value or len(value.split()) > 5:
        return False
    return bool(
        re.search(
            r"\b(?:Information|Assessment|Details|Report|Requested|Requirements|Approval|Acknowledgement)\b$",
            value,
            flags=re.I,
        )
    )


def _normalize_form_section_candidate(value: str) -> str:
    cleaned = _trim_form_value(value)
    cleaned = re.sub(r"\b9(?=[A-Za-z])", "S", cleaned, flags=re.I)
    cleaned = re.sub(r"\b9\b", "S", cleaned, flags=re.I)
    normalized = re.sub(r"[^A-Za-z]+", " ", cleaned)
    normalized = re.sub(r"\bREQVESTED\b", "Requested", normalized, flags=re.I)
    normalized = re.sub(r"\b([A-Za-z]+)\s+S\s+(Requested|Needed)\b", r"\1s \2", normalized, flags=re.I)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if normalized and _looks_like_form_section_heading(normalized):
        return _title_case_preserving_acronyms(normalized)
    return cleaned


def _extract_form_fields(text: str) -> list[str]:
    fields: list[str] = []
    option_values = {
        option.lower()
        for values in _extract_form_options(text).values()
        for option in values
    }
    for line in _clean_lines(text):
        if _is_form_boilerplate(line) or _is_footer_metadata_line(line) or _is_role_only_label(line):
            continue
        if _line_is_checkbox_options(line):
            option_label = _option_group_label_from_line(line)
            if option_label and not _is_option_only_group_label(option_label):
                fields.append(option_label)
            continue
        fields.extend(
            label
            for label in _field_labels_from_line(line)
            if label.lower() not in option_values
        )
    return _normalize_form_fields(fields)


def _field_labels_from_line(line: str) -> list[str]:
    labels: list[str] = []
    if _line_is_checkbox_options(line):
        return labels
    for match in re.finditer(r"([A-Za-z][A-Za-z0-9 /().'-]{1,45})\s*(?:[:;_]{1,}|_{2,})", line):
        label = _clean_field_label(match.group(1))
        if label:
            labels.append(label)

    if "|" in line:
        cells = [cell.strip() for cell in line.split("|") if cell.strip()]
        for cell in cells:
            label = _clean_field_label(re.sub(r"[_:]+.*$", "", cell))
            if label:
                labels.append(label)

    return labels


def _clean_field_label(value: str) -> str:
    value = _trim_form_value(value)
    value = re.sub(r"^(?:Type of|Type)\s+", "Type of ", value, flags=re.I)
    value = re.sub(r"\bReq(?:uest)?or\b", "Requestor", value, flags=re.I)
    value = re.sub(r"\bSignat(?:ure)?\b", "Signature", value, flags=re.I)
    value = value.strip(" .:-;")
    if not value or len(value) > 45:
        return ""
    if (
        _is_form_boilerplate(value)
        or _is_footer_metadata_line(value)
        or _is_role_only_label(value)
        or _is_option_only_group_label(value)
    ):
        return ""
    if re.search(r"\b(?:form|revision|republic|philippines|university|polytechnic|campus|rev|acv)\b", value, flags=re.I):
        return ""
    label = _canonical_field_label(_title_case_preserving_acronyms(value))
    return label if _is_confident_form_field_label(label) else ""


def _extract_form_options(text: str) -> dict[str, list[str]]:
    options: dict[str, list[str]] = {}
    current_key = ""
    for line in _clean_lines(text):
        if _is_form_boilerplate(line) or _is_footer_metadata_line(line):
            continue
        label_match = re.search(r"\b(Type\s+of\s+[A-Za-z /]+|[A-Za-z /]+)\s*[:\-]\s*(.*)$", line, flags=re.I)
        if label_match:
            possible_label = _clean_option_group_label(label_match.group(1))
            if possible_label and _is_option_block_terminator(possible_label):
                current_key = ""
                continue
            if possible_label and _is_option_group_label(possible_label):
                current_key = _snake_key(possible_label)
                trailing = label_match.group(2)
                found = _option_values_from_line(trailing)
                if not found:
                    found = _delimited_option_values(trailing)
                if found:
                    options.setdefault(current_key, [])
                    options[current_key].extend(found)
                    if any(_is_other_specify_option(value) for value in found):
                        current_key = ""
                continue
        if re.search(r"\bplease\s+check\s+(?:all\s+)?applicable\b", line, flags=re.I):
            current_key = "options_or_services"
            continue
        found = _option_values_from_line(line)
        if current_key and found:
            options.setdefault(current_key, [])
            options[current_key].extend(found)
            if any(_is_other_specify_option(value) for value in found):
                current_key = ""
            continue
        if _looks_like_form_section_heading(_normalize_form_section_candidate(line)) or _is_option_block_terminator(line):
            current_key = ""
            continue
        if current_key and _looks_like_standalone_option_line(line):
            found = _standalone_option_values(line)
            options.setdefault(current_key, [])
            options[current_key].extend(found)
            if any(_is_other_specify_option(value) for value in found):
                current_key = ""
    return {key: _unique_preserve_order(values) for key, values in options.items() if values}


def _option_group_label_from_line(line: str) -> str:
    label_match = re.search(r"\b(Type\s+of\s+[A-Za-z /]+|[A-Za-z /]+)\s*[:\-]\s*", line, flags=re.I)
    if not label_match:
        return ""
    label = _clean_option_group_label(label_match.group(1))
    if label and _is_option_group_label(label):
        return label
    return ""


def _is_option_group_label(label: str) -> bool:
    if _is_option_block_terminator(label):
        return False
    return bool(re.search(
        r"\b(type|status|category|mode|purpose|request|requested|account|service|services|needed|applicable|option)\b",
        label,
        flags=re.I,
    ))


def _is_option_block_terminator(value: str) -> bool:
    cleaned = _trim_form_value(value)
    normalized = re.sub(r"[^a-z]+", " ", cleaned.lower()).strip()
    if _is_role_only_label(cleaned):
        return True
    if normalized in {
        "requested by",
        "requestor signature",
        "requester signature",
        "received by",
        "approved by",
        "printed name signature",
        "signature over printed name",
        "remarks",
        "comments",
    }:
        return True
    return bool(re.search(
        r"\b(?:requested|received|approved)\s+by\b|\bsignature\b|\bassessment\b|\brat(?:e|ing)\b|\bremarks?\b",
        cleaned,
        flags=re.I,
    ))


def _clean_option_group_label(value: str) -> str:
    value = _trim_form_value(value).strip(" .:-")
    if not value or len(value) > 45:
        return ""
    if _is_form_boilerplate(value) or _is_footer_metadata_line(value) or _is_role_only_label(value):
        return ""
    return _title_case_preserving_acronyms(value)


def _is_option_only_group_label(value: str) -> bool:
    return bool(re.search(r"\b(?:Services?|Items?|Assistance)\s+Needed\b$", value, flags=re.I))


def _option_values_from_line(line: str) -> list[str]:
    checkbox_pattern = r"(?:\[[ xX/]\]|\(\s*[xX/ ]?\s*\)|☐|☑|□|■)\s*([A-Za-z][A-Za-z0-9 /&().'-]{1,35})"
    values = [_clean_option_value(match.group(1)) for match in re.finditer(checkbox_pattern, line)]
    values = [value for value in values if value]
    if values:
        return values
    bracket_pattern = r"\[\s*([A-Za-z][A-Za-z0-9 /&().'-]{1,35})\s*\]"
    values = [_clean_option_value(match.group(1)) for match in re.finditer(bracket_pattern, line)]
    values = [value for value in values if value and not re.fullmatch(r"[xX/]", value)]
    if values:
        return values
    return []


def _delimited_option_values(value: str) -> list[str]:
    if not value or re.search(r"_{2,}", value):
        return []
    if not re.search(r"\s{2,}|\||,|;", value):
        return []
    parts = re.split(r"\s{2,}|\||,|;", value)
    return [_clean_option_value(part) for part in parts if _clean_option_value(part)]


def _looks_like_standalone_option_line(line: str) -> bool:
    value = _trim_form_value(line).strip(" -")
    if not value or len(value) > 80:
        return False
    if _is_option_block_terminator(value):
        return False
    if re.search(r"\b(?:when|date|time|venue)\s+(?:needed|required)\b", value, flags=re.I):
        return False
    if _is_fillable_field_line(value) or _is_form_boilerplate(value) or _is_footer_or_copy_line(value):
        return False
    if ":" in value:
        return False
    if re.match(r"^(?:[A-Z]\.|\d+\.)\s+", value):
        return True
    words = re.findall(r"[A-Za-z][A-Za-z0-9/&().'-]*", value)
    if not (1 <= len(words) <= 5):
        return False
    return bool(re.search(r"[A-Za-z]{3,}", value))


def _standalone_option_values(line: str) -> list[str]:
    value = re.sub(r"^(?:[A-Z]\.|\d+\.)\s+", "", _trim_form_value(line).strip(" -"))
    delimited = _delimited_option_values(value)
    if delimited:
        return delimited
    cleaned = _clean_option_value(value)
    return [cleaned] if cleaned else []


def _is_other_specify_option(value: str) -> bool:
    normalized = re.sub(r"[^a-z]+", " ", value.lower()).strip()
    return bool(re.search(r"\b(?:others?|orhers?)\b", normalized) and re.search(r"\bspec(?:ify|ilyl|ily)\b", normalized))


def _flatten_form_options(options: dict[str, list[str]]) -> list[str]:
    values: list[str] = []
    for option_values in options.values():
        values.extend(option_values)
    return _unique_preserve_order(values)


def _requirements_from_form_fields(fields: list[str]) -> list[str]:
    return _unique_preserve_order([field for field in fields if field and field != NEEDS_REVIEW])


def _how_to_fill_out(fields: list[str], options_or_services: list[str]) -> list[str]:
    instructions = ["Fill in the required requester information."]
    if options_or_services:
        instructions.append("Select the applicable service option if available.")
    if any(re.search(r"\bdescription\b", field, flags=re.I) for field in fields):
        instructions.append("Provide a description if the form includes a description field.")
    if any(re.search(r"\bsignature|signed|sign\b", field, flags=re.I) for field in fields):
        instructions.append("Sign the form if a signature field is present.")
    instructions.append("Submit the completed form to the indicated office.")
    return instructions


def _line_is_checkbox_options(line: str) -> bool:
    return bool(re.search(r"(?:\[[ xX/]\]|\(\s*[xX/ ]?\s*\)|☐|☑|□|■)", line))


def _is_fillable_field_line(value: str) -> bool:
    value = _trim_form_value(value)
    if _line_is_checkbox_options(value):
        return True
    if re.search(r"[_]{2,}", value):
        return True
    label = re.sub(r"[:_].*$", "", value).strip(" |:-")
    return _is_fillable_field_label(label)


def _is_fillable_field_label(value: str) -> bool:
    label = re.sub(r"[^A-Za-z/ ]+", " ", value)
    label = re.sub(r"\s+", " ", label).strip().lower()
    return label in {
        "name",
        "date",
        "college/office",
        "office",
        "user name",
        "description",
        "requestor signature",
        "approved",
        "approved by",
        "approved",
        "requested by",
        "requester name",
        "contact number",
        "signature",
        "item received",
        "date received",
        "description of the problem",
        "assigned personnel",
        "expected finish date/time",
        "endorsement",
        "event title",
        "date needed",
        "rating",
        "comments",
    }


def _is_footer_or_copy_line(value: str) -> bool:
    return bool(re.search(
        r"\b(?:copy|staff|signature|prepared by|received by|servicing staff|page\s*\d+)\b",
        value,
        flags=re.I,
    ))


def _is_office_header_line(value: str) -> bool:
    cleaned = _trim_form_value(value)
    if not cleaned or re.search(r"\bForm\b", cleaned, flags=re.I):
        return False
    if re.search(r"\b(?:Requested|Report|Assessment|Acknowledgement|Information)\b", cleaned, flags=re.I):
        return False
    if _is_fillable_field_label(cleaned):
        return False
    normalized = re.sub(r"[^A-Z]+", " ", cleaned.upper())
    if all(token in normalized for token in ["INFORMATION", "COMMUNICATION", "TECHNOLOGY"]):
        return True
    if _is_government_location_header(cleaned):
        return True
    return bool(re.search(
        r"\b(?:Office|Department|Division|Unit|Services|University|College)\b",
        cleaned,
        flags=re.I,
    ))


def _is_government_location_header(value: str) -> bool:
    return bool(re.search(
        r"\b(?:province|provincu|prowincu|laguna|republic|philippines|university|services)\b",
        value,
        flags=re.I,
    ))


def _is_same_text(first: str, second: str) -> bool:
    normalize = lambda value: re.sub(r"[^a-z0-9]+", "", value.lower())
    return bool(first and second and normalize(first) == normalize(second))


def _is_form_title_fragment(value: str, form_name: str) -> bool:
    if not value or not form_name:
        return False
    if re.search(r"\b(?:Information|Assessment|Report|Requirements|Approval)\b$", value, flags=re.I):
        return False
    normalize = lambda text: re.sub(r"[^a-z0-9]+", "", text.lower())
    fragment = normalize(value)
    title = normalize(form_name)
    return bool(fragment and len(fragment) >= 6 and fragment in title)


def _clean_option_value(value: str) -> str:
    value = _trim_form_value(value)
    value = re.sub(r"\bPlease\s+specify\b.*$", "", value, flags=re.I)
    value = value.strip(" .:-_")
    if not value or len(value) > 35:
        return ""
    if _is_form_boilerplate(value):
        return ""
    return _title_case_preserving_acronyms(value)


def _is_footer_metadata_line(value: str) -> bool:
    cleaned = _trim_form_value(value)
    if _extract_form_code(cleaned) != NEEDS_REVIEW:
        return True
    return bool(re.fullmatch(
        r"(?:REV\.?\s*\d+|Rev|REV|Acv|(?:[A-Za-z]+\s+)?\d{4}|[0-3]?\d\s+[A-Za-z]+\s+\d{4})",
        cleaned,
        flags=re.I,
    ))


def _is_role_only_label(value: str) -> bool:
    cleaned = _trim_form_value(value)
    if re.fullmatch(r"(?:Requested|Received|Approved)\s+By", cleaned, flags=re.I):
        return False
    compact = re.sub(r"[^a-z]+", " ", cleaned.lower()).strip()
    role_patterns = [
        r"\bict\s+servicing\s+staff\b",
        r"\bservicing\s+staff\b",
        r"\bicts?\s+director\b",
        r"\bdirector\b",
        r"\bchairperson\b",
        r"\bhead\s+of\s+office\b",
        r"\bauthorized\s+representative\b",
        r"\bprinted\s+name\s+signature\b",
        r"\bsignature\s+over\s+printed\s+name\b",
    ]
    return any(re.search(pattern, compact) for pattern in role_patterns)


def _duplicate_form_warnings(text: str) -> list[str]:
    warnings: list[str] = []
    code = _extract_form_code(text)
    if code != NEEDS_REVIEW and len(re.findall(re.escape(code), text, flags=re.I)) > 1:
        warnings.append("Multiple identical form copies detected. Please crop or split before OCR.")
    name = _extract_form_name(text)
    if name != NEEDS_REVIEW and len(re.findall(re.escape(name), text, flags=re.I)) > 1:
        warnings.append("Multiple identical form copies detected. Please crop or split before OCR.")
    return _unique_preserve_order(warnings)


def _clean_lines(text: str) -> list[str]:
    return [clean_ocr_text(line.strip()) for line in text.splitlines() if line.strip()]


def _trim_form_value(value: str) -> str:
    value = clean_ocr_text(value)
    value = _split_compacted_form_heading(value)
    value = re.sub(r"[_]{2,}", " ", value)
    value = re.sub(r"\s+", " ", value).strip(" |:-")
    return value


def _split_compacted_form_heading(value: str) -> str:
    value = re.sub(
        r"\b([A-Za-z]{3,}?)(INFORMATION|ASSESSMENT|DETAILS|REQUEST|SERVICE)\b",
        lambda m: f"{m.group(1)} {m.group(2)}",
        value,
        flags=re.I,
    )
    return value


def normalize_inline_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" |:-")


def _title_case_preserving_acronyms(value: str) -> str:
    words = []
    small_words = {"and", "or", "of", "for", "to", "the", "a", "an"}
    acronym_stop_words = {
        "USER",
        "FORM",
        "TYPE",
        "DATE",
        "NAME",
        "TIME",
        "PAGE",
        "COPY",
        "REV",
        "AND",
        "OF",
        "FOR",
        "THE",
    }
    known_terms = {
        term.lower(): term
        for term in re.findall(r"\b[A-Z]{2,4}\b", value)
        if term not in acronym_stop_words
    }
    for index, word in enumerate(value.split()):
        stripped = re.sub(r"[^A-Za-z0-9]", "", word)
        lowered = stripped.lower()
        if lowered in known_terms:
            words.append(re.sub(re.escape(stripped), known_terms[lowered], word, flags=re.I))
        elif index > 0 and lowered in small_words:
            words.append(word.lower())
        elif "/" in word:
            words.append("/".join(_title_case_preserving_acronyms(part) for part in word.split("/")))
        else:
            words.append(word[:1].upper() + word[1:].lower())
    return " ".join(words)


def _is_form_boilerplate(value: str) -> bool:
    return bool(re.search(
        r"\b(?:Republic|Philippines|State|Polytechnic|University|Campus|Form Code|Document Code|Revision|REV|Effectivity|Page)\b",
        value,
        flags=re.I,
    ))


def _snake_key(value: str) -> str:
    key = re.sub(r"[^A-Za-z0-9]+", "_", value.lower()).strip("_")
    return key


def _unique_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        key = value.lower()
        if value and key not in seen:
            seen.add(key)
            unique.append(value)
    return unique


def _is_confident_form_field_label(value: str) -> bool:
    if not value or _is_role_only_label(value) or _is_footer_metadata_line(value):
        return False
    if _is_known_form_field_label(value):
        return True
    if _has_poor_ocr_field_quality(value):
        return False
    words = re.findall(r"[A-Za-z][A-Za-z/]*", value)
    if not words or len(words) > 6:
        return False
    return bool(re.search(
        r"\b(?:Name|Date|Office|Contact|Signature|Description|Problem|Received|Assigned|Personnel|Expected|Finish|Endorsement|Venue|Time|Department)\b",
        value,
        flags=re.I,
    ))


def _is_known_form_field_label(value: str) -> bool:
    compact = re.sub(r"[^a-z/]+", " ", value.lower())
    compact = re.sub(r"\s+", " ", compact).strip()
    return compact in {
        "requester name",
        "college/office",
        "contact number",
        "signature",
        "item received",
        "date received",
        "description of the problem",
        "assigned icts personnel",
        "expected finish date/time",
        "endorsement",
        "requested by",
        "received by",
        "approved by",
        "approved",
        "name",
        "date",
        "venue",
        "time",
    }


def _has_poor_ocr_field_quality(value: str) -> bool:
    if re.search(r"[@}\[\]'\"]", value):
        return True
    compact = re.sub(r"\s+", "", value)
    if compact:
        alpha_ratio = sum(char.isalpha() for char in compact) / len(compact)
        if alpha_ratio < 0.65:
            return True
    tokens = re.findall(r"\S+", value)
    unreadable = 0
    for token in tokens:
        core = re.sub(r"[^A-Za-z0-9]", "", token)
        if len(core) >= 8 and not re.search(r"[aeiouAEIOU]", core):
            unreadable += 1
        if re.search(r"[A-Za-z]\d|\d[A-Za-z]", core):
            unreadable += 1
    return unreadable >= 2


def _normalize_form_fields(fields: list[str]) -> list[str]:
    normalized = [_canonical_field_label(field) for field in fields]
    unique = _unique_preserve_order([field for field in normalized if field])
    if "Approved By" in unique and "Approved" in unique:
        unique = [field for field in unique if field != "Approved"]
    return unique


def _canonical_field_label(value: str) -> str:
    cleaned = _trim_form_value(value).strip(" .:-;")
    compact = re.sub(r"[^a-z/]+", " ", cleaned.lower())
    compact = re.sub(r"\s+", " ", compact).strip()
    aliases = {
        "collcec/omcc": "College/Office",
        "college/office": "College/Office",
        "dale": "Date",
        "duic": "Date",
        "date": "Date",
        "acceivcd by": "Received By",
        "received by": "Received By",
        "approved dy": "Approved By",
        "approved by": "Approved By",
        "approved": "Approved",
        "requested by": "Requested By",
        "requester name": "Requester Name",
        "contact number": "Contact Number",
        "signature": "Signature",
        "item received": "Item Received",
        "date received": "Date Received",
        "description of the problem": "Description of the Problem",
        "assigned personnel": "Assigned Personnel",
        "expected finish date/time": "Expected Finish Date/Time",
        "endorsement": "Endorsement",
        "nomo": "Name",
        "name": "Name",
        "venve": "Venue",
        "venue": "Venue",
        "fma": "Time",
        "time": "Time",
    }
    return aliases.get(compact, cleaned)


def parse_structured_document(text: str) -> dict[str, Any]:
    cleaned = clean_ocr_text(text)
    document_type = classify_document_type(cleaned)
    if document_type == "form":
        return parse_form_document(cleaned)

    services: list[ServiceRecord] = []
    for block in _service_blocks(cleaned, document_type=document_type):
        has_service_label = re.search(
            r"\b(?:Office\s*(?:or)?\s*Division|Service|Requirements?|Steps|CLIENT\s+STEPS|Checklist\s+of\s+Requirements)\s*[:|]?",
            block,
            flags=re.I,
        )
        if not has_service_label:
            continue

        service = _extract_service_name(block)
        try:
            from app.services.citizen_charter_services import is_artifact_charter_title

            # Drop named artifacts only. Untitled blocks may still be recovered later.
            if (
                document_type == "citizen_charter"
                and service
                and service != NEEDS_REVIEW
                and is_artifact_charter_title(service)
            ):
                continue
        except Exception:
            pass

        total_raw = _first(
            [r"Total\s*[:\|]?\s*([^\n]+)", r"Processing\s+Time\s*:\s*([^\n]+)"],
            block,
            default="",
        )
        total_fees, total_processing = _parse_total_line(total_raw) if total_raw else (NEEDS_REVIEW, NEEDS_REVIEW)
        if total_processing == NEEDS_REVIEW and total_raw:
            total_processing = total_raw

        requirements = _extract_requirements(block)
        steps = _extract_steps(block, service)
        cleaned_block = clean_ocr_text(block, remove_table_headers=True)
        dropped_headers = [
            token
            for token in (
                "CLIENT STEPS",
                "AGENCY ACTIONS",
                "FEES TO BE PAID",
                "PROCESSING TIME",
                "PERSON RESPONSIBLE",
                "BE",
                "TIME",
                "RESPONSIBLE",
            )
            if re.search(rf"\b{re.escape(token)}\b", block, flags=re.I)
            and not re.search(rf"\b{re.escape(token)}\b", cleaned_block, flags=re.I)
        ]
        rejected_fake_steps = 0
        # Count potential header-only rows that were present before filtering.
        for line in block.splitlines():
            if "|" not in line:
                continue
            cells = [c.strip() for c in line.split("|") if c.strip()]
            if _is_fake_header_step_cells(cells):
                rejected_fake_steps += 1

        record = ServiceRecord(
            office=_extract_office(block),
            service=service,
            classification=_first(
                [r"Classification\s*[:\-]?\s*\|?\s*([^|\n]+)", r"\b(Simple|Complex|Highly\s+Technical)\b"],
                block,
            ),
            transaction_type=_first(
                [
                    r"Type\s+of\s+Transaction\s*[:\-]?\s*\|?\s*([^|\n]+)",
                    r"Transaction\s*[:\-]?\s*\|?\s*([Gg]\d[GgCc](?:\s*/\s*[Gg]\d[GgCc])?)",
                    r"\b(G2G\s*G2C|G2C|G2G)\b",
                ],
                block,
            ),
            who_may_avail=_extract_who_may_avail(block),
            requirements=requirements,
            steps=steps,
            total_processing_time=total_processing,
            total_fees=total_fees,
            parser_debug={
                "raw_service_block": block[:4000],
                "cleaned_service_block": cleaned_block[:4000],
                "dropped_header_fragments": dropped_headers,
                "reconstructed_step_rows": len(steps),
                "rejected_fake_steps": rejected_fake_steps,
                "requirement_pairs_detected": len(requirements or []),
                "total_line_detected": bool(total_raw),
            },
        )
        services.append(record)

    service_dicts = [s.to_dict() for s in services]
    charter_dropped_noise = 0
    charter_merged_splits = 0
    if document_type == "citizen_charter":
        from app.services.citizen_charter_services import merge_charter_services

        raw_block_count = len(service_dicts)
        service_dicts = merge_charter_services(service_dicts)
        if service_dicts:
            charter_dropped_noise = int(service_dicts[0].get("_charter_dropped_noise") or 0)
            charter_merged_splits = int(service_dicts[0].get("_charter_merge_events") or 0)
        else:
            charter_dropped_noise = raw_block_count

    if not service_dicts:
        service_dicts = [ServiceRecord(requirements=[Requirement()], steps=[Step()]).to_dict()]
    result = {
        "status": "success",
        "document_type": document_type,
        "services": service_dicts,
        "cleaned_text": cleaned,
    }
    if document_type == "citizen_charter":
        result["charter_dropped_noise"] = charter_dropped_noise
        result["charter_merged_splits"] = charter_merged_splits
        result["charter_detected_blocks"] = (
            len(service_dicts) + charter_merged_splits + charter_dropped_noise
        )
    return result


def format_structured_document(parsed: dict[str, Any] | str) -> str:
    if isinstance(parsed, str):
        parsed = parse_structured_document(parsed)
    if parsed.get("document_type") in {"form", "requirement"} and parsed.get("form"):
        return _format_form_document(parsed)

    out: list[str] = []
    for svc in parsed.get("services", []):
        out.append(f"Office: {svc.get('office', NEEDS_REVIEW)}")
        out.append(f"Service: {svc.get('service', NEEDS_REVIEW)}")
        out.append(f"Classification: {svc.get('classification', NEEDS_REVIEW)}")
        out.append(f"Transaction Type: {svc.get('transaction_type', NEEDS_REVIEW)}")
        out.append(f"Who May Avail: {svc.get('who_may_avail', NEEDS_REVIEW)}")
        out.append("Requirements:")
        for r in svc.get("requirements", []):
            out.append(f"  - Requirement: {r.get('requirement', NEEDS_REVIEW)}")
            out.append(f"    Where to Secure: {r.get('where_to_secure', NEEDS_REVIEW)}")
        out.append("Steps:")
        for i, st in enumerate(svc.get("steps", []), start=1):
            out.append(f"  {i}. Client Step: {st.get('client_step', NEEDS_REVIEW)}")
            out.append(f"     Agency Action: {st.get('agency_action', NEEDS_REVIEW)}")
            out.append(f"     Fees: {st.get('fees', NEEDS_REVIEW)}")
            out.append(f"     Processing Time: {st.get('processing_time', NEEDS_REVIEW)}")
            out.append(f"     Responsible Personnel: {st.get('responsible_personnel', NEEDS_REVIEW)}")
        out.append(f"Total Processing Time: {svc.get('total_processing_time', NEEDS_REVIEW)}")
        out.append("\n---\n")
    return "\n".join(out).strip()


def _format_form_document(parsed: dict[str, Any]) -> str:
    form = parsed.get("form", {})
    out = [
        "Document Type:",
        f"  {form.get('display_document_type') or 'Requirement / Form Document'}",
        "",
        "Basic Information:",
        f"  - Form Title: {form.get('form_title') or form.get('form_name', NEEDS_REVIEW)}",
        f"  - Office: {form.get('office', NEEDS_REVIEW)}",
        f"  - Office Detection Source: {form.get('office_detection_source', 'unknown')}",
        f"  - Form Code: {form.get('form_code', NEEDS_REVIEW)}",
        f"  - Revision: {form.get('revision', NEEDS_REVIEW)}",
        f"  - Date: {form.get('date', NEEDS_REVIEW)}",
    ]
    warnings = form.get("warnings") or []
    if warnings:
        out.append("Warnings:")
        for warning in warnings:
            out.append(f"  - {warning}")
    sections = form.get("sections") or []
    if sections:
        out.append("Sections:")
        for section in sections:
            out.append(f"  - {section}")
    fields = form.get("fields") or []
    if fields:
        out.append("Fields / Required Information:")
        for field_name in fields:
            out.append(f"  - {field_name}")
    options_or_services = form.get("options_or_services") or _flatten_form_options(form.get("options") or {})
    out.append("Options / Services:")
    if options_or_services:
        for option in options_or_services:
            out.append(f"  - {option}")
    else:
        out.append("  - None found in the uploaded document.")
    requirements = form.get("requirements") or _requirements_from_form_fields(fields)
    out.append("Generated Requirements:")
    if requirements:
        for requirement in requirements:
            out.append(f"  - {requirement}")
    else:
        out.append("  - None found in the uploaded document.")
    how_to_fill_out = form.get("how_to_fill_out") or _how_to_fill_out(fields, options_or_services)
    out.append("How to Fill Out:")
    for instruction in how_to_fill_out:
        out.append(f"  - {instruction}")
    related_services = form.get("related_services") or list(options_or_services)
    out.append("Related Services:")
    if related_services:
        for service in related_services:
            out.append(f"  - {service}")
    else:
        out.append("  - None found in the uploaded document.")
    return "\n".join(out).strip()


# Backward-compatible aliases.
def parse_document(text: str) -> dict[str, Any]:
    return parse_structured_document(text)


def structure_text(text: str) -> str:
    return format_structured_document(parse_structured_document(text))

def build_structured_document(text: str, *, source_document: str = "", preview_file_path: str = "") -> StructuredDocument:
    """
    Basic fallback structured parser.

    This prevents backend import errors and gives the knowledge-base
    pipeline a valid structured document format.
    """
    parsed = parse_structured_document(text)
    if parsed.get("document_type") in {"form", "requirement"} and parsed.get("form"):
        parsed["form"]["source_document"] = source_document
        parsed["form"]["preview_file_path"] = preview_file_path
    formatted = _mark_unclear_words(format_structured_document(parsed))
    if parsed.get("document_type") in {"form", "requirement"} and parsed.get("form"):
        form = parsed.get("form", {})
        fields: list[DocumentField] = [
            DocumentField("Document Type", "text", value="requirement"),
            DocumentField("Display Document Type", "text", value=form.get("display_document_type", "Requirement / Form Document")),
            DocumentField("Form Title", "text", value=_mark_unclear_words(form.get("form_title") or form.get("form_name", NEEDS_REVIEW))),
            DocumentField("Office", "text", value=_mark_unclear_words(form.get("office", NEEDS_REVIEW))),
            DocumentField("Office Detection Source", "text", value=form.get("office_detection_source", "unknown")),
            DocumentField("Form Name", "text", value=_mark_unclear_words(form.get("form_name", NEEDS_REVIEW))),
            DocumentField("Form Code", "text", value=_mark_unclear_words(form.get("form_code", NEEDS_REVIEW))),
            DocumentField("Revision", "text", value=_mark_unclear_words(form.get("revision", NEEDS_REVIEW))),
            DocumentField("Date", "text", value=_mark_unclear_words(form.get("date", NEEDS_REVIEW))),
            DocumentField("Sections", "list", items=[_mark_unclear_words(item) for item in form.get("sections", [])] or []),
            DocumentField("Fields", "list", items=[_mark_unclear_words(item) for item in form.get("fields", [])] or []),
            DocumentField("Options / Services", "list", items=[_mark_unclear_words(item) for item in form.get("options_or_services", [])] or []),
            DocumentField("Generated Requirements", "list", items=[_mark_unclear_words(item) for item in form.get("requirements", [])] or []),
            DocumentField("How to Fill Out", "list", items=[_mark_unclear_words(item) for item in form.get("how_to_fill_out", [])] or []),
            DocumentField("Related Services", "list", items=[_mark_unclear_words(item) for item in form.get("related_services", [])] or []),
            DocumentField("Source Document", "text", value=form.get("source_document", "")),
            DocumentField("Preview File Path", "text", value=form.get("preview_file_path", "")),
        ]
        for key, values in (form.get("options") or {}).items():
            fields.append(DocumentField(f"Options: {key}", "list", items=[_mark_unclear_words(item) for item in values]))
        if form.get("warnings"):
            fields.append(DocumentField("Warnings", "list", items=form["warnings"]))
        return StructuredDocument(fields=fields, formatted_text=formatted)

    services = parsed.get("services", [])
    first = services[0] if services else {}

    fields: list[DocumentField] = [
        DocumentField("Office", "text", value=_mark_unclear_words(first.get("office", NEEDS_REVIEW))),
        DocumentField("Service", "text", value=_mark_unclear_words(first.get("service", NEEDS_REVIEW))),
        DocumentField("Classification", "text", value=_mark_unclear_words(first.get("classification", NEEDS_REVIEW))),
        DocumentField("Transaction Type", "text", value=_mark_unclear_words(first.get("transaction_type", NEEDS_REVIEW))),
        DocumentField("Who May Avail", "text", value=_mark_unclear_words(first.get("who_may_avail", NEEDS_REVIEW))),
    ]

    req_items = [
        _mark_unclear_words(req.get("requirement", NEEDS_REVIEW))
        for req in first.get("requirements", [])
        if req.get("requirement")
    ]
    fields.append(DocumentField("Requirements", "list", items=req_items or [NEEDS_REVIEW]))

    step_items = [
        _mark_unclear_words(step.get("client_step", NEEDS_REVIEW))
        for step in first.get("steps", [])
        if step.get("client_step")
    ]
    fields.append(DocumentField("Steps", "list", items=step_items or [NEEDS_REVIEW]))
    fields.append(
        DocumentField(
            "Total Processing Time",
            "text",
            value=_mark_unclear_words(first.get("total_processing_time", NEEDS_REVIEW)),
        )
    )

    return StructuredDocument(fields=fields, formatted_text=formatted)


def _mark_unclear_words(text: str) -> str:
    return re.sub(r"\b\S*\?\S*\b", NEEDS_REVIEW, text)
