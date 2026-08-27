"""Create auth_events table for abuse detection.

Revision ID: 20260814_0006
Revises: 20260801_0005
Create Date: 2026-08-14
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "20260814_0006"
down_revision: Union[str, Sequence[str], None] = "20260801_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if inspect(bind).has_table("auth_events"):
        return

    op.create_table(
        "auth_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("event_type", sa.String(length=20), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("ip_address", sa.String(length=80), nullable=False),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_auth_events_event_type", "auth_events", ["event_type"])
    op.create_index("ix_auth_events_email", "auth_events", ["email"])
    op.create_index("ix_auth_events_user_id", "auth_events", ["user_id"])
    op.create_index("ix_auth_events_ip_address", "auth_events", ["ip_address"])
    op.create_index("ix_auth_events_created_at", "auth_events", ["created_at"])


def downgrade() -> None:
    bind = op.get_bind()
    if inspect(bind).has_table("auth_events"):
        op.drop_table("auth_events")
