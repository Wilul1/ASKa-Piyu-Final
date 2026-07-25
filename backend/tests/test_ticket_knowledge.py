"""Tests for ticket → draft FAQ → publish → Chroma self-improving loop."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.db_models import Office, PublishedArticle, Ticket, TicketReply, User
from app.services.article_rag_indexer import (
    FaqIndexWriteError,
    RagIndexOrphanError,
    cleanup_failed_faq_index,
    filter_chunks_for_audience,
    filter_unpublished_faq_chunks,
    index_published_article,
    infer_rag_audience_from_document,
    remove_published_article_index,
)
from app.services.chroma_store import RetrievedChunk
from app.services.passwords import hash_password
from app.services.ticket_knowledge import (
    TicketKnowledgeError,
    convert_ticket_to_draft_article,
    ensure_unique_article_slug,
    infer_audience_from_text,
)


@pytest.fixture()
def session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = factory()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def _office(session: Session) -> Office:
    office = Office(id="office-1", name="Office of the Registrar", description="Registrar")
    session.add(office)
    session.commit()
    return office


def _user(session: Session, *, role: str, office_id: str | None = None) -> User:
    user = User(
        id=f"user-{role}-{office_id or 'x'}",
        email=f"{role}@lspu.test",
        password_hash=hash_password("password123"),
        full_name=f"{role.title()} User",
        role=role,
        office_id=office_id,
        student_id="STU-1" if role == "student" else None,
    )
    session.add(user)
    session.commit()
    return user


def _resolved_ticket(session: Session, office: Office, student: User, staff: User) -> Ticket:
    now = datetime.now(timezone.utc)
    ticket = Ticket(
        id="TKT-KB-001",
        user_id=student.id,
        original_question="How do I validate my student ID?",
        description="Freshman ID validation process",
        category="Student Services",
        assigned_office_id=office.id,
        assigned_office=office.name,
        priority="Medium",
        status="Resolved",
        kb_conversion_status="none",
        created_at=now,
        updated_at=now,
        resolved_at=now,
    )
    session.add(ticket)
    session.flush()
    session.add(
        TicketReply(
            ticket_id=ticket.id,
            sender_id=staff.id,
            sender_role=staff.role,
            sender_name=staff.full_name,
            message=(
                "Bring your Certificate of Registration and a valid government ID to OSAS. "
                "Validation is processed within one working day."
            ),
            created_at=now,
        )
    )
    session.commit()
    session.refresh(ticket)
    return ticket


def test_infer_audience_for_faculty_topics():
    assert infer_audience_from_text("How is teaching load assigned?") == "faculty"
    assert infer_audience_from_text("How do I enroll?") == "student"
    assert infer_audience_from_text("Where is the main campus?") == "both"
    assert infer_audience_from_text("General office hours question") == "student"


def test_infer_rag_audience_from_document_filename():
    assert (
        infer_rag_audience_from_document(filename="LSPU_Faculty_Manual_2024.pdf")
        == "faculty"
    )
    assert infer_rag_audience_from_document(filename="LSPU Faculty Guide.pdf") == "faculty"
    assert (
        infer_rag_audience_from_document(
            filename="policies.pdf", document_type="faculty_manual"
        )
        == "faculty"
    )
    assert (
        infer_rag_audience_from_document(filename="Student_Handbook.pdf") == "student"
    )
    assert (
        infer_rag_audience_from_document(filename="Citizens_Charter.pdf") == "both"
    )
    assert infer_rag_audience_from_document(filename="memo.pdf") == "student"


def test_convert_ticket_creates_draft_faq(session: Session):
    office = _office(session)
    student = _user(session, role="student")
    staff = _user(session, role="office", office_id=office.id)
    ticket = _resolved_ticket(session, office, student, staff)

    payload = convert_ticket_to_draft_article(session, ticket_id=ticket.id, actor=staff)
    assert payload["published"] is False
    assert payload["kb_origin"] == "ticket_resolution"
    assert payload["source_ticket_id"] == ticket.id
    assert "Certificate of Registration" in (payload["content"] or "")

    session.refresh(ticket)
    assert ticket.kb_conversion_status == "draft"
    assert ticket.kb_article_id == payload["article_id"]

    article = session.get(PublishedArticle, payload["article_id"])
    assert article is not None
    assert article.published is False


def test_convert_requires_staff_reply(session: Session):
    office = _office(session)
    student = _user(session, role="student")
    staff = _user(session, role="office", office_id=office.id)
    now = datetime.now(timezone.utc)
    ticket = Ticket(
        id="TKT-KB-002",
        user_id=student.id,
        original_question="Where is the registrar?",
        description="",
        category="General",
        assigned_office_id=office.id,
        assigned_office=office.name,
        priority="Low",
        status="Resolved",
        kb_conversion_status="none",
        created_at=now,
        updated_at=now,
        resolved_at=now,
    )
    session.add(ticket)
    session.commit()

    with pytest.raises(TicketKnowledgeError):
        convert_ticket_to_draft_article(session, ticket_id=ticket.id, actor=staff)


def test_audience_filter_keeps_legacy_and_role_chunks():
    student_chunk = RetrievedChunk(
        document_id="a",
        title="Student FAQ",
        source_filename="faq.pdf",
        chunk_index=0,
        text="student id validation",
        relevance_score=0.9,
        metadata={"audience": "student"},
    )
    faculty_chunk = RetrievedChunk(
        document_id="b",
        title="Faculty FAQ",
        source_filename="faq.pdf",
        chunk_index=1,
        text="teaching load",
        relevance_score=0.9,
        metadata={"audience": "faculty"},
    )
    legacy_chunk = RetrievedChunk(
        document_id="c",
        title="Handbook",
        source_filename="handbook.pdf",
        chunk_index=2,
        text="legacy policy",
        relevance_score=0.8,
        metadata={},
    )
    chunks = [student_chunk, faculty_chunk, legacy_chunk]
    student_view = filter_chunks_for_audience(chunks, "student")
    assert student_chunk in student_view
    assert faculty_chunk not in student_view
    # Untagged legacy corpora are student-visible only (not faculty-secret).
    assert legacy_chunk in student_view

    faculty_view = filter_chunks_for_audience(chunks, "faculty")
    # Faculty can read student handbook content plus faculty-only.
    assert student_chunk in faculty_view
    assert faculty_chunk in faculty_view
    assert legacy_chunk in faculty_view

    admin_view = filter_chunks_for_audience(chunks, "admin")
    assert len(admin_view) == 3
    assert legacy_chunk in admin_view


def test_publish_indexes_and_unpublish_removes_chroma(session: Session, monkeypatch):
    office = _office(session)
    student = _user(session, role="student")
    staff = _user(session, role="office", office_id=office.id)
    admin = _user(session, role="admin")
    ticket = _resolved_ticket(session, office, student, staff)
    payload = convert_ticket_to_draft_article(session, ticket_id=ticket.id, actor=staff)
    article = session.get(PublishedArticle, payload["article_id"])
    assert article is not None

    added: list[str] = []
    deleted: list[str] = []

    class _FakeStore:
        def __init__(self) -> None:
            self.docs: dict[str, list] = {}

        def export_document(self, document_id: str):
            chunks = self.docs.get(document_id)
            if not chunks:
                return None
            return {
                "document_id": document_id,
                "ids": [f"{document_id}::{i}" for i in range(len(chunks))],
                "documents": [c["text"] for c in chunks],
                "metadatas": [c.get("metadata") or {} for c in chunks],
            }

        def restore_document_export(self, export):
            document_id = export["document_id"]
            self.docs[document_id] = [
                {"text": text, "metadata": meta}
                for text, meta in zip(export["documents"], export["metadatas"])
            ]

        def delete_document(self, document_id: str) -> None:
            deleted.append(document_id)
            self.docs.pop(document_id, None)

        def add_document_chunks(self, **kwargs):
            document_id = kwargs["document_id"]
            added.append(document_id)
            self.docs[document_id] = [
                {"text": chunk.text, "metadata": getattr(chunk, "metadata", {}) or {}}
                for chunk in kwargs["chunks"]
            ]
            return len(kwargs["chunks"])

    store = _FakeStore()
    monkeypatch.setattr(
        "app.services.article_rag_indexer.get_knowledge_base_store",
        lambda: store,
    )

    article.published = True
    count = index_published_article(session, article)
    session.commit()
    assert count >= 1
    assert article.rag_indexed is True
    assert added and added[0].startswith("faq:")

    session.refresh(ticket)
    assert ticket.kb_conversion_status == "published"

    article.published = False
    remove_published_article_index(session, article)
    from app.services.ticket_knowledge import sync_ticket_kb_status

    sync_ticket_kb_status(session, article)
    session.commit()
    assert article.rag_indexed is False
    assert deleted
    session.refresh(ticket)
    assert ticket.kb_conversion_status == "draft"
    assert admin.role == "admin"


def test_reindex_restores_chroma_backup_when_add_fails(session: Session, monkeypatch):
    office = _office(session)
    student = _user(session, role="student")
    staff = _user(session, role="office", office_id=office.id)
    ticket = _resolved_ticket(session, office, student, staff)
    payload = convert_ticket_to_draft_article(session, ticket_id=ticket.id, actor=staff)
    article = session.get(PublishedArticle, payload["article_id"])
    assert article is not None
    article.published = True
    article.content = (
        "Bring your Certificate of Registration and a valid government ID to OSAS. "
        "Validation is processed within one working day."
    )
    session.commit()

    class _RestoreStore:
        def __init__(self) -> None:
            self.docs: dict[str, str] = {"faq:seed": "old chunk"}
            self.fail_add = False

        def export_document(self, document_id: str):
            text = self.docs.get(document_id)
            if text is None:
                return None
            return {
                "document_id": document_id,
                "ids": [f"{document_id}::0"],
                "documents": [text],
                "metadatas": [{"audience": "student"}],
            }

        def restore_document_export(self, export):
            self.docs[export["document_id"]] = export["documents"][0]

        def delete_document(self, document_id: str) -> None:
            self.docs.pop(document_id, None)

        def add_document_chunks(self, **kwargs):
            if self.fail_add:
                raise RuntimeError("chroma write failed")
            self.docs[kwargs["document_id"]] = kwargs["chunks"][0].text
            return len(kwargs["chunks"])

    store = _RestoreStore()
    document_id = f"faq:{article.id}"
    monkeypatch.setattr(
        "app.services.article_rag_indexer.get_knowledge_base_store",
        lambda: store,
    )

    # First successful index
    index_published_article(session, article)
    session.commit()
    assert document_id in store.docs
    previous_text = store.docs[document_id]

    # Re-index failure must restore previous vectors
    store.fail_add = True
    article.content = (
        "Bring your Certificate of Registration and a valid government ID to OSAS. "
        "Validation is processed within one working day. Updated answer text."
    )
    with pytest.raises(FaqIndexWriteError, match="chroma write failed") as caught:
        index_published_article(session, article)
    assert caught.value.previous_vectors_restored is True
    assert store.docs.get(document_id) == previous_text
    # Caller cleanup must not wipe the restored vectors.
    cleanup_failed_faq_index(caught.value, article.id)
    assert store.docs.get(document_id) == previous_text


def test_reindex_aborts_when_export_fails_without_deleting(session: Session, monkeypatch):
    office = _office(session)
    student = _user(session, role="student")
    staff = _user(session, role="office", office_id=office.id)
    ticket = _resolved_ticket(session, office, student, staff)
    payload = convert_ticket_to_draft_article(session, ticket_id=ticket.id, actor=staff)
    article = session.get(PublishedArticle, payload["article_id"])
    assert article is not None
    article.published = True
    article.content = (
        "Bring your Certificate of Registration and a valid government ID to OSAS. "
        "Validation is processed within one working day for enrolled students."
    )
    session.commit()

    class _ExportFailStore:
        def __init__(self) -> None:
            self.deleted: list[str] = []

        def export_document(self, document_id: str):
            raise RuntimeError("export boom")

        def delete_document(self, document_id: str) -> None:
            self.deleted.append(document_id)

        def add_document_chunks(self, **kwargs):
            raise AssertionError("add should not run when export fails")

    store = _ExportFailStore()
    monkeypatch.setattr(
        "app.services.article_rag_indexer.get_knowledge_base_store",
        lambda: store,
    )
    with pytest.raises(RuntimeError, match="snapshot existing Chroma chunks"):
        index_published_article(session, article)
    assert store.deleted == []


def test_filter_unpublished_faq_chunks_drops_orphans(session: Session, monkeypatch):
    published = PublishedArticle(
        id="art-pub",
        title="Published FAQ",
        slug="published-faq",
        category="Student Services",
        content="Published answer body long enough.",
        published=True,
        rag_indexed=True,
        rag_document_id="faq:art-pub",
    )
    draft = PublishedArticle(
        id="art-draft",
        title="Draft FAQ",
        slug="draft-faq",
        category="Student Services",
        content="Draft answer body long enough.",
        published=False,
        rag_indexed=False,
    )
    session.add_all([published, draft])
    session.commit()

    from sqlalchemy.orm import sessionmaker

    factory = sessionmaker(bind=session.get_bind(), autoflush=False, autocommit=False)
    monkeypatch.setattr(
        "app.services.article_rag_indexer.get_session_factory",
        lambda: factory,
    )

    chunks = [
        RetrievedChunk(
            document_id="faq:art-pub",
            title="Published FAQ",
            source_filename="ticket",
            chunk_index=0,
            text="published",
            relevance_score=0.9,
            metadata={"article_id": "art-pub", "article_type": "faq", "audience": "both"},
        ),
        RetrievedChunk(
            document_id="faq:art-draft",
            title="Draft FAQ",
            source_filename="ticket",
            chunk_index=0,
            text="draft orphan",
            relevance_score=0.8,
            metadata={"article_id": "art-draft", "article_type": "faq", "audience": "both"},
        ),
        RetrievedChunk(
            document_id="faq:missing",
            title="Gone",
            source_filename="ticket",
            chunk_index=0,
            text="missing row",
            relevance_score=0.7,
            metadata={"article_id": "missing", "article_type": "faq", "audience": "both"},
        ),
        RetrievedChunk(
            document_id="handbook-doc",
            title="Handbook",
            source_filename="handbook.pdf",
            chunk_index=0,
            text="policy",
            relevance_score=0.6,
            metadata={"audience": "student"},
        ),
    ]

    kept = filter_unpublished_faq_chunks(chunks)
    assert [c.document_id for c in kept] == ["faq:art-pub", "handbook-doc"]


def test_ensure_unique_article_slug_suffixes_collisions(session: Session):
    session.add(
        PublishedArticle(
            title="Enrollment Steps",
            slug="enrollment-steps",
            category="Academic Policies",
            content="Existing",
            published=False,
        )
    )
    session.commit()
    assert ensure_unique_article_slug(session, "Enrollment Steps") == "enrollment-steps-2"
    assert (
        ensure_unique_article_slug(session, "Enrollment Steps", exclude_id="x")
        == "enrollment-steps-2"
    )


def test_reindex_marks_rag_stale_when_restore_fails(session: Session, monkeypatch):
    office = _office(session)
    student = _user(session, role="student")
    staff = _user(session, role="office", office_id=office.id)
    ticket = _resolved_ticket(session, office, student, staff)
    payload = convert_ticket_to_draft_article(session, ticket_id=ticket.id, actor=staff)
    article = session.get(PublishedArticle, payload["article_id"])
    assert article is not None
    article.published = True
    article.rag_indexed = True
    article.rag_document_id = f"faq:{article.id}"
    article.content = (
        "Bring your Certificate of Registration and a valid government ID to OSAS. "
        "Validation is processed within one working day."
    )
    session.commit()
    article_id = article.id

    class _BrokenRestoreStore:
        def export_document(self, document_id: str):
            return {
                "document_id": document_id,
                "ids": [f"{document_id}::0"],
                "documents": ["old"],
                "metadatas": [{"audience": "student"}],
            }

        def restore_document_export(self, export):
            raise RuntimeError("restore failed")

        def delete_document(self, document_id: str) -> None:
            return None

        def add_document_chunks(self, **kwargs):
            raise RuntimeError("chroma write failed")

    from sqlalchemy.orm import sessionmaker

    factory = sessionmaker(bind=session.get_bind(), autoflush=False, autocommit=False)
    monkeypatch.setattr(
        "app.services.article_rag_indexer.get_knowledge_base_store",
        lambda: _BrokenRestoreStore(),
    )
    monkeypatch.setattr(
        "app.services.article_rag_indexer.get_session_factory",
        lambda: factory,
    )

    with pytest.raises(RagIndexOrphanError):
        index_published_article(session, article)

    # Caller may roll back; durable stale flags must still be committed.
    session.rollback()
    stale = session.get(PublishedArticle, article_id)
    assert stale is not None
    assert stale.rag_indexed is False
    assert stale.rag_document_id is None
