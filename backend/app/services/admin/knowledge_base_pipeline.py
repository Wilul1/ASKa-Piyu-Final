"""
Admin knowledge-base creation flow.

Upload → extract (OCR/PDF) → clean → chunk → embed → ChromaDB

Runs at deployment, policy updates, and admin maintenance — not during student Q&A.
"""

from __future__ import annotations

import logging
import uuid
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any
import re

from app.services.chunking import DocumentChunk, chunk_document_text
from app.services.chroma_store import get_knowledge_base_store
from app.models.schemas import DocumentFieldSchema, StructuredDocumentSchema
from app.services.document_ingestion import ingest_document
from app.services.document_structurer import prepare_review_document
from app.services.dynamic_document_analyzer import analyze_document_structure
from app.services.handbook_policy_processor import (
    HandbookPolicyDocument,
    KNOWN_CAMPUS_NAMES,
    handbook_ocr_split_audit,
)
from app.services.knowledge_taxonomy import enrich_chunks_with_category_metadata
from app.services.knowledge_document_types import (
    KnowledgeDocumentType,
    build_chunks_from_charter_v2_services,
    build_typed_chunks,
    detect_knowledge_document_type,
)
from app.services.structured_document_parser import build_structured_document, format_structured_document


NEEDS_REVIEW = "[NEEDS REVIEW]"
RETRIEVAL_TEST_PREVIEW_CHARS = 700

logger = logging.getLogger(__name__)


def _pipeline_stages(
    *,
    extraction_method: str,
    structuring_method: str,
    indexed: bool,
    chunks_indexed: int = 0,
) -> list[dict]:
    review_status = "completed" if indexed else "needs_review"
    index_status = "completed" if indexed else "waiting"
    return [
        {
            "key": "extract",
            "label": "OCR/PDF extraction",
            "status": "completed",
            "detail": extraction_method,
        },
        {
            "key": "clean",
            "label": "Automatic cleaning",
            "status": "completed",
            "detail": "Obvious OCR errors normalized",
        },
        {
            "key": "structure",
            "label": "LLM structuring",
            "status": "completed",
            "detail": structuring_method,
        },
        {
            "key": "review",
            "label": "Admin review/edit",
            "status": review_status,
            "detail": "Editable preview is ready" if not indexed else "Reviewed text accepted",
        },
        {
            "key": "index",
            "label": "Index to ChromaDB",
            "status": index_status,
            "detail": f"{chunks_indexed} chunks indexed" if indexed else "Waiting for admin approval",
        },
    ]


@dataclass
class KnowledgeBaseIngestResult:
    document_id: str
    document_type: str
    source_filename: str
    title: str
    chunks_indexed: int
    page_count: int
    extraction_method: str
    extracted_text_preview: str
    structured: StructuredDocumentSchema
    structuring_method: str
    pipeline_stages: list[dict]
    diagnostic_report: dict | None = None
    validation_report: dict | None = None
    detected_document_type: dict | None = None
    knowledge_units: list[dict] | None = None
    chunk_preview: list[dict] | None = None
    kb_statistics: dict | None = None


def _structured_response(result) -> StructuredDocumentSchema:
    structured = result.structured
    if structured is None:
        return StructuredDocumentSchema(fields=[], formatted_text=result.extracted_text)
    if isinstance(structured, HandbookPolicyDocument):
        return StructuredDocumentSchema(fields=[], formatted_text=structured.formatted_articles)
    if isinstance(structured, dict):
        return StructuredDocumentSchema(fields=[], formatted_text=format_structured_document(structured))
    return StructuredDocumentSchema(
        fields=[DocumentFieldSchema(**f.to_dict()) for f in structured.fields],
        formatted_text=structured.formatted_text,
    )


def _structured_text_response(text: str, *, source_document: str = "", preview_file_path: str | None = None) -> StructuredDocumentSchema:
    structured = build_structured_document(
        text,
        source_document=source_document,
        preview_file_path=preview_file_path or "",
    )
    if isinstance(structured, dict):
        return StructuredDocumentSchema(fields=[], formatted_text=format_structured_document(structured) or text)
    return StructuredDocumentSchema(
        fields=[DocumentFieldSchema(**f.to_dict()) for f in structured.fields],
        formatted_text=structured.formatted_text or text,
    )


def _only_needs_review(text: str) -> bool:
    meaningful_lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and line.strip() != "---"
    ]
    if not meaningful_lines:
        return False

    values = [
        line.split(":", 1)[1].strip() if ":" in line else line
        for line in meaningful_lines
    ]
    return all(not value or value == NEEDS_REVIEW for value in values)


def _normalize_source_key(value: str | None) -> str:
    """Normalize filenames/titles so Charter matching survives unicode dashes."""
    text = (value or "").casefold().strip()
    text = re.sub(r"[\u2010-\u2015\u2212\uFE58\uFE63\uFF0D]+", "-", text)
    text = re.sub(r"\s+", " ", text)
    return text


def _is_citizens_charter_source(
    *,
    filename: str | None = None,
    title: str | None = None,
    text: str | None = None,
    document_type: str | None = None,
    detection_type: KnowledgeDocumentType | None = None,
) -> bool:
    """Detect Citizen's Charter sources even when OCR/review text looks like a form."""
    manual = _normalize_source_key(document_type).replace(" ", "_")
    if manual in {
        "citizen_charter",
        "citizens_charter",
        "charter",
        "procedure",
        "service_process",
        "service",
    }:
        return True
    if detection_type == KnowledgeDocumentType.PROCEDURE:
        return True

    name = _normalize_source_key(f"{filename or ''} {title or ''}")
    if re.search(r"\bcitizen(?:'s|s)?\s+charter\b", name) or "charter" in name:
        return True
    # Catch common LSPU naming: University-CC_2026, LSPU_CC_..., etc.
    if re.search(r"(?:^|[^a-z0-9])cc[_-]", name) or re.search(r"[_-]cc[_-]", name):
        return True

    sample = _normalize_source_key((text or "")[:4000])
    if re.search(r"\bcitizen(?:'s|s)?\s+charter\b", sample):
        return True
    if "office / division" in sample and "who may avail" in sample and "client step" in sample:
        return True
    return False


