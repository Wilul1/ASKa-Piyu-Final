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
    r"you(?:'re| are)\s+welcome|"
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
    r"\b(?:"
    r"i(?:'ll| will)\s+check|"
    r"we\s+will\s+get\s+back|"
    r"we\s+will\s+(?:update|notify|contact)\s+you|"
    r"no\s+idea|not\s+sure|"
    r"please\s+wait(?:\s+while)?|"
    r"follow\s+up\s+later|"
    # Status-only ticket updates (not reusable FAQ answers).
    r"(?:your\s+)?(?:request|application)\s+is\s+"
    r"(?:being\s+processed|currently\s+under\s+review|under\s+review)|"
    r"is\s+being\s+processed|"
    r"currently\s+under\s+review|"
    r"under\s+review|"
    r"once\s+(?:it\s+is\s+ready|it\s+is\s+available|processing\s+is\s+complete)"
    r")\b",
    re.IGNORECASE,
)
# Staff redirects the student to verify/confirm elsewhere without stating facts.
_REFERRAL_ANSWER_RE = re.compile(
    r"\b(?:"
    r"please\s+(?:check|confirm|verify|inquire|ask|coordinate)|"
    r"(?:check|confirm|verify|inquire)\s+(?:with|at|the\s+current|current)|"
    r"contact\s+(?:the\s+)?(?:registrar|osas|office|cashier|dean)|"
    r"for\s+the\s+(?:specific|latest|current|exact)\s+"
    r"(?:form|forms|requirements?|fee|fees|process|procedure)|"
    r"requirements?\s+(?:may\s+)?(?:vary|change)|"
    r"subject\s+to\s+(?:change|the\s+office)"
    r")\b",
    re.IGNORECASE,
)
# Actionable reusable facts (not merely mentioning that a form/requirement exists).
_CONCRETE_FACT_RE = re.compile(
    r"\b(?:"
    r"submit|file(?:\s+the)?|bring|pay(?:\s+the|\s+at)?|fill\s+out|go\s+to|return\s+with|"
    r"present(?:\s+the)?|proceed\s+to|claim(?:\s+stub)?|"
    r"within\s+\d+\s+(?:working\s+)?days?|"
    r"(?:next|\d+)\s+working\s+days?|working\s+days?|"
    r"official\s+receipt|assessment\s+form|"
    r"medical\s+certificate|excuse\s+slip\s+form"
    r")\b",
    re.IGNORECASE,
)
# Requirement lists that are reusable even without an imperative verb.
_REQUIREMENT_EVIDENCE_RE = re.compile(
    r"\b(?:"
    r"required\s+documents?|documents?\s+required|"
    r"requirements?\s+(?:are|include)|"
    r"valid\s+(?:government\s+)?id|"
    r"enrollment\s+form|application\s+form|payment\s+receipt"
    r")\b",
    re.IGNORECASE,
)
# Courtesy / boilerplate that must never count as a reusable FAQ answer.
_COURTESY_ONLY_RE = re.compile(
    r"^(?:"
    r"thank\s+you(?:\s+for\s+contacting(?:\s+the)?[^.!?]{0,80})?|"
    r"you(?:'re| are)\s+welcome|"
    r"good\s+day(?:\s+and\s+welcome)?|"
    r"if\s+you\s+have\s+any\s+questions(?:\s+or\s+need\s+further\s+assistance)?[^.!?]{0,80}|"
    r"feel\s+free\s+to\s+(?:reply|reach\s+out|contact\s+us)[^.!?]{0,80}|"
    r"for\s+further\s+assistance[^.!?]{0,60}"
    r")[\s.!?]*$",
    re.IGNORECASE,
)
# Staff asking the student to clarify missing information — not reusable FAQ.
# Deliberately omits bare "provide" so instructional "could you please provide
# the … form at Window N" remains eligible as actionable guidance.
_STAFF_CLARIFYING_QUESTION_RE = re.compile(
    r"\b(?:"
    r"please\s+(?:also\s+)?confirm\s+whether|"
    r"kindly\s+(?:confirm|advise)\s+whether|"
    r"could\s+you\s+(?:please\s+)?(?:confirm|clarify)|"
    r"may\s+(?:i|we)\s+know(?:\s+(?:whether|your))?|"
    r"let\s+us\s+know\s+(?:if|whether|what)"
    r")\b",
    re.IGNORECASE,
)
# Personal identity fields. Bare "program" alone is not enough (avoids
# "enroll in the nursing program"); require year-level pairing or "your program".
_IDENTITY_FIELD_RE = re.compile(
    r"\b(?:"
    r"complete\s+name|full\s+name|"
    r"student\s+number|student\s+id|"
    r"year\s+level|"
    r"(?:your\s+)?program\s+and\s+(?:current\s+)?year\s+level|"
    r"your\s+program\b"
    r")\b",
    re.IGNORECASE,
)
# Language that requests the student's personal details (intake), not instructions
# to present/bring an ID as part of a procedure.
_IDENTITY_REQUEST_RE = re.compile(
    r"\b(?:"
    r"(?:kindly|please)\s+provide(?:\s+your)?|"
    r"provide\s+your|"
    r"may\s+(?:i|we)\s+know(?:\s+your)?|"
    r"so\s+we\s+can\s+(?:check|verify|locate|review)\s+your|"
    r"need\s+(?:your|the\s+following)\s+"
    r"(?:complete\s+name|full\s+name|student\s+number|student\s+id|details)"
    r")\b",
    re.IGNORECASE,
)
# Soft clause often attached to intake prompts; not a reusable procedure step.
_SOFT_WHEN_SUBMITTING_RE = re.compile(
    r"\bwhen\s+submitting\s+your\s+request\b",
    re.IGNORECASE,
)
# Backward-compatible alias used by older call sites / tests.
_IDENTITY_INTAKE_ONLY_RE = _IDENTITY_FIELD_RE
# Hedge that keeps "submit/bring" from turning a confirm/check referral into a fact.
_REFERRAL_HEDGE_RE = re.compile(
    r"\b(?:"
    r"recommend\s+confirming|please\s+(?:check|confirm|verify|coordinate|inquire)|"
    r"confirm(?:ing)?\s+(?:the\s+)?(?:current|latest|specific)|"
    r"check\s+(?:the\s+)?(?:university(?:'s)?|current|latest)|"
    r"coordinate\s+with|"
    r"to\s+avoid\s+using\s+an\s+outdated"
    r")\b",
    re.IGNORECASE,
)
_REFERRAL_BOILERPLATE_TOKENS = frozenset(
    {
        "please",
        "confirm",
        "check",
        "verify",
        "inquire",
        "ask",
        "coordinate",
        "contact",
        "current",
        "latest",
        "specific",
        "exact",
        "office",
        "with",
        "the",
        "for",
        "and",
        "your",
        "you",
        "from",
        "this",
        "that",
        "about",
        "their",
        "them",
        "also",
        "still",
        "need",
        "needed",
        "requirements",
        "requirement",
        "process",
        "procedure",
        "details",
        "detail",
        "information",
    }
)
_COURTESY_PREFIX_RE = re.compile(
    r"^(?:"
    r"thank\s+you(?:\s+for\s+contacting(?:\s+the)?[^.!?]{0,60})?|"
    r"you(?:'re| are)\s+welcome|"
    r"good\s+day(?:\s+and\s+welcome)?"
    r")[,!.\s]+",
    re.IGNORECASE,
)
_CONVERSATIONAL_PAREN_RE = re.compile(
    r"\s*\((?:[^)]*(?:thank\s+you|i\s+need|is\s+there|can\s+you|"
    r"please|scholarship|follow[\s-]?up)[^)]*)\)\s*$",
    re.IGNORECASE,
)
_FOLLOWUP_TOPIC_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("form", re.compile(r"\bforms?\b", re.IGNORECASE)),
    ("fee", re.compile(r"\b(?:fee|fees|payment|cost|how much|php|₱)\b", re.IGNORECASE)),
    (
        "timeline",
        re.compile(r"\b(?:how long|processing|deadline|working days?|release)\b", re.IGNORECASE),
    ),
    (
        "location",
        re.compile(r"\b(?:where|which office|location|window|counter)\b", re.IGNORECASE),
    ),
)
_COMPLETION_MARKER = (
    "[Needs staff completion: the ticket conversation does not contain "
    "a complete reusable answer.]"
)
_INCOMPLETE_NOTES_HEADING = "## Needs staff completion"
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
    elif generated.needs_manual_completion and not _staff_supplied_content_completes_draft(
        resolved_body
    ):
        # Staff pasted/edited body still lacks a reusable answer — keep the marker.
        resolved_body = _ensure_completion_placeholder(resolved_body)
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

    blocked = ticket_article_publication_blocked(
        content=article.content,
        needs_manual_completion=bool(
            getattr(article, "needs_manual_completion", False)
        ),
        source_ticket_id=article.source_ticket_id,
        kb_origin=article.kb_origin,
    )
    if blocked:
        # Draft is already saved; do not publish or clear completion signals.
        raise TicketKnowledgeError(blocked)

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
    except TicketKnowledgeError as exc:
        reason = _auto_generation_failure_reason(exc)
        logger.error(
            "ticket article auto-generation skipped ticket_id=%s reason=%s",
            ticket_id,
            reason,
        )
        try:
            _mark_generation_failed(
                session, ticket_id=ticket_id, actor=actor, reason=reason
            )
        except Exception:
            logger.error(
                "ticket article failure status could not be recorded ticket_id=%s",
                ticket_id,
            )
        return None
    except Exception:
        logger.error("ticket article auto-generation failed ticket_id=%s", ticket_id)
        try:
            _mark_generation_failed(
                session,
                ticket_id=ticket_id,
                actor=actor,
                reason="unexpected_error",
            )
        except Exception:
            logger.error(
                "ticket article failure status could not be recorded ticket_id=%s",
                ticket_id,
            )
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
    blocked = ticket_article_publication_blocked(
        content=body,
        needs_manual_completion=bool(
            getattr(article, "needs_manual_completion", False)
        ),
        source_ticket_id=article.source_ticket_id,
        kb_origin=article.kb_origin,
    )
    if blocked or len(body.strip()) < _MIN_RESOLUTION_CHARS:
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
    """Synthesize a reusable FAQ draft from the public ticket conversation.

    Titles come only from the original question (never student follow-ups).
    Staff replies are classified into substantive answers vs referrals /
    deferred replies. Incomplete conversations stay unpublished via
    ``needs_manual_completion`` and never invent missing official details.
    Internal notes are ignored.
    """
    identities = _identities_from_ticket(ticket)
    original_question = redact_ticket_pii(
        (ticket.original_question or "").strip(), identities=identities
    )
    student_followups: list[str] = []
    staff_substantive: list[str] = []
    staff_referrals: list[str] = []
    staff_deferred: list[str] = []

    for reply in sorted(ticket.replies or [], key=lambda item: item.created_at):
        if bool(getattr(reply, "is_internal", False)):
            continue
        raw = redact_ticket_pii((reply.message or "").strip(), identities=identities)
        cleaned = _strip_filler(raw)
        if not cleaned:
            continue
        if reply.sender_role in {"student", "faculty"}:
            if (
                cleaned.casefold() != original_question.casefold()
                and cleaned not in student_followups
            ):
                student_followups.append(cleaned)
            continue
        if reply.sender_role not in {"office", "admin"}:
            continue
        # Partition at clause level so status language cannot erase requirements,
        # including when status is joined with "and" or lacks terminal punctuation.
        for sentence in _split_staff_evidence_units(cleaned):
            _bucket_staff_evidence_unit(
                sentence,
                staff_substantive=staff_substantive,
                staff_referrals=staff_referrals,
                staff_deferred=staff_deferred,
            )

    office_name = (getattr(ticket, "assigned_office", None) or "").strip()
    notes: str | None = None
    needs_completion = False
    context_parts = [original_question, *student_followups, *staff_substantive]
    if office_name:
        context_parts.append(office_name)
    relevant_referrals, ambiguous_referrals = _partition_referrals_by_relevance(
        staff_referrals,
        context_parts=context_parts,
    )

    if staff_substantive and _staff_answers_contradict(staff_substantive):
        needs_completion = True
        notes = "contradictory_answers"
        known = list(staff_substantive)
        known.extend(
            referral
            for referral in relevant_referrals
            if referral not in known
        )
        content = _format_incomplete_article(
            known=known,
            missing=[
                "Staff replies give conflicting instructions. "
                "Reconcile the official process before publishing.",
            ],
            office_name=office_name,
        )
    elif staff_substantive:
        unanswered = _unanswered_followup_topics(student_followups, staff_substantive)
        preserved_referrals = _unique_referrals_not_in_answers(
            relevant_referrals, staff_substantive
        )
        embedded_referrals = _filter_referrals_by_relevance(
            _embedded_referral_sentences(staff_substantive),
            context_parts=context_parts,
            keep="relevant",
        )
        unconfirmed_referrals = _dedupe_texts(
            [*preserved_referrals, *embedded_referrals]
        )
        # Status/progress chatter is omitted from reusable FAQ copy. When a
        # substantive answer already exists, do not force incomplete solely
        # because the ticket also had "please wait / under review" updates —
        # staff review remains the quality gate before publish.
        content = _format_structured_article(
            staff_substantive,
            office_name=office_name,
            followups=student_followups,
            referrals=preserved_referrals,
            status_updates=None,
        )
        completion_notes: list[str] = []
        if unanswered:
            completion_notes.extend(
                f"Student follow-up about {topic} was not answered with "
                "reusable official details."
                for topic in unanswered
            )
        if unconfirmed_referrals:
            completion_notes.extend(
                _referral_completion_notes(
                    unconfirmed_referrals,
                    question=original_question,
                    followups=student_followups,
                )
            )
        if ambiguous_referrals:
            completion_notes.append(
                "At least one staff referral was too ambiguous to include as "
                "confirmed guidance and needs manual review."
            )
        if completion_notes:
            needs_completion = True
            if unanswered:
                notes = "unanswered_followup"
            elif unconfirmed_referrals or ambiguous_referrals:
                notes = "unconfirmed_referral"
            else:
                notes = "unconfirmed_referral"
            content = _append_incomplete_notes(content, completion_notes)
        elif len(" ".join(staff_substantive)) < _MIN_AUTO_ANSWER_CHARS:
            needs_completion = True
            notes = "answer_too_short"
            content = _ensure_completion_placeholder(content)
    elif relevant_referrals or ambiguous_referrals or staff_referrals:
        needs_completion = True
        notes = "incomplete_referral"
        known = list(relevant_referrals) if relevant_referrals else []
        missing = _missing_detail_notes(original_question, student_followups)
        if ambiguous_referrals and not relevant_referrals:
            missing = [
                "Staff only provided ambiguous referral guidance that is not "
                "safe to publish as confirmed Knowledge Base facts.",
                *missing,
            ]
        elif not relevant_referrals and not ambiguous_referrals and staff_referrals:
            missing = [
                "Staff replies did not provide on-topic reusable guidance for "
                "this question.",
                *missing,
            ]
        elif ambiguous_referrals:
            missing.append(
                "An ambiguous staff referral was omitted from confirmed guidance "
                "and needs manual review."
            )
        if staff_deferred:
            known.extend(
                item for item in staff_deferred if item not in known
            )
        content = _format_incomplete_article(
            known=known,
            missing=missing,
            office_name=office_name,
        )
    elif staff_deferred:
        needs_completion = True
        notes = "deferred_answer"
        content = _format_incomplete_article(
            known=staff_deferred,
            missing=[
                "Staff indicated a follow-up is still needed; no reusable "
                "answer was recorded."
            ],
            office_name=office_name,
        )
    else:
        needs_completion = True
        notes = "no_staff_answer"
        content = _COMPLETION_MARKER

    title_source = original_question or "Support question"
    try:
        title = _clean_title(title_source)
    except TicketKnowledgeError:
        title = "Support question"
    summary = _article_summary(
        title=title,
        content=content,
        incomplete=needs_completion,
        notes=notes,
    )
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


