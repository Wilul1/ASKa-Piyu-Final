"""Admin hard-delete helpers that clear campus FK references first."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.db_models import (
    Announcement,
    Notification,
    PublishedArticle,
    Ticket,
    TicketAttachment,
    TicketAuditEvent,
    TicketReply,
    User,
)


def hard_delete_user(session: Session, user: User) -> None:
    """Remove a user and dependent rows so ticket FKs cannot block delete.

    Prefer disable (``is_active=false``) for normal offboarding. Hard delete is
    for mistaken accounts / GDPR-style removal and will remove the user's tickets.
    """
    user_id = user.id
    owned_ticket_ids = [
        row[0]
        for row in session.query(Ticket.id).filter(Ticket.user_id == user_id).all()
    ]

    if owned_ticket_ids:
        # Articles may FK to tickets; detach before wiping ticket rows.
        session.query(PublishedArticle).filter(
            PublishedArticle.source_ticket_id.in_(owned_ticket_ids)
        ).update({PublishedArticle.source_ticket_id: None}, synchronize_session=False)
        session.query(Notification).filter(
            Notification.ticket_id.in_(owned_ticket_ids)
        ).delete(synchronize_session=False)
        session.query(TicketAuditEvent).filter(
            TicketAuditEvent.ticket_id.in_(owned_ticket_ids)
        ).delete(synchronize_session=False)
        # Replies/attachments cascade from Ticket relationships, but delete
        # explicitly so SQLite/Postgres behave the same without relying on ORM load.
        session.query(TicketReply).filter(
            TicketReply.ticket_id.in_(owned_ticket_ids)
        ).delete(synchronize_session=False)
        session.query(TicketAttachment).filter(
            TicketAttachment.ticket_id.in_(owned_ticket_ids)
        ).delete(synchronize_session=False)
        session.query(Ticket).filter(Ticket.id.in_(owned_ticket_ids)).delete(
            synchronize_session=False
        )

    # Activity on other users' tickets.
    session.query(TicketReply).filter(TicketReply.sender_id == user_id).delete(
        synchronize_session=False
    )
    session.query(TicketAttachment).filter(
        TicketAttachment.uploaded_by_id == user_id
    ).delete(synchronize_session=False)
    session.query(TicketAuditEvent).filter(TicketAuditEvent.actor_id == user_id).update(
        {TicketAuditEvent.actor_id: None},
        synchronize_session=False,
    )
    session.query(Notification).filter(Notification.user_id == user_id).delete(
        synchronize_session=False
    )
    session.query(PublishedArticle).filter(
        PublishedArticle.created_by_user_id == user_id
    ).update({PublishedArticle.created_by_user_id: None}, synchronize_session=False)
    session.query(PublishedArticle).filter(
        PublishedArticle.published_by_user_id == user_id
    ).update({PublishedArticle.published_by_user_id: None}, synchronize_session=False)
    session.query(Announcement).filter(
        Announcement.created_by_user_id == user_id
    ).update({Announcement.created_by_user_id: None}, synchronize_session=False)

    session.delete(user)
