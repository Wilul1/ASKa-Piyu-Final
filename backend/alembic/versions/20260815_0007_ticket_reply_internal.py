"""Add is_internal on ticket replies for staff-only notes.

Revision ID: 20260815_0007
Revises: 20260814_0006
Create Date: 2026-08-15
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260815_0007"
down_revision: Union[str, None] = "20260814_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "ALTER TABLE ticket_replies "
            "ADD COLUMN IF NOT EXISTS is_internal BOOLEAN NOT NULL DEFAULT FALSE"
        )
    )


def downgrade() -> None:
    op.execute(sa.text("ALTER TABLE ticket_replies DROP COLUMN IF EXISTS is_internal"))
