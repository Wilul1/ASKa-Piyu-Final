"""Focused tests for the review_ready/indexing job split (2026-10-05):

Extract & Structure (digital-fast-path OR background OCR) -> review_ready
-> Index for Chatbot Retrieval (background publish, reusing persisted
page texts, never re-OCRing) -> published/failed/needs_reconciliation.

See app/services/admin/digital_ingestion.py:
  start_extraction_job, process_extraction_preview_job,
  build_preview_from_job, start_indexing_job, process_indexing_job.

Safety, matching every other test file in this suite:
  - never touches a real Chroma client (local or cloud) -- get_knowledge_
    base_store is patched everywhere it's reachable (digital_ingestion.py
    directly, and knowledge_base_pipeline.py's own import, used by
    kb_statistics()/collection_statistics() calls inside preview assembly).
  - never makes a real HTTP call -- httpx.post is mocked for every OCR path.
  - TestClient runs FastAPI BackgroundTasks synchronously before .post()
    returns (same documented behavior relied on by test_ingest_digital_
    retry.py), so "the background job already finished" can be asserted
    immediately after each request in these tests.
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.db.safety import assert_destructive_database_ops_allowed
from app.db.session import get_session_factory
from app.main import app
from app.models.db_models import IngestionJob
from app.services.admin.digital_ingestion import (
    DigitalIngestionError,
    DigitalIngestionReconciliationError,
)
from app.services.chroma_store import KnowledgeBaseStore

ADMIN_HEADERS = {"X-Admin-Key": "test-admin-key"}
FAKE_TOKEN = "fake-ocr-worker-secret-token-xyz"
FAKE_URL = "https://aska-piyu-ocr.example.com"


# --- Fake Chroma (never touches a real client) ------------------------------


class FakeChromaCollection:
    def __init__(self):
        self._records: dict[str, dict] = {}
        self._documents: dict[str, str] = {}
        self.add_call_count = 0
        self.delete_call_count = 0

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
        return {"ids": page, "metadatas": [self._records[i] for i in page]}

    def delete(self, *, ids):
        self.delete_call_count += 1
        for i in ids:
            self._records.pop(i, None)

    def count(self):
        return len(self._records)


def make_fake_store() -> tuple[KnowledgeBaseStore, FakeChromaCollection]:
    collection = FakeChromaCollection()
    store = KnowledgeBaseStore.__new__(KnowledgeBaseStore)
    store._collection = collection
    return store, collection


def patched_store(store):
    """Patches get_knowledge_base_store everywhere this flow reaches it:
    directly in digital_ingestion.py (publish), and via knowledge_base_
    pipeline.py's own import (used by kb_statistics() inside every preview
    assembly, including the pure Extract path)."""
    return (
        patch("app.services.admin.digital_ingestion.get_knowledge_base_store", return_value=store),
        patch("app.services.admin.knowledge_base_pipeline.get_knowledge_base_store", return_value=store),
    )


# --- PDF fixtures -------------------------------------------------------------


def _make_digital_pdf(text: str = "This page has plenty of real selectable digital text content.") -> bytes:
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def _make_multi_page_digital_pdf(texts: list[str]) -> bytes:
    import fitz

    doc = fitz.open()
    for text in texts:
        page = doc.new_page()
        page.insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def _make_blank_scanned_pdf(n_pages: int = 1) -> bytes:
    import fitz

    doc = fitz.open()
    for _ in range(n_pages):
        doc.new_page()
    data = doc.tobytes()
    doc.close()
    return data


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


# --- Job row helpers -----------------------------------------------------------


def _fetch_job(job_id: str) -> IngestionJob:
    session = get_session_factory()()
    try:
        job = session.get(IngestionJob, job_id)
        session.expunge(job)
        return job
    finally:
        session.close()


def _insert_job(*, source_filename: str, status: str) -> str:
    session = get_session_factory()()
    try:
        job = IngestionJob(
            source_filename=source_filename,
            sha256_hash=uuid.uuid4().hex + uuid.uuid4().hex,
            status=status,
            pdf_bytes=b"x",
            byte_size=1,
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        return job.id
    finally:
        session.close()


@pytest.fixture(autouse=True)
def _admin_key(monkeypatch):
    monkeypatch.setattr("app.routes.admin.knowledge_base.settings.admin_api_key", "test-admin-key")


@pytest.fixture(autouse=True)
def _ingestion_unavailable(monkeypatch):
    """Forces the lightweight/cloud-safe branch for every test in this file."""
    monkeypatch.setattr("app.routes.admin.knowledge_base.ingestion_available", lambda: False)


@pytest.fixture(autouse=True)
def _cleanup_test_jobs():
    yield
    assert_destructive_database_ops_allowed()
    session = get_session_factory()()
    try:
        session.query(IngestionJob).filter(IngestionJob.source_filename.like("review_index_test_%")).delete(
            synchronize_session=False
        )
        session.commit()
    finally:
        session.close()


client = TestClient(app)


def _extract(pdf_bytes: bytes, filename: str):
    return client.post(
        "/admin/knowledge-base/extract",
        headers=ADMIN_HEADERS,
        files={"file": (filename, pdf_bytes, "application/pdf")},
    )


def _index(job_id: str, reviewed_text: str | None = None):
    return client.post(
        f"/admin/knowledge-base/jobs/{job_id}/index",
        headers=ADMIN_HEADERS,
        json={"reviewed_text": reviewed_text},
    )


# --- 8/9/10/11: scanned PDF Extract returns job_id quickly, OCR persisted ----


def test_scanned_pdf_extract_returns_job_id_and_processing_stub(monkeypatch):
    monkeypatch.setattr("app.services.admin.digital_ingestion.settings.ocr_worker_enabled", True)
    monkeypatch.setattr("app.services.admin.digital_ingestion.settings.ocr_worker_url", FAKE_URL)
    monkeypatch.setattr("app.services.admin.digital_ingestion.settings.ocr_worker_token", FAKE_TOKEN)
    store, _collection = make_fake_store()
    p1, p2 = patched_store(store)
    payload = _completed_payload([(1, "Scanned registrar text. " * 50)])

    with p1, p2, patch("httpx.post", return_value=_fake_http_response(200, payload)) as mock_post:
        response = _extract(_make_blank_scanned_pdf(), "review_index_test_scanned.pdf")

    assert response.status_code == 200
    data = response.json()
    assert data["job_id"]
    mock_post.assert_called_once()  # background task already ran under TestClient

    job = _fetch_job(data["job_id"])
    assert job.status == "review_ready"
    assert job.extracted_pages_json
    pages = json.loads(job.extracted_pages_json)
    assert pages["extraction_method"] == "remote_ocr_worker"
    assert "registrar" in pages["pages"][0].lower()


# --- 12/13: preview job never publishes, never writes to Chroma -------------


def test_extract_never_calls_publish_new_version_digital_or_ocr(monkeypatch):
    monkeypatch.setattr("app.services.admin.digital_ingestion.settings.ocr_worker_enabled", True)
    monkeypatch.setattr("app.services.admin.digital_ingestion.settings.ocr_worker_url", FAKE_URL)
    monkeypatch.setattr("app.services.admin.digital_ingestion.settings.ocr_worker_token", FAKE_TOKEN)
    store, collection = make_fake_store()
    p1, p2 = patched_store(store)
    payload = _completed_payload([(1, "Scanned registrar text. " * 50)])

    with p1, p2, patch("httpx.post", return_value=_fake_http_response(200, payload)), patch(
        "app.services.admin.digital_ingestion.publish_new_version"
    ) as mock_publish:
        digital_response = _extract(_make_digital_pdf(), "review_index_test_digital.pdf")
        ocr_response = _extract(_make_blank_scanned_pdf(), "review_index_test_ocr.pdf")

    assert digital_response.status_code == 200
    assert ocr_response.status_code == 200
    mock_publish.assert_not_called()
    assert collection.add_call_count == 0
    assert collection.delete_call_count == 0
    assert collection.count() == 0


# --- 14: preview-fetch rebuilds the normal Extract response shape -----------


def test_job_preview_endpoint_rebuilds_extract_response_shape(monkeypatch):
    monkeypatch.setattr("app.services.admin.digital_ingestion.settings.ocr_worker_enabled", True)
    monkeypatch.setattr("app.services.admin.digital_ingestion.settings.ocr_worker_url", FAKE_URL)
    monkeypatch.setattr("app.services.admin.digital_ingestion.settings.ocr_worker_token", FAKE_TOKEN)
    store, _collection = make_fake_store()
    p1, p2 = patched_store(store)
    payload = _completed_payload([(1, "Scanned registrar text about enrollment. " * 30)])

    with p1, p2, patch("httpx.post", return_value=_fake_http_response(200, payload)):
        extract_response = _extract(_make_blank_scanned_pdf(), "review_index_test_preview_fetch.pdf")
        job_id = extract_response.json()["job_id"]

        preview_response = client.get(
            f"/admin/knowledge-base/jobs/{job_id}/preview", headers=ADMIN_HEADERS
        )

    assert preview_response.status_code == 200
    data = preview_response.json()
    assert data["job_id"] == job_id
    assert data["extraction_method"] == "remote_ocr_worker"
    assert "enrollment" in data["review_text"].lower()
    assert "knowledge_units" in data and isinstance(data["knowledge_units"], list)
    assert "chunk_preview" in data and isinstance(data["chunk_preview"], list)
    assert "validation_report" in data


def test_job_preview_endpoint_404s_for_unknown_job():
    response = client.get(
        f"/admin/knowledge-base/jobs/{uuid.uuid4()}/preview", headers=ADMIN_HEADERS
    )
    assert response.status_code == 404


def test_job_preview_endpoint_409s_before_review_ready():
    job_id = _insert_job(source_filename="review_index_test_not_ready.pdf", status="processing")
    response = client.get(f"/admin/knowledge-base/jobs/{job_id}/preview", headers=ADMIN_HEADERS)
    assert response.status_code == 409


# --- 16/17: Index uses persisted pages, preserves page-aware metadata -------


def test_index_uses_persisted_pages_and_preserves_page_metadata(monkeypatch):
    monkeypatch.setattr("app.services.admin.digital_ingestion.settings.chunk_max_chars", 50)
    monkeypatch.setattr("app.services.admin.digital_ingestion.settings.chunk_overlap", 0)
    store, collection = make_fake_store()
    p1, p2 = patched_store(store)
    texts = ["Office of the Registrar. " * 100, "Student Affairs Office procedures. " * 100]

    with p1, p2, patch("httpx.post") as mock_post:
        extract_response = _extract(
            _make_multi_page_digital_pdf(texts), "review_index_test_multi_page.pdf"
        )
        job_id = extract_response.json()["job_id"]

        index_response = _index(job_id)

    mock_post.assert_not_called()  # digital path: OCR never involved at all
    assert index_response.status_code == 200
    assert index_response.json()["status"] == "indexing"

    job = _fetch_job(job_id)
    assert job.status == "published"
    assert job.chunks_indexed and job.chunks_indexed > 0

    page_numbers = {m.get("page_number") for m in collection._records.values()}
    assert page_numbers == {1, 2}


# --- 18: Index with reviewed_text uses the override -------------------------


def test_index_with_reviewed_text_uses_the_override():
    store, collection = make_fake_store()
    p1, p2 = patched_store(store)

    with p1, p2, patch("httpx.post") as mock_post:
        extract_response = _extract(
            _make_digital_pdf("Original text about parking permits."),
            "review_index_test_reviewed_override.pdf",
        )
        job_id = extract_response.json()["job_id"]

        index_response = _index(job_id, reviewed_text="Admin-edited text about library hours.")

    mock_post.assert_not_called()
    assert index_response.status_code == 200
    job = _fetch_job(job_id)
    assert job.status == "published"

    combined = " ".join(collection._documents.values()).lower()
    assert "library hours" in combined
    assert "parking permits" not in combined


# --- 19: Index never calls OCR again -----------------------------------------


def test_index_never_calls_ocr_worker_again(monkeypatch):
    monkeypatch.setattr("app.services.admin.digital_ingestion.settings.ocr_worker_enabled", True)
    monkeypatch.setattr("app.services.admin.digital_ingestion.settings.ocr_worker_url", FAKE_URL)
    monkeypatch.setattr("app.services.admin.digital_ingestion.settings.ocr_worker_token", FAKE_TOKEN)
    store, _collection = make_fake_store()
    p1, p2 = patched_store(store)
    payload = _completed_payload([(1, "Scanned registrar text. " * 50)])

    with p1, p2, patch("httpx.post", return_value=_fake_http_response(200, payload)) as mock_post:
        extract_response = _extract(_make_blank_scanned_pdf(), "review_index_test_ocr_once.pdf")
        job_id = extract_response.json()["job_id"]
        assert mock_post.call_count == 1  # OCR happened exactly once, during Extract

        index_response = _index(job_id)
        assert index_response.status_code == 200
        # NO additional OCR call during Index -- still exactly one call total.
        assert mock_post.call_count == 1

    job = _fetch_job(job_id)
    assert job.status == "published"


# --- 20: Index calls publish_new_version as its only Chroma write path -----


def test_index_calls_publish_new_version_as_only_write_path():
    store, collection = make_fake_store()
    p1, p2 = patched_store(store)

    from app.services.admin.digital_ingestion import publish_new_version as real_publish_new_version

    with p1, p2, patch("httpx.post") as mock_post, patch(
        "app.services.admin.digital_ingestion.publish_new_version", wraps=real_publish_new_version
    ) as mock_publish:
        extract_response = _extract(
            _make_digital_pdf("Enrollment procedures for new students."),
            "review_index_test_publish_path.pdf",
        )
        job_id = extract_response.json()["job_id"]
        _index(job_id)

    mock_post.assert_not_called()
    mock_publish.assert_called_once()
    assert collection.add_call_count >= 1
    assert collection.delete_call_count == 0  # first-ever publish: nothing to delete


# --- 21: Index failure preserves existing published Chroma data ------------


def test_index_failure_leaves_existing_published_version_intact():
    store, collection = make_fake_store()
    p1, p2 = patched_store(store)

    # Simulate an existing published version for this source_filename.
    collection.add(
        ids=["old-chunk-1"],
        documents=["old content"],
        metadatas=[
            {
                "document_id": "old-doc-id",
                "source_filename": "review_index_test_failure.pdf",
            }
        ],
    )

    with p1, p2, patch("httpx.post") as mock_post:
        extract_response = _extract(
            _make_digital_pdf("New replacement content."), "review_index_test_failure.pdf"
        )
        job_id = extract_response.json()["job_id"]

        with patch(
            "app.services.admin.digital_ingestion.publish_new_version",
            side_effect=DigitalIngestionError("Adding the new version failed: simulated failure"),
        ):
            index_response = _index(job_id)

    mock_post.assert_not_called()
    assert index_response.status_code == 200  # the HTTP call itself just kicks off a background task
    job = _fetch_job(job_id)
    assert job.status == "failed"
    assert collection.get(where={"document_id": "old-doc-id"})["ids"] == ["old-chunk-1"]


# --- 22: needs_reconciliation behavior remains intact ------------------------


def test_index_reconciliation_error_sets_needs_reconciliation():
    store, _collection = make_fake_store()
    p1, p2 = patched_store(store)

    with p1, p2, patch("httpx.post") as mock_post:
        extract_response = _extract(
            _make_digital_pdf("Some content for reconciliation test."),
            "review_index_test_reconciliation.pdf",
        )
        job_id = extract_response.json()["job_id"]

        with patch(
            "app.services.admin.digital_ingestion.publish_new_version",
            side_effect=DigitalIngestionReconciliationError("cleanup of old version failed"),
        ):
            _index(job_id)

    mock_post.assert_not_called()
    job = _fetch_job(job_id)
    assert job.status == "needs_reconciliation"
    assert "cleanup" in (job.error_message or "").lower()


def test_index_409s_when_not_review_ready():
    job_id = _insert_job(source_filename="review_index_test_not_review_ready.pdf", status="processing")
    response = _index(job_id)
    assert response.status_code == 409


def test_index_404s_for_unknown_job():
    response = _index(str(uuid.uuid4()))
    assert response.status_code == 404


# --- 25/26/27: historical-job isolation --------------------------------------


def test_historical_needs_reconciliation_job_is_never_touched_by_new_extract():
    """Simulates the real concern: a historical needs_reconciliation row
    (like the production LSPU Student Handbook incident) must never be
    read, modified, or attached merely because a brand-new, unrelated
    Extract operation runs on the same dyno."""
    historical_id = _insert_job(
        source_filename="review_index_test_HISTORICAL_handbook.pdf", status="needs_reconciliation"
    )
    before = _fetch_job(historical_id)

    store, _collection = make_fake_store()
    p1, p2 = patched_store(store)
    with p1, p2, patch("httpx.post") as mock_post:
        response = _extract(
            _make_digital_pdf("A completely unrelated new document."),
            "review_index_test_unrelated_new_upload.pdf",
        )

    mock_post.assert_not_called()
    assert response.status_code == 200
    new_job_id = response.json()["job_id"]
    assert new_job_id != historical_id

    after = _fetch_job(historical_id)
    assert after.status == "needs_reconciliation"
    assert after.status == before.status
    assert after.error_message == before.error_message
    assert after.updated_at == before.updated_at


def test_same_filename_as_historical_job_still_creates_a_brand_new_job():
    """Even an upload sharing the exact SAME filename as a historical
    terminal job (different content/bytes) must never be treated as a
    continuation of it -- start_extraction_job does no filename-based
    lookup at all."""
    historical_id = _insert_job(
        source_filename="review_index_test_SAME_NAME.pdf", status="published"
    )

    store, _collection = make_fake_store()
    p1, p2 = patched_store(store)
    with p1, p2, patch("httpx.post") as mock_post:
        response = _extract(_make_digital_pdf("Different content."), "review_index_test_SAME_NAME.pdf")

    mock_post.assert_not_called()
    assert response.status_code == 200
    assert response.json()["job_id"] != historical_id


def test_active_job_concurrency_guard_returns_409_not_a_historical_job():
    """The only existing-row check in start_extraction_job is the
    single-dyno concurrency guard -- it must reject with 409, never
    silently return/attach some other job."""
    _insert_job(source_filename="review_index_test_already_running.pdf", status="processing")

    store, _collection = make_fake_store()
    p1, p2 = patched_store(store)
    with p1, p2, patch("httpx.post") as mock_post:
        response = _extract(_make_digital_pdf("Blocked by the active job."), "review_index_test_blocked.pdf")

    mock_post.assert_not_called()
    assert response.status_code == 409
