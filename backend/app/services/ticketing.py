"""PostgreSQL-backed smart ticketing storage, triage, and access control."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.models.db_models import Notification, Office, Ticket, TicketReply, TicketTransferRequest, User
from app.models.schemas import (
    CreateTicketRequest,
    TicketAttachmentSchema,
    TicketSchema,
    TicketTransferRequestSchema,
    UpdateTicketRequest,
)
from app.services.knowledge_taxonomy import DEFAULT_CATEGORY, classify_question
from app.services.ticket_audit import record_ticket_audit
from app.services.ticket_notifications import notify_office_id_staff, notify_office_staff, notify_ticket_owner
from app.services.ticket_office_resolver import UnresolvedOfficeLabelError, resolve_office_for_ticket
from app.services.ticket_text_quality import validate_ticket_description, validate_ticket_subject


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
        # A specific (non-"General") taxonomy classification must not be
        # silently rehomed to the Office of Student Affairs default when its
        # seeded office can't be found -- that would make an unresolved
        # taxonomy label indistinguishable from a genuine OSA classification.
        # Only the deliberate "General"/unclassified sentinel is allowed to
        # fall back to the OSA default here.
        is_default_classification = classification.category == DEFAULT_CATEGORY
        try:
            office_id, office_name = resolve_office_for_ticket(
                session,
                classification.office,
                allow_default_fallback=is_default_classification,
            )
        except LookupError:
            # Leaves office_id = None and office_name = classification.office
            # (the raw taxonomy label) untouched, so the caller can tell this
            # apart from a resolved office and preserve the label for
            # diagnostics instead of silently claiming OSA was the target.
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
    _require_role(actor, {"student", "faculty", "admin", "office"})
    try:
        original_question = validate_ticket_subject(payload.original_question)
        description = validate_ticket_description(payload.description)
    except ValueError as exc:
        raise TicketValidationError(str(exc)) from exc

    triage = triage_ticket(original_question, description, session=session)

    owner = actor
    on_behalf_email = (getattr(payload, "on_behalf_of_email", None) or "").strip().lower()
    if actor.role == "office":
        if not on_behalf_email:
            raise TicketValidationError(
                "Office staff must provide on_behalf_of_email for the requester."
            )
        owner = session.query(User).filter(User.email == on_behalf_email).first()
        if owner is None:
            raise TicketValidationError("Requester account was not found for on_behalf_of_email.")
        if owner.role not in {"student", "faculty"}:
            raise TicketValidationError("Tickets can only be opened on behalf of students or faculty.")
    elif on_behalf_email and actor.role == "admin":
        owner = session.query(User).filter(User.email == on_behalf_email).first()
        if owner is None:
            raise TicketValidationError("Requester account was not found for on_behalf_of_email.")

    staff_selected_office = (
        actor.role in {"admin", "office"}
        and bool(payload.preferred_office_id or payload.preferred_office)
    )
    # Student direct office selection: deliberately narrower than the staff
    # path above -- requires an explicit routing_method opt-in (not merely a
    # non-null preferred_office_id, which the student-preference-ignored
    # tests below still cover) and ID-only (never the fuzzy preferred_office
    # name resolver, which silently defaults to OSA when unresolved -- fine
    # for a trusted staff correction, wrong contract for a student-facing
    # exact-selection dropdown).
    student_selected_office = (
        actor.role == "student"
        and payload.routing_method == "student_selected"
        and bool(payload.preferred_office_id)
    )
    explicit_office_selected = staff_selected_office or student_selected_office
    if explicit_office_selected:
        if payload.preferred_office_id:
            office = session.get(Office, payload.preferred_office_id)
            if office is None:
                raise TicketValidationError("Preferred office was not found.")
            office_id, office_name = office.id, office.name
        else:
            office_id, office_name = resolve_office_for_ticket(session, payload.preferred_office or "")
    else:
        # Reuse triage's already-computed resolution instead of re-resolving
        # triage["assigned_office"] here. Re-resolving would call
        # resolve_office_for_ticket() with its default allow_default_fallback
        # (True), which would silently default an unresolved specific office
        # back to OSA -- exactly the silent-OSA behavior Fix 2 removes -- and
        # would do so uncaught, since this call site has no try/except.
        office_id, office_name = triage["assigned_office_id"], triage["assigned_office"]

    priority = triage["priority"]
    if payload.preferred_priority and actor.role in {"admin", "office"}:
        priority = payload.preferred_priority
    now = _utc_now()
    ticket = Ticket(
        id=_ticket_id(),
        user_id=owner.id,
        original_question=original_question,
        description=description,
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
    if explicit_office_selected:
        # actor_role on this event (already recorded by record_ticket_audit)
        # distinguishes staff-confirmed ("admin"/"office") from student-
        # selected ("student") without needing a new event type or field.
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
    return _ticket_schema(session, ticket, viewer=actor)


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

    if actor.role in {"student", "faculty"}:
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
    return [_ticket_schema(session, ticket, viewer=actor) for ticket in tickets]


def get_ticket(session: Session, ticket_id: str, actor: User) -> TicketSchema:
    ticket = _load_ticket(session, ticket_id)
    if not _can_view(ticket, actor, session):
        raise TicketAccessError("You do not have access to this ticket.")
    return _ticket_schema(session, ticket, viewer=actor)


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
    if payload.status is not None:
        # Status is no longer settable through this generic endpoint for
        # anyone but admin -- office staff must use the dedicated
        # resolve_ticket()/close_ticket() actions (which enforce their own,
        # narrower authorization and transition rules), and students/
        # faculty can no longer self-close a Resolved ticket this way.
        # Hiding the Flutter status dropdown is not a safeguard on its own;
        # this is the actual enforcement.
        _require_role(actor, {"admin"})
        if not _valid_status_transition(ticket.status, payload.status, actor.role):
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
            # Admin reassignment must never silently default an unresolved
            # label back to OSA (that is exactly the bug this blocker fixes):
            # a specific label either resolves to a real office or the
            # request is rejected, explicitly, so re-saving a ticket whose
            # raw taxonomy label happens to be its current assigned_office
            # can never quietly re-launder it into "Office of Student
            # Affairs". Admin recovers an unresolved ticket with a real
            # assigned_office_id instead (see below).
            try:
                office_id, office_name = resolve_office_for_ticket(
                    session, payload.assigned_office, allow_default_fallback=False
                )
            except UnresolvedOfficeLabelError as exc:
                raise TicketValidationError(
                    f"No office matches {exc.label!r}. "
                    "Use assigned_office_id to assign a specific existing office."
                ) from exc
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
    return _ticket_schema(session, ticket, viewer=actor)


def add_ticket_reply(
    session: Session,
    ticket_id: str,
    message: str,
    actor: User,
    *,
    is_internal: bool = False,
) -> TicketSchema:
    ticket = _load_ticket(session, ticket_id)
    if not _can_view(ticket, actor, session):
        raise TicketAccessError("You do not have access to this ticket.")
    if ticket.status == "Closed":
        raise TicketValidationError("Closed tickets do not accept new replies.")
    if actor.role == "student" and ticket.status not in {"Open", "In Progress", "Resolved"}:
        raise TicketValidationError(
            "You can only reply while your ticket is Open, In Progress, or Resolved."
        )
    # Internal notes are a staff-only authoring tool -- a student/faculty
    # requester's own reply is never internal, regardless of what a client
    # sends, matching AddTicketReplyRequest.is_internal's own contract.
    is_internal = bool(is_internal) and actor.role not in {"student", "faculty"}

    now = _utc_now()
    reply = TicketReply(
        id=str(uuid.uuid4()),
        ticket_id=ticket.id,
        sender_id=actor.id,
        sender_role=actor.role,
        sender_name=actor.full_name,
        message=message.strip(),
        created_at=now,
        is_internal=is_internal,
    )
    ticket.replies.append(reply)
    ticket.updated_at = now
    # A student reply to a Resolved ticket must NOT reopen it (approved
    # workflow) -- deliberately no status mutation for that case at all.
    # A staff reply (office matching the ticket, or admin) on an Open
    # ticket auto-advances it to In Progress, but only once the reply has
    # actually been appended above -- this status write and the reply
    # share the same session.commit() below, so a failure before that
    # commit rolls back both together and never leaves the status changed
    # without the reply, or vice versa.
    previous_status = ticket.status
    if actor.role in {"office", "admin"} and ticket.status == "Open":
        ticket.status = "In Progress"

    record_ticket_audit(
        session,
        ticket_id=ticket.id,
        actor=actor,
        action="reply_added",
        field_name="reply",
        old_value=None,
        # Never the real preview for an internal note -- the audit/history
        # endpoint applies no per-viewer filtering of its own (it reuses
        # the same ticket-visibility check as the ticket itself, so a
        # requester who may view the ticket can also list its audit
        # events), so an internal note's content must never be written
        # into this row at all.
        new_value=(
            "[internal note]" if is_internal else _preview_text(message, limit=80)
        ),
    )

    if ticket.status != previous_status:
        record_ticket_audit(
            session,
            ticket_id=ticket.id,
            actor=actor,
            action="status_changed",
            field_name="status",
            old_value=previous_status,
            new_value=ticket.status,
        )
        notify_ticket_owner(
            session,
            ticket,
            type="status_changed",
            title=f"Ticket {ticket.id} is now {ticket.status}",
            body=f"Status updated from {previous_status} to {ticket.status} by {actor.full_name}.",
            exclude_user_id=actor.id,
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
    elif not is_internal:
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
    return _ticket_schema(session, ticket, viewer=actor)


def resolve_ticket(session: Session, ticket_id: str, actor: User) -> TicketSchema:
    """Dedicated Resolve action -- the only supported way to move a ticket
    to Resolved, replacing the removed generic-PATCH status dropdown.
    Authorized office staff (matching the ticket's current office) or
    admin only; a student/faculty requester can never resolve their own
    ticket through this action."""
    ticket = _load_ticket(session, ticket_id)
    if not (actor.role == "admin" or (actor.role == "office" and _office_matches_ticket(actor, ticket, session))):
        raise TicketAccessError("You do not have permission to resolve this ticket.")
    if ticket.status not in {"Open", "In Progress"}:
        raise TicketValidationError(f"Cannot resolve a ticket that is {ticket.status}.")

    previous_status = ticket.status
    now = _utc_now()
    ticket.status = "Resolved"
    ticket.resolved_at = now
    ticket.updated_at = now

    record_ticket_audit(
        session,
        ticket_id=ticket.id,
        actor=actor,
        action="status_changed",
        field_name="status",
        old_value=previous_status,
        new_value="Resolved",
    )
    notify_ticket_owner(
        session,
        ticket,
        type="status_changed",
        title=f"Ticket {ticket.id} is now Resolved",
        body=f"Status updated from {previous_status} to Resolved by {actor.full_name}.",
        exclude_user_id=actor.id,
    )

    session.commit()
    session.refresh(ticket)
    return _ticket_schema(session, ticket, viewer=actor)


def close_ticket(session: Session, ticket_id: str, actor: User) -> TicketSchema:
    """Dedicated, admin-only Close action -- the only newly supported way
    to move a ticket to Closed. Idempotent: closing an already-Closed
    ticket is a harmless no-op (no duplicate audit/notification), matching
    the same-status no-op convention already used by the generic PATCH
    transition map."""
    ticket = _load_ticket(session, ticket_id)
    _require_role(actor, {"admin"})
    if ticket.status == "Closed":
        return _ticket_schema(session, ticket, viewer=actor)

    previous_status = ticket.status
    now = _utc_now()
    ticket.status = "Closed"
    ticket.closed_at = now
    ticket.updated_at = now

    record_ticket_audit(
        session,
        ticket_id=ticket.id,
        actor=actor,
        action="status_changed",
        field_name="status",
        old_value=previous_status,
        new_value="Closed",
    )
    notify_ticket_owner(
        session,
        ticket,
        type="status_changed",
        title=f"Ticket {ticket.id} is now Closed",
        body=f"Status updated from {previous_status} to Closed by {actor.full_name}.",
        exclude_user_id=actor.id,
    )

    session.commit()
    session.refresh(ticket)
    return _ticket_schema(session, ticket, viewer=actor)


def _may_decide_transfer(actor: User, request: TicketTransferRequest) -> bool:
    """Only the destination office's own staff, or admin, may accept/reject
    -- never the source office, never an unrelated office. Direct id
    comparison (not _office_matches_ticket's name-fallback) since
    destination_office_id is always a real office id by construction."""
    return actor.role == "admin" or (
        actor.role == "office" and actor.office_id == request.destination_office_id
    )


def request_ticket_transfer(
    session: Session,
    ticket_id: str,
    *,
    destination_office_id: str,
    reason: str,
    actor: User,
) -> TicketTransferRequestSchema:
    """Create a Pending transfer request. Never reassigns the ticket --
    only accept_ticket_transfer() does that, and only later. Rejects a
    nonexistent destination, a same-office "transfer", an empty reason,
    and (at the database level, via the partial unique index on
    TicketTransferRequest) a second concurrent Pending request for the
    same ticket -- the last of these is only detectable by actually
    attempting the insert, never by a pre-check alone, since two requests
    could race past a pre-check at the same instant."""
    ticket = _load_ticket(session, ticket_id)
    if not (
        actor.role == "admin"
        or (actor.role == "office" and _office_matches_ticket(actor, ticket, session))
    ):
        raise TicketAccessError("You do not have permission to transfer this ticket.")
    if not ticket.assigned_office_id:
        raise TicketValidationError(
            "This ticket has no resolved office assignment yet -- resolve it to a real "
            "office before requesting a transfer."
        )

    cleaned_reason = (reason or "").strip()
    if not cleaned_reason:
        raise TicketValidationError("A transfer reason is required.")

    destination = session.get(Office, destination_office_id)
    if destination is None:
        raise TicketValidationError("Destination office was not found.")
    if destination.id == ticket.assigned_office_id:
        raise TicketValidationError(
            "Cannot transfer a ticket to the office it is already assigned to."
        )

    request = TicketTransferRequest(
        id=str(uuid.uuid4()),
        ticket_id=ticket.id,
        source_office_id=ticket.assigned_office_id,
        destination_office_id=destination.id,
        initiated_by_user_id=actor.id,
        reason=cleaned_reason,
        status="Pending",
        created_at=_utc_now(),
    )
    session.add(request)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        raise TicketValidationError(
            "This ticket already has a pending transfer request. Wait for it to be "
            "decided before requesting another."
        )

    record_ticket_audit(
        session,
        ticket_id=ticket.id,
        actor=actor,
        action="transfer_requested",
        field_name="transfer_status",
        old_value=None,
        new_value=f"Pending -> {destination.name}",
    )
    notify_office_id_staff(
        session,
        office_id=destination.id,
        ticket_id=ticket.id,
        type="transfer_requested",
        title=f"Incoming transfer request for {ticket.id}",
        body=cleaned_reason,
        exclude_user_id=actor.id,
        transfer_request_id=request.id,
    )

    session.commit()
    session.refresh(request)
    return _transfer_request_schema(session, request)


def accept_ticket_transfer(session: Session, transfer_id: str, actor: User) -> TicketSchema:
    """Atomically: re-check the request is still Pending (a guarded UPDATE,
    not a read-then-write -- see the `claimed == 0` check below, which is
    race-safe against a concurrent accept/reject of the SAME request),
    re-check the ticket's current office still matches the request's
    recorded source office, reassign the ticket, mark the request
    Accepted, and record audit/notifications. Never touches ticket
    status, replies, attachments, or requester -- only assigned_office_id/
    assigned_office."""
    request = session.get(TicketTransferRequest, transfer_id)
    if request is None:
        raise TicketNotFoundError("Transfer request not found.")
    if not _may_decide_transfer(actor, request):
        raise TicketAccessError("You do not have permission to decide this transfer request.")

    claimed = (
        session.query(TicketTransferRequest)
        .filter(TicketTransferRequest.id == transfer_id, TicketTransferRequest.status == "Pending")
        .update(
            {
                "status": "Accepted",
                "decided_by_user_id": actor.id,
                "decided_at": _utc_now(),
            },
            synchronize_session=False,
        )
    )
    if claimed == 0:
        raise TicketValidationError("This transfer request has already been decided.")

    ticket = _load_ticket(session, request.ticket_id)
    if ticket.assigned_office_id != request.source_office_id:
        # The ticket moved (e.g. an admin direct-reassigned it) since this
        # request was created -- accepting now would silently transfer
        # FROM the wrong office. Reject the acceptance with a clear
        # conflict instead of ever doing that.
        session.rollback()
        raise TicketValidationError(
            "This ticket's office assignment has changed since the transfer was "
            "requested; it can no longer be accepted."
        )

    destination = session.get(Office, request.destination_office_id)
    if destination is None:
        session.rollback()
        raise TicketValidationError("Destination office no longer exists.")

    previous_office = ticket.assigned_office
    ticket.assigned_office_id = destination.id
    ticket.assigned_office = destination.name
    ticket.updated_at = _utc_now()

    record_ticket_audit(
        session,
        ticket_id=ticket.id,
        actor=actor,
        action="transfer_accepted",
        field_name="assigned_office",
        old_value=previous_office,
        new_value=destination.name,
    )
    notify_ticket_owner(
        session,
        ticket,
        type="office_reassigned",
        title=f"Ticket {ticket.id} reassigned",
        body=f"Your ticket was reassigned to {destination.name}.",
        exclude_user_id=actor.id,
    )
    notify_office_id_staff(
        session,
        office_id=destination.id,
        ticket_id=ticket.id,
        type="ticket_assigned",
        title=f"Ticket {ticket.id} assigned to your office",
        body=ticket.original_question[:140],
        exclude_user_id=actor.id,
    )
    notify_office_id_staff(
        session,
        office_id=request.source_office_id,
        ticket_id=ticket.id,
        type="transfer_accepted",
        title=f"Transfer request for {ticket.id} was accepted",
        body=f"{destination.name} accepted the transfer.",
        exclude_user_id=actor.id,
        transfer_request_id=request.id,
    )
    # Resolve the destination office's own "please decide" notification for
    # THIS exact request now that it has been -- for every destination-
    # office recipient, not just the actor, since the decision is made for
    # the whole office. Scoped by transfer_request_id (never ticket_id
    # alone), so an unrelated earlier/later request on the same ticket, or
    # any other notification type, is never touched. Part of the same
    # transaction as the rest of this decision.
    session.query(Notification).filter(
        Notification.transfer_request_id == request.id,
        Notification.type == "transfer_requested",
        Notification.is_read.is_(False),
    ).update({"is_read": True}, synchronize_session=False)

    session.commit()
    session.refresh(ticket)
    return _ticket_schema(session, ticket, viewer=actor)


def reject_ticket_transfer(
    session: Session,
    transfer_id: str,
    actor: User,
    *,
    rejection_reason: str | None = None,
) -> TicketTransferRequestSchema:
    """Never touches the ticket at all -- the ticket's office, status,
    conversation, and everything else are preserved simply by this
    function never loading/mutating the Ticket row. Race-safe against a
    concurrent accept/reject the same way accept_ticket_transfer() is."""
    request = session.get(TicketTransferRequest, transfer_id)
    if request is None:
        raise TicketNotFoundError("Transfer request not found.")
    if not _may_decide_transfer(actor, request):
        raise TicketAccessError("You do not have permission to decide this transfer request.")

    cleaned_reason = (rejection_reason or "").strip() or None
    claimed = (
        session.query(TicketTransferRequest)
        .filter(TicketTransferRequest.id == transfer_id, TicketTransferRequest.status == "Pending")
        .update(
            {
                "status": "Rejected",
                "decided_by_user_id": actor.id,
                "decided_at": _utc_now(),
                "rejection_reason": cleaned_reason,
            },
            synchronize_session=False,
        )
    )
    if claimed == 0:
        raise TicketValidationError("This transfer request has already been decided.")

    record_ticket_audit(
        session,
        ticket_id=request.ticket_id,
        actor=actor,
        action="transfer_rejected",
        field_name="transfer_status",
        old_value="Pending",
        new_value="Rejected",
    )
    notify_office_id_staff(
        session,
        office_id=request.source_office_id,
        ticket_id=request.ticket_id,
        type="transfer_rejected",
        title=f"Transfer request for {request.ticket_id} was rejected",
        body=cleaned_reason or "No reason given.",
        exclude_user_id=actor.id,
        transfer_request_id=request.id,
    )
    # Same precise, scoped resolution as accept_ticket_transfer() -- see
    # its comment for why this is safe and why it covers every
    # destination-office recipient, not just the actor.
    session.query(Notification).filter(
        Notification.transfer_request_id == request.id,
        Notification.type == "transfer_requested",
        Notification.is_read.is_(False),
    ).update({"is_read": True}, synchronize_session=False)

    session.commit()
    session.refresh(request)
    return _transfer_request_schema(session, request)


def list_ticket_transfer_requests(
    session: Session, ticket_id: str, actor: User
) -> list[TicketTransferRequestSchema]:
    """So the ticket's CURRENT assigned office, and admin, can see whether
    a transfer is Pending, Accepted, or Rejected. Deliberately narrower
    than _can_view: the requester (student/faculty) must never see
    office-internal transfer reasons/rejection commentary, so this is NOT
    "can this actor view the ticket" -- it's "is this actor admin, or
    office staff of the ticket's current assigned office" only. A former
    (source) office that has since lost the ticket via an accepted
    transfer is intentionally not included here -- see
    list_outgoing_ticket_transfers() for that case, which is scoped to
    transfer-request rows only and never grants back any ticket
    conversation/attachment/internal-note access."""
    ticket = _load_ticket(session, ticket_id)
    if not (
        actor.role == "admin"
        or (actor.role == "office" and _office_matches_ticket(actor, ticket, session))
    ):
        raise TicketAccessError("You do not have access to this ticket.")
    requests = (
        session.query(TicketTransferRequest)
        .filter(TicketTransferRequest.ticket_id == ticket_id)
        .order_by(TicketTransferRequest.created_at.desc())
        .all()
    )
    return [_transfer_request_schema(session, request) for request in requests]


def list_incoming_ticket_transfers(session: Session, actor: User) -> list[TicketTransferRequestSchema]:
    """Pending requests addressed to the caller's own office -- the
    Incoming Transfers mailbox. Admin sees every Pending request across
    all offices."""
    query = session.query(TicketTransferRequest).filter(TicketTransferRequest.status == "Pending")
    if actor.role == "office":
        if not actor.office_id:
            return []
        query = query.filter(TicketTransferRequest.destination_office_id == actor.office_id)
    elif actor.role != "admin":
        return []
    requests = query.order_by(TicketTransferRequest.created_at.asc()).all()
    return [_transfer_request_schema(session, request) for request in requests]


def list_outgoing_ticket_transfers(session: Session, actor: User) -> list[TicketTransferRequestSchema]:
    """All requests (Pending, Accepted, or Rejected) that the caller's own
    office originated -- lets a source office review its own outgoing
    requests and their final outcomes even after an Accepted transfer has
    moved the ticket away to the destination office and the per-ticket
    list_ticket_transfer_requests()/get_ticket() would otherwise 403 it.
    Returns only TicketTransferRequestSchema rows (office ids/names,
    reason, status, decision metadata) -- never touches the Ticket row,
    so it can never grant back conversation/attachment/internal-note
    access. Admin sees every office's outgoing requests."""
    query = session.query(TicketTransferRequest)
    if actor.role == "office":
        if not actor.office_id:
            return []
        query = query.filter(TicketTransferRequest.source_office_id == actor.office_id)
    elif actor.role != "admin":
        return []
    requests = query.order_by(TicketTransferRequest.created_at.desc()).all()
    return [_transfer_request_schema(session, request) for request in requests]


def _transfer_request_schema(
    session: Session, request: TicketTransferRequest
) -> TicketTransferRequestSchema:
    source = session.get(Office, request.source_office_id)
    destination = session.get(Office, request.destination_office_id)
    return TicketTransferRequestSchema(
        id=request.id,
        ticket_id=request.ticket_id,
        source_office_id=request.source_office_id,
        source_office_name=source.name if source else request.source_office_id,
        destination_office_id=request.destination_office_id,
        destination_office_name=destination.name if destination else request.destination_office_id,
        initiated_by_user_id=request.initiated_by_user_id,
        reason=request.reason,
        status=request.status,
        created_at=_iso(request.created_at),
        decided_at=_iso(request.decided_at) if request.decided_at else None,
        decided_by_user_id=request.decided_by_user_id,
        rejection_reason=request.rejection_reason,
    )


def ticket_statistics(session: Session, actor: User) -> dict[str, Any]:
    _require_role(actor, {"admin"})
    tickets = session.query(Ticket).all()
    by_office: dict[str, int] = {}
    by_priority: dict[str, int] = {}
    by_category: dict[str, int] = {}
    for ticket in tickets:
        office_label = ticket.assigned_office or "Unassigned"
        by_office[office_label] = by_office.get(office_label, 0) + 1
        priority_label = (ticket.priority or "Medium").strip() or "Medium"
        by_priority[priority_label] = by_priority.get(priority_label, 0) + 1
        category_label = (ticket.category or "Uncategorized").strip() or "Uncategorized"
        by_category[category_label] = by_category.get(category_label, 0) + 1
    return {
        "total": len(tickets),
        "open": sum(1 for ticket in tickets if ticket.status == "Open"),
        "in_progress": sum(1 for ticket in tickets if ticket.status == "In Progress"),
        "resolved": sum(1 for ticket in tickets if ticket.status == "Resolved"),
        "closed": sum(1 for ticket in tickets if ticket.status == "Closed"),
        "high_priority": sum(
            1
            for ticket in tickets
            if (ticket.priority or "").strip() in {"High", "Urgent"}
            and ticket.status in {"Open", "In Progress"}
        ),
        "by_office": dict(sorted(by_office.items(), key=lambda item: (-item[1], item[0]))),
        "by_priority": by_priority,
        "by_category": dict(
            sorted(by_category.items(), key=lambda item: (-item[1], item[0]))
        ),
    }


def create_office(
    session: Session,
    *,
    name: str,
    service_category: str | None = None,
    description: str | None = None,
) -> Office:
    cleaned_name = " ".join((name or "").split())
    if not cleaned_name:
        raise TicketValidationError("Office name is required.")
    existing = (
        session.query(Office)
        .filter(func.lower(Office.name) == cleaned_name.lower())
        .first()
    )
    if existing is not None:
        raise TicketValidationError("An office with that name already exists.")
    office = Office(
        name=cleaned_name,
        service_category=(service_category or "").strip() or None,
        description=(description or "").strip() or None,
    )
    session.add(office)
    session.commit()
    session.refresh(office)
    return office


def delete_office(session: Session, office_id: str) -> None:
    office = session.get(Office, office_id)
    if office is None:
        raise TicketValidationError("Office was not found.")

    staff_count = session.query(User).filter(User.office_id == office.id).count()
    ticket_count = session.query(Ticket).filter(Ticket.assigned_office_id == office.id).count()
    if staff_count > 0 or ticket_count > 0:
        raise TicketValidationError(
            "Remove staff accounts and reassign tickets before deleting this office."
        )

    session.delete(office)
    session.commit()


def list_offices(session: Session) -> list[Office]:
    return session.query(Office).order_by(Office.name.asc()).all()


def _may_view_internal_notes(viewer: User, ticket: Ticket, session: Session) -> bool:
    """Internal-only staff notes are never requester-visible (see
    AddTicketReplyRequest.is_internal's own docstring). Admin and the
    ticket's currently-assigned office may see them; a student/faculty
    requester never can, even on their own ticket."""
    if viewer.role == "admin":
        return True
    if viewer.role == "office":
        return _office_matches_ticket(viewer, ticket, session)
    return False


def _ticket_schema(session: Session, ticket: Ticket, viewer: User) -> TicketSchema:
    all_replies = sorted(ticket.replies or [], key=lambda item: item.created_at)
    may_view_internal = _may_view_internal_notes(viewer, ticket, session)
    # Filtered BEFORE building messages/latest_preview/replies_count, so an
    # internal note can never leak through any of those three surfaces to a
    # viewer who isn't allowed to see it -- not the message text, not its
    # preview, and not even its existence via a count mismatch.
    visible_replies = [
        reply for reply in all_replies if may_view_internal or not reply.is_internal
    ]
    messages = [
        {
            "id": reply.id,
            "ticket_id": reply.ticket_id,
            "sender_id": reply.sender_id,
            "sender_role": reply.sender_role,
            "sender_name": reply.sender_name,
            "message": reply.message,
            "created_at": _iso(reply.created_at),
            "is_internal": reply.is_internal,
        }
        for reply in visible_replies
    ]
    latest_preview = None
    if visible_replies:
        latest_preview = _preview_text(visible_replies[-1].message)
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
        needs_manual_routing=ticket.assigned_office_id is None,
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
        replies_count=len(visible_replies),
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
        kb_article_id=ticket.kb_article_id,
        kb_conversion_status=(ticket.kb_conversion_status or "none"),  # type: ignore[arg-type]
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
    if actor.role in {"student", "faculty"}:
        return ticket.user_id == actor.id
    if actor.role == "office":
        return _office_matches_ticket(actor, ticket, session)
    return False


def _can_update(ticket: Ticket, actor: User, session: Session) -> bool:
    if actor.role == "admin":
        return True
    if actor.role == "office":
        return _office_matches_ticket(actor, ticket, session)
    if actor.role in {"student", "faculty"}:
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
    # This helper's only caller (update_ticket) already requires admin via
    # _require_role() before ever reaching this call, so `role` is always
    # "admin" here in practice -- the branch above already covers every
    # real invocation. No other role is expected to reach this point.
    return next_status in transitions.get(current, set())


def _priority_for_text(text: str) -> str:
    """Score urgency from question+description keywords.

    Urgent > High > Medium > Low.

    A ticket only reaches Urgent when either:
      (a) it describes a genuinely severe situation (a system-wide outage,
          a hard graduation/access blocker) -- these are severe on their own,
          regardless of whether the requester also uses urgency language; or
      (b) the requester's own self-declared urgency language ("urgent",
          "asap", "emergency", "immediately") is corroborated by an
          independent High-tier blocker signal.

    A lone self-declared urgency word is never sufficient by itself (so
    "an urgent question about the library hours" is not Urgent), and
    repeating that same word any number of times does not add score, since
    each term is scored once per presence in the text, not once per
    occurrence -- "urgent urgent urgent" scores identically to a single
    "urgent". Access/enrollment blockers on their own become High.
    """
    normalized = _normalize(text)
    # "cannot log in" and "cannot login" should match the same signals.
    compact = re.sub(r"[^a-z0-9]+", "", normalized)
    severe_score = 0
    urgent_word_score = 0
    high_score = 0
    medium_score = 0

    # Self-sufficient: genuinely severe situations become Urgent on their
    # own, independent of whether urgency language is also present.
    severe_terms = (
        "system outage",
        "completely down",
        "portal is down",
        "cannot graduate",
        "locked out",
    )
    # Self-declared urgency only ("I need this urgent/asap/emergency/
    # immediately"). On its own this is not evidence of a genuinely severe
    # situation, so it can only push a ticket to Urgent when corroborated by
    # an independent High-tier blocker below.
    self_declared_urgency_terms = (
        "urgent",
        "asap",
        "emergency",
        "immediately",
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

    for term in severe_terms:
        if term in normalized:
            severe_score += 1
    for term in self_declared_urgency_terms:
        if term in normalized:
            urgent_word_score += 1
    for term in high_terms:
        if term in normalized:
            high_score += 1
    for term in high_compact_terms:
        if term in compact:
            high_score += 1
    for term in medium_terms:
        if term in normalized:
            medium_score += 1

    # Genuinely severe situations are Urgent on their own.
    if severe_score >= 1:
        return "Urgent"
    # Self-declared urgency language ("urgent"/"asap"/"emergency"/
    # "immediately" -- however many times repeated) is never sufficient by
    # itself; it must be corroborated by an independent High-tier blocker.
    if urgent_word_score >= 1 and high_score >= 1:
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
