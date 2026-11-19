"""Add ticket_transfer_requests table for office-to-office ticket transfers.

Revision ID: 20261013_0013
Revises: 20261007_0012
Create Date: 2026-10-13

Stores the full transfer-request lifecycle (Pending -> Accepted/Rejected).
A request never immediately reassigns its ticket -- only an Accepted
decision does that. source_office_id/destination_office_id are always real
``offices.id`` foreign keys (never raw office-name strings), so a request
can never be ambiguous about which offices it concerns. Completed rows are
never overwritten, so this table also doubles as the append-only transfer
history. The partial unique index enforces "at most one Pending request per
ticket" at the database level, matching the SQLAlchemy model's
``Index(..., postgresql_where=..., sqlite_where=...)`` definition used by
the test suite's ``Base.metadata.create_all``.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "20261013_0013"
down_revision: Union[str, None] = "20261007_0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if inspect(bind).has_table("ticket_transfer_requests"):
        return

    op.create_table(
        "ticket_transfer_requests",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("ticket_id", sa.String(length=32), sa.ForeignKey("tickets.id"), nullable=False),
        sa.Column("source_office_id", sa.String(length=36), sa.ForeignKey("offices.id"), nullable=False),
        sa.Column("destination_office_id", sa.String(length=36), sa.ForeignKey("offices.id"), nullable=False),
        sa.Column("initiated_by_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="Pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('Pending', 'Accepted', 'Rejected')",
            name="ck_ticket_transfer_requests_status",
        ),
    )
    op.create_index(
        "ix_ticket_transfer_requests_ticket_id", "ticket_transfer_requests", ["ticket_id"]
    )
    op.create_index(
        "ix_ticket_transfer_requests_source_office_id",
        "ticket_transfer_requests",
        ["source_office_id"],
    )
    op.create_index(
        "ix_ticket_transfer_requests_destination_office_id",
        "ticket_transfer_requests",
        ["destination_office_id"],
    )
    op.create_index(
        "ix_ticket_transfer_requests_status", "ticket_transfer_requests", ["status"]
    )
    op.create_index(
        "ux_ticket_transfer_requests_one_pending_per_ticket",
        "ticket_transfer_requests",
        ["ticket_id"],
        unique=True,
        postgresql_where=sa.text("status = 'Pending'"),
        sqlite_where=sa.text("status = 'Pending'"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if inspect(bind).has_table("ticket_transfer_requests"):
        op.drop_table("ticket_transfer_requests")
