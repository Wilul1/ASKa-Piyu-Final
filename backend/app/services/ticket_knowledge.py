"""Convert resolved tickets into draft knowledge-base FAQs."""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.models.db_models import PublishedArticle, Ticket, User, utc_now
from app.services.ticket_audit import record_ticket_audit

logger = logging.getLogger(__name__)


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
_MIN_AUTO_ANSWER_CHARS = 40
_GENERATION_NOTES_MAX = 80

_FILLER_RE = re.compile(
    r"^(?:"
    r"hi|hello|hey|good\s+(?:day|morning|afternoon|evening)|"
    r"thanks?(?:\s+you)?|thank\s+you|ok(?:ay)?|noted|"
    r"please\s+wait|any\s+updates?|"
    r"will\s+(?:follow\s+up|check)|for\s+follow[\s-]?up"
    r")[\s.!?]*$",
    re.IGNORECASE,
)
_LEADING_GREETING_RE = re.compile(
    r"^(?:hi|hello|hey|good\s+(?:day|morning|afternoon|evening))[,!.\s]+",
    re.IGNORECASE,
)
_IDENTITY_STOPWORDS = frozenset(
    {
        "student",
        "faculty",
        "office",
        "admin",
        "user",
        "the",
        "and",
        "for",
        "with",
        "from",
        "your",
        "you",
        "lspu",
        "registrar",
    }
)
_DEFERRED_ANSWER_RE = re.compile(
    r"\b(?:i(?:'ll| will)\s+check|we\s+will\s+get\s+back|no\s+idea|"
    r"not\s+sure|please\s+wait|follow\s+up\s+later)\b",
    re.IGNORECASE,
)
_COMPLETION_MARKER = (
    "[Needs staff completion: the ticket conversation does not contain "
    "a complete reusable answer.]"
)
_PUBLIC_FAQ_SOURCE_FILENAME = "Knowledge Base article"
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+63[\s.-]*|0)9\d{2}[\s.-]*\d{3}[\s.-]*\d{4}(?!\d)"
    r"|\(\s*0?\d{2,4}\s*\)\s*\d{3}[\s-]?\d{4}"
)
_STUDENT_ID_LABEL_RE = re.compile(
    r"\b(?:student\s*id|id\s*no\.?|student\s*number|stud(?:ent)?\s*no\.?)"
    r"\s*[:#]?\s*[A-Za-z0-9\-_/]+\b",
    re.IGNORECASE,
)
_STUDENT_NUMBER_RE = re.compile(
    r"\b(?:20|19)\d{2}[\s-]\d{4,}\b"
    r"|\b(?:20|19)\d{8,}\b"
)
_ADDRESS_RE = re.compile(
    r"\b(?:blk\.?|block|lot|purok|sitio|phase|brgy\.?|barangay)\s+"
    r"[A-Za-z0-9][A-Za-z0-9\s.,-]{0,40}"
    r"|\b\d{1,5}\s+[A-Za-z][A-Za-z\s.]{2,40}?"
    r"(?:street|st\.|road|rd\.|avenue|ave\.|blvd\.?|subdivision|subd\.?|"
    r"barangay|brgy\.?)\b",
    re.IGNORECASE,
)
_ALIAS_RE = re.compile(
    r"\b(?:call me|aka|a\.k\.a\.|i am|i'm|ako si)\s+([A-Za-z][A-Za-z.'-]{1,20})\b",
    re.IGNORECASE,
)
_TICKET_ID_RE = re.compile(r"\bTKT[-_]?[A-Z0-9-]+\b", re.IGNORECASE)
_NAME_NICKNAMES = {
    "maria": ("mai", "marie", "mary", "ria"),
    "juan": ("jun", "johnny", "john"),
    "jose": ("pepe", "joey"),
    "ana": ("anne", "ann"),
    "antonio": ("tony", "tonio"),
    "francisco": ("cisco", "frank"),
}


