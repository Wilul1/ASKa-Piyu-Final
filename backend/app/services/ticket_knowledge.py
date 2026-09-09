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
    category: str | None = None,
    audience: str | None = None,
    publish: bool = False,
) -> dict[str, Any]:
    ticket = _load_ticket(session, ticket_id)
    _assert_can_convert(actor, ticket)

    if ticket.status not in {"Resolved", "Closed"}:
        raise TicketKnowledgeError("Only Resolved or Closed tickets can be converted to knowledge.")

    resolution = _latest_staff_resolution(ticket)
    resolved_body = (content or "").strip()
    if not resolved_body:
        if not resolution:
            raise TicketKnowledgeError(
                "Add an office or admin reply with the approved answer before converting."
            )
        resolved_body = _default_article_content(ticket, resolution)
    if len(resolved_body) < _MIN_RESOLUTION_CHARS:
        raise TicketKnowledgeError(
            f"Article content must be at least {_MIN_RESOLUTION_CHARS} characters "
            "to save as reusable knowledge."
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
    assert_no_duplicate_published_topic(
        session,
        title=resolved_title,
        exclude_article_id=existing.id if existing else None,
    )

    resolved_summary = (summary or _short_summary(resolved_body)).strip() or None
    resolved_audience = _normalize_audience(
        audience
        or infer_audience_from_text(
            ticket.original_question, ticket.description, resolution or resolved_body
        )
    )
    resolved_category = ((category or ticket.category or "General").strip() or "General")[:120]
    slug = _unique_slug(session, resolved_title, exclude_id=existing.id if existing else None)

    if existing is None:
        article = PublishedArticle(
            id=str(uuid.uuid4()),
            title=resolved_title,
            slug=slug,
            category=resolved_category,
            summary=resolved_summary,
            content=resolved_body,
            office=ticket.assigned_office,
            source_filename=f"Ticket FAQ ({ticket.id})",
            source_ticket_id=ticket.id,
            audience=resolved_audience,
            kb_origin="ticket_resolution",
            resolution_summary=(resolution or resolved_body).strip()[:4000],
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
        article.category = resolved_category
        article.summary = resolved_summary
        article.content = resolved_body
        article.office = ticket.assigned_office
        article.source_filename = f"Ticket FAQ ({ticket.id})"
        article.audience = resolved_audience
        article.kb_origin = "ticket_resolution"
        article.resolution_summary = (resolution or resolved_body).strip()[:4000]
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

    if not publish:
        return article_link_payload(article)

    return _publish_converted_ticket_article(session, article=article, actor=actor)


def assert_no_duplicate_published_topic(
    session: Session,
    *,
    title: str,
    exclude_article_id: str | None = None,
) -> None:
    """Hard-block ticket FAQs that duplicate an already-published KB article topic."""
    duplicate = find_duplicate_published_topic(
        session,
        title=title,
        exclude_article_id=exclude_article_id,
    )
    if duplicate is None:
        return
    raise TicketKnowledgeError(
        f'A published article already covers this topic: "{duplicate.title}". '
        "Point the student to the Knowledge Base instead of publishing a duplicate."
    )


def find_duplicate_published_topic(
    session: Session,
    *,
    title: str,
    exclude_article_id: str | None = None,
) -> PublishedArticle | None:
    """Return a published article whose title matches the ticket FAQ topic."""
    from app.services.admin.article_candidate_generator import (
        _normalize_match_title,
        find_matching_published_article,
    )

    want = _normalize_match_title(title)
    if len(want) < 3:
        return None

    # Prefer the shared matcher (exact / near title across the library).
    match = find_matching_published_article(session, title=title)
    if (
        match is not None
        and bool(match.published)
        and (not exclude_article_id or match.id != exclude_article_id)
        and _titles_are_duplicate_topics(want, _normalize_match_title(match.title))
    ):
        return match

    # Fallback: only published rows, exact or containment match.
    rows = (
        session.query(PublishedArticle)
        .filter(PublishedArticle.published.is_(True))
        .all()
    )
    for row in rows:
        if exclude_article_id and row.id == exclude_article_id:
            continue
        other = _normalize_match_title(row.title)
        if _titles_are_duplicate_topics(want, other):
            return row
    return None


def _titles_are_duplicate_topics(left: str, right: str) -> bool:
    if not left or not right:
        return False
    if left == right:
        return True
    # Containment only when both sides are long enough to avoid accidental hits.
    shorter, longer = (left, right) if len(left) <= len(right) else (right, left)
    if len(shorter) < 8:
        return False
    return shorter in longer


def _publish_converted_ticket_article(
    session: Session,
    *,
    article: PublishedArticle,
    actor: User,
) -> dict[str, Any]:
    """Publish a ticket FAQ and index it for chatbot retrieval (fail-closed)."""
    from datetime import datetime, timezone

    from app.services.article_rag_indexer import index_published_article

    assert_no_duplicate_published_topic(
        session,
        title=article.title,
        exclude_article_id=article.id,
    )

    article.published = True
    article.published_at = datetime.now(timezone.utc)
    article.published_by_user_id = actor.id
    article.rag_indexed = False
    sync_ticket_kb_status(session, article)
    session.add(article)
    if article.source_ticket_id:
        record_ticket_audit(
            session,
            ticket_id=article.source_ticket_id,
            actor=actor,
            action="kb_publish",
            field_name="kb_conversion_status",
            old_value="draft",
            new_value="published",
        )
    session.commit()
    session.refresh(article)

    try:
        index_published_article(session, article)
        session.commit()
        session.refresh(article)
    except Exception as exc:
        article.published = False
        article.published_at = None
        article.rag_indexed = False
        article.rag_document_id = None
        article.chunk_count = 0
        sync_ticket_kb_status(session, article)
        session.add(article)
        session.commit()
        raise TicketKnowledgeError(
            "FAQ was saved as a draft, but publishing to the chatbot index failed. "
            "Try Publish again from the ticket or Article Library."
        ) from exc

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


def check_ticket_kb_duplicate(
    session: Session,
    *,
    ticket_id: str,
    actor: User,
    title: str,
) -> dict[str, Any]:
    ticket = _load_ticket(session, ticket_id)
    _assert_can_convert(actor, ticket)
    cleaned_title = _clean_title(title)
    existing_article_id = None
    existing = (
        session.query(PublishedArticle)
        .filter(PublishedArticle.source_ticket_id == ticket.id)
        .one_or_none()
    )
    if existing is not None:
        existing_article_id = existing.id
    duplicate = find_duplicate_published_topic(
        session,
        title=cleaned_title,
        exclude_article_id=existing_article_id,
    )
    if duplicate is None:
        return {
            "has_duplicate": False,
            "title": None,
            "article_id": None,
            "slug": None,
            "message": None,
        }
    return {
        "has_duplicate": True,
        "title": duplicate.title,
        "article_id": duplicate.id,
        "slug": duplicate.slug,
        "message": (
            f'A published article already covers this topic: "{duplicate.title}". '
            "Point the student to the Knowledge Base instead of publishing a duplicate."
        ),
    }


def save_ticket_kb_image(
    session: Session,
    *,
    ticket_id: str,
    actor: User,
    filename: str,
    content: bytes,
) -> dict[str, Any]:
    ticket = _load_ticket(session, ticket_id)
    _assert_can_convert(actor, ticket)
    if ticket.status not in {"Resolved", "Closed"}:
        raise TicketKnowledgeError("Only Resolved or Closed tickets can receive knowledge-base images.")

    from app.services.kb_media import save_kb_image

    return save_kb_image(filename=filename, content=content)


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
        if bool(getattr(reply, "is_internal", False)):
            continue
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
    """Build student-facing FAQ body from a resolved ticket.

    The article title already carries the question, so the body is the answer
    (plus optional ticket details) — not ``## Question`` / ``## Answer`` labels.
    """
    question = _redact_pii((ticket.original_question or "").strip())
    description = _redact_pii((ticket.description or "").strip())
    answer = _redact_pii((resolution or "").strip())
    parts: list[str] = []
    if answer:
        parts.append(answer)
    if (
        description
        and description.casefold() != question.casefold()
        and description.casefold() != answer.casefold()
    ):
        parts.append(description)
    if not parts and question:
        parts.append(question)
    return "\n\n".join(parts)


_TICKET_FAQ_SCAFFOLD_HEADING = re.compile(
    r"^##\s*(Question|Answer|Additional details)\s*$",
    re.IGNORECASE,
)


def strip_ticket_faq_scaffolding(content: str, *, title: str | None = None) -> str:
    """Remove ticket→FAQ markdown headings from stored or displayed article body.

    Optionally drops a leading paragraph that only repeats the article title
    (leftover from the old ``## Question`` block).
    """
    text = (content or "").replace("\r\n", "\n").replace("\r", "\n")
    kept: list[str] = []
    for line in text.splitlines():
        if _TICKET_FAQ_SCAFFOLD_HEADING.match(line.strip()):
            continue
        kept.append(line)
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()
    if not text:
        return ""

    title_norm = re.sub(r"\s+", " ", (title or "").strip()).casefold().rstrip("?")
    if title_norm:
        paragraphs = re.split(r"\n\s*\n", text, maxsplit=1)
        lead = re.sub(r"\s+", " ", paragraphs[0]).strip().casefold().rstrip("?")
        if lead == title_norm and len(paragraphs) > 1:
            text = paragraphs[1].strip()
    return text


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
