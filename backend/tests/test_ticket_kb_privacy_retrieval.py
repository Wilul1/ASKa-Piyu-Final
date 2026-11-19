"""Privacy hardening and chatbot retrieval for ticket-derived KB articles."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db.base import Base
from app.models.db_models import (
    Office,
    PublishedArticle,
    Ticket,
    TicketAttachment,
    TicketReply,
    User,
)
from app.services.article_rag_indexer import (
    filter_unpublished_faq_chunks,
    index_published_article,
    faq_document_id,
)
from app.services.chroma_store import RetrievedChunk
from app.services.passwords import hash_password
from app.services.qa.question_answering import answer_qa_question
from app.services.ticket_knowledge import (
    TicketKnowledgeAccessError,
    TicketKnowledgeError,
    approve_ticket_kb_article,
    convert_ticket_to_draft_article,
    generate_article_from_resolved_ticket,
    redact_ticket_pii,
    reject_ticket_kb_article,
    retry_ticket_kb_generation,
    try_auto_generate_ticket_article,
)
from app.services.ticketing import resolve_ticket


_PII_FRAGMENTS = (
    "Maria Santos",
    "Mai",
    "maria.santos@lspu.edu.ph",
    "09171234567",
    "0917-123-4567",
    "+63 917 123 4567",
    "2023-445566",
    "2023 445566",
    "2023445566",
    "12 Mabini Street",
    "Brgy. San Jose",
    "Purok 3",
    "do not publish this",
    "maria_santos_cor.pdf",
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


@pytest.fixture(autouse=True)
def _lexical_citations(monkeypatch):
    monkeypatch.setattr(settings, "citation_verification_mode", "lexical")


def _office(session: Session) -> Office:
    office = Office(id="office-1", name="Office of the Registrar", description="Registrar")
    session.add(office)
    session.commit()
    return office


def _staff(session: Session, office: Office) -> User:
    user = User(
        id="user-office-1",
        email="office@lspu.test",
        password_hash=hash_password("password123"),
        full_name="Office User",
        role="office",
        office_id=office.id,
    )
    session.add(user)
    session.commit()
    return user


def _pii_student(session: Session) -> User:
    user = User(
        id="user-pii-student",
        email="maria.santos@lspu.edu.ph",
        password_hash=hash_password("password123"),
        full_name="Maria Santos",
        role="student",
        student_id="2023-445566",
    )
    session.add(user)
    session.commit()
    return user


def _plain_student(session: Session) -> User:
    user = User(
        id="user-student-1",
        email="student@lspu.test",
        password_hash=hash_password("password123"),
        full_name="Student User",
        role="student",
        student_id="STU-1",
    )
    session.add(user)
    session.commit()
    return user


def _ticket_with_thread(
    session: Session,
    *,
    office: Office,
    student: User,
    staff: User,
    ticket_id: str,
    question: str,
    student_messages: list[str],
    staff_messages: list[str],
    internal_notes: list[str] | None = None,
    status: str = "Resolved",
    attachment_name: str | None = None,
) -> Ticket:
    now = datetime.now(timezone.utc)
    ticket = Ticket(
        id=ticket_id,
        user_id=student.id,
        original_question=question,
        description=question,
        category="Student Services",
        assigned_office_id=office.id,
        assigned_office=office.name,
        priority="Medium",
        status=status,
        kb_conversion_status="none",
        created_at=now,
        updated_at=now,
        resolved_at=now if status == "Resolved" else None,
    )
    session.add(ticket)
    session.flush()
    for message in student_messages:
        session.add(
            TicketReply(
                ticket_id=ticket.id,
                sender_id=student.id,
                sender_role="student",
                sender_name=student.full_name,
                message=message,
                created_at=now,
            )
        )
    for message in internal_notes or []:
        session.add(
            TicketReply(
                ticket_id=ticket.id,
                sender_id=staff.id,
                sender_role=staff.role,
                sender_name=staff.full_name,
                message=message,
                is_internal=True,
                created_at=now,
            )
        )
    for message in staff_messages:
        session.add(
            TicketReply(
                ticket_id=ticket.id,
                sender_id=staff.id,
                sender_role=staff.role,
                sender_name=staff.full_name,
                message=message,
                created_at=now,
            )
        )
    if attachment_name:
        session.add(
            TicketAttachment(
                ticket_id=ticket.id,
                uploaded_by_id=student.id,
                original_filename=attachment_name,
                content_type="application/pdf",
                size_bytes=12,
                stored_filename=f"stored-{attachment_name}",
            )
        )
    session.commit()
    session.refresh(ticket)
    return ticket


def _payload_blob(payload: dict) -> str:
    return " ".join(str(payload.get(key) or "") for key in payload)


def _assert_no_pii(blob: str) -> None:
    for fragment in _PII_FRAGMENTS:
        if len(fragment) <= 3:
            assert not re.search(
                rf"(?<![A-Za-z0-9]){re.escape(fragment)}(?![A-Za-z0-9])",
                blob,
                flags=re.IGNORECASE,
            ), f"PII leaked: {fragment!r} in {blob!r}"
            continue
        assert fragment.casefold() not in blob.casefold(), f"PII leaked: {fragment!r} in {blob!r}"


class InMemoryFaqStore:
    """Test double for Chroma that stores FAQ chunks and scores by token overlap."""

    def __init__(self) -> None:
        self.docs: dict[str, list[dict]] = {}
        self.fail_add = False
        self.fail_delete = False

    @property
    def chunk_count(self) -> int:
        return max(sum(len(rows) for rows in self.docs.values()), 1)

    def add_document_chunks(self, **kwargs):
        if self.fail_add:
            raise RuntimeError("chroma write failed")
        document_id = kwargs["document_id"]
        rows = []
        for chunk in kwargs["chunks"]:
            meta = dict(getattr(chunk, "metadata", None) or {})
            meta.update(
                {
                    "document_id": document_id,
                    "title": kwargs["title"],
                    "source_filename": kwargs["source_filename"],
                    "chunk_index": chunk.chunk_index,
                    "chunk_id": f"{document_id}::{chunk.chunk_index}",
                    "article_type": "faq",
                }
            )
            for key, value in (kwargs.get("document_metadata") or {}).items():
                if isinstance(value, (str, int, float, bool)):
                    meta[f"doc_{key}"] = value
            rows.append({"text": chunk.text, "metadata": meta})
        self.docs[document_id] = rows
        return len(rows)

    def delete_document(self, document_id: str) -> None:
        if self.fail_delete:
            raise RuntimeError("chroma delete failed")
        self.docs.pop(document_id, None)

    def export_document(self, document_id: str):
        rows = self.docs.get(document_id)
        if not rows:
            return None
        return {
            "document_id": document_id,
            "ids": [row["metadata"]["chunk_id"] for row in rows],
            "documents": [row["text"] for row in rows],
            "metadatas": [row["metadata"] for row in rows],
        }

    def restore_document_export(self, export) -> None:
        document_id = export["document_id"]
        self.docs[document_id] = [
            {"text": text, "metadata": meta}
            for text, meta in zip(export["documents"], export["metadatas"])
        ]

    def search(self, query: str, *, top_k: int | None = None, raw_k=None, user_role=None):
        k = top_k or 5
        query_tokens = set(re.findall(r"[a-z0-9]+", query.lower()))
        scored: list[RetrievedChunk] = []
        for rows in self.docs.values():
            for row in rows:
                tokens = set(re.findall(r"[a-z0-9]+", row["text"].lower()))
                overlap = len(query_tokens & tokens)
                if overlap <= 0:
                    continue
                meta = row["metadata"]
                scored.append(
                    RetrievedChunk(
                        document_id=str(meta.get("document_id") or ""),
                        title=str(meta.get("title") or meta.get("source_section") or ""),
                        source_filename=str(meta.get("source_filename") or ""),
                        chunk_index=int(meta.get("chunk_index") or 0),
                        text=row["text"],
                        relevance_score=float(overlap),
                        metadata=meta,
                    )
                )
        scored.sort(key=lambda item: item.relevance_score, reverse=True)
        return scored[:k]


def test_adversarial_pii_redaction_covers_formatted_identifiers():
    cleaned = redact_ticket_pii(
        "Call me Mai. Email maria.santos@lspu.edu.ph, 0917-123-4567 or +63 917 123 4567. "
        "Student numbers 2023-445566, 2023 445566 and 2023445566. "
        "I live at 12 Mabini Street, Brgy. San Jose, Purok 3. "
        "Ask for Maria Santos.",
        identities=("Maria Santos", "Mai", "2023-445566", "maria.santos@lspu.edu.ph"),
    )
    _assert_no_pii(cleaned)
    assert "[email redacted]" in cleaned
    assert "[phone redacted]" in cleaned
    assert "[student id redacted]" in cleaned
    assert "[name redacted]" in cleaned
    assert "[address redacted]" in cleaned


def test_generated_article_redacts_every_field_and_skips_private_material(session: Session):
    office = _office(session)
    student = _pii_student(session)
    staff = _staff(session, office)
    ticket = _ticket_with_thread(
        session,
        office=office,
        student=student,
        staff=staff,
        ticket_id="TKT-PRIV-001",
        question="How can Maria Santos get an excuse slip?",
        student_messages=[
            "Hi, I am Maria Santos. Call me Mai. Student number 2023-445566 / 2023 445566. "
            "Email maria.santos@lspu.edu.ph, 0917-123-4567 or +63 917 123 4567. "
            "I live at 12 Mabini Street, Brgy. San Jose, Purok 3."
        ],
        internal_notes=["Internal: Maria Santos phone 09171234567, do not publish this."],
        staff_messages=[
            "Submit the excuse slip form and a medical certificate to OSAS "
            "within three working days of the absence. Keep a photocopy of both."
        ],
        attachment_name="maria_santos_cor.pdf",
    )
    payload = generate_article_from_resolved_ticket(
        session, ticket_id=ticket.id, actor=staff
    )
    blob = _payload_blob(payload)
    _assert_no_pii(blob)
    assert payload["published"] is False
    assert "excuse slip form" in (payload["content"] or "").casefold()
    article = session.get(PublishedArticle, payload["article_id"])
    assert article is not None
    assert article.source_filename == "Knowledge Base article"
    _assert_no_pii(
        " ".join(
            [
                article.title,
                article.content or "",
                article.summary or "",
                article.resolution_summary or "",
                article.slug or "",
                article.source_filename or "",
                article.generation_notes or "",
            ]
        )
    )
    assert "internal" not in (payload["content"] or "").casefold()
    assert "maria_santos_cor.pdf" not in (article.content or "")


def test_needs_review_draft_cannot_be_approved_until_edited(session: Session):
    office = _office(session)
    student = _plain_student(session)
    staff = _staff(session, office)
    ticket = _ticket_with_thread(
        session,
        office=office,
        student=student,
        staff=staff,
        ticket_id="TKT-PRIV-INC",
        question="What is the deadline for adding a subject?",
        student_messages=["Any update?"],
        staff_messages=["Hi", "I will check and get back to you later this week."],
    )
    payload = generate_article_from_resolved_ticket(
        session, ticket_id=ticket.id, actor=staff
    )
    assert payload["needs_manual_completion"] is True
    assert payload["kb_conversion_status"] == "needs_review"
    with pytest.raises(TicketKnowledgeError, match="complete"):
        approve_ticket_kb_article(session, ticket_id=ticket.id, actor=staff)

    edited = convert_ticket_to_draft_article(
        session,
        ticket_id=ticket.id,
        actor=staff,
        content=(
            "Adding a subject is allowed during the first two weeks of classes. "
            "File the add/drop form at the Registrar and have your adviser sign it."
        ),
    )
    assert edited["needs_manual_completion"] is False
    store = InMemoryFaqStore()
    with patch(
        "app.services.article_rag_indexer.get_knowledge_base_store",
        return_value=store,
    ):
        approved = approve_ticket_kb_article(session, ticket_id=ticket.id, actor=staff)
    assert approved["published"] is True
    assert approved["rag_indexed"] is True


def test_student_cannot_approve_and_retries_do_not_duplicate(session: Session):
    office = _office(session)
    student = _plain_student(session)
    staff = _staff(session, office)
    ticket = _ticket_with_thread(
        session,
        office=office,
        student=student,
        staff=staff,
        ticket_id="TKT-PRIV-PERM",
        question="How do I request a certificate of enrollment?",
        student_messages=["I need a certificate of enrollment."],
        staff_messages=[
            "Submit the certificate request form at the Registrar, pay the fee "
            "at the cashier, and present the receipt the next working day."
        ],
    )
    first = generate_article_from_resolved_ticket(
        session, ticket_id=ticket.id, actor=staff
    )
    second = generate_article_from_resolved_ticket(
        session, ticket_id=ticket.id, actor=staff
    )
    assert first["article_id"] == second["article_id"]
    with pytest.raises(TicketKnowledgeAccessError):
        approve_ticket_kb_article(session, ticket_id=ticket.id, actor=student)
    rows = (
        session.query(PublishedArticle)
        .filter(PublishedArticle.source_ticket_id == ticket.id)
        .all()
    )
    assert len(rows) == 1


def test_generation_failure_does_not_rollback_resolve_or_log_pii(
    session: Session, monkeypatch, caplog
):
    office = _office(session)
    student = _pii_student(session)
    staff = _staff(session, office)
    ticket = _ticket_with_thread(
        session,
        office=office,
        student=student,
        staff=staff,
        ticket_id="TKT-PRIV-FAIL",
        question="How can Maria Santos pay tuition?",
        student_messages=["Maria Santos 09171234567"],
        staff_messages=["Pay at the cashier with your assessment form and keep the receipt."],
        status="Open",
    )

    def _boom(*_args, **_kwargs):
        raise RuntimeError("generation backend unavailable for Maria Santos 09171234567")

    monkeypatch.setattr(
        "app.services.ticket_knowledge.generate_article_from_resolved_ticket",
        _boom,
    )
    with caplog.at_level(logging.ERROR):
        payload = resolve_ticket(session, ticket.id, staff)
    assert payload.status == "Resolved"
    assert payload.kb_conversion_status == "failed"
    log_text = caplog.text.casefold()
    assert "maria santos" not in log_text
    assert "09171234567" not in log_text
    assert "maria.santos@lspu.edu.ph" not in log_text


def test_unpublished_statuses_are_dropped_from_retrieval(session: Session, monkeypatch):
    office = _office(session)
    student = _plain_student(session)
    staff = _staff(session, office)
    ticket = _ticket_with_thread(
        session,
        office=office,
        student=student,
        staff=staff,
        ticket_id="TKT-PRIV-HIDE",
        question="How do I request a certificate of enrollment?",
        student_messages=["Need COE"],
        staff_messages=[
            "Submit the certificate request form at the Registrar, pay the fee "
            "at the cashier, and present the receipt the next working day."
        ],
    )
    payload = generate_article_from_resolved_ticket(
        session, ticket_id=ticket.id, actor=staff
    )
    article_id = payload["article_id"]
    store = InMemoryFaqStore()
    factory = sessionmaker(bind=session.get_bind(), autoflush=False, autocommit=False)
    monkeypatch.setattr(
        "app.services.article_rag_indexer.get_session_factory",
        lambda: factory,
    )
    monkeypatch.setattr(
        "app.services.article_rag_indexer.get_knowledge_base_store",
        lambda: store,
    )
    chunk = RetrievedChunk(
        document_id=faq_document_id(article_id),
        title="Draft FAQ",
        source_filename="Knowledge Base article",
        chunk_index=0,
        text="certificate request form",
        relevance_score=0.9,
        metadata={
            "article_id": article_id,
            "article_type": "faq",
            "kb_origin": "ticket_resolution",
            "audience": "student",
        },
    )
    assert filter_unpublished_faq_chunks([chunk]) == []

    approve_ticket_kb_article(session, ticket_id=ticket.id, actor=staff)
    kept = filter_unpublished_faq_chunks([chunk])
    assert [item.document_id for item in kept] == [faq_document_id(article_id)]

    reject_ticket_kb_article(session, ticket_id=ticket.id, actor=staff)
    assert filter_unpublished_faq_chunks([chunk]) == []


def test_resolve_approve_paraphrase_retrieve_cite_reject_and_index_failure(
    session: Session, monkeypatch
):
    office = _office(session)
    student = _plain_student(session)
    staff = _staff(session, office)
    ticket = _ticket_with_thread(
        session,
        office=office,
        student=student,
        staff=staff,
        ticket_id="TKT-PRIV-RAG",
        question="How do I request a certificate of enrollment?",
        student_messages=["I need a certificate of enrollment for scholarship."],
        staff_messages=[
            "Submit the certificate request form at the Registrar, pay the fee "
            "at the cashier, and present the official receipt. Release is the next "
            "working day."
        ],
        status="Open",
    )
    store = InMemoryFaqStore()
    factory = sessionmaker(bind=session.get_bind(), autoflush=False, autocommit=False)
    monkeypatch.setattr(
        "app.services.article_rag_indexer.get_knowledge_base_store",
        lambda: store,
    )
    monkeypatch.setattr(
        "app.services.qa.question_answering.get_knowledge_base_store",
        lambda: store,
    )
    monkeypatch.setattr(
        "app.services.article_rag_indexer.get_session_factory",
        lambda: factory,
    )

    resolved = resolve_ticket(session, ticket.id, staff)
    assert resolved.status == "Resolved"
    assert resolved.kb_conversion_status in {"draft", "needs_review"}
    article_id = resolved.kb_article_id
    assert article_id
    assert faq_document_id(article_id) not in store.docs

    def _ask(question: str):
        with patch(
            "app.services.qa.question_answering.generate_groq_answer",
            side_effect=lambda **kwargs: kwargs.get("context") or "No grounded answer.",
        ):
            return answer_qa_question(question, user_role="student")

    paraphrase = "I need a COE from the registrar, what form do I submit and where do I pay?"
    draft_result = _ask(paraphrase)
    assert faq_document_id(article_id) not in {
        source.get("document_id") for source in draft_result.sources
    }
    assert faq_document_id(article_id) not in {
        chunk.document_id for chunk in draft_result.retrieved_chunks
    }

    store.fail_add = True
    approved = approve_ticket_kb_article(session, ticket_id=ticket.id, actor=staff)
    assert approved["published"] is True
    assert approved["rag_indexed"] is False
    assert approved["generation_notes"] == "index_failed"
    session.refresh(ticket)
    assert ticket.status == "Resolved"
    assert ticket.kb_conversion_status == "published"
    assert faq_document_id(article_id) not in store.docs
    assert faq_document_id(article_id) not in {
        chunk.document_id for chunk in _ask(paraphrase).retrieved_chunks
    }

    store.fail_add = False
    retried = retry_ticket_kb_generation(session, ticket_id=ticket.id, actor=staff)
    assert retried["published"] is True
    assert retried["rag_indexed"] is True
    assert faq_document_id(article_id) in store.docs
    indexed_text = " ".join(row["text"] for row in store.docs[faq_document_id(article_id)])
    _assert_no_pii(indexed_text)
    for row in store.docs[faq_document_id(article_id)]:
        assert "Maria" not in str(row["metadata"].get("source_filename") or "")
        assert "TKT-" not in str(row["metadata"].get("source_filename") or "")

    paraphrased = _ask(paraphrase)
    assert faq_document_id(article_id) in {
        source.get("document_id") for source in paraphrased.sources
    } or any(
        "certificate" in (source.get("title") or "").casefold()
        for source in paraphrased.sources
    )
    assert "certificate request form" in paraphrased.answer.casefold()
    citation_blob = str(paraphrased.sources)
    assert "0917" not in citation_blob
    assert "maria.santos" not in citation_blob.casefold()
    assert "source_ticket_id" not in citation_blob

    article = session.get(PublishedArticle, article_id)
    assert article is not None
    article.content = (
        "Go to the Registrar window, file the certificate request form, pay at "
        "the cashier, then claim the printed certificate the next working day."
    )
    session.add(article)
    session.commit()
    index_published_article(session, article)
    session.commit()
    docs_after = store.docs[faq_document_id(article_id)]
    assert "registrar window" in " ".join(row["text"] for row in docs_after).casefold()
    assert list(store.docs.keys()).count(faq_document_id(article_id)) == 1

    reject_ticket_kb_article(session, ticket_id=ticket.id, actor=staff)
    assert faq_document_id(article_id) not in store.docs
    hidden = _ask(paraphrase)
    assert faq_document_id(article_id) not in {
        source.get("document_id") for source in hidden.sources
    }
