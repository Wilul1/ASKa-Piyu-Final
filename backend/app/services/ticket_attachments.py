"""Persist and serve ticket attachment files."""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import settings
from app.models.db_models import Ticket, TicketAttachment, User, utc_now
from app.models.schemas import TicketAttachmentSchema
from app.services.ticketing import TicketAccessError, TicketNotFoundError, TicketValidationError, _can_view, _load_ticket


ALLOWED_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
    "application/pdf",
}
MAX_TICKET_ATTACHMENT_BYTES = 10 * 1024 * 1024


def _attachments_root() -> Path:
    root = Path(settings.ticket_attachments_dir)
    if not root.is_absolute():
        root = Path(__file__).resolve().parents[2] / root
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^\w.\- ]+", "_", (name or "attachment").strip())[:120]
    return cleaned or "attachment"


def add_ticket_attachment(
    session: Session,
    ticket_id: str,
    *,
    actor: User,
    filename: str,
    content_type: str,
    content: bytes,
) -> TicketAttachmentSchema:
    ticket = _load_ticket(session, ticket_id)
    if not _can_view(ticket, actor, session):
        raise TicketAccessError("You do not have access to this ticket.")
    if actor.role == "student" and ticket.user_id != actor.id:
        raise TicketAccessError("You can only attach files to your own tickets.")
    if ticket.status == "Closed":
        raise TicketValidationError("Closed tickets do not accept attachments.")

    ctype = (content_type or "application/octet-stream").split(";")[0].strip().lower()
    if ctype not in ALLOWED_CONTENT_TYPES:
        raise TicketValidationError("Only images (JPG/PNG/WebP/GIF) and PDF files are allowed.")
    if len(content) > MAX_TICKET_ATTACHMENT_BYTES:
        raise TicketValidationError("Attachment exceeds the 10 MB limit.")
    if not content:
        raise TicketValidationError("Attachment file is empty.")

    attachment_id = str(uuid.uuid4())
    stored_name = f"{attachment_id}_{_safe_filename(filename)}"
    ticket_dir = _attachments_root() / ticket.id
    ticket_dir.mkdir(parents=True, exist_ok=True)
    path = ticket_dir / stored_name
    path.write_bytes(content)

    row = TicketAttachment(
        id=attachment_id,
        ticket_id=ticket.id,
        uploaded_by_id=actor.id,
        original_filename=_safe_filename(filename),
        content_type=ctype,
        size_bytes=len(content),
        stored_filename=stored_name,
        created_at=utc_now(),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return attachment_schema(row)


def attachment_file_path(session: Session, ticket_id: str, attachment_id: str, actor: User) -> tuple[Path, TicketAttachment]:
    ticket = _load_ticket(session, ticket_id)
    if not _can_view(ticket, actor, session):
        raise TicketAccessError("You do not have access to this ticket.")
    row = (
        session.query(TicketAttachment)
        .filter(TicketAttachment.id == attachment_id, TicketAttachment.ticket_id == ticket.id)
        .one_or_none()
    )
    if row is None:
        raise TicketNotFoundError("Attachment not found.")
    path = _attachments_root() / ticket.id / row.stored_filename
    if not path.is_file():
        raise TicketNotFoundError("Attachment file is missing on disk.")
    return path, row


def attachment_schema(row: TicketAttachment) -> TicketAttachmentSchema:
    return TicketAttachmentSchema(
        id=row.id,
        ticket_id=row.ticket_id,
        original_filename=row.original_filename,
        content_type=row.content_type,
        size_bytes=row.size_bytes,
        uploaded_by_id=row.uploaded_by_id,
        created_at=row.created_at.isoformat() if row.created_at else "",
        download_url=f"/tickets/{row.ticket_id}/attachments/{row.id}/download",
    )
