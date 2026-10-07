"""Tests for the local-only source_documents.pdf_data backfill utility
(scripts/backfill_source_document_pdf.py, 2026-10-07).

This utility is never run against production by this suite or by any
automated workflow -- these tests only exercise it against the isolated
test database. Dry-run is the default; "apply" is opt-in and scoped to
rows with an unambiguous byte-identical match.
"""

from __future__ import annotations

import uuid

import pytest

from app.db.safety import assert_destructive_database_ops_allowed
from app.db.session import get_session_factory
from app.models.db_models import IngestionJob, SourceDocument
from scripts.backfill_source_document_pdf import apply_backfill, find_backfill_candidates

_FILENAME_PREFIX = "backfill_test_"


def _make_source_document_row(
    session, *, filename: str, byte_size: int | None, pdf_data: bytes | None = None
) -> SourceDocument:
    doc_id = str(uuid.uuid4())
    row = SourceDocument(
        id=doc_id,
        original_filename=filename,
        stored_file_path=f"{doc_id}/{filename}",  # intentionally never written to disk
        byte_size=byte_size,
        pdf_data=pdf_data,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def _make_ingestion_job(session, *, filename: str, pdf_bytes: bytes) -> IngestionJob:
    job = IngestionJob(
        source_filename=filename,
        sha256_hash=uuid.uuid4().hex + uuid.uuid4().hex,
        status="published",
        pdf_bytes=pdf_bytes,
        content_type="application/pdf",
        byte_size=len(pdf_bytes),
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


@pytest.fixture(autouse=True)
def _cleanup_test_rows():
    yield
    assert_destructive_database_ops_allowed()
    session = get_session_factory()()
    try:
        session.query(IngestionJob).filter(
            IngestionJob.source_filename.like(f"{_FILENAME_PREFIX}%")
        ).delete(synchronize_session=False)
        session.query(SourceDocument).filter(
            SourceDocument.original_filename.like(f"{_FILENAME_PREFIX}%")
        ).delete(synchronize_session=False)
        session.commit()
    finally:
        session.close()


# --- K: dry-run performs ZERO writes ----------------------------------------


def test_dry_run_default_performs_zero_writes():
    session = get_session_factory()()
    try:
        pdf_bytes = b"%PDF-1.4 unique-recoverable-content"
        row = _make_source_document_row(
            session, filename=f"{_FILENAME_PREFIX}handbook.pdf", byte_size=len(pdf_bytes)
        )
        _make_ingestion_job(session, filename=f"{_FILENAME_PREFIX}handbook.pdf", pdf_bytes=pdf_bytes)

        results = find_backfill_candidates(session)
        matches = [r for r in results if r.source_document_id == row.id]
        assert len(matches) == 1
        assert matches[0].status == "matched"

        # find_backfill_candidates is read-only by itself -- confirm the row
        # is untouched without ever calling apply_backfill.
        session.expire_all()
        reloaded = session.get(SourceDocument, row.id)
        assert reloaded.pdf_data is None
    finally:
        session.close()


# --- L: ambiguous backfill candidate is skipped -----------------------------


def test_ambiguous_candidate_with_distinct_content_is_skipped():
    session = get_session_factory()()
    try:
        row = _make_source_document_row(
            session, filename=f"{_FILENAME_PREFIX}charter.pdf", byte_size=None
        )
        # Two jobs, same filename, but genuinely DIFFERENT content -- must
        # never guess which one is correct.
        _make_ingestion_job(
            session, filename=f"{_FILENAME_PREFIX}charter.pdf", pdf_bytes=b"%PDF-1.4 version-one"
        )
        _make_ingestion_job(
            session, filename=f"{_FILENAME_PREFIX}charter.pdf", pdf_bytes=b"%PDF-1.4 version-two-different"
        )

        results = find_backfill_candidates(session)
        match = next(r for r in results if r.source_document_id == row.id)
        assert match.status == "skipped_ambiguous"
        assert match.matched_job_id is None

        written = apply_backfill(session, results)
        assert written == 0
        session.expire_all()
        assert session.get(SourceDocument, row.id).pdf_data is None
    finally:
        session.close()


def test_no_candidate_is_skipped_and_reported():
    session = get_session_factory()()
    try:
        row = _make_source_document_row(
            session, filename=f"{_FILENAME_PREFIX}orphan.pdf", byte_size=12345
        )
        results = find_backfill_candidates(session)
        match = next(r for r in results if r.source_document_id == row.id)
        assert match.status == "skipped_no_candidate"
        assert match.matched_job_id is None
    finally:
        session.close()


# --- M: unique filename + byte-size candidate is selected correctly --------


def test_unique_filename_and_byte_size_candidate_is_applied_correctly():
    session = get_session_factory()()
    try:
        pdf_bytes = b"%PDF-1.4 the-one-true-recoverable-copy"
        row = _make_source_document_row(
            session, filename=f"{_FILENAME_PREFIX}faculty.pdf", byte_size=len(pdf_bytes)
        )
        # A same-filename job with a DIFFERENT byte_size must be excluded by
        # the byte_size filter even though the filename matches.
        _make_ingestion_job(
            session,
            filename=f"{_FILENAME_PREFIX}faculty.pdf",
            pdf_bytes=b"%PDF-1.4 wrong-size-decoy-content-longer",
        )
        _make_ingestion_job(
            session, filename=f"{_FILENAME_PREFIX}faculty.pdf", pdf_bytes=pdf_bytes
        )

        results = find_backfill_candidates(session)
        match = next(r for r in results if r.source_document_id == row.id)
        assert match.status == "matched"

        written = apply_backfill(session, results)
        assert written == 1

        session.expire_all()
        reloaded = session.get(SourceDocument, row.id)
        assert reloaded.pdf_data == pdf_bytes
    finally:
        session.close()


def test_multiple_byte_identical_candidates_are_not_treated_as_ambiguous():
    """Two historical job rows with the SAME content (e.g. a retried
    upload) must still produce a confident match -- ambiguity is about
    distinct CONTENT, never merely about row count."""
    session = get_session_factory()()
    try:
        pdf_bytes = b"%PDF-1.4 retried-upload-identical-bytes"
        row = _make_source_document_row(
            session, filename=f"{_FILENAME_PREFIX}retry.pdf", byte_size=len(pdf_bytes)
        )
        _make_ingestion_job(session, filename=f"{_FILENAME_PREFIX}retry.pdf", pdf_bytes=pdf_bytes)
        _make_ingestion_job(session, filename=f"{_FILENAME_PREFIX}retry.pdf", pdf_bytes=pdf_bytes)

        results = find_backfill_candidates(session)
        match = next(r for r in results if r.source_document_id == row.id)
        assert match.status == "matched"

        written = apply_backfill(session, results)
        assert written == 1
        session.expire_all()
        assert session.get(SourceDocument, row.id).pdf_data == pdf_bytes
    finally:
        session.close()


def test_already_ok_rows_are_never_modified():
    """A row that already has pdf_data (or a valid local file) must be
    reported as already_ok and never touched, even if a differing
    candidate job exists."""
    session = get_session_factory()()
    try:
        existing_bytes = b"%PDF-1.4 already-durable"
        row = _make_source_document_row(
            session,
            filename=f"{_FILENAME_PREFIX}already_ok.pdf",
            byte_size=None,
            pdf_data=existing_bytes,
        )
        _make_ingestion_job(
            session,
            filename=f"{_FILENAME_PREFIX}already_ok.pdf",
            pdf_bytes=b"%PDF-1.4 some-other-job-content",
        )

        results = find_backfill_candidates(session)
        match = next(r for r in results if r.source_document_id == row.id)
        assert match.status == "already_ok"

        written = apply_backfill(session, results)
        assert written == 0
        session.expire_all()
        assert session.get(SourceDocument, row.id).pdf_data == existing_bytes
    finally:
        session.close()
