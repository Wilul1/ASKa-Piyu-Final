from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Office(Base):
    __tablename__ = "offices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    service_category: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    users: Mapped[list["User"]] = relationship(back_populates="office")
    aliases: Mapped[list["OfficeAlias"]] = relationship(
        back_populates="office",
        cascade="all, delete-orphan",
    )


class OfficeAlias(Base):
    """Dynamic office name/abbreviation aliases used for text matching.

    Alias strings and weights live in PostgreSQL so Article Planner / grouping
    never hardcodes institution-specific office names.
    """

    __tablename__ = "office_aliases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    office_id: Mapped[str] = mapped_column(String(36), ForeignKey("offices.id"), index=True, nullable=False)
    alias: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    weight: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    office: Mapped[Office] = relationship(back_populates="aliases")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "role IN ('student', 'faculty', 'office', 'admin')",
            name="ck_users_role",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    office_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("offices.id"), nullable=True)
    student_id: Mapped[str | None] = mapped_column(String(80), unique=True, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    credentials_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Public student signup starts unverified; admin-created faculty/office/admin
    # accounts are set True at creation (an admin already vouched for them).
    # Existing rows are backfilled True by the additive schema upgrade so
    # accounts created before this feature shipped are grandfathered in.
    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # SHA-256 hex digest of the current one-time code; never store the raw code.
    email_verification_code_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    email_verification_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Drives the resend cooldown (see email_verification_resend_cooldown_seconds).
    email_verification_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    office: Mapped[Office | None] = relationship(back_populates="users")
    tickets: Mapped[list["Ticket"]] = relationship(back_populates="user", foreign_keys="Ticket.user_id")
    replies: Mapped[list["TicketReply"]] = relationship(back_populates="sender", foreign_keys="TicketReply.sender_id")


class Ticket(Base):
    __tablename__ = "tickets"
    __table_args__ = (
        CheckConstraint(
            "priority IN ('Urgent', 'High', 'Medium', 'Low')",
            name="ck_tickets_priority",
        ),
        CheckConstraint("status IN ('Open', 'In Progress', 'Resolved', 'Closed')", name="ck_tickets_status"),
        CheckConstraint(
            "kb_conversion_status IN ('none', 'draft', 'published')",
            name="ck_tickets_kb_conversion_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True, nullable=False)
    original_question: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    category: Mapped[str] = mapped_column(String(120), nullable=False)
    assigned_office_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("offices.id"), index=True, nullable=True
    )
    assigned_office: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    priority: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="Open", index=True, nullable=False)
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_from_chatbot: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    kb_article_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    kb_conversion_status: Mapped[str] = mapped_column(String(20), default="none", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="tickets", foreign_keys=[user_id])
    assigned_office_ref: Mapped["Office | None"] = relationship(foreign_keys=[assigned_office_id])
    replies: Mapped[list["TicketReply"]] = relationship(
        back_populates="ticket",
        cascade="all, delete-orphan",
        order_by="TicketReply.created_at",
    )
    attachments: Mapped[list["TicketAttachment"]] = relationship(
        back_populates="ticket",
        cascade="all, delete-orphan",
        order_by="TicketAttachment.created_at",
    )


class TicketReply(Base):
    __tablename__ = "ticket_replies"
    __table_args__ = (
        CheckConstraint(
            "sender_role IN ('student', 'faculty', 'office', 'admin')",
            name="ck_ticket_replies_sender_role",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    ticket_id: Mapped[str] = mapped_column(String(36), ForeignKey("tickets.id"), index=True, nullable=False)
    sender_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True, nullable=False)
    sender_role: Mapped[str] = mapped_column(String(20), nullable=False)
    sender_name: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    is_internal: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    ticket: Mapped[Ticket] = relationship(back_populates="replies")
    sender: Mapped[User] = relationship(back_populates="replies", foreign_keys=[sender_id])


class TicketAttachment(Base):
    __tablename__ = "ticket_attachments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    ticket_id: Mapped[str] = mapped_column(String(32), ForeignKey("tickets.id"), index=True, nullable=False)
    uploaded_by_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True, nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    stored_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    ticket: Mapped[Ticket] = relationship(back_populates="attachments")
    uploaded_by: Mapped[User] = relationship(foreign_keys=[uploaded_by_id])


class TicketAuditEvent(Base):
    """Append-only history of ticket field / lifecycle changes."""

    __tablename__ = "ticket_audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    ticket_id: Mapped[str] = mapped_column(String(32), ForeignKey("tickets.id"), index=True, nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), index=True, nullable=True)
    actor_role: Mapped[str] = mapped_column(String(20), nullable=False)
    action: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    field_name: Mapped[str | None] = mapped_column(String(40), nullable=True)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class Notification(Base):
    """In-app notification for ticket replies and lifecycle updates."""

    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True, nullable=False)
    ticket_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("tickets.id"), index=True, nullable=True)
    type: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True, nullable=False)


class AuthEvent(Base):
    """Login/signup audit trail used for abuse detection (IP velocity)."""

    __tablename__ = "auth_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('signup', 'login_ok', 'login_fail')",
            name="ck_auth_events_event_type",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    event_type: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), index=True, nullable=True)
    ip_address: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True, nullable=False)


