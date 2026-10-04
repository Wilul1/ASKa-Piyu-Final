"""Allow retrying a failed digital-ingestion job with the same file.

Revision ID: 20261004_0010
Revises: 20261002_0009
Create Date: 2026-10-04

Root cause fix: sha256_hash was globally UNIQUE (ix_ingestion_jobs_sha256_hash),
so once a job for a given file failed, that exact file could never be
submitted again -- the duplicate-detection query matched the failed row
forever and returned its stale failure instead of creating a new attempt
(discovered 2026-10-04 while retrying the LSPU Student Handbook).

Replaces the global unique index with:
  - a plain (non-unique) index on sha256_hash, for lookup performance.
  - a PARTIAL unique index on sha256_hash, restricted to rows whose status
    is 'queued' or 'processing'. This is the actual concurrency guard for
    "only one active job per file at a time" -- see
    app/routes/admin/knowledge_base.py's IntegrityError handling for the
    race this protects against. It is enforced by Postgres, not by an
    application-only check-then-insert.

Historical failed/published/needs_reconciliation/ocr_required rows for the
same hash are now retained side by side (e.g. attempt 1 -> failed, attempt
2 -> published), which is the intended audit trail.

Downgrade note: restoring full uniqueness will fail with an IntegrityError
if any sha256_hash now has more than one row (which is the whole point of
this migration, and expected once a retry has happened) -- that data
conflict cannot be resolved automatically and this migration does not
attempt to delete or merge historical rows to force it through.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "20261004_0010"
down_revision: Union[str, None] = "20261002_0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LOOKUP_INDEX = "ix_ingestion_jobs_sha256_hash"
_PARTIAL_UNIQUE_INDEX = "uq_ingestion_jobs_sha256_active_status"


def upgrade() -> None:
    bind = op.get_bind()
    if not inspect(bind).has_table("ingestion_jobs"):
        return

    existing_indexes = {idx["name"] for idx in inspect(bind).get_indexes("ingestion_jobs")}

    if _LOOKUP_INDEX in existing_indexes:
        op.drop_index(_LOOKUP_INDEX, table_name="ingestion_jobs")
    op.create_index(_LOOKUP_INDEX, "ingestion_jobs", ["sha256_hash"], unique=False)

    if _PARTIAL_UNIQUE_INDEX not in existing_indexes:
        op.create_index(
            _PARTIAL_UNIQUE_INDEX,
            "ingestion_jobs",
            ["sha256_hash"],
            unique=True,
            postgresql_where=sa.text("status IN ('queued', 'processing')"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    if not inspect(bind).has_table("ingestion_jobs"):
        return

    existing_indexes = {idx["name"] for idx in inspect(bind).get_indexes("ingestion_jobs")}

    if _PARTIAL_UNIQUE_INDEX in existing_indexes:
        op.drop_index(_PARTIAL_UNIQUE_INDEX, table_name="ingestion_jobs")
    if _LOOKUP_INDEX in existing_indexes:
        op.drop_index(_LOOKUP_INDEX, table_name="ingestion_jobs")

    # Will raise IntegrityError here if any sha256_hash has 2+ rows --
    # intentional; see module docstring.
    op.create_index(_LOOKUP_INDEX, "ingestion_jobs", ["sha256_hash"], unique=True)