@dataclass(frozen=True)
class GeneratedTicketArticle:
    title: str
    content: str
    summary: str
    needs_manual_completion: bool
    generation_notes: str | None


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
    keep_generation_flags: bool = False,
) -> dict[str, Any]:
    ticket = _load_ticket(session, ticket_id)
    _assert_can_convert(actor, ticket)

    if ticket.status not in {"Resolved", "Closed"}:
        raise TicketKnowledgeError("Only Resolved or Closed tickets can be converted to knowledge.")

    resolution = _latest_staff_resolution(ticket)
    generated = build_generated_article_from_ticket(ticket)
    resolved_body = (content or "").strip()
    if not resolved_body:
        if not resolution and not keep_generation_flags:
            raise TicketKnowledgeError(
                "Add an office or admin reply with the approved answer before converting."
            )
        if not resolution and not generated.content:
            raise TicketKnowledgeError(
                "Add an office or admin reply with the approved answer before converting."
            )
        resolved_body = generated.content or _default_article_content(ticket, resolution)
    if keep_generation_flags:
        if generated.needs_manual_completion or len(resolved_body) < _MIN_AUTO_ANSWER_CHARS:
            resolved_body = _ensure_completion_placeholder(resolved_body)
    elif len(resolved_body) < _MIN_RESOLUTION_CHARS:
        raise TicketKnowledgeError(
            f"Article content must be at least {_MIN_RESOLUTION_CHARS} characters "
            "to save as reusable knowledge."
        )
    if publish and keep_generation_flags and generated.needs_manual_completion:
        raise TicketKnowledgeError(
            "The generated answer is incomplete. Edit and approve it before publishing."
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

    resolved_title = _clean_title(title or generated.title or ticket.original_question)
    assert_no_duplicate_published_topic(
        session,
        title=resolved_title,
        exclude_article_id=existing.id if existing else None,
    )

    identities = _identities_from_ticket(ticket)
    resolved_title = redact_ticket_pii(resolved_title, identities=identities)
    resolved_body = redact_ticket_pii(resolved_body, identities=identities)
    resolved_summary = redact_ticket_pii(
        (summary or generated.summary or _short_summary(resolved_body)).strip() or "",
        identities=identities,
    ) or None
    resolution = redact_ticket_pii(resolution, identities=identities)
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
            source_filename=_PUBLIC_FAQ_SOURCE_FILENAME,
            source_ticket_id=ticket.id,
            audience=resolved_audience,
            kb_origin="ticket_resolution",
            resolution_summary=(resolution or resolved_body).strip()[:4000],
            created_by_user_id=actor.id,
            published=False,
            published_at=None,
            needs_manual_completion=_needs_manual_flag(generated, content, keep_generation_flags),
            review_status="pending",
            generation_notes=_generation_notes_flag(generated, content, keep_generation_flags),
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
        article.source_filename = _PUBLIC_FAQ_SOURCE_FILENAME
        article.audience = resolved_audience
        article.kb_origin = "ticket_resolution"
        article.resolution_summary = (resolution or resolved_body).strip()[:4000]
        article.published = False
        article.published_at = None
        article.needs_manual_completion = _needs_manual_flag(
            generated, content, keep_generation_flags
        )
        article.review_status = "pending"
        article.generation_notes = _generation_notes_flag(
            generated, content, keep_generation_flags
        )
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

    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        raced = (
            session.query(PublishedArticle)
            .filter(PublishedArticle.source_ticket_id == ticket.id)
            .one_or_none()
        )
        if raced is None:
            raise TicketKnowledgeError("Could not save the knowledge article draft.") from None
        return article_link_payload(raced)

    ticket.kb_article_id = article.id
    ticket.kb_conversion_status = _ticket_status_for_article(article)
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


def try_auto_generate_ticket_article(
    session: Session,
    *,
    ticket_id: str,
    actor: User,
) -> dict[str, Any] | None:
    """Best-effort draft generation after resolve. Never raises to the caller."""
    try:
        return generate_article_from_resolved_ticket(
            session, ticket_id=ticket_id, actor=actor
        )
    except TicketKnowledgeError:
        logger.error("ticket article auto-generation skipped ticket_id=%s", ticket_id)
        return None
    except Exception:
        logger.error("ticket article auto-generation failed ticket_id=%s", ticket_id)
        try:
            _mark_generation_failed(session, ticket_id=ticket_id, actor=actor)
        except Exception:
            logger.error("ticket article failure status could not be recorded ticket_id=%s", ticket_id)
        return None


def generate_article_from_resolved_ticket(
    session: Session,
    *,
    ticket_id: str,
    actor: User,
    replace_draft: bool = False,
) -> dict[str, Any]:
    """Create or reuse an unpublished FAQ draft from the ticket conversation."""
    ticket = _load_ticket(session, ticket_id)
    _assert_can_convert(actor, ticket)
    if ticket.status not in {"Resolved", "Closed"}:
        raise TicketKnowledgeError("Only Resolved or Closed tickets can generate knowledge articles.")

    existing = (
        session.query(PublishedArticle)
        .filter(PublishedArticle.source_ticket_id == ticket.id)
        .one_or_none()
    )
    if existing is not None:
        if bool(existing.published):
            return article_link_payload(existing)
        if not replace_draft and (existing.review_status or "pending") != "rejected":
            if ticket.kb_conversion_status not in {"failed", "none"}:
                return article_link_payload(existing)

    generated = build_generated_article_from_ticket(ticket)
    body = generated.content
    if generated.needs_manual_completion or len(body.strip()) < _MIN_AUTO_ANSWER_CHARS:
        body = _ensure_completion_placeholder(body)
    return convert_ticket_to_draft_article(
        session,
        ticket_id=ticket.id,
        actor=actor,
        title=generated.title,
        content=body,
        summary=generated.summary,
        publish=False,
        keep_generation_flags=True,
    )


def approve_ticket_kb_article(
    session: Session,
    *,
    ticket_id: str,
    actor: User,
) -> dict[str, Any]:
    ticket = _load_ticket(session, ticket_id)
    _assert_can_convert(actor, ticket)
    article = _require_ticket_article(session, ticket)
    if bool(article.published):
        return article_link_payload(article)
    identities = _identities_from_ticket(ticket)
    body = redact_ticket_pii(article.content or "", identities=identities)
    if (
        bool(article.needs_manual_completion)
        or _COMPLETION_MARKER in body
        or len(body.strip()) < _MIN_RESOLUTION_CHARS
    ):
        raise TicketKnowledgeError(
            "Edit the draft so the answer is complete before approving it for the Knowledge Base."
        )
    article.content = body
    article.title = redact_ticket_pii(article.title, identities=identities)
    article.summary = redact_ticket_pii(article.summary or "", identities=identities) or None
    article.resolution_summary = (
        redact_ticket_pii(article.resolution_summary or "", identities=identities) or None
    )
    article.needs_manual_completion = False
    article.review_status = "approved"
    article.generation_notes = None
    session.add(article)
    return _publish_converted_ticket_article(session, article=article, actor=actor)


def reject_ticket_kb_article(
    session: Session,
    *,
    ticket_id: str,
    actor: User,
    reason: str | None = None,
) -> dict[str, Any]:
    ticket = _load_ticket(session, ticket_id)
    _assert_can_convert(actor, ticket)
    article = _require_ticket_article(session, ticket)
    if bool(article.published):
        from app.services.article_rag_indexer import remove_published_article_index

        article.published = False
        article.published_at = None
        try:
            remove_published_article_index(session, article)
        except Exception:
            article.rag_indexed = False
            article.rag_document_id = None
            article.chunk_count = 0
    article.review_status = "rejected"
    article.needs_manual_completion = False
    article.generation_notes = "rejected"
    session.add(article)
    ticket.kb_article_id = article.id
    ticket.kb_conversion_status = "rejected"
    ticket.updated_at = utc_now()
    session.add(ticket)
    record_ticket_audit(
        session,
        ticket_id=ticket.id,
        actor=actor,
        action="kb_reject",
        field_name="kb_conversion_status",
        old_value="draft",
        new_value="rejected",
    )
    _ = redact_ticket_pii(reason or "", identities=_identities_from_ticket(ticket))
    session.commit()
    session.refresh(article)
    return article_link_payload(article)


def retry_ticket_kb_generation(
    session: Session,
    *,
    ticket_id: str,
    actor: User,
) -> dict[str, Any]:
    ticket = _load_ticket(session, ticket_id)
    _assert_can_convert(actor, ticket)
    existing = (
        session.query(PublishedArticle)
        .filter(PublishedArticle.source_ticket_id == ticket.id)
        .one_or_none()
    )
    if existing is not None and bool(existing.published):
        if not bool(existing.rag_indexed):
            return _reindex_ticket_article(session, article=existing)
        raise TicketKnowledgeError("This ticket already has a published knowledge article.")
    return generate_article_from_resolved_ticket(
        session, ticket_id=ticket.id, actor=actor, replace_draft=True
    )


def build_generated_article_from_ticket(ticket: Ticket) -> GeneratedTicketArticle:
    """Consolidate the public conversation into one question and one answer."""
    identities = _identities_from_ticket(ticket)
    question = redact_ticket_pii((ticket.original_question or "").strip(), identities=identities)
    student_followups: list[str] = []
    staff_answers: list[str] = []
    for reply in sorted(ticket.replies or [], key=lambda item: item.created_at):
        if bool(getattr(reply, "is_internal", False)):
            continue
        raw = redact_ticket_pii((reply.message or "").strip(), identities=identities)
        cleaned = _strip_filler(raw)
        if not cleaned:
            continue
        if reply.sender_role in {"student", "faculty"}:
            if cleaned.casefold() != question.casefold() and cleaned not in student_followups:
                student_followups.append(cleaned)
            continue
        if reply.sender_role in {"office", "admin"}:
            if cleaned not in staff_answers:
                staff_answers.append(cleaned)

    if student_followups:
        extra = student_followups[0]
        if extra.casefold() not in question.casefold() and len(extra.split()) >= 4:
            question = f"{question.rstrip('?')} ({extra})".strip()

    answer = _format_answer_steps(staff_answers)
    notes = None
    needs_completion = False
    if not answer:
        needs_completion = True
        notes = "no_staff_answer"
        answer = ""
    elif len(answer) < _MIN_AUTO_ANSWER_CHARS:
        needs_completion = True
        notes = "answer_too_short"
    elif _DEFERRED_ANSWER_RE.search(answer) and len(answer) < _MIN_RESOLUTION_CHARS:
        needs_completion = True
        notes = "deferred_answer"

    if needs_completion and not answer:
        content = _COMPLETION_MARKER
    else:
        content = answer
    title_source = question or (ticket.original_question or "Support question")
    try:
        title = _clean_title(title_source)
    except TicketKnowledgeError:
        title = "Support question"
    summary = _short_summary(content or question)
    return GeneratedTicketArticle(
        title=redact_ticket_pii(title, identities=identities),
        content=content,
        summary=redact_ticket_pii(summary, identities=identities),
        needs_manual_completion=needs_completion,
        generation_notes=notes,
    )


def redact_ticket_pii(text: str, *, identities: tuple[str, ...] = ()) -> str:
    """Strip emails, phones, IDs, addresses, and known requester identity strings."""
    return _redact_pii(text, identities=identities)


def identities_for_ticket_article(session: Session, article: PublishedArticle) -> tuple[str, ...]:
    """Load requester identity strings for a ticket-derived article."""
    if not article.source_ticket_id:
        return ()
    ticket = (
        session.query(Ticket)
        .options(joinedload(Ticket.replies), joinedload(Ticket.user))
        .filter(Ticket.id == article.source_ticket_id)
        .one_or_none()
    )
    if ticket is None:
        return ()
    return _identities_from_ticket(ticket)


def _reindex_ticket_article(session: Session, *, article: PublishedArticle) -> dict[str, Any]:
    from app.services.article_rag_indexer import index_published_article

    _redact_article_fields(session, article)
    try:
        index_published_article(session, article)
        article.generation_notes = None
        session.add(article)
        session.commit()
        session.refresh(article)
    except Exception:
        logger.error("ticket FAQ reindex failed article_id=%s", article.id)
        article.rag_indexed = False
        article.generation_notes = "index_failed"
        session.add(article)
        session.commit()
        session.refresh(article)
    return article_link_payload(article)


def _mark_generation_failed(session: Session, *, ticket_id: str, actor: User) -> None:
    ticket = session.get(Ticket, ticket_id)
    if ticket is None:
        return
    existing = (
        session.query(PublishedArticle)
        .filter(PublishedArticle.source_ticket_id == ticket.id)
        .one_or_none()
    )
    if existing is not None and bool(existing.published):
        return
    ticket.kb_conversion_status = "failed"
    ticket.updated_at = utc_now()
    session.add(ticket)
    record_ticket_audit(
        session,
        ticket_id=ticket.id,
        actor=actor,
        action="kb_generate_failed",
        field_name="kb_conversion_status",
        old_value="none",
        new_value="failed",
    )
    session.commit()


def _require_ticket_article(session: Session, ticket: Ticket) -> PublishedArticle:
    article = (
        session.query(PublishedArticle)
        .filter(PublishedArticle.source_ticket_id == ticket.id)
        .one_or_none()
    )
    if article is None and ticket.kb_article_id:
        article = session.get(PublishedArticle, ticket.kb_article_id)
    if article is None:
        raise TicketKnowledgeNotFoundError("This ticket has no knowledge article draft.")
    return article


def _ticket_status_for_article(article: PublishedArticle) -> str:
    if bool(article.published):
        return "published"
    if getattr(article, "review_status", None) == "rejected":
        return "rejected"
    if getattr(article, "needs_manual_completion", False):
        return "needs_review"
    return "draft"


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
    """Approve a ticket FAQ, then index it. Index failure does not unpublish."""
    from datetime import datetime, timezone

    from app.services.article_rag_indexer import index_published_article

    assert_no_duplicate_published_topic(
        session,
        title=article.title,
        exclude_article_id=article.id,
    )

    _redact_article_fields(session, article)
    article.published = True
    article.published_at = datetime.now(timezone.utc)
    article.published_by_user_id = actor.id
    article.review_status = "approved"
    article.needs_manual_completion = False
    article.generation_notes = None
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
        article.generation_notes = None
        session.add(article)
        session.commit()
        session.refresh(article)
    except Exception:
        logger.error("ticket FAQ index failed article_id=%s", article.id)
        article.published = True
        article.review_status = "approved"
        article.rag_indexed = False
        article.rag_document_id = None
        article.chunk_count = 0
        article.generation_notes = "index_failed"
        sync_ticket_kb_status(session, article)
        session.add(article)
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
        "kb_conversion_status": _ticket_status_for_article(article),
        "created_at": article.created_at.isoformat() if article.created_at else None,
        "updated_at": article.updated_at.isoformat() if article.updated_at else None,
        "published_at": article.published_at.isoformat() if article.published_at else None,
        "needs_manual_completion": bool(getattr(article, "needs_manual_completion", False)),
        "review_status": getattr(article, "review_status", None),
        "generation_notes": getattr(article, "generation_notes", None),
    }