class PublishedArticle(Base):
    __tablename__ = "published_articles"
    __table_args__ = (
        CheckConstraint(
            "audience IN ('student', 'faculty', 'both')",
            name="ck_published_articles_audience",
        ),
        CheckConstraint(
            "kb_origin IN ('document', 'ticket_resolution')",
            name="ck_published_articles_kb_origin",
        ),
        CheckConstraint(
            "content_format IN ('plain', 'html')",
            name="ck_published_articles_content_format",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    category: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    subcategory: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_format: Mapped[str] = mapped_column(String(20), default="plain", nullable=False)
    office: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_document_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    source_ticket_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("tickets.id"), unique=True, nullable=True, index=True
    )
    audience: Mapped[str] = mapped_column(String(20), default="both", nullable=False, index=True)
    kb_origin: Mapped[str] = mapped_column(String(40), default="document", nullable=False, index=True)
    resolution_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    published_by_user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    rag_indexed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    rag_document_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    chunk_count: Mapped[int | None] = mapped_column(CheckConstraint("chunk_count >= 0"), nullable=True)
    published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    media: Mapped[list["ArticleMedia"]] = relationship(
        back_populates="article",
        cascade="all, delete-orphan",
    )


class ArticleMedia(Base):
    """Inline images and file attachments for Knowledge Articles.

    Files live in ``kb_media_dir`` (same volume as existing public KB images).
    ``article_id`` is null while the Create form is still unsaved.
    """

    __tablename__ = "article_media"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('inline_image', 'attachment')",
            name="ck_article_media_kind",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    article_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("published_articles.id"), index=True, nullable=True
    )
    uploaded_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), index=True, nullable=False
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_filename: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    article: Mapped[PublishedArticle | None] = relationship(back_populates="media")
    uploaded_by: Mapped[User] = relationship(foreign_keys=[uploaded_by_user_id])


class SourceDocument(Base):
    """Original uploaded source file (PDF etc.) — durable citation grounding.

    Chroma holds retrieval chunks only. This table + filesystem store remain
    the source of truth for opening the original document at a cited page.
    """

    __tablename__ = "source_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    stored_file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    document_type: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    source_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    edition: Mapped[str | None] = mapped_column(String(120), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    byte_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Level-3 citation readiness (optional document-level page geometry hints)
    page_width: Mapped[float | None] = mapped_column(Float, nullable=True)
    page_height: Mapped[float | None] = mapped_column(Float, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )


class IngestionJob(Base):
    """Zero-cost digital-PDF background ingestion job.

    Lives entirely in the existing Heroku Postgres instance -- no Redis, no
    separate worker/queue service. ``pdf_bytes`` replaces local-filesystem
    persistence for this path (the web dyno's disk is ephemeral).

    ``document_id`` is set only once the job reaches ``published`` -- it is
    the Chroma ``document_id`` for the NEW version's chunks. ``needs_
    reconciliation`` means the new version published successfully but
    cleanup of the OLD version's chunks (by ``replaced_document_id``) failed
    partway through and must be retried/inspected manually -- the old
    version is intentionally left in place rather than guessed at.

    ``sha256_hash`` is deliberately NOT globally unique: a ``failed`` row
    must never permanently block retrying the exact same file (2026-10-04
    fix). Only ONE row with an ACTIVE status (queued/processing) may exist
    per hash at a time -- enforced by the partial unique index below, the
    real concurrency guard (see app/routes/admin/knowledge_base.py's
    IntegrityError handling for the race it protects against), not an
    application-only check. Historical failed/published/etc. rows for the
    same hash are retained side by side for audit.

    ``review_ready``/``indexing`` (2026-10-05) split the Heroku-web-dyno
    lightweight pipeline into a preview phase and a separate publish phase,
    so a slow remote-OCR extraction never has to run inside a single
    synchronous HTTP request (see digital_ingestion.py's
    process_extraction_preview_job / process_indexing_job). A job reaches
    ``review_ready`` once its (possibly OCR'd) page texts are persisted in
    ``extracted_pages_json`` -- nothing has been published yet. ``indexing``
    means a publish is in progress for a job that already passed review;
    it is kept distinct from ``processing`` (used for the pre-review
    extract/OCR/clean/chunk phase) so a page refresh mid-publish is never
    ambiguous with mid-extraction.
    """

    __tablename__ = "ingestion_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','processing','published','failed','ocr_required',"
            "'needs_reconciliation','review_ready','indexing')",
            name="ck_ingestion_jobs_status",
        ),
        Index(
            "uq_ingestion_jobs_sha256_active_status",
            "sha256_hash",
            unique=True,
            postgresql_where=text("status IN ('queued', 'processing')"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    source_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    sha256_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True, nullable=False)
    status_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    pdf_bytes: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # NEW chroma document_id, set once chunks are successfully added (publish step).
    document_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    # OLD chroma document_id this job is replacing, if any (version-aware replacement).
    replaced_document_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    chunks_indexed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # JSON {"pages": [...], "extraction_method": "..."} once a review_ready/
    # indexing/published job's (possibly OCR'd) page texts are known. NULL
    # until then; never the full preview/knowledge-units/validation payload,
    # which is cheap to rebuild on demand from these page texts.
    extracted_pages_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )


class Announcement(Base):
    """Campus announcements shown in the student/faculty Announcements page."""

    __tablename__ = "announcements"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by_user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )