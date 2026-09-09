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


def is_factual_service_detail_query(question: str) -> bool:
    """True for office/fee/time/document FAQs that must not use step dumps."""
    normalized = _normalize(question)
    return bool(
        re.search(
            r"\b(?:how much|how long|how many|which office|what office|who may|who can|"
            r"who handles|responsible|in charge|"
            r"what (?:are|is) the (?:fee|fees|requirement|requirements|document|documents|"
            r"edition|year|total)|"
            r"what documents|what additional|what must|"
            r"documents? (?:are )?required|requirements? (?:for|from|needed)|"
            r"fee for|cost of|processing time)\b",
            normalized,
        )
    )


def format_requirements_detail_answer(
    question: str,
    chunk: RetrievedChunk,
    sources: list[dict[str, Any]] | None = None,
) -> str | None:
    """Build a requirements/documents answer from one charter/service chunk."""
    if not _chunk_fits_requirements_question(question, chunk):
        return None
    fields = extract_service_fields(chunk)
    metadata = chunk.metadata or {}
    title = (
        _clean_value(metadata.get("source_section"))
        or _clean_value(metadata.get("canonical_topic"))
        or _clean_value(metadata.get("procedure_title"))
        or fields["title"]
    )
    if "enroll" in _normalize(question) and re.search(r"\benrol(?:l)?ment\b", _normalize(title)):
        title = "Enrollment"

    requirements = _requirements_for_audience(question, chunk, fields["requirements"])
    requirements = [_clean_document_requirement(item) for item in requirements]
    requirements = [item for item in requirements if item and _looks_like_document_requirement(item)]
    # De-dupe while preserving order.
    deduped: list[str] = []
    seen: set[str] = set()
    for item in requirements:
        key = _normalize(item)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    requirements = deduped
    if not requirements:
        return None

    source_label = _format_source_line(chunk, sources)
    audience = _audience_hint(question)
    preface = (
        f"For {audience} under {title}, the required documents are:"
        if audience
        else f"The required documents for {title} are:"
    )
    lines = [preface, ""]
    lines.extend(f"- {item}" for item in requirements)
    if fields["office"]:
        lines.extend(["", f"Office: {fields['office']}"])
    lines.extend(["", f"Source: {source_label}"])
    return "\n".join(lines).strip()


def _chunk_fits_requirements_question(question: str, chunk: RetrievedChunk) -> bool:
    """Avoid handbook process sections when asking enrollment document FAQs."""
    normalized_q = _normalize(question)
    metadata = chunk.metadata or {}
    title = _normalize(
        " ".join(
            str(value or "")
            for value in (
                metadata.get("source_section"),
                metadata.get("title"),
                metadata.get("section"),
                chunk.title,
            )
        )
    )
    doc_type = _normalize(
        str(
            metadata.get("document_type")
            or metadata.get("parser_document_type")
            or metadata.get("article_type")
            or ""
        )
    )
    text_norm = _normalize(chunk.text or "")
    if "enroll" not in normalized_q:
        return True
    if "visitation" in title or "article 3" in title:
        return False
    if "registration" in title and "enrollment" not in title and "enrolment" not in title:
        if "citizen" not in doc_type and "service_procedure" not in doc_type:
            return False
    if re.search(r"\benrol(?:l)?ment\b", title) or "citizen" in doc_type or "service_procedure" in doc_type:
        return True
    return "for old students" in text_norm or "for new" in text_norm


def _audience_hint(question: str) -> str | None:
    normalized = _normalize(question)
    if re.search(r"\b(?:old|continuing|returnee|returnees)\b", normalized):
        return "old / continuing students"
    if re.search(r"\b(?:new|freshmen|incoming)\b", normalized):
        return "new students"
    if re.search(r"\b(?:transferee|transferees|transfer)\b", normalized):
        return "transferees"
    return None


def _requirements_for_audience(
    question: str,
    chunk: RetrievedChunk,
    fallback_requirements: list[str],
) -> list[str]:
    normalized = _normalize(question)
    text = chunk.text or ""

    audience_headers = ()
    if re.search(r"\b(?:old|continuing|returnee|returnees)\b", normalized):
        audience_headers = (
            "For Old Students",
            "Old Students",
            "For Continuing Students",
            "Continuing Students",
        )
    elif re.search(r"\b(?:new|freshmen|incoming)\b", normalized):
        audience_headers = (
            "For New College Students",
            "For New Students",
            "New College Students",
            "New Students",
        )
    elif re.search(r"\b(?:transferee|transferees|transfer)\b", normalized):
        audience_headers = ("For Transferees", "Transferees", "For Transfer Students")

    for header in audience_headers:
        section = _extract_audience_section(text, header)
        if section:
            items = _requirements_from_text(section)
            if not items:
                inline = re.search(rf"(?im)^{re.escape(header)}\s*[:\-]\s*(.+)$", text)
                if inline:
                    items = _split_requirement_items(inline.group(1))
            items = [
                _clean_document_requirement(item)
                for item in items
                if _looks_like_document_requirement(_clean_document_requirement(item))
            ]
            if items:
                return items

    docs = [
        _clean_document_requirement(item)
        for item in (fallback_requirements or [])
        if _looks_like_document_requirement(_clean_document_requirement(item))
    ]
    if audience_headers:
        # If audience was requested, only return generic docs when section parsing failed
        # and docs still look like document names (not process sentences).
        return docs
    return docs