def sync_ticket_kb_status(session: Session, article: PublishedArticle) -> None:
    """Keep denormalized ticket conversion status aligned after publish/unpublish."""
    if not article.source_ticket_id:
        return
    ticket = session.get(Ticket, article.source_ticket_id)
    if ticket is None:
        return
    ticket.kb_article_id = article.id
    ticket.kb_conversion_status = _ticket_status_for_article(article)
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


def _redact_pii(text: str, *, identities: tuple[str, ...] = ()) -> str:
    """Strip common PII before ticket text becomes a public FAQ draft."""
    cleaned = text or ""
    cleaned = _EMAIL_RE.sub("[email redacted]", cleaned)
    cleaned = _PHONE_RE.sub("[phone redacted]", cleaned)
    cleaned = _STUDENT_ID_LABEL_RE.sub("[student id redacted]", cleaned)
    cleaned = _STUDENT_NUMBER_RE.sub("[student id redacted]", cleaned)
    cleaned = _ADDRESS_RE.sub("[address redacted]", cleaned)
    cleaned = _TICKET_ID_RE.sub("[ticket id redacted]", cleaned)
    for identity in identities:
        token = (identity or "").strip()
        if len(token) < 2:
            continue
        if "@" in token:
            replacement = "[email redacted]"
        elif " " not in token and re.search(r"\d", token):
            replacement = "[student id redacted]"
        else:
            replacement = "[name redacted]"
        cleaned = re.sub(
            rf"(?<![A-Za-z0-9]){re.escape(token)}(?![A-Za-z0-9])",
            replacement,
            cleaned,
            flags=re.IGNORECASE,
        )
    return cleaned


