"""Ensure office_aliases.is_active (and other additive columns) exist.

Revision ID: 20260725_0004
Revises: 20260725_0003
Create Date: 2026-07-25
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260725_0004"
down_revision: Union[str, Sequence[str], None] = "20260725_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from app.db.schema_upgrades import apply_additive_schema_upgrades

    apply_additive_schema_upgrades(op.get_bind())


def downgrade() -> None:
    pass