def _charter_index_text(
    *,
    reviewed_text: str | None,
    extraction,
    structured_v2_text: str = "",
) -> str:
    """Prefer full extraction / V2 text over truncated or form-like reviewed_text."""
    structured = (structured_v2_text or "").strip()
    if structured and structured.count("\n") >= 8:
        return structured

    cleaned = (getattr(extraction, "cleaned_text", None) or "").strip()
    extracted = (getattr(extraction, "extracted_text", None) or "").strip()
    full = cleaned or extracted
    reviewed = (reviewed_text or "").strip()

    if not reviewed:
        return full
    # Reject short/truncated review buffers that collapse indexing to one form card.
    if len(reviewed) < 800 and full and len(full) > len(reviewed) * 1.5:
        return full
    if reviewed.casefold().startswith("requirement:") and full:
        return full
    if "form preview" in reviewed.casefold() and full and "office / division" in full.casefold():
        return full
    # Reviewed V2/extraction text is usable when it already looks multi-service.
    if reviewed.count("Service:") >= 2 or reviewed.count("Office / Division") >= 2:
        return reviewed
    return full or reviewed


def _best_review_text(*, reviewed_text: str | None, review_text: str, cleaned_text: str, extracted_text: str) -> str:
    reviewed = (reviewed_text or "").strip()
    if reviewed:
        return reviewed
    if _only_needs_review(review_text):
        return cleaned_text or extracted_text
    return review_text


def _response_document_type(extraction) -> str:
    return getattr(extraction, "knowledge_document_type", None) or extraction.document_type.value


def _detect_kb_document_type(extraction, text: str, manual_document_type: str | None):
    # Priority: admin override → structural detection → handbook fallback.
    if manual_document_type is not None:
        return detect_knowledge_document_type(text, manual_document_type=manual_document_type)

    detection = detect_knowledge_document_type(text, manual_document_type=None)
    structured = getattr(extraction, "structured", None)
    if isinstance(structured, HandbookPolicyDocument):
        from app.services.structured_document_parser import classify_document_type

        parsed_kind = classify_document_type(text)
        # Citizen's Charter / strong procedure signals must not be forced to handbook_policy.
        if parsed_kind == "citizen_charter" or detection.document_type == KnowledgeDocumentType.PROCEDURE:
            if detection.document_type != KnowledgeDocumentType.PROCEDURE:
                return detect_knowledge_document_type(
                    text,
                    manual_document_type=KnowledgeDocumentType.PROCEDURE.value,
                )
            return detection
        return detect_knowledge_document_type(
            text,
            manual_document_type=KnowledgeDocumentType.INFORMATION.value,
        )
    return detection


def _compat_response_document_type(extraction, kb_document_type: KnowledgeDocumentType) -> str:
    if kb_document_type == KnowledgeDocumentType.INFORMATION:
        return _response_document_type(extraction)
    return kb_document_type.value


def _chunks_for_extraction(
    extraction,
    index_text: str,
    *,
    kb_document_type: KnowledgeDocumentType = KnowledgeDocumentType.INFORMATION,
    title: str = "Untitled document",
    source_document: str = "unknown",
    preview_file_path: str | None = None,
) -> list[DocumentChunk]:
    if kb_document_type != KnowledgeDocumentType.INFORMATION:
        return build_typed_chunks(
            kb_document_type=kb_document_type,
            extraction=extraction,
            index_text=index_text,
            title=title,
            source_document=source_document,
            preview_file_path=preview_file_path,
        )
    structured = getattr(extraction, "structured", None)
    if isinstance(structured, HandbookPolicyDocument):
        return build_typed_chunks(
            kb_document_type=KnowledgeDocumentType.INFORMATION,
            extraction=extraction,
            index_text=index_text,
            title=title,
            source_document=source_document,
            preview_file_path=preview_file_path,
        )
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
            },
        )
        for chunk in chunks
    ]


def _word_count(text: str) -> int:
    return len(re.findall(r"\b\S+\b", text or ""))


def _hierarchy_path(metadata: dict | None) -> str:
    metadata = metadata or {}
    parts = [
        str(metadata.get(key))
        for key in ("chapter", "article", "section", "appendix")
        if metadata.get(key)
    ]
    return " > ".join(parts)


def _title_from_chunk(chunk: DocumentChunk) -> str:
    metadata = chunk.metadata or {}
    metadata_title = _title_from_metadata(metadata)
    if metadata_title:
        return metadata_title
    first_line = next((line.strip() for line in chunk.text.splitlines() if line.strip()), "")
    return first_line[:120] or "Untitled chunk"