def _mark_generation_failed(
    session: Session,
    *,
    ticket_id: str,
    actor: User,
    reason: str | None = None,
) -> None:
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
    note = (reason or "generation_failed").strip()[:_GENERATION_NOTES_MAX] or "generation_failed"
    previous_status = ticket.kb_conversion_status or "none"
    ticket.kb_conversion_status = "failed"
    ticket.updated_at = utc_now()
    session.add(ticket)
    if existing is not None:
        existing.generation_notes = note
        existing.needs_manual_completion = False
        # Keep an unpublished draft linked, but surface the failure reason.
        if (existing.review_status or "").strip().lower() != "rejected":
            existing.review_status = "pending"
        session.add(existing)
        ticket.kb_article_id = existing.id
        session.add(ticket)
    record_ticket_audit(
        session,
        ticket_id=ticket.id,
        actor=actor,
        action="kb_generate_failed",
        field_name="kb_conversion_status",
        old_value=previous_status,
        new_value=f"failed:{note}",
    )
    session.commit()


def _auto_generation_failure_reason(exc: TicketKnowledgeError) -> str:
    """Map a TicketKnowledgeError to a short staff-visible note (no PII)."""
    message = str(exc or "").strip()
    lowered = message.casefold()
    if "already covers this topic" in lowered:
        return "duplicate_topic"
    if "only resolved or closed" in lowered:
        return "invalid_status"
    if "at least" in lowered and "characters" in lowered:
        return "answer_too_short"
    if "add an office or admin reply" in lowered:
        return "missing_staff_answer"
    if "incomplete" in lowered:
        return "incomplete_answer"
    # Keep a sanitized, truncated remnant for unexpected TicketKnowledgeError.
    cleaned = redact_ticket_pii(message)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return "generation_blocked"
    return cleaned[:_GENERATION_NOTES_MAX]


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


