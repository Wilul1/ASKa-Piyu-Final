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
    _attach_unit_diagnostics,
)
from app.services.admin.knowledge_base_pipeline import suspicious_unit_diagnostics
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


# --- Stage 23 Part 2: suspicious-unit diagnostics attached to the preview --
#
# Pure, no-HTTP/no-Chroma unit tests of _attach_unit_diagnostics() -- the
# function that joins knowledge_base_pipeline.suspicious_unit_diagnostics()
# results back onto their exact source unit by unit_index (never by title,
# never by units.index(), never by filter-then-zip position). See Stage 23
# Part 1 for why unit_index is the only safe join key.


def _suspicious_unit(unit_index: int, title: str = "Minor Offense", page_start: int = 1) -> dict:
    return {
        "unit_index": unit_index,
        "title": title,
        "content": "",
        "content_type": "disciplinary_rule",
        "status": "Suspicious",
        "suspicious_reasons": ["very_short"],
        "metadata": {"page_start": page_start},
    }


def _ok_unit(unit_index: int, title: str = "Admission Requirements", page_start: int = 1) -> dict:
    return {
        "unit_index": unit_index,
        "title": title,
        "content": "A student seeking admission must comply with the minimum requirements for enrolment.",
        "content_type": "policy",
        "status": "OK",
        "suspicious_reasons": [],
        "metadata": {"page_start": page_start, "chapter": "Chapter 3 > Admission"},
    }


def test_attach_unit_diagnostics_suspicious_unit_receives_snippet_and_classification():
    page_texts = ["Minor Offense\nSome disciplinary content on this page."]
    units = [_suspicious_unit(0)]

    result = _attach_unit_diagnostics(units, page_texts)

    assert result[0]["original_page_text_snippet"] == page_texts[0].strip()
    assert result[0]["proposed_classification"] == "extraction issue"
    # Existing fields untouched.
    assert result[0]["title"] == "Minor Offense"
    assert result[0]["status"] == "Suspicious"
    assert result[0]["suspicious_reasons"] == ["very_short"]


def test_attach_unit_diagnostics_normal_unit_has_none_for_both_new_fields():
    page_texts = ["Admission Requirements\nSome policy text."]
    units = [_ok_unit(0)]

    result = _attach_unit_diagnostics(units, page_texts)

    assert result[0]["original_page_text_snippet"] is None
    assert result[0]["proposed_classification"] is None
    assert result[0]["status"] == "OK"


def test_attach_unit_diagnostics_suspicious_unit_without_matching_page_text_does_not_raise():
    # page_start points past the end of page_texts -- suspicious_unit_
    # diagnostics() already handles this (empty snippet); this proves the
    # merge layer propagates that without raising or inventing a fallback.
    units = [_suspicious_unit(0, page_start=5)]

    result = _attach_unit_diagnostics(units, page_texts=["Only one real page."])

    assert result[0]["original_page_text_snippet"] == ""
    assert result[0]["proposed_classification"] == "extraction issue"


def test_attach_unit_diagnostics_multiple_suspicious_units_retain_correct_association():
    page_texts = [
        "Minor Offense\nFirst disciplinary content.",
        "Admission Requirements\nSome policy text.",
        "Major Offense\nSecond disciplinary content.",
    ]
    units = [
        _suspicious_unit(0, title="Minor Offense", page_start=1),
        _ok_unit(1, page_start=2),
        _suspicious_unit(2, title="Major Offense", page_start=3),
    ]

    result = _attach_unit_diagnostics(units, page_texts)

    assert result[0]["original_page_text_snippet"] == page_texts[0].strip()
    assert result[1]["original_page_text_snippet"] is None
    assert result[2]["original_page_text_snippet"] == page_texts[2].strip()


def test_attach_unit_diagnostics_identical_units_do_not_swap_diagnostic_data():
    # Two units with the SAME title/content but different unit_index and
    # different page_start -- each must receive its OWN page's snippet,
    # proving association is never by title/content alone.
    units = [
        _suspicious_unit(0, title="Minor Offense", page_start=1),
        _suspicious_unit(1, title="Minor Offense", page_start=2),
    ]
    page_texts = [
        "Minor Offense\nFirst occurrence content.",
        "Minor Offense\nSecond occurrence content.",
    ]

    result = _attach_unit_diagnostics(units, page_texts)

    assert result[0]["original_page_text_snippet"] == page_texts[0].strip()
    assert result[1]["original_page_text_snippet"] == page_texts[1].strip()
    assert result[0]["original_page_text_snippet"] != result[1]["original_page_text_snippet"]