def _title_from_metadata(metadata: dict | None) -> str:
    metadata = metadata or {}
    for key in ("section", "article", "chapter"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.split(">", 1)[-1].strip()
    return ""


def _looks_toc_like(text: str) -> bool:
    stripped = (text or "").strip()
    return bool(
        re.search(r"(?:\.{3,}|…)\s*\d+\s*$", stripped)
        or re.fullmatch(r"[A-Z][A-Za-z0-9 ,&'()/.-]{2,90}\s+\d{1,4}", stripped)
    )


def _looks_toc_like(text: str) -> bool:
    stripped = (text or "").strip()
    if re.search(r"(?:\.{2,}|…|â€¦|Ã¢â‚¬Â¦)\s*\|?\s*\d+\s*$", stripped):
        return True
    if re.match(r"^(?:article|chapter|appendix|sec(?:tion)?\.?)\s+[A-Z0-9IVXLCDM]+[:\-.]?\s+.+$", stripped, flags=re.I) and re.search(r"(?:\.{2,}|…|â€¦|Ã¢â‚¬Â¦)\s*\|?\s*\d+\s*$", stripped):
        return True
    return _looks_like_title_page_reference(stripped)


def _looks_like_title_page_reference(text: str) -> bool:
    match = re.fullmatch(r"([A-Z][A-Za-z0-9 ,&'()/.-]{2,90})\s+(\d{1,4})", text)
    if not match:
        return False
    title = match.group(1).strip()
    if re.search(r"[.!?:;|]$", title):
        return False
    if re.search(r"\b(page|year|no\.?|percent|grade|gwa|minutes?|hours?|process|wherein|acceptable|time)\b", title, flags=re.I):
        return False
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", title)
    if not (1 <= len(words) <= 8):
        return False
    title_like = sum(1 for word in words if word[:1].isupper() or word.isupper())
    return title_like / len(words) >= 0.6


def _has_standalone_page_number_path_segment(path: str) -> bool:
    return any(re.fullmatch(r"\d{1,4}", part.strip()) for part in (path or "").split(">"))


def _is_page_number_only(text: str) -> bool:
    return bool(re.fullmatch(r"(?:p(?:age)?\.?\s*)?\d{1,4}", (text or "").strip(), flags=re.I))


def _is_valid_short_program_listing(unit: dict, text: str) -> bool:
    content_type = str(unit.get("content_type") or "").strip()
    metadata = unit.get("metadata") if isinstance(unit.get("metadata"), dict) else {}
    if content_type != "program_listing" and metadata.get("content_type") != "program_listing":
        return False
    return bool(re.search(r"(?m)^Programs:\s*$", text) and re.search(r"(?m)^-\s+\S+", text))


def _is_valid_short_appendix_metadata_page(unit: dict, text: str, metadata: dict) -> bool:
    content_type = str(unit.get("content_type") or metadata.get("content_type") or "").strip()
    hierarchy = _hierarchy_path(metadata)
    title = str(unit.get("title") or "").strip()
    if content_type not in {"appendix", "form_template"}:
        return False
    if not (metadata.get("appendix") or title.lower().startswith("appendix") or "appendix" in hierarchy.lower()):
        return False
    if not text.strip():
        return False
    if _looks_toc_like(title) or _looks_toc_like(text) or _is_page_number_only(text):
        return False
    return True


def _is_valid_short_disciplinary_rule(unit: dict, text: str, metadata: dict) -> bool:
    content_type = str(unit.get("content_type") or metadata.get("content_type") or "").strip()
    if content_type != "disciplinary_rule":
        return False
    combined = f"{unit.get('title') or ''}\n{text}".strip()
    if not text.strip():
        return False
    if _looks_toc_like(combined) or _is_page_number_only(text):
        return False
    return bool(
        re.search(r"\b(offense|violation|sanction|penalt(?:y|ies)|warning|suspension|dismissal)\b", combined, flags=re.I)
        or re.search(r"(?m)^-\s+\S+", text)
    )


def _is_valid_short_definition_unit(unit: dict, text: str, metadata: dict) -> bool:
    content_type = str(unit.get("content_type") or metadata.get("content_type") or "").strip()
    if content_type != "policy":
        return False
    title = str(unit.get("title") or "").strip()
    if not title or not text.strip():
        return False
    if _looks_toc_like(title) or _looks_toc_like(text) or _is_page_number_only(text):
        return False
    if _word_count(text) > 60:
        return False
    if not re.match(r"^[A-Z][A-Za-z ,'/()-]{2,}$", title):
        return False
    return bool(
        re.search(r"\b(?:a|an|the)\s+\w+.{0,80}\b(?:who|which|that)\b", text, flags=re.I)
        or re.search(r"\b(?:means|refers to|is|are)\b", text, flags=re.I)
    )


def _is_valid_long_procedure(unit: dict, text: str, metadata: dict) -> bool:
    content_type = str(unit.get("content_type") or metadata.get("content_type") or "").strip()
    title = str(unit.get("title") or "").strip()
    if content_type != "procedure":
        return False
    if not title or not text.strip():
        return False
    if _looks_toc_like(title) or _looks_toc_like(text) or _is_page_number_only(text):
        return False
    return bool(re.search(r"\b(process|procedure|steps?|shall|must|submit|receive|refer|document|counsel)\b", text, flags=re.I))


def _unit_status(unit: dict) -> tuple[str, list[str]]:
    reasons: list[str] = []
    title = str(unit.get("title") or "").strip()
    text = str(unit.get("content") or unit.get("text") or "")
    metadata = unit.get("metadata") if isinstance(unit.get("metadata"), dict) else {}
    words = int(unit.get("word_count") or _word_count(text))
    valid_short_unit = (
        _is_valid_short_program_listing(unit, text)
        or _is_valid_short_appendix_metadata_page(unit, text, metadata)
        or _is_valid_short_disciplinary_rule(unit, text, metadata)
        or _is_valid_short_definition_unit(unit, text, metadata)
    )
    if not title:
        reasons.append("missing_title")
    if words < 20 and not valid_short_unit:
        reasons.append("very_short")
    if words > 1200 and not _is_valid_long_procedure(unit, text, metadata):
        reasons.append("very_long")
    if _is_page_number_only(text):
        reasons.append("page_number_only")
    hierarchy = _hierarchy_path(metadata)
    if _looks_toc_like(title) or _looks_toc_like(text) or _has_standalone_page_number_path_segment(hierarchy):
        reasons.append("toc_like")
    if title.endswith(",") and words < 35 and not re.search(r"\b(shall|must|required|procedure|requirements?|submit|comply)\b", text, flags=re.I):
        reasons.append("toc_like")
    if not metadata.get("source_title"):
        reasons.append("missing_source_metadata")
    if not hierarchy:
        reasons.append("missing_hierarchy_metadata")
    return ("Suspicious" if reasons else "OK", reasons)


def suspicious_unit_diagnostics(*, page_texts: list[str], units: list[dict]) -> list[dict]:
    diagnostics: list[dict] = []
    for unit in units:
        status = unit.get("status")
        reasons = list(unit.get("suspicious_reasons") or [])
        if status != "Suspicious" and not reasons:
            continue
        metadata = unit.get("metadata") if isinstance(unit.get("metadata"), dict) else {}
        page_start = metadata.get("page_start") or unit.get("page_start")
        page_index = int(page_start) - 1 if isinstance(page_start, int) and page_start > 0 else None
        original_snippet = ""
        if page_index is not None and page_index < len(page_texts):
            original_snippet = _page_snippet_for_unit(page_texts[page_index], str(unit.get("title") or ""))
        diagnostics.append(
            {
                "original_page_text_snippet": original_snippet,
                "extracted_unit_title": unit.get("title"),
                "extracted_content": unit.get("content"),
                "suspicious_reasons": reasons,
                "proposed_classification": _proposed_unit_classification(unit),
            }
        )
    return diagnostics


def _page_snippet_for_unit(page_text: str, title: str, *, radius: int = 320) -> str:
    normalized_title = re.sub(r"\s+", " ", title or "").strip()
    haystack = page_text or ""
    if normalized_title:
        pattern = re.escape(normalized_title).replace(r"\ ", r"\s+")
        match = re.search(pattern, haystack, flags=re.I)
        if match:
            start = max(0, match.start() - radius)
            end = min(len(haystack), match.end() + radius)
            return haystack[start:end].strip()
    return haystack[: radius * 2].strip()


def _proposed_unit_classification(unit: dict) -> str:
    text = str(unit.get("content") or unit.get("text") or "")
    metadata = unit.get("metadata") if isinstance(unit.get("metadata"), dict) else {}
    if _is_valid_short_program_listing(unit, text):
        return "valid"
    if _is_valid_short_appendix_metadata_page(unit, text, metadata):
        return "valid"
    if _is_valid_short_disciplinary_rule(unit, text, metadata):
        return "valid"
    if _is_valid_short_definition_unit(unit, text, metadata):
        return "valid"
    if _is_valid_long_procedure(unit, text, metadata):
        return "valid"
    if "toc_like" in (unit.get("suspicious_reasons") or []) or _looks_toc_like(str(unit.get("title") or "")):
        return "extraction issue"
    if "very_short" in (unit.get("suspicious_reasons") or []) and _word_count(text) < 5:
        return "extraction issue"
    return "needs review"


def _knowledge_units_for_extraction(
    extraction,
    chunks: list[DocumentChunk],
    *,
    kb_document_type: KnowledgeDocumentType | None = None,
) -> list[dict]:
    structured = getattr(extraction, "structured", None)
    # Typed procedure/requirement chunks (including Citizen's Charter service blocks)
    # must win over handbook logical units when the detected KB profile is not information.
    prefer_typed_chunks = kb_document_type in {
        KnowledgeDocumentType.PROCEDURE,
        KnowledgeDocumentType.REQUIREMENT,
    } or any(
        str((chunk.metadata or {}).get("parser_document_type") or "").lower()
        in {"citizen_charter", "service_process", "procedure"}
        for chunk in chunks
    )
    if isinstance(structured, HandbookPolicyDocument) and not prefer_typed_chunks:
        units: list[dict] = []
        for index, unit in enumerate(structured.units):
            metadata = dict(unit.metadata)
            item = {
                "unit_index": index,
                "title": unit.title,
                "content": unit.content,
                "content_type": metadata.get("content_type") or "policy",
                "hierarchy_path": _hierarchy_path(metadata),
                "word_count": _word_count(unit.article_text),
                "page_start": metadata.get("page_start"),
                "page_end": metadata.get("page_end"),
                "metadata": metadata,
            }
            status, reasons = _unit_status(item)
            item["status"] = status
            item["suspicious_reasons"] = reasons
            units.append(item)
        return units

    units = []
    for chunk in chunks:
        metadata = dict(chunk.metadata or {})
        item = {
            "unit_index": chunk.chunk_index,
            "title": _title_from_chunk(chunk),
            "content": chunk.text,
            "content_type": metadata.get("content_type") or "document_chunk",
            "hierarchy_path": _hierarchy_path(metadata),
            "word_count": _word_count(chunk.text),
            "page_start": metadata.get("page_start"),
            "page_end": metadata.get("page_end"),
            "metadata": metadata,
            "parser_document_type": metadata.get("parser_document_type"),
            "source_type": metadata.get("source_type"),
            "document_type": metadata.get("document_type"),
        }
        status, reasons = _unit_status(item)
        item["status"] = status
        item["suspicious_reasons"] = reasons
        units.append(item)
    return units


def _chunk_preview(chunks: list[DocumentChunk]) -> list[dict]:
    previews: list[dict] = []
    for chunk in chunks:
        metadata = dict(chunk.metadata or {})
        previews.append(
            {
                "chunk_index": chunk.chunk_index,
                "title": _title_from_chunk(chunk),
                "word_count": _word_count(chunk.text),
                "hierarchy_path": _hierarchy_path(metadata),
                "page_start": metadata.get("page_start"),
                "page_end": metadata.get("page_end"),
                "content_preview": chunk.text[:300],
                "content": chunk.text,
                "metadata": metadata,
            }
        )
    return previews


def _validation_report(*, document_type: str, units: list[dict], chunks: list[DocumentChunk]) -> dict:
    chunk_words = [_word_count(chunk.text) for chunk in chunks]
    missing_metadata_count = 0
    toc_like_units_count = 0
    empty_units_count = 0
    suspicious_units_count = 0
    for unit in units:
        metadata = unit.get("metadata") if isinstance(unit.get("metadata"), dict) else {}
        hierarchy = _hierarchy_path(metadata)
        if not unit.get("title") or not metadata.get("source_title") or not hierarchy:
            missing_metadata_count += 1
        if (
            _looks_toc_like(str(unit.get("title") or ""))
            or _looks_toc_like(str(unit.get("content") or ""))
            or _has_standalone_page_number_path_segment(hierarchy)
            or "toc_like" in (unit.get("suspicious_reasons") or [])
        ):
            toc_like_units_count += 1
        if _word_count(str(unit.get("content") or "")) == 0:
            empty_units_count += 1
        if unit.get("status") == "Suspicious":
            suspicious_units_count += 1
    oversized_chunks_count = sum(1 for words in chunk_words if words > 1200)
    campus_values, program_campus_values, invalid_campus_values = _campus_validation_from_units(units)
    remaining_ocr_word_splits = _ocr_split_validation_from_units(units)
    needs_review = any(
        count > 0
        for count in (
            missing_metadata_count,
            toc_like_units_count,
            empty_units_count,
            suspicious_units_count,
            oversized_chunks_count,
            len(invalid_campus_values),
            len(remaining_ocr_word_splits),
        )
    )
    return {
        "document_type": document_type,
        "total_knowledge_units": len(units),
        "total_chunks": len(chunks),
        "average_chunk_words": round(sum(chunk_words) / len(chunk_words), 2) if chunk_words else 0,
        "largest_chunk_words": max(chunk_words, default=0),
        "smallest_chunk_words": min(chunk_words, default=0),
        "missing_metadata_count": missing_metadata_count,
        "toc_like_units_count": toc_like_units_count,
        "empty_units_count": empty_units_count,
        "suspicious_units_count": suspicious_units_count,
        "oversized_chunks_count": oversized_chunks_count,
        "known_campuses": list(KNOWN_CAMPUS_NAMES),
        "unique_campus_names": sorted(campus_values),
        "unique_program_campus_values": sorted(program_campus_values),
        "invalid_campus_values": invalid_campus_values,
        "remaining_ocr_word_splits": remaining_ocr_word_splits,
        "status": "Needs Review" if needs_review else "Ready for Indexing",
    }


def _campus_validation_from_units(units: list[dict]) -> tuple[set[str], set[str], list[dict[str, str]]]:
    campus_values: set[str] = set()
    program_campus_values: set[str] = set()
    invalid: list[dict[str, str]] = []
    for unit in units:
        title = str(unit.get("title") or "")
        metadata = unit.get("metadata") if isinstance(unit.get("metadata"), dict) else {}
        for value in metadata.get("campuses") or []:
            if not isinstance(value, str):
                continue
            campus_values.add(value)
            if value not in KNOWN_CAMPUS_NAMES:
                invalid.append({"title": title, "field": "campuses", "value": value})
        program_campuses = metadata.get("program_campuses") or {}
        if not isinstance(program_campuses, dict):
            continue
        for program, values in program_campuses.items():
            for value in values or []:
                if not isinstance(value, str):
                    continue
                program_campus_values.add(value)
                if value not in KNOWN_CAMPUS_NAMES:
                    invalid.append({"title": title, "field": f"program_campuses.{program}", "value": value})
    return campus_values, program_campus_values, invalid


def _ocr_split_validation_from_units(units: list[dict]) -> list[dict[str, str | int]]:
    class _AuditDocument:
        def __init__(self, source_units: list[dict]) -> None:
            self.units = [
                type(
                    "AuditUnit",
                    (),
                    {
                        "title": str(unit.get("title") or ""),
                        "content": str(unit.get("content") or ""),
                        "raw_text": str(unit.get("content") or ""),
                    },
                )()
                for unit in source_units
            ]

    return handbook_ocr_split_audit(_AuditDocument(units))


def _quality_payload(
    extraction,
    index_text: str,
    *,
    kb_document_type: KnowledgeDocumentType = KnowledgeDocumentType.INFORMATION,
    title: str = "Untitled document",
    source_document: str = "unknown",
    preview_file_path: str | None = None,
) -> tuple[list[DocumentChunk], list[dict], list[dict], dict]:
    chunks = _chunks_for_extraction(
        extraction,
        index_text,
        kb_document_type=kb_document_type,
        title=title,
        source_document=source_document,
        preview_file_path=preview_file_path,
    )
    chunks = enrich_chunks_with_category_metadata(
        chunks,
        title=title or kb_document_type.value,
    )
    units = _knowledge_units_for_extraction(
        extraction,
        chunks,
        kb_document_type=kb_document_type,
    )
    previews = _chunk_preview(chunks)
    validation = _validation_report(
        document_type=kb_document_type.value,
        units=units,
        chunks=chunks,
    )
    return chunks, units, previews, validation


def knowledge_base_statistics() -> dict:
    try:
        return get_knowledge_base_store().collection_statistics()
    except Exception as exc:
        return {
            "documents_indexed": 0,
            "total_chunks_indexed": 0,
            "embedding_model": "ChromaDB default embedding function",
            "vector_store": "ChromaDB",
            "last_indexed_document": None,
            "error": str(exc),
        }


def _diagnostic_report(extraction) -> dict | None:
    structured = getattr(extraction, "structured", None)
    if isinstance(structured, HandbookPolicyDocument):
        return structured.diagnostic_report()
    return None


_CHARTER_V2_EMPTY_DIAGNOSTICS: dict[str, Any] = {
    "v2_attempted": False,
    "pdf_pages_available": False,
    "pdf_pages_count": 0,
    "pages_with_words_count": 0,
    "total_words_count": 0,
    "preview_has_charter_v2_services": False,
    "preview_charter_v2_services_count": 0,
    "v2_error_message": None,
    "fallback_reason": None,
    "page_geometry_debug": [],
}

_CHARTER_V2_EMPTY_PAYLOAD: dict[str, Any] = {
    "charter_v2_services": [],
    "charter_v2_detected_count": 0,
    "charter_v2_clean_count": 0,
    "charter_v2_needs_review_count": 0,
    "charter_v2_low_quality_count": 0,
    "charter_v2_rag_only_count": 0,
    "charter_v2_diagnostics": dict(_CHARTER_V2_EMPTY_DIAGNOSTICS),
    "structured_extraction_text": "",
    "extraction_priority_diagnostics": [],
}

_PARSER_DEBUG_CLIP_CHARS = 400


def _pdf_pages_geometry_stats(pdf_pages) -> dict[str, Any]:
    pages = list(pdf_pages or [])
    pages_with_words = 0
    total_words = 0
    for page in pages:
        words = getattr(page, "words", None) or []
        if words:
            pages_with_words += 1
            total_words += len(words)
    return {
        "pdf_pages_available": bool(pages),
        "pdf_pages_count": len(pages),
        "pages_with_words_count": pages_with_words,
        "total_words_count": total_words,
    }


def _reconstruct_page_rows_from_words(words: list[dict], *, max_rows: int = 20) -> list[str]:
    """Compact row dump for debug when V2 returns zero services."""
    if not words:
        return []
    buckets: dict[int, list[tuple[float, str]]] = {}
    for word in words:
        text = str(word.get("text") or "").strip()
        if not text:
            continue
        try:
            cy = float(word.get("cy") if word.get("cy") is not None else word.get("y0") or 0.0)
            x0 = float(word.get("x0") or 0.0)
        except (TypeError, ValueError):
            continue
        # Bucket by ~10pt Y bands so wrapped table cells stay readable.
        key = int(round(cy / 10.0))
        buckets.setdefault(key, []).append((x0, text))
    rows: list[str] = []
    for key in sorted(buckets.keys()):
        cells = sorted(buckets[key], key=lambda item: item[0])
        line = " ".join(text for _, text in cells).strip()
        if line:
            rows.append(line)
        if len(rows) >= max_rows:
            break
    return rows


def _charter_v2_page_geometry_debug(pdf_pages, *, max_pages: int = 3) -> list[dict[str, Any]]:
    dump: list[dict[str, Any]] = []
    for page in list(pdf_pages or [])[:max_pages]:
        words = list(getattr(page, "words", None) or [])
        rows = _reconstruct_page_rows_from_words(words, max_rows=20)
        heading_like = [
            row
            for row in rows
            if row[:1].isdigit()
            or row.lower().startswith(("office", "classification", "who may", "checklist", "client"))
        ][:10]
        dump.append(
            {
                "page_number": getattr(page, "page_number", None),
                "word_count": len(words),
                "first_20_rows": rows,
                "detected_headings": heading_like,
            }
        )
    return dump


def _compact_charter_v2_service(service_dict: dict[str, Any]) -> dict[str, Any]:
    """Keep Flutter/localStorage payload small: clip large parser_debug blocks."""
    compact = dict(service_dict)
    debug = compact.get("parser_debug")
    if isinstance(debug, dict):
        clipped = dict(debug)
        for key in ("raw_service_block", "cleaned_service_block"):
            value = clipped.get(key)
            if isinstance(value, str) and len(value) > _PARSER_DEBUG_CLIP_CHARS:
                clipped[key] = value[:_PARSER_DEBUG_CLIP_CHARS] + "…"
        compact["parser_debug"] = clipped
    return compact


def _charter_v2_preview_payload(result, document_profile: str) -> dict[str, Any]:
    """Run Citizen's Charter Extraction V2 during the extraction preview.

    Strictly gated to citizen_charter / service_process document profiles.
    Only compact structured services + parser_debug go into the returned
    payload — never raw word/geometry boxes — to keep the Flutter preview
    payload small. Always includes ``charter_v2_diagnostics`` so Generate
    Articles / the admin report can explain why V2 was or was not used.

    When services are detected, also builds ``structured_extraction_text`` so
    Full Extraction Result / download TXT can render from V2 structured fields
    instead of the older flattened text parser.
    """
    diagnostics = dict(_CHARTER_V2_EMPTY_DIAGNOSTICS)
    empty = {
        **dict(_CHARTER_V2_EMPTY_PAYLOAD),
        "charter_v2_diagnostics": diagnostics,
        "structured_extraction_text": "",
        "extraction_priority_diagnostics": [],
    }

    if document_profile not in {"citizen_charter", "service_process"}:
        diagnostics["fallback_reason"] = "document_profile_not_charter_or_service_process"
        return empty

    pdf_pages = getattr(result, "pdf_pages", None)
    geometry = _pdf_pages_geometry_stats(pdf_pages)
    diagnostics.update(geometry)

    if not pdf_pages:
        diagnostics["v2_attempted"] = False
        diagnostics["fallback_reason"] = "pdf_pages_missing_from_ingestion_result"
        return empty

    diagnostics["v2_attempted"] = True

    from app.services.citizen_charter_extractor_v2 import extract_citizen_charter_services_v2
    from app.services.citizen_charter_extraction_renderer import (
        build_extraction_priority_diagnostics,
        finalize_charter_v2_services_for_extraction,
        render_citizen_charter_v2_extraction_text,
    )

    try:
        services = extract_citizen_charter_services_v2(pdf_pages)
    except Exception as exc:
        logger.exception(
            "Citizen's Charter Extraction V2 failed; Generate Articles will not use V2 services."
        )
        diagnostics["v2_error_message"] = f"{type(exc).__name__}: {exc}"
        diagnostics["fallback_reason"] = "v2_extractor_raised"
        diagnostics["page_geometry_debug"] = _charter_v2_page_geometry_debug(pdf_pages)
        return empty

    compact_services = [_compact_charter_v2_service(asdict(service)) for service in services]
    compact_services = finalize_charter_v2_services_for_extraction(compact_services)
    quality_counts = Counter(
        str(item.get("extraction_quality") or "low_quality") for item in compact_services
    )
    diagnostics["preview_has_charter_v2_services"] = bool(compact_services)
    diagnostics["preview_charter_v2_services_count"] = len(compact_services)
    priority_diagnostics = build_extraction_priority_diagnostics(compact_services)
    diagnostics["extraction_priority_diagnostics"] = priority_diagnostics
    structured_extraction_text = (
        render_citizen_charter_v2_extraction_text(
            compact_services, include_priority_diagnostics=True
        )
        if compact_services
        else ""
    )
    if not compact_services:
        diagnostics["fallback_reason"] = "v2_returned_zero_services"
        diagnostics["page_geometry_debug"] = _charter_v2_page_geometry_debug(pdf_pages)
        # Collect rejection crumbs from any partial debug if the extractor exposed none.
        rejected: list[str] = []
        for page_dump in diagnostics["page_geometry_debug"]:
            for row in page_dump.get("first_20_rows") or []:
                lower = str(row).casefold()
                if any(
                    crumb in lower
                    for crumb in (
                        "government to citizen",
                        "ds review",
                        "interview of reference",
                        "id or registration cards",
                    )
                ):
                    rejected.append(str(row)[:120])
        if rejected:
            diagnostics["rejection_reason_samples"] = rejected[:20]
    else:
        diagnostics["fallback_reason"] = None

    return {
        "charter_v2_services": compact_services,
        "charter_v2_detected_count": len(compact_services),
        "charter_v2_clean_count": int(quality_counts.get("clean", 0)),
        "charter_v2_needs_review_count": int(quality_counts.get("needs_review", 0)),
        "charter_v2_low_quality_count": int(quality_counts.get("low_quality", 0)),
        "charter_v2_rag_only_count": int(quality_counts.get("rag_only", 0)),
        "charter_v2_diagnostics": diagnostics,
        "structured_extraction_text": structured_extraction_text,
        "extraction_priority_diagnostics": priority_diagnostics,
    }


def extract_document_preview(
    file_bytes: bytes,
    *,
    filename: str | None = None,
    content_type: str | None = None,
    document_type: str | None = None,
    preview_file_path: str | None = None,
) -> dict:
    """Extract and clean text only (no ChromaDB write). For admin preview."""
    result = ingest_document(file_bytes, filename=filename, content_type=content_type)
    review = prepare_review_document(result)
    preview_text = _best_review_text(
        reviewed_text=None,
        review_text=review.review_text,
        cleaned_text=review.cleaned_text,
        extracted_text=result.extracted_text,
    )
    detection = _detect_kb_document_type(result, preview_text, document_type)
    display_title = filename or "Untitled document"
    from app.services.structured_document_parser import classify_document_type

    parsed_kind = classify_document_type(preview_text)
    # Detect charter profile early so V2 can replace Full Extraction Result text.
    if parsed_kind == "citizen_charter" or detection.document_type == KnowledgeDocumentType.PROCEDURE:
        # Prefer citizen_charter when parser says so; otherwise procedure ≈ service_process
        # until units are known. refine after units below.
        tentative_profile = (
            "citizen_charter" if parsed_kind == "citizen_charter" else "service_process"
        )
    else:
        tentative_profile = detection.document_type.value

    charter_v2_payload = _charter_v2_preview_payload(result, tentative_profile)
    structured_v2_text = str(charter_v2_payload.get("structured_extraction_text") or "").strip()
    used_v2_structure = bool(structured_v2_text)
    if used_v2_structure:
        # Full Extraction Result / TXT come from V2 structured services.
        preview_text = structured_v2_text

    chunks, units, previews, validation = _quality_payload(
        result,
        preview_text,
        kb_document_type=(
            KnowledgeDocumentType.PROCEDURE
            if used_v2_structure or tentative_profile in {"citizen_charter", "service_process"}
            else detection.document_type
        ),
        title=display_title,
        source_document=filename or display_title,
        preview_file_path=preview_file_path,
    )
    has_charter_units = any(
        str((unit.get("metadata") or {}).get("parser_document_type") or "").lower()
        == "citizen_charter"
        or str(unit.get("parser_document_type") or "").lower() == "citizen_charter"
        for unit in units
    )
    if used_v2_structure or parsed_kind == "citizen_charter" or has_charter_units:
        document_profile = "citizen_charter"
    elif detection.document_type == KnowledgeDocumentType.PROCEDURE:
        document_profile = "service_process"
    else:
        document_profile = detection.document_type.value

    # If profile only became charter after units and V2 wasn't run, run now.
    if (
        document_profile in {"citizen_charter", "service_process"}
        and not charter_v2_payload.get("charter_v2_services")
        and tentative_profile not in {"citizen_charter", "service_process"}
    ):
        charter_v2_payload = _charter_v2_preview_payload(result, document_profile)
        structured_v2_text = str(charter_v2_payload.get("structured_extraction_text") or "").strip()
        if structured_v2_text:
            preview_text = structured_v2_text
            used_v2_structure = True
            chunks, units, previews, validation = _quality_payload(
                result,
                preview_text,
                kb_document_type=KnowledgeDocumentType.PROCEDURE,
                title=display_title,
                source_document=filename or display_title,
                preview_file_path=preview_file_path,
            )

    return {
        "document_type": (
            "citizen_charter"
            if document_profile == "citizen_charter"
            else _compat_response_document_type(result, detection.document_type)
        ),
        "document_profile": document_profile,
        "detected_document_type": {
            "document_type": (
                "citizen_charter"
                if document_profile == "citizen_charter"
                else detection.document_type.value
            ),
            "reason": detection.reason,
            "scores": detection.scores,
            "manual_override": detection.manual_override,
            "admin_selected_document_type": document_type,
            "parser_kind": parsed_kind,
        },
        "admin_selected_document_type": document_type,
        "source_type": "Citizen's Charter" if document_profile == "citizen_charter" else None,
        "parser_document_type": "citizen_charter" if document_profile == "citizen_charter" else None,
        "raw_text": review.raw_text,
        "cleaned_text": review.cleaned_text,
        "review_text": preview_text,
        "extracted_text": preview_text,
        "page_count": result.page_count,
        "extraction_method": result.extraction_method,
        "structuring_method": (
            "citizen_charter_extractor_v2"
            if used_v2_structure
            else review.structuring_method
        ),
        "pipeline_stages": _pipeline_stages(
            extraction_method=result.extraction_method,
            structuring_method=(
                "citizen_charter_extractor_v2" if used_v2_structure else review.structuring_method
            ),
            indexed=False,
        ),
        "structured": _structured_text_response(
            preview_text,
            source_document=filename or display_title,
            preview_file_path=preview_file_path,
        ),
        "diagnostic_report": _diagnostic_report(result),
        "validation_report": validation,
        "knowledge_units": units,
        "chunk_preview": previews,
        "kb_statistics": knowledge_base_statistics(),
        **charter_v2_payload,
    }


def ingest_document_into_knowledge_base(
    file_bytes: bytes,
    *,
    filename: str | None = None,
    content_type: str | None = None,
    title: str | None = None,
    reviewed_text: str | None = None,
    document_type: str | None = None,
    preview_file_path: str | None = None,
    replace_existing: bool = False,
    document_id: str | None = None,
) -> KnowledgeBaseIngestResult:
    """
    Full admin pipeline: OCR/PDF extraction through ChromaDB indexing.
    """
    if document_id and not replace_existing:
        raise ValueError("document_id can only be used when replace_existing is true.")
    if replace_existing and not document_id:
        raise ValueError("replace_existing requires document_id.")

    extraction = ingest_document(file_bytes, filename=filename, content_type=content_type)
    review = prepare_review_document(extraction)
    dynamic = analyze_document_structure(extraction.cleaned_text or extraction.extracted_text)
    display_title = title or filename or "Untitled document"
    source_document = filename or display_title

    # Early Charter detection from filename / manual type before reviewed_text can
    # collapse typing into requirement/form (e.g. active Generate Articles card).
    looks_like_charter = _is_citizens_charter_source(
        filename=filename,
        title=title,
        text=(extraction.cleaned_text or extraction.extracted_text or "")[:6000],
        document_type=document_type,
    )

    charter_v2_services: list[dict] = []
    used_v2_chunks = False
    structured_v2_text = ""
    structuring_method = review.structuring_method
    charter_v2_diagnostics: dict[str, Any] = {}

    if looks_like_charter:
        charter_v2_payload = _charter_v2_preview_payload(extraction, "citizen_charter")
        charter_v2_services = list(charter_v2_payload.get("charter_v2_services") or [])
        structured_v2_text = str(charter_v2_payload.get("structured_extraction_text") or "").strip()
        charter_v2_diagnostics = dict(charter_v2_payload.get("charter_v2_diagnostics") or {})
        if structured_v2_text:
            structuring_method = "citizen_charter_extractor_v2"
        if charter_v2_services:
            chunks = build_chunks_from_charter_v2_services(
                charter_v2_services,
                title=display_title,
                source_document=source_document,
            )
            used_v2_chunks = bool(chunks)
            if used_v2_chunks:
                units = _knowledge_units_for_extraction(
                    extraction,
                    chunks,
                    kb_document_type=KnowledgeDocumentType.PROCEDURE,
                )
                previews = _chunk_preview(chunks)
                validation = _validation_report(
                    document_type="citizen_charter",
                    units=units,
                    chunks=chunks,
                )

        index_text = _charter_index_text(
            reviewed_text=reviewed_text,
            extraction=extraction,
            structured_v2_text=structured_v2_text,
        )
    else:
        index_text = _best_review_text(
            reviewed_text=reviewed_text,
            review_text=review.review_text,
            cleaned_text=extraction.cleaned_text,
            extracted_text=extraction.extracted_text,
        )

    from app.services.structured_document_parser import classify_document_type

    parsed_kind = classify_document_type(index_text)
    detection = _detect_kb_document_type(
        extraction,
        index_text,
        "citizen_charter" if looks_like_charter else document_type,
    )
    # Second-pass: reviewed/extraction text may still reveal a charter.
    if not looks_like_charter:
        looks_like_charter = _is_citizens_charter_source(
            filename=filename,
            title=title,
            text=index_text,
            document_type=document_type,
            detection_type=detection.document_type,
        ) or parsed_kind == "citizen_charter"
        if looks_like_charter and not used_v2_chunks:
            charter_v2_payload = _charter_v2_preview_payload(extraction, "citizen_charter")
            charter_v2_services = list(charter_v2_payload.get("charter_v2_services") or [])
            structured_v2_text = str(charter_v2_payload.get("structured_extraction_text") or "").strip()
            charter_v2_diagnostics = dict(charter_v2_payload.get("charter_v2_diagnostics") or {})
            if structured_v2_text:
                index_text = structured_v2_text
                structuring_method = "citizen_charter_extractor_v2"
            if charter_v2_services:
                chunks = build_chunks_from_charter_v2_services(
                    charter_v2_services,
                    title=display_title,
                    source_document=source_document,
                )
                used_v2_chunks = bool(chunks)
                if used_v2_chunks:
                    units = _knowledge_units_for_extraction(
                        extraction,
                        chunks,
                        kb_document_type=KnowledgeDocumentType.PROCEDURE,
                    )
                    previews = _chunk_preview(chunks)
                    validation = _validation_report(
                        document_type="citizen_charter",
                        units=units,
                        chunks=chunks,
                    )

    response_document_type = _compat_response_document_type(extraction, detection.document_type)

    if not used_v2_chunks:
        # Never let Citizen's Charter fall into single requirement_form chunking.
        kb_type = detection.document_type
        if looks_like_charter:
            kb_type = KnowledgeDocumentType.PROCEDURE
            response_document_type = "citizen_charter"
            index_text = _charter_index_text(
                reviewed_text=reviewed_text,
                extraction=extraction,
                structured_v2_text=structured_v2_text,
            )
        chunks, units, previews, validation = _quality_payload(
            extraction,
            index_text,
            kb_document_type=kb_type,
            title=display_title,
            source_document=source_document,
            preview_file_path=preview_file_path,
        )
    else:
        response_document_type = "citizen_charter"

    if not chunks:
        raise ValueError("No chunks produced from extracted text.")

    # Guard: a lone Requirement:/form card must never replace a full Charter index.
    chunk_titles = [
        str((getattr(chunk, "metadata", None) or {}).get("title") or "").strip()
        for chunk in chunks
    ]
    only_requirement_form = (
        len(chunks) == 1
        and (
            chunk_titles[0].casefold().startswith("requirement:")
            or "request form" in chunk_titles[0].casefold()
            or (getattr(chunks[0], "metadata", None) or {}).get("article_type")
            in {"requirement_form", "form_requirement"}
        )
    )
    if looks_like_charter and only_requirement_form:
        raise ValueError(
            "Citizen's Charter indexing produced only a requirement/form chunk. "
            "Re-run Extract on the full PDF, then Index for Chatbot Retrieval again. "
            f"Diagnostics: {charter_v2_diagnostics or 'charter_v2 unavailable'}"
        )
    if looks_like_charter and len(chunks) < 2:
        logger.warning(
            "Citizen's Charter indexed fewer than 2 chunks (count=%s, titles=%s). "
            "Expected one service_procedure chunk per detected service.",
            len(chunks),
            chunk_titles[:12],
        )

    doc_id = document_id or str(uuid.uuid4())
    chunks = enrich_chunks_with_category_metadata(
        chunks,
        title=display_title,
        source_document=source_document,
    )
    if not used_v2_chunks:
        units = _knowledge_units_for_extraction(
            extraction,
            chunks,
            kb_document_type=KnowledgeDocumentType.PROCEDURE
            if looks_like_charter
            else detection.document_type,
        )
        previews = _chunk_preview(chunks)
        validation = _validation_report(
            document_type=response_document_type,
            units=units,
            chunks=chunks,
        )
    store = get_knowledge_base_store()

    if replace_existing and document_id:
        store.delete_document(document_id)
    # Always replace prior chunks for this source file so re-index rebuilds the
    # full Citizen's Charter (not a leftover single form card).
    deleted = store.delete_by_source_filename(source_document)
    if deleted:
        logger.info(
            "Removed %s existing Chroma chunk(s) for source_filename=%s before re-index",
            deleted,
            source_document,
        )

    # Persist original bytes for citation / PDF viewer (PostgreSQL + filesystem).
    try:
        from app.services.document_storage import persist_uploaded_document

        persist_uploaded_document(
            file_bytes,
            document_id=doc_id,
            filename=source_document,
            content_type=content_type,
            document_type=response_document_type,
            title=display_title,
            page_count=extraction.page_count,
        )
    except Exception:
        logger.exception(
            "Failed to persist source document file for citation grounding: document_id=%s",
            doc_id,
        )

    indexed = store.add_document_chunks(
        document_id=doc_id,
        title=display_title,
        source_filename=source_document,
        document_type=response_document_type,
        chunks=chunks,
        document_metadata={
            "source_document_type": _response_document_type(extraction),
            "detected_document_type": detection.document_type.value,
            "document_type_reason": detection.reason,
            "kind": dynamic.document_kind,
            "structure_confidence": round(dynamic.confidence, 3),
            "source_label": display_title,
            "display_title": display_title,
            "charter_v2_services_indexed": len(charter_v2_services) if used_v2_chunks else 0,
            "structuring_method": structuring_method,
            **{
                key.lower().replace(" ", "_"): value
                for key, value in dynamic.metadata.items()
            },
        },
    )

    preview = index_text[:500]
    if len(index_text) > 500:
        preview += "..."

    return KnowledgeBaseIngestResult(
        document_id=doc_id,
        document_type=response_document_type,
        source_filename=source_document,
        title=display_title,
        chunks_indexed=indexed,
        page_count=extraction.page_count,
        extraction_method=extraction.extraction_method,
        extracted_text_preview=preview,
        structured=_structured_text_response(
            index_text,
            source_document=source_document,
            preview_file_path=preview_file_path,
        ),
        structuring_method=structuring_method,
        pipeline_stages=_pipeline_stages(
            extraction_method=extraction.extraction_method,
            structuring_method=structuring_method,
            indexed=True,
            chunks_indexed=indexed,
        ),
        diagnostic_report=_diagnostic_report(extraction),
        validation_report=validation,
        detected_document_type={
            "document_type": response_document_type,
            "reason": detection.reason,
            "scores": detection.scores,
            "manual_override": detection.manual_override,
            "charter_v2_used": used_v2_chunks,
            "charter_v2_services_count": len(charter_v2_services) if used_v2_chunks else 0,
            "charter_v2_diagnostics": charter_v2_diagnostics,
        },
        knowledge_units=units,
        chunk_preview=previews,
        kb_statistics=store.collection_statistics(),
    )


def retrieval_test(question: str, *, top_k: int = 5) -> dict:
    store = get_knowledge_base_store()
    display_k = max(1, min(top_k, 20))
    results = store.search(question, top_k=display_k, raw_k=max(10, display_k))
    chunks = []
    for rank, chunk in enumerate(results, start=1):
        metadata = chunk.metadata or {}
        chunks.append(
            {
                "rank": rank,
                "title": _title_from_metadata(metadata) or chunk.title,
                "similarity_score": chunk.original_score if chunk.original_score is not None else chunk.relevance_score,
                "original_score": chunk.original_score if chunk.original_score is not None else chunk.relevance_score,
                "reranked_score": chunk.reranked_score if chunk.reranked_score is not None else chunk.relevance_score,
                "boost_reasons": chunk.rerank_reasons or [],
                "hierarchy_path": _hierarchy_path(metadata),
                "page_start": metadata.get("page_start"),
                "page_end": metadata.get("page_end"),
                "content_preview": _text_preview(chunk.text, max_chars=RETRIEVAL_TEST_PREVIEW_CHARS),
                "content": chunk.text,
            }
        )
    return {
        "question": question,
        "top_k": display_k,
        "results": chunks,
        "kb_statistics": store.collection_statistics(),
    }


def _text_preview(text: str, *, max_chars: int) -> str:
    cleaned = (text or "").strip()
    if len(cleaned) <= max_chars:
        return cleaned
    preview = cleaned[:max_chars].rstrip()
    boundary = max(preview.rfind("\n"), preview.rfind(". "), preview.rfind("; "), preview.rfind(", "))
    if boundary >= int(max_chars * 0.65):
        preview = preview[: boundary + 1].rstrip()
    return f"{preview}..."