def is_ticket_derived_article(
    *,
    source_ticket_id: str | None = None,
    kb_origin: str | None = None,
) -> bool:
    """True when persisted article fields identify a ticket-resolution draft."""
    if (source_ticket_id or "").strip():
        return True
    return str(kb_origin or "").strip().lower() == "ticket_resolution"


def ticket_article_publication_blocked(
    *,
    content: str | None,
    needs_manual_completion: bool = False,
    source_ticket_id: str | None = None,
    kb_origin: str | None = None,
) -> str | None:
    """Soft incomplete signals no longer hard-block publication.

    Ticket-derived drafts may still show a staff-facing warning in the UI when
    ``needs_manual_completion`` is set or the completion marker remains, but
    office/admin reviewers decide whether to publish. Other content gates
    (empty body, ``[NEEDS REVIEW]``, etc.) stay enforced elsewhere.
    """
    _ = (
        content,
        needs_manual_completion,
        source_ticket_id,
        kb_origin,
    )
    return None


def clear_incomplete_signals_on_publish(article: PublishedArticle) -> None:
    """Drop stuck incomplete flags once staff publishes a ticket-derived draft."""
    if not is_ticket_derived_article(
        source_ticket_id=getattr(article, "source_ticket_id", None),
        kb_origin=getattr(article, "kb_origin", None),
    ):
        return
    article.needs_manual_completion = False
    article.generation_notes = None


def apply_staff_edit_completion_state(article: PublishedArticle) -> bool:
    """Clear incomplete flags when staff saved a completed ticket-derived body.

    Knowledge Base article edits previously updated content only and left
    ``needs_manual_completion`` stuck true, so publish stayed blocked even after
    staff removed the completion warning. Returns True when flags were cleared.
    """
    if bool(getattr(article, "published", False)):
        return False
    if not is_ticket_derived_article(
        source_ticket_id=getattr(article, "source_ticket_id", None),
        kb_origin=getattr(article, "kb_origin", None),
    ):
        return False
    content = getattr(article, "content", None) or ""
    if _COMPLETION_MARKER in content or _INCOMPLETE_NOTES_HEADING in content:
        article.needs_manual_completion = True
        return False
    if not _staff_supplied_content_completes_draft(content):
        return False
    if not bool(getattr(article, "needs_manual_completion", False)) and not getattr(
        article, "generation_notes", None
    ):
        return False
    article.needs_manual_completion = False
    article.generation_notes = None
    return True


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

    want = _canonical_topic_title(_normalize_match_title(title))
    if len(want) < 3:
        return None

    # Prefer the shared matcher (exact / near title across the library).
    match = find_matching_published_article(session, title=title)
    if (
        match is not None
        and bool(match.published)
        and (not exclude_article_id or match.id != exclude_article_id)
        and _titles_are_duplicate_topics(
            want, _canonical_topic_title(_normalize_match_title(match.title))
        )
    ):
        return match

    # Fallback: only published rows with the tightened topic comparator.
    rows = (
        session.query(PublishedArticle)
        .filter(PublishedArticle.published.is_(True))
        .all()
    )
    for row in rows:
        if exclude_article_id and row.id == exclude_article_id:
            continue
        other = _canonical_topic_title(_normalize_match_title(row.title))
        if _titles_are_duplicate_topics(want, other):
            return row
    return None


