"""Tests for the ingestion-job retry-after-failure fix (2026-10-04).

Root cause: sha256_hash was globally unique on ingestion_jobs, so once a
job for a given file failed, the exact same file could never be submitted
again -- duplicate detection matched the failed row forever. These tests
exercise the real POST /admin/knowledge-base/ingest-digital route and the
real Postgres test database (never Chroma, never the real background
pipeline -- process_ingestion_job is patched to a no-op so only the
job-creation/dedup logic itself is under test).
"""

from __future__ import annotations

import threading
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app.db.safety import assert_destructive_database_ops_allowed
from app.db.session import get_engine, get_session_factory
from app.main import app
from app.models.db_models import IngestionJob

client = TestClient(app)

ADMIN_HEADERS = {"x-admin-key": "test-admin-key"}
MINIMAL_PDF_BYTES = b"%PDF-1.4\n%fake test pdf for retry-fix tests\n%%EOF"


@pytest.fixture(autouse=True)
def _admin_key(monkeypatch):
    monkeypatch.setattr("app.routes.admin.knowledge_base.settings.admin_api_key", "test-admin-key")


@pytest.fixture(autouse=True)
def _no_real_background_processing(monkeypatch):
    """The route schedules process_ingestion_job as a BackgroundTask, which
    TestClient runs synchronously before .post() returns. Replace it with a
    no-op so these tests cover only job creation/dedup, never the real
    Chroma/embedding pipeline."""
    monkeypatch.setattr("app.routes.admin.knowledge_base.process_ingestion_job", lambda job_id: None)


@pytest.fixture(autouse=True)
def _cleanup_test_jobs():
    yield
    assert_destructive_database_ops_allowed()
    session = get_session_factory()()
    try:
        session.query(IngestionJob).filter(IngestionJob.source_filename.like("retry_fix_test_%")).delete(
            synchronize_session=False
        )
        session.commit()
    finally:
        session.close()


def _make_pdf_bytes(marker: str) -> bytes:
    """Distinct content (-> distinct sha256) per marker, still a valid-looking PDF."""
    return MINIMAL_PDF_BYTES + marker.encode("utf-8")


