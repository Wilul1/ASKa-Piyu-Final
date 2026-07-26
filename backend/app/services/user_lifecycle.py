"""Admin hard-delete helpers that clear campus FK references first."""

from __future__ import annotations

import logging
from pathlib import Path

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
from app.services.ticket_attachments import resolve_attachment_path

logger = logging.getLogger(__name__)


def _attachment_disk_paths(rows: list[TicketAttachment]) -> list[Path]:
    paths: list[Path] = []
    for row in rows:
        try:
            paths.append(resolve_attachment_path(row.ticket_id, row.stored_filename))
        except ValueError:
            continue
    return paths


def _unlink_attachment_files(paths: list[Path]) -> None:
    ticket_dirs: set[Path] = set()
    for path in paths:
        try:
            if path.is_file():
                path.unlink()
            if path.parent.is_dir():
                ticket_dirs.add(path.parent)
        except OSError:
            logger.warning("Could not delete attachment file %s", path, exc_info=True)
    for directory in ticket_dirs:
        try:
            if directory.is_dir() and not any(directory.iterdir()):
                directory.rmdir()
        except OSError:
            logger.warning("Could not remove attachment dir %s", directory, exc_info=True)


def hard_delete_user(session: Session, user: User) -> list[Path]:
    """Remove a user and dependent rows so ticket FKs cannot block delete.

    Prefer disable (``is_active=false``) for normal offboarding. Hard delete is
    for mistaken accounts / GDPR-style removal and will remove the user's tickets.

    Returns attachment file paths to delete **after** a successful DB commit.
    """
    user_id = user.id
    owned_ticket_ids = [
        row[0]
        for row in session.query(Ticket.id).filter(Ticket.user_id == user_id).all()
    ]

    attachment_rows: list[TicketAttachment] = []
    if owned_ticket_ids:
        attachment_rows.extend(
            session.query(TicketAttachment)
            .filter(TicketAttachment.ticket_id.in_(owned_ticket_ids))
            .all()
        )
    # Files this user uploaded on other users' tickets.
    attachment_rows.extend(
        session.query(TicketAttachment)
        .filter(TicketAttachment.uploaded_by_id == user_id)
        .all()
    )
    # Deduplicate by id while preserving path collection order.
    seen_ids: set[str] = set()
    unique_attachments: list[TicketAttachment] = []
    for row in attachment_rows:
        if row.id in seen_ids:
            continue
        seen_ids.add(row.id)
        unique_attachments.append(row)
    disk_paths = _attachment_disk_paths(unique_attachments)

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
    return disk_paths


def remove_attachment_files(paths: list[Path]) -> None:
    """Delete attachment files collected by :func:`hard_delete_user` after commit."""
    _unlink_attachment_files(paths)