def _canonical_topic_title(normalized: str) -> str:
    """Drop trailing parenthetical asides from already-normalized titles."""
    text = (normalized or "").strip()
    text = re.sub(r"\s*\([^)]*\)\s*$", "", text).strip()
    return re.sub(r"\s+", " ", text).strip()


def _topic_tokens(normalized: str) -> list[str]:
    """Split a normalized title into alphanumeric tokens."""
    return [
        token
        for token in re.findall(r"[a-z0-9]+", (normalized or "").casefold())
        if token
    ]


def _is_contiguous_subsequence(shorter: list[str], longer: list[str]) -> bool:
    if not shorter or len(shorter) > len(longer):
        return False
    span = len(shorter)
    for start in range(0, len(longer) - span + 1):
        if longer[start : start + span] == shorter:
            return True
    return False


def _titles_are_duplicate_topics(left: str, right: str) -> bool:
    """True when two FAQ titles describe the same topic.

    Exact normalized equality always matches. Single-token / generic titles
    (e.g. ``Enrollment``) never block a longer specific title via substring
    containment — that was the v87 production false positive. Multi-token
    phrases may still match when the shorter phrase appears as a contiguous
    token sequence inside the longer title.
    """
    if not left or not right:
        return False
    if left == right:
        return True

    left_tokens = _topic_tokens(left)
    right_tokens = _topic_tokens(right)
    if not left_tokens or not right_tokens:
        return False
    if left_tokens == right_tokens:
        return True

    shorter, longer = (
        (left_tokens, right_tokens)
        if len(left_tokens) <= len(right_tokens)
        else (right_tokens, left_tokens)
    )
    # One generic word is never enough evidence of duplication.
    if len(shorter) < 2:
        return False
    if not _is_contiguous_subsequence(shorter, longer):
        return False
    # Specific 3+ token phrases (e.g. "certificate of enrollment") may block
    # a longer title that contains them. Two-token phrases only when they are
    # a large share of the longer title (avoids "student id" blocking
    # unrelated student-id-adjacent topics that merely share those words
    # non-specifically — still require contiguity above).
    if len(shorter) >= 3:
        return True
    return (len(shorter) / max(len(longer), 1)) >= 0.6


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
        stripped = _COURTESY_PREFIX_RE.sub("", stripped).strip()
        if stripped and not _FILLER_RE.match(stripped):
            kept.append(stripped)
    joined = " ".join(kept).strip()
    if not joined or _FILLER_RE.match(joined):
        return ""
    return joined


def _is_courtesy_or_boilerplate(text: str) -> bool:
    cleaned = (text or "").strip()
    if not cleaned:
        return True
    if _COURTESY_ONLY_RE.match(cleaned) or _FILLER_RE.match(cleaned):
        return True
    return False


def _is_staff_clarifying_question(text: str) -> bool:
    return bool(_STAFF_CLARIFYING_QUESTION_RE.search(text or ""))


def _has_actionable_procedure_cue(text: str) -> bool:
    """True when the sentence gives form/office/payment/procedure guidance.

    Used to keep instructional phrasing (including polite "could you please
    provide the … form") from being discarded as a clarifying question.
    """
    cleaned = (text or "").strip()
    if not cleaned or _referral_hedge_overrides_action(cleaned):
        return False
    if _CONCRETE_FACT_RE.search(cleaned) or _REQUIREMENT_EVIDENCE_RE.search(cleaned):
        return True
    return bool(
        re.search(
            r"\b(?:"
            r"request\s+form|application\s+form|"
            r"window\s*\d+|at\s+window|"
            r"cashier|payment|pay(?:\s+at|\s+the)?|"
            r"procedure|osas|dean(?:'s)?\s+office"
            r")\b",
            cleaned,
            flags=re.IGNORECASE,
        )
    )


def _is_clarifying_only(text: str) -> bool:
    """Clarifying ask with no actionable procedure/form/payment guidance."""
    cleaned = (text or "").strip()
    if not cleaned or not _is_staff_clarifying_question(cleaned):
        return False
    return not _has_actionable_procedure_cue(cleaned)


def _is_identity_intake_only(text: str) -> bool:
    """True when staff only requests the student's personal identity details.

    Mentions of student ID / student number / program inside procedural
    instructions (present, bring, enroll, pay, window, form, etc.) are not
    identity intake.
    """
    cleaned = (text or "").strip()
    if not cleaned:
        return False
    if not _IDENTITY_REQUEST_RE.search(cleaned):
        return False
    if not _IDENTITY_FIELD_RE.search(cleaned):
        return False
    # Ignore the soft "when submitting your request" tail common on intake prompts.
    procedural = _SOFT_WHEN_SUBMITTING_RE.sub(" ", cleaned)
    if _REQUIREMENT_EVIDENCE_RE.search(procedural):
        return False
    if re.search(
        r"\b(?:application\s+form|request\s+form|fee|cashier|window|working\s+days?)\b",
        procedural,
        flags=re.IGNORECASE,
    ):
        return False
    # Present/bring/enroll/pay/go-to instructions are actionable, not intake.
    if re.search(
        r"\b(?:"
        r"present(?:\s+your)?|bring(?:\s+your)?|enroll(?:\s+in)?|"
        r"pay(?:\s+at|\s+the)?|go\s+to|proceed\s+to|claim(?:\s+stub)?|"
        r"fill\s+out|file(?:\s+the)?"
        r")\b",
        procedural,
        flags=re.IGNORECASE,
    ):
        return False
    # Remaining "submit" after stripping the soft clause still means procedure.
    if re.search(r"\bsubmit\b", procedural, flags=re.IGNORECASE):
        return False
    return True


def _referral_hedge_overrides_action(text: str) -> bool:
    """True when submit/bring verbs are only inside a confirm/check hedge."""
    cleaned = (text or "").strip()
    if not cleaned:
        return False
    if not _REFERRAL_HEDGE_RE.search(cleaned):
        return False
    # Affirmative requirement lists stay substantive; "confirm the current
    # application form before submitting" remains a referral despite form nouns.
    if re.search(
        r"\b(?:requirements?\s+(?:are|include)|required\s+documents?|"
        r"documents?\s+required)\b",
        cleaned,
        flags=re.IGNORECASE,
    ):
        return False
    return True


