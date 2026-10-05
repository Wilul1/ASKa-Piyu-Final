"""Add extracted_pages_json + review_ready/indexing statuses to ingestion_jobs.

Revision ID: 20261005_0011
Revises: 20261004_0010
Create Date: 2026-10-05

Supports splitting the Heroku-web-dyno document pipeline into two phases
(preview-only extraction, then a separate publish step) so a slow remote-OCR
extraction can run in the background without the admin UI's synchronous
request ever risking Heroku's 30s router timeout (H12) -- see
app/services/admin/digital_ingestion.py's process_extraction_preview_job /
process_indexing_job.

Additive/reversible:
  - extracted_pages_json: new NULLable Text column. Existing rows get NULL
    (SQLAlchemy/Postgres default for a new nullable column -- no backfill,
    no fake extraction data). Holds a small JSON object
    {"pages": [...], "extraction_method": "..."} for a job once its
    (possibly OCR'd) page texts are known but nothing has been published
    yet -- never the full preview/knowledge-units/validation payload, which
    is cheap to rebuid from these page texts on demand.
  - ck_ingestion_jobs_status: widened to additionally allow 'review_ready'
    and 'indexing'. All six existing values (including 'needs_reconciliation'
    and 'ocr_required') are preserved unchanged, so historical rows --
    including the LSPU Student Handbook's needs_reconciliation row -- remain
    valid and are never rewritten or touched by this migration.

Downgrade note (same caveat as 20261004_0010's downgrade): re-narrowing the
CHECK constraint will raise an IntegrityError if any row currently has
status='review_ready' or 'indexing' -- intentional; this migration does not
delete or rewrite rows to force a downgrade through. Dropping
extracted_pages_json after narrowing the constraint discards whatever was
stored there, which is safe by construction: a job can only reach
review_ready/indexing while this migration is applied, so after a clean
downgrade no row holding meaningful data in that column should remain in
disallowed states anyway.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy import Column, Text, inspect

revision: str = "20261005_0011"
down_revision: Union[str, None] = "20261004_0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CHECK_NAME = "ck_ingestion_jobs_status"
_OLD_STATUSES = "'queued','processing','published','failed','ocr_required','needs_reconciliation'"
_NEW_STATUSES = (
    "'queued','processing','published','failed','ocr_required',"
    "'needs_reconciliation','review_ready','indexing'"
)


def upgrade() -> None:
    bind = op.get_bind()
    if not inspect(bind).has_table("ingestion_jobs"):
        return

    columns = {c["name"] for c in inspect(bind).get_columns("ingestion_jobs")}
    if "extracted_pages_json" not in columns:
        op.add_column("ingestion_jobs", Column("extracted_pages_json", Text(), nullable=True))

    op.drop_constraint(_CHECK_NAME, "ingestion_jobs", type_="check")
    op.create_check_constraint(_CHECK_NAME, "ingestion_jobs", f"status IN ({_NEW_STATUSES})")


def downgrade() -> None:
    bind = op.get_bind()
    if not inspect(bind).has_table("ingestion_jobs"):
        return

    op.drop_constraint(_CHECK_NAME, "ingestion_jobs", type_="check")
    # Raises IntegrityError if any row has status='review_ready'/'indexing' --
    # intentional; see module docstring.
    op.create_check_constraint(_CHECK_NAME, "ingestion_jobs", f"status IN ({_OLD_STATUSES})")

    columns = {c["name"] for c in inspect(bind).get_columns("ingestion_jobs")}
    if "extracted_pages_json" in columns:
        op.drop_column("ingestion_jobs", "extracted_pages_json")
