"""Tests for linking the Heroku lightweight digital-ingestion publish path
to a durable ``source_documents`` row (2026-10-07).

Root cause this closes: ``digital_ingestion.py``'s ``publish_new_version``
generates a fresh Chroma ``document_id`` but, before this change, never
created a matching ``source_documents`` row -- any citation for a document
published through this path could never resolve to its original PDF (see
``app/routes/documents.py``'s 404 "Source document not found"). This is
distinct from (and in addition to) the ephemeral-local-disk issue fixed by
``SourceDocument.pdf_data`` (see ``test_document_citations.py``).

Never touches a real Chroma client -- get_knowledge_base_store is patched
to a FakeChromaCollection, matching every other digital-ingestion test file
in this suite (see test_digital_ingestion_batching.py).
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import patch

import pytest

from app.db.safety import assert_destructive_database_ops_allowed
from app.db.session import get_session_factory
from app.models.db_models import IngestionJob, SourceDocument
from app.services.admin.digital_ingestion import (
    extracted_pages_payload,
    process_ingestion_job,
    process_indexing_job,
)
from app.services.chroma_store import KnowledgeBaseStore
from app.services.document_storage import resolve_stored_path

_FILENAME_PREFIX = "source_persistence_test_"


class FakeChromaCollection:
    def __init__(self) -> None:
        self._records: dict[str, dict] = {}
        self._documents: dict[str, str] = {}
        self.add_call_count = 0

    def add(self, *, ids, documents, metadatas):
        self.add_call_count += 1
        for _id, doc, meta in zip(ids, documents, metadatas):
            self._records[_id] = meta
            self._documents[_id] = doc

    def get(self, where=None, include=None, limit=None, offset=0, ids=None):
        if ids is not None:
            matched = [i for i in ids if i in self._records]
        elif where and "document_id" in where:
            wanted = where["document_id"]
            matched = [i for i, m in self._records.items() if m.get("document_id") == wanted]
        elif where and "source_filename" in where:
            wanted = where["source_filename"]
            matched = [i for i, m in self._records.items() if m.get("source_filename") == wanted]
        else:
            matched = list(self._records.keys())
        page = matched[offset:] if limit is None else matched[offset : offset + limit]
        result = {"ids": page}
        if include and "metadatas" in include:
            result["metadatas"] = [self._records[i] for i in page]
        if include and "documents" in include:
            result["documents"] = [self._documents[i] for i in page]
        return result

    def delete(self, *, ids):
        for i in ids:
            self._records.pop(i, None)
            self._documents.pop(i, None)

    def count(self):
        return len(self._records)


def make_store() -> tuple[KnowledgeBaseStore, FakeChromaCollection]:
    collection = FakeChromaCollection()
    store = KnowledgeBaseStore.__new__(KnowledgeBaseStore)
    store._collection = collection
    return store, collection


def _make_digital_pdf(text: str) -> bytes:
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def _insert_job(
    *,
    pdf_bytes: bytes,
    filename: str,
    status: str,
    extracted_pages_json: str | None = None,
) -> str:
    session = get_session_factory()()
    try:
        job = IngestionJob(
            source_filename=filename,
            sha256_hash=uuid.uuid4().hex + uuid.uuid4().hex,
            status=status,
            pdf_bytes=pdf_bytes,
            content_type="application/pdf",
            byte_size=len(pdf_bytes),
            extracted_pages_json=extracted_pages_json,
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        return job.id
    finally:
        session.close()


def _fetch_job(job_id: str) -> IngestionJob:
    session = get_session_factory()()
    try:
        job = session.get(IngestionJob, job_id)
        session.expunge(job)
        return job
    finally:
        session.close()


def _fetch_source_document(doc_id: str) -> SourceDocument | None:
    session = get_session_factory()()
    try:
        row = session.get(SourceDocument, doc_id)
        if row is not None:
            session.expunge(row)
        return row
    finally:
        session.close()


@pytest.fixture(autouse=True)
def _isolate_store(monkeypatch):
    store, collection = make_store()
    monkeypatch.setattr(
        "app.services.admin.digital_ingestion.get_knowledge_base_store", lambda: store
    )
    yield store, collection


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


# --- H: Chroma document_id == SourceDocument.id -----------------------------


def test_published_document_id_matches_source_documents_id(_isolate_store):
    _store, collection = _isolate_store
    pdf_bytes = _make_digital_pdf("Enrollment procedures for new students. " * 20)
    filename = f"{_FILENAME_PREFIX}handbook.pdf"
    job_id = _insert_job(pdf_bytes=pdf_bytes, filename=filename, status="queued")

    process_ingestion_job(job_id)

    job = _fetch_job(job_id)
    assert job.status == "published"
    assert job.document_id

    source_row = _fetch_source_document(job.document_id)
    assert source_row is not None, "publish must create a source_documents row under the SAME id"
    assert source_row.id == job.document_id
    assert source_row.pdf_data == pdf_bytes
    assert source_row.original_filename == filename

    # And the PDF is actually servable under that id (local cache file).
    path = resolve_stored_path(source_row.stored_file_path)
    assert path.is_file()
    assert path.read_bytes() == pdf_bytes

    # Confirm the Chroma side really used the same document_id.
    chroma_doc_ids = {m.get("document_id") for m in collection._records.values()}
    assert chroma_doc_ids == {job.document_id}


def test_indexing_job_path_also_links_source_document(_isolate_store):
    """Same linkage, via the review_ready -> indexing split path."""
    pdf_bytes = _make_digital_pdf("Office of the Registrar enrollment procedures. " * 20)
    filename = f"{_FILENAME_PREFIX}handbook_split.pdf"
    pages_json = extracted_pages_payload(
        ["Office of the Registrar enrollment procedures. " * 20], "digital"
    )
    job_id = _insert_job(
        pdf_bytes=pdf_bytes,
        filename=filename,
        status="indexing",
        extracted_pages_json=pages_json,
    )

    process_indexing_job(job_id, reviewed_text=None)

    job = _fetch_job(job_id)
    assert job.status == "published"
    source_row = _fetch_source_document(job.document_id)
    assert source_row is not None
    assert source_row.id == job.document_id
    assert source_row.pdf_data == pdf_bytes


# --- I: source persistence does not change chunk text or metadata ----------


def test_source_persistence_does_not_change_chunk_text_or_metadata(_isolate_store):
    """Adding the persist_source_pdf_for_published_version call must be
    strictly additive: the Chroma chunk text/metadata written for a
    publish must be identical to what publish_new_version alone would
    have written (no new/renamed Chroma fields, no text mutation)."""
    _store, collection = _isolate_store
    text = "Validation of Subjects requires payment of outstanding fees. " * 15
    pdf_bytes = _make_digital_pdf(text)
    filename = f"{_FILENAME_PREFIX}validation.pdf"
    job_id = _insert_job(pdf_bytes=pdf_bytes, filename=filename, status="queued")

    process_ingestion_job(job_id)

    job = _fetch_job(job_id)
    assert job.status == "published"
    assert collection.count() == job.chunks_indexed

    expected_core_keys = {"document_id", "title", "source_filename", "document_type", "chunk_index", "chunk_id"}
    for chunk_id, meta in collection._records.items():
        assert expected_core_keys.issubset(meta.keys())
        assert meta["document_id"] == job.document_id
        assert meta["source_filename"] == filename
        # pdf_data/source persistence is Postgres-only -- it must never leak
        # into Chroma chunk metadata.
        assert "pdf_data" not in meta
        assert "pdf_bytes" not in meta

    combined_text = " ".join(collection._documents.values())
    assert "Validation of Subjects" in combined_text
    assert "outstanding fees" in combined_text


# --- Failure behavior: never silently publish an unresolvable citation -----


def test_source_persistence_failure_sets_needs_reconciliation_and_preserves_chroma_data(
    _isolate_store,
):
    _store, collection = _isolate_store
    pdf_bytes = _make_digital_pdf("Scholarship application requirements. " * 20)
    filename = f"{_FILENAME_PREFIX}scholarship.pdf"
    job_id = _insert_job(pdf_bytes=pdf_bytes, filename=filename, status="queued")

    with patch(
        "app.services.admin.digital_ingestion.persist_source_pdf_for_published_version",
        side_effect=RuntimeError("simulated Postgres write failure"),
    ):
        process_ingestion_job(job_id)

    job = _fetch_job(job_id)
    # Never "published" (would silently claim a working citation) and never
    # "failed" (the Chroma chunks ARE live) -- needs_reconciliation is the
    # correct, existing status for "new version live, something else about
    # this publish needs manual attention".
    assert job.status == "needs_reconciliation"
    assert job.document_id  # pointer to the live Chroma data is preserved
    assert job.chunks_indexed and job.chunks_indexed > 0
    assert "chroma publish succeeded" in (job.error_message or "").lower()
    assert "simulated postgres write failure" in (job.error_message or "").lower()

    # The already-verified Chroma chunks must NOT be rolled back.
    assert collection.count() == job.chunks_indexed
    chroma_doc_ids = {m.get("document_id") for m in collection._records.values()}
    assert chroma_doc_ids == {job.document_id}

    # And, correctly, no source_documents row exists for this failed link.
    assert _fetch_source_document(job.document_id) is None
