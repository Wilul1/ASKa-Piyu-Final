"""Tests for Option A: structured LSPU Student Handbook disciplinary-table
extraction integrated into the lightweight (Heroku web dyno) digital-
ingestion review/index job flow.

Covers:
  app/services/admin/handbook_lightweight_extraction.py (new module)
  app/services/admin/digital_ingestion.py's extracted_pages_payload /
  load_extracted_pages / process_extraction_preview_job /
  chunks_from_pages_or_reviewed_text / process_indexing_job changes.

Safety, matching every other file in this suite:
  - never touches a real Chroma client -- get_knowledge_base_store is
    patched everywhere reachable (see test_extraction_review_index_jobs.py,
    whose fake-store/job-row helpers are duplicated narrowly here rather
    than cross-imported).
  - never makes a real HTTP/OCR-worker call.
  - one test (test_structured_* baseline/content assertions) depends on a
    local-only copy of the real LSPU Student Handbook PDF
    (backend/data/documents/.../LSPU Student Handbook.pdf, gitignored, not
    committed to this repo) and is skipped automatically where that file
    isn't present -- e.g. in CI or on a fresh checkout.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.db.safety import assert_destructive_database_ops_allowed
from app.db.session import get_session_factory
from app.main import app
from app.models.db_models import IngestionJob
from app.services.admin import digital_ingestion as di
from app.services.admin.handbook_lightweight_extraction import (
    STATUS_ATTEMPTED_NO_MATCH,
    STATUS_ELIGIBLE,
    extract_structured_handbook_data,
    find_candidate_table_pages,
    reconstruct_page_extractions,
)
from app.services.admin.digital_ingestion import (
    STRUCTURING_METHOD_GENERIC_FALLBACK,
    DigitalIngestionHandbookReviewRequiredError,
)
from app.services.chroma_store import KnowledgeBaseStore
from app.services.handbook_policy_processor import build_handbook_policy_document

ADMIN_HEADERS = {"X-Admin-Key": "test-admin-key"}

REAL_PDF_PATH = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "documents"
    / "8dff347a-1f00-4454-b0da-f6d09e795308"
    / "LSPU Student Handbook.pdf"
)
_HAS_REAL_PDF = REAL_PDF_PATH.exists()


# --- Fake Chroma (never touches a real client) -------------------------------


class FakeChromaCollection:
    def __init__(self):
        self._records: dict[str, dict] = {}
        self._documents: dict[str, str] = {}

    def add(self, *, ids, documents, metadatas):
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
        return {"ids": page, "metadatas": [self._records[i] for i in page], "documents": [self._documents[i] for i in page]}

    def delete(self, *, ids):
        for i in ids:
            self._records.pop(i, None)
            self._documents.pop(i, None)

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


# --- PDF fixtures -------------------------------------------------------------


def _make_multi_page_digital_pdf(texts: list[str]) -> bytes:
    import fitz

    doc = fitz.open()
    for text in texts:
        page = doc.new_page()
        y = 72
        for line in text.splitlines():
            page.insert_text((72, y), line)
            y += 14
    data = doc.tobytes()
    doc.close()
    return data


# --- Job row helpers -----------------------------------------------------------


def _fetch_job(job_id: str) -> IngestionJob:
    session = get_session_factory()()
    try:
        job = session.get(IngestionJob, job_id)
        session.expunge(job)
        return job
    finally:
        session.close()


def _insert_job(*, source_filename: str, status: str, pdf_bytes: bytes = b"x") -> str:
    session = get_session_factory()()
    try:
        job = IngestionJob(
            source_filename=source_filename,
            sha256_hash=uuid.uuid4().hex + uuid.uuid4().hex,
            status=status,
            pdf_bytes=pdf_bytes,
            byte_size=len(pdf_bytes),
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
    monkeypatch.setattr("app.routes.admin.knowledge_base.ingestion_available", lambda: False)


@pytest.fixture(autouse=True)
def _cleanup_test_jobs():
    yield
    assert_destructive_database_ops_allowed()
    session = get_session_factory()()
    try:
        session.query(IngestionJob).filter(IngestionJob.source_filename.like("handbook_struct_test_%")).delete(
            synchronize_session=False
        )
        session.commit()
    finally:
        session.close()


client = TestClient(app)


# === 1 & 2: persistence round-trip / backward compatibility =================


def test_extracted_pages_payload_roundtrip_with_handbook_structured():
    structured = {
        "status": STATUS_ELIGIBLE,
        "candidate_pages": [3],
        "matched_pages": [3],
        "table_regions_by_page": {
            "3": [{"bbox": [1.0, 2.0, 3.0, 4.0], "rows": [["Section/Title/Definition", "1st", "2nd", "3rd"]]}]
        },
        "words_by_page": {"3": [{"text": "Article", "x0": 1.0, "y0": 2.0, "x1": 3.0, "y1": 4.0, "cy": 3.0, "height": 2.0}]},
    }
    payload = di.extracted_pages_payload(["p1", "p2", "p3"], "pymupdf_digital", handbook_structured=structured)
    job = IngestionJob(
        id="roundtrip-job",
        source_filename="x.pdf",
        sha256_hash="a" * 64,
        status="review_ready",
        pdf_bytes=b"x",
        byte_size=1,
        extracted_pages_json=payload,
    )
    pages, method, handbook_structured = di.load_extracted_pages(job)
    assert pages == ["p1", "p2", "p3"]
    assert method == "pymupdf_digital"
    assert handbook_structured == structured


def test_load_extracted_pages_old_format_without_handbook_structured_key_is_compatible():
    old_payload = json.dumps({"pages": ["a", "b"], "extraction_method": "pymupdf_digital"})
    job = IngestionJob(
        id="old-job",
        source_filename="x.pdf",
        sha256_hash="b" * 64,
        status="review_ready",
        pdf_bytes=b"x",
        byte_size=1,
        extracted_pages_json=old_payload,
    )
    pages, method, handbook_structured = di.load_extracted_pages(job)
    assert pages == ["a", "b"]
    assert method == "pymupdf_digital"
    assert handbook_structured is None


# === 10: candidate pre-filter uses text anchors, never a hardcoded range ====


def test_find_candidate_table_pages_uses_text_anchor_not_hardcoded_range():
    anchor = "Section/Title/Definition | 1st | 2nd | 3rd"
    # The anchor appears on page 50 (index 49) of an otherwise-short document
    # -- nowhere near any page range used elsewhere in this project's own
    # investigation notes -- to prove this is a dynamic text scan, not a
    # disguised hardcoded range.
    page_texts = ["irrelevant prose" for _ in range(60)]
    page_texts[49] = f"{anchor}\nOffense | Offense | Offense\nSome row text"
    assert find_candidate_table_pages(page_texts) == [50]


def test_find_candidate_table_pages_finds_nothing_when_no_anchor_present():
    page_texts = ["irrelevant prose"] * 5
    assert find_candidate_table_pages(page_texts) == []


# === 9: non-handbook documents keep today's generic behavior ===============


def test_non_handbook_document_uses_generic_chunking_and_no_handbook_structured():
    pdf_bytes = _make_multi_page_digital_pdf(
        [
            "This is a plain announcement about the cafeteria menu this week.",
            "No policy numbering, no chapters, no disciplinary table here at all.",
        ]
    )
    store, _collection = make_fake_store()
    patches = patched_store(store)
    for p in patches:
        p.start()
    try:
        resp = client.post(
            "/admin/knowledge-base/extract",
            headers=ADMIN_HEADERS,
            files={"file": ("handbook_struct_test_non_handbook.pdf", pdf_bytes, "application/pdf")},
        )
        assert resp.status_code == 200
        job_id = resp.json()["job_id"]
        job = _fetch_job(job_id)
        assert job.status == "review_ready"
        _pages, _method, handbook_structured = di.load_extracted_pages(job)
        assert handbook_structured is None
        assert job.status_detail is None

        index_resp = client.post(
            f"/admin/knowledge-base/jobs/{job_id}/index",
            headers=ADMIN_HEADERS,
            json={"reviewed_text": None},
        )
        assert index_resp.status_code == 200
        published = _fetch_job(job_id)
        assert published.status == "published"
        for meta in _collection._records.values():
            assert meta.get("structuring_method") == "generic_chunking"
    finally:
        for p in patches:
            p.stop()


# === 5: handbook-like text, but no real matching table -> explicit warning =


def test_handbook_like_document_with_no_matching_table_gets_no_match_status_and_warning():
    pdf_bytes = _make_multi_page_digital_pdf(
        [
            "Chapter I. Student Handbook\nArticle II. Rules\nSec. 1. Introduction 1.1 Scope",
            "Section/Title/Definition | 1st | 2nd | 3rd\nOffense | Offense | Offense\n"
            "This text merely CONTAINS the header anchor words as plain prose, with no "
            "real PyMuPDF table object behind it, so find_tables() will find nothing here.",
        ]
    )
    store, _collection = make_fake_store()
    patches = patched_store(store)
    for p in patches:
        p.start()
    try:
        resp = client.post(
            "/admin/knowledge-base/extract",
            headers=ADMIN_HEADERS,
            files={"file": ("handbook_struct_test_no_match.pdf", pdf_bytes, "application/pdf")},
        )
        assert resp.status_code == 200
        job_id = resp.json()["job_id"]
        job = _fetch_job(job_id)
        assert job.status == "review_ready"

        _pages, _method, handbook_structured = di.load_extracted_pages(job)
        assert handbook_structured is not None
        assert handbook_structured["status"] == STATUS_ATTEMPTED_NO_MATCH
        assert handbook_structured["matched_pages"] == []

        # The explicit, admin-visible warning: surfaced via the existing
        # status_detail field, which the Flutter review screen already
        # renders for any non-terminal job status (review_ready included) --
        # no new API field or UI change needed.
        assert job.status_detail is not None
        assert "disciplinary-offense table" in job.status_detail

        index_resp = client.post(
            f"/admin/knowledge-base/jobs/{job_id}/index",
            headers=ADMIN_HEADERS,
            json={"reviewed_text": None},
        )
        assert index_resp.status_code == 200
        for meta in _collection._records.values():
            assert meta.get("structuring_method") == "generic_chunking"
    finally:
        for p in patches:
            p.stop()


# === 4: OCR-required documents never call find_tables()/word extraction ====


def test_ocr_required_document_never_attempts_structured_extraction(monkeypatch):
    called = {"extract_structured_handbook_data": False}

    def _tracking_extract(*args, **kwargs):
        called["extract_structured_handbook_data"] = True
        return extract_structured_handbook_data(*args, **kwargs)

    monkeypatch.setattr(di, "extract_structured_handbook_data", _tracking_extract)
    monkeypatch.setattr(di, "ocr_worker_configured", lambda: True)
    monkeypatch.setattr(di, "run_ocr_worker", lambda pdf_bytes: (["OCR'd page text"], [0]))

    import fitz

    doc = fitz.open()
    doc.new_page()  # a genuinely blank page: no digital text at all
    pdf_bytes = doc.tobytes()
    doc.close()

    store, _collection = make_fake_store()
    patches = patched_store(store)
    for p in patches:
        p.start()
    try:
        job_id = _insert_job(source_filename="handbook_struct_test_ocr.pdf", status="queued", pdf_bytes=pdf_bytes)
        di.process_extraction_preview_job(job_id)
    finally:
        for p in patches:
            p.stop()

    job = _fetch_job(job_id)
    assert job.status == "review_ready"
    _pages, method, handbook_structured = di.load_extracted_pages(job)
    assert method == "remote_ocr_worker"
    assert handbook_structured is None
    assert called["extract_structured_handbook_data"] is False


# === 6: exceptions never leak partial structured output into published chunks


def test_structured_extraction_exception_falls_back_to_generic_chunking(monkeypatch):
    def _raise(*args, **kwargs):
        raise RuntimeError("simulated structured-processing failure")

    monkeypatch.setattr(di, "build_handbook_policy_document", _raise)

    handbook_structured = {
        "status": STATUS_ELIGIBLE,
        "candidate_pages": [1],
        "matched_pages": [1],
        "table_regions_by_page": {"1": []},
        "words_by_page": {"1": []},
    }
    chunks = di.chunks_from_pages_or_reviewed_text(
        ["Some page text"],
        None,
        title="Test Handbook",
        source_filename="x.pdf",
        handbook_structured=handbook_structured,
    )
    assert chunks  # fell back to generic chunking rather than raising or returning nothing
    # Tagged distinctly from the normal/intentional generic case (Fix 2,
    # 2026-10-27 audit) -- see STRUCTURING_METHOD_GENERIC_FALLBACK's own
    # dedicated test for the full rationale.
    for chunk in chunks:
        assert chunk.metadata.get("structuring_method") == STRUCTURING_METHOD_GENERIC_FALLBACK


# === 3, 7, 8: real-PDF baseline parity + known disciplinary-example content =


def _extract_structured_handbook_data_unscoped(file_bytes: bytes, page_texts: list[str]) -> dict:
    """Test-only reference implementation: identical to
    extract_structured_handbook_data, except every page is treated as a
    "candidate" (no text-anchor pre-filter), i.e. find_tables()/word boxes
    run on all 198 pages instead of only the pre-filtered subset. Used ONLY
    to prove the pre-filter loses nothing on the real document -- never
    part of the production code path (which must stay scoped for the
    measured ~36s-vs-~6s cost difference established in this project's own
    read-only benchmark investigation)."""
    import app.services.admin.handbook_lightweight_extraction as hle

    doc = hle.fitz.open(stream=file_bytes, filetype="pdf")
    try:
        table_regions_by_page: dict[str, list[dict]] = {}
        matched_pages: list[int] = []
        for index in range(len(doc)):
            page_number = index + 1
            page = doc[index]
            regions = hle._extract_table_regions(page)
            table_regions_by_page[str(page_number)] = regions
            for table in regions:
                rows = table.get("rows") or []
                if rows and hle._disciplinary_table_header_row_matches(rows[0]):
                    matched_pages.append(page_number)
                    break
        words_by_page: dict[str, list[dict]] = {}
        for page_number in matched_pages:
            words_by_page[str(page_number)] = hle._page_word_items(doc[page_number - 1])
    finally:
        doc.close()
    status = hle.STATUS_ELIGIBLE if matched_pages else hle.STATUS_ATTEMPTED_NO_MATCH
    return {
        "status": status,
        "candidate_pages": list(range(1, len(page_texts) + 1)),
        "matched_pages": matched_pages,
        "table_regions_by_page": table_regions_by_page,
        "words_by_page": words_by_page,
    }


@pytest.mark.skipif(not _HAS_REAL_PDF, reason="local-only real handbook PDF not present on this machine")
def test_structured_pipeline_matches_direct_from_pdf_baseline_and_known_offenses():
    file_bytes = REAL_PDF_PATH.read_bytes()

    # Lightweight path's own plain-text extraction (what
    # digital_ingestion.extract_digital_text_only actually produces --
    # intentionally NOT app.utils.pdf.pymupdf_extractor's layout-
    # reconstructed .text, which is a different, "|"-joined representation
    # the generic lightweight chunking path has never used either; the two
    # are not expected to be byte-identical).
    lightweight_page_texts, _offsets = di.extract_digital_text_only(file_bytes)

    # The actual, scoped (pre-filtered) production code path.
    handbook_structured = extract_structured_handbook_data(file_bytes, lightweight_page_texts)
    assert handbook_structured is not None
    assert handbook_structured["status"] == STATUS_ELIGIBLE
    # Matches this project's own prior, independently-established finding
    # (via a dedicated read-only investigation) that the disciplinary table
    # spans pages 73-87 in this exact PDF -- found here dynamically via the
    # text-anchor pre-filter, never hardcoded.
    assert handbook_structured["matched_pages"]
    assert min(handbook_structured["matched_pages"]) >= 70
    assert max(handbook_structured["matched_pages"]) <= 90

    # Reference, unscoped computation (every page a "candidate") -- proves
    # the pre-filter (#10) loses no real match on the actual document,
    # which is the round-trip-fidelity property (#3) that actually matters
    # here: scoping table/word extraction to the pre-filtered subset must
    # produce the IDENTICAL final processor output as scanning every page.
    unscoped = _extract_structured_handbook_data_unscoped(file_bytes, lightweight_page_texts)
    assert unscoped["matched_pages"] == handbook_structured["matched_pages"]

    scoped_pages = reconstruct_page_extractions(lightweight_page_texts, handbook_structured)
    unscoped_pages = reconstruct_page_extractions(lightweight_page_texts, unscoped)
    raw = "\n\n".join(
        f"--- Page {i + 1} ---\n{(t or '').strip()}" for i, t in enumerate(lightweight_page_texts) if (t or "").strip()
    )
    scoped_doc = build_handbook_policy_document(
        raw_text=raw, page_texts=lightweight_page_texts, source_title="LSPU Student Handbook", pdf_pages=scoped_pages
    )
    unscoped_doc = build_handbook_policy_document(
        raw_text=raw, page_texts=lightweight_page_texts, source_title="LSPU Student Handbook", pdf_pages=unscoped_pages
    )

    # Round-trip fidelity (#3): scoping to the pre-filtered candidate pages
    # produces byte-identical structured output to computing table/word
    # geometry for every page -- the persisted, scoped JSON shape loses
    # nothing build_handbook_policy_document actually needed.
    scoped_pairs = [(u.title, u.content) for u in scoped_doc.units]
    unscoped_pairs = [(u.title, u.content) for u in unscoped_doc.units]
    assert scoped_pairs == unscoped_pairs

    # Final chunk metadata/content for the known disciplinary examples (#7),
    # via the actual chunks_from_pages_or_reviewed_text conversion, not just
    # the processor's raw unit output.
    chunks = di.chunks_from_pages_or_reviewed_text(
        lightweight_page_texts,
        None,
        title="LSPU Student Handbook",
        source_filename="LSPU Student Handbook.pdf",
        handbook_structured=handbook_structured,
    )
    assert all(c.metadata.get("structuring_method") == "structured_handbook_v1" for c in chunks)

    by_title = {(c.metadata.get("title") or "").strip(): c for c in chunks}

    cyberbullying = by_title["Cyber bullying or bullying"]
    assert "one (1) month" in cyberbullying.text
    assert "one (1) semester" in cyberbullying.text
    assert "Expulsion" in cyberbullying.text

    gambling = by_title["Gambling"]
    assert "one (1) week" in gambling.text
    assert "40 hours" in gambling.text
    assert "one (1) semester" in gambling.text
    # The genuinely-absent third-offense Gambling penalty must stay absent,
    # never invented/backfilled from a neighboring offense's value (#8).
    assert gambling.metadata.get("penalty_3rd_confidence") in ("empty", "unconfirmed")
    assert "Expulsion" not in gambling.text

    # 5.1 / 5.4 / 6.2 / 14.3 are titled from their own body text (these
    # disciplinary-table entries never carry a literal numeric prefix in
    # unit.title -- confirmed against this project's own existing
    # test_handbook_policy_processor.py fixtures), not a "5.1"-style
    # prefix -- so each is identified by its known, previously-verified
    # opening phrase instead of a numeric string match.
    for expected_phrase in (
        "Any severe or repeated use of",  # 5.1
        "Any slanderous statement or",  # 5.4
        "Any drunkenness or drunken",  # 6.2
        "Recruitment of an unauthor",  # 14.3
    ):
        assert expected_phrase in by_title, f"no chunk found for offense titled {expected_phrase!r}"


# =============================================================================
# 2026-10-27 audit fixes
# =============================================================================

# --- Fix 1: /admin/knowledge-base/ingest must refuse a detected handbook ---
# without a reviewed_text override, rather than silently publishing generic
# chunks with no warning (see DigitalIngestionHandbookReviewRequiredError).


def _handbook_like_pdf_bytes() -> bytes:
    # is_handbook_policy_text() needs >=2 hierarchy signals (chapter/
    # article/sec/decimal numbering) -- the exact same signal used by the
    # real document, not a special-cased string.
    return _make_multi_page_digital_pdf(
        [
            "Chapter I. Student Handbook\nArticle II. Rules\nSec. 1. Introduction 1.1 Scope",
            "Sec. 5. Discipline\n5.1 Conduct expectations for all enrolled students on campus.",
        ]
    )


def test_ingest_route_refuses_detected_handbook_without_reviewed_text():
    pdf_bytes = _handbook_like_pdf_bytes()
    store, collection = make_fake_store()
    patches = patched_store(store)
    for p in patches:
        p.start()
    try:
        resp = client.post(
            "/admin/knowledge-base/ingest",
            headers=ADMIN_HEADERS,
            files={"file": ("handbook_struct_test_ingest_refuse.pdf", pdf_bytes, "application/pdf")},
        )
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert "Extract & Structure" in detail
        assert "/admin/knowledge-base/jobs/" in detail
        # Nothing was published -- the refusal happens before any Chroma write.
        assert collection.count() == 0
    finally:
        for p in patches:
            p.stop()


def test_ingest_route_still_allows_handbook_with_explicit_reviewed_text_override():
    pdf_bytes = _handbook_like_pdf_bytes()
    store, collection = make_fake_store()
    patches = patched_store(store)
    for p in patches:
        p.start()
    try:
        resp = client.post(
            "/admin/knowledge-base/ingest",
            headers=ADMIN_HEADERS,
            data={"reviewed_text": "An explicitly reviewed and edited flat-text override."},
            files={"file": ("handbook_struct_test_ingest_override.pdf", pdf_bytes, "application/pdf")},
        )
        assert resp.status_code == 200
        assert collection.count() > 0
    finally:
        for p in patches:
            p.stop()


def test_ingest_route_non_handbook_document_still_publishes_normally():
    pdf_bytes = _make_multi_page_digital_pdf(
        ["Plain cafeteria menu announcement with no policy numbering or chapters at all."]
    )
    store, collection = make_fake_store()
    patches = patched_store(store)
    for p in patches:
        p.start()
    try:
        resp = client.post(
            "/admin/knowledge-base/ingest",
            headers=ADMIN_HEADERS,
            files={"file": ("handbook_struct_test_ingest_normal.pdf", pdf_bytes, "application/pdf")},
        )
        assert resp.status_code == 200
        assert resp.json()["chunks_indexed"] > 0
        assert collection.count() > 0
    finally:
        for p in patches:
            p.stop()


def test_ingest_route_ocr_required_document_is_unaffected_by_the_new_guard(monkeypatch):
    # OCR-required documents are never eligible for structured processing
    # on either route, so the new guard must not block them -- they should
    # behave exactly as before (fail with the pre-existing "insufficient
    # digital text" error, never the new handbook-review-required one).
    monkeypatch.setattr(di, "ocr_worker_configured", lambda: False)
    import fitz

    doc = fitz.open()
    doc.new_page()
    pdf_bytes = doc.tobytes()
    doc.close()

    store, _collection = make_fake_store()
    patches = patched_store(store)
    for p in patches:
        p.start()
    try:
        resp = client.post(
            "/admin/knowledge-base/ingest",
            headers=ADMIN_HEADERS,
            files={"file": ("handbook_struct_test_ingest_ocr.pdf", pdf_bytes, "application/pdf")},
        )
        assert resp.status_code == 422
        assert "Extract & Structure" not in resp.json()["detail"]
    finally:
        for p in patches:
            p.stop()


def test_build_lightweight_publish_raises_handbook_review_required_directly():
    """Unit-level check of the guard itself, independent of the route."""
    pdf_bytes = _handbook_like_pdf_bytes()
    store, _collection = make_fake_store()
    patches = patched_store(store)
    for p in patches:
        p.start()
    try:
        with pytest.raises(DigitalIngestionHandbookReviewRequiredError):
            di.build_lightweight_publish(
                pdf_bytes,
                filename="x.pdf",
                content_type="application/pdf",
                reviewed_text=None,
            )
    finally:
        for p in patches:
            p.stop()


# --- Fix 2: the index-time structured-fallback warning must survive to ----
# the published state, via the existing status_detail field.


def test_chunks_from_pages_or_reviewed_text_tags_fallback_distinctly_from_generic(monkeypatch):
    def _raise(*args, **kwargs):
        raise RuntimeError("simulated structured-processing failure")

    monkeypatch.setattr(di, "build_handbook_policy_document", _raise)

    handbook_structured = {
        "status": "eligible",
        "candidate_pages": [1],
        "matched_pages": [1],
        "table_regions_by_page": {"1": []},
        "words_by_page": {"1": []},
    }
    chunks = di.chunks_from_pages_or_reviewed_text(
        ["Some page text"],
        None,
        title="Test Handbook",
        source_filename="x.pdf",
        handbook_structured=handbook_structured,
    )
    assert chunks
    assert all(c.metadata.get("structuring_method") == STRUCTURING_METHOD_GENERIC_FALLBACK for c in chunks)

    # Never confused with the normal, intentional generic case.
    normal_chunks = di.chunks_from_pages_or_reviewed_text(
        ["Some page text"], None, title="Test Handbook", source_filename="x.pdf", handbook_structured=None
    )
    assert all(c.metadata.get("structuring_method") == "generic_chunking" for c in normal_chunks)


def test_index_time_structured_failure_leaves_durable_warning_on_published_job(monkeypatch):
    def _raise(*args, **kwargs):
        raise RuntimeError("simulated structured-processing failure")

    monkeypatch.setattr(di, "build_handbook_policy_document", _raise)

    handbook_structured = {
        "status": "eligible",
        "candidate_pages": [1],
        "matched_pages": [1],
        "table_regions_by_page": {"1": []},
        "words_by_page": {"1": []},
    }
    payload = di.extracted_pages_payload(
        ["Some page text"], "pymupdf_digital", handbook_structured=handbook_structured
    )
    job_id = _insert_job(source_filename="handbook_struct_test_fallback.pdf", status="indexing")
    session = get_session_factory()()
    try:
        job = session.get(IngestionJob, job_id)
        job.extracted_pages_json = payload
        session.commit()
    finally:
        session.close()

    store, collection = make_fake_store()
    patches = patched_store(store)
    for p in patches:
        p.start()
    try:
        di.process_indexing_job(job_id, None)
    finally:
        for p in patches:
            p.stop()

    published = _fetch_job(job_id)
    assert published.status == "published"
    # The durable warning, never falsely reporting success, and never lost
    # once the job reached its terminal published state.
    assert published.status_detail is not None
    assert "generic chunking was published instead" in published.status_detail
    assert "NOT applied" in published.status_detail
    for meta in collection._records.values():
        assert meta.get("structuring_method") == STRUCTURING_METHOD_GENERIC_FALLBACK


def test_index_time_structured_success_still_clears_status_detail_on_publish():
    """Regression guard: the normal (no-fallback) case must be completely
    unaffected by the Fix 2 change -- status_detail still clears to None."""
    job_id = _insert_job(source_filename="handbook_struct_test_no_fallback.pdf", status="indexing")
    payload = di.extracted_pages_payload(["Plain non-handbook page text."], "pymupdf_digital")
    session = get_session_factory()()
    try:
        job = session.get(IngestionJob, job_id)
        job.extracted_pages_json = payload
        session.commit()
    finally:
        session.close()

    store, _collection = make_fake_store()
    patches = patched_store(store)
    for p in patches:
        p.start()
    try:
        di.process_indexing_job(job_id, None)
    finally:
        for p in patches:
            p.stop()

    published = _fetch_job(job_id)
    assert published.status == "published"
    assert published.status_detail is None


def test_index_time_never_eligible_preserves_warning_on_published_job():
    """2026-10-31 fix: a document that was never eligible for structured
    processing (STATUS_ATTEMPTED_NO_MATCH at review time) and gets indexed
    anyway, without a reviewed_text override, must still carry a
    meaningful warning once published -- the review-time warning
    (test_handbook_like_document_with_no_matching_table_gets_no_match_status_and_warning)
    must not be silently dropped just because the admin proceeded."""
    handbook_structured = {
        "status": STATUS_ATTEMPTED_NO_MATCH,
        "candidate_pages": [1],
        "matched_pages": [],
        "table_regions_by_page": {"1": []},
        "words_by_page": {},
    }
    payload = di.extracted_pages_payload(
        ["Some handbook-like page text with no matching table."],
        "pymupdf_digital",
        handbook_structured=handbook_structured,
    )
    job_id = _insert_job(source_filename="handbook_struct_test_never_eligible.pdf", status="indexing")
    session = get_session_factory()()
    try:
        job = session.get(IngestionJob, job_id)
        job.extracted_pages_json = payload
        session.commit()
    finally:
        session.close()

    store, collection = make_fake_store()
    patches = patched_store(store)
    for p in patches:
        p.start()
    try:
        di.process_indexing_job(job_id, None)
    finally:
        for p in patches:
            p.stop()

    published = _fetch_job(job_id)
    assert published.status == "published"
    # The published job must still carry a meaningful warning -- not
    # silently cleared to None as if the table correction had been applied.
    assert published.status_detail is not None
    assert "disciplinary-offense table structure could not be confirmed" in published.status_detail
    assert "NOT applied" in published.status_detail
    for meta in collection._records.values():
        assert meta.get("structuring_method") == di.STRUCTURING_METHOD_GENERIC


def test_index_time_never_eligible_with_reviewed_text_override_clears_warning():
    """Regression guard for the Fix 3 change: an explicit reviewed_text
    override means the admin's own edit, not the missing table structure,
    is what actually got published -- status_detail must still clear to
    None exactly as before, never carry the never-eligible warning."""
    handbook_structured = {
        "status": STATUS_ATTEMPTED_NO_MATCH,
        "candidate_pages": [1],
        "matched_pages": [],
        "table_regions_by_page": {"1": []},
        "words_by_page": {},
    }
    payload = di.extracted_pages_payload(
        ["Some handbook-like page text with no matching table."],
        "pymupdf_digital",
        handbook_structured=handbook_structured,
    )
    job_id = _insert_job(source_filename="handbook_struct_test_never_eligible_override.pdf", status="indexing")
    session = get_session_factory()()
    try:
        job = session.get(IngestionJob, job_id)
        job.extracted_pages_json = payload
        session.commit()
    finally:
        session.close()

    store, _collection = make_fake_store()
    patches = patched_store(store)
    for p in patches:
        p.start()
    try:
        di.process_indexing_job(job_id, "The admin's own reviewed replacement text.")
    finally:
        for p in patches:
            p.stop()

    published = _fetch_job(job_id)
    assert published.status == "published"
    assert published.status_detail is None
