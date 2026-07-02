"""
Document ingestion pipeline: detect type, extract text, clean for knowledge base.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.services.structured_document_parser import (
    StructuredDocument,
    build_structured_document,
    format_structured_document,
)
from app.services.handbook_policy_processor import (
    HandbookPolicyDocument,
    build_handbook_policy_document,
    is_handbook_policy_text,
)
from app.services.text_cleaner import clean_extracted_text
from app.utils.ocr.easyocr_engine import extract_text_from_image_bytes
from app.utils.pdf.pymupdf_extractor import PdfExtractionResult, extract_pdf


class DocumentType(str, Enum):
    IMAGE = "image"
    PDF = "pdf"


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif"}
IMAGE_CONTENT_TYPES = {
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
    "image/bmp",
    "image/tiff",
    "image/gif",
}
PDF_EXTENSIONS = {".pdf"}
PDF_CONTENT_TYPES = {"application/pdf"}


@dataclass
class IngestionResult:
    document_type: DocumentType
    extracted_text: str  # formatted clean text for KB / display
    extraction_method: str  # "ocr" | "digital" | "digital+ocr_fallback"
    page_count: int
    raw_extracted_text: str = ""
    cleaned_text: str = ""
    structured: StructuredDocument | HandbookPolicyDocument | None = None
    knowledge_document_type: str | None = None


class UnsupportedDocumentError(ValueError):
    pass


class EmptyDocumentError(ValueError):
    pass


def detect_document_type(filename: str | None, content_type: str | None) -> DocumentType:
    name = (filename or "").lower()
    ctype = (content_type or "").lower().split(";")[0].strip()

    if any(name.endswith(ext) for ext in PDF_EXTENSIONS) or ctype in PDF_CONTENT_TYPES:
        return DocumentType.PDF
    if any(name.endswith(ext) for ext in IMAGE_EXTENSIONS) or ctype in IMAGE_CONTENT_TYPES:
        return DocumentType.IMAGE

    raise UnsupportedDocumentError(
        f"Unsupported file type. Upload a scanned image or PDF (got: {filename!r}, {content_type!r})."
    )


def ingest_document(
    file_bytes: bytes,
    *,
    filename: str | None = None,
    content_type: str | None = None,
) -> IngestionResult:
    if not file_bytes:
        raise EmptyDocumentError("Uploaded file is empty.")

    doc_type = detect_document_type(filename, content_type)

    if doc_type == DocumentType.IMAGE:
        return _ingest_image(file_bytes)
    return _ingest_pdf(file_bytes, filename=filename)


def _finalize_extraction(
    *,
    document_type: DocumentType,
    raw: str,
    cleaned: str,
    page_texts: list[str] | None,
    extraction_method: str,
    page_count: int,
    structured_override: StructuredDocument | HandbookPolicyDocument | None = None,
    knowledge_document_type: str | None = None,
) -> IngestionResult:
    structured = structured_override or build_structured_document(cleaned)
    if isinstance(structured, HandbookPolicyDocument):
        display_text = structured.formatted_articles or cleaned
    elif isinstance(structured, dict):
        display_text = format_structured_document(structured) or cleaned
    else:
        display_text = structured.formatted_text or cleaned
    if not display_text.strip():
        raise EmptyDocumentError("No text could be extracted from the document.")
    return IngestionResult(
        document_type=document_type,
        extracted_text=display_text,
        raw_extracted_text=raw,
        cleaned_text=cleaned,
        structured=structured,
        knowledge_document_type=knowledge_document_type,
        extraction_method=extraction_method,
        page_count=page_count,
    )


def _ingest_image(file_bytes: bytes) -> IngestionResult:
    raw = extract_text_from_image_bytes(file_bytes)
    cleaned = clean_extracted_text(raw)
    if not cleaned.strip():
        raise EmptyDocumentError("No text could be extracted from the image.")
    return _finalize_extraction(
        document_type=DocumentType.IMAGE,
        raw=raw,
        cleaned=cleaned,
        page_texts=None,
        extraction_method="ocr",
        page_count=1,
    )


def _ingest_pdf(file_bytes: bytes, *, filename: str | None = None) -> IngestionResult:
    pdf_result: PdfExtractionResult = extract_pdf(file_bytes)
    page_texts = [p.text for p in pdf_result.pages]
    raw = _format_multipage_text(pdf_result)
    cleaned = clean_extracted_text(raw, page_texts=page_texts)

    if not cleaned.strip():
        raise EmptyDocumentError("No text could be extracted from the PDF.")

    method = "ocr" if pdf_result.used_ocr_fallback else "digital"
    if pdf_result.used_ocr_fallback:
        method = "digital+ocr_fallback" if _any_digital_signal(page_texts) else "ocr"

    if is_handbook_policy_text(cleaned):
        handbook = build_handbook_policy_document(
            raw_text=raw,
            page_texts=page_texts,
            source_title=_title_from_filename(filename),
        )
        return _finalize_extraction(
            document_type=DocumentType.PDF,
            raw=raw,
            cleaned=handbook.cleaned_text,
            page_texts=page_texts,
            extraction_method=method,
            page_count=len(pdf_result.pages),
            structured_override=handbook,
            knowledge_document_type=handbook.document_type,
        )

    return _finalize_extraction(
        document_type=DocumentType.PDF,
        raw=raw,
        cleaned=cleaned,
        page_texts=page_texts,
        extraction_method=method,
        page_count=len(pdf_result.pages),
    )


def _format_multipage_text(pdf_result: PdfExtractionResult) -> str:
    """Preserve page boundaries for procedural / multi-page documents."""
    blocks: list[str] = []
    for page in pdf_result.pages:
        body = (page.text or "").strip()
        if not body:
            continue
        blocks.append(f"--- Page {page.page_number} ---\n{body}")
    return "\n\n".join(blocks)


def _any_digital_signal(page_texts: list[str]) -> bool:
    return any(len(t.strip()) > 20 for t in page_texts)


def _title_from_filename(filename: str | None) -> str | None:
    if not filename:
        return None
    name = filename.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
    stem = name.rsplit(".", 1)[0]
    stem = stem.replace("_", " ").replace("-", " ").strip()
    return " ".join(part.capitalize() if part.islower() else part for part in stem.split()) or None
