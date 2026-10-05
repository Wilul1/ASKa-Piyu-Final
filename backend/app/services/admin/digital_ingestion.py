"""Zero-cost digital-PDF background ingestion for the Heroku web dyno.

Deliberately separate from app/services/admin/knowledge_base_pipeline.py
(the full local/Docker ingestion pipeline, which can use OCR/local
embeddings and remains unmodified). This module is a narrower, independent
path for the Heroku web dyno specifically:

- PyMuPDF digital text extraction ONLY. No app.utils.pdf.pymupdf_extractor
  and no app.utils.ocr.easyocr_engine import anywhere in this module's
  import graph -- avoided by construction, not by a runtime check, so
  EasyOCR/PyTorch can never be triggered from this code path regardless of
  document content. A document with insufficient digital text gets
  status="ocr_required" and stops; nothing is indexed.
- Embeddings happen implicitly via the existing HFRemoteEmbeddingFunction
  already configured on the production Chroma collection
  (ASKA_EMBEDDING_BACKEND=huggingface) -- this module never loads
  sentence-transformers/torch either.
- Runs as an in-process asyncio background task on the SAME web dyno (the
  same pattern already used by citation_verification_jobs.py) -- no new
  dyno, no new paid service. See IngestionJob's own docstring for the
  Postgres-only job/status/dedup/original-file storage design.
- Version-aware, safe replacement: a replacement ALWAYS gets a brand new
  Chroma document_id. The new version's chunks are added and verified
  BEFORE the old version's chunks (looked up by their own, different,
  document_id -- never by source_filename) are deleted. If verification
  fails, the old version is left untouched. If deleting the old version
  fails AFTER the new version is confirmed published, the job is marked
  needs_reconciliation rather than silently left inconsistent or retried
  blindly.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

import fitz  # PyMuPDF

from sqlalchemy.orm import Session

from app.config import settings
from app.models.db_models import IngestionJob
from app.models.schemas import DocumentFieldSchema, StructuredDocumentSchema
from app.services.admin.knowledge_base_pipeline import (
    chunk_preview,
    knowledge_base_statistics,
    knowledge_units_for_extraction,
    pipeline_stages,
    validation_report,
)
from app.services.admin.ocr_worker_client import OcrWorkerError, call_ocr_worker
from app.services.chroma_store import KnowledgeBaseStore, get_knowledge_base_store
from app.services.chunking import DocumentChunk, chunk_document_text
from app.services.knowledge_taxonomy import enrich_chunks_with_category_metadata
from app.services.structured_document_parser import build_structured_document, format_structured_document
from app.services.text_cleaner import clean_extracted_text

logger = logging.getLogger(__name__)

# Matches the existing _any_digital_signal() heuristic in
# app/services/document_ingestion.py (reimplemented locally -- see module
# docstring for why this file never imports that one).
MIN_DIGITAL_CHARS_PER_PAGE = 20

MAX_PDF_BYTES = 25 * 1024 * 1024  # 25 MB -- generous for a policy/handbook PDF, bounds memory use

# Chroma Cloud enforces a per-request "Number of records" quota on the Add
# action (separate from total collection size -- see the 2026-10-03 incident:
# a single 371-record add() was rejected with "current usage of 371 exceeds
# limit of 300" while the collection already held 728 records overall). 250
# leaves headroom under that 300 ceiling for any per-tenant variance.
CHROMA_ADD_MAX_BATCH_SIZE = 250


class DigitalIngestionError(RuntimeError):
    """Raised for conditions that should stop the job with status='failed'.

    Always means: the new version never became visible in Chroma, and the
    old version (if any) was never touched. Safe for the admin to retry.
    """


class DigitalIngestionReconciliationError(RuntimeError):
    """Raised when automatic cleanup could not fully restore a known-good
    state and a human must inspect/reconcile Chroma manually.

    Maps to status='needs_reconciliation', never 'failed' (which would
    wrongly imply it's simply safe to retry) and never silently
    'published'. The message always carries whatever document_id a human
    needs to find the leftover chunks.
    """


class DigitalIngestionActiveJobError(RuntimeError):
    """Raised when a new job cannot be created because another job is
    already queued/processing/indexing on this single dyno.

    Deliberately NOT a sha256-based duplicate check (see module docstring
    for start_extraction_job) -- this is purely the single-worker
    concurrency guard already used by the existing /ingest-digital path,
    extended to also cover the new review/index split.
    """

    def __init__(self, active_job_id: str) -> None:
        super().__init__(f"Another job (id={active_job_id}) is already in progress on this dyno.")
        self.active_job_id = active_job_id


class DigitalIngestionJobStateError(RuntimeError):
    """Raised when an operation is requested against an IngestionJob whose
    current status doesn't allow it (e.g. indexing a job that isn't
    review_ready yet). Carries the job's actual status for the caller to
    report back."""

    def __init__(self, status: str) -> None:
        super().__init__(f"Job is not in a valid state for this operation (status={status}).")
        self.status = status


def compute_sha256(file_bytes: bytes) -> str:
    return hashlib.sha256(file_bytes).hexdigest()


def validate_pdf_bytes(file_bytes: bytes, *, content_type: str | None) -> None:
    if not file_bytes:
        raise DigitalIngestionError("Uploaded file is empty.")
    if len(file_bytes) > MAX_PDF_BYTES:
        raise DigitalIngestionError(
            f"File exceeds the {MAX_PDF_BYTES // (1024 * 1024)}MB limit for this ingestion path."
        )
    if not file_bytes.startswith(b"%PDF-"):
        raise DigitalIngestionError("File does not look like a PDF (missing %PDF- header).")
    if content_type and content_type not in ("application/pdf", "application/octet-stream"):
        raise DigitalIngestionError(f"Unsupported content type for this path: {content_type}")


def _page_offsets_from_texts(page_texts: list[str]) -> list[int]:
    """page_start_offsets[i] is the character offset, in the newline-joined
    full text, at which page i's text begins -- shared by both the digital
    (PyMuPDF) and OCR-worker text sources so page_number metadata is
    computed identically regardless of which one produced the text."""
    offsets: list[int] = []
    running = 0
    for text in page_texts:
        offsets.append(running)
        running += len(text) + 1  # +1 for the "\n" used to join pages below
    return offsets


def extract_digital_text_only(file_bytes: bytes) -> tuple[list[str], list[int]]:
    """PyMuPDF-only extraction. See module docstring for the OCR-avoidance guarantee.

    Returns (page_texts, page_start_offsets) -- see _page_offsets_from_texts.
    """
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
    except Exception as exc:
        raise DigitalIngestionError(f"Could not open file as a PDF: {exc}") from exc

    page_texts: list[str] = []
    try:
        for page in doc:
            page_texts.append(page.get_text() or "")
    finally:
        doc.close()

    return page_texts, _page_offsets_from_texts(page_texts)


def has_usable_digital_text(page_texts: list[str]) -> bool:
    return any(len(t.strip()) > MIN_DIGITAL_CHARS_PER_PAGE for t in page_texts)


def ocr_worker_configured() -> bool:
    """Whether the external AWS EasyOCR worker is enabled AND safely
    configured. Returns False (never raises) for any missing/insecure
    configuration, so the caller falls back to the existing ocr_required
    behavior rather than attempting an unsafe or broken call.
    """
    if not settings.ocr_worker_enabled:
        return False
    if not settings.ocr_worker_url or not settings.ocr_worker_token:
        logger.error(
            "ASKA_OCR_WORKER_ENABLED is true but ASKA_OCR_WORKER_URL/ASKA_OCR_WORKER_TOKEN "
            "is not set -- falling back to ocr_required."
        )
        return False
    if not settings.ocr_worker_url.startswith("https://"):
        logger.error(
            "ASKA_OCR_WORKER_ENABLED is true but ASKA_OCR_WORKER_URL does not start with "
            "https:// -- refusing to call it insecurely. Falling back to ocr_required."
        )
        return False
    return True


def run_ocr_worker(file_bytes: bytes) -> tuple[list[str], list[int]]:
    """Call the external OCR worker and return (page_texts, page_offsets) --
    the exact same shape extract_digital_text_only returns, so the result
    feeds into build_chunks_with_pages completely unchanged.

    Raises DigitalIngestionError (never OcrWorkerError) on any failure --
    this call happens strictly BEFORE anything is written to Chroma, so a
    failure here is always a plain, safe-to-retry job failure, exactly
    like any other pre-publish error on this path (see module docstring).
    """
    try:
        page_texts = call_ocr_worker(
            file_bytes,
            url=settings.ocr_worker_url,
            token=settings.ocr_worker_token,
            timeout_seconds=settings.ocr_worker_timeout_seconds,
        )
    except OcrWorkerError as exc:
        raise DigitalIngestionError(f"OCR worker failed: {exc}") from exc
    return page_texts, _page_offsets_from_texts(page_texts)


def _page_for_offset(char_start: int, page_offsets: list[int]) -> int:
    """1-indexed page number containing a given character offset in the joined text."""
    page_index = 0
    for i, start in enumerate(page_offsets):
        if start <= char_start:
            page_index = i
        else:
            break
    return page_index + 1


def build_chunks_with_pages(
    page_texts: list[str],
    page_offsets: list[int],
    *,
    chunk_size: int,
    chunk_overlap: int,
    title: str,
    source_filename: str,
) -> list[DocumentChunk]:
    full_text = "\n".join(page_texts)
    cleaned = clean_extracted_text(full_text, page_texts=page_texts)
    if not cleaned.strip():
        raise DigitalIngestionError("No usable text remained after cleaning.")

    raw_chunks = chunk_document_text(cleaned, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    chunks = [
        DocumentChunk(
            text=c.text,
            chunk_index=c.chunk_index,
            char_start=c.char_start,
            metadata={
                **(c.metadata or {}),
                "document_type": "information",
                "title": title,
                "source_document": source_filename,
                "page_number": _page_for_offset(c.char_start, page_offsets),
            },
        )
        for c in raw_chunks
    ]
    # allow_llm=False: this path must stay fast and free of per-chunk LLM
    # calls (classify_chunk's Groq fallback can take minutes and cost real
    # API usage across a multi-page document) -- rule/similarity-only
    # classification is an accepted tradeoff for the zero-cost web-dyno path.
    return enrich_chunks_with_category_metadata(
        chunks, title=title, source_document=source_filename, allow_llm=False
    )


def _mirror_page_range_metadata(chunks: list[DocumentChunk]) -> list[DocumentChunk]:
    """Mirror page_number into page_start/page_end on each chunk's metadata.

    The admin preview/validation helpers reused below (knowledge_units_for_
    extraction / chunk_preview, built for the legacy pipeline's chunker)
    read page_start/page_end; this pipeline's chunks only carry page_number
    (consumed separately by citation grounding -- see chroma_store.py /
    question_answering.py). Purely additive: page_number is left untouched.
    """
    for chunk in chunks:
        metadata = chunk.metadata or {}
        if "page_number" in metadata and "page_start" not in metadata:
            metadata["page_start"] = metadata["page_number"]
            metadata["page_end"] = metadata["page_number"]
    return chunks


def _lightweight_structured_response(text: str, *, source_document: str) -> StructuredDocumentSchema:
    """Mirrors knowledge_base_pipeline._structured_text_response. Reimplemented
    here (rather than importing that still-private helper) since this is its
    only caller in this module."""
    structured = build_structured_document(text, source_document=source_document, preview_file_path="")
    if isinstance(structured, dict):
        return StructuredDocumentSchema(fields=[], formatted_text=format_structured_document(structured) or text)
    return StructuredDocumentSchema(
        fields=[DocumentFieldSchema(**f.to_dict()) for f in structured.fields],
        formatted_text=structured.formatted_text or text,
    )


def _lightweight_detected_document_type(*, reason: str) -> dict[str, Any]:
    return {
        "document_type": "information",
        "base_document_type": "information",
        "reason": reason,
        "scores": {},
        "manual_override": False,
        "admin_selected_document_type": None,
        "parser_kind": None,
    }


def _extract_or_ocr(file_bytes: bytes) -> tuple[list[str], list[int], str]:
    """Shared by build_lightweight_preview/build_lightweight_publish: PyMuPDF
    digital extraction, falling back to the remote OCR worker exactly as
    process_ingestion_job already does. Raises DigitalIngestionError if
    digital text is insufficient and the worker is unavailable/misconfigured
    -- never silently proceeds with empty/garbage text.
    """
    page_texts, page_offsets = extract_digital_text_only(file_bytes)
    extraction_method = "pymupdf_digital"
    if not has_usable_digital_text(page_texts):
        if not ocr_worker_configured():
            raise DigitalIngestionError(
                "This document does not contain enough selectable/digital text, "
                "and the remote OCR worker is not configured. Configure the OCR "
                "worker, or use the full local/Docker admin environment, to "
                "extract this document."
            )
        page_texts, page_offsets = run_ocr_worker(file_bytes)
        extraction_method = "remote_ocr_worker"
    return page_texts, page_offsets, extraction_method


def assemble_preview_payload(
    page_texts: list[str],
    *,
    title: str,
    source_filename: str,
    extraction_method: str,
) -> dict[str, Any]:
    """Pure (page_texts -> ExtractDocumentResponse-shaped dict) assembly --
    cleaning, chunking, and the cheap preview/validation/pipeline-stage
    helpers. No network/OCR call, no Chroma write. Shared by:
      - build_lightweight_preview (digital-fast synchronous path, where
        page_texts was just extracted/OCR'd in the same call), and
      - build_preview_from_job (rebuilds the SAME shape on demand from a
        review_ready/indexing/published job's persisted extracted_pages_json
        -- see that function's docstring for why this is cheap enough to
        never need to be persisted itself).
    """
    page_offsets = _page_offsets_from_texts(page_texts)
    full_text = "\n".join(page_texts)
    cleaned = clean_extracted_text(full_text, page_texts=page_texts)

    chunks = build_chunks_with_pages(
        page_texts,
        page_offsets,
        chunk_size=settings.chunk_max_chars,
        chunk_overlap=settings.chunk_overlap,
        title=title,
        source_filename=source_filename,
    )
    chunks = _mirror_page_range_metadata(chunks)

    units = knowledge_units_for_extraction(None, chunks, kb_document_type=None)
    previews = chunk_preview(chunks)
    validation = validation_report(document_type="information", units=units, chunks=chunks)
    stages = pipeline_stages(
        extraction_method=extraction_method,
        structuring_method="generic_chunking",
        indexed=False,
    )

    return {
        "document_type": "information",
        "document_profile": "information",
        "admin_selected_document_type": None,
        "parser_document_type": None,
        "source_type": None,
        "raw_text": full_text,
        "cleaned_text": cleaned,
        "review_text": cleaned,
        "extracted_text": cleaned,
        "page_count": len(page_texts),
        "extraction_method": extraction_method,
        "structuring_method": "generic_chunking",
        "pipeline_stages": stages,
        "structured": _lightweight_structured_response(cleaned, source_document=source_filename),
        "diagnostic_report": None,
        "validation_report": validation,
        "detected_document_type": _lightweight_detected_document_type(
            reason="Lightweight cloud-safe pipeline: generic chunking, no document-type detection."
        ),
        "knowledge_units": units,
        "chunk_preview": previews,
        "kb_statistics": knowledge_base_statistics(),
    }


def build_lightweight_preview(
    file_bytes: bytes,
    *,
    filename: str | None,
    content_type: str | None,
) -> dict[str, Any]:
    """Cloud-safe equivalent of knowledge_base_pipeline.extract_document_preview
    for runtimes without local easyocr/sentence-transformers (see
    app.services.ingestion_runtime.ingestion_available). Never writes to
    Chroma. Returns a dict matching the ExtractDocumentResponse schema
    exactly, so the existing Flutter Extract & Structure UI needs no change.

    Used directly only when the whole extraction (including OCR, if
    needed) can safely run inside a single synchronous call -- i.e. never
    from the HTTP route when OCR is required (see start_extraction_job),
    only from contexts (tests, the legacy-shaped /ingest route) that accept
    a potentially slow synchronous call.
    """
    validate_pdf_bytes(file_bytes, content_type=content_type)
    title = (filename or "Untitled document").rsplit(".", 1)[0]
    source_document = filename or "Untitled document"

    page_texts, _page_offsets, extraction_method = _extract_or_ocr(file_bytes)
    return assemble_preview_payload(
        page_texts, title=title, source_filename=source_document, extraction_method=extraction_method
    )


def chunks_from_pages_or_reviewed_text(
    page_texts: list[str],
    reviewed_text: str | None,
    *,
    title: str,
    source_filename: str,
) -> list[DocumentChunk]:
    """Build chunks either from the original (possibly OCR'd) page texts, or
    from the admin's edited reviewed_text when provided -- shared by
    build_lightweight_publish (legacy-shaped, re-OCRs/re-extracts upstream of
    this) and process_indexing_job (reuses persisted page texts, never
    re-OCRs). The admin's free-text edit has no page boundaries of its own,
    so it's treated as a single page, exactly like the legacy /ingest path's
    equivalent reviewed_text override already accepts (see
    knowledge_base_pipeline._best_review_text) -- page_number/page_start/
    page_end all collapse to 1 for every resulting chunk in that case.
    """
    reviewed = (reviewed_text or "").strip()
    if reviewed:
        chunks = build_chunks_with_pages(
            [reviewed],
            [0],
            chunk_size=settings.chunk_max_chars,
            chunk_overlap=settings.chunk_overlap,
            title=title,
            source_filename=source_filename,
        )
    else:
        chunks = build_chunks_with_pages(
            page_texts,
            _page_offsets_from_texts(page_texts),
            chunk_size=settings.chunk_max_chars,
            chunk_overlap=settings.chunk_overlap,
            title=title,
            source_filename=source_filename,
        )
    return _mirror_page_range_metadata(chunks)


def build_lightweight_publish(
    file_bytes: bytes,
    *,
    filename: str | None,
    content_type: str | None,
    title: str | None = None,
    reviewed_text: str | None = None,
) -> dict[str, Any]:
    """Cloud-safe equivalent of
    knowledge_base_pipeline.ingest_document_into_knowledge_base for runtimes
    without local easyocr/sentence-transformers.

    Uses publish_new_version() -- staged add-new/verify/delete-old -- NEVER
    delete_by_source_filename()-then-add(). Returns a dict matching the
    IngestKnowledgeBaseResponse schema exactly.

    Superseded, for the admin UI, by the review_ready/indexing job split
    (start_extraction_job / process_indexing_job), which avoids re-running
    OCR here. Kept working and tested as its own independent entry point
    (e.g. for direct API use) -- see knowledge_base.py's /ingest route.
    """
    validate_pdf_bytes(file_bytes, content_type=content_type)
    display_title = title or (filename or "Untitled document").rsplit(".", 1)[0]
    source_document = filename or "Untitled document"

    page_texts, _page_offsets, extraction_method = _extract_or_ocr(file_bytes)

    chunks = chunks_from_pages_or_reviewed_text(
        page_texts, reviewed_text, title=display_title, source_filename=source_document
    )

    if not chunks:
        raise DigitalIngestionError("No chunks produced from extracted text.")

    store = get_knowledge_base_store()
    replaced_document_id = store.document_id_for_source_filename(source_document)

    new_document_id, indexed = publish_new_version(
        store,
        chunks=chunks,
        title=display_title,
        source_filename=source_document,
        replaced_document_id=replaced_document_id,
    )

    units = knowledge_units_for_extraction(None, chunks, kb_document_type=None)
    previews = chunk_preview(chunks)
    validation = validation_report(document_type="information", units=units, chunks=chunks)
    stages = pipeline_stages(
        extraction_method=extraction_method,
        structuring_method="generic_chunking",
        indexed=True,
        chunks_indexed=indexed,
    )
    index_text = (reviewed_text or "").strip() or "\n".join(page_texts)
    preview_text = index_text[:500] + ("..." if len(index_text) > 500 else "")

    return {
        "document_id": new_document_id,
        "document_type": "information",
        "source_filename": source_document,
        "title": display_title,
        "chunks_indexed": indexed,
        "page_count": len(page_texts),
        "extraction_method": extraction_method,
        "extracted_text_preview": preview_text,
        "structured": _lightweight_structured_response(index_text, source_document=source_document),
        "structuring_method": "generic_chunking",
        "pipeline_stages": stages,
        "diagnostic_report": None,
        "validation_report": validation,
        "detected_document_type": _lightweight_detected_document_type(
            reason="Lightweight cloud-safe pipeline: generic chunking, no document-type detection."
        ),
        "knowledge_units": units,
        "chunk_preview": previews,
        "kb_statistics": store.collection_statistics(),
    }


# --- review_ready / indexing job split (2026-10-05) --------------------------
#
# Splits the lightweight pipeline into two independently-triggered phases so
# a slow remote-OCR extraction never has to complete inside a single
# synchronous HTTP request (Heroku's router enforces a flat 30s timeout --
# H12 -- regardless of what the app is doing; see the 2026-10-05 production
# incident on /admin/knowledge-base/extract). Only the (possibly OCR'd) page
# texts are persisted (extracted_pages_json) -- everything else in the
# preview (cleaning, chunking, knowledge units, validation report) is cheap,
# local, pure-Python work and is rebuilt on demand by build_preview_from_job
# rather than stored.


def extracted_pages_payload(page_texts: list[str], extraction_method: str) -> str:
    return json.dumps({"pages": page_texts, "extraction_method": extraction_method})


def load_extracted_pages(job: IngestionJob) -> tuple[list[str], str]:
    if not job.extracted_pages_json:
        raise DigitalIngestionError(
            f"Job {job.id} has no persisted extraction result yet (status={job.status})."
        )
    try:
        data = json.loads(job.extracted_pages_json)
        pages = data["pages"]
        extraction_method = data.get("extraction_method", "unknown")
    except (ValueError, KeyError, TypeError) as exc:
        raise DigitalIngestionError(f"Job {job.id}'s persisted extraction result is corrupt.") from exc
    return pages, extraction_method


def build_preview_from_job(job: IngestionJob) -> dict[str, Any]:
    """Rebuilds the exact ExtractDocumentResponse-shaped payload for a
    review_ready/indexing/published job from its persisted
    extracted_pages_json -- no OCR, no Chroma access beyond the existing
    read-only knowledge_base_statistics() call inside assemble_preview_payload.
    """
    page_texts, extraction_method = load_extracted_pages(job)
    title = (job.source_filename or "Untitled document").rsplit(".", 1)[0]
    return assemble_preview_payload(
        page_texts, title=title, source_filename=job.source_filename, extraction_method=extraction_method
    )


_ACTIVE_JOB_STATUSES = ("queued", "processing", "indexing")


def start_extraction_job(
    file_bytes: bytes,
    *,
    filename: str | None,
    content_type: str | None,
    session: Session,
) -> tuple[IngestionJob, dict[str, Any] | None]:
    """Creates a brand-new IngestionJob row for this specific upload and
    either finishes synchronously (digital text sufficient -- returns
    (job, preview_dict), job.status == "review_ready") or leaves the job at
    status="processing" for the caller to dispatch
    process_extraction_preview_job(job.id) as a background task (returns
    (job, None)).

    Deliberately does NOT do sha256-based duplicate lookup/reuse of any
    existing row (unlike /ingest-digital's dedup) -- every call creates a
    fresh job explicitly for this operation, so this path can never return
    or attach an old job (including, critically, never the historical
    Student Handbook needs_reconciliation row) merely because it happens to
    share a filename or hash. The only existing-row check here is the
    single-dyno "something else is already running" concurrency guard,
    which never inspects job content/history, only current status.
    """
    validate_pdf_bytes(file_bytes, content_type=content_type)

    active = (
        session.query(IngestionJob)
        .filter(IngestionJob.status.in_(_ACTIVE_JOB_STATUSES))
        .first()
    )
    if active is not None:
        raise DigitalIngestionActiveJobError(active.id)

    job = IngestionJob(
        source_filename=filename or "untitled.pdf",
        sha256_hash=compute_sha256(file_bytes),
        status="processing",
        pdf_bytes=file_bytes,
        content_type=content_type,
        byte_size=len(file_bytes),
    )
    session.add(job)
    session.commit()
    session.refresh(job)

    try:
        page_texts, _page_offsets = extract_digital_text_only(file_bytes)
    except DigitalIngestionError as exc:
        job.status = "failed"
        job.error_message = str(exc)
        session.commit()
        raise

    job.page_count = len(page_texts)

    if not has_usable_digital_text(page_texts):
        session.commit()
        return job, None  # caller dispatches process_extraction_preview_job(job.id)

    title = (filename or "Untitled document").rsplit(".", 1)[0]
    try:
        preview = assemble_preview_payload(
            page_texts, title=title, source_filename=job.source_filename, extraction_method="pymupdf_digital"
        )
        job.extracted_pages_json = extracted_pages_payload(page_texts, "pymupdf_digital")
        job.status = "review_ready"
        session.commit()
    except DigitalIngestionError as exc:
        job.status = "failed"
        job.error_message = str(exc)
        session.commit()
        raise
    return job, preview


def process_extraction_preview_job(job_id: str) -> None:
    """Background-task entry point for the OCR-required extraction path.

    Mirrors process_ingestion_job's structure/error-handling conventions but
    STOPS at status="review_ready" -- it NEVER calls publish_new_version()
    and NEVER writes/deletes anything in Chroma. Only the (possibly OCR'd)
    page texts are persisted; cleaning/chunking/preview-building is re-done
    on demand by build_preview_from_job rather than stored here.
    """
    from app.db.session import get_session_factory

    session_factory = get_session_factory()
    session: Session = session_factory()
    try:
        job = session.get(IngestionJob, job_id)
        if job is None:
            logger.error("Extraction preview job %s vanished before processing started.", job_id)
            return

        job.status = "processing"
        job.status_detail = "Extracting digital text..."
        session.commit()

        try:
            page_texts, _page_offsets = extract_digital_text_only(job.pdf_bytes)
        except DigitalIngestionError as exc:
            job.status = "failed"
            job.error_message = str(exc)
            session.commit()
            return

        job.page_count = len(page_texts)
        extraction_method = "pymupdf_digital"

        if not has_usable_digital_text(page_texts):
            if not ocr_worker_configured():
                job.status = "failed"
                job.error_message = (
                    "This document does not contain enough selectable/digital text, "
                    "and the remote OCR worker is not configured."
                )
                session.commit()
                return
            job.status_detail = (
                "Digital text insufficient; running OCR via the external worker "
                "(this can take several minutes for scanned documents)..."
            )
            session.commit()
            try:
                page_texts, _page_offsets = run_ocr_worker(job.pdf_bytes)
            except DigitalIngestionError as exc:
                job.status = "failed"
                job.error_message = str(exc)
                session.commit()
                return
            job.page_count = len(page_texts)
            extraction_method = "remote_ocr_worker"

        job.status_detail = "Cleaning and structuring..."
        session.commit()

        title = (job.source_filename or "Untitled document").rsplit(".", 1)[0]
        try:
            # Validate the preview can actually be built (e.g. catches "no
            # usable text remained after cleaning") -- result discarded; the
            # fetch endpoint rebuilds it fresh from extracted_pages_json.
            assemble_preview_payload(
                page_texts, title=title, source_filename=job.source_filename, extraction_method=extraction_method
            )
        except DigitalIngestionError as exc:
            job.status = "failed"
            job.error_message = str(exc)
            session.commit()
            return

        job.extracted_pages_json = extracted_pages_payload(page_texts, extraction_method)
        job.status = "review_ready"
        job.status_detail = None
        session.commit()
    except Exception:
        logger.exception("Unhandled error processing extraction preview job %s", job_id)
        try:
            job = session.get(IngestionJob, job_id)
            if job is not None:
                job.status = "failed"
                job.error_message = "Unhandled internal error during extraction."
                session.commit()
        except Exception:
            logger.exception("Failed to record failure state for extraction preview job %s", job_id)
    finally:
        session.close()


def start_indexing_job(job: IngestionJob, *, session: Session) -> None:
    """Validates and transitions a review_ready job to status="indexing".

    The actual publish happens in the caller's dispatched background task
    (process_indexing_job) -- this function only performs the synchronous
    state-transition part so the HTTP route can return immediately.
    """
    if job.status != "review_ready":
        raise DigitalIngestionJobStateError(job.status)
    job.status = "indexing"
    session.commit()


def process_indexing_job(job_id: str, reviewed_text: str | None) -> None:
    """Background-task entry point for the publish phase of a review_ready
    job. Reuses the job's persisted extracted_pages_json -- NEVER re-opens
    job.pdf_bytes and NEVER calls the OCR worker again. publish_new_version()
    remains the only Chroma-write primitive, identical to process_ingestion_job's
    publish tail and build_lightweight_publish.
    """
    from app.db.session import get_session_factory

    session_factory = get_session_factory()
    session: Session = session_factory()
    try:
        job = session.get(IngestionJob, job_id)
        if job is None:
            logger.error("Indexing job %s vanished before processing started.", job_id)
            return
        if job.status != "indexing":
            logger.error(
                "process_indexing_job called for job %s with unexpected status=%s (expected indexing).",
                job_id,
                job.status,
            )
            return

        try:
            page_texts, _extraction_method = load_extracted_pages(job)
        except DigitalIngestionError as exc:
            job.status = "failed"
            job.error_message = str(exc)
            session.commit()
            return

        title = (job.source_filename or "Untitled document").rsplit(".", 1)[0]
        try:
            chunks = chunks_from_pages_or_reviewed_text(
                page_texts, reviewed_text, title=title, source_filename=job.source_filename
            )
        except DigitalIngestionError as exc:
            job.status = "failed"
            job.error_message = str(exc)
            session.commit()
            return

        if not chunks:
            job.status = "failed"
            job.error_message = "No chunks produced from extracted text."
            session.commit()
            return

        store = get_knowledge_base_store()
        replaced_document_id = store.document_id_for_source_filename(job.source_filename)

        total_chunks = len(chunks)
        job.status_detail = f"Embedding and publishing {total_chunks} chunks..."
        job.replaced_document_id = replaced_document_id
        session.commit()

        def _on_batch_complete(added_so_far: int, total: int) -> None:
            job.status_detail = f"Embedding and publishing chunk {added_so_far}/{total}..."
            session.commit()

        try:
            new_document_id, indexed = publish_new_version(
                store,
                chunks=chunks,
                title=title,
                source_filename=job.source_filename,
                replaced_document_id=replaced_document_id,
                progress_callback=_on_batch_complete,
            )
        except DigitalIngestionReconciliationError as exc:
            job.status = "needs_reconciliation"
            job.error_message = str(exc)
            session.commit()
            return
        except DigitalIngestionError as exc:
            job.status = "failed"
            job.error_message = str(exc)
            session.commit()
            return
        except Exception as exc:  # noqa: BLE001 -- last-resort safety net, mirrors process_ingestion_job
            job.status = "needs_reconciliation"
            job.error_message = (
                f"New version published but cleanup of the old version may be incomplete: {exc}"
            )
            session.commit()
            return

        job.status = "published"
        job.document_id = new_document_id
        job.chunks_indexed = indexed
        job.status_detail = None
        session.commit()
    except Exception:
        logger.exception("Unhandled error processing indexing job %s", job_id)
        try:
            job = session.get(IngestionJob, job_id)
            if job is not None:
                # needs_reconciliation (not failed): publish_new_version may
                # have partially run before the unhandled exception.
                job.status = "needs_reconciliation"
                job.error_message = "Unhandled internal error during indexing; manual verification required."
                session.commit()
        except Exception:
            logger.exception("Failed to record failure state for indexing job %s", job_id)
    finally:
        session.close()


def _rollback_orphaned_new_version(
    store: KnowledgeBaseStore, new_document_id: str, *, add_error: Exception
) -> None:
    """Best-effort cleanup of whatever batches of the new version already
    landed in Chroma before a later batch or verification step failed.

    Deletes strictly by ``new_document_id`` (never by filename -- see
    module docstring), then re-queries to CONFIRM zero chunks remain
    rather than trusting the delete call's return value alone. Raises
    DigitalIngestionReconciliationError (never silently swallows) if the
    rollback cannot be verified complete, so the caller marks the job
    needs_reconciliation -- never 'failed', which would wrongly imply it's
    simply safe to retry while an orphan may still sit in Chroma.
    """
    try:
        store.delete_by_document_id(new_document_id)
        remaining = store.document_chunk_count(new_document_id)
    except Exception as cleanup_exc:
        raise DigitalIngestionReconciliationError(
            f"Adding the new version failed ({add_error}) and automatic rollback of its "
            f"partially-added chunks also failed ({cleanup_exc}). Partially-added chunks "
            f"may remain in Chroma under document_id={new_document_id}; manual cleanup is "
            "required before retrying this document."
        ) from cleanup_exc
    if remaining != 0:
        raise DigitalIngestionReconciliationError(
            f"Adding the new version failed ({add_error}) and {remaining} chunk(s) remain "
            f"in Chroma under document_id={new_document_id} after attempted rollback. "
            "Manual cleanup is required before retrying this document."
        )


def publish_new_version(
    store: KnowledgeBaseStore,
    *,
    chunks: list[DocumentChunk],
    title: str,
    source_filename: str,
    replaced_document_id: str | None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> tuple[str, int]:
    """Add the new version in batches, verify it, then (only then) delete
    the old version.

    Returns (new_document_id, chunks_indexed).

    The add is split into sequential Chroma ``add()`` calls of at most
    CHROMA_ADD_MAX_BATCH_SIZE records each (Chroma Cloud enforces a
    per-request "Number of records" quota on the Add action, independent
    of total collection size). Unlike a single atomic add, a later batch
    can fail after earlier batches already succeeded -- so failure here
    always attempts a rollback (delete-by-new-document_id, verified down
    to zero) before raising:

    - DigitalIngestionError: the new version never became visible and the
      rollback was verified complete. Old version untouched. Safe to retry.
    - DigitalIngestionReconciliationError: the new version failed AND its
      rollback could not be verified complete (an orphan may remain under
      new_document_id), OR the new version published successfully but
      deleting the old version failed/left chunks behind. Old version is
      never touched by this function in either case -- only ever read,
      never deleted, until the new version is fully confirmed below.
    """
    new_document_id = str(uuid.uuid4())
    expected = len(chunks)

    # Everything up to and including verification is "new version not yet
    # safe". A failure here means either a clean DigitalIngestionError
    # (rollback verified complete) or a DigitalIngestionReconciliationError
    # (rollback itself could not be verified) -- never silently nothing.
    try:
        store.add_document_chunks(
            document_id=new_document_id,
            title=title,
            source_filename=source_filename,
            document_type="information",
            chunks=chunks,
            max_batch_size=CHROMA_ADD_MAX_BATCH_SIZE,
            on_batch_complete=progress_callback,
        )
        actual_count = store.document_chunk_count(new_document_id)
    except Exception as exc:
        _rollback_orphaned_new_version(store, new_document_id, add_error=exc)
        raise DigitalIngestionError(f"Adding the new version failed: {exc}") from exc

    if actual_count != expected or actual_count == 0:
        _rollback_orphaned_new_version(
            store,
            new_document_id,
            add_error=RuntimeError(f"expected {expected} chunks, found {actual_count}"),
        )
        raise DigitalIngestionError(
            f"New version verification failed: expected {expected} chunks, found {actual_count}."
        )

    # From this point on, the new version is CONFIRMED published (exact
    # expected count verified, no partial batches). Only the old-version
    # cleanup remains, and its failures map to needs_reconciliation, never
    # failed -- the new version is already live and must not be re-added.
    if replaced_document_id and replaced_document_id != new_document_id:
        try:
            store.delete_by_document_id(replaced_document_id)
            remaining_old = store.document_chunk_count(replaced_document_id)
        except Exception as exc:
            raise DigitalIngestionReconciliationError(
                f"New version document_id={new_document_id} was published and verified "
                f"({expected} chunks), but deleting the OLD version "
                f"(document_id={replaced_document_id}) failed: {exc}. The old version may "
                "still be partially present; remove it manually after inspection."
            ) from exc
        if remaining_old != 0:
            raise DigitalIngestionReconciliationError(
                f"New version document_id={new_document_id} was published and verified "
                f"({expected} chunks), but {remaining_old} chunk(s) under the OLD "
                f"document_id={replaced_document_id} remain after cleanup and must be "
                "removed manually."
            )

    return new_document_id, expected


def process_ingestion_job(job_id: str) -> None:
    """Background-task entry point. Runs on the SAME web dyno process as an
    in-process asyncio task (mirrors citation_verification_jobs.py's
    fire-and-poll pattern) -- no new dyno, no new queue service.

    Opens its own DB session: the original HTTP request's session does not
    survive past that request/response cycle, and this function is invoked
    after the response has already been returned to the client.
    """
    from app.db.session import get_session_factory

    session_factory = get_session_factory()
    session: Session = session_factory()
    try:
        job = session.get(IngestionJob, job_id)
        if job is None:
            logger.error("Ingestion job %s vanished before processing started.", job_id)
            return

        job.status = "processing"
        job.status_detail = "Extracting digital text..."
        session.commit()

        try:
            page_texts, page_offsets = extract_digital_text_only(job.pdf_bytes)
        except DigitalIngestionError as exc:
            job.status = "failed"
            job.error_message = str(exc)
            session.commit()
            return

        job.page_count = len(page_texts)

        if not has_usable_digital_text(page_texts):
            if ocr_worker_configured():
                job.status_detail = (
                    "Digital text insufficient; running OCR via the external worker "
                    "(this can take several minutes for scanned documents)..."
                )
                session.commit()
                try:
                    page_texts, page_offsets = run_ocr_worker(job.pdf_bytes)
                except DigitalIngestionError as exc:
                    # OCR runs strictly before any Chroma write -- nothing
                    # was ever published for this attempt, exactly like any
                    # other pre-publish failure on this path. Original
                    # pdf_bytes remain in the job row for the admin to retry.
                    job.status = "failed"
                    job.error_message = str(exc)
                    session.commit()
                    return
                job.page_count = len(page_texts)
            else:
                job.status = "ocr_required"
                job.status_detail = (
                    "This document does not contain enough selectable/digital text. "
                    "OCR is required but is not available on this lightweight runtime -- "
                    "use the full local/Docker admin environment to ingest this document."
                )
                session.commit()
                return

        job.status_detail = "Cleaning and chunking..."
        session.commit()

        title = (job.source_filename or "Untitled document").rsplit(".", 1)[0]
        try:
            chunks = build_chunks_with_pages(
                page_texts,
                page_offsets,
                chunk_size=settings.chunk_max_chars,
                chunk_overlap=settings.chunk_overlap,
                title=title,
                source_filename=job.source_filename,
            )
        except DigitalIngestionError as exc:
            job.status = "failed"
            job.error_message = str(exc)
            session.commit()
            return

        store = get_knowledge_base_store()
        replaced_document_id = store.document_id_for_source_filename(job.source_filename)

        total_chunks = len(chunks)
        job.status_detail = f"Embedding and publishing {total_chunks} chunks..."
        job.replaced_document_id = replaced_document_id
        session.commit()

        def _on_batch_complete(added_so_far: int, total: int) -> None:
            job.status_detail = f"Embedding and publishing chunk {added_so_far}/{total}..."
            session.commit()

        try:
            new_document_id, indexed = publish_new_version(
                store,
                chunks=chunks,
                title=title,
                source_filename=job.source_filename,
                replaced_document_id=replaced_document_id,
                progress_callback=_on_batch_complete,
            )
        except DigitalIngestionReconciliationError as exc:
            # Either a failed add's rollback could not be verified complete
            # (an orphan may remain under some new document_id -- see the
            # message for it), or the new version published but deleting
            # the old version failed/left chunks behind. Never guess or
            # retry automatically: surface for manual reconciliation.
            job.status = "needs_reconciliation"
            job.error_message = str(exc)
            session.commit()
            return
        except DigitalIngestionError as exc:
            # New version never became visible (rollback verified complete);
            # old version (if any) is untouched. Safe for the admin to retry.
            job.status = "failed"
            job.error_message = str(exc)
            session.commit()
            return
        except Exception as exc:  # noqa: BLE001 -- last-resort safety net; see module docstring
            # Should not normally be reached now that publish_new_version
            # raises typed exceptions for every known failure mode above.
            job.status = "needs_reconciliation"
            job.error_message = (
                f"New version published but cleanup of the old version may be incomplete: {exc}"
            )
            session.commit()
            return

        job.status = "published"
        job.document_id = new_document_id
        job.chunks_indexed = indexed
        job.status_detail = None
        session.commit()
    except Exception:
        logger.exception("Unhandled error processing ingestion job %s", job_id)
        try:
            job = session.get(IngestionJob, job_id)
            if job is not None:
                job.status = "failed"
                job.error_message = "Unhandled internal error during processing."
                session.commit()
        except Exception:
            logger.exception("Failed to record failure state for ingestion job %s", job_id)
    finally:
        session.close()