def _insert_job(*, sha256_hash: str, status: str, filename: str = None) -> str:
    session = get_session_factory()()
    try:
        job = IngestionJob(
            source_filename=filename or f"retry_fix_test_{uuid.uuid4().hex}.pdf",
            sha256_hash=sha256_hash,
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


def _upload(content: bytes, filename: str = "retry_fix_test_handbook.pdf"):
    return client.post(
        "/admin/knowledge-base/ingest-digital",
        headers=ADMIN_HEADERS,
        files={"file": (filename, content, "application/pdf")},
    )


def _sha256(content: bytes) -> str:
    import hashlib

    return hashlib.sha256(content).hexdigest()


# --- A / B: failed -> new job created, old failed row untouched -----------


def test_A_same_hash_failed_creates_a_new_job():
    content = _make_pdf_bytes("scenario-A")
    old_job_id = _insert_job(sha256_hash=_sha256(content), status="failed")

    response = _upload(content)

    assert response.status_code == 200
    data = response.json()
    assert data["duplicate_of_existing_job"] is False
    assert data["job_id"] != old_job_id
    assert data["status"] == "queued"


def test_B_old_failed_job_remains_unchanged_after_retry():
    content = _make_pdf_bytes("scenario-B")
    sha = _sha256(content)
    old_job_id = _insert_job(sha256_hash=sha, status="failed")

    _upload(content)

    session = get_session_factory()()
    try:
        old_job = session.get(IngestionJob, old_job_id)
        assert old_job is not None
        assert old_job.status == "failed"
        rows_for_hash = session.query(IngestionJob).filter(IngestionJob.sha256_hash == sha).all()
        assert len(rows_for_hash) == 2  # old failed row + new queued row, both retained
    finally:
        session.close()


# --- C / D: active jobs are returned as duplicates, no new row -------------


@pytest.mark.parametrize("active_status", ["queued", "processing"])
def test_C_D_same_hash_active_status_returns_existing_job(active_status):
    content = _make_pdf_bytes(f"scenario-active-{active_status}")
    sha = _sha256(content)
    existing_id = _insert_job(sha256_hash=sha, status=active_status)

    response = _upload(content)

    assert response.status_code == 200
    data = response.json()
    assert data["duplicate_of_existing_job"] is True
    assert data["job_id"] == existing_id
    assert data["status"] == active_status

    session = get_session_factory()()
    try:
        rows_for_hash = session.query(IngestionJob).filter(IngestionJob.sha256_hash == sha).all()
        assert len(rows_for_hash) == 1  # no new row was created
    finally:
        session.close()


# --- E: published -- current safe duplicate behavior preserved ------------


def test_E_same_hash_published_returns_existing_job_not_reingested():
    content = _make_pdf_bytes("scenario-E")
    sha = _sha256(content)
    existing_id = _insert_job(sha256_hash=sha, status="published")

    response = _upload(content)

    assert response.status_code == 200
    data = response.json()
    assert data["duplicate_of_existing_job"] is True
    assert data["job_id"] == existing_id
    assert data["status"] == "published"


# --- F: needs_reconciliation -- retry blocked ------------------------------


def test_F_same_hash_needs_reconciliation_blocks_retry():
    content = _make_pdf_bytes("scenario-F")
    sha = _sha256(content)
    existing_id = _insert_job(sha256_hash=sha, status="needs_reconciliation")

    response = _upload(content)

    assert response.status_code == 200
    data = response.json()
    assert data["duplicate_of_existing_job"] is True
    assert data["job_id"] == existing_id
    assert data["status"] == "needs_reconciliation"

    session = get_session_factory()()
    try:
        rows_for_hash = session.query(IngestionJob).filter(IngestionJob.sha256_hash == sha).all()
        assert len(rows_for_hash) == 1  # never auto-retried
    finally:
        session.close()


# --- ocr_required: documented, deliberate choice (also blocks a retry) ----


def test_ocr_required_same_hash_is_also_treated_as_a_blocking_duplicate():
    """Deliberate choice (see knowledge_base.py comment + report): identical
    bytes extract identical digital text deterministically, so a retry of
    the exact same file would just land on ocr_required again. A real
    "retry" for this case means uploading an actually-different (OCR'd)
    file, which gets a different hash and is unaffected by this check."""
    content = _make_pdf_bytes("scenario-ocr-required")
    sha = _sha256(content)
    existing_id = _insert_job(sha256_hash=sha, status="ocr_required")

    response = _upload(content)

    assert response.status_code == 200
    data = response.json()
    assert data["duplicate_of_existing_job"] is True
    assert data["job_id"] == existing_id
    assert data["status"] == "ocr_required"


# --- G: concurrent/simultaneous retry protection ---------------------------


def test_G_db_level_partial_unique_index_rejects_two_simultaneous_active_rows():
    """Direct proof the constraint the route's IntegrityError handler relies
    on actually exists and is enforced by Postgres, not just application
    logic: two ACTIVE rows for the same hash can never coexist, but an
    active + a historical failed row can."""
    sha = "G_" + uuid.uuid4().hex
    _insert_job(sha256_hash=sha, status="failed")  # historical row: fine
    _insert_job(sha256_hash=sha, status="queued")  # first active row: fine

    with pytest.raises(IntegrityError):
        _insert_job(sha256_hash=sha, status="processing")  # second active row: must fail


def test_G_concurrent_uploads_of_a_brand_new_file_never_double_create_or_500():
    content = _make_pdf_bytes("scenario-G-concurrent-" + uuid.uuid4().hex)
    sha = _sha256(content)

    results: list = []
    barrier = threading.Barrier(2)

    def worker():
        barrier.wait()
        results.append(_upload(content, filename="retry_fix_test_concurrent.pdf"))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert len(results) == 2
    for r in results:
        assert r.status_code == 200  # never a raw 500/IntegrityError leak

    job_ids = {r.json()["job_id"] for r in results}
    duplicate_flags = [r.json()["duplicate_of_existing_job"] for r in results]
    # Exactly one row for this hash ever exists afterward, and both
    # responses agree on which job won the race.
    assert len(job_ids) == 1
    assert duplicate_flags.count(False) == 1
    assert duplicate_flags.count(True) == 1

    session = get_session_factory()()
    try:
        rows_for_hash = session.query(IngestionJob).filter(IngestionJob.sha256_hash == sha).all()
        assert len(rows_for_hash) == 1
    finally:
        session.close()


# --- H: different hash -- normal new ingestion -----------------------------


def test_H_different_hash_is_a_normal_new_ingestion():
    content = _make_pdf_bytes("scenario-H-" + uuid.uuid4().hex)

    response = _upload(content)

    assert response.status_code == 200
    data = response.json()
    assert data["duplicate_of_existing_job"] is False
    assert data["status"] == "queued"


# --- I: schema/migration ----------------------------------------------------


def test_I_sha256_hash_index_is_no_longer_globally_unique():
    engine = get_engine()
    indexes = {idx["name"]: idx for idx in inspect(engine).get_indexes("ingestion_jobs")}
    assert "ix_ingestion_jobs_sha256_hash" in indexes
    assert indexes["ix_ingestion_jobs_sha256_hash"]["unique"] is False


def test_I_partial_unique_index_on_active_statuses_exists():
    engine = get_engine()
    indexes = {idx["name"]: idx for idx in inspect(engine).get_indexes("ingestion_jobs")}
    assert "uq_ingestion_jobs_sha256_active_status" in indexes
    partial = indexes["uq_ingestion_jobs_sha256_active_status"]
    assert partial["unique"] is True
    assert partial["column_names"] == ["sha256_hash"]


def test_I_historical_rows_for_the_same_hash_can_coexist_in_the_db():
    sha = "I_" + uuid.uuid4().hex
    _insert_job(sha256_hash=sha, status="failed")
    _insert_job(sha256_hash=sha, status="published")

    session = get_session_factory()()
    try:
        rows = session.query(IngestionJob).filter(IngestionJob.sha256_hash == sha).all()
        assert sorted(r.status for r in rows) == ["failed", "published"]
    finally:
        session.close()