def _extract_audience_section(text: str, header: str) -> str:
    """Return text under an audience header until the next audience/major section."""
    pattern = re.compile(
        rf"(?is)(?:^|\n)\s*{re.escape(header)}\s*:?\s*\n(.*?)(?="
        r"\n\s*For (?:Old|New|Continuing|Transfer)|"
        r"\n\s*(?:Old|New|Continuing)\s+Students\b|"
        r"\n\s*Transferees?\b|"
        r"\n\s*(?:Who May Avail|Office\s*/\s*Division|Steps|Fees|Total Processing Time|Client Step)\b|"
        r"\Z)",
    )
    match = pattern.search(text or "")
    return (match.group(1) or "").strip() if match else ""


def _looks_like_document_requirement(value: str) -> bool:
    normalized = _normalize(value)
    if not normalized or len(normalized) < 3:
        return False
    if re.search(
        r"\b(?:onsite|online registration|registration is|may also be available|"
        r"follow the|submit to|go to|proceed to|approval of the dean|"
        r"faculty-in-charge|through the university portal|initials of)\b",
        normalized,
    ):
        return False
    if len(normalized.split()) > 18 and not re.search(
        r"\b(?:certificate|clearance|id|form|card|tor|transcript|diploma|receipt|envelope|picture|photo)\b",
        normalized,
    ):
        return False
    return True


def _clean_document_requirement(value: str) -> str:
    cleaned = _clean_value(value)
    cleaned = re.sub(r"(?i)^(?:for\s+)?(?:old|new|continuing)\s+students?\s*[:\-]\s*", "", cleaned).strip()
    cleaned = re.sub(r"(?i)^requirement:\s*", "", cleaned).strip()
    cleaned = re.sub(r"(?i)\s*where to secure:.*$", "", cleaned).strip()
    # Drop OCR numbering leftovers like "1. Clearance 1."
    cleaned = re.sub(r"^\d+\.\s*", "", cleaned).strip()
    cleaned = re.sub(r"\s+\d+\.$", "", cleaned).strip()
    return cleaned


def _split_requirement_items(raw: str) -> list[str]:
    cleaned = re.sub(r"\s+", " ", raw or "").strip()
    if not cleaned:
        return []
    parts = re.split(r"\s*(?:,|;|\band\b)\s*", cleaned, flags=re.I)
    output: list[str] = []
    for part in parts:
        value = _clean_document_requirement(part)
        if value and not _PLACEHOLDER.match(value) and len(value) > 2 and _looks_like_document_requirement(value):
            output.append(value)
    if len(output) >= 2:
        return output
    value = _clean_document_requirement(cleaned)
    return [value] if value and _looks_like_document_requirement(value) else []


def is_service_howto_query(question: str) -> bool:
    """True only for process / how-to intents, not factual charter FAQs."""
    if is_form_or_requirement_query(question):
        return False
    if is_factual_service_detail_query(question):
        return False
    normalized = _normalize(question)
    return bool(
        re.search(
            r"\b(?:how (?:do|can|to) i|how (?:do|can|to)|where (?:do|can|to) i|"
            r"where (?:do|can|to)|steps to|step by step|procedure for|process for|"
            r"how to (?:validate|apply|request|secure|claim|reclaim|avail|enroll|drop)|"
            r"can i (?:apply|request|validate|enroll))\b",
            normalized,
        )
    )


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
    """Keep semantic hits, but demote/filter form artifacts for service questions.

    Service-procedure boosting applies only for how-to / office / charter-detail
    questions. Institutional identity questions (vision, mission, quality policy)
    must keep handbook ranking — otherwise random charter services jump to #1.
    """
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

    normalized_question = _normalize(question)
    service_oriented = (
        is_service_howto_query(question)
        or is_factual_service_detail_query(question)
        or ("office" in normalized_question and "responsible" in normalized_question)
        or ("office" in normalized_question and "handles" in normalized_question)
        or ("which office" in normalized_question)
        or ("what office" in normalized_question)
    )

    # For non-service questions (definitions, policies, identity, etc.), keep semantic
    # ranking but demote unrelated charter service procedures so they do not leap to #1.
    if not service_oriented:
        preferred.sort(
            key=lambda chunk: (
                0 if _chunk_overlaps_question_topic(chunk, normalized_question) else 1,
                1
                if is_service_procedure_chunk(chunk)
                and not _chunk_overlaps_question_topic(chunk, normalized_question)
                else 0,
                -(
                    chunk.reranked_score
                    if chunk.reranked_score is not None
                    else chunk.relevance_score or 0.0
                ),
            )
        )
        return preferred + demoted

    # Prefer complete charter service procedures, then title match to the asked service.
    preferred.sort(
        key=lambda chunk: (
            0 if is_service_procedure_chunk(chunk) and _has_usable_service_fields(chunk) else 1,
            0 if is_service_procedure_chunk(chunk) else 1,
            _service_title_mismatch_rank(chunk, normalized_question),
            0 if _chunk_office_present(chunk) else 1,
        )
    )
    return preferred + demoted