def _has_substantive_evidence(text: str) -> bool:
    cleaned = (text or "").strip()
    if not cleaned:
        return False
    if _is_courtesy_or_boilerplate(cleaned):
        return False
    if _is_clarifying_only(cleaned):
        return False
    if _is_identity_intake_only(cleaned):
        return False
    if _referral_hedge_overrides_action(cleaned):
        return False
    return bool(_CONCRETE_FACT_RE.search(cleaned) or _REQUIREMENT_EVIDENCE_RE.search(cleaned))


def _classify_sentence(text: str) -> str:
    """Classify one staff sentence as substantive, referral, or deferred."""
    cleaned = (text or "").strip()
    if not cleaned:
        return "deferred"
    if _is_courtesy_or_boilerplate(cleaned):
        return "deferred"
    # Clarifying asks defer unless the same sentence also gives actionable
    # form/office/payment/procedure guidance.
    if _is_clarifying_only(cleaned):
        return "deferred"
    has_deferred = bool(_DEFERRED_ANSWER_RE.search(cleaned))
    has_referral = bool(_REFERRAL_ANSWER_RE.search(cleaned)) or _referral_hedge_overrides_action(
        cleaned
    )
    has_action = bool(_CONCRETE_FACT_RE.search(cleaned)) and not _referral_hedge_overrides_action(
        cleaned
    )
    has_evidence = _has_substantive_evidence(cleaned)
    # Pure status / wait updates are never reusable FAQ answers.
    if has_deferred and not has_evidence and not has_referral:
        return "deferred"
    # "Contact X to obtain the application form" remains a referral, not a fact.
    # Also keep "confirm current form before submitting" as referral despite "submit".
    if has_referral and not has_action:
        return "referral"
    if has_referral and _referral_hedge_overrides_action(cleaned):
        return "referral"
    if _is_identity_intake_only(cleaned):
        return "deferred"
    if has_evidence:
        return "substantive"
    if has_deferred:
        return "deferred"
    if len(cleaned) < _MIN_AUTO_ANSWER_CHARS:
        return "deferred"
    if has_referral:
        return "referral"
    return "substantive"


def _classify_staff_answer(text: str) -> str:
    """Return ``substantive``, ``referral``, or ``deferred`` for a full reply.

    Classification is aggregated from clauses so a status phrase cannot erase
    actionable requirements in the same message, even without punctuation.
    """
    cleaned = (text or "").strip()
    if not cleaned:
        return "deferred"
    units = _split_staff_evidence_units(cleaned)
    kinds = {_classify_sentence(unit) for unit in units}
    if "substantive" in kinds:
        return "substantive"
    if "referral" in kinds:
        return "referral"
    return "deferred"


def _staff_answers_contradict(answers: list[str]) -> bool:
    blob = " ".join(answers)
    day_values = {
        match.group(1)
        for match in re.finditer(
            r"\b(\d+)\s*(?:working\s+)?days?\b", blob, flags=re.IGNORECASE
        )
    }
    if len(day_values) >= 2:
        return True
    fee_values = {
        re.sub(r"[^\d]", "", match.group(0))
        for match in re.finditer(
            r"(?:php|₱)\s*[\d,]+|\b\d{2,6}\s*pesos?\b", blob, flags=re.IGNORECASE
        )
    }
    fee_values.discard("")
    return len(fee_values) >= 2


def _unanswered_followup_topics(
    followups: list[str], staff_answers: list[str]
) -> list[str]:
    """Topics raised by the student that lack an actionable staff answer."""
    if not followups:
        return []
    follow_blob = " ".join(followups)
    missing: list[str] = []
    for topic, pattern in _FOLLOWUP_TOPIC_PATTERNS:
        if not pattern.search(follow_blob):
            continue
        answered = any(
            pattern.search(answer) and _CONCRETE_FACT_RE.search(answer)
            for answer in staff_answers
        )
        if not answered:
            missing.append(topic)
    return missing


def _missing_detail_notes(question: str, followups: list[str]) -> list[str]:
    blob = " ".join([question, *followups]).casefold()
    notes = [
        "Official requirements were not confirmed in this conversation.",
        "Do not invent forms, fees, processing times, or submission locations.",
    ]
    if "form" in blob:
        notes.append("The specific form/document required was not identified.")
    if any(token in blob for token in ("fee", "payment", "cost", "how much")):
        notes.append("Fees or payment details were not provided.")
    if any(token in blob for token in ("how long", "processing", "deadline", "release")):
        notes.append("Processing time or release schedule was not provided.")
    if any(token in blob for token in ("where", "office", "location")):
        notes.append("Exact submission location/window was not confirmed.")
    return notes


def _format_answer_steps(answers: list[str]) -> str:
    usable = [item.strip() for item in answers if item and item.strip()]
    if not usable:
        return ""
    if len(usable) == 1:
        return usable[0]
    return "\n".join(f"{index}. {item}" for index, item in enumerate(usable, start=1))


def _split_requirement_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!;])\s+|\n+", text)
    return [part.strip(" -•\t") for part in parts if part and part.strip(" -•\t")]


_STATUS_CLAUSE_SPLIT_RE = re.compile(
    r"(?i)(?<=\w)(?:\s+and\s+|\s+)"
    r"(?="
    r"we\s+will\s+(?:update|notify|contact)\s+you|"
    r"your\s+(?:request|application)\s+is\s+"
    r"(?:being\s+processed|currently\s+under\s+review|under\s+review)|"
    r"please\s+wait"
    r")"
)
_SUBSTANTIVE_CLAUSE_START_RE = re.compile(
    r"(?i)\b(?:"
    r"submit|bring|pay(?:\s+the|\s+at)?|fill\s+out|go\s+to|return\s+with|"
    r"present(?:\s+the)?|proceed\s+to|keep|"
    r"required\s+documents?|documents?\s+required|"
    r"requirements?\s+(?:are|include)|"
    r"the\s+required\s+documents?"
    r")\b"
)
# Status update followed by an actionable tail ("so please keep your claim stub").
_STATUS_THEN_ACTION_SPLIT_RE = re.compile(
    r"(?i)^(?P<status>.*?\b(?:"
    r"we\s+will\s+(?:update|notify|contact)\s+you\b.*?"
    r"(?:complete|ready|available)|"
    r"your\s+(?:request|application)\s+is\s+"
    r"(?:being\s+processed|currently\s+under\s+review|under\s+review)"
    r"))\s*(?:so\s+(?:please\s+)?|and\s+then\s+|then\s+|,\s*)?"
    r"(?P<action>(?:please\s+)?(?:keep|bring|submit|present|pay|return|go\s+to|claim)\b.+)$"
)


def _unit_has_unresolved_status(text: str) -> bool:
    """True when text still carries a ticket-status update signal."""
    return bool(_DEFERRED_ANSWER_RE.search(text or ""))


