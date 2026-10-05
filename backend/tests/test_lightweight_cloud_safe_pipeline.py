"""Focused tests for the lightweight/cloud-safe Extract & Structure / Index
for Chatbot Retrieval pipeline (app/services/admin/digital_ingestion.py:
build_lightweight_preview / build_lightweight_publish).

This is the code path /admin/knowledge-base/extract and
/admin/knowledge-base/ingest now use whenever ingestion_available() is
False (e.g. the Heroku web dyno, which deliberately never installs
easyocr/sentence-transformers) -- see app/routes/admin/knowledge_base.py.

Same safety conventions as test_digital_ingestion_ocr_worker.py:
  - never touches real Chroma Cloud (get_knowledge_base_store is patched to
    a FakeChromaCollection-backed store in both the modules that call it --
    digital_ingestion.py directly, and knowledge_base_pipeline.py via its
    own knowledge_base_statistics()/collection_statistics() calls).
  - never makes a real HTTP call (httpx.post is mocked).
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.models.schemas import ExtractDocumentResponse, IngestKnowledgeBaseResponse
from app.services.admin.digital_ingestion import (
    DigitalIngestionError,
    build_lightweight_preview,
    build_lightweight_publish,
    publish_new_version,
)
from app.services.chroma_store import KnowledgeBaseStore

FAKE_TOKEN = "fake-ocr-worker-secret-token-xyz"
FAKE_URL = "https://aska-piyu-ocr.example.com"


# --- Fake Chroma (never touches real Chroma Cloud) --------------------------


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


def _patched_store(store):
    """Patches get_knowledge_base_store everywhere this pipeline reaches it:
    directly in digital_ingestion.py, and indirectly via
    knowledge_base_pipeline.knowledge_base_statistics()."""
    return (
        patch("app.services.admin.digital_ingestion.get_knowledge_base_store", return_value=store),
        patch("app.services.admin.knowledge_base_pipeline.get_knowledge_base_store", return_value=store),
    )


# --- PDF fixtures (shared style with test_digital_ingestion_ocr_worker.py) --


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


# --- 2: lightweight digital PDF extraction -----------------------------------


def test_lightweight_preview_digital_pdf_never_calls_ocr_worker():
    store, _collection = make_fake_store()
    p1, p2 = _patched_store(store)
    with p1, p2, patch("httpx.post") as mock_post:
        result = build_lightweight_preview(
            _make_digital_pdf("Office of the Registrar enrollment procedures."),
            filename="handbook.pdf",
            content_type="application/pdf",
        )

    mock_post.assert_not_called()
    assert result["extraction_method"] == "pymupdf_digital"
    assert "Registrar" in result["review_text"]
    assert result["structuring_method"] == "generic_chunking"
    # 12/13: schema compatibility -- builds without a pydantic ValidationError.
    ExtractDocumentResponse(**result)


# --- 3: lightweight remote OCR fallback with mocked HTTP --------------------


def test_lightweight_preview_falls_back_to_ocr_worker_when_scanned(monkeypatch):
    monkeypatch.setattr("app.services.admin.digital_ingestion.settings.ocr_worker_enabled", True)
    monkeypatch.setattr("app.services.admin.digital_ingestion.settings.ocr_worker_url", FAKE_URL)
    monkeypatch.setattr("app.services.admin.digital_ingestion.settings.ocr_worker_token", FAKE_TOKEN)

    store, _collection = make_fake_store()
    p1, p2 = _patched_store(store)
    payload = _completed_payload([(1, "Scanned registrar text. " * 50)])

    with p1, p2, patch("httpx.post", return_value=_fake_http_response(200, payload)) as mock_post:
        result = build_lightweight_preview(
            _make_blank_scanned_pdf(),
            filename="scanned.pdf",
            content_type="application/pdf",
        )

    mock_post.assert_called_once()
    assert result["extraction_method"] == "remote_ocr_worker"
    assert "registrar" in result["review_text"].lower()
    ExtractDocumentResponse(**result)


# --- 4: OCR worker disabled/misconfigured behavior --------------------------


def test_lightweight_preview_raises_when_ocr_needed_but_worker_disabled(monkeypatch):
    monkeypatch.setattr("app.services.admin.digital_ingestion.settings.ocr_worker_enabled", False)
    store, _collection = make_fake_store()
    p1, p2 = _patched_store(store)

    with p1, p2, patch("httpx.post") as mock_post:
        with pytest.raises(DigitalIngestionError, match="OCR worker is not configured"):
            build_lightweight_preview(
                _make_blank_scanned_pdf(), filename="scanned.pdf", content_type="application/pdf"
            )

    mock_post.assert_not_called()


def test_lightweight_preview_raises_when_worker_missing_token(monkeypatch):
    monkeypatch.setattr("app.services.admin.digital_ingestion.settings.ocr_worker_enabled", True)
    monkeypatch.setattr("app.services.admin.digital_ingestion.settings.ocr_worker_url", FAKE_URL)
    monkeypatch.setattr("app.services.admin.digital_ingestion.settings.ocr_worker_token", None)
    store, _collection = make_fake_store()
    p1, p2 = _patched_store(store)

    with p1, p2, patch("httpx.post") as mock_post:
        with pytest.raises(DigitalIngestionError):
            build_lightweight_preview(
                _make_blank_scanned_pdf(), filename="scanned.pdf", content_type="application/pdf"
            )

    mock_post.assert_not_called()


# --- 5: OCR worker timeout/failure behavior ---------------------------------


@pytest.mark.parametrize(
    "mock_kwargs",
    [
        {"side_effect": httpx.TimeoutException("timed out")},
        {"return_value": _fake_http_response(401)},
        {"return_value": _fake_http_response(503)},
    ],
)
def test_lightweight_preview_raises_on_ocr_worker_failure(monkeypatch, mock_kwargs):
    monkeypatch.setattr("app.services.admin.digital_ingestion.settings.ocr_worker_enabled", True)
    monkeypatch.setattr("app.services.admin.digital_ingestion.settings.ocr_worker_url", FAKE_URL)
    monkeypatch.setattr("app.services.admin.digital_ingestion.settings.ocr_worker_token", FAKE_TOKEN)
    store, _collection = make_fake_store()
    p1, p2 = _patched_store(store)

    with p1, p2, patch("httpx.post", **mock_kwargs):
        with pytest.raises(DigitalIngestionError):
            build_lightweight_preview(
                _make_blank_scanned_pdf(), filename="scanned.pdf", content_type="application/pdf"
            )


# --- 6: no Chroma write during Extract & Structure --------------------------


def test_lightweight_preview_never_writes_to_chroma():
    store, collection = make_fake_store()
    p1, p2 = _patched_store(store)
    with p1, p2, patch("httpx.post") as mock_post:
        build_lightweight_preview(
            _make_digital_pdf(), filename="handbook.pdf", content_type="application/pdf"
        )

    mock_post.assert_not_called()
    assert collection.add_call_count == 0
    assert collection.delete_call_count == 0
    assert collection.count() == 0


# --- 7: Index uses publish_new_version (never delete-by-filename-then-add) --


def test_lightweight_publish_uses_publish_new_version():
    store, _collection = make_fake_store()
    p1, p2 = _patched_store(store)

    with p1, p2, patch("httpx.post") as mock_post, patch(
        "app.services.admin.digital_ingestion.publish_new_version",
        wraps=publish_new_version,
    ) as mock_publish:
        result = build_lightweight_publish(
            _make_digital_pdf("Enrollment procedures for new students."),
            filename="handbook.pdf",
            content_type="application/pdf",
            title="Handbook",
        )

    mock_post.assert_not_called()
    mock_publish.assert_called_once()
    assert result["chunks_indexed"] > 0
    assert result["document_id"]
    IngestKnowledgeBaseResponse(**result)


def test_lightweight_publish_never_uses_delete_by_source_filename():
    store, collection = make_fake_store()
    p1, p2 = _patched_store(store)
    with p1, p2, patch("httpx.post") as mock_post:
        build_lightweight_publish(
            _make_digital_pdf("Enrollment procedures."),
            filename="handbook.pdf",
            content_type="application/pdf",
        )
    mock_post.assert_not_called()
    # publish_new_version's contract: add-new (verified) happens before any
    # delete at all -- for a first-ever publish there is nothing to delete.
    assert collection.delete_call_count == 0
    assert collection.add_call_count >= 1


# --- 8: a failed Index does not destroy the currently published version ----


def test_lightweight_publish_failure_leaves_existing_published_version_intact():
    store, collection = make_fake_store()
    p1, p2 = _patched_store(store)

    # Simulate an existing published version for this source_filename.
    collection.add(
        ids=["old-chunk-1"],
        documents=["old content"],
        metadatas=[{"document_id": "old-doc-id", "source_filename": "handbook.pdf"}],
    )

    with p1, p2, patch("httpx.post") as mock_post, patch(
        "app.services.admin.digital_ingestion.publish_new_version",
        side_effect=DigitalIngestionError("Adding the new version failed: simulated failure"),
    ):
        with pytest.raises(DigitalIngestionError):
            build_lightweight_publish(
                _make_digital_pdf("New replacement content."),
                filename="handbook.pdf",
                content_type="application/pdf",
            )

    mock_post.assert_not_called()
    # The old version's chunk is untouched -- publish_new_version itself
    # (already tested exhaustively in test_chroma_pagination_fix.py) is the
    # only thing that may ever delete it, and it never got the chance to.
    assert collection.get(where={"document_id": "old-doc-id"})["ids"] == ["old-chunk-1"]


# --- 9: reviewed_text is used during Index -----------------------------------


def test_lightweight_publish_uses_reviewed_text_override():
    store, _collection = make_fake_store()
    p1, p2 = _patched_store(store)

    with p1, p2, patch("httpx.post") as mock_post:
        result = build_lightweight_publish(
            _make_digital_pdf("Original extracted text about parking permits."),
            filename="handbook.pdf",
            content_type="application/pdf",
            reviewed_text="Admin-edited replacement text about library hours.",
        )

    mock_post.assert_not_called()
    combined = " ".join(
        str(chunk.get("content", "")) for chunk in (result.get("chunk_preview") or [])
    ).lower()
    assert "library hours" in combined
    assert "parking permits" not in combined


# --- 10: token never exposed in response/errors/loggable exception text ----


def test_lightweight_preview_never_leaks_ocr_token(monkeypatch, caplog):
    monkeypatch.setattr("app.services.admin.digital_ingestion.settings.ocr_worker_enabled", True)
    monkeypatch.setattr("app.services.admin.digital_ingestion.settings.ocr_worker_url", FAKE_URL)
    monkeypatch.setattr("app.services.admin.digital_ingestion.settings.ocr_worker_token", FAKE_TOKEN)
    store, _collection = make_fake_store()
    p1, p2 = _patched_store(store)

    caught: list[Exception] = []
    with caplog.at_level(logging.DEBUG):
        with p1, p2, patch(
            "httpx.post",
            side_effect=httpx.TimeoutException(f"timed out, request=<...Authorization: Bearer {FAKE_TOKEN}...>"),
        ):
            try:
                build_lightweight_preview(
                    _make_blank_scanned_pdf(), filename="scanned.pdf", content_type="application/pdf"
                )
            except DigitalIngestionError as exc:
                caught.append(exc)

    assert len(caught) == 1
    assert FAKE_TOKEN not in str(caught[0])
    for record in caplog.records:
        assert FAKE_TOKEN not in record.getMessage()
        if record.exc_text:
            assert FAKE_TOKEN not in record.exc_text


# --- 11: page-aware metadata behavior where available -----------------------


def test_lightweight_preview_preserves_page_metadata_across_pages(monkeypatch):
    # PyMuPDF's insert_text() (no wrapping) only renders/extracts what fits
    # on one line, so a short chunk_max_chars is needed here to force a
    # chunk boundary to actually fall inside the page1/page2 text -- unlike
    # the OCR-worker tests, this page's text comes from a real rendered
    # PDF, not an arbitrary-length mocked JSON string. The repeated text and
    # chunk_size=50 (with margin above the few-char offset drift that
    # clean_extracted_text's whitespace normalization introduces between
    # the cleaned-text chunk offsets and the raw-text page offsets --
    # pre-existing behavior of build_chunks_with_pages, not changed here)
    # are chosen so a chunk boundary reliably lands past the page1/page2
    # seam either way.
    monkeypatch.setattr("app.services.admin.digital_ingestion.settings.chunk_max_chars", 50)
    monkeypatch.setattr("app.services.admin.digital_ingestion.settings.chunk_overlap", 0)

    store, _collection = make_fake_store()
    p1, p2 = _patched_store(store)
    texts = ["Office of the Registrar. " * 100, "Student Affairs Office procedures. " * 100]

    with p1, p2, patch("httpx.post") as mock_post:
        result = build_lightweight_preview(
            _make_multi_page_digital_pdf(texts), filename="handbook.pdf", content_type="application/pdf"
        )

    mock_post.assert_not_called()
    page_numbers = {
        chunk.get("page_start") for chunk in (result.get("chunk_preview") or [])
    }
    assert page_numbers == {1, 2}


def test_lightweight_publish_reviewed_text_collapses_page_metadata_to_one():
    """Matches the legacy /ingest path's existing, accepted limitation: an
    admin's free-text edit has no page boundaries of its own."""
    store, _collection = make_fake_store()
    p1, p2 = _patched_store(store)

    with p1, p2, patch("httpx.post") as mock_post:
        result = build_lightweight_publish(
            _make_multi_page_digital_pdf(["Page one text. " * 50, "Page two text. " * 50]),
            filename="handbook.pdf",
            content_type="application/pdf",
            reviewed_text="A single reviewed blob of text with no original page boundaries. " * 20,
        )

    mock_post.assert_not_called()
    page_numbers = {chunk.get("page_start") for chunk in (result.get("chunk_preview") or [])}
    assert page_numbers == {1}
