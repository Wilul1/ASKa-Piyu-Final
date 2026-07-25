"""Baseline schema helpers + user lifecycle columns.

Revision ID: 20260725_0001
Revises:
Create Date: 2026-07-25
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260725_0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Ensure ORM tables exist for fresh databases.
    from app.db.base import Base
    from app.models import db_models  # noqa: F401

    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)

    # Additive lifecycle columns (safe on existing DBs).
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE"
    )
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS credentials_version INTEGER NOT NULL DEFAULT 0"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS credentials_version")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS is_active")