def _bucket_staff_evidence_unit(
    sentence: str,
    *,
    staff_substantive: list[str],
    staff_referrals: list[str],
    staff_deferred: list[str],
) -> None:
    """Route one evidence unit without letting concrete nouns cancel status."""
    text = (sentence or "").strip()
    if not text:
        return
    kind = _classify_sentence(text)
    if kind == "deferred":
        if text not in staff_deferred:
            staff_deferred.append(text)
        return
    if kind == "referral":
        if text not in staff_referrals:
            staff_referrals.append(text)
        return

    # Substantive unit that still embeds unresolved status (inseparable residue).
    if _unit_has_unresolved_status(text) and _has_substantive_evidence(text):
        action = _actionable_remainder_without_status(text)
        status = _status_remainder_without_action(text)
        if action and action not in staff_substantive:
            staff_substantive.append(action)
        if status and status not in staff_deferred:
            staff_deferred.append(status)
        elif text not in staff_deferred:
            # Separation failed: keep evidence, but force unresolved-status review.
            staff_deferred.append(text)
            if action is None and text not in staff_substantive:
                staff_substantive.append(text)
        return

    if text not in staff_substantive:
        staff_substantive.append(text)


def _actionable_remainder_without_status(text: str) -> str | None:
    """Return actionable text with unresolved status phrasing removed when possible."""
    cleaned = (text or "").strip()
    if not cleaned:
        return None
    match = _STATUS_THEN_ACTION_SPLIT_RE.match(cleaned)
    if match:
        action = (match.group("action") or "").strip(" \t-•,;")
        return action or None
    # Action-then-status already split elsewhere; drop trailing status markers.
    parts = [
        part.strip(" \t-•,;")
        for part in _STATUS_CLAUSE_SPLIT_RE.split(cleaned)
        if part and part.strip(" \t-•,;")
    ]
    actionable = [
        part
        for part in parts
        if _has_substantive_evidence(part) and not _unit_has_unresolved_status(part)
    ]
    if actionable:
        return " ".join(actionable).strip() or None
    # Fall back: remove deferred phrases, keep remaining evidence tokens/sentences.
    remainder = _DEFERRED_ANSWER_RE.sub(" ", cleaned)
    remainder = re.sub(r"\s+", " ", remainder).strip(" \t-•,;")
    if remainder and _has_substantive_evidence(remainder):
        return remainder
    return None


def _status_remainder_without_action(text: str) -> str | None:
    """Return unresolved status phrasing without the actionable tail when possible."""
    cleaned = (text or "").strip()
    if not cleaned:
        return None
    match = _STATUS_THEN_ACTION_SPLIT_RE.match(cleaned)
    if match:
        status = (match.group("status") or "").strip(" \t-•,;")
        return status or None
    parts = [
        part.strip(" \t-•,;")
        for part in _STATUS_CLAUSE_SPLIT_RE.split(cleaned)
        if part and part.strip(" \t-•,;")
    ]
    statuses = [
        part
        for part in parts
        if _unit_has_unresolved_status(part) and not _has_substantive_evidence(part)
    ]
    if statuses:
        return " ".join(statuses).strip() or None
    match = _DEFERRED_ANSWER_RE.search(cleaned)
    if not match:
        return None
    # Best-effort: keep from deferred match through the status endpoint words.
    snippet = cleaned[match.start() :].strip()
    endpoint = re.search(
        r"(?i)\b(?:complete|ready|available|under\s+review|being\s+processed)\b",
        snippet,
    )
    if endpoint:
        return snippet[: endpoint.end()].strip(" \t-•,;") or None
    return match.group(0).strip() or None


def _partition_mixed_status_clause(text: str) -> list[str]:
    """Split one clause that mixes actionable evidence with unresolved status.

    Concrete nouns such as ``claim stub`` must not cancel an unresolved status
    signal: both portions are preserved as separate units when possible.
    """
    cleaned = (text or "").strip(" \t-•,;")
    if not cleaned:
        return []
    has_deferred = _unit_has_unresolved_status(cleaned)
    has_evidence = _has_substantive_evidence(cleaned)
    if not (has_deferred and has_evidence):
        return [cleaned]

    pieces = [
        part.strip(" \t-•,;")
        for part in _STATUS_CLAUSE_SPLIT_RE.split(cleaned)
        if part and part.strip(" \t-•,;")
    ]
    if len(pieces) >= 2:
        return _refine_mixed_units(pieces)

    # Status then action: "... once processing is complete so please keep ..."
    match = _STATUS_THEN_ACTION_SPLIT_RE.match(cleaned)
    if match:
        status = (match.group("status") or "").strip(" \t-•,;")
        action = (match.group("action") or "").strip(" \t-•,;")
        if status and action:
            return _refine_mixed_units([status, action])

    # Status-first / run-on: cut before the actionable requirement clause.
    match = _SUBSTANTIVE_CLAUSE_START_RE.search(cleaned)
    if match and match.start() > 0:
        left = cleaned[: match.start()].strip(" \t-•,;and")
        right = cleaned[match.start() :].strip(" \t-•,;")
        if left and right and _unit_has_unresolved_status(left):
            return _refine_mixed_units([left, right])
    # Could not separate reliably: keep the text once; callers must still flag
    # unresolved status when deferred language remains beside evidence.
    return [cleaned]


def _refine_mixed_units(parts: list[str]) -> list[str]:
    """Re-run mixed partitioning on pieces that still combine status + evidence."""
    refined: list[str] = []
    for part in parts:
        text = (part or "").strip(" \t-•,;")
        if not text:
            continue
        if _unit_has_unresolved_status(text) and _has_substantive_evidence(text):
            # Avoid infinite recursion when a piece cannot be split further.
            nested = _partition_mixed_status_clause(text)
            if nested == [text]:
                refined.append(text)
            else:
                refined.extend(nested)
        else:
            refined.append(text)
    return refined


def _split_staff_evidence_units(text: str) -> list[str]:
    """Split staff text into classify-able evidence units (sentence + status-aware)."""
    cleaned = (text or "").strip()
    if not cleaned:
        return []
    units: list[str] = []
    for sentence in _split_requirement_sentences(cleaned) or [cleaned]:
        units.extend(_partition_mixed_status_clause(sentence))
    return _dedupe_texts(units)


