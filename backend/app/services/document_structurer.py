"""Document structuring facade for ASKa-Piyu.

Use this after OCR/PDF extraction and before admin review/indexing.
It returns both machine-readable JSON and a clean preview string.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.text_cleaner import clean_ocr_text
from app.services.dynamic_document_analyzer import (
    analyze_document_structure,
    format_dynamic_document,
)
from app.services.structured_document_parser import (
    parse_structured_document,
    format_structured_document,
)
from app.services.handbook_policy_processor import HandbookPolicyDocument


@dataclass
class ReviewDocument:
    raw_text: str
    cleaned_text: str
    review_text: str
    structuring_method: str


def structure_document(text: str, as_text: bool = True) -> str | dict[str, Any]:
    cleaned = clean_ocr_text(text)
    dynamic = analyze_document_structure(cleaned)

    if dynamic.document_kind == "citizen_charter":
        parsed = parse_structured_document(cleaned)
        formatted = format_structured_document(parsed)
    else:
        parsed = {
            "status": "success",
            "document_kind": dynamic.document_kind,
            "confidence": dynamic.confidence,
            "metadata": dynamic.metadata,
            "sections": [section.__dict__ for section in dynamic.sections],
            "tables": [
                {"headers": table.headers, "rows": table.rows}
                for table in dynamic.tables
            ],
        }
        formatted = format_dynamic_document(dynamic, cleaned)

    if _structure_is_uncertain(formatted, cleaned):
        formatted = cleaned

    parsed["cleaned_text"] = cleaned
    parsed["review_required"] = "[NEEDS REVIEW]" in formatted
    if as_text:
        return formatted
    return parsed


def _structure_is_uncertain(formatted: str, cleaned: str) -> bool:
    if not formatted.strip():
        return True
    useful_text = formatted.replace("[NEEDS REVIEW]", "").strip()
    useful_text_ratio = len(useful_text) / max(len(cleaned.strip()), 1)
    return formatted.count("[NEEDS REVIEW]") >= 4 and useful_text_ratio < 0.2


def structure_ocr_text(text: str) -> str:
    return str(structure_document(text, as_text=True))


def clean_and_structure_document(text: str) -> dict[str, Any]:
    return structure_document(text, as_text=False)  # type: ignore[return-value]


def clean_and_structure_text(text: str) -> str:
    return str(structure_document(text, as_text=True))


def build_structured_preview(text: str) -> str:
    return str(structure_document(text, as_text=True))


def structure_for_preview(text: str) -> str:
    return build_structured_preview(text)

def prepare_review_document(source: Any) -> ReviewDocument:
    """
    Compatibility function for knowledge_base_pipeline.py.

    Prepares extracted/cleaned text for admin review before indexing.
    """
    if hasattr(source, "extracted_text"):
        structured = getattr(source, "structured", None)
        if isinstance(structured, HandbookPolicyDocument):
            return ReviewDocument(
                raw_text=(getattr(source, "raw_extracted_text", "") or structured.raw_text).strip(),
                cleaned_text=structured.cleaned_text,
                review_text=structured.formatted_articles or structured.cleaned_text,
                structuring_method="handbook_policy_logical",
            )
        cleaned_text = (getattr(source, "cleaned_text", "") or source.extracted_text or "").strip()
        raw_text = (getattr(source, "raw_extracted_text", "") or cleaned_text).strip()
    else:
        cleaned_text = str(source or "").strip()
        raw_text = cleaned_text

    return ReviewDocument(
        raw_text=raw_text,
        cleaned_text=cleaned_text,
        review_text=build_structured_preview(cleaned_text),
        structuring_method="deterministic",
    )