def _identities_from_ticket(ticket: Ticket) -> tuple[str, ...]:
    values: list[str] = []
    user = getattr(ticket, "user", None)
    if user is not None:
        values.extend(
            [
                getattr(user, "full_name", None) or "",
                getattr(user, "email", None) or "",
                getattr(user, "student_id", None) or "",
            ]
        )
    public_blobs: list[str] = [
        getattr(ticket, "original_question", None) or "",
        getattr(ticket, "description", None) or "",
    ]
    for reply in getattr(ticket, "replies", None) or []:
        if bool(getattr(reply, "is_internal", False)):
            continue
        if reply.sender_role in {"student", "faculty"}:
            values.append(reply.sender_name or "")
            public_blobs.append(reply.message or "")
    for blob in public_blobs:
        for match in _ALIAS_RE.finditer(blob or ""):
            values.append(match.group(1))
    seen: set[str] = set()
    cleaned: list[str] = []
    for raw in values:
        text = (raw or "").strip()
        if len(text) < 2:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
        for part in re.split(r"[\s,]+", text):
            part = part.strip(".,;:<>@")
            part_key = part.casefold()
            if len(part) < 3 or part_key in _IDENTITY_STOPWORDS or part_key in seen:
                continue
            seen.add(part_key)
            cleaned.append(part)
            for nickname in _NAME_NICKNAMES.get(part_key, ()):
                if nickname in seen:
                    continue
                seen.add(nickname)
                cleaned.append(nickname)
    cleaned.sort(key=len, reverse=True)
    return tuple(cleaned)


