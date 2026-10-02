"""Add ingestion_jobs table for zero-cost digital-PDF background ingestion.

Revision ID: 20261002_0009
Revises: 20260915_0008
Create Date: 2026-10-02

Stores the full ingestion job lifecycle (queued -> processing -> published /
failed / ocr_required / needs_reconciliation) entirely in the existing
Heroku Postgres instance -- no Redis, no new service. ``pdf_bytes`` holds the
original uploaded file (Postgres BYTEA) since the Heroku web dyno's local
filesystem is ephemeral; this replaces the local-disk assumption for this
new ingestion path only (existing ``source_documents.stored_file_path`` is
untouched).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "20261002_0009"
down_revision: Union[str, None] = "20260915_0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if inspect(bind).has_table("ingestion_jobs"):
        return

    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("source_filename", sa.String(length=255), nullable=False),
        sa.Column("sha256_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="queued"),
        sa.Column("status_detail", sa.Text(), nullable=True),
        sa.Column("pdf_bytes", sa.LargeBinary(), nullable=False),
        sa.Column("content_type", sa.String(length=120), nullable=True),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("document_id", sa.String(length=36), nullable=True),
        sa.Column("replaced_document_id", sa.String(length=36), nullable=True),
        sa.Column("chunks_indexed", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('queued','processing','published','failed','ocr_required','needs_reconciliation')",
            name="ck_ingestion_jobs_status",
        ),
    )
    op.create_index("ix_ingestion_jobs_sha256_hash", "ingestion_jobs", ["sha256_hash"], unique=True)
    op.create_index("ix_ingestion_jobs_status", "ingestion_jobs", ["status"])
    op.create_index("ix_ingestion_jobs_document_id", "ingestion_jobs", ["document_id"])


def downgrade() -> None:
    bind = op.get_bind()
    if inspect(bind).has_table("ingestion_jobs"):
        op.drop_table("ingestion_jobs")
