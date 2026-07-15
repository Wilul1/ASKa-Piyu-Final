"""Deterministic student-facing answers for Citizen Charter / service procedures."""

from __future__ import annotations

import re
from typing import Any

from app.services.chroma_store import RetrievedChunk


_NEEDS_REVIEW = re.compile(r"\[?\s*needs\s+review\s*\]?", re.I)
_PLACEHOLDER = re.compile(r"^(not specified|n/?a|none of the above|client steps|agency actions)$", re.I)


def is_form_or_requirement_query(question: str) -> bool:
    normalized = _normalize(question)
    return bool(
        re.search(
            r"\b(?:form|fill\s+out|how to fill|application form|request form|"
            r"checklist of requirements|what (?:documents?|requirements?) do i need for (?:the )?form)\b",
            normalized,
        )
    )


def is_service_howto_query(question: str) -> bool:
    if is_form_or_requirement_query(question):
        return False
    normalized = _normalize(question)
    return bool(
        re.search(
            r"\b(?:how (?:do|can|to)|where (?:do|can|to)|steps?|procedure|process|"
            r"validate|validation|avail|apply|request|secure|claim|reclaim)\b",
            normalized,
        )
    ) or " id" in f" {normalized} "


def is_service_procedure_chunk(chunk: RetrievedChunk) -> bool:
    metadata = chunk.metadata or {}
    doc_type = _normalize(
        str(
            metadata.get("document_type")
            or metadata.get("parser_document_type")
            or metadata.get("source_document_type")
            or ""
        )
    )
    article_type = _normalize(str(metadata.get("article_type") or metadata.get("content_type") or ""))
    source_type = _normalize(str(metadata.get("source_type") or ""))
    if article_type in {"service_procedure", "procedure"}:
        return True
    if doc_type in {"citizen_charter", "procedure"}:
        return True
    if "citizen" in source_type and "charter" in source_type:
        return True
    text = chunk.text or ""
    return bool(
        re.search(r"(?im)^(?:Office\s*/\s*Division|Client Step:|Total Processing Time)\b", text)
    )


def is_artifact_or_requirement_form_chunk(chunk: RetrievedChunk) -> bool:
    metadata = chunk.metadata or {}
    title = _chunk_title(chunk)
    article_type = _normalize(str(metadata.get("article_type") or metadata.get("content_type") or ""))
    extraction_status = _normalize(str(metadata.get("extraction_status") or ""))
    text = chunk.text or ""
    if article_type in {"requirement_form", "requirement", "form"}:
        return True
    if extraction_status == "rag_only":
        return True
    if _normalize(title).startswith("requirement:"):
        return True
    if _NEEDS_REVIEW.search(title) or _NEEDS_REVIEW.search(text[:400]):
        return True
    if re.search(r"(?im)^(Form Preview|Related Services|How to Fill Out)\s*:", text):
        return True
    if is_artifact_like_title(title):
        return True
    return False


def is_artifact_like_title(title: str) -> bool:
    cleaned = (title or "").strip()
    if not cleaned:
        return True
    lowered = cleaned.lower()
    if lowered.startswith("requirement:"):
        return True
    if _NEEDS_REVIEW.search(cleaned):
        return True
    noisy = (
        "abstract of quotation",
        "approving officials",
        "nexus system",
        "client steps",
        "agency actions",
        "fees to be paid",
        "person responsible",
    )
    return any(token in lowered for token in noisy)


def prefer_service_chunks(
    chunks: list[RetrievedChunk],
    *,
    question: str,
) -> list[RetrievedChunk]:
    """Keep semantic hits, but demote/filter form artifacts for service questions."""
    if not chunks:
        return chunks
    if is_form_or_requirement_query(question):
        return chunks

    preferred: list[RetrievedChunk] = []
    demoted: list[RetrievedChunk] = []
    for chunk in chunks:
        if is_artifact_or_requirement_form_chunk(chunk):
            demoted.append(chunk)
            continue
        preferred.append(chunk)
    if not preferred:
        return chunks
    # Prefer complete charter service procedures first among preferred.
    preferred.sort(
        key=lambda chunk: (
            0 if is_service_procedure_chunk(chunk) and _has_usable_service_fields(chunk) else 1,
            0 if is_service_procedure_chunk(chunk) else 1,
        )
    )
    return preferred + demoted