def _strip_filler(text: str) -> str:
    cleaned = (text or "").replace("\r\n", "\n").strip()
    if not cleaned:
        return ""
    kept: list[str] = []
    for line in cleaned.splitlines():
        stripped = line.strip()
        if not stripped or _FILLER_RE.match(stripped):
            continue
        stripped = _LEADING_GREETING_RE.sub("", stripped).strip()
        if stripped:
            kept.append(stripped)
    joined = " ".join(kept).strip()
    if not joined or _FILLER_RE.match(joined):
        return ""
    return joined


def _format_answer_steps(answers: list[str]) -> str:
    usable = [item.strip() for item in answers if item and item.strip()]
    if not usable:
        return ""
    if len(usable) == 1:
        return usable[0]
    return "\n".join(f"{index}. {item}" for index, item in enumerate(usable, start=1))


def _needs_manual_flag(
    generated: GeneratedTicketArticle,
    content: str | None,
    keep_generation_flags: bool,
) -> bool:
    if keep_generation_flags:
        return bool(generated.needs_manual_completion)
    return bool(generated.needs_manual_completion) and not (content or "").strip()


def _generation_notes_flag(
    generated: GeneratedTicketArticle,
    content: str | None,
    keep_generation_flags: bool,
) -> str | None:
    notes = generated.generation_notes
    if notes:
        notes = notes[:_GENERATION_NOTES_MAX]
    if keep_generation_flags:
        return notes
    return notes if not (content or "").strip() else None


