"""In-app notifications for ticket activity."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models.db_models import Notification, Ticket, User, utc_now
from app.models.schemas import NotificationSchema


#: Notification `type` values exclusive to the transfer workflow (never
#: used by any other code path) -- used to scope the transfer-specific
#: mark-read/unread-count operations below, and the Flutter badge filter.
TRANSFER_NOTIFICATION_TYPES = ("transfer_requested", "transfer_accepted", "transfer_rejected")


def notify_user(
    session: Session,
    *,
    user_id: str,
    ticket_id: str | None,
    type: str,
    title: str,
    body: str,
    transfer_request_id: str | None = None,
) -> Notification:
    item = Notification(
        id=str(uuid.uuid4()),
        user_id=user_id,
        ticket_id=ticket_id,
        type=type,
        title=title,
        body=body,
        is_read=False,
        created_at=utc_now(),
        transfer_request_id=transfer_request_id,
    )
    session.add(item)
    return item


def notify_ticket_owner(
    session: Session,
    ticket: Ticket,
    *,
    type: str,
    title: str,
    body: str,
    exclude_user_id: str | None = None,
) -> None:
    if exclude_user_id and ticket.user_id == exclude_user_id:
        return
    notify_user(
        session,
        user_id=ticket.user_id,
        ticket_id=ticket.id,
        type=type,
        title=title,
        body=body,
    )


def notify_office_staff(
    session: Session,
    ticket: Ticket,
    *,
    type: str,
    title: str,
    body: str,
    exclude_user_id: str | None = None,
) -> None:
    if not ticket.assigned_office_id:
        return
    staff = (
        session.query(User)
        .filter(User.role == "office", User.office_id == ticket.assigned_office_id)
        .all()
    )
    for user in staff:
        if exclude_user_id and user.id == exclude_user_id:
            continue
        notify_user(
            session,
            user_id=user.id,
            ticket_id=ticket.id,
            type=type,
            title=title,
            body=body,
        )


def notify_office_id_staff(
    session: Session,
    *,
    office_id: str,
    ticket_id: str | None,
    type: str,
    title: str,
    body: str,
    exclude_user_id: str | None = None,
    transfer_request_id: str | None = None,
) -> None:
    """Like notify_office_staff, but for an explicit office_id rather than
    a ticket's own (current) assigned_office_id -- needed for transfer
    requests, where the notified office is the request's destination, not
    necessarily the ticket's current office."""
    staff = session.query(User).filter(User.role == "office", User.office_id == office_id).all()
    for user in staff:
        if exclude_user_id and user.id == exclude_user_id:
            continue
        notify_user(
            session,
            user_id=user.id,
            ticket_id=ticket_id,
            type=type,
            title=title,
            body=body,
            transfer_request_id=transfer_request_id,
        )


def list_notifications(session: Session, user: User, *, unread_only: bool = False) -> list[Notification]:
    query = session.query(Notification).filter(Notification.user_id == user.id)
    if unread_only:
        query = query.filter(Notification.is_read.is_(False))
    return query.order_by(Notification.created_at.desc()).limit(100).all()


def unread_notification_count(session: Session, user: User) -> int:
    return (
        session.query(Notification)
        .filter(Notification.user_id == user.id, Notification.is_read.is_(False))
        .count()
    )


def mark_notification_read(session: Session, user: User, notification_id: str) -> Notification | None:
    item = (
        session.query(Notification)
        .filter(Notification.id == notification_id, Notification.user_id == user.id)
        .one_or_none()
    )
    if item is None:
        return None
    item.is_read = True
    session.commit()
    session.refresh(item)
    return item


def mark_all_notifications_read(session: Session, user: User) -> int:
    items = (
        session.query(Notification)
        .filter(Notification.user_id == user.id, Notification.is_read.is_(False))
        .all()
    )
    for item in items:
        item.is_read = True
    session.commit()
    return len(items)


def mark_transfer_notifications_read(session: Session, user: User) -> int:
    """Explicit, user-initiated bulk action: marks read every one of the
    caller's own unread transfer-specific notifications (transfer_requested
    / transfer_accepted / transfer_rejected), and nothing else -- never a
    different type, never another user's row. This is a bulk action, not a
    precise per-notification one: the Notification model (and the Flutter
    client) has no stable way to target "this one outgoing notification"
    individually, since the mailbox only knows transfer-request ids, not
    notification ids. Marking the caller's whole transfer-notification
    backlog read in one explicit action is the safest supported
    alternative without adding a finer-grained (and currently unneeded)
    per-notification identifier to the API."""
    items = (
        session.query(Notification)
        .filter(
            Notification.user_id == user.id,
            Notification.is_read.is_(False),
            Notification.type.in_(TRANSFER_NOTIFICATION_TYPES),
        )
        .all()
    )
    for item in items:
        item.is_read = True
    session.commit()
    return len(items)


def unread_transfer_notification_count(session: Session, user: User) -> int:
    """Direct COUNT query, never windowed by list_notifications()'s
    100-row cap -- so this stays accurate even once a user's total unread
    notification backlog (of ANY type) exceeds 100, unlike client-side
    filtering of the paginated list."""
    return (
        session.query(Notification)
        .filter(
            Notification.user_id == user.id,
            Notification.is_read.is_(False),
            Notification.type.in_(TRANSFER_NOTIFICATION_TYPES),
        )
        .count()
    )


def notification_schema(item: Notification) -> NotificationSchema:
    return NotificationSchema(
        id=item.id,
        ticket_id=item.ticket_id,
        type=item.type,
        title=item.title,
        body=item.body,
        is_read=item.is_read,
        created_at=item.created_at.isoformat() if item.created_at else "",
    )