def format_service_procedure_answer(
    chunk: RetrievedChunk,
    sources: list[dict[str, Any]] | None = None,
    *,
    busy_fallback: bool = False,
) -> str:
    """Format a Citizenship Charter / service procedure answer.

    ``busy_fallback`` is retained for call-site compatibility but no longer
    injects user-facing “AI busy” wording — LLM failures are logged only.
    """
    del busy_fallback  # unused; kept for API compatibility
    fields = extract_service_fields(chunk)
    title = fields["title"]
    lines: list[str] = [
        f"To complete {title}, follow the steps below.",
    ]

    lines.extend(["", "Requirements:"])
    if fields["requirements"]:
        lines.extend(f"- {item}" for item in fields["requirements"])
    else:
        lines.append("- Not specified in the cited source.")

    lines.extend(["", "Steps:"])
    if fields["steps"]:
        for index, step in enumerate(fields["steps"], start=1):
            lines.append(f"{index}. {step}")
    else:
        lines.append("1. See the cited source for the documented client steps.")

    lines.extend(
        [
            "",
            f"Office: {fields['office']}",
            f"Processing Time: {fields['processing_time']}",
            f"Fee: {fields['fee']}",
            "",
            f"Source: {_format_source_line(chunk, sources)}",
        ]
    )
    return "\n".join(lines).strip()


def extract_service_fields(chunk: RetrievedChunk) -> dict[str, Any]:
    metadata = chunk.metadata or {}
    text = chunk.text or ""
    title = (
        _clean_value(metadata.get("canonical_topic"))
        or _clean_value(metadata.get("source_section"))
        or _clean_value(metadata.get("procedure_title"))
        or _clean_value(metadata.get("title"))
        or _chunk_title(chunk)
        or "this service"
    )
    if _normalize(title).startswith("requirement:"):
        title = _extract_labeled_block(text, "Service") or "this service"

    office = (
        _clean_value(metadata.get("office"))
        or _clean_value(metadata.get("responsible_office"))
        or _extract_section_value(text, "Office / Division")
        or _extract_labeled_block(text, "Office")
        or "Not specified"
    )

    requirements = _requirements_from_metadata(metadata) or _requirements_from_text(text)
    steps = _steps_from_metadata(metadata) or _steps_from_text(text)
    fee = (
        _clean_value(metadata.get("fees"))
        or _clean_value(metadata.get("fee"))
        or _extract_section_value(text, "Fees")
        or _fee_from_steps_text(text)
        or "None"
    )
    processing_time = (
        _clean_value(metadata.get("total_processing_time"))
        or _extract_section_value(text, "Total Processing Time")
        or _extract_labeled_block(text, "Processing Time")
        or "Not specified"
    )
    page = metadata.get("page_number") or metadata.get("page") or _page_from_text(text)

    return {
        "title": title,
        "office": office,
        "requirements": requirements,
        "steps": steps,
        "fee": fee if fee.lower() not in {"not specified", ""} else "None",
        "processing_time": processing_time,
        "page": int(page) if isinstance(page, int) or (isinstance(page, str) and page.isdigit()) else None,
    }


def _has_usable_service_fields(chunk: RetrievedChunk) -> bool:
    fields = extract_service_fields(chunk)
    return bool(fields["requirements"] or fields["steps"]) and not is_artifact_like_title(fields["title"])


def _chunk_title(chunk: RetrievedChunk) -> str:
    metadata = chunk.metadata or {}
    for key in ("source_section", "canonical_topic", "title", "section", "article", "procedure_title"):
        value = _clean_value(metadata.get(key))
        if value:
            return value
    return (chunk.title or "").strip()


def _requirements_from_metadata(metadata: dict[str, Any]) -> list[str]:
    raw = metadata.get("extracted_requirements") or metadata.get("requirements")
    items: list[Any]
    if isinstance(raw, str):
        try:
            import json

            parsed = json.loads(raw)
            items = parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            items = []
    elif isinstance(raw, list):
        items = raw
    else:
        items = []
    output: list[str] = []
    for item in items:
        if isinstance(item, dict):
            value = _clean_value(item.get("requirement") or item.get("name"))
        else:
            value = _clean_value(item)
        if value and not _PLACEHOLDER.match(value):
            output.append(value)
    return output


def _requirements_from_text(text: str) -> list[str]:
    output: list[str] = []
    for match in re.finditer(r"(?im)^\s*-\s*Requirement:\s*(.+?)\s*$", text or ""):
        value = _clean_value(match.group(1))
        if value and not _PLACEHOLDER.match(value):
            output.append(value)
    if output:
        return output
    # Bulleted list under Requirements section.
    section = _extract_section_block(text, "Requirements")
    for line in section.splitlines():
        stripped = line.strip()
        if stripped.startswith("-"):
            value = _clean_value(re.sub(r"^-\s*", "", stripped))
            value = re.sub(r"(?i)^requirement:\s*", "", value).strip()
            if value and not _PLACEHOLDER.match(value) and not value.lower().startswith("where to secure"):
                output.append(value)
    return output


