"""In-app notifications for ticket activity."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models.db_models import Notification, Ticket, User, utc_now
from app.models.schemas import NotificationSchema


def notify_user(
    session: Session,
    *,
    user_id: str,
    ticket_id: str | None,
    type: str,
    title: str,
    body: str,
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
