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
    return root.resolve()


def _safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^\w.\- ]+", "_", (name or "attachment").strip())[:120]
    return cleaned or "attachment"


def resolve_attachment_path(ticket_id: str, stored_filename: str) -> Path:
    """Resolve an attachment path confined under ``_attachments_root()``.

    Rejects absolute paths, directory separators, and ``..`` escapes so a
    tampered DB ``stored_filename`` cannot read files outside the attachments dir.
    """
    root = _attachments_root()
    tid = (ticket_id or "").strip()
    name = (stored_filename or "").strip()
    if not tid or not name:
        raise ValueError("Attachment path is empty.")
    if Path(tid).name != tid or "/" in tid or "\\" in tid or ".." in tid:
        raise ValueError("Attachment path escapes the attachments root.")
    # stored_filename must be a single basename (no directories).
    if Path(name).name != name or "/" in name or "\\" in name or ".." in name:
        raise ValueError("Attachment path escapes the attachments root.")
    resolved = (root / tid / name).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("Attachment path escapes the attachments root.") from exc
    return resolved


def detect_content_type(content: bytes) -> str | None:
    """Sniff allowed types from magic bytes (ignore client Content-Type)."""
    if not content:
        return None
    if content.startswith(b"%PDF"):
        return "application/pdf"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(content) >= 3 and content[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if content.startswith(b"GIF87a") or content.startswith(b"GIF89a"):
        return "image/gif"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    return None


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
    if actor.role in {"student", "faculty"} and ticket.user_id != actor.id:
        raise TicketAccessError("You can only attach files to your own tickets.")
    if ticket.status == "Closed":
        raise TicketValidationError("Closed tickets do not accept attachments.")

    if len(content) > MAX_TICKET_ATTACHMENT_BYTES:
        raise TicketValidationError("Attachment exceeds the 10 MB limit.")
    if not content:
        raise TicketValidationError("Attachment file is empty.")

    sniffed = detect_content_type(content)
    if sniffed is None or sniffed not in ALLOWED_CONTENT_TYPES:
        raise TicketValidationError("Only images (JPG/PNG/WebP/GIF) and PDF files are allowed.")

    claimed = (content_type or "").split(";")[0].strip().lower()
    if claimed and claimed in ALLOWED_CONTENT_TYPES and claimed != sniffed:
        raise TicketValidationError("Attachment content does not match the declared file type.")

    ctype = sniffed
    attachment_id = str(uuid.uuid4())
    stored_name = f"{attachment_id}_{_safe_filename(filename)}"
    ticket_dir = _attachments_root() / ticket.id
    ticket_dir.mkdir(parents=True, exist_ok=True)
    path = ticket_dir / stored_name
    path.write_bytes(content)

    now = utc_now()
    row = TicketAttachment(
        id=attachment_id,
        ticket_id=ticket.id,
        uploaded_by_id=actor.id,
        original_filename=_safe_filename(filename),
        content_type=ctype,
        size_bytes=len(content),
        stored_filename=stored_name,
        created_at=now,
    )
    ticket.updated_at = now
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
    try:
        path = resolve_attachment_path(ticket.id, row.stored_filename)
    except ValueError as exc:
        raise TicketNotFoundError("Attachment file is missing on disk.") from exc
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
