"""Convert resolved tickets into draft knowledge-base FAQs."""

from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy.orm import Session, joinedload

from app.models.db_models import PublishedArticle, Ticket, TicketReply, User, utc_now
from app.services.ticket_audit import record_ticket_audit


class TicketKnowledgeError(ValueError):
    pass


class TicketKnowledgeAccessError(PermissionError):
    pass


class TicketKnowledgeNotFoundError(LookupError):
    pass


_FACULTY_AUDIENCE_TERMS = (
    "faculty",
    "teaching load",
    "faculty manual",
    "leave form",
    "workload",
    "professor",
    "instructor",
    "faculty grading",
    "faculty duties",
    "academic rank",
)

_STUDENT_AUDIENCE_TERMS = (
    "student",
    "enroll",
    "enrollment",
    "enrolment",
    "excuse slip",
    "student id",
    "tuition",
    "scholarship",
    "registrar",
    "freshman",
    "transferee",
    "graduation",
    "retention",
    "scholastic",
)

_BOTH_AUDIENCE_TERMS = (
    "citizen's charter",
    "citizens charter",
    "citizen charter",
    "campus",
    "all clients",
    "students and faculty",
    "faculty and students",
)

_MIN_RESOLUTION_CHARS = 80


def infer_audience_from_text(*parts: str) -> str:
    blob = " ".join(part for part in parts if part).casefold()
    faculty_hit = any(term in blob for term in _FACULTY_AUDIENCE_TERMS)
    student_hit = any(term in blob for term in _STUDENT_AUDIENCE_TERMS)
    both_hit = any(term in blob for term in _BOTH_AUDIENCE_TERMS)
    if both_hit or (faculty_hit and student_hit):
        return "both"
    if faculty_hit:
        return "faculty"
    if student_hit:
        return "student"
    # Fail closed: unclear ticket text → student, not both.
    return "student"


def convert_ticket_to_draft_article(
    session: Session,
    *,
    ticket_id: str,
    actor: User,
    title: str | None = None,
    content: str | None = None,
    summary: str | None = None,
    audience: str | None = None,
) -> dict[str, Any]:
    ticket = _load_ticket(session, ticket_id)
    _assert_can_convert(actor, ticket)

    if ticket.status not in {"Resolved", "Closed"}:
        raise TicketKnowledgeError("Only Resolved or Closed tickets can be converted to knowledge.")

    resolution = _latest_staff_resolution(ticket)
    if not resolution:
        raise TicketKnowledgeError(
            "Add an office or admin reply with the approved answer before converting."
        )

    existing = (
        session.query(PublishedArticle)
        .filter(PublishedArticle.source_ticket_id == ticket.id)
        .one_or_none()
    )
    if existing is not None and bool(existing.published):
        raise TicketKnowledgeError(
            "This ticket already has a published knowledge article. Unpublish it before re-converting."
        )

    resolved_title = _clean_title(title or ticket.original_question)
    resolved_body = (content or _default_article_content(ticket, resolution)).strip()
    if len(resolved_body) < _MIN_RESOLUTION_CHARS:
        raise TicketKnowledgeError(
            f"Article content must be at least {_MIN_RESOLUTION_CHARS} characters "
            "to save as reusable knowledge."
        )

    resolved_summary = (summary or _short_summary(resolved_body)).strip() or None
    resolved_audience = _normalize_audience(
        audience or infer_audience_from_text(ticket.original_question, ticket.description, resolution)
    )
    slug = _unique_slug(session, resolved_title, exclude_id=existing.id if existing else None)

    if existing is None:
        article = PublishedArticle(
            id=str(uuid.uuid4()),
            title=resolved_title,
            slug=slug,
            category=ticket.category or "General",
            summary=resolved_summary,
            content=resolved_body,
            office=ticket.assigned_office,
            source_filename=f"Ticket FAQ ({ticket.id})",
            source_ticket_id=ticket.id,
            audience=resolved_audience,
            kb_origin="ticket_resolution",
            resolution_summary=resolution.strip(),
            created_by_user_id=actor.id,
            published=False,
            published_at=None,
            rag_indexed=False,
            rag_document_id=None,
            chunk_count=0,
        )
        session.add(article)
        created = True
    else:
        article = existing
        article.title = resolved_title
        article.slug = slug
        article.category = ticket.category or article.category or "General"
        article.summary = resolved_summary
        article.content = resolved_body
        article.office = ticket.assigned_office
        article.source_filename = f"Ticket FAQ ({ticket.id})"
        article.audience = resolved_audience
        article.kb_origin = "ticket_resolution"
        article.resolution_summary = resolution.strip()
        article.published = False
        article.published_at = None
        # Drop any leftover Chroma FAQ vectors from a prior publish before draft rewrite.
        try:
            from app.services.article_rag_indexer import remove_published_article_index

            if article.rag_indexed or article.rag_document_id:
                remove_published_article_index(session, article)
        except Exception:
            article.rag_indexed = False
            article.rag_document_id = None
            article.chunk_count = 0
        article.rag_indexed = False
        article.rag_document_id = None
        article.chunk_count = 0
        created = False
        session.add(article)

    session.flush()
    ticket.kb_article_id = article.id
    ticket.kb_conversion_status = "draft"
    ticket.updated_at = utc_now()
    session.add(ticket)

    record_ticket_audit(
        session,
        ticket_id=ticket.id,
        actor=actor,
        action="kb_convert",
        field_name="kb_article_id",
        old_value=None if created else article.id,
        new_value=article.id,
    )
    session.commit()
    session.refresh(article)
    return article_link_payload(article)


