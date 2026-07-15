"""Append-only ticket audit events."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models.db_models import TicketAuditEvent, User, utc_now


def record_ticket_audit(
    session: Session,
    *,
    ticket_id: str,
    actor: User | None,
    action: str,
    field_name: str | None = None,
    old_value: str | None = None,
    new_value: str | None = None,
) -> TicketAuditEvent:
    event = TicketAuditEvent(
        id=str(uuid.uuid4()),
        ticket_id=ticket_id,
        actor_id=actor.id if actor is not None else None,
        actor_role=actor.role if actor is not None else "system",
        action=action,
        field_name=field_name,
        old_value=old_value,
        new_value=new_value,
        created_at=utc_now(),
    )
    session.add(event)
    return event


def list_ticket_audit_events(session: Session, ticket_id: str) -> list[TicketAuditEvent]:
    return (
        session.query(TicketAuditEvent)
        .filter(TicketAuditEvent.ticket_id == ticket_id)
        .order_by(TicketAuditEvent.created_at.asc())
        .all()
    )
