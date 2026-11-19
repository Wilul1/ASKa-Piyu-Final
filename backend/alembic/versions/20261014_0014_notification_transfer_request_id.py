"""Add transfer_request_id on notifications for precise transfer linkage.

Revision ID: 20261014_0014
Revises: 20261013_0013
Create Date: 2026-10-14

Lets a transfer decision mark read exactly the notifications it caused
(scoped by this exact transfer request id) instead of inferring identity
from ticket_id alone, which multiple distinct transfer requests and
multiple recipients can share. Nullable and additive: every pre-existing
notification, and every notification of a type unrelated to transfers
(e.g. "ticket_assigned", "office_reassigned", "ticket_reply"), simply
leaves this column NULL.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261014_0014"
down_revision: Union[str, None] = "20261013_0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "ALTER TABLE notifications "
            "ADD COLUMN IF NOT EXISTS transfer_request_id VARCHAR(36) "
            "REFERENCES ticket_transfer_requests(id)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_notifications_transfer_request_id "
            "ON notifications (transfer_request_id)"
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS ix_notifications_transfer_request_id"))
    op.execute(sa.text("ALTER TABLE notifications DROP COLUMN IF EXISTS transfer_request_id"))
