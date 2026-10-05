"""Integration tests for routing OCR_REQUIRED documents through the optional
external AWS EasyOCR worker (app/services/admin/digital_ingestion.py).

Runs the REAL process_ingestion_job against the real Postgres test
database (a real IngestionJob row), but:
  - never touches real Chroma Cloud (get_knowledge_base_store is patched
    to return a FakeChromaCollection-backed store, same style as
    test_chroma_pagination_fix.py / test_digital_ingestion_batching.py).
  - never makes a real HTTP call (httpx.post is mocked, same convention
    as test_ocr_worker_client.py / test_embeddings.py).
"""

from __future__ import annotations

import logging
import uuid
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.db.safety import assert_destructive_database_ops_allowed
from app.db.session import get_session_factory
from app.models.db_models import IngestionJob
from app.services.admin.digital_ingestion import process_ingestion_job
from app.services.chroma_store import KnowledgeBaseStore

FAKE_TOKEN = "fake-ocr-worker-secret-token-xyz"
FAKE_URL = "https://aska-piyu-ocr.example.com"


# --- Fake Chroma (never touches real Chroma Cloud) --------------------------


class FakeChromaCollection:
    def __init__(self):
        self._records: dict[str, dict] = {}
        self.add_call_count = 0

    def add(self, *, ids, documents, metadatas):
        self.add_call_count += 1
        for _id, meta in zip(ids, metadatas):
            self._records[_id] = meta

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
        return {"ids": page, "metadatas": [self._records[i] for i in page]}

    def delete(self, *, ids):
        for i in ids:
            self._records.pop(i, None)

    def count(self):
        return len(self._records)


def make_fake_store() -> tuple[KnowledgeBaseStore, FakeChromaCollection]:
    collection = FakeChromaCollection()
    store = KnowledgeBaseStore.__new__(KnowledgeBaseStore)
    store._collection = collection
    return store, collection


# --- PDF fixtures ------------------------------------------------------------


def _make_digital_pdf(text: str = "This page has plenty of real selectable digital text content.") -> bytes:
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def _make_blank_scanned_pdf(n_pages: int = 1) -> bytes:
    """No text layer at all -- triggers has_usable_digital_text() == False,
    same as a real scanned page with no OCR'd text embedded."""
    import fitz

    doc = fitz.open()
    for _ in range(n_pages):
        doc.new_page()
    data = doc.tobytes()
    doc.close()
    return data


# --- Job row helpers ----------------------------------------------------------


