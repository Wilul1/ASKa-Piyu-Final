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
    chroma_where_for_audience,
    filter_chunks_for_audience,
    filter_unpublished_faq_chunks,
    index_published_article,
    infer_rag_audience_from_document,
    remove_published_article_index,
)
from app.services.chroma_store import RetrievedChunk, select_role_visible_hits
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
    content = payload["content"] or ""
    assert "## Question" not in content
    assert "## Answer" not in content
    assert "## Additional details" not in content

    session.refresh(ticket)
    assert ticket.kb_conversion_status == "draft"
    assert ticket.kb_article_id == payload["article_id"]

    article = session.get(PublishedArticle, payload["article_id"])
    assert article is not None
    assert article.published is False


def test_default_ticket_faq_body_is_answer_first_without_scaffold_headings():
    from types import SimpleNamespace

    from app.services.ticket_knowledge import (
        _default_article_content,
        strip_ticket_faq_scaffolding,
    )

    ticket = SimpleNamespace(
        original_question="How do I request an excuse slip?",
        description="I was absent for two days due to illness.",
    )
    body = _default_article_content(
        ticket,  # type: ignore[arg-type]
        "Submit a medical certificate and excuse slip form to OSAS within three days.",
    )
    assert body.startswith("Submit a medical certificate")
    assert "I was absent for two days due to illness." in body
    assert "## Question" not in body
    assert "## Answer" not in body

    legacy = (
        "## Question\n\nHow do I request an excuse slip?\n\n"
        "## Answer\n\nSubmit a medical certificate to OSAS."
    )
    cleaned = strip_ticket_faq_scaffolding(
        legacy, title="How do I request an excuse slip?"
    )
    assert "## Question" not in cleaned
    assert "## Answer" not in cleaned
    assert cleaned == "Submit a medical certificate to OSAS."


def test_convert_blocks_duplicate_of_published_pdf_article(session: Session):
    office = _office(session)
    student = _user(session, role="student")
    staff = _user(session, role="office", office_id=office.id)
    now = datetime.now(timezone.utc)
    session.add(
        PublishedArticle(
            id="art-id-validation",
            title="ID Validation",
            slug="id-validation",
            category="Student Services",
            summary="Citizen Charter service",
            content="## Service\n\nID Validation steps from the Citizen Charter.",
            office="Office of Student Affairs",
            source_filename="Laguna State Polytechnic University-CC_2026-1st Edition.pdf",
            audience="student",
            kb_origin="document",
            published=True,
            published_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    ticket = Ticket(
        id="TKT-KB-DUP",
        user_id=student.id,
        original_question="ID Validation",
        description="I already tried OSAS and still need help with my ID.",
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
                "Bring your Certificate of Registration and a valid government ID. "
                "Validation is processed within one working day at OSAS."
            ),
            created_at=now,
        )
    )
    session.commit()

    with pytest.raises(TicketKnowledgeError, match="already covers this topic"):
        convert_ticket_to_draft_article(
            session,
            ticket_id=ticket.id,
            actor=staff,
            title="ID Validation",
            publish=True,
        )

    from app.services.ticket_knowledge import find_duplicate_published_topic

    match = find_duplicate_published_topic(session, title="ID Validation")
    assert match is not None
    assert match.title == "ID Validation"
    assert find_duplicate_published_topic(session, title="Completely different topic") is None


