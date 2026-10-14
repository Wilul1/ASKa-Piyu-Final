"""Smart ticketing API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.db.session import get_db_session
from app.models.db_models import User
from app.models.schemas import (
    AddTicketReplyRequest,
    ConvertTicketToArticleRequest,
    CreateOfficeRequest,
    CreateTicketRequest,
    CreateTicketTransferRequest,
    NotificationListResponse,
    NotificationSchema,
    OfficeListResponse,
    OfficeSummarySchema,
    RejectTicketTransferRequest,
    TicketAttachmentSchema,
    TicketAuditEventSchema,
    TicketKbArticleSchema,
    TicketKbDuplicateCheckResponse,
    TicketKbImageUploadResponse,
    TicketListResponse,
    TicketSchema,
    TicketStatisticsResponse,
    TicketTransferRequestListResponse,
    TicketTransferRequestSchema,
    TicketTriageSchema,
    TransferNotificationUnreadCountResponse,
    UpdateTicketRequest,
)
from app.services.auth import get_current_user, require_verified_email_for_tickets
from app.services.ticket_attachments import add_ticket_attachment, attachment_file_path
from app.services.ticket_audit import list_ticket_audit_events
from app.services.ticket_knowledge import (
    TicketKnowledgeAccessError,
    TicketKnowledgeError,
    TicketKnowledgeNotFoundError,
    check_ticket_kb_duplicate,
    convert_ticket_to_draft_article,
    get_ticket_kb_article,
    save_ticket_kb_image,
)
from app.services.ticket_notifications import (
    list_notifications,
    mark_all_notifications_read,
    mark_notification_read,
    mark_transfer_notifications_read,
    notification_schema,
    unread_notification_count,
    unread_transfer_notification_count,
)
from app.services.ticketing import (
    TicketAccessError,
    TicketNotFoundError,
    TicketValidationError,
    accept_ticket_transfer,
    add_ticket_reply,
    close_ticket,
    delete_office,
    create_office,
    create_ticket,
    get_ticket,
    list_incoming_ticket_transfers,
    list_offices,
    list_outgoing_ticket_transfers,
    list_ticket_transfer_requests,
    list_tickets,
    reject_ticket_transfer,
    request_ticket_transfer,
    resolve_ticket,
    ticket_statistics,
    triage_ticket,
    update_ticket,
)
from app.services.triage_rate_limit import check_triage_rate_limit


router = APIRouter(prefix="/tickets", tags=["Smart Ticketing"])


@router.post("/triage", response_model=TicketTriageSchema)
async def triage_ticket_preview(
    payload: CreateTicketRequest,
    actor: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> TicketTriageSchema:
    rate_key = f"user:{actor.id}"
    if not check_triage_rate_limit(rate_key):
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


@router.post("/offices", response_model=OfficeSummarySchema)
async def create_office_endpoint(
    payload: CreateOfficeRequest,
    actor: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> OfficeSummarySchema:
    if str(actor.role).strip().lower() != "admin":
        raise HTTPException(status_code=403, detail="Only admins can create offices.")
    try:
        office = create_office(
            session,
            name=payload.name,
            service_category=payload.service_category,
            description=payload.description,
        )
    except TicketValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return OfficeSummarySchema(
        id=office.id,
        name=office.name,
        service_category=office.service_category,
    )


@router.delete("/offices/{office_id}")
async def delete_office_endpoint(
    office_id: str,
    actor: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> dict[str, str]:
    if str(actor.role).strip().lower() != "admin":
        raise HTTPException(status_code=403, detail="Only admins can delete offices.")
    try:
        delete_office(session, office_id)
    except TicketValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"status": "success", "detail": "Office deleted."}


@router.post("", response_model=TicketSchema)
async def create_ticket_endpoint(
    payload: CreateTicketRequest,
    actor: User = Depends(require_verified_email_for_tickets),
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


@router.post("/notifications/transfers/read-all")
async def mark_transfer_notifications_read_endpoint(
    actor: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> dict:
    # Transfer notifications only ever reach office/admin recipients (see
    # notify_office_id_staff), so this is already a harmless no-op for any
    # other role via the user-scoped query below -- this check just makes
    # that explicit at the boundary, matching this router's existing
    # inline-role-check convention (see create_office_endpoint above),
    # rather than leaving it to be inferred from the query's scoping.
    if actor.role not in {"office", "admin"}:
        raise HTTPException(
            status_code=403, detail="Only office staff or admins can use this endpoint."
        )
    count = mark_transfer_notifications_read(session, actor)
    return {"marked_read": count}


@router.get(
    "/notifications/transfers/unread-count",
    response_model=TransferNotificationUnreadCountResponse,
)
async def unread_transfer_notification_count_endpoint(
    actor: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> TransferNotificationUnreadCountResponse:
    if actor.role not in {"office", "admin"}:
        raise HTTPException(
            status_code=403, detail="Only office staff or admins can use this endpoint."
        )
    return TransferNotificationUnreadCountResponse(
        unread_count=unread_transfer_notification_count(session, actor)
    )


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


@router.get("/{ticket_id}/kb-article", response_model=TicketKbArticleSchema | None)
async def get_ticket_kb_article_endpoint(
    ticket_id: str,
    actor: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> TicketKbArticleSchema | None:
    try:
        payload = get_ticket_kb_article(session, ticket_id=ticket_id, actor=actor)
    except TicketKnowledgeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TicketKnowledgeAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if payload is None:
        return None
    return TicketKbArticleSchema(**payload)


@router.get("/{ticket_id}/kb-duplicate-check", response_model=TicketKbDuplicateCheckResponse)
async def check_ticket_kb_duplicate_endpoint(
    ticket_id: str,
    title: str = Query(..., min_length=3, max_length=240),
    actor: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> TicketKbDuplicateCheckResponse:
    try:
        result = check_ticket_kb_duplicate(
            session,
            ticket_id=ticket_id,
            actor=actor,
            title=title,
        )
    except TicketKnowledgeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TicketKnowledgeAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except TicketKnowledgeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return TicketKbDuplicateCheckResponse(**result)


@router.post("/{ticket_id}/convert-to-article", response_model=TicketKbArticleSchema)
async def convert_ticket_to_article_endpoint(
    ticket_id: str,
    payload: ConvertTicketToArticleRequest | None = None,
    actor: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> TicketKbArticleSchema:
    body = payload or ConvertTicketToArticleRequest()
    try:
        result = convert_ticket_to_draft_article(
            session,
            ticket_id=ticket_id,
            actor=actor,
            title=body.title,
            content=body.content,
            summary=body.summary,
            audience=body.audience,
        )
    except TicketKnowledgeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TicketKnowledgeAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except TicketKnowledgeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return TicketKbArticleSchema(**result)


@router.post("/{ticket_id}/kb-images", response_model=TicketKbImageUploadResponse)
async def upload_ticket_kb_image_endpoint(
    ticket_id: str,
    file: UploadFile = File(...),
    actor: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> TicketKbImageUploadResponse:
    content = await file.read()
    try:
        result = save_ticket_kb_image(
            session,
            ticket_id=ticket_id,
            actor=actor,
            filename=file.filename or "image",
            content=content,
        )
    except TicketKnowledgeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TicketKnowledgeAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except TicketKnowledgeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return TicketKbImageUploadResponse(**result)


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
        return add_ticket_reply(
            session, ticket_id, payload.message, actor, is_internal=payload.is_internal
        )
    except TicketNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TicketValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except TicketAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/{ticket_id}/resolve", response_model=TicketSchema)
async def resolve_ticket_endpoint(
    ticket_id: str,
    actor: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> TicketSchema:
    try:
        return resolve_ticket(session, ticket_id, actor)
    except TicketNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TicketValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except TicketAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/{ticket_id}/close", response_model=TicketSchema)
async def close_ticket_endpoint(
    ticket_id: str,
    actor: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> TicketSchema:
    try:
        return close_ticket(session, ticket_id, actor)
    except TicketNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TicketValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except TicketAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/{ticket_id}/transfers", response_model=TicketTransferRequestSchema)
async def request_ticket_transfer_endpoint(
    ticket_id: str,
    payload: CreateTicketTransferRequest,
    actor: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> TicketTransferRequestSchema:
    try:
        return request_ticket_transfer(
            session,
            ticket_id,
            destination_office_id=payload.destination_office_id,
            reason=payload.reason,
            actor=actor,
        )
    except TicketNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TicketValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except TicketAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/{ticket_id}/transfers", response_model=TicketTransferRequestListResponse)
async def list_ticket_transfer_requests_endpoint(
    ticket_id: str,
    actor: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> TicketTransferRequestListResponse:
    try:
        items = list_ticket_transfer_requests(session, ticket_id, actor)
        return TicketTransferRequestListResponse(items=items, total=len(items))
    except TicketNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TicketAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/transfers/incoming", response_model=TicketTransferRequestListResponse)
async def list_incoming_ticket_transfers_endpoint(
    actor: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> TicketTransferRequestListResponse:
    items = list_incoming_ticket_transfers(session, actor)
    return TicketTransferRequestListResponse(items=items, total=len(items))


@router.get("/transfers/outgoing", response_model=TicketTransferRequestListResponse)
async def list_outgoing_ticket_transfers_endpoint(
    actor: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> TicketTransferRequestListResponse:
    items = list_outgoing_ticket_transfers(session, actor)
    return TicketTransferRequestListResponse(items=items, total=len(items))


@router.post("/transfers/{transfer_id}/accept", response_model=TicketSchema)
async def accept_ticket_transfer_endpoint(
    transfer_id: str,
    actor: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> TicketSchema:
    try:
        return accept_ticket_transfer(session, transfer_id, actor)
    except TicketNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TicketValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except TicketAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/transfers/{transfer_id}/reject", response_model=TicketTransferRequestSchema)
async def reject_ticket_transfer_endpoint(
    transfer_id: str,
    payload: RejectTicketTransferRequest | None = None,
    actor: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> TicketTransferRequestSchema:
    try:
        return reject_ticket_transfer(
            session,
            transfer_id,
            actor,
            rejection_reason=payload.rejection_reason if payload else None,
        )
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