def test_attach_unit_diagnostics_older_payload_shape_without_new_fields_still_builds():
    """A unit dict shaped exactly like output predating this change (no
    original_page_text_snippet/proposed_classification keys at all) must
    still be processable -- this function only ever reads pre-existing
    keys and adds the two new ones; it never requires them to already
    exist."""
    units = [_ok_unit(0)]
    assert "original_page_text_snippet" not in units[0]

    result = _attach_unit_diagnostics(units, page_texts=["Admission Requirements\nSome policy text."])

    assert result[0]["original_page_text_snippet"] is None
    assert result[0]["proposed_classification"] is None


def test_attach_unit_diagnostics_no_suspicious_units_preserves_existing_behavior():
    units = [_ok_unit(0), _ok_unit(1, title="Attendance Policy")]
    page_texts = ["Admission Requirements\nSome policy text.", "Attendance Policy\nMore policy text."]

    result = _attach_unit_diagnostics(units, page_texts)

    assert len(result) == 2
    assert all(u["original_page_text_snippet"] is None for u in result)
    assert all(u["proposed_classification"] is None for u in result)
    assert [u["title"] for u in result] == ["Admission Requirements", "Attendance Policy"]


def test_attach_unit_diagnostics_out_of_range_index_is_dropped_not_misattached(monkeypatch):
    """Defends the merge layer itself: even if suspicious_unit_diagnostics()
    returned an entry whose unit_index matches no real unit (a defensive
    scenario, not one reachable today since that function derives its
    index from enumerate(units) over this exact same list), the merge must
    never fall back to attaching it to some other unit by position."""
    units = [_ok_unit(0), _suspicious_unit(1)]

    def _fake_diagnostics(*, page_texts, units):
        real = suspicious_unit_diagnostics(page_texts=page_texts, units=units)
        # Inject an extra, unmatched diagnostic entry (unit_index=99).
        return real + [
            {
                "unit_index": 99,
                "original_page_text_snippet": "should never be attached to anything",
                "extracted_unit_title": "nonexistent",
                "extracted_content": "",
                "suspicious_reasons": [],
                "proposed_classification": "needs review",
            }
        ]

    monkeypatch.setattr(
        "app.services.admin.digital_ingestion.suspicious_unit_diagnostics", _fake_diagnostics
    )

    result = _attach_unit_diagnostics(units, page_texts=["Admission Requirements\nSome policy text.", "Minor Offense\nSome disciplinary content."])

    assert result[0]["original_page_text_snippet"] is None, "the OK unit must not receive the orphaned diagnostic"
    assert result[1]["original_page_text_snippet"] is not None, "the real suspicious unit must still get its own diagnostic"
    assert "should never be attached to anything" not in [
        result[0]["original_page_text_snippet"], result[1]["original_page_text_snippet"]
    ]


def test_job_preview_endpoint_includes_diagnostic_fields_on_knowledge_units(monkeypatch):
    """End-to-end: the real /preview HTTP response's knowledge_units carry
    the two new optional keys, proving this is actually wired in, not just
    unit-tested in isolation. Does not force a specific OK/Suspicious
    outcome for the real generic-chunked text (that depends on heading
    detection, not something this test should hard-code) -- it only
    asserts the keys exist with the correct None-vs-populated shape for
    whatever status each real unit actually received."""
    monkeypatch.setattr("app.services.admin.digital_ingestion.settings.ocr_worker_enabled", True)
    monkeypatch.setattr("app.services.admin.digital_ingestion.settings.ocr_worker_url", FAKE_URL)
    monkeypatch.setattr("app.services.admin.digital_ingestion.settings.ocr_worker_token", FAKE_TOKEN)
    store, _collection = make_fake_store()
    p1, p2 = patched_store(store)
    payload = _completed_payload([(1, "Scanned registrar text about enrollment. " * 30)])

    with p1, p2, patch("httpx.post", return_value=_fake_http_response(200, payload)):
        extract_response = _extract(_make_blank_scanned_pdf(), "review_index_test_diagnostics_shape.pdf")
        job_id = extract_response.json()["job_id"]

        preview_response = client.get(
            f"/admin/knowledge-base/jobs/{job_id}/preview", headers=ADMIN_HEADERS
        )

    assert preview_response.status_code == 200
    units = preview_response.json()["knowledge_units"]
    assert units, "expected at least one real knowledge unit from the scanned-text pipeline"
    for unit in units:
        assert "original_page_text_snippet" in unit
        assert "proposed_classification" in unit
        if unit["status"] == "Suspicious":
            assert unit["proposed_classification"] is not None
        else:
            assert unit["original_page_text_snippet"] is None
            assert unit["proposed_classification"] is None