def test_convert_allows_novel_faculty_manual_topic(session: Session, monkeypatch):
    office = _office(session)
    student = _user(session, role="student")
    staff = _user(session, role="office", office_id=office.id)
    now = datetime.now(timezone.utc)
    ticket = Ticket(
        id="TKT-KB-FAC",
        user_id=student.id,
        original_question="How is teaching load computed for full-time faculty?",
        description=(
            "I need clarification from the Faculty Manual about regular teaching load units."
        ),
        category="Faculty Policies",
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
                "Per the Faculty Manual, full-time faculty generally carry eighteen units "
                "per semester unless an overload is approved by the campus director."
            ),
            created_at=now,
        )
    )
    session.commit()

    def _fake_index(session_arg, article):
        article.rag_indexed = True
        article.rag_document_id = f"faq-{article.id}"
        article.chunk_count = 1
        session_arg.add(article)
        return 1

    monkeypatch.setattr(
        "app.services.article_rag_indexer.index_published_article",
        _fake_index,
    )

    payload = convert_ticket_to_draft_article(
        session,
        ticket_id=ticket.id,
        actor=staff,
        publish=True,
    )
    assert payload["published"] is True
    assert payload["kb_origin"] == "ticket_resolution"
    assert "teaching load" in (payload["title"] or "").casefold()
    article = session.get(PublishedArticle, payload["article_id"])
    assert article is not None
    assert article.published is True
    assert article.rag_indexed is True


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
    # Faculty KB/RAG is faculty-targeted (+ shared both), not student-only.
    assert student_chunk not in faculty_view
    assert faculty_chunk in faculty_view
    assert legacy_chunk not in faculty_view

    admin_view = filter_chunks_for_audience(chunks, "admin")
    assert len(admin_view) == 3

    assert chroma_where_for_audience("student") is None
    assert chroma_where_for_audience("admin") is None
    assert chroma_where_for_audience("faculty") == {"audience": {"$in": ["faculty", "both"]}}
    assert legacy_chunk in admin_view


def test_audience_filter_before_top_k_keeps_student_evidence():
    """Faculty-only hits must not empty the student window just because they ranked first."""
    faculty_pool = [
        RetrievedChunk(
            document_id=f"fac-{i}",
            title=f"Faculty Leave {i}",
            source_filename="faculty-manual.pdf",
            chunk_index=i,
            text="Faculty leave of absence and vacation service credits.",
            relevance_score=4.0 - (i * 0.05),
            original_score=0.86,
            reranked_score=4.0 - (i * 0.05),
            metadata={"audience": "faculty"},
        )
        for i in range(7)
    ]
    student_chunk = RetrievedChunk(
        document_id="stu-absences",
        title="Absences",
        source_filename="handbook.pdf",
        chunk_index=20,
        text="A student who incurs absences of more than 25% of the required number of class hours is dropped from the subject.",
        relevance_score=2.4,
        original_score=0.84,
        reranked_score=2.4,
        metadata={"audience": "student"},
    )
    faculty_only = RetrievedChunk(
        document_id="fac-secret",
        title="Faculty-only salary schedule",
        source_filename="faculty-manual.pdf",
        chunk_index=99,
        text="Faculty salary schedule is restricted.",
        relevance_score=1.1,
        original_score=0.81,
        reranked_score=1.1,
        metadata={"audience": "faculty"},
    )
    selected = select_role_visible_hits(
        faculty_pool + [student_chunk, faculty_only],
        user_role="student",
        top_k=7,
    )
    assert student_chunk in selected
    assert all((chunk.metadata or {}).get("audience") != "faculty" for chunk in selected)
    assert faculty_only not in selected
    faculty_selected = select_role_visible_hits(
        faculty_pool + [student_chunk, faculty_only],
        user_role="faculty",
        top_k=7,
    )
    assert student_chunk not in faculty_selected
    assert faculty_pool[0] in faculty_selected


def test_office_can_convert_and_publish_in_one_step(session: Session, monkeypatch):
    office = _office(session)
    student = _user(session, role="student")
    staff = _user(session, role="office", office_id=office.id)
    ticket = _resolved_ticket(session, office, student, staff)

    indexed: list[str] = []

    def _fake_index(db, article):
        indexed.append(article.id)
        article.rag_indexed = True
        article.rag_document_id = f"faq:{article.id}"
        article.chunk_count = 1
        db.add(article)
        return 1

    monkeypatch.setattr(
        "app.services.article_rag_indexer.index_published_article",
        _fake_index,
    )

    payload = convert_ticket_to_draft_article(
        session,
        ticket_id=ticket.id,
        actor=staff,
        publish=True,
    )
    assert payload["published"] is True
    assert payload["kb_conversion_status"] == "published"
    assert indexed == [payload["article_id"]]

    article = session.get(PublishedArticle, payload["article_id"])
    assert article is not None
    assert article.published is True
    assert article.rag_indexed is True
    session.refresh(ticket)
    assert ticket.kb_conversion_status == "published"


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