def _steps_from_metadata(metadata: dict[str, Any]) -> list[str]:
    raw = metadata.get("extracted_steps") or metadata.get("steps")
    if isinstance(raw, str):
        try:
            import json

            parsed = json.loads(raw)
            items = parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            items = []
    elif isinstance(raw, list):
        items = raw
    else:
        items = []
    output: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            value = _clean_value(item)
            if value and not _PLACEHOLDER.match(value):
                output.append(value)
            continue
        client = _clean_value(item.get("client_step"))
        agency = _clean_value(item.get("agency_action"))
        if client and not _PLACEHOLDER.match(client):
            output.append(client.rstrip("."))
        if agency and not _PLACEHOLDER.match(agency) and agency != client:
            # Phrase agency action as a student-facing process beat.
            if not agency.lower().startswith(("osas", "the ", "office")):
                agency = f"OSAS / office: {agency}"
            output.append(agency.rstrip("."))
    return output


def _steps_from_text(text: str) -> list[str]:
    output: list[str] = []
    for match in re.finditer(
        r"(?im)^\s*\d+\.\s*Client Step:\s*(.+?)\s*$",
        text or "",
    ):
        client = _clean_value(match.group(1))
        if client and not _PLACEHOLDER.match(client):
            output.append(client.rstrip("."))
        # Pull following Agency Action line if present.
        after = text[match.end() : match.end() + 220]
        agency_match = re.search(r"(?im)^\s*Agency Action:\s*(.+?)\s*$", after)
        if agency_match:
            agency = _clean_value(agency_match.group(1))
            if agency and not _PLACEHOLDER.match(agency) and agency != client:
                if re.search(r"(?i)\bcheck|verify|evaluate|release|issue|accept\b", agency):
                    # Prefer office-natural phrasing when agency names are missing.
                    if not re.search(r"(?i)\b(osas|office|registrar|cashier|clinic)\b", agency):
                        agency = f"OSAS {agency[0].lower()}{agency[1:]}" if agency else agency
                    output.append(agency.rstrip("."))
    if output:
        return output
    # Fallback: plain numbered lines.
    for line in (text or "").splitlines():
        match = re.match(r"^\s*\d+\.\s+(.+)$", line.strip())
        if not match:
            continue
        value = _clean_value(match.group(1))
        value = re.sub(r"(?i)^client step:\s*", "", value).strip()
        if value and not _PLACEHOLDER.match(value):
            output.append(value.rstrip("."))
    return output


def _fee_from_steps_text(text: str) -> str:
    fees = re.findall(r"(?im)^\s*Fees:\s*(.+?)\s*$", text or "")
    cleaned = [_clean_value(item) for item in fees]
    cleaned = [item for item in cleaned if item and not _PLACEHOLDER.match(item)]
    if not cleaned:
        return ""
    unique = list(dict.fromkeys(cleaned))
    if all(item.lower() in {"none", "n/a", "free"} for item in unique):
        return "None"
    return unique[0]


def _extract_section_value(text: str, heading: str) -> str:
    block = _extract_section_block(text, heading)
    for line in block.splitlines():
        value = _clean_value(line)
        if value and _normalize(value) != _normalize(heading):
            return value
    return ""


def _extract_section_block(text: str, heading: str) -> str:
    pattern = rf"(?ims)^\s*{re.escape(heading)}\s*\n(.*?)(?=^\s*[A-Z][A-Za-z0-9 /&-]{{2,40}}\s*$|\Z)"
    match = re.search(pattern, text or "")
    return match.group(1).strip() if match else ""


def _extract_labeled_block(text: str, label: str) -> str:
    match = re.search(rf"(?im)^\s*{re.escape(label)}\s*:\s*(.+?)\s*$", text or "")
    return _clean_value(match.group(1)) if match else ""


def _page_from_text(text: str) -> int | None:
    match = re.search(r"(?im)^\s*Page:\s*(\d+)\s*$", text or "")
    if match:
        return int(match.group(1))
    return None


def _format_source_line(chunk: RetrievedChunk, sources: list[dict[str, Any]] | None) -> str:
    if sources:
        source = sources[0]
        label = str(source.get("source_label") or source.get("title") or "").strip()
        section = str(source.get("source_section") or source.get("path") or "").strip()
        page = source.get("page_number") if source.get("page_number") is not None else source.get("page")
        parts = [part for part in (label, section) if part]
        if page is not None:
            parts.append(f"page {page}")
        if parts:
            return ", ".join(parts)
    metadata = chunk.metadata or {}
    label = (
        _clean_value(metadata.get("source_label"))
        or _clean_value(metadata.get("source_document"))
        or chunk.source_filename
        or "Citizen’s Charter"
    )
    section = _clean_value(metadata.get("source_section")) or _chunk_title(chunk)
    page = metadata.get("page_number") or metadata.get("page") or _page_from_text(chunk.text or "")
    parts = [label]
    if section and _normalize(section) != _normalize(label):
        parts.append(section)
    if page is not None:
        parts.append(f"page {page}")
    return ", ".join(str(part) for part in parts if part)


def _clean_value(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if _NEEDS_REVIEW.search(text):
        return ""
    return re.sub(r"\s+", " ", text).strip()


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()