def get_ticket_kb_article(session: Session, *, ticket_id: str, actor: User) -> dict[str, Any] | None:
    ticket = _load_ticket(session, ticket_id)
    _assert_can_view(actor, ticket)
    article = (
        session.query(PublishedArticle)
        .filter(PublishedArticle.source_ticket_id == ticket.id)
        .one_or_none()
    )
    if article is None and ticket.kb_article_id:
        article = session.get(PublishedArticle, ticket.kb_article_id)
    if article is None:
        return None
    return article_link_payload(article)


def article_link_payload(article: PublishedArticle) -> dict[str, Any]:
    return {
        "article_id": article.id,
        "title": article.title,
        "slug": article.slug,
        "category": article.category,
        "office": article.office,
        "audience": article.audience,
        "kb_origin": article.kb_origin,
        "summary": article.summary,
        "content": article.content,
        "resolution_summary": article.resolution_summary,
        "published": bool(article.published),
        "rag_indexed": bool(article.rag_indexed),
        "source_ticket_id": article.source_ticket_id,
        "kb_conversion_status": "published" if article.published else "draft",
        "created_at": article.created_at.isoformat() if article.created_at else None,
        "updated_at": article.updated_at.isoformat() if article.updated_at else None,
        "published_at": article.published_at.isoformat() if article.published_at else None,
    }


def sync_ticket_kb_status(session: Session, article: PublishedArticle) -> None:
    """Keep denormalized ticket conversion status aligned after publish/unpublish."""
    if not article.source_ticket_id:
        return
    ticket = session.get(Ticket, article.source_ticket_id)
    if ticket is None:
        return
    ticket.kb_article_id = article.id
    ticket.kb_conversion_status = "published" if article.published else "draft"
    ticket.updated_at = utc_now()
    session.add(ticket)


def _load_ticket(session: Session, ticket_id: str) -> Ticket:
    ticket = (
        session.query(Ticket)
        .options(
            joinedload(Ticket.replies),
            joinedload(Ticket.assigned_office_ref),
            joinedload(Ticket.user),
        )
        .filter(Ticket.id == ticket_id)
        .one_or_none()
    )
    if ticket is None:
        raise TicketKnowledgeNotFoundError(f"Ticket {ticket_id} was not found.")
    return ticket


