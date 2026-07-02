"""Smart ticketing API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from app.models.schemas import (
    AddTicketReplyRequest,
    CreateTicketRequest,
    TicketListResponse,
    TicketSchema,
    TicketStatisticsResponse,
    TicketTriageSchema,
    UpdateTicketRequest,
)
from app.services.ticketing import (
    TicketAccessError,
    TicketActor,
    TicketNotFoundError,
    TicketValidationError,
    add_ticket_reply,
    create_ticket,
    get_ticket,
    list_tickets,
    ticket_statistics,
    triage_ticket,
    update_ticket,
)


router = APIRouter(prefix="/tickets", tags=["Smart Ticketing"])


def ticket_actor(
    x_user_id: str | None = Header(default=None, alias="x-user-id"),
    x_user_role: str | None = Header(default=None, alias="x-user-role"),
    x_user_name: str | None = Header(default=None, alias="x-user-name"),
    x_user_email: str | None = Header(default=None, alias="x-user-email"),
    x_user_office: str | None = Header(default=None, alias="x-user-office"),
) -> TicketActor:
    role = (x_user_role or "").strip().lower()
    if role not in {"student", "office", "admin"}:
        raise HTTPException(status_code=401, detail="Set x-user-role to student, office, or admin.")
    user_id = (x_user_id or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="Set x-user-id for ticket access.")
    if role == "office" and not (x_user_office or "").strip():
        raise HTTPException(status_code=401, detail="Set x-user-office for office ticket access.")
    return TicketActor(
        user_id=user_id,
        role=role,
        name=(x_user_name or user_id).strip(),
        email=(x_user_email or "").strip() or None,
        office=(x_user_office or "").strip() or None,
    )


@router.post("/triage", response_model=TicketTriageSchema)
async def triage_ticket_preview(payload: CreateTicketRequest) -> TicketTriageSchema:
    return TicketTriageSchema(**triage_ticket(payload.original_question, payload.description))


@router.post("", response_model=TicketSchema)
async def create_ticket_endpoint(
    payload: CreateTicketRequest,
    actor: TicketActor = Depends(ticket_actor),
) -> TicketSchema:
    try:
        return create_ticket(payload, actor)
    except TicketAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("", response_model=TicketListResponse)
async def list_tickets_endpoint(
    status: str | None = Query(default=None),
    priority: str | None = Query(default=None),
    office: str | None = Query(default=None),
    actor: TicketActor = Depends(ticket_actor),
) -> TicketListResponse:
    items = list_tickets(actor, status=status, priority=priority, office=office)
    return TicketListResponse(items=items, total=len(items))


@router.get("/statistics", response_model=TicketStatisticsResponse)
async def ticket_statistics_endpoint(actor: TicketActor = Depends(ticket_actor)) -> TicketStatisticsResponse:
    try:
        return TicketStatisticsResponse(**ticket_statistics(actor))
    except TicketAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/{ticket_id}", response_model=TicketSchema)
async def get_ticket_endpoint(ticket_id: str, actor: TicketActor = Depends(ticket_actor)) -> TicketSchema:
    try:
        return get_ticket(ticket_id, actor)
    except TicketNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TicketAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.patch("/{ticket_id}", response_model=TicketSchema)
async def update_ticket_endpoint(
    ticket_id: str,
    payload: UpdateTicketRequest,
    actor: TicketActor = Depends(ticket_actor),
) -> TicketSchema:
    try:
        return update_ticket(ticket_id, payload, actor)
    except TicketNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TicketValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except TicketAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/{ticket_id}/replies", response_model=TicketSchema)
async def add_ticket_reply_endpoint(
    ticket_id: str,
    payload: AddTicketReplyRequest,
    actor: TicketActor = Depends(ticket_actor),
) -> TicketSchema:
    try:
        return add_ticket_reply(ticket_id, payload.message, actor)
    except TicketNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TicketValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except TicketAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
