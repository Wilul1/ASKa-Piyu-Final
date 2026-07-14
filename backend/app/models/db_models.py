from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, ForeignKey, Integer, String, Text
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
        CheckConstraint("role IN ('student', 'office', 'admin')", name="ck_users_role"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    office_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("offices.id"), nullable=True)
    student_id: Mapped[str | None] = mapped_column(String(80), unique=True, nullable=True)
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
        CheckConstraint("priority IN ('High', 'Medium', 'Low')", name="ck_tickets_priority"),
        CheckConstraint("status IN ('Open', 'In Progress', 'Resolved', 'Closed')", name="ck_tickets_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True, nullable=False)
    original_question: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    category: Mapped[str] = mapped_column(String(120), nullable=False)
    assigned_office: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    priority: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="Open", index=True, nullable=False)
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_from_chatbot: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
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
    replies: Mapped[list["TicketReply"]] = relationship(back_populates="ticket", cascade="all, delete-orphan")


class TicketReply(Base):
    __tablename__ = "ticket_replies"
    __table_args__ = (
        CheckConstraint("sender_role IN ('student', 'office', 'admin')", name="ck_ticket_replies_sender_role"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    ticket_id: Mapped[str] = mapped_column(String(36), ForeignKey("tickets.id"), index=True, nullable=False)
    sender_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True, nullable=False)
    sender_role: Mapped[str] = mapped_column(String(20), nullable=False)
    sender_name: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    ticket: Mapped[Ticket] = relationship(back_populates="replies")
    sender: Mapped[User] = relationship(back_populates="replies", foreign_keys=[sender_id])


class PublishedArticle(Base):
    __tablename__ = "published_articles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    category: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    subcategory: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    office: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_document_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
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