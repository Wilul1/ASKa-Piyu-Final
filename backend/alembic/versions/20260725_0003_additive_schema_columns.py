"""Apply additive columns/indexes expected by the ORM (prod Alembic path).

Revision ID: 20260725_0003
Revises: 20260725_0002
Create Date: 2026-07-25

With ASKA_DATABASE_INIT_ON_STARTUP=false, startup no longer runs ALTER TABLE
upgrades. This revision applies the same idempotent statements so a campus DB
upgraded via ``alembic upgrade head`` alone matches the code.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260725_0003"
down_revision: Union[str, Sequence[str], None] = "20260725_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from app.db.schema_upgrades import apply_additive_schema_upgrades

    apply_additive_schema_upgrades(op.get_bind())


def downgrade() -> None:
    # Additive-only: do not drop campus columns/data on downgrade.
    pass