def _insert_job(*, pdf_bytes: bytes, filename: str = None) -> str:
    session = get_session_factory()()
    try:
        job = IngestionJob(
            source_filename=filename or f"ocr_worker_test_{uuid.uuid4().hex}.pdf",
            sha256_hash=uuid.uuid4().hex + uuid.uuid4().hex,  # unique per test, not a real hash
            status="queued",
            pdf_bytes=pdf_bytes,
            byte_size=len(pdf_bytes),
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


@pytest.fixture(autouse=True)
def _cleanup_test_jobs():
    yield
    assert_destructive_database_ops_allowed()
    session = get_session_factory()()
    try:
        session.query(IngestionJob).filter(IngestionJob.source_filename.like("ocr_worker_test_%")).delete(
            synchronize_session=False
        )
        session.commit()
    finally:
        session.close()


def _completed_payload(pages: list[tuple[int, str]]):
    return {
        "status": "completed",
        "pages": [{"page": p, "text": t} for p, t in pages],
        "page_count": len(pages),
        "processing_seconds": 10.22,
        "peak_rss_mb": 1462.2,
    }


def _fake_http_response(status_code: int, json_body=None):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_body
    return response


# --- A: OCR worker disabled -> existing OCR_REQUIRED behavior unchanged ----


def test_disabled_worker_preserves_existing_ocr_required_behavior(monkeypatch):
    monkeypatch.setattr("app.services.admin.digital_ingestion.settings.ocr_worker_enabled", False)
    job_id = _insert_job(pdf_bytes=_make_blank_scanned_pdf())

    with patch("httpx.post") as mock_post:
        process_ingestion_job(job_id)

    mock_post.assert_not_called()
    job = _fetch_job(job_id)
    assert job.status == "ocr_required"


def test_misconfigured_worker_missing_token_falls_back_to_ocr_required(monkeypatch):
    monkeypatch.setattr("app.services.admin.digital_ingestion.settings.ocr_worker_enabled", True)
    monkeypatch.setattr("app.services.admin.digital_ingestion.settings.ocr_worker_url", FAKE_URL)
    monkeypatch.setattr("app.services.admin.digital_ingestion.settings.ocr_worker_token", None)
    job_id = _insert_job(pdf_bytes=_make_blank_scanned_pdf())

    with patch("httpx.post") as mock_post:
        process_ingestion_job(job_id)

    mock_post.assert_not_called()
    assert _fetch_job(job_id).status == "ocr_required"


def test_insecure_http_url_falls_back_to_ocr_required_not_called_insecurely(monkeypatch):
    monkeypatch.setattr("app.services.admin.digital_ingestion.settings.ocr_worker_enabled", True)
    monkeypatch.setattr("app.services.admin.digital_ingestion.settings.ocr_worker_url", "http://insecure.example.com")
    monkeypatch.setattr("app.services.admin.digital_ingestion.settings.ocr_worker_token", FAKE_TOKEN)
    job_id = _insert_job(pdf_bytes=_make_blank_scanned_pdf())

    with patch("httpx.post") as mock_post:
        process_ingestion_job(job_id)

    mock_post.assert_not_called()
    assert _fetch_job(job_id).status == "ocr_required"


# --- I: existing digital PDF path never calls the OCR worker ---------------


def test_sufficient_digital_text_never_calls_ocr_worker_even_when_enabled(monkeypatch):
    monkeypatch.setattr("app.services.admin.digital_ingestion.settings.ocr_worker_enabled", True)
    monkeypatch.setattr("app.services.admin.digital_ingestion.settings.ocr_worker_url", FAKE_URL)
    monkeypatch.setattr("app.services.admin.digital_ingestion.settings.ocr_worker_token", FAKE_TOKEN)

    store, collection = make_fake_store()
    job_id = _insert_job(pdf_bytes=_make_digital_pdf())

    with patch("httpx.post") as mock_post, \
         patch("app.services.admin.digital_ingestion.get_knowledge_base_store", return_value=store):
        process_ingestion_job(job_id)

    mock_post.assert_not_called()
    job = _fetch_job(job_id)
    assert job.status == "published"
    assert collection.add_call_count >= 1  # digital path still published normally


# --- B / H: successful mocked OCR -> page-aware mapping -> published -------


def test_successful_ocr_worker_response_publishes_with_page_aware_metadata(monkeypatch):
    monkeypatch.setattr("app.services.admin.digital_ingestion.settings.ocr_worker_enabled", True)
    monkeypatch.setattr("app.services.admin.digital_ingestion.settings.ocr_worker_url", FAKE_URL)
    monkeypatch.setattr("app.services.admin.digital_ingestion.settings.ocr_worker_token", FAKE_TOKEN)

    store, collection = make_fake_store()
    job_id = _insert_job(pdf_bytes=_make_blank_scanned_pdf(n_pages=2))

    # Long enough (several thousand chars) that the two pages' combined text
    # spans multiple 1200-char chunks (settings.chunk_max_chars), so the
    # page-2 boundary actually gets exercised rather than everything fitting
    # into one chunk whose char_start only ever resolves to page 1.
    ocr_text_p1 = "Office of the Registrar. " * 100
    ocr_text_p2 = "Student Affairs Office procedures. " * 100
    payload = _completed_payload([(1, ocr_text_p1), (2, ocr_text_p2)])

    with patch("httpx.post", return_value=_fake_http_response(200, payload)) as mock_post, \
         patch("app.services.admin.digital_ingestion.get_knowledge_base_store", return_value=store):
        process_ingestion_job(job_id)

    mock_post.assert_called_once()
    job = _fetch_job(job_id)
    assert job.status == "published"
    assert job.chunks_indexed and job.chunks_indexed > 0
    assert job.page_count == 2

    # Page-number traceability preserved through the existing pipeline.
    page_numbers = {m.get("page_number") for m in collection._records.values()}
    assert page_numbers == {1, 2}


# --- C/D/E/F/G: every OCR failure mode -> failed, never published ----------


@pytest.mark.parametrize(
    "setup_mock,expected_status",
    [
        ("unauthorized", "failed"),
        ("timeout", "failed"),
        ("server_error", "failed"),
        ("malformed", "failed"),
        ("empty_text", "failed"),
    ],
)
def test_every_ocr_failure_mode_fails_cleanly_without_publishing(monkeypatch, setup_mock, expected_status):
    monkeypatch.setattr("app.services.admin.digital_ingestion.settings.ocr_worker_enabled", True)
    monkeypatch.setattr("app.services.admin.digital_ingestion.settings.ocr_worker_url", FAKE_URL)
    monkeypatch.setattr("app.services.admin.digital_ingestion.settings.ocr_worker_token", FAKE_TOKEN)

    store, collection = make_fake_store()
    job_id = _insert_job(pdf_bytes=_make_blank_scanned_pdf())

    if setup_mock == "unauthorized":
        mock_kwargs = {"return_value": _fake_http_response(401)}
    elif setup_mock == "timeout":
        mock_kwargs = {"side_effect": httpx.TimeoutException("timed out")}
    elif setup_mock == "server_error":
        mock_kwargs = {"return_value": _fake_http_response(503)}
    elif setup_mock == "malformed":
        resp = MagicMock()
        resp.status_code = 200
        resp.json.side_effect = ValueError("bad json")
        mock_kwargs = {"return_value": resp}
    else:  # empty_text
        mock_kwargs = {"return_value": _fake_http_response(200, _completed_payload([(1, "   ")]))}

    with patch("httpx.post", **mock_kwargs), \
         patch("app.services.admin.digital_ingestion.get_knowledge_base_store", return_value=store):
        process_ingestion_job(job_id)

    job = _fetch_job(job_id)
    assert job.status == expected_status

    # J: no Chroma publishing of any kind was ever attempted.
    assert collection.add_call_count == 0
    assert collection.count() == 0


# --- K: token never leaked into the stored job error_message ---------------


def test_token_never_leaked_into_job_error_message(monkeypatch, caplog):
    monkeypatch.setattr("app.services.admin.digital_ingestion.settings.ocr_worker_enabled", True)
    monkeypatch.setattr("app.services.admin.digital_ingestion.settings.ocr_worker_url", FAKE_URL)
    monkeypatch.setattr("app.services.admin.digital_ingestion.settings.ocr_worker_token", FAKE_TOKEN)

    store, _collection = make_fake_store()
    job_id = _insert_job(pdf_bytes=_make_blank_scanned_pdf())

    with caplog.at_level(logging.DEBUG):
        with patch(
            "httpx.post",
            side_effect=httpx.TimeoutException(f"timed out, request=<...Authorization: Bearer {FAKE_TOKEN}...>"),
        ), patch("app.services.admin.digital_ingestion.get_knowledge_base_store", return_value=store):
            process_ingestion_job(job_id)

    job = _fetch_job(job_id)
    assert job.status == "failed"
    assert FAKE_TOKEN not in (job.error_message or "")
    for record in caplog.records:
        assert FAKE_TOKEN not in record.getMessage()
        if record.exc_text:
            assert FAKE_TOKEN not in record.exc_text
