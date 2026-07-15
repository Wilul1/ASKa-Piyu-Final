"""Knowledge-base document-type detection and typed chunk construction."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.services.chunking import DocumentChunk, chunk_document_text
from app.services.handbook_policy_processor import HandbookPolicyDocument
from app.services.structured_document_parser import (
    NEEDS_REVIEW,
    parse_structured_document,
)


class KnowledgeDocumentType(str, Enum):
    """Broad chunking / KB routing categories (information, procedure, requirement)."""

    INFORMATION = "information"
    PROCEDURE = "procedure"
    REQUIREMENT = "requirement"


class KnowledgeDocumentTypeName(str, Enum):
    """All document types accepted/returned by admin extract & ingest APIs.

    Keep this in sync with API schemas via ``DOCUMENT_TYPE_VALUES``.
    Specific names may map to a broad ``KnowledgeDocumentType`` via
    ``to_base_document_type``.
    """

    INFORMATION = "information"
    PROCEDURE = "procedure"
    REQUIREMENT = "requirement"
    CITIZEN_CHARTER = "citizen_charter"
    SERVICE_PROCESS = "service_process"
    HANDBOOK_POLICY = "handbook_policy"
    MANUAL_POLICY = "manual_policy"
    MEMO_ANNOUNCEMENT = "memo_announcement"
    FORM_TEMPLATE = "form_template"
    UNKNOWN = "unknown"


DOCUMENT_TYPE_VALUES: tuple[str, ...] = tuple(item.value for item in KnowledgeDocumentTypeName)
BASE_DOCUMENT_TYPE_VALUES: tuple[str, ...] = tuple(item.value for item in KnowledgeDocumentType)

_SPECIFIC_TO_BASE: dict[str, KnowledgeDocumentType] = {
    KnowledgeDocumentTypeName.INFORMATION.value: KnowledgeDocumentType.INFORMATION,
    KnowledgeDocumentTypeName.PROCEDURE.value: KnowledgeDocumentType.PROCEDURE,
    KnowledgeDocumentTypeName.REQUIREMENT.value: KnowledgeDocumentType.REQUIREMENT,
    KnowledgeDocumentTypeName.CITIZEN_CHARTER.value: KnowledgeDocumentType.PROCEDURE,
    KnowledgeDocumentTypeName.SERVICE_PROCESS.value: KnowledgeDocumentType.PROCEDURE,
    KnowledgeDocumentTypeName.HANDBOOK_POLICY.value: KnowledgeDocumentType.INFORMATION,
    KnowledgeDocumentTypeName.MANUAL_POLICY.value: KnowledgeDocumentType.INFORMATION,
    KnowledgeDocumentTypeName.MEMO_ANNOUNCEMENT.value: KnowledgeDocumentType.INFORMATION,
    KnowledgeDocumentTypeName.FORM_TEMPLATE.value: KnowledgeDocumentType.REQUIREMENT,
    KnowledgeDocumentTypeName.UNKNOWN.value: KnowledgeDocumentType.INFORMATION,
}


@dataclass(frozen=True)
class KnowledgeDocumentTypeDetection:
    document_type: KnowledgeDocumentType
    reason: str
    scores: dict[str, int] = field(default_factory=dict)
    manual_override: bool = False


def to_base_document_type(value: str | KnowledgeDocumentType | KnowledgeDocumentTypeName | None) -> str:
    """Map a specific API document type to the broad chunking category."""
    if value is None:
        return KnowledgeDocumentType.INFORMATION.value
    if isinstance(value, KnowledgeDocumentType):
        return value.value
    if isinstance(value, KnowledgeDocumentTypeName):
        return _SPECIFIC_TO_BASE[value.value].value
    key = str(value).strip().lower().replace("-", "_")
    mapped = _SPECIFIC_TO_BASE.get(key)
    if mapped is not None:
        return mapped.value
    try:
        normalized = normalize_knowledge_document_type(key)
    except ValueError:
        return KnowledgeDocumentType.INFORMATION.value
    if normalized is not None:
        return normalized.value
    return KnowledgeDocumentType.INFORMATION.value


def coerce_document_type_name(value: str | None) -> str:
    """Return a valid ``KnowledgeDocumentTypeName`` value (never raises)."""
    if value is None:
        return KnowledgeDocumentTypeName.UNKNOWN.value
    key = str(value).strip().lower().replace("-", "_")
    if key in {item.value for item in KnowledgeDocumentTypeName}:
        return key
    aliases = {
        "info": KnowledgeDocumentTypeName.INFORMATION.value,
        "handbook": KnowledgeDocumentTypeName.HANDBOOK_POLICY.value,
        "policy": KnowledgeDocumentTypeName.HANDBOOK_POLICY.value,
        "manual": KnowledgeDocumentTypeName.MANUAL_POLICY.value,
        "citizens_charter": KnowledgeDocumentTypeName.CITIZEN_CHARTER.value,
        "charter": KnowledgeDocumentTypeName.CITIZEN_CHARTER.value,
        "procedures": KnowledgeDocumentTypeName.PROCEDURE.value,
        "service": KnowledgeDocumentTypeName.SERVICE_PROCESS.value,
        "requirements": KnowledgeDocumentTypeName.REQUIREMENT.value,
        "form": KnowledgeDocumentTypeName.FORM_TEMPLATE.value,
        "forms": KnowledgeDocumentTypeName.FORM_TEMPLATE.value,
        "memo": KnowledgeDocumentTypeName.MEMO_ANNOUNCEMENT.value,
        "announcement": KnowledgeDocumentTypeName.MEMO_ANNOUNCEMENT.value,
    }
    return aliases.get(key, KnowledgeDocumentTypeName.UNKNOWN.value)


def normalize_knowledge_document_type(value: str | None) -> KnowledgeDocumentType | None:
    if value is None:
        return None
    normalized = value.strip().lower().replace("-", "_")
    if normalized in {"", "auto", "auto_detect", "autodetect"}:
        return None
    aliases = {
        "info": KnowledgeDocumentType.INFORMATION,
        "information": KnowledgeDocumentType.INFORMATION,
        "handbook": KnowledgeDocumentType.INFORMATION,
        "handbook_policy": KnowledgeDocumentType.INFORMATION,
        "manual_policy": KnowledgeDocumentType.INFORMATION,
        "manual": KnowledgeDocumentType.INFORMATION,
        "memo_announcement": KnowledgeDocumentType.INFORMATION,
        "memo": KnowledgeDocumentType.INFORMATION,
        "announcement": KnowledgeDocumentType.INFORMATION,
        "policy": KnowledgeDocumentType.INFORMATION,
        "procedure": KnowledgeDocumentType.PROCEDURE,
        "procedures": KnowledgeDocumentType.PROCEDURE,
        "service": KnowledgeDocumentType.PROCEDURE,
        "service_process": KnowledgeDocumentType.PROCEDURE,
        "citizen_charter": KnowledgeDocumentType.PROCEDURE,
        "citizens_charter": KnowledgeDocumentType.PROCEDURE,
        "charter": KnowledgeDocumentType.PROCEDURE,
        "requirement": KnowledgeDocumentType.REQUIREMENT,
        "requirements": KnowledgeDocumentType.REQUIREMENT,
        "form": KnowledgeDocumentType.REQUIREMENT,
        "forms": KnowledgeDocumentType.REQUIREMENT,
        "form_template": KnowledgeDocumentType.REQUIREMENT,
        "unknown": KnowledgeDocumentType.INFORMATION,
    }
    if normalized not in aliases:
        valid = ", ".join(DOCUMENT_TYPE_VALUES)
        raise ValueError(f"Invalid document_type. Use auto, {valid}.")
    return aliases[normalized]


def detect_knowledge_document_type(
    text: str,
    *,
    manual_document_type: str | None = None,
) -> KnowledgeDocumentTypeDetection:
    manual = normalize_knowledge_document_type(manual_document_type)
    if manual is not None:
        return KnowledgeDocumentTypeDetection(
            document_type=manual,
            reason="Manual admin selection.",
            scores={},
            manual_override=True,
        )

    cleaned = _normalize_text(text)
    scores = {
        KnowledgeDocumentType.INFORMATION.value: _score(
            cleaned,
            [
                r"\bchapter\s+[ivxlcdm\d]+\b",
                r"\barticle\s+[ivxlcdm\d]+\b",
                r"\bsection\s+[\divxlcdm]+\b",
                r"\bpolicy|policies|rules?|guidelines?\b",
                r"\bhandbook|manual\b",
            ],
        ),
        KnowledgeDocumentType.PROCEDURE.value: _score(
            cleaned,
            [
                r"\bclient\s+steps?\b",
                r"\bagency\s+actions?\b",
                r"\bprocessing\s+time\b",
                r"\bperson\s+responsible|responsible\s+personnel\b",
                r"\bfees?\s+to\s+be\s+paid\b",
                r"\bchecklist\s+of\s+requirements\b",
                r"\bwho\s+may\s+avail\b",
                r"\boffice\s*(?:or)?\s*division\b",
                r"\bclassification\s*:",
                r"\bwhere\s+to\s+secure\b",
            ],
        ),
        KnowledgeDocumentType.REQUIREMENT.value: _score(
            cleaned,
            [
                r"\b(?:application|request|clearance|assistance|access)\s+form\b",
                r"\bform\s*(?:no\.?|code|number)\b",
                r"\brequester|requestor|applicant\b",
                r"\bsignature\b",
                r"(?:\[[ x/]\]|\(\s*[x/ ]?\s*\)|checkbox|check\s+box)",
                r"\btype\s+of\s+(?:request|account|service)\b",
                r"_{3,}",
            ],
        ),
    }
    parsed = parse_structured_document(cleaned)
    parsed_kind = str(parsed.get("document_type") or "")
    if parsed_kind in {"form", "requirement"} and parsed.get("form"):
        scores[KnowledgeDocumentType.REQUIREMENT.value] += 4
    elif parsed_kind == "citizen_charter":
        scores[KnowledgeDocumentType.PROCEDURE.value] += 4
    elif parsed_kind == "handbook_policy":
        scores[KnowledgeDocumentType.INFORMATION.value] += 4

    selected = max(scores, key=scores.get)
    if scores[selected] <= 0:
        selected = KnowledgeDocumentType.INFORMATION.value
    return KnowledgeDocumentTypeDetection(
        document_type=KnowledgeDocumentType(selected),
        reason=_reason_for_scores(scores, selected),
        scores=scores,
    )


def build_typed_chunks(
    *,
    kb_document_type: KnowledgeDocumentType,
    extraction: Any,
    index_text: str,
    title: str,
    source_document: str,
    preview_file_path: str | None = None,
) -> list[DocumentChunk]:
    if kb_document_type == KnowledgeDocumentType.PROCEDURE:
        return _procedure_chunks(index_text, title=title, source_document=source_document)
    if kb_document_type == KnowledgeDocumentType.REQUIREMENT:
        return _requirement_chunks(
            index_text,
            title=title,
            source_document=source_document,
            preview_file_path=preview_file_path or source_document,
        )
    return _information_chunks(extraction, index_text, title=title, source_document=source_document)


def build_chunks_from_charter_v2_services(
    services: list[dict[str, Any]],
    *,
    title: str,
    source_document: str,
) -> list[DocumentChunk]:
    """Build one indexed service_procedure chunk per Citizen's Charter V2 service.

    Skips requirement/form artifacts and noise titles so chatbot retrieval is
    driven by real services (ID Validation, Good Moral, etc.).
    """
    from app.services.citizen_charter_services import (
        build_charter_article_body,
        charter_v2_service_to_fields,
        classify_charter_audience,
        classify_charter_candidate_bucket,
        is_charter_reference_section,
        is_noise_service_title,
        map_charter_category,
        score_charter_service_completeness,
        strip_service_part_suffix,
    )

    chunks: list[DocumentChunk] = []
    char_start = 0
    for service in services:
        if not isinstance(service, dict):
            continue
        service_title = strip_service_part_suffix(
            _clean_value(service.get("service_title") or service.get("service") or service.get("title")) or ""
        )
        if not service_title:
            continue
        if _is_requirement_form_artifact_title(service_title):
            continue
        if is_noise_service_title(service_title):
            continue
        if is_charter_reference_section(service_title, str(service)):
            continue

        fields = charter_v2_service_to_fields(service)
        enriched = {
            **fields,
            "document_title": _clean_value(service.get("document_title")) or title,
            "service": service_title,
        }
        content = build_charter_article_body(
            title=service_title,
            service=enriched,
            source_document=source_document,
        )
        audience = classify_charter_audience(
            office=_clean_value(enriched.get("office")),
            who_may_avail=_clean_value(enriched.get("who_may_avail")),
            title=service_title,
            text=content,
        )
        category = map_charter_category(
            office=_clean_value(enriched.get("office")),
            title=service_title,
            text=content,
        )
        completeness = score_charter_service_completeness(enriched, title=service_title)
        charter_bucket = classify_charter_candidate_bucket(
            title=service_title,
            service=enriched,
            audience=audience,
            text=content,
        )
        page = _page_int(
            service.get("page_start")
            or service.get("page_number")
            or service.get("page")
            or enriched.get("page")
        )
        metadata: dict[str, Any] = {
            "document_type": "citizen_charter",
            "article_type": "service_procedure",
            "title": service_title,
            "procedure_title": service_title,
            "canonical_topic": service_title,
            "source_section": service_title,
            "section_heading": service_title,
            "office": _clean_value(enriched.get("office")),
            "who_may_avail": _clean_value(enriched.get("who_may_avail")),
            "classification": _clean_value(enriched.get("classification")),
            "extracted_requirements": json.dumps(enriched.get("requirements") or []),
            "extracted_steps": json.dumps(enriched.get("steps") or []),
            "total_processing_time": _clean_value(enriched.get("total_processing_time")),
            "total_fees": _clean_value(enriched.get("total_fees")),
            "source_document": source_document,
            "source_type": "Citizen's Charter",
            "parser_document_type": "citizen_charter",
            "document_profile": "citizen_charter",
            "parser_used": "citizen_charter_extractor_v2",
            "formatter_used": "build_charter_article_body",
            "detected_document_type": "citizen_charter",
            "charter_audience": audience,
            "suggested_category": category,
            "charter_completeness": completeness,
            "charter_candidate_bucket": charter_bucket,
            "extraction_quality": _clean_value(service.get("extraction_quality")) or "clean",
        }
        if page is not None:
            metadata["page"] = page
            metadata["page_start"] = page
            metadata["page_number"] = page
        excerpt = " ".join(content.split())
        metadata["source_excerpt"] = excerpt[:700]
        chunks.append(
            DocumentChunk(
                text=content,
                chunk_index=len(chunks),
                char_start=char_start,
                metadata=metadata,
            )
        )
        char_start += len(content) + 2
    return chunks


def _is_requirement_form_artifact_title(title: str) -> bool:
    lowered = (title or "").strip().lower()
    if not lowered:
        return True
    if lowered.startswith("requirement:"):
        return True
    if "request form" in lowered and "clearance" in lowered:
        return True
    return False


def _page_int(value: Any) -> int | None:
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.strip().isdigit():
        page = int(value.strip())
        return page if page > 0 else None
    return None


def _information_chunks(extraction: Any, index_text: str, *, title: str, source_document: str) -> list[DocumentChunk]:
    structured = getattr(extraction, "structured", None)
    if isinstance(structured, HandbookPolicyDocument):
        chunks: list[DocumentChunk] = []
        char_start = 0
        for unit in structured.units:
            metadata = dict(unit.metadata)
            previous_type = metadata.get("document_type")
            if previous_type and previous_type != KnowledgeDocumentType.INFORMATION.value:
                metadata["source_document_type"] = previous_type
            metadata.update(
                {
                    "document_type": KnowledgeDocumentType.INFORMATION.value,
                    "title": unit.title or title,
                    "source_document": source_document,
                    "page_number": metadata.get("page_start"),
                    "section_heading": metadata.get("section") or metadata.get("article") or metadata.get("chapter"),
                }
            )
            text = unit.article_text
            chunks.append(DocumentChunk(text=text, chunk_index=len(chunks), char_start=char_start, metadata=metadata))
            char_start += len(text) + 2
        return chunks

    chunks = chunk_document_text(index_text)
    return [
        DocumentChunk(
            text=chunk.text,
            chunk_index=chunk.chunk_index,
            char_start=chunk.char_start,
            metadata={
                **(chunk.metadata or {}),
                "document_type": KnowledgeDocumentType.INFORMATION.value,
                "title": title,
                "source_document": source_document,
                "section_heading": _first_heading(chunk.text),
            },
        )
        for chunk in chunks
    ]


def _procedure_chunks(text: str, *, title: str, source_document: str) -> list[DocumentChunk]:
    from app.services.citizen_charter_services import (
        build_charter_article_body,
        classify_charter_audience,
        classify_charter_candidate_bucket,
        is_charter_reference_section,
        is_noise_service_title,
        map_charter_category,
        score_charter_service_completeness,
        strip_service_part_suffix,
    )

    parsed = parse_structured_document(text)
    services = parsed.get("services") or []
    is_charter = str(parsed.get("document_type") or "").strip().lower() == "citizen_charter"
    charter_dropped_noise = int(parsed.get("charter_dropped_noise") or 0)
    charter_merged_splits = int(parsed.get("charter_merged_splits") or 0)
    charter_detected_blocks = int(
        parsed.get("charter_detected_blocks")
        or (len(services) + charter_merged_splits + charter_dropped_noise)
    )
    chunks: list[DocumentChunk] = []
    char_start = 0
    for service in services:
        service_title = strip_service_part_suffix(_clean_value(service.get("service")) or "")
        if not service_title:
            service_title = title
        if is_noise_service_title(service_title):
            continue
        if is_charter_reference_section(service_title, str(service)):
            continue

        requirements = []
        for item in service.get("requirements") or []:
            if isinstance(item, dict):
                requirement = _clean_value(item.get("requirement"))
                if not requirement:
                    continue
                requirements.append(
                    {
                        "requirement": requirement,
                        "where_to_secure": _clean_value(item.get("where_to_secure")) or "Not specified",
                    }
                )
            else:
                requirement = _clean_value(item)
                if requirement:
                    requirements.append(
                        {"requirement": requirement, "where_to_secure": "Not specified"}
                    )

        steps = [
            {
                "client_step": _clean_value(step.get("client_step")),
                "agency_action": _clean_value(step.get("agency_action")),
                "fees": _clean_value(step.get("fees")),
                "processing_time": _clean_value(step.get("processing_time")),
                "person_responsible": _clean_value(step.get("responsible_personnel")),
            }
            for step in service.get("steps") or []
        ]
        steps = [step for step in steps if any(step.values())]

        enriched = {
            **service,
            "requirements": requirements,
            "steps": steps,
        }
        if is_charter:
            content = build_charter_article_body(
                title=service_title,
                service=enriched,
                source_document=source_document,
            )
        else:
            content = _procedure_text(
                service_title,
                service,
                [item["requirement"] for item in requirements],
                steps,
                source_document,
            )

        audience = classify_charter_audience(
            office=_clean_value(service.get("office")),
            who_may_avail=_clean_value(service.get("who_may_avail")),
            title=service_title,
            text=content,
        )
        category = map_charter_category(
            office=_clean_value(service.get("office")),
            title=service_title,
            text=content,
        )
        completeness = score_charter_service_completeness(enriched, title=service_title)
        charter_bucket = (
            classify_charter_candidate_bucket(
                title=service_title,
                service=enriched,
                audience=audience,
                text=content,
            )
            if is_charter
            else None
        )
        page = _page_int(
            service.get("page")
            or service.get("page_number")
            or service.get("page_start")
        )
        metadata = {
            "document_type": "citizen_charter" if is_charter else KnowledgeDocumentType.PROCEDURE.value,
            "article_type": "service_procedure" if is_charter else "procedure",
            "title": service_title,
            "procedure_title": service_title,
            "canonical_topic": service_title,
            "source_section": service_title,
            "office": _clean_value(service.get("office")),
            "who_may_avail": _clean_value(service.get("who_may_avail")),
            "classification": _clean_value(service.get("classification")),
            "extracted_requirements": json.dumps(requirements),
            "extracted_steps": json.dumps(steps),
            "total_processing_time": _clean_value(service.get("total_processing_time")),
            "total_fees": _clean_value(service.get("total_fees")),
            "parser_debug": service.get("parser_debug") if isinstance(service.get("parser_debug"), dict) else None,
            "source_document": source_document,
            "section_heading": service_title,
            "source_type": "Citizen's Charter" if is_charter else "Procedure",
            "parser_document_type": "citizen_charter" if is_charter else "procedure",
            "document_profile": "citizen_charter" if is_charter else "procedure",
            "parser_used": "citizen_charter_service_parser" if is_charter else "procedure_parser",
            "formatter_used": "build_charter_article_body" if is_charter else "procedure_formatter",
            "detected_document_type": "citizen_charter" if is_charter else "procedure",
            "charter_audience": audience if is_charter else None,
            "suggested_category": category if is_charter else None,
            "charter_completeness": completeness if is_charter else None,
            "charter_candidate_bucket": charter_bucket,
            "charter_parts_merged": int(service.get("charter_parts_merged") or 1) if is_charter else None,
            "charter_dropped_noise": charter_dropped_noise if is_charter else None,
            "charter_merged_splits": charter_merged_splits if is_charter else None,
            "charter_detected_blocks": charter_detected_blocks if is_charter else None,
        }
        if page is not None:
            metadata["page"] = page
            metadata["page_start"] = page
            metadata["page_number"] = page
        if _is_requirement_form_artifact_title(service_title):
            continue
        chunks.append(
            DocumentChunk(
                text=content,
                chunk_index=len(chunks),
                char_start=char_start,
                metadata=metadata,
            )
        )
        char_start += len(content) + 2
    return chunks or _information_chunks(
        type("Extraction", (), {"structured": None})(),
        text,
        title=title,
        source_document=source_document,
    )


def _procedure_text(
    title: str,
    service: dict[str, Any],
    requirements: list[str],
    steps: list[dict[str, str]],
    source: str,
) -> str:
    lines = [
        f"Procedure Title: {title}",
        f"Office: {_clean_value(service.get('office')) or 'Not specified'}",
        f"Who May Avail: {_clean_value(service.get('who_may_avail')) or 'Not specified'}",
        "Requirements:",
    ]
    if requirements:
        lines.extend(f"- {item}" for item in requirements)
    else:
        lines.append("- Not specified")
    lines.append("Steps:")
    for index, step in enumerate(steps, start=1):
        lines.append(f"{index}. Client Step: {step.get('client_step') or 'Not specified'}")
        if step.get("agency_action"):
            lines.append(f"   Agency Action: {step['agency_action']}")
        if step.get("fees"):
            lines.append(f"   Fees: {step['fees']}")
        if step.get("processing_time"):
            lines.append(f"   Processing Time: {step['processing_time']}")
        if step.get("person_responsible"):
            lines.append(f"   Person Responsible: {step['person_responsible']}")
    lines.extend(
        [
            f"Total Processing Time: {_clean_value(service.get('total_processing_time')) or 'Not specified'}",
            f"Source: {source}",
        ]
    )
    return "\n".join(lines)


def _requirement_chunks(text: str, *, title: str, source_document: str, preview_file_path: str) -> list[DocumentChunk]:
    data = _requirement_data_from_text(text, fallback_title=title)
    form_title = data["form_title"]
    fields = data["fields"]
    options = data["options"]
    related_services = data["related_services"] or _related_services(options)
    summary = data["summary"] or _summary_for_requirement(form_title, data, fields, options)
    how_to_fill_out = data["how_to_fill_out"] or _how_to_fill_out(fields, _flatten_options(options))
    content = _requirement_text(
        title=form_title,
        display_document_type=data["display_document_type"],
        office=data["office"],
        summary=summary,
        fields=fields,
        options=options,
        related_services=related_services,
        how_to_fill_out=how_to_fill_out,
        form_code=data["form_code"],
        revision=data["revision"],
        date=data["date"],
        source_document=source_document,
        preview_file_path=preview_file_path,
    )
    metadata = {
        "document_type": KnowledgeDocumentType.REQUIREMENT.value,
        "title": form_title,
        "form_title": form_title,
        "display_document_type": data["display_document_type"],
        "office": data["office"],
        "office_detection_source": data["office_detection_source"],
        "form_code": data["form_code"],
        "revision": data["revision"],
        "date": data["date"],
        "summary": summary,
        "keywords": json.dumps(_keywords([form_title, *fields, *related_services])),
        "related_services": json.dumps(related_services),
        "preview_file_path": preview_file_path,
        "extracted_requirements": json.dumps(fields),
        "form_options": json.dumps(options),
        "how_to_fill_out": json.dumps(how_to_fill_out),
        "source_document": source_document,
        "raw_extraction_available": data["raw_extraction_available"],
        "section_heading": form_title,
    }
    return [DocumentChunk(text=content, chunk_index=0, char_start=0, metadata=metadata)]


def _requirement_text(
    *,
    title: str,
    display_document_type: str,
    office: str,
    summary: str,
    fields: list[str],
    options: dict[str, list[str]],
    related_services: list[str],
    how_to_fill_out: list[str],
    form_code: str,
    revision: str,
    date: str,
    source_document: str,
    preview_file_path: str,
) -> str:
    lines = [
        f"Document Type: {display_document_type or 'Requirement / Form Document'}",
        f"Requirement Title: {title}",
        f"Office: {office or 'Not specified'}",
        f"Form Code: {form_code or 'Not specified'}",
        f"Revision: {revision or 'Not specified'}",
        f"Date: {date or 'Not specified'}",
        f"Summary: {summary}",
        "Requirements:",
    ]
    if fields:
        lines.extend(f"- {field}" for field in fields)
    else:
        lines.append("- Not specified")
    lines.append("Options / Services:")
    option_values = _flatten_options(options)
    if option_values:
        lines.extend(f"- {item}" for item in option_values)
    else:
        lines.append("- None found in the uploaded document.")
    lines.append("How to Fill Out:")
    for instruction in how_to_fill_out:
        lines.append(f"- {instruction}")
    lines.append(f"Form Preview: {preview_file_path}")
    lines.append("Related Services:")
    if related_services:
        lines.extend(f"- {item}" for item in related_services)
    else:
        lines.append("- None found in the uploaded document.")
    lines.append(f"Source: {source_document}")
    return "\n".join(lines)


def _score(text: str, patterns: list[str]) -> int:
    return sum(1 for pattern in patterns if re.search(pattern, text, flags=re.I))


def _requirement_data_from_text(text: str, *, fallback_title: str) -> dict[str, Any]:
    if _looks_like_formatted_requirement_preview(text):
        return _requirement_data_from_formatted_preview(text, fallback_title=fallback_title)
    return _requirement_data_from_raw_text(text, fallback_title=fallback_title)


def _looks_like_formatted_requirement_preview(text: str) -> bool:
    head = _strip_raw_extraction(text)[:800]
    return bool(
        re.search(r"(?m)^Document Type:\s*$", head)
        and re.search(r"\bRequirement\s*/\s*Form\s+Document\b", head, flags=re.I)
    )


def _strip_raw_extraction(text: str) -> str:
    return re.split(r"(?im)^\s*Raw Extraction:\s*$", text or "", maxsplit=1)[0].strip()


def _requirement_data_from_formatted_preview(text: str, *, fallback_title: str) -> dict[str, Any]:
    safe_text = _strip_raw_extraction(text)
    sections = _formatted_sections(safe_text)
    basic = _basic_info_from_lines(sections.get("Basic Information", []))
    fields = _clean_list(sections.get("Generated Requirements") or sections.get("Fields / Required Information") or [])
    options = {"options_or_services": _clean_list(sections.get("Options / Services") or [])}
    options = {key: values for key, values in options.items() if values}
    related_services = _clean_list(sections.get("Related Services") or []) or _flatten_options(options)
    how_to_fill_out = _clean_list(sections.get("How to Fill Out") or [])
    return {
        "display_document_type": "Requirement / Form Document",
        "form_title": _clean_value(basic.get("Form Title")) or fallback_title,
        "office": _clean_value(basic.get("Office")),
        "office_detection_source": _clean_value(basic.get("Office Detection Source")),
        "form_code": _clean_value(basic.get("Form Code")),
        "revision": _clean_value(basic.get("Revision")),
        "date": _clean_value(basic.get("Date")),
        "summary": "",
        "fields": fields,
        "options": options,
        "related_services": related_services,
        "how_to_fill_out": how_to_fill_out,
        "raw_extraction_available": bool(re.search(r"(?im)^\s*Raw Extraction:\s*$", text or "")),
    }


def _requirement_data_from_raw_text(text: str, *, fallback_title: str) -> dict[str, Any]:
    parsed = parse_structured_document(text)
    form = parsed.get("form") or {}
    form_title = _clean_value(form.get("form_title")) or _clean_value(form.get("form_name")) or fallback_title
    fields = [_clean_value(item) for item in form.get("requirements") or form.get("fields") or [] if _clean_value(item)]
    options = {
        str(key): [_clean_value(value) for value in values if _clean_value(value)]
        for key, values in (form.get("options") or {}).items()
    }
    options = {key: values for key, values in options.items() if values}
    return {
        "display_document_type": _clean_value(form.get("display_document_type")) or "Requirement / Form Document",
        "form_title": form_title,
        "office": _clean_value(form.get("office")),
        "office_detection_source": _clean_value(form.get("office_detection_source")),
        "form_code": _clean_value(form.get("form_code")),
        "revision": _clean_value(form.get("revision")),
        "date": _clean_value(form.get("date")),
        "summary": "",
        "fields": fields,
        "options": options,
        "related_services": [_clean_value(item) for item in form.get("related_services") or [] if _clean_value(item)],
        "how_to_fill_out": [_clean_value(item) for item in form.get("how_to_fill_out") or [] if _clean_value(item)],
        "raw_extraction_available": bool(_clean_value(form.get("raw_extracted_text"))),
    }


def _formatted_sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current = ""
    for raw_line in (text or "").splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            continue
        heading = stripped[:-1] if stripped.endswith(":") else ""
        if heading in {
            "Document Type",
            "Basic Information",
            "Sections",
            "Fields / Required Information",
            "Options / Services",
            "Generated Requirements",
            "How to Fill Out",
            "Related Services",
        }:
            current = heading
            sections.setdefault(current, [])
            continue
        if current:
            sections[current].append(stripped)
    return sections


def _basic_info_from_lines(lines: list[str]) -> dict[str, str]:
    info: dict[str, str] = {}
    for line in lines:
        value = re.sub(r"^\s*-\s*", "", line).strip()
        if ":" not in value:
            continue
        key, item = value.split(":", 1)
        info[key.strip()] = item.strip()
    return info


def _clean_list(lines: list[str]) -> list[str]:
    values = []
    for line in lines:
        value = re.sub(r"^\s*-\s*", "", line).strip()
        if value and not re.match(r"none found\b|not specified\b", value, flags=re.I):
            values.append(value)
    return _unique(values)


def _reason_for_scores(scores: dict[str, int], selected: str) -> str:
    labels = {
        KnowledgeDocumentType.INFORMATION.value: "policy, chapter, section, guideline, or handbook signals",
        KnowledgeDocumentType.PROCEDURE.value: "client step, agency action, processing time, fee, or responsible-person signals",
        KnowledgeDocumentType.REQUIREMENT.value: "form title, field, checkbox, signature, requester, or request-option signals",
    }
    return f"Detected {selected} from {labels[selected]}."


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _clean_value(value: Any) -> str:
    text = str(value or "").strip()
    return "" if not text or text == NEEDS_REVIEW else text


def _first_heading(text: str) -> str:
    for line in (text or "").splitlines():
        line = line.strip()
        if line:
            return line[:120]
    return ""


def _related_services(options: dict[str, list[str]]) -> list[str]:
    values: list[str] = []
    for option_values in options.values():
        values.extend(option_values)
    return _unique(values)


def _flatten_options(options: dict[str, list[str]]) -> list[str]:
    values: list[str] = []
    for option_values in options.values():
        values.extend(option_values)
    return _unique(values)


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


def _summary_for_requirement(title: str, form: dict[str, Any], fields: list[str], options: dict[str, list[str]]) -> str:
    office = _clean_value(form.get("office"))
    subject = title or "This form"
    if office:
        return f"Use {subject} for requests handled by {office}."
    if fields or options:
        return f"Use {subject} to submit the listed request details and required information."
    return f"Use {subject} for the documented requirement."


def _keywords(values: list[str]) -> list[str]:
    tokens: list[str] = []
    for value in values:
        tokens.extend(token.lower() for token in re.findall(r"[A-Za-z0-9]{3,}", value))
    return _unique(tokens)


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        normalized = value.strip()
        key = normalized.lower()
        if normalized and key not in seen:
            seen.add(key)
            output.append(normalized)
    return output
