"""Tests for the 20261005_0011 migration: adds extracted_pages_json and
widens ingestion_jobs' status CHECK to allow review_ready/indexing.

Runs against the real Postgres test database (same convention as
test_ingest_digital_retry.py's schema-assertion tests) since this
migration's DDL (CHECK constraint drop/recreate) is Postgres-specific.
"""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app.db.safety import assert_destructive_database_ops_allowed
from app.db.session import get_engine, get_session_factory
from app.models.db_models import IngestionJob

REVISION_PATH = (
    Path(__file__).resolve().parents[1] / "alembic" / "versions" / "20261005_0011_ingestion_jobs_review_ready.py"
)


def _load_revision():
    spec = importlib.util.spec_from_file_location("alembic_rev_0011", REVISION_PATH)
    assert spec is not None and spec.loader is not None
    rev = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rev)
    return rev


def _insert_job(*, status: str, filename: str | None = None) -> str:
    session = get_session_factory()()
    try:
        job = IngestionJob(
            source_filename=filename or f"migration_test_{uuid.uuid4().hex}.pdf",
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
def _cleanup_test_jobs():
    yield
    assert_destructive_database_ops_allowed()
    session = get_session_factory()()
    try:
        session.query(IngestionJob).filter(IngestionJob.source_filename.like("migration_test_%")).delete(
            synchronize_session=False
        )
        session.commit()
    finally:
        session.close()


# --- 1/5: migration upgrades successfully; review_ready/indexing are valid -


def test_revision_metadata_chains_onto_0010():
    rev = _load_revision()
    assert rev.revision == "20261005_0011"
    assert rev.down_revision == "20261004_0010"


def test_extracted_pages_json_column_exists_and_is_nullable():
    engine = get_engine()
    columns = {c["name"]: c for c in inspect(engine).get_columns("ingestion_jobs")}
    assert "extracted_pages_json" in columns
    assert columns["extracted_pages_json"]["nullable"] is True


def test_existing_rows_received_null_for_extracted_pages_json():
    """No backfill, no fake extraction data for rows that predate this column."""
    job_id = _insert_job(status="failed")
    session = get_session_factory()()
    try:
        job = session.get(IngestionJob, job_id)
        assert job.extracted_pages_json is None
    finally:
        session.close()


def test_review_ready_and_indexing_statuses_are_valid():
    review_ready_id = _insert_job(status="review_ready")
    indexing_id = _insert_job(status="indexing")
    session = get_session_factory()()
    try:
        assert session.get(IngestionJob, review_ready_id).status == "review_ready"
        assert session.get(IngestionJob, indexing_id).status == "indexing"
    finally:
        session.close()


# --- 4: needs_reconciliation (and every other historical status) is still valid


@pytest.mark.parametrize(
    "status", ["queued", "processing", "published", "failed", "ocr_required", "needs_reconciliation"]
)
def test_all_historical_statuses_remain_valid(status):
    job_id = _insert_job(status=status)
    session = get_session_factory()()
    try:
        assert session.get(IngestionJob, job_id).status == status
    finally:
        session.close()


# --- 6: invalid statuses remain rejected ------------------------------------


def test_invalid_status_is_still_rejected():
    with pytest.raises(IntegrityError):
        _insert_job(status="not_a_real_status")


# --- 3: a pre-existing historical row survives the migration unchanged -----
# (simulated here: the real historical LSPU Student Handbook
# needs_reconciliation row was created long before this migration existed
# and must never be rewritten by it -- re-asserting its exact column set
# and that this migration's upgrade() is a no-op for already-migrated rows.)


def test_a_simulated_historical_needs_reconciliation_row_is_unaffected_by_rerunning_upgrade():
    historical_id = _insert_job(status="needs_reconciliation", filename="migration_test_HISTORICAL.pdf")
    session = get_session_factory()()
    try:
        before = session.get(IngestionJob, historical_id)
        before_status, before_error, before_extracted = (
            before.status,
            before.error_message,
            before.extracted_pages_json,
        )
    finally:
        session.close()

    rev = _load_revision()
    engine = get_engine()
    with engine.begin() as conn:
        from alembic.operations import Operations
        from alembic.runtime.migration import MigrationContext

        context = MigrationContext.configure(conn)
        with Operations.context(context):
            rev.upgrade()  # idempotent re-run: must not raise, must not rewrite rows

    session = get_session_factory()()
    try:
        after = session.get(IngestionJob, historical_id)
        assert after.status == before_status == "needs_reconciliation"
        assert after.error_message == before_error
        assert after.extracted_pages_json == before_extracted
    finally:
        session.close()


# --- 2: migration downgrades successfully (then re-upgraded for the rest of
# the suite, which depends on the widened schema being present) -----------


def test_migration_downgrade_then_upgrade_round_trip():
    rev = _load_revision()
    engine = get_engine()

    # Clean slate: no row may hold a status the downgrade's narrower CHECK
    # would reject (this is the documented, intentional behavior -- see the
    # migration's own docstring -- not something this test works around).
    session = get_session_factory()()
    try:
        stuck = (
            session.query(IngestionJob)
            .filter(IngestionJob.status.in_(["review_ready", "indexing"]))
            .count()
        )
    finally:
        session.close()
    assert stuck == 0, "a leftover review_ready/indexing row would make downgrade legitimately fail"

    try:
        with engine.begin() as conn:
            from alembic.operations import Operations
            from alembic.runtime.migration import MigrationContext

            context = MigrationContext.configure(conn)
            with Operations.context(context):
                rev.downgrade()

        # Narrower constraint now active: review_ready must be rejected.
        # Raw SQL (not the ORM-mapped IngestionJob class, which still
        # expects extracted_pages_json -- already dropped at this point)
        # against exactly the pre-0011 column set, isolating the check to
        # the status CHECK constraint itself.
        with engine.connect() as conn:
            trans = conn.begin()
            try:
                with pytest.raises(IntegrityError):
                    conn.execute(
                        text(
                            "INSERT INTO ingestion_jobs "
                            "(id, source_filename, sha256_hash, status, pdf_bytes, byte_size) "
                            "VALUES (:id, :fn, :sha, 'review_ready', :pdf, 1)"
                        ),
                        {
                            "id": str(uuid.uuid4()),
                            "fn": "migration_test_downgrade_reject.pdf",
                            "sha": uuid.uuid4().hex,
                            "pdf": b"x",
                        },
                    )
            finally:
                trans.rollback()  # the failed INSERT aborts the transaction either way

        columns = {c["name"] for c in inspect(engine).get_columns("ingestion_jobs")}
        assert "extracted_pages_json" not in columns
    finally:
        # Always restore head -- every other test in the suite depends on
        # the widened schema being present.
        with engine.begin() as conn:
            from alembic.operations import Operations
            from alembic.runtime.migration import MigrationContext

            context = MigrationContext.configure(conn)
            with Operations.context(context):
                rev.upgrade()

    columns_after = {c["name"] for c in inspect(get_engine()).get_columns("ingestion_jobs")}
    assert "extracted_pages_json" in columns_after
    review_ready_id = _insert_job(status="review_ready")
    session = get_session_factory()()
    try:
        assert session.get(IngestionJob, review_ready_id).status == "review_ready"
    finally:
        session.close()