def _dedupe_texts(values: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = (value or "").strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(text)
    return unique


def _unique_referrals_not_in_answers(
    referrals: list[str], answers: list[str]
) -> list[str]:
    """Keep referral guidance that is not already copied inside substantive replies."""
    answer_blob = " ".join(answers).casefold()
    unique: list[str] = []
    for referral in _dedupe_texts(referrals):
        if referral.casefold() in answer_blob:
            continue
        unique.append(referral)
    return unique


_RELEVANCE_STOPWORDS = frozenset(
    token
    for token in (_IDENTITY_STOPWORDS | _REFERRAL_BOILERPLATE_TOKENS)
    if token
    not in {
        "registrar",
        "student",
        "faculty",
    }
)
# Generic terms that must not independently establish referral relevance.
_GENERIC_RELEVANCE_TOKENS = frozenset(
    {
        "form",
        "forms",
        "office",
        "requirements",
        "requirement",
        "processing",
        "schedule",
        "procedure",
        "procedures",
        "latest",
        "information",
        "info",
        "details",
        "detail",
        "current",
        "process",
        "request",
        "requests",
        "documents",
        "document",
        "application",
        "applications",
        "working",
        "days",
        "day",
        "steps",
        "step",
        "window",
        "assignment",
    }
)
_FEE_TOPIC_RE = re.compile(
    r"\b(?:fee|fees|payment|cashier|how\s+much|cost)\b",
    re.IGNORECASE,
)
_RELATED_TOKEN_GROUPS: tuple[frozenset[str], ...] = (
    frozenset({"claim", "release", "releasing", "claiming"}),
    frozenset({"tor", "transcript"}),
    frozenset({"coe", "enrollment", "enrolment", "certificate"}),
    frozenset({"excuse", "absence"}),
)


def _significant_tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", (text or "").casefold())
        if len(token) >= 3 and token not in _RELEVANCE_STOPWORDS
    }


def _distinctive_tokens(text: str) -> set[str]:
    """Content tokens strong enough to support referral relevance."""
    return _significant_tokens(text) - _GENERIC_RELEVANCE_TOKENS


def _expand_related_tokens(tokens: set[str]) -> set[str]:
    expanded = set(tokens)
    for group in _RELATED_TOKEN_GROUPS:
        if tokens & group:
            expanded |= group
    return expanded


def _referral_relevance(
    referral: str, *, context_parts: list[str]
) -> str:
    """Return ``relevant``, ``unrelated``, or ``ambiguous`` for a referral sentence.

    Generic words such as form/office/requirements/processing alone never make a
    referral relevant. Distinctive topic evidence from the ticket context is required.
    """
    text = (referral or "").strip()
    if not text:
        return "unrelated"

    ref_distinct = _distinctive_tokens(text)
    ctx_distinct: set[str] = set()
    for part in context_parts:
        ctx_distinct |= _distinctive_tokens(part or "")
    ref_expanded = _expand_related_tokens(ref_distinct)
    ctx_expanded = _expand_related_tokens(ctx_distinct)

    # Fee/payment is distinctive when both referral and ticket discuss it.
    if _FEE_TOPIC_RE.search(text) and any(
        _FEE_TOPIC_RE.search(part or "") for part in context_parts
    ):
        return "relevant"

    # Light synonym bridges on distinctive tokens only (claim/release, COE, etc.).
    for group in _RELATED_TOKEN_GROUPS:
        if (ref_distinct & group) and (ctx_distinct & group):
            return "relevant"

    overlap = ref_expanded & ctx_expanded
    if len(overlap) >= 2:
        return "relevant"
    if len(overlap) == 1:
        return "ambiguous"

    # No distinctive evidence left in the referral (generic office/requirements only).
    if not ref_distinct:
        return "ambiguous"
    return "unrelated"


def _partition_referrals_by_relevance(
    referrals: list[str],
    *,
    context_parts: list[str],
) -> tuple[list[str], list[str]]:
    """Split referrals into (relevant, ambiguous). Unrelated referrals are dropped."""
    relevant: list[str] = []
    ambiguous: list[str] = []
    for referral in _dedupe_texts(referrals):
        verdict = _referral_relevance(referral, context_parts=context_parts)
        if verdict == "relevant":
            relevant.append(referral)
        elif verdict == "ambiguous":
            ambiguous.append(referral)
    return relevant, ambiguous


def _filter_referrals_by_relevance(
    referrals: list[str],
    *,
    context_parts: list[str],
    keep: str,
) -> list[str]:
    kept: list[str] = []
    for referral in _dedupe_texts(referrals):
        if _referral_relevance(referral, context_parts=context_parts) == keep:
            kept.append(referral)
    return kept


def _embedded_referral_sentences(answers: list[str]) -> list[str]:
    """Referral-only sentences embedded inside otherwise substantive staff replies."""
    found: list[str] = []
    for answer in answers:
        for sentence in _split_staff_evidence_units(answer):
            if _classify_sentence(sentence) == "referral":
                found.append(sentence)
    return _dedupe_texts(found)


def _referral_completion_notes(
    referrals: list[str],
    *,
    question: str = "",
    followups: list[str] | None = None,
) -> list[str]:
    """Staff-facing notes when referrals leave official details unconfirmed."""
    notes = [
        "Some details still require office confirmation and must not be published "
        "as verified facts.",
        "Do not invent forms, fees, processing times, or submission locations.",
    ]
    blob = " ".join([question, *(followups or []), *referrals]).casefold()
    if any(token in blob for token in ("fee", "payment", "cost", "how much", "cashier")):
        notes.append("Processing fee / payment amount was not confirmed.")
    if "form" in blob:
        notes.append("Any form or document still marked for confirmation needs an official name.")
    if re.search(
        r"\b(?:how long|processing time|deadline|release schedule|working days?)\b",
        blob,
    ):
        notes.append("Processing time or release schedule still needs confirmation.")
    if any(token in blob for token in ("where", "location", "window", "counter")):
        notes.append("Exact submission location/window still needs confirmation.")
    return notes