def _chunk_overlaps_question_topic(chunk: RetrievedChunk, normalized_question: str) -> bool:
    """True when chunk title/section/text shares contentful tokens with the question."""
    stop = {
        "what", "which", "who", "how", "when", "where", "why", "the", "a", "an",
        "is", "are", "was", "were", "do", "does", "did", "can", "for", "of", "to",
        "in", "on", "at", "by", "with", "from", "about", "that", "this", "it",
        "lspu", "university", "please", "tell", "me", "regarding", "prior",
        "question", "context",
    }
    q_tokens = {
        token
        for token in re.findall(r"[a-z0-9]+", normalized_question)
        if token not in stop and len(token) >= 3
    }
    if not q_tokens:
        return True
    blob = _normalize(
        " ".join(
            str(value or "")
            for value in (
                (chunk.metadata or {}).get("source_section"),
                (chunk.metadata or {}).get("section"),
                (chunk.metadata or {}).get("canonical_topic"),
                (chunk.metadata or {}).get("title"),
                chunk.title,
                (chunk.text or "")[:320],
            )
        )
    )
    return any(token in blob for token in q_tokens)


def _service_title_mismatch_rank(chunk: RetrievedChunk, normalized_question: str) -> int:
    """Lower is better: title should match the named service in the question."""
    title = _normalize(
        " ".join(
            str(value or "")
            for value in (
                (chunk.metadata or {}).get("source_section"),
                (chunk.metadata or {}).get("canonical_topic"),
                (chunk.metadata or {}).get("title"),
                chunk.title,
            )
        )
    )
    if "enroll" in normalized_question or "enrol" in normalized_question:
        if "assessment of fee" in title or "ip registration" in title:
            return 3
        if re.search(r"\benrol(?:l)?ment\b", title) and "assessment" not in title and "ip registration" not in title:
            return 0
        if "registration" in title and "enrollment" not in title and "enrolment" not in title:
            return 3
        return 2
    if re.search(r"\b(?:tor|transcript)\b", normalized_question):
        if re.search(r"\b(?:transcript of records|issuance of transcript|\btor\b)\b", title):
            return 0
        if "annual report" in title or "certificate of completion" in title:
            return 3
        return 2
    if "diploma" in normalized_question:
        if "diploma" in title:
            return 0
        if "examination" in title or "open to all clients" in title:
            return 3
        return 2
    # Token overlap for other named services.
    stop = {
        "which",
        "what",
        "office",
        "is",
        "are",
        "the",
        "for",
        "of",
        "a",
        "an",
        "to",
        "in",
        "responsible",
        "process",
        "service",
        "who",
        "handles",
        "how",
        "do",
        "i",
        "can",
        "long",
        "much",
    }
    q_tokens = {token for token in re.findall(r"[a-z0-9]+", normalized_question) if token not in stop and len(token) >= 4}
    t_tokens = set(re.findall(r"[a-z0-9]+", title))
    if q_tokens & t_tokens:
        return 0
    return 1


def _chunk_office_present(chunk: RetrievedChunk) -> bool:
    office = str((chunk.metadata or {}).get("office") or (chunk.metadata or {}).get("responsible_office") or "").strip()
    return bool(office) and office.lower() not in {"none", "not specified", "[needs review]", "n/a"}


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
        _clean_value(metadata.get("total_fees"))
        or _clean_value(metadata.get("fees"))
        or _clean_value(metadata.get("fee"))
        or _extract_section_value(text, "Fees")
        or _extract_section_value(text, "Total Fees")
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
            # The office is whatever the charter names. When it names none, the
            # step is reported without one rather than attributed to a guess.
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
                    # Reported as the charter wrote it; no office is supplied
                    # when the document did not name one.
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
