"""Add article_media table and published_articles.content_format.

Revision ID: 20260915_0008
Revises: 20260815_0007
Create Date: 2026-09-15

Production effect (when later applied):
- Adds content_format VARCHAR(20) NOT NULL DEFAULT 'plain' on published_articles.
  Existing rows stay 'plain'; body text is not rewritten.
- Creates article_media for inline images and attachments stored under kb_media_dir.

Like 20260725_0003 and 20260801_0005, this applies the shared, idempotent
``ADDITIVE_SCHEMA_STATEMENTS`` (IF NOT EXISTS / DROP+ADD CONSTRAINT guards)
instead of duplicating SQL here, so schema_upgrades.py stays the single
source of truth for what "up to date" means and a campus DB upgraded via
``alembic upgrade head`` alone matches the code.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260915_0008"
down_revision: Union[str, None] = "20260815_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from app.db.schema_upgrades import apply_additive_schema_upgrades

    apply_additive_schema_upgrades(op.get_bind())


def downgrade() -> None:
    import sqlalchemy as sa

    # Unlike the additive-only campus-column migrations, article_media/content_format
    # are wholly new in this revision, so a downgrade safely removes exactly what
    # this revision added rather than any pre-existing campus data.
    op.execute(sa.text("DROP TABLE IF EXISTS article_media"))
    op.execute(sa.text("ALTER TABLE published_articles DROP CONSTRAINT IF EXISTS ck_published_articles_content_format"))
    op.execute(sa.text("ALTER TABLE published_articles DROP COLUMN IF EXISTS content_format"))
