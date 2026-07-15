"""PostgreSQL-backed smart ticketing storage, triage, and access control."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.models.db_models import Office, Ticket, TicketReply, User
from app.models.schemas import CreateTicketRequest, TicketAttachmentSchema, TicketSchema, UpdateTicketRequest
from app.services.knowledge_taxonomy import classify_question
from app.services.ticket_audit import record_ticket_audit
from app.services.ticket_notifications import notify_office_staff, notify_ticket_owner
from app.services.ticket_office_resolver import resolve_office_for_ticket


class TicketAccessError(PermissionError):
    pass


class TicketNotFoundError(LookupError):
    pass


class TicketValidationError(ValueError):
    pass


def triage_ticket(question: str, description: str = "", *, session: Session | None = None) -> dict[str, Any]:
    text = " ".join(part for part in (question, description) if part).strip()
    classification = classify_question(question or text)
    office_name = classification.office
    office_id: str | None = None
    if session is not None:
        try:
            office_id, office_name = resolve_office_for_ticket(session, classification.office)
        except LookupError:
            office_id = None
    return {
        "category": classification.category,
        "assigned_office": office_name,
        "assigned_office_id": office_id,
        "priority": _priority_for_text(text),
        "confidence": classification.confidence,
        "method": classification.method,
    }


def create_ticket(session: Session, payload: CreateTicketRequest, actor: User) -> TicketSchema:
    _require_role(actor, {"student", "admin"})
    triage = triage_ticket(payload.original_question, payload.description, session=session)

    if payload.preferred_office_id or payload.preferred_office:
        if payload.preferred_office_id:
            office = session.get(Office, payload.preferred_office_id)
            if office is None:
                raise TicketValidationError("Preferred office was not found.")
            office_id, office_name = office.id, office.name
        else:
            office_id, office_name = resolve_office_for_ticket(session, payload.preferred_office or "")
    else:
        office_id, office_name = resolve_office_for_ticket(session, triage["assigned_office"])

    priority = payload.preferred_priority or triage["priority"]
    now = _utc_now()
    ticket = Ticket(
        id=_ticket_id(),
        user_id=actor.id,
        original_question=payload.original_question.strip(),
        description=payload.description.strip(),
        category=triage["category"],
        assigned_office_id=office_id,
        assigned_office=office_name,
        priority=priority,
        status="Open",
        confidence_score=payload.confidence_score,
        source_from_chatbot=payload.source_from_chatbot,
        created_at=now,
        updated_at=now,
    )
    session.add(ticket)
    session.flush()
    record_ticket_audit(
        session,
        ticket_id=ticket.id,
        actor=actor,
        action="created",
        field_name="status",
        old_value=None,
        new_value="Open",
    )
    if payload.preferred_office_id or payload.preferred_office:
        record_ticket_audit(
            session,
            ticket_id=ticket.id,
            actor=actor,
            action="office_confirmed",
            field_name="assigned_office",
            old_value=triage["assigned_office"],
            new_value=office_name,
        )
    notify_office_staff(
        session,
        ticket,
        type="ticket_created",
        title=f"New ticket {ticket.id}",
        body=f"{actor.full_name} submitted: {ticket.original_question[:120]}",
        exclude_user_id=actor.id,
    )
    session.commit()
    session.refresh(ticket)
    return _ticket_schema(session, ticket)


def list_tickets(
    session: Session,
    actor: User,
    *,
    status: str | None = None,
    priority: str | None = None,
    office: str | None = None,
) -> list[TicketSchema]:
    query = session.query(Ticket).options(
        joinedload(Ticket.user),
        joinedload(Ticket.assigned_office_ref),
        joinedload(Ticket.replies),
        joinedload(Ticket.attachments),
    )

    if actor.role == "student":
        query = query.filter(Ticket.user_id == actor.id)
    elif actor.role == "office":
        office_filters = []
        if actor.office_id:
            office_filters.append(Ticket.assigned_office_id == actor.office_id)
        office_name = actor.office.name if actor.office is not None else None
        if not office_name and actor.office_id:
            office_row = session.get(Office, actor.office_id)
            office_name = office_row.name if office_row else None
        if office_name:
            office_filters.append(Ticket.assigned_office == office_name)
        if not office_filters:
            return []
        query = query.filter(or_(*office_filters))
    elif actor.role != "admin":
        return []

    if status:
        query = query.filter(Ticket.status == status)
    if priority:
        query = query.filter(Ticket.priority == priority)
    if office and actor.role == "admin":
        matched_office_ids = [
            row.id for row in session.query(Office.id).filter(Office.name == office).all()
        ]
        office_filters = [Ticket.assigned_office == office]
        if matched_office_ids:
            office_filters.append(Ticket.assigned_office_id.in_(matched_office_ids))
        query = query.filter(or_(*office_filters))

    tickets = query.order_by(Ticket.updated_at.desc()).all()
    return [_ticket_schema(session, ticket) for ticket in tickets]


def get_ticket(session: Session, ticket_id: str, actor: User) -> TicketSchema:
    ticket = _load_ticket(session, ticket_id)
    if not _can_view(ticket, actor, session):
        raise TicketAccessError("You do not have access to this ticket.")
    return _ticket_schema(session, ticket)


def update_ticket(
    session: Session,
    ticket_id: str,
    payload: UpdateTicketRequest,
    actor: User,
) -> TicketSchema:
    ticket = _load_ticket(session, ticket_id)
    if not _can_update(ticket, actor, session):
        raise TicketAccessError("You do not have permission to update this ticket.")

    next_status = payload.status or ticket.status
    if payload.status and not _valid_status_transition(ticket.status, payload.status, actor.role):
        raise TicketValidationError(f"Cannot move ticket from {ticket.status} to {payload.status}.")

    previous_status = ticket.status
    previous_office = ticket.assigned_office
    previous_priority = ticket.priority

    if payload.assigned_office_id is not None or payload.assigned_office is not None:
        _require_role(actor, {"admin"})
        if payload.assigned_office_id:
            office = session.get(Office, payload.assigned_office_id)
            if office is None:
                raise TicketValidationError("Assigned office was not found.")
            ticket.assigned_office_id = office.id
            ticket.assigned_office = office.name
        elif payload.assigned_office:
            office_id, office_name = resolve_office_for_ticket(session, payload.assigned_office)
            ticket.assigned_office_id = office_id
            ticket.assigned_office = office_name
        if ticket.assigned_office != previous_office:
            record_ticket_audit(
                session,
                ticket_id=ticket.id,
                actor=actor,
                action="office_reassigned",
                field_name="assigned_office",
                old_value=previous_office,
                new_value=ticket.assigned_office,
            )

    if payload.category is not None:
        _require_role(actor, {"admin"})
        old_category = ticket.category
        ticket.category = payload.category.strip()
        if ticket.category != old_category:
            record_ticket_audit(
                session,
                ticket_id=ticket.id,
                actor=actor,
                action="category_changed",
                field_name="category",
                old_value=old_category,
                new_value=ticket.category,
            )

    if payload.priority is not None:
        if actor.role not in {"admin", "office"}:
            raise TicketAccessError("Only office staff or admin can change priority.")
        ticket.priority = payload.priority
        if ticket.priority != previous_priority:
            record_ticket_audit(
                session,
                ticket_id=ticket.id,
                actor=actor,
                action="priority_changed",
                field_name="priority",
                old_value=previous_priority,
                new_value=ticket.priority,
            )

    ticket.status = next_status
    ticket.updated_at = _utc_now()
    if next_status == "Resolved" and ticket.resolved_at is None:
        ticket.resolved_at = ticket.updated_at
    if next_status == "Closed" and ticket.closed_at is None:
        ticket.closed_at = ticket.updated_at
    if next_status == "In Progress" and previous_status in {"Resolved", "Closed"}:
        ticket.resolved_at = None
        if previous_status == "Closed":
            ticket.closed_at = None

    if next_status != previous_status:
        record_ticket_audit(
            session,
            ticket_id=ticket.id,
            actor=actor,
            action="status_changed",
            field_name="status",
            old_value=previous_status,
            new_value=next_status,
        )
        notify_ticket_owner(
            session,
            ticket,
            type="status_changed",
            title=f"Ticket {ticket.id} is now {next_status}",
            body=f"Status updated from {previous_status} to {next_status} by {actor.full_name}.",
            exclude_user_id=actor.id,
        )

    if ticket.assigned_office != previous_office:
        notify_ticket_owner(
            session,
            ticket,
            type="office_reassigned",
            title=f"Ticket {ticket.id} reassigned",
            body=f"Your ticket was reassigned to {ticket.assigned_office}.",
            exclude_user_id=actor.id,
        )
        notify_office_staff(
            session,
            ticket,
            type="ticket_assigned",
            title=f"Ticket {ticket.id} assigned to your office",
            body=ticket.original_question[:140],
            exclude_user_id=actor.id,
        )

    session.commit()
    session.refresh(ticket)
    return _ticket_schema(session, ticket)


def add_ticket_reply(session: Session, ticket_id: str, message: str, actor: User) -> TicketSchema:
    ticket = _load_ticket(session, ticket_id)
    if not _can_view(ticket, actor, session):
        raise TicketAccessError("You do not have access to this ticket.")
    if ticket.status == "Closed":
        raise TicketValidationError("Closed tickets do not accept new replies.")
    if actor.role == "student" and ticket.status not in {"Open", "In Progress"}:
        raise TicketValidationError(
            "You can only reply while your ticket is Open or In Progress. "
            "Ask the office to reopen it if you need more help."
        )

    now = _utc_now()
    reply = TicketReply(
        id=str(uuid.uuid4()),
        ticket_id=ticket.id,
        sender_id=actor.id,
        sender_role=actor.role,
        sender_name=actor.full_name,
        message=message.strip(),
        created_at=now,
    )
    ticket.replies.append(reply)
    ticket.updated_at = now
    if actor.role == "student" and ticket.status == "Resolved":
        ticket.status = "In Progress"
        ticket.resolved_at = None

    record_ticket_audit(
        session,
        ticket_id=ticket.id,
        actor=actor,
        action="reply_added",
        field_name="reply",
        old_value=None,
        new_value=_preview_text(message, limit=80),
    )

    preview = _preview_text(message)
    if actor.role == "student":
        notify_office_staff(
            session,
            ticket,
            type="ticket_reply",
            title=f"Student reply on {ticket.id}",
            body=preview,
            exclude_user_id=actor.id,
        )
    else:
        notify_ticket_owner(
            session,
            ticket,
            type="ticket_reply",
            title=f"New reply on {ticket.id}",
            body=preview,
            exclude_user_id=actor.id,
        )

    session.commit()
    session.refresh(ticket)
    return _ticket_schema(session, ticket)


def ticket_statistics(session: Session, actor: User) -> dict[str, Any]:
    _require_role(actor, {"admin"})
    tickets = session.query(Ticket).all()
    by_office: dict[str, int] = {}
    for ticket in tickets:
        label = ticket.assigned_office or "Unassigned"
        by_office[label] = by_office.get(label, 0) + 1
    return {
        "total": len(tickets),
        "open": sum(1 for ticket in tickets if ticket.status == "Open"),
        "in_progress": sum(1 for ticket in tickets if ticket.status == "In Progress"),
        "resolved": sum(1 for ticket in tickets if ticket.status == "Resolved"),
        "closed": sum(1 for ticket in tickets if ticket.status == "Closed"),
        "by_office": by_office,
    }


def list_offices(session: Session) -> list[Office]:
    return session.query(Office).order_by(Office.name.asc()).all()


def _ticket_schema(session: Session, ticket: Ticket) -> TicketSchema:
    replies = sorted(ticket.replies or [], key=lambda item: item.created_at)
    messages = [
        {
            "id": reply.id,
            "ticket_id": reply.ticket_id,
            "sender_id": reply.sender_id,
            "sender_role": reply.sender_role,
            "sender_name": reply.sender_name,
            "message": reply.message,
            "created_at": _iso(reply.created_at),
        }
        for reply in replies
    ]
    latest_preview = None
    if replies:
        latest_preview = _preview_text(replies[-1].message)
    user = ticket.user
    if user is None:
        user = session.get(User, ticket.user_id)
    user_name = user.full_name if user else "Student"
    user_email = user.email if user else None
    office_name = ticket.assigned_office
    if ticket.assigned_office_ref is not None:
        office_name = ticket.assigned_office_ref.name
    elif ticket.assigned_office_id:
        office = session.get(Office, ticket.assigned_office_id)
        if office is not None:
            office_name = office.name

    return TicketSchema(
        id=ticket.id,
        ticket_id=ticket.id,
        user_id=ticket.user_id,
        user_name=user_name,
        user_email=user_email,
        original_question=ticket.original_question,
        description=ticket.description,
        category=ticket.category,
        assigned_office_id=ticket.assigned_office_id,
        assigned_office=office_name,
        assigned_office_name=office_name,
        priority=ticket.priority,
        status=ticket.status,
        confidence_score=ticket.confidence_score,
        source_from_chatbot=ticket.source_from_chatbot,
        created_by={
            "user_id": ticket.user_id,
            "full_name": user_name,
            "email": user_email,
        },
        created_at=_iso(ticket.created_at),
        updated_at=_iso(ticket.updated_at),
        resolved_at=_iso(ticket.resolved_at) if ticket.resolved_at else None,
        closed_at=_iso(ticket.closed_at) if ticket.closed_at else None,
        latest_reply_preview=latest_preview,
        replies_count=len(replies),
        messages=messages,
        attachments=[
            TicketAttachmentSchema(
                id=item.id,
                ticket_id=item.ticket_id,
                original_filename=item.original_filename,
                content_type=item.content_type,
                size_bytes=item.size_bytes,
                uploaded_by_id=item.uploaded_by_id,
                created_at=_iso(item.created_at),
                download_url=f"/tickets/{item.ticket_id}/attachments/{item.id}/download",
            )
            for item in sorted(ticket.attachments or [], key=lambda row: row.created_at)
        ],
    )


def _load_ticket(session: Session, ticket_id: str) -> Ticket:
    ticket = (
        session.query(Ticket)
        .options(
            joinedload(Ticket.user),
            joinedload(Ticket.assigned_office_ref),
            joinedload(Ticket.replies),
            joinedload(Ticket.attachments),
        )
        .filter(Ticket.id == ticket_id)
        .one_or_none()
    )
    if ticket is None:
        raise TicketNotFoundError("Ticket not found.")
    return ticket


def _can_view(ticket: Ticket, actor: User, session: Session) -> bool:
    if actor.role == "admin":
        return True
    if actor.role == "student":
        return ticket.user_id == actor.id
    if actor.role == "office":
        return _office_matches_ticket(actor, ticket, session)
    return False


def _can_update(ticket: Ticket, actor: User, session: Session) -> bool:
    if actor.role == "admin":
        return True
    if actor.role == "office":
        return _office_matches_ticket(actor, ticket, session)
    if actor.role == "student":
        return ticket.user_id == actor.id and ticket.status == "Resolved"
    return False


def _office_matches_ticket(actor: User, ticket: Ticket, session: Session) -> bool:
    if actor.office_id and ticket.assigned_office_id:
        return actor.office_id == ticket.assigned_office_id
    office_name = actor.office.name if actor.office is not None else None
    if not office_name and actor.office_id:
        office = session.get(Office, actor.office_id)
        office_name = office.name if office else None
    return bool(office_name) and _same(ticket.assigned_office, office_name)


def _valid_status_transition(current: str, next_status: str, role: str) -> bool:
    if current == next_status:
        return True
    transitions = {
        "Open": {"In Progress"},
        "In Progress": {"Resolved", "Closed"},
        "Resolved": {"Closed", "In Progress"},
        "Closed": set(),
    }
    if role == "admin":
        return True
    if role == "student":
        return current == "Resolved" and next_status == "Closed"
    return next_status in transitions.get(current, set())


def _priority_for_text(text: str) -> str:
    """Score urgency from question+description keywords.

    Urgent > High > Medium > Low. Explicit emergency language or severe outages
    become Urgent; access/enrollment blockers become High.
    """
    normalized = _normalize(text)
    # "cannot log in" and "cannot login" should match the same signals.
    compact = re.sub(r"[^a-z0-9]+", "", normalized)
    urgent_score = 0
    high_score = 0
    medium_score = 0

    urgent_terms = (
        "urgent",
        "asap",
        "emergency",
        "immediately",
        "system outage",
        "completely down",
        "portal is down",
        "cannot graduate",
        "locked out",
    )
    high_terms = (
        "deadline",
        "blocked enrollment",
        "cannot enroll",
        "can't enroll",
        "cannot login",
        "cannot log in",
        "can't login",
        "can't log in",
        "cannot sign in",
        "can't sign in",
        "cannot access",
        "can't access",
        "invalid credentials",
        "wrong password",
        "locked account",
        "payment validation",
        "graduation clearance",
        "clearance blocker",
        "down",
    )
    high_compact_terms = (
        "cannotlogin",
        "cantlogin",
        "cannotloginin",  # unlikely
        "cannotsignin",
        "cantsignin",
        "cannotaccess",
        "cantaccess",
        "invalidcredentials",
        "lockedaccount",
        "lockedout",
    )
    medium_terms = (
        "request",
        "process",
        "follow up",
        "requirement",
        "requirements",
        "document",
        "records",
        "certificate",
        "tor",
    )

    for term in urgent_terms:
        if term in normalized:
            urgent_score += 2 if term in {"urgent", "emergency", "asap", "system outage"} else 1
    for term in high_terms:
        if term in normalized:
            high_score += 1
    for term in high_compact_terms:
        if term in compact:
            high_score += 1
    for term in medium_terms:
        if term in normalized:
            medium_score += 1

    # "Urgent" self-rating language plus any blocker → Urgent
    if urgent_score >= 2 or (urgent_score >= 1 and high_score >= 1):
        return "Urgent"
    if urgent_score >= 1 and "urgent" in normalized:
        return "Urgent"
    if high_score >= 1:
        return "High"
    if medium_score >= 1:
        return "Medium"
    return "Low"


def _require_role(actor: User, allowed: set[str]) -> None:
    if actor.role not in allowed:
        raise TicketAccessError("This role cannot perform the requested action.")


def _ticket_id() -> str:
    return f"TK-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _preview_text(message: str, *, limit: int = 140) -> str:
    text = re.sub(r"\s+", " ", (message or "").strip())
    if len(text) <= limit:
        return text
    clipped = text[: limit - 1].rsplit(" ", 1)[0]
    return f"{clipped or text[: limit - 1]}…"


def _same(left: str, right: str) -> bool:
    return _normalize(left) == _normalize(right)


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").lower()).strip()
