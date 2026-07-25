"""Add announcements table (idempotent).

Revision ID: 20260725_0002
Revises: 20260725_0001
Create Date: 2026-07-25

Baseline revision 0001 runs Base.metadata.create_all(), which already creates
``announcements`` on a fresh DB. This revision must no-op when the table
exists so ``alembic upgrade head`` does not fail in Docker.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "20260725_0002"
down_revision: Union[str, Sequence[str], None] = "20260725_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if inspect(bind).has_table("announcements"):
        return

    op.create_table(
        "announcements",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("published", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_by_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if inspect(bind).has_table("announcements"):
        op.drop_table("announcements")