def _assert_can_convert(actor: User, ticket: Ticket) -> None:
    if actor.role == "admin":
        return
    if actor.role == "office":
        if ticket.assigned_office_id and actor.office_id == ticket.assigned_office_id:
            return
        if actor.office and actor.office.name.casefold() == (ticket.assigned_office or "").casefold():
            return
        raise TicketKnowledgeAccessError("Offices can only convert tickets assigned to their office.")
    raise TicketKnowledgeAccessError("Only office staff or admins can convert tickets to knowledge.")


def _assert_can_view(actor: User, ticket: Ticket) -> None:
    if actor.role == "admin":
        return
    if actor.role == "office":
        _assert_can_convert(actor, ticket)
        return
    if actor.id == ticket.user_id:
        return
    raise TicketKnowledgeAccessError("You do not have access to this ticket.")


def _latest_staff_resolution(ticket: Ticket) -> str:
    replies = sorted(ticket.replies or [], key=lambda item: item.created_at)
    for reply in reversed(replies):
        if reply.sender_role in {"office", "admin"} and (reply.message or "").strip():
            return reply.message.strip()
    return ""


def _redact_pii(text: str) -> str:
    """Strip common PII before ticket text becomes a public FAQ draft."""
    cleaned = text or ""
    cleaned = re.sub(
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
        "[email redacted]",
        cleaned,
    )
    cleaned = re.sub(r"\b(?:09|\+639)\d{9}\b", "[phone redacted]", cleaned)
    cleaned = re.sub(
        r"\b(?:student\s*id|id\s*no\.?|student\s*number)\s*[:#]?\s*[A-Za-z0-9\-_/]+\b",
        "[student id redacted]",
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned


def _default_article_content(ticket: Ticket, resolution: str) -> str:
    question = _redact_pii((ticket.original_question or "").strip())
    description = _redact_pii((ticket.description or "").strip())
    answer = _redact_pii((resolution or "").strip())
    parts = [f"## Question\n\n{question}"]
    if description and description.casefold() != question.casefold():
        parts.append(f"## Additional details\n\n{description}")
    parts.append(f"## Answer\n\n{answer}")
    return "\n\n".join(parts)


def _clean_title(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", (value or "").strip())
    cleaned = cleaned[:240].strip()
    if len(cleaned) < 3:
        raise TicketKnowledgeError("Article title is too short.")
    if cleaned.endswith("?"):
        cleaned = cleaned[:-1].strip() or cleaned
    return cleaned[0].upper() + cleaned[1:] if cleaned else cleaned


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return (slug or "ticket-faq")[:240]


def ensure_unique_article_slug(
    session: Session, title: str, *, exclude_id: str | None = None
) -> str:
    """Public helper for admin create/update paths."""
    return _unique_slug(session, title, exclude_id=exclude_id)


def _unique_slug(session: Session, title: str, *, exclude_id: str | None = None) -> str:
    """Return a slug unique among published_articles (suffix -2, -3, ... if needed)."""
    base = _slugify(title)
    candidate = base
    suffix = 2
    while True:
        query = session.query(PublishedArticle.id).filter(PublishedArticle.slug == candidate)
        if exclude_id:
            query = query.filter(PublishedArticle.id != exclude_id)
        if query.first() is None:
            return candidate
        trimmed = base[: max(1, 240 - len(f"-{suffix}"))]
        candidate = f"{trimmed}-{suffix}"
        suffix += 1
        if suffix > 1000:
            return f"{base[:200]}-{uuid.uuid4().hex[:8]}"


def _short_summary(text: str, *, limit: int = 220) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    cleaned = re.sub(r"^#+\s*", "", cleaned)
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rsplit(" ", 1)[0] + "…"


def _normalize_audience(value: str | None) -> str:
    normalized = (value or "student").strip().lower()
    if normalized not in {"student", "faculty", "both"}:
        raise TicketKnowledgeError("audience must be student, faculty, or both.")
    return normalized
