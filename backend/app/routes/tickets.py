"""Smart ticketing API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.db.session import get_db_session
from app.models.db_models import User
from app.models.schemas import (
    AddTicketReplyRequest,
    CreateTicketRequest,
    NotificationListResponse,
    NotificationSchema,
    OfficeListResponse,
    OfficeSummarySchema,
    TicketAttachmentSchema,
    TicketAuditEventSchema,
    TicketListResponse,
    TicketSchema,
    TicketStatisticsResponse,
    TicketTriageSchema,
    UpdateTicketRequest,
)
from app.services.auth import get_current_user
from app.services.ticket_attachments import add_ticket_attachment, attachment_file_path
from app.services.ticket_audit import list_ticket_audit_events
from app.services.ticket_notifications import (
    list_notifications,
    mark_all_notifications_read,
    mark_notification_read,
    notification_schema,
    unread_notification_count,
)
from app.services.ticketing import (
    TicketAccessError,
    TicketNotFoundError,
    TicketValidationError,
    add_ticket_reply,
    create_ticket,
    get_ticket,
    list_offices,
    list_tickets,
    ticket_statistics,
    triage_ticket,
    update_ticket,
)
from app.services.triage_rate_limit import check_triage_rate_limit


router = APIRouter(prefix="/tickets", tags=["Smart Ticketing"])


@router.post("/triage", response_model=TicketTriageSchema)
async def triage_ticket_preview(
    payload: CreateTicketRequest,
    request: Request,
    session: Session = Depends(get_db_session),
) -> TicketTriageSchema:
    client = request.client.host if request.client else "unknown"
    if not check_triage_rate_limit(client):
        raise HTTPException(status_code=429, detail="Too many triage requests. Please wait a moment.")
    return TicketTriageSchema(**triage_ticket(payload.original_question, payload.description, session=session))


@router.get("/offices", response_model=OfficeListResponse)
async def list_offices_endpoint(
    _: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> OfficeListResponse:
    offices = list_offices(session)
    items = [
        OfficeSummarySchema(id=office.id, name=office.name, service_category=office.service_category)
        for office in offices
    ]
    return OfficeListResponse(items=items, total=len(items))


@router.post("", response_model=TicketSchema)
async def create_ticket_endpoint(
    payload: CreateTicketRequest,
    actor: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> TicketSchema:
    try:
        return create_ticket(session, payload, actor)
    except TicketAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except TicketValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("", response_model=TicketListResponse)
async def list_tickets_endpoint(
    status: str | None = Query(default=None),
    priority: str | None = Query(default=None),
    office: str | None = Query(default=None),
    actor: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> TicketListResponse:
    items = list_tickets(session, actor, status=status, priority=priority, office=office)
    return TicketListResponse(items=items, total=len(items))


@router.get("/statistics", response_model=TicketStatisticsResponse)
async def ticket_statistics_endpoint(
    actor: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> TicketStatisticsResponse:
    try:
        return TicketStatisticsResponse(**ticket_statistics(session, actor))
    except TicketAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/notifications", response_model=NotificationListResponse)
async def list_notifications_endpoint(
    unread_only: bool = Query(default=False),
    actor: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> NotificationListResponse:
    items = [notification_schema(item) for item in list_notifications(session, actor, unread_only=unread_only)]
    return NotificationListResponse(
        items=items,
        total=len(items),
        unread_count=unread_notification_count(session, actor),
    )


@router.post("/notifications/read-all")
async def mark_all_notifications_read_endpoint(
    actor: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> dict:
    count = mark_all_notifications_read(session, actor)
    return {"marked_read": count}


@router.patch("/notifications/{notification_id}/read", response_model=NotificationSchema)
async def mark_notification_read_endpoint(
    notification_id: str,
    actor: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> NotificationSchema:
    item = mark_notification_read(session, actor, notification_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Notification not found.")
    return notification_schema(item)


@router.get("/{ticket_id}", response_model=TicketSchema)
async def get_ticket_endpoint(
    ticket_id: str,
    actor: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> TicketSchema:
    try:
        return get_ticket(session, ticket_id, actor)
    except TicketNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TicketAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/{ticket_id}/audit", response_model=list[TicketAuditEventSchema])
async def get_ticket_audit_endpoint(
    ticket_id: str,
    actor: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> list[TicketAuditEventSchema]:
    try:
        get_ticket(session, ticket_id, actor)
    except TicketNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TicketAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    events = list_ticket_audit_events(session, ticket_id)
    return [
        TicketAuditEventSchema(
            id=event.id,
            ticket_id=event.ticket_id,
            actor_id=event.actor_id,
            actor_role=event.actor_role,
            action=event.action,
            field_name=event.field_name,
            old_value=event.old_value,
            new_value=event.new_value,
            created_at=event.created_at.isoformat() if event.created_at else "",
        )
        for event in events
    ]


@router.patch("/{ticket_id}", response_model=TicketSchema)
async def update_ticket_endpoint(
    ticket_id: str,
    payload: UpdateTicketRequest,
    actor: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> TicketSchema:
    try:
        return update_ticket(session, ticket_id, payload, actor)
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
    actor: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> TicketSchema:
    try:
        return add_ticket_reply(session, ticket_id, payload.message, actor)
    except TicketNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TicketValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except TicketAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/{ticket_id}/attachments", response_model=TicketAttachmentSchema)
async def upload_ticket_attachment_endpoint(
    ticket_id: str,
    file: UploadFile = File(...),
    actor: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> TicketAttachmentSchema:
    content = await file.read()
    try:
        return add_ticket_attachment(
            session,
            ticket_id,
            actor=actor,
            filename=file.filename or "attachment",
            content_type=file.content_type or "application/octet-stream",
            content=content,
        )
    except TicketNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TicketValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except TicketAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/{ticket_id}/attachments/{attachment_id}/download")
async def download_ticket_attachment_endpoint(
    ticket_id: str,
    attachment_id: str,
    actor: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
):
    try:
        path, row = attachment_file_path(session, ticket_id, attachment_id, actor)
    except TicketNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TicketAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return FileResponse(
        path,
        media_type=row.content_type,
        filename=row.original_filename,
    )