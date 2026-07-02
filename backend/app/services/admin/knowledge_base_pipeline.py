"""
Admin knowledge-base creation flow.

Upload → extract (OCR/PDF) → clean → chunk → embed → ChromaDB

Runs at deployment, policy updates, and admin maintenance — not during student Q&A.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
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
from app.services.structured_document_parser import build_structured_document, format_structured_document


NEEDS_REVIEW = "[NEEDS REVIEW]"
RETRIEVAL_TEST_PREVIEW_CHARS = 700


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


def _structured_text_response(text: str) -> StructuredDocumentSchema:
    structured = build_structured_document(text)
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


def _best_review_text(*, reviewed_text: str | None, review_text: str, cleaned_text: str, extracted_text: str) -> str:
    reviewed = (reviewed_text or "").strip()
    if reviewed:
        return reviewed
    if _only_needs_review(review_text):
        return cleaned_text or extracted_text
    return review_text


def _response_document_type(extraction) -> str:
    return getattr(extraction, "knowledge_document_type", None) or extraction.document_type.value


def _chunks_for_extraction(extraction, index_text: str) -> list[DocumentChunk]:
    structured = getattr(extraction, "structured", None)
    if isinstance(structured, HandbookPolicyDocument):
        chunks: list[DocumentChunk] = []
        char_start = 0
        for unit in structured.units:
            text = unit.article_text
            chunks.append(
                DocumentChunk(
                    text=text,
                    chunk_index=len(chunks),
                    char_start=char_start,
                    metadata=dict(unit.metadata),
                )
            )
            char_start += len(text) + 2
        return chunks
    return chunk_document_text(index_text)


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


def _knowledge_units_for_extraction(extraction, chunks: list[DocumentChunk]) -> list[dict]:
    structured = getattr(extraction, "structured", None)
    if isinstance(structured, HandbookPolicyDocument):
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


def _quality_payload(extraction, index_text: str) -> tuple[list[DocumentChunk], list[dict], list[dict], dict]:
    chunks = _chunks_for_extraction(extraction, index_text)
    chunks = enrich_chunks_with_category_metadata(
        chunks,
        title=getattr(extraction, "knowledge_document_type", None) or getattr(extraction, "document_type", ""),
    )
    units = _knowledge_units_for_extraction(extraction, chunks)
    previews = _chunk_preview(chunks)
    validation = _validation_report(
        document_type=_response_document_type(extraction),
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


def extract_document_preview(
    file_bytes: bytes,
    *,
    filename: str | None = None,
    content_type: str | None = None,
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
    chunks, units, previews, validation = _quality_payload(result, preview_text)
    return {
        "document_type": _response_document_type(result),
        "raw_text": review.raw_text,
        "cleaned_text": review.cleaned_text,
        "review_text": preview_text,
        "extracted_text": preview_text,
        "page_count": result.page_count,
        "extraction_method": result.extraction_method,
        "structuring_method": review.structuring_method,
        "pipeline_stages": _pipeline_stages(
            extraction_method=result.extraction_method,
            structuring_method=review.structuring_method,
            indexed=False,
        ),
        "structured": _structured_text_response(preview_text),
        "diagnostic_report": _diagnostic_report(result),
        "validation_report": validation,
        "knowledge_units": units,
        "chunk_preview": previews,
        "kb_statistics": knowledge_base_statistics(),
    }


def ingest_document_into_knowledge_base(
    file_bytes: bytes,
    *,
    filename: str | None = None,
    content_type: str | None = None,
    title: str | None = None,
    reviewed_text: str | None = None,
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
    index_text = _best_review_text(
        reviewed_text=reviewed_text,
        review_text=review.review_text,
        cleaned_text=extraction.cleaned_text,
        extracted_text=extraction.extracted_text,
    )
    chunks, units, previews, validation = _quality_payload(extraction, index_text)

    if not chunks:
        raise ValueError("No chunks produced from extracted text.")

    doc_id = document_id or str(uuid.uuid4())
    display_title = title or filename or "Untitled document"
    chunks = enrich_chunks_with_category_metadata(
        chunks,
        title=display_title,
        source_document=filename or display_title,
    )
    units = _knowledge_units_for_extraction(extraction, chunks)
    previews = _chunk_preview(chunks)
    validation = _validation_report(
        document_type=_response_document_type(extraction),
        units=units,
        chunks=chunks,
    )
    store = get_knowledge_base_store()

    if replace_existing and document_id:
        store.delete_document(document_id)

    indexed = store.add_document_chunks(
        document_id=doc_id,
        title=display_title,
        source_filename=filename or "unknown",
        document_type=_response_document_type(extraction),
        chunks=chunks,
        document_metadata={
            "kind": dynamic.document_kind,
            "structure_confidence": round(dynamic.confidence, 3),
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
        document_type=_response_document_type(extraction),
        source_filename=filename or "unknown",
        title=display_title,
        chunks_indexed=indexed,
        page_count=extraction.page_count,
        extraction_method=extraction.extraction_method,
        extracted_text_preview=preview,
        structured=_structured_text_response(index_text),
        structuring_method=review.structuring_method,
        pipeline_stages=_pipeline_stages(
            extraction_method=extraction.extraction_method,
            structuring_method=review.structuring_method,
            indexed=True,
            chunks_indexed=indexed,
        ),
        diagnostic_report=_diagnostic_report(extraction),
        validation_report=validation,
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