def _format_structured_article(
    answers: list[str],
    *,
    office_name: str = "",
    followups: list[str] | None = None,
    referrals: list[str] | None = None,
    status_updates: list[str] | None = None,
) -> str:
    """Build a concise structured FAQ body from substantive staff answers."""
    _ = followups  # Follow-ups inform incompleteness checks, not body copy.
    usable = [item.strip() for item in answers if item and item.strip()]
    if not usable:
        return ""

    requirements: list[str] = []
    procedures: list[str] = []
    overview: list[str] = []
    notes: list[str] = []

    for answer in usable:
        for sentence in _split_staff_evidence_units(answer):
            kind = _classify_sentence(sentence)
            if kind == "deferred" or (
                _unit_has_unresolved_status(sentence)
                and not _has_substantive_evidence(sentence)
            ):
                # Status language never becomes the FAQ overview/answer.
                continue
            if kind == "referral":
                notes.append(sentence)
                continue
            # Concrete nouns must not smuggle unresolved status into Procedure.
            if _unit_has_unresolved_status(sentence):
                scrubbed = _actionable_remainder_without_status(sentence)
                if not scrubbed:
                    continue
                sentence = scrubbed
            lower = sentence.casefold()
            if any(
                token in lower
                for token in (
                    "bring",
                    "submit",
                    "requirement",
                    "required document",
                    "documents are",
                    "form",
                    "tor",
                    "id ",
                    "valid id",
                )
            ) and not lower.startswith(("go to", "pay at", "return", "keep")):
                requirements.append(sentence)
            elif any(
                token in lower
                for token in (
                    "go to",
                    "fill out",
                    "pay",
                    "return",
                    "claim",
                    "present",
                    "proceed",
                    "keep",
                )
            ):
                procedures.append(sentence)
            elif "working day" in lower or (
                "within" in lower and "day" in lower
            ):
                notes.append(sentence)
            else:
                overview.append(sentence)

    sections: list[str] = []
    if overview:
        sections.append("## Overview\n\n" + " ".join(overview).strip())
    if requirements:
        bullets = "\n".join(f"- {item}" for item in requirements)
        sections.append(f"## Requirements\n\n{bullets}")
    if procedures:
        if len(procedures) == 1:
            sections.append(f"## Procedure\n\n{procedures[0]}")
        else:
            steps = "\n".join(
                f"{index}. {item}" for index, item in enumerate(procedures, start=1)
            )
            sections.append(f"## Procedure\n\n{steps}")
    where_lines: list[str] = []
    if office_name:
        where_lines.append(office_name)
    referral_lines = _unique_referrals_not_in_answers(referrals or [], usable)
    for item in referral_lines:
        if item not in where_lines:
            where_lines.append(item)
    # Hedged confirm/check sentences classified as notes are still office directions.
    for item in notes:
        if (_REFERRAL_ANSWER_RE.search(item) or _referral_hedge_overrides_action(item)) and (
            item not in where_lines
        ):
            where_lines.append(item)
    retained_notes = [
        item
        for item in notes
        if not (
            _REFERRAL_ANSWER_RE.search(item) or _referral_hedge_overrides_action(item)
        )
    ]
    if where_lines:
        if len(where_lines) == 1 and where_lines[0] == office_name:
            sections.append(f"## Where to go\n\n{office_name}")
        else:
            bullets = "\n".join(f"- {item}" for item in where_lines)
            sections.append(f"## Where to go\n\n{bullets}")
    if retained_notes:
        note_lines = "\n".join(f"- {item}" for item in retained_notes)
        sections.append(f"## Important notes\n\n{note_lines}")
    # Ticket progress/status lines are intentionally not rendered into FAQ
    # bodies. They are not reusable procedures, and surfacing them as
    # "## Request status" confused staff review without improving the answer.
    _ = status_updates

    if sections:
        return "\n\n".join(sections).strip()
    # Fallback: keep a coherent multi-reply answer without conversational scaffolding.
    return _format_answer_steps(usable)


def _format_incomplete_article(
    *,
    known: list[str],
    missing: list[str],
    office_name: str = "",
) -> str:
    parts: list[str] = []
    known_text = _format_answer_steps(known).strip()
    if known_text:
        parts.append(f"## What we know\n\n{known_text}")
    if office_name:
        parts.append(
            f"## Where to go\n\n{office_name}\n\n"
            "Confirm the current official process with this office before publishing."
        )
    return _append_incomplete_notes("\n\n".join(parts).strip(), missing)


def _append_incomplete_notes(content: str, missing: list[str]) -> str:
    notes = [item.strip() for item in missing if item and item.strip()]
    if not notes:
        notes = [
            "The conversation does not establish a complete reusable answer.",
        ]
    bullet = "\n".join(f"- {item}" for item in notes)
    block = f"{_INCOMPLETE_NOTES_HEADING}\n\n{bullet}\n\n{_COMPLETION_MARKER}"
    text = (content or "").strip()
    if not text:
        return block
    if _INCOMPLETE_NOTES_HEADING in text and _COMPLETION_MARKER in text:
        return text
    return f"{text}\n\n{block}".strip()


def _article_summary(
    *,
    title: str,
    content: str,
    incomplete: bool,
    notes: str | None,
) -> str:
    topic = re.sub(r"\s+", " ", (title or "").strip()).rstrip("?")
    if incomplete:
        if notes == "incomplete_referral":
            return (
                f"Partial guidance about {topic} from a support conversation. "
                "Official requirements still need staff confirmation before publishing."
            )
        if notes == "contradictory_answers":
            return (
                f"Draft notes about {topic} contain conflicting staff instructions "
                "and need reconciliation before publishing."
            )
        if notes == "unanswered_followup":
            return (
                f"Draft answer about {topic} is missing details raised in the "
                "student follow-up and needs staff completion."
            )
        if notes == "unconfirmed_referral":
            return (
                f"Draft answer about {topic} includes confirmed steps plus details "
                "that still need office confirmation before publishing."
            )
        if notes == "unresolved_status":
            return (
                f"Draft answer about {topic} still includes an unresolved status "
                "update and needs staff completion before publishing."
            )
        if notes == "deferred_answer":
            return (
                f"Incomplete draft about {topic}. Staff only recorded a status "
                "update; a reusable answer is still missing."
            )
        return (
            f"Incomplete draft about {topic}. Staff must supply the missing "
            "official details before this can be published."
        )
    # Prefer a short overview sentence from the generated body.
    overview_match = re.search(
        r"##\s*Overview\s*\n+(.+?)(?:\n\n|\Z)", content or "", flags=re.IGNORECASE | re.DOTALL
    )
    if overview_match:
        return _short_summary(overview_match.group(1), limit=220)
    return _short_summary(
        f"How to handle {topic}, based on an approved office support answer.",
        limit=220,
    )


def _staff_supplied_content_completes_draft(content: str) -> bool:
    """True when staff-edited body removes incompleteness markers and states facts.

    Acknowledgements, generic office referrals, and identity-intake prompts alone
    never complete a ticket-derived draft. Staff-authored FAQ prose classified as
    substantive (including non-imperative policy text) does complete it.
    """
    text = (content or "").strip()
    if not text:
        return False
    if _COMPLETION_MARKER in text or _INCOMPLETE_NOTES_HEADING in text:
        return False
    units = _split_staff_evidence_units(text)
    if not units:
        units = [text]
    return any(_classify_sentence(unit) == "substantive" for unit in units)


def _needs_manual_flag(
    generated: GeneratedTicketArticle,
    content: str | None,
    keep_generation_flags: bool,
) -> bool:
    if keep_generation_flags:
        return bool(generated.needs_manual_completion)
    text = (content or "").strip()
    if not text:
        return bool(generated.needs_manual_completion)
    # Staff-supplied bodies only clear incompleteness when they actually complete
    # the reusable answer. Pasting the incomplete ticket chat must not publish.
    if _COMPLETION_MARKER in text:
        return True
    if generated.needs_manual_completion:
        return not _staff_supplied_content_completes_draft(text)
    return False


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
    text = (content or "").strip()
    if not text:
        return notes
    if generated.needs_manual_completion and not _staff_supplied_content_completes_draft(text):
        return notes
    return None


def _ensure_completion_placeholder(content: str) -> str:
    """Always attach the completion marker when an incomplete draft is persisted."""
    text = (content or "").strip()
    if _COMPLETION_MARKER in text:
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
    # Drop conversational parentheticals accidentally appended from follow-ups.
    cleaned = _CONVERSATIONAL_PAREN_RE.sub("", cleaned).strip()
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
