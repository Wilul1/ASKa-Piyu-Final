"""Focused tests for the 2026-10-05 LSPU Student Handbook H12 follow-up fix:

FIX #1: the lightweight/cloud-safe pipeline must never call
app.services.structured_document_parser.build_structured_document() /
parse_structured_document() -- that generic service-block regex scanner,
designed for the legacy local/Docker pipeline's Citizen's Charter/form
documents, measured at over 1000 seconds on a synthetic document matching
the real 198-page/~343K-char Handbook's size (see
app/services/admin/digital_ingestion.py::_lightweight_structured_response's
docstring). This file proves it is now structurally unreachable from the
lightweight pipeline, not just "didn't happen to run slow this time" --
every test here mocks build_structured_document/parse_structured_document
and asserts they are NEVER called, rather than relying on fragile
wall-clock timing.

Also covers FIX #2 (every /extract call on the lightweight runtime is now
asynchronous, including digital-sufficient documents) end-to-end for both
digital and OCR-required documents.

Safety: never touches a real Chroma client, never makes a real HTTP call
(httpx.post is mocked for every OCR path).
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.db.safety import assert_destructive_database_ops_allowed
from app.db.session import get_session_factory
from app.main import app
from app.models.db_models import IngestionJob
from app.services.chroma_store import KnowledgeBaseStore

ADMIN_HEADERS = {"X-Admin-Key": "test-admin-key"}
FAKE_TOKEN = "fake-ocr-worker-secret-token-xyz"
FAKE_URL = "https://aska-piyu-ocr.example.com"


class FakeChromaCollection:
    def __init__(self):
        self._records: dict[str, dict] = {}
        self.add_call_count = 0
        self.delete_call_count = 0

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
    return (
        patch("app.services.admin.digital_ingestion.get_knowledge_base_store", return_value=store),
        patch("app.services.admin.knowledge_base_pipeline.get_knowledge_base_store", return_value=store),
    )


def _mock_structured_parser():
    """Patches the ORIGINAL functions (not something digital_ingestion.py
    re-exports -- it imports neither anymore) so a call from ANY code path
    reached by this pipeline would be caught."""
    return (
        patch("app.services.structured_document_parser.build_structured_document"),
        patch("app.services.structured_document_parser.parse_structured_document"),
    )


def _large_synthetic_pages(n_pages: int, chars_per_page: int) -> list[str]:
    """Deterministic, non-real-Handbook-content synthetic text matching
    the real incident's scale (198 pages, ~343K chars total) -- same
    technique used for the original local timing benchmark, never the
    real Handbook text."""
    import random

    rng = random.Random(42)
    words = [
        "the", "student", "shall", "office", "registrar", "policy", "section",
        "article", "chapter", "university", "campus", "admission", "enrollment",
        "requirement", "procedure", "grade", "academic", "faculty", "dean",
        "committee", "must", "submit", "form", "fee", "payment", "schedule",
        "semester", "program", "curriculum",
    ]
    pages = []
    for _ in range(n_pages):
        out = []
        total = 0
        while total < chars_per_page:
            w = rng.choice(words)
            out.append(w)
            total += len(w) + 1
        pages.append(" ".join(out))
    return pages


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


@pytest.fixture(autouse=True)
def _admin_key(monkeypatch):
    monkeypatch.setattr("app.routes.admin.knowledge_base.settings.admin_api_key", "test-admin-key")


@pytest.fixture(autouse=True)
def _ingestion_unavailable(monkeypatch):
    monkeypatch.setattr("app.routes.admin.knowledge_base.ingestion_available", lambda: False)


@pytest.fixture(autouse=True)
def _cleanup_test_jobs():
    yield
    assert_destructive_database_ops_allowed()
    session = get_session_factory()()
    try:
        session.query(IngestionJob).filter(
            IngestionJob.source_filename.like("structured_fix_test_%")
        ).delete(synchronize_session=False)
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


def _fetch_job(job_id: str) -> IngestionJob:
    session = get_session_factory()()
    try:
        job = session.get(IngestionJob, job_id)
        session.expunge(job)
        return job
    finally:
        session.close()


# --- 1/2/4: digital PDF /extract returns processing+job_id immediately,  ---
# --- background processing reaches review_ready (no synchronous fast    ---
# --- path anymore, even for digital-sufficient documents)               ---


def test_digital_pdf_extract_always_returns_processing_stub_now():
    store, _collection = make_fake_store()
    p1, p2 = patched_store(store)
    with p1, p2, patch("httpx.post") as mock_post:
        response = _extract(
            _make_multi_page_digital_pdf(["Some digital page text. " * 20]),
            "structured_fix_test_digital_stub.pdf",
        )

    mock_post.assert_not_called()
    assert response.status_code == 200
    data = response.json()
    # ALWAYS the processing stub now, even though this is a digital PDF --
    # no more synchronous fast path.
    assert data["status"] == "processing"
    assert data["job_id"]
    assert data["review_text"] == ""
    assert data["structured"] is None
    assert data["pipeline_stages"] == []

    job = _fetch_job(data["job_id"])
    # Background processing (run synchronously by TestClient before
    # .post() returns) already reached review_ready.
    assert job.status == "review_ready"
    pages = json.loads(job.extracted_pages_json)
    assert pages["extraction_method"] == "pymupdf_digital"


# --- 3/5: scanned PDF behaves the same way; OCR background job reaches  ---
# --- review_ready too                                                    ---


def test_scanned_pdf_extract_also_returns_processing_stub_and_reaches_review_ready(monkeypatch):
    monkeypatch.setattr("app.services.admin.digital_ingestion.settings.ocr_worker_enabled", True)
    monkeypatch.setattr("app.services.admin.digital_ingestion.settings.ocr_worker_url", FAKE_URL)
    monkeypatch.setattr("app.services.admin.digital_ingestion.settings.ocr_worker_token", FAKE_TOKEN)
    store, _collection = make_fake_store()
    p1, p2 = patched_store(store)
    payload = _completed_payload([(1, "Scanned registrar text. " * 50)])

    with p1, p2, patch("httpx.post", return_value=_fake_http_response(200, payload)) as mock_post:
        response = _extract(_make_blank_scanned_pdf(), "structured_fix_test_scanned_stub.pdf")

    mock_post.assert_called_once()
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "processing"
    assert data["job_id"]

    job = _fetch_job(data["job_id"])
    assert job.status == "review_ready"
    pages = json.loads(job.extracted_pages_json)
    assert pages["extraction_method"] == "remote_ocr_worker"


# --- 6/7/8: build_structured_document/parse_structured_document are      ---
# --- NEVER called by lightweight extraction or /jobs/{id}/preview        ---


def test_build_structured_document_never_called_by_extract_or_preview_fetch():
    store, _collection = make_fake_store()
    p1, p2 = patched_store(store)
    build_patch, parse_patch = _mock_structured_parser()

    with p1, p2, patch("httpx.post") as mock_post, build_patch as mock_build, parse_patch as mock_parse:
        extract_response = _extract(
            _make_multi_page_digital_pdf(["Content about enrollment. " * 30, "More content. " * 30]),
            "structured_fix_test_no_structured_parser.pdf",
        )
        job_id = extract_response.json()["job_id"]

        preview_response = client.get(
            f"/admin/knowledge-base/jobs/{job_id}/preview", headers=ADMIN_HEADERS
        )

    mock_post.assert_not_called()
    mock_build.assert_not_called()
    mock_parse.assert_not_called()
    assert preview_response.status_code == 200
    data = preview_response.json()
    assert data["structured"]["fields"] == []
    assert data["structured"]["formatted_text"]  # populated directly from cleaned text


def test_build_structured_document_never_called_for_ocr_path_either(monkeypatch):
    monkeypatch.setattr("app.services.admin.digital_ingestion.settings.ocr_worker_enabled", True)
    monkeypatch.setattr("app.services.admin.digital_ingestion.settings.ocr_worker_url", FAKE_URL)
    monkeypatch.setattr("app.services.admin.digital_ingestion.settings.ocr_worker_token", FAKE_TOKEN)
    store, _collection = make_fake_store()
    p1, p2 = patched_store(store)
    build_patch, parse_patch = _mock_structured_parser()
    payload = _completed_payload([(1, "Scanned text. " * 50)])

    with p1, p2, patch("httpx.post", return_value=_fake_http_response(200, payload)), build_patch as mock_build, parse_patch as mock_parse:
        extract_response = _extract(_make_blank_scanned_pdf(), "structured_fix_test_ocr_no_structured.pdf")
        job_id = extract_response.json()["job_id"]
        preview_response = client.get(
            f"/admin/knowledge-base/jobs/{job_id}/preview", headers=ADMIN_HEADERS
        )

    mock_build.assert_not_called()
    mock_parse.assert_not_called()
    assert preview_response.status_code == 200


# --- 9: large synthetic preview reconstruction completes using the      ---
# --- lightweight representation (performance-oriented, no wall-clock    ---
# --- timing assertion -- the mock assertion above is the real proof;    ---
# --- this test additionally proves it actually runs to completion at    ---
# --- real Handbook scale without relying on how fast that happens to be)---


def test_handbook_scale_synthetic_document_completes_without_structured_parser():
    """198 pages / ~343K chars -- the exact scale of the real incident --
    using synthetic (non-Handbook) text. No wall-clock assertion: the
    build_structured_document mock-assertion is the actual regression
    guard; this proves the full pipeline still produces a correct result
    at that scale, not just that it avoids one slow function."""
    store, _collection = make_fake_store()
    p1, p2 = patched_store(store)
    build_patch, parse_patch = _mock_structured_parser()
    pages = _large_synthetic_pages(n_pages=198, chars_per_page=1731)

    with p1, p2, patch("httpx.post") as mock_post, build_patch as mock_build, parse_patch as mock_parse:
        extract_response = _extract(
            _make_multi_page_digital_pdf(pages), "structured_fix_test_handbook_scale.pdf"
        )
        job_id = extract_response.json()["job_id"]
        preview_response = client.get(
            f"/admin/knowledge-base/jobs/{job_id}/preview", headers=ADMIN_HEADERS
        )

    mock_post.assert_not_called()
    mock_build.assert_not_called()
    mock_parse.assert_not_called()

    assert extract_response.status_code == 200
    assert preview_response.status_code == 200
    data = preview_response.json()
    # 10: response schema remains Flutter-compatible.
    for key in (
        "status", "job_id", "document_type", "raw_text", "cleaned_text",
        "review_text", "extracted_text", "page_count", "extraction_method",
        "structuring_method", "pipeline_stages", "structured",
        "knowledge_units", "chunk_preview", "validation_report", "kb_statistics",
    ):
        assert key in data
    # 11: review_text/cleaned text preserved (not empty, not a fabricated stub).
    assert len(data["review_text"]) > 1000
    assert data["review_text"] == data["cleaned_text"]
    # 12: page metadata preserved across the full 198-page document.
    page_starts = {c.get("page_start") for c in data["chunk_preview"]}
    assert page_starts
    assert max(page_starts) > 1  # spans multiple pages, not collapsed to one
    assert max(page_starts) <= 198

    job = _fetch_job(job_id)
    assert job.status == "review_ready"
    assert job.page_count == 198


# --- 20: an orphaned review_ready job (exactly this incident's shape)   ---
# --- cannot be auto-discovered by a new, unrelated Extract operation    ---


def test_orphaned_review_ready_job_is_never_auto_discovered_by_new_extract():
    """Mirrors the real production situation: a job that reached
    review_ready but was never surfaced to any browser session (the
    router gave up before the response was delivered) must stay
    completely inert -- a brand-new Extract for an unrelated document
    must never find, reuse, or reference it."""
    session = get_session_factory()()
    try:
        orphan = IngestionJob(
            source_filename="structured_fix_test_ORPHANED_handbook.pdf",
            sha256_hash=uuid.uuid4().hex + uuid.uuid4().hex,
            status="review_ready",
            pdf_bytes=b"x",
            byte_size=1,
            extracted_pages_json=json.dumps({"pages": ["orphaned content"], "extraction_method": "pymupdf_digital"}),
        )
        session.add(orphan)
        session.commit()
        session.refresh(orphan)
        orphan_id = orphan.id
        orphan_updated_at = orphan.updated_at
    finally:
        session.close()

    store, _collection = make_fake_store()
    p1, p2 = patched_store(store)
    with p1, p2, patch("httpx.post") as mock_post:
        response = _extract(
            _make_multi_page_digital_pdf(["A completely unrelated new document."]),
            "structured_fix_test_unrelated.pdf",
        )

    mock_post.assert_not_called()
    assert response.status_code == 200
    new_job_id = response.json()["job_id"]
    assert new_job_id != orphan_id

    session = get_session_factory()()
    try:
        after = session.get(IngestionJob, orphan_id)
        assert after.status == "review_ready"
        assert after.updated_at == orphan_updated_at
    finally:
        session.close()
