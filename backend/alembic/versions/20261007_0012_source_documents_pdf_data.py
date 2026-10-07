"""Add durable pdf_data column to source_documents.

Revision ID: 20261007_0012
Revises: 20261005_0011
Create Date: 2026-10-07

The local filesystem store under ``documents_persist_dir`` lives on the web
dyno's ephemeral disk -- any file written there is lost on the next dyno
restart or deploy, even though the ``source_documents`` row describing it
survives in Postgres. This was confirmed in production on 2026-10-07: every
``source_documents`` row for the three flagship documents (Student Handbook,
Faculty Manual, Citizen's Charter) correctly matches its Chroma
``document_id``, but the backing file is gone from every current dyno.

``pdf_data`` gives ``source_documents`` the same durable-bytes-in-Postgres
pattern already used by ``ingestion_jobs.pdf_bytes`` (LargeBinary, which
survives dyno restarts because it lives in the Postgres add-on, not on
dyno-local disk). The local filesystem copy is kept as a best-effort cache;
``pdf_data`` becomes the actual source of truth going forward.

Additive/reversible:
  - pdf_data: new NULLable LargeBinary column. Existing rows get NULL --
    no backfill is performed by this migration (a separate, explicitly
    opt-in backfill utility handles that). No existing row is rewritten,
    rewritten, or deleted.
  - Downgrade drops the column, discarding any bytes stored in it -- safe
    by construction, since nothing outside this feature reads/writes it.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy import Column, LargeBinary, inspect

revision: str = "20261007_0012"
down_revision: Union[str, None] = "20261005_0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if not inspect(bind).has_table("source_documents"):
        return

    columns = {c["name"] for c in inspect(bind).get_columns("source_documents")}
    if "pdf_data" not in columns:
        op.add_column("source_documents", Column("pdf_data", LargeBinary(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if not inspect(bind).has_table("source_documents"):
        return

    columns = {c["name"] for c in inspect(bind).get_columns("source_documents")}
    if "pdf_data" in columns:
        op.drop_column("source_documents", "pdf_data")