def _ensure_completion_placeholder(content: str) -> str:
    text = (content or "").strip()
    if _COMPLETION_MARKER in text:
        return text
    if len(text) >= _MIN_RESOLUTION_CHARS:
        return text
    return f"{text}\n\n{_COMPLETION_MARKER}".strip() if text else _COMPLETION_MARKER


def _redact_article_fields(session: Session, article: PublishedArticle) -> None:
    identities = identities_for_ticket_article(session, article)
    article.title = redact_ticket_pii(article.title, identities=identities)
    article.content = redact_ticket_pii(article.content or "", identities=identities)
    article.summary = redact_ticket_pii(article.summary or "", identities=identities) or None
    article.resolution_summary = (
        redact_ticket_pii(article.resolution_summary or "", identities=identities) or None
    )
    article.generation_notes = (article.generation_notes or None)
    if article.generation_notes:
        article.generation_notes = article.generation_notes[:_GENERATION_NOTES_MAX]
    article.source_filename = _PUBLIC_FAQ_SOURCE_FILENAME


def _default_article_content(ticket: Ticket, resolution: str) -> str:
    """Build student-facing FAQ body from a resolved ticket.

    The article title already carries the question, so the body is the answer
    (plus optional ticket details) — not ``## Question`` / ``## Answer`` labels.
    """
    identities = _identities_from_ticket(ticket)
    question = _redact_pii((ticket.original_question or "").strip(), identities=identities)
    description = _redact_pii((ticket.description or "").strip(), identities=identities)
    answer = _redact_pii((resolution or "").strip(), identities=identities)
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
