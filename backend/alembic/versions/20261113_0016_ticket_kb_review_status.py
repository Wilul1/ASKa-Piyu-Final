"""Add ticket-to-KB review status columns and conversion statuses.

Revision ID: 20261113_0016
Revises: 20261104_0015
Create Date: 2026-11-13

Additive only:
- Expand tickets.kb_conversion_status CHECK to include needs_review/failed/rejected
- Add published_articles.needs_manual_completion / review_status / generation_notes

Does not touch ChromaDB, evaluation tables, or extraction/ingestion schemas.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20261113_0016"
down_revision: Union[str, None] = "20261104_0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Idempotent additive SQL — safe if partially applied by older startup upgrades.
    statements = (
        "ALTER TABLE tickets DROP CONSTRAINT IF EXISTS ck_tickets_kb_conversion_status",
        "ALTER TABLE tickets ADD CONSTRAINT ck_tickets_kb_conversion_status "
        "CHECK (kb_conversion_status IN ('none', 'draft', 'needs_review', 'published', 'failed', 'rejected'))",
        "ALTER TABLE published_articles ADD COLUMN IF NOT EXISTS needs_manual_completion "
        "BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE published_articles ADD COLUMN IF NOT EXISTS review_status VARCHAR(20)",
        "ALTER TABLE published_articles ADD COLUMN IF NOT EXISTS generation_notes VARCHAR(80)",
        "ALTER TABLE published_articles DROP CONSTRAINT IF EXISTS ck_published_articles_review_status",
        "ALTER TABLE published_articles ADD CONSTRAINT ck_published_articles_review_status "
        "CHECK (review_status IS NULL OR review_status IN ('pending', 'approved', 'rejected'))",
    )
    for statement in statements:
        op.execute(statement)


def downgrade() -> None:
    # Keep columns (data-preserving). Only restore the narrower status CHECK.
    op.execute("ALTER TABLE tickets DROP CONSTRAINT IF EXISTS ck_tickets_kb_conversion_status")
    op.execute(
        "ALTER TABLE tickets ADD CONSTRAINT ck_tickets_kb_conversion_status "
        "CHECK (kb_conversion_status IN ('none', 'draft', 'published'))"
    )
    op.execute(
        "ALTER TABLE published_articles DROP CONSTRAINT IF EXISTS "
        "ck_published_articles_review_status"
    )
