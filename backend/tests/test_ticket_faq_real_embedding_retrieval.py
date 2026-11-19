"""Isolated real-E5 retrieval validation for ticket-derived FAQ articles.

Uses the production embedding implementation (intfloat/multilingual-e5-small)
against a temporary Chroma collection. Never writes ./data/chroma or
aska_knowledge_base.
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db.base import Base
from app.models.db_models import Office, PublishedArticle, Ticket, TicketReply, User
from app.services.article_rag_indexer import faq_document_id, index_published_article
from app.services.embeddings import (
    DEFAULT_EMBEDDING_MODEL,
    EXPECTED_EMBEDDING_DIMENSION,
    E5EmbeddingFunction,
    get_embedding_function,
)
from app.services.passwords import hash_password
from app.services.qa.question_answering import EmptyKnowledgeBaseError, answer_qa_question
from app.services.ticket_knowledge import (
    approve_ticket_kb_article,
    generate_article_from_resolved_ticket,
    reject_ticket_kb_article,
    retry_ticket_kb_generation,
)
from app.services.ticketing import resolve_ticket


PRODUCTION_COLLECTION = "aska_knowledge_base"
PRODUCTION_CHROMA_DIR_NAMES = {"chroma"}
_OLD_EMBED_SENTINEL = "ORANGE-RECEIPT-TOKEN-A1"
_NEW_EMBED_SENTINEL = "BLUE-VALIDATION-TOKEN-B2"

FAQ_CORPUS: list[dict[str, Any]] = [
    {
        "key": "coe",
        "office": "Office of the Registrar",
        "question": "How do I request a Certificate of Enrollment?",
        "answer": (
            "Go to the Office of the Registrar and fill out the Certificate of "
            "Enrollment request form. Pay the documentary stamp fee at the cashier, "
            "then present the official receipt at the Registrar releasing window. "
            "The Certificate of Enrollment is released the next working day."
        ),
        "queries": [
            ("How do I request a Certificate of Enrollment?", "exact"),
            (
                "I need a COE from the registrar, what form do I submit and where do I pay?",
                "paraphrase",
            ),
            ("Paano magpa-request ng Certificate of Enrollment sa registrar?", "taglish"),
            ("Where can I get proof that I am currently enrolled?", "same_intent"),
        ],
    },
    {
        "key": "tor",
        "office": "Office of the Registrar",
        "question": "How do I request a Transcript of Records?",
        "answer": (
            "Alumni and currently enrolled students request a Transcript of Records "
            "at the Registrar. Submit the TOR application form, a valid ID, and pay "
            "the transcript fee at the cashier. Release takes three working days after "
            "the official receipt is presented."
        ),
        "queries": [
            ("How do I request a Transcript of Records?", "exact"),
            ("What are the steps to get my TOR as an alumnus?", "paraphrase"),
            ("Paano kumuha ng TOR o transcript of records sa registrar?", "taglish"),
            ("I need a copy of my complete grades for employment, how do I apply?", "same_intent"),
        ],
    },
    {
        "key": "enrollment",
        "office": "Office of the Registrar",
        "question": "How do I add or drop subjects during enrollment?",
        "answer": (
            "Adding or dropping subjects is allowed only during the adjustment period. "
            "Secure the adding/dropping form from the Registrar, obtain the instructor "
            "and dean's signatures, then return the form to the Registrar for encoding. "
            "Late adding after the adjustment period is not accepted."
        ),
        "queries": [
            ("How do I add or drop subjects during enrollment?", "exact"),
            ("Can I still change my enlisted subjects during the adjustment period?", "paraphrase"),
            ("Paano mag-add or mag-drop ng subject pag enrollment?", "taglish"),
            ("Where do I file an adding form if I want another class?", "same_intent"),
        ],
    },
    {
        "key": "clearance",
        "office": "Office of the Registrar",
        "question": "How do I process semester clearance?",
        "answer": (
            "Semester clearance starts at your college. Get the clearance form, then "
            "secure stamps from the library, accounting, and the Office of Student "
            "Affairs. Return the completed clearance to the Registrar. A hold remains "
            "on grades until all offices have signed."
        ),
        "queries": [
            ("How do I process semester clearance?", "exact"),
            ("Which offices need to stamp my clearance before grades are released?", "paraphrase"),
            ("Paano magpaclearance para makuha grades ko?", "taglish"),
            ("What is the procedure if accounting still has a hold on my account?", "same_intent"),
        ],
    },
    {
        "key": "scholarship",
        "office": "Office of Student Affairs and Services",
        "question": "How do I apply for scholarship and financial assistance?",
        "answer": (
            "Scholarship and financial assistance applications are filed at the Office "
            "of Student Affairs and Services. Submit a Certificate of Registration, "
            "certificate of good moral character, and the accomplished scholarship "
            "form. OSAS evaluates documents and posts the list of qualified grantees."
        ),
        "queries": [
            ("How do I apply for scholarship and financial assistance?", "exact"),
            ("What documents does OSAS need for a CHED scholarship application?", "paraphrase"),
            ("Saan mag-apply ng scholarship at anong papers ang kailangan?", "taglish"),
            ("Where do I submit requirements for student financial assistance?", "same_intent"),
        ],
    },
    {
        "key": "student_id",
        "office": "Business Affairs Office",
        "question": "How do I process a new student ID?",
        "answer": (
            "New student ID processing is done at the Business Affairs Office. Bring "
            "your Certificate of Registration, one 2x2 photo with white background, "
            "and the official receipt for the ID fee. Claim the ID at the BAO window "
            "after three working days."
        ),
        "queries": [
            ("How do I process a new student ID?", "exact"),
            ("Where do I get my school ID and what photo should I bring?", "paraphrase"),
            ("Paano magprocess ng student ID sa BAO?", "taglish"),
            ("I am a freshman, how do I claim my campus identification card?", "same_intent"),
        ],
    },
]

CONFUSION_PROBES: list[dict[str, Any]] = [
    {
        "text": "How do I request a Certificate of Good Moral Character?",
        "must_not_rank1": "coe",
        "reason": "similar certificate request, different office document",
    },
    {
        "text": "Paano kumuha ng diploma after graduation?",
        "must_not_rank1": "tor",
        "reason": "registrar credential, not a transcript",
    },
    {
        "text": "What time does the university library close on weekdays?",
        "must_not_rank1": "clearance",
        "reason": "library hours vs clearance stamps",
    },
    {
        "text": "How do I pay my unpaid tuition balance at the cashier?",
        "must_not_rank1": "enrollment",
        "reason": "cashier payment vs adding/dropping subjects",
    },
]


def _assert_isolated_chroma_target() -> None:
    persist = Path(settings.chroma_persist_dir).resolve()
    collection = (settings.chroma_collection_name or "").strip()
    production_persist = (Path(__file__).resolve().parents[1] / "data" / "chroma").resolve()
    assert collection != PRODUCTION_COLLECTION
    assert collection.startswith("ticket_faq_e5_eval_")
    assert persist != production_persist
    assert persist.name not in PRODUCTION_CHROMA_DIR_NAMES
    assert (settings.chroma_backend or "local").strip().lower() == "local"


@pytest.fixture(scope="module")
def isolated_e5_store():
    pytest.importorskip("sentence_transformers")
    from app.services import chroma_store as chroma_store_mod
    from app.services.chroma_store import get_knowledge_base_store

    original_persist_dir = settings.chroma_persist_dir
    tmp = Path(tempfile.mkdtemp(prefix="ticket_faq_e5_eval_"))
    collection_name = f"ticket_faq_e5_eval_{uuid4().hex[:12]}"
    previous = {
        "chroma_persist_dir": settings.chroma_persist_dir,
        "chroma_collection_name": settings.chroma_collection_name,
        "chroma_backend": settings.chroma_backend,
        "embedding_backend": settings.embedding_backend,
        "resolve": chroma_store_mod._resolve_embedding_function,
    }
    settings.chroma_persist_dir = str(tmp)
    settings.chroma_collection_name = collection_name
    settings.chroma_backend = "local"
    settings.embedding_backend = "local"
    get_embedding_function.cache_clear()
    chroma_store_mod._resolve_embedding_function = lambda: get_embedding_function()
    get_knowledge_base_store.cache_clear()
    _assert_isolated_chroma_target()
    try:
        embedding_fn = get_embedding_function()
        assert isinstance(embedding_fn, E5EmbeddingFunction)
        store = get_knowledge_base_store()
        store.reset_collection()
        yield {
            "store": store,
            "persist_dir": tmp,
            "collection_name": collection_name,
            "embedding_fn": embedding_fn,
        }
    finally:
        get_knowledge_base_store.cache_clear()
        get_embedding_function.cache_clear()
        chroma_store_mod._resolve_embedding_function = previous["resolve"]
        settings.chroma_persist_dir = previous["chroma_persist_dir"]
        settings.chroma_collection_name = previous["chroma_collection_name"]
        settings.chroma_backend = previous["chroma_backend"]
        settings.embedding_backend = previous["embedding_backend"]
        assert settings.chroma_persist_dir == original_persist_dir


@pytest.fixture()
def e5_store(isolated_e5_store):
    store = isolated_e5_store["store"]
    store.reset_collection()
    _assert_isolated_chroma_target()
    return isolated_e5_store


@pytest.fixture()
def session(e5_store, monkeypatch) -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr("app.services.article_rag_indexer.get_session_factory", lambda: factory)
    monkeypatch.setattr(settings, "citation_verification_mode", "lexical")
    db = factory()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def _seed_actors(session: Session) -> tuple[Office, User, User, User]:
    office = Office(id="office-reg", name="Office of the Registrar", description="Registrar")
    session.add(office)
    session.flush()
    student = User(
        id="user-student-e5",
        email="student-e5@lspu.test",
        password_hash=hash_password("password123"),
        full_name="Student User",
        role="student",
        student_id="2026-E5",
    )
    staff = User(
        id="user-office-e5",
        email="office-e5@lspu.test",
        password_hash=hash_password("password123"),
        full_name="Office User",
        role="office",
        office_id=office.id,
    )
    admin = User(
        id="user-admin-e5",
        email="admin-e5@lspu.test",
        password_hash=hash_password("password123"),
        full_name="Admin User",
        role="admin",
    )
    session.add_all([student, staff, admin])
    session.commit()
    return office, student, staff, admin


def _ticket(
    session: Session,
    *,
    office: Office,
    student: User,
    staff: User,
    ticket_id: str,
    question: str,
    staff_answer: str,
    status: str = "Resolved",
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
    session.add(
        TicketReply(
            ticket_id=ticket.id,
            sender_id=staff.id,
            sender_role=staff.role,
            sender_name=staff.full_name,
            message=staff_answer,
            created_at=now,
        )
    )
    session.commit()
    session.refresh(ticket)
    return ticket


def _article_ids_from_chunks(chunks: list) -> list[str]:
    ids: list[str] = []
    for chunk in chunks:
        meta = getattr(chunk, "metadata", None) or {}
        article_id = str(meta.get("article_id") or "").strip()
        document_id = str(getattr(chunk, "document_id", "") or meta.get("document_id") or "")
        if not article_id and document_id.startswith("faq:"):
            article_id = document_id[4:]
        if article_id:
            ids.append(article_id)
    return ids


def _search(store, question: str, *, top_k: int = 5):
    return store.search(question, top_k=top_k, user_role="student")


def _ask(question: str):
    with patch(
        "app.services.qa.question_answering.generate_groq_answer",
        side_effect=lambda **kwargs: kwargs.get("context") or "No grounded answer.",
    ):
        return answer_qa_question(question, user_role="student")


def _source_doc_ids(result) -> set[str]:
    return {str(source.get("document_id") or "") for source in (result.sources or [])}


def _selected_doc_ids(result) -> set[str]:
    selected = set()
    for chunk in result.retrieved_chunks or []:
        if chunk.get("selected_for_context"):
            selected.add(str(chunk.get("document_id") or ""))
    if selected:
        return selected
    return {str(chunk.get("document_id") or "") for chunk in (result.retrieved_chunks or [])}


def _publish_case(session: Session, *, admin: User, student: User, office: Office, case: dict) -> PublishedArticle:
    ticket = _ticket(
        session,
        office=office,
        student=student,
        staff=admin,
        ticket_id=f"TKT-E5-{case['key']}-{uuid4().hex[:8]}",
        question=case["question"],
        staff_answer=case["answer"],
        status="Open",
    )
    ticket.assigned_office = case["office"]
    session.add(ticket)
    session.commit()
    resolve_ticket(session, ticket.id, admin)
    generate_article_from_resolved_ticket(session, ticket_id=ticket.id, actor=admin)
    approve_ticket_kb_article(session, ticket_id=ticket.id, actor=admin)
    article = (
        session.query(PublishedArticle)
        .filter(PublishedArticle.source_ticket_id == ticket.id)
        .one()
    )
    assert article.published is True
    assert article.rag_indexed is True
    return article


def test_isolated_store_uses_production_e5_not_minilm(e5_store):
    from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

    embedding_fn = e5_store["embedding_fn"]
    assert isinstance(embedding_fn, E5EmbeddingFunction)
    assert not isinstance(embedding_fn, DefaultEmbeddingFunction)
    assert (embedding_fn._model_name or DEFAULT_EMBEDDING_MODEL) == "intfloat/multilingual-e5-small"
    assert (settings.embedding_backend or "local").strip().lower() == "local"
    assert settings.rag_top_k == 5
    vector = embedding_fn.embed_query(["How do I request a Transcript of Records?"])[0]
    assert len(vector) == EXPECTED_EMBEDDING_DIMENSION
    _assert_isolated_chroma_target()


def test_ticket_faq_real_e5_lifecycle_retrieve_cite_edit_reject_retry(session: Session, e5_store):
    store = e5_store["store"]
    office, student, staff, admin = _seed_actors(session)

    distractor = _publish_case(
        session,
        admin=admin,
        student=student,
        office=office,
        case=FAQ_CORPUS[-1],
    )
    distractor_doc = faq_document_id(distractor.id)

    ticket = _ticket(
        session,
        office=office,
        student=student,
        staff=staff,
        ticket_id=f"TKT-E5-LIFE-{uuid4().hex[:8]}",
        question="How do I request a Certificate of Enrollment?",
        staff_answer=(
            "Submit the Certificate of Enrollment request form at the Registrar. "
            f"Pay at the cashier and keep {_OLD_EMBED_SENTINEL}. "
            "Release is the next working day after the official receipt is presented."
        ),
        status="Open",
    )
    resolved = resolve_ticket(session, ticket.id, staff)
    assert resolved.status == "Resolved"
    payload = generate_article_from_resolved_ticket(session, ticket_id=ticket.id, actor=staff)
    article_id = payload["article_id"]
    article_doc = faq_document_id(article_id)
    assert payload["published"] is False
    assert payload.get("rag_indexed") in {False, None, 0}
    assert store.export_document(article_doc) is None

    draft_hits = _search(store, "How do I request a Certificate of Enrollment?")
    assert article_id not in _article_ids_from_chunks(draft_hits)
    draft_qa = _ask("I need a COE from the registrar, what form do I submit?")
    assert article_doc not in _source_doc_ids(draft_qa)
    assert article_doc not in _selected_doc_ids(draft_qa)

    original_add = store.add_document_chunks

    def _fail_add(**kwargs):
        raise RuntimeError("simulated chroma write failure")

    store.add_document_chunks = _fail_add
    failed = approve_ticket_kb_article(session, ticket_id=ticket.id, actor=staff)
    assert failed["published"] is True
    assert failed["rag_indexed"] is False
    assert failed.get("generation_notes") == "index_failed"
    assert store.export_document(article_doc) is None
    session.refresh(ticket)
    assert ticket.status == "Resolved"

    store.add_document_chunks = original_add
    retried = retry_ticket_kb_generation(session, ticket_id=ticket.id, actor=staff)
    assert retried["published"] is True
    assert retried["rag_indexed"] is True
    exported = store.export_document(article_doc)
    assert exported is not None
    assert len(exported.get("ids") or []) >= 1
    indexed_blob = " ".join(exported.get("documents") or [])
    assert _OLD_EMBED_SENTINEL in indexed_blob

    paraphrase = "I need a COE from the registrar, what form do I submit and where do I pay?"
    hits = _search(store, paraphrase)
    assert _article_ids_from_chunks(hits)[0] == article_id
    qa = _ask(paraphrase)
    assert article_doc in _selected_doc_ids(qa)
    assert article_doc in _source_doc_ids(qa)
    citation = next(source for source in qa.sources if source.get("document_id") == article_doc)
    assert citation.get("source_filename") == "Knowledge Base article"
    assert "TKT-" not in str(citation.get("source_filename") or "")
    assert _OLD_EMBED_SENTINEL in (qa.answer or "") or _OLD_EMBED_SENTINEL in str(
        citation.get("source_excerpt") or ""
    )

    article = session.get(PublishedArticle, article_id)
    assert article is not None
    article.content = (
        "Submit the Certificate of Enrollment request form at the Registrar. "
        f"The cashier now stamps {_NEW_EMBED_SENTINEL} on the validated receipt. "
        "Release is three working days after cashier validation, not the next day."
    )
    session.add(article)
    session.commit()
    index_published_article(session, article)
    session.refresh(article)
    updated = store.export_document(article_doc)
    assert updated is not None
    updated_blob = " ".join(updated.get("documents") or [])
    assert _NEW_EMBED_SENTINEL in updated_blob
    assert _OLD_EMBED_SENTINEL not in updated_blob
    assert len(updated.get("ids") or []) == len(set(updated.get("ids") or []))
    new_hits = _search(store, "When is the Certificate of Enrollment released after cashier validation?")
    new_texts = " ".join(chunk.text for chunk in new_hits if chunk.document_id == article_doc)
    assert _NEW_EMBED_SENTINEL in new_texts
    assert _OLD_EMBED_SENTINEL not in new_texts
    assert article_id in _article_ids_from_chunks(new_hits)[:3]

    rejected = reject_ticket_kb_article(session, ticket_id=ticket.id, actor=staff)
    assert rejected["published"] is False
    assert store.export_document(article_doc) is None
    gone = _search(store, paraphrase)
    assert article_id not in _article_ids_from_chunks(gone)
    gone_qa = _ask(paraphrase)
    assert article_doc not in _source_doc_ids(gone_qa)
    assert article_doc not in _selected_doc_ids(gone_qa)
    assert store.export_document(distractor_doc) is not None


def test_realistic_student_queries_hit_at_k_and_citations(session: Session, e5_store):
    store = e5_store["store"]
    office, student, _staff, admin = _seed_actors(session)
    articles_by_key: dict[str, PublishedArticle] = {}
    for case in FAQ_CORPUS:
        articles_by_key[case["key"]] = _publish_case(
            session, admin=admin, student=student, office=office, case=case
        )

    all_ids = [faq_document_id(article.id) for article in articles_by_key.values()]
    assert len(all_ids) == len(set(all_ids))
    for article in articles_by_key.values():
        exported = store.export_document(faq_document_id(article.id))
        assert exported is not None
        ids = exported.get("ids") or []
        assert ids
        assert len(ids) == len(set(ids))

    ranked_rows: list[dict[str, Any]] = []
    hit1 = 0
    hit3 = 0
    citation_ok = 0
    citation_n = 0
    for case in FAQ_CORPUS:
        gold_id = articles_by_key[case["key"]].id
        gold_doc = faq_document_id(gold_id)
        for question, kind in case["queries"]:
            hits = _search(store, question, top_k=max(3, settings.rag_top_k))
            ranked = _article_ids_from_chunks(hits)
            unique_ranked: list[str] = []
            for item in ranked:
                if item not in unique_ranked:
                    unique_ranked.append(item)
            is_hit1 = bool(unique_ranked) and unique_ranked[0] == gold_id
            is_hit3 = gold_id in unique_ranked[:3]
            hit1 += int(is_hit1)
            hit3 += int(is_hit3)
            ranked_rows.append(
                {
                    "key": case["key"],
                    "kind": kind,
                    "question": question,
                    "hit1": is_hit1,
                    "hit3": is_hit3,
                    "rank": unique_ranked.index(gold_id) + 1 if gold_id in unique_ranked else None,
                }
            )
            if kind in {"exact", "paraphrase", "taglish"}:
                citation_n += 1
                try:
                    qa = _ask(question)
                except EmptyKnowledgeBaseError:
                    print(f"  citation FAIL empty-kb {case['key']} {kind} :: {question}")
                    continue
                cited = gold_doc in _source_doc_ids(qa)
                selected = gold_doc in _selected_doc_ids(qa)
                if cited:
                    citation_ok += 1
                    matching = [
                        source
                        for source in qa.sources
                        if source.get("document_id") == gold_doc
                    ]
                    assert matching
                    assert matching[0].get("source_filename") == "Knowledge Base article"
                else:
                    retrieved = [
                        {
                            "rank": chunk.get("rank"),
                            "title": chunk.get("title"),
                            "document_id": chunk.get("document_id"),
                            "selected": chunk.get("selected_for_context"),
                            "boost": chunk.get("boost_reasons"),
                            "preview": str(chunk.get("content_preview") or "")[:80],
                        }
                        for chunk in (qa.retrieved_chunks or [])[:5]
                    ]
                    print(
                        "  citation FAIL "
                        f"{case['key']} {kind} fallback={qa.fallback_reason!r} "
                        f"intent={qa.detected_intent} sources={sorted(_source_doc_ids(qa))} "
                        f"selected={sorted(_selected_doc_ids(qa))} "
                        f"gold={gold_doc} selected_count={qa.selected_context_count} "
                        f"retrieved={retrieved} "
                        f"answer={str(qa.answer)[:160]!r} :: {question}"
                    )
                if not selected:
                    print(
                        f"  context MISS {case['key']} {kind} "
                        f"selected={sorted(_selected_doc_ids(qa))} gold={gold_doc}"
                    )

    total = len(ranked_rows)
    hit1_rate = hit1 / total
    hit3_rate = hit3 / total
    citation_rate = citation_ok / citation_n if citation_n else 0.0
    print(
        "ticket_faq_e5_metrics "
        f"model=intfloat/multilingual-e5-small backend=local dim={EXPECTED_EMBEDDING_DIMENSION} "
        f"collection={e5_store['collection_name']} n={total} "
        f"Hit@1={hit1_rate:.3f} Hit@3={hit3_rate:.3f} "
        f"citation={citation_ok}/{citation_n}={citation_rate:.3f}"
    )
    for row in ranked_rows:
        print(
            f"  {row['key']:12} {row['kind']:12} hit1={int(row['hit1'])} "
            f"hit3={int(row['hit3'])} rank={row['rank']} :: {row['question']}"
        )

    confusion_ok = 0
    for probe in CONFUSION_PROBES:
        forbidden_id = articles_by_key[probe["must_not_rank1"]].id
        hits = _search(store, probe["text"], top_k=3)
        ranked = _article_ids_from_chunks(hits)
        unique_ranked: list[str] = []
        for item in ranked:
            if item not in unique_ranked:
                unique_ranked.append(item)
        blocked = not unique_ranked or unique_ranked[0] != forbidden_id
        confusion_ok += int(blocked)
        print(
            f"  confusion   blocked={int(blocked)} top={unique_ranked[:1]} "
            f"forbidden={probe['must_not_rank1']} :: {probe['text']}"
        )

    assert total == sum(len(case["queries"]) for case in FAQ_CORPUS)
    assert hit1_rate >= 0.70, f"Hit@1 {hit1_rate:.3f} below 0.70 on isolated E5 ticket FAQs"
    assert hit3_rate >= 0.85, f"Hit@3 {hit3_rate:.3f} below 0.85 on isolated E5 ticket FAQs"
    assert citation_rate >= 0.70, f"citation correctness {citation_rate:.3f} below 0.70"
    assert confusion_ok >= 2, "too many similar-but-unrelated false Hit@1 results"
