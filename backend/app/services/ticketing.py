"""Smart ticketing storage, triage, and access helpers."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import settings
from app.models.schemas import CreateTicketRequest, TicketSchema, UpdateTicketRequest
from app.services.knowledge_taxonomy import classify_question


@dataclass(frozen=True)
class TicketActor:
    user_id: str
    role: str
    name: str
    email: str | None = None
    office: str | None = None


class TicketAccessError(PermissionError):
    pass


class TicketNotFoundError(LookupError):
    pass


class TicketValidationError(ValueError):
    pass


def triage_ticket(question: str, description: str = "") -> dict[str, Any]:
    text = " ".join(part for part in (question, description) if part).strip()
    classification = classify_question(question or text)
    return {
        "category": classification.category,
        "assigned_office": classification.office,
        "priority": _priority_for_text(text),
        "confidence": classification.confidence,
        "method": classification.method,
    }


def create_ticket(payload: CreateTicketRequest, actor: TicketActor) -> TicketSchema:
    _require_role(actor, {"student", "admin"})
    now = _now()
    triage = triage_ticket(payload.original_question, payload.description)
    ticket = {
        "id": _ticket_id(),
        "user_id": actor.user_id,
        "user_name": actor.name,
        "user_email": actor.email,
        "original_question": payload.original_question.strip(),
        "description": payload.description.strip(),
        "category": triage["category"],
        "assigned_office": triage["assigned_office"],
        "priority": triage["priority"],
        "status": "Open",
        "confidence_score": payload.confidence_score,
        "source_from_chatbot": payload.source_from_chatbot,
        "created_at": now,
        "updated_at": now,
        "resolved_at": None,
        "closed_at": None,
        "messages": [],
    }
    tickets = _load_tickets()
    tickets.append(ticket)
    _save_tickets(tickets)
    return TicketSchema(**ticket)


def list_tickets(
    actor: TicketActor,
    *,
    status: str | None = None,
    priority: str | None = None,
    office: str | None = None,
) -> list[TicketSchema]:
    tickets = [_schema(item) for item in _load_tickets()]
    visible = [ticket for ticket in tickets if _can_view(ticket, actor)]
    if status:
        visible = [ticket for ticket in visible if _same(ticket.status, status)]
    if priority:
        visible = [ticket for ticket in visible if _same(ticket.priority, priority)]
    if office and actor.role == "admin":
        visible = [ticket for ticket in visible if _same(ticket.assigned_office, office)]
    return sorted(visible, key=lambda ticket: ticket.updated_at, reverse=True)


def get_ticket(ticket_id: str, actor: TicketActor) -> TicketSchema:
    ticket = _find_ticket(ticket_id)
    if not _can_view(ticket, actor):
        raise TicketAccessError("You do not have access to this ticket.")
    return ticket


def update_ticket(ticket_id: str, payload: UpdateTicketRequest, actor: TicketActor) -> TicketSchema:
    tickets = _load_tickets()
    index, ticket = _find_raw_ticket(tickets, ticket_id)
    current = _schema(ticket)
    if not _can_update(current, actor):
        raise TicketAccessError("You do not have permission to update this ticket.")

    next_status = payload.status or current.status
    if payload.status and not _valid_status_transition(current.status, payload.status, actor.role):
        raise TicketValidationError(f"Cannot move ticket from {current.status} to {payload.status}.")

    if payload.assigned_office is not None:
        _require_role(actor, {"admin"})
        ticket["assigned_office"] = payload.assigned_office.strip()
    if payload.category is not None:
        _require_role(actor, {"admin"})
        ticket["category"] = payload.category.strip()
    if payload.priority is not None:
        if actor.role != "admin" and actor.role != "office":
            raise TicketAccessError("Only office staff or admin can change priority.")
        ticket["priority"] = payload.priority

    ticket["status"] = next_status
    ticket["updated_at"] = _now()
    if next_status == "Resolved" and not ticket.get("resolved_at"):
        ticket["resolved_at"] = ticket["updated_at"]
    if next_status == "Closed" and not ticket.get("closed_at"):
        ticket["closed_at"] = ticket["updated_at"]

    tickets[index] = ticket
    _save_tickets(tickets)
    return _schema(ticket)


def add_ticket_reply(ticket_id: str, message: str, actor: TicketActor) -> TicketSchema:
    tickets = _load_tickets()
    index, ticket = _find_raw_ticket(tickets, ticket_id)
    current = _schema(ticket)
    if not _can_view(current, actor):
        raise TicketAccessError("You do not have access to this ticket.")
    if current.status == "Closed":
        raise TicketValidationError("Closed tickets do not accept new replies.")

    now = _now()
    ticket.setdefault("messages", []).append(
        {
            "id": uuid.uuid4().hex,
            "ticket_id": current.id,
            "sender_id": actor.user_id,
            "sender_role": actor.role,
            "sender_name": actor.name,
            "message": message.strip(),
            "created_at": now,
        }
    )
    ticket["updated_at"] = now
    tickets[index] = ticket
    _save_tickets(tickets)
    return _schema(ticket)


def ticket_statistics(actor: TicketActor) -> dict[str, Any]:
    _require_role(actor, {"admin"})
    tickets = [_schema(item) for item in _load_tickets()]
    by_office: dict[str, int] = {}
    for ticket in tickets:
        by_office[ticket.assigned_office] = by_office.get(ticket.assigned_office, 0) + 1
    return {
        "total": len(tickets),
        "open": sum(1 for ticket in tickets if ticket.status == "Open"),
        "in_progress": sum(1 for ticket in tickets if ticket.status == "In Progress"),
        "resolved": sum(1 for ticket in tickets if ticket.status == "Resolved"),
        "closed": sum(1 for ticket in tickets if ticket.status == "Closed"),
        "by_office": by_office,
    }


def _priority_for_text(text: str) -> str:
    normalized = _normalize(text)
    high_terms = (
        "urgent",
        "deadline",
        "blocked enrollment",
        "cannot enroll",
        "can't enroll",
        "cannot login",
        "can't log in",
        "cannot access",
        "can't access",
        "locked account",
        "payment validation",
        "graduation clearance",
        "clearance blocker",
        "system outage",
        "down",
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
    if any(term in normalized for term in high_terms):
        return "High"
    if any(term in normalized for term in medium_terms):
        return "Medium"
    return "Low"


def _can_view(ticket: TicketSchema, actor: TicketActor) -> bool:
    if actor.role == "admin":
        return True
    if actor.role == "student":
        return ticket.user_id == actor.user_id
    if actor.role == "office":
        return bool(actor.office) and _same(ticket.assigned_office, actor.office)
    return False


def _can_update(ticket: TicketSchema, actor: TicketActor) -> bool:
    if actor.role == "admin":
        return True
    if actor.role == "office":
        return bool(actor.office) and _same(ticket.assigned_office, actor.office)
    if actor.role == "student":
        return ticket.user_id == actor.user_id and ticket.status == "Resolved"
    return False


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


def _find_ticket(ticket_id: str) -> TicketSchema:
    return _schema(_find_raw_ticket(_load_tickets(), ticket_id)[1])


def _find_raw_ticket(tickets: list[dict[str, Any]], ticket_id: str) -> tuple[int, dict[str, Any]]:
    for index, ticket in enumerate(tickets):
        if ticket.get("id") == ticket_id:
            return index, dict(ticket)
    raise TicketNotFoundError("Ticket not found.")


def _schema(ticket: dict[str, Any]) -> TicketSchema:
    return TicketSchema(**ticket)


def _require_role(actor: TicketActor, allowed: set[str]) -> None:
    if actor.role not in allowed:
        raise TicketAccessError("This role cannot perform the requested action.")


def _load_tickets() -> list[dict[str, Any]]:
    path = _store_path()
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else []


def _save_tickets(tickets: list[dict[str, Any]]) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(tickets, indent=2), encoding="utf-8")


def _store_path() -> Path:
    path = Path(settings.ticket_store_path)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[2] / path
    return path


def _ticket_id() -> str:
    return f"TK-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _same(left: str, right: str) -> bool:
    return _normalize(left) == _normalize(right)


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").lower()).strip()
