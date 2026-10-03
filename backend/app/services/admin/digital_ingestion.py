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
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

import fitz  # PyMuPDF

from sqlalchemy.orm import Session

from app.config import settings
from app.models.db_models import IngestionJob
from app.services.chroma_store import KnowledgeBaseStore, get_knowledge_base_store
from app.services.chunking import DocumentChunk, chunk_document_text
from app.services.knowledge_taxonomy import enrich_chunks_with_category_metadata
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


def extract_digital_text_only(file_bytes: bytes) -> tuple[list[str], list[int]]:
    """PyMuPDF-only extraction. See module docstring for the OCR-avoidance guarantee.

    Returns (page_texts, page_start_offsets): page_start_offsets[i] is the
    character offset, in the newline-joined full text, at which page i's
    text begins -- used later to recover each chunk's starting page number.
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

    offsets: list[int] = []
    running = 0
    for text in page_texts:
        offsets.append(running)
        running += len(text) + 1  # +1 for the "\n" used to join pages below

    return page_texts, offsets


def has_usable_digital_text(page_texts: list[str]) -> bool:
    return any(len(t.strip()) > MIN_DIGITAL_CHARS_PER_PAGE for t in page_texts)


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
