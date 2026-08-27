"""Add email verification columns to users (additive schema upgrade).

Revision ID: 20260801_0005
Revises: 20260725_0004
Create Date: 2026-08-01
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260801_0005"
down_revision: Union[str, Sequence[str], None] = "20260725_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from app.db.schema_upgrades import apply_additive_schema_upgrades

    apply_additive_schema_upgrades(op.get_bind())


def downgrade() -> None:
    # Additive-only: do not drop campus columns/data on downgrade.
    pass
