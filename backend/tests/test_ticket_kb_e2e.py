"""HTTP E2E: convert resolved ticket → publish → audience-filtered KB browse."""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import get_db_session, initialize_database
from app.main import app
from app.models.db_models import Office, PublishedArticle, Ticket, TicketReply, User
from app.services.auth import create_access_token
from app.services.passwords import hash_password


@pytest.fixture()
def e2e_client(monkeypatch) -> Generator[tuple[TestClient, sessionmaker], None, None]:
    from sqlalchemy import create_engine

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    initialize_database(engine)
    session_factory = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
    )

    def override_get_db_session() -> Generator[Session, None, None]:
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setattr("app.services.auth.settings.auth_secret_key", "test-auth-secret")
    monkeypatch.setattr("app.services.auth.settings.auth_token_ttl_minutes", 60)
    monkeypatch.setattr(
        "app.routes.admin.knowledge_base.get_session_factory",
        lambda: session_factory,
    )
    app.dependency_overrides[get_db_session] = override_get_db_session

    with session_factory() as session:
        _seed(session)

    class _FakeStore:
        def __init__(self) -> None:
            self.fail_add = False
            self.fail_delete = False
            self.docs: set[str] = set()

        def export_document(self, document_id: str):
            if document_id not in self.docs:
                return None
            return {
                "document_id": document_id,
                "ids": [f"{document_id}::0"],
                "documents": ["prior"],
                "metadatas": [{"audience": "faculty"}],
            }

        def restore_document_export(self, export):
            self.docs.add(export["document_id"])

        def delete_document(self, document_id: str) -> None:
            if self.fail_delete:
                raise RuntimeError("chroma delete failed")
            self.docs.discard(document_id)

        def add_document_chunks(self, **kwargs):
            if self.fail_add:
                raise RuntimeError("chroma write failed")
            self.docs.add(kwargs["document_id"])
            return len(kwargs.get("chunks") or [])

    store = _FakeStore()
    monkeypatch.setattr(
        "app.services.article_rag_indexer.get_knowledge_base_store",
        lambda: store,
    )

    try:
        yield TestClient(app), session_factory, store
    finally:
        app.dependency_overrides.clear()


def _seed(session: Session) -> None:
    office = Office(id="office-reg", name="Registrar", description="Registrar")
    session.add(office)
    session.flush()
    session.add_all(
        [
            User(
                id="user-student",
                email="student@lspu.test",
                password_hash=hash_password("password123"),
                full_name="Student User",
                role="student",
                student_id="2026-1",
            ),
            User(
                id="user-faculty",
                email="faculty@lspu.test",
                password_hash=hash_password("password123"),
                full_name="Faculty User",
                role="faculty",
            ),
            User(
                id="user-office",
                email="office@lspu.test",
                password_hash=hash_password("password123"),
                full_name="Office User",
                role="office",
                office_id=office.id,
            ),
            User(
                id="user-admin",
                email="admin@lspu.test",
                password_hash=hash_password("password123"),
                full_name="Admin User",
                role="admin",
            ),
        ]
    )
    now = datetime.now(timezone.utc)
    ticket = Ticket(
        id="TKT-E2E-001",
        user_id="user-student",
        original_question="How is teaching load computed for faculty?",
        description="Faculty teaching load clarification",
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
            sender_id="user-office",
            sender_role="office",
            sender_name="Office User",
            message=(
                "Teaching load is assigned per the Faculty Manual. Full-time faculty "
                "carry 18 units per semester unless approved for overload."
            ),
            created_at=now,
        )
    )
    session.commit()


def _auth(user_id: str, session_factory: sessionmaker) -> dict[str, str]:
    with session_factory() as session:
        user = session.get(User, user_id)
        assert user is not None
        return {"Authorization": f"Bearer {create_access_token(user)}"}


def test_convert_publish_sets_publisher_and_filters_kb(e2e_client):
    client, session_factory, _store = e2e_client
    office_headers = _auth("user-office", session_factory)
    admin_headers = _auth("user-admin", session_factory)
    student_headers = _auth("user-student", session_factory)
    faculty_headers = _auth("user-faculty", session_factory)

    convert = client.post(
        "/tickets/TKT-E2E-001/convert-to-article",
        headers=office_headers,
        json={
            "title": "Faculty teaching load",
            "content": (
                "Teaching load is assigned per the Faculty Manual. Full-time faculty "
                "carry 18 units per semester unless approved for overload."
            ),
            "audience": "faculty",
        },
    )
    assert convert.status_code == 200, convert.text
    article_id = convert.json()["article_id"]
    assert article_id
    assert convert.json()["kb_conversion_status"] == "draft"

    publish = client.post(
        f"/admin/kb/articles/{article_id}/publish",
        headers=admin_headers,
    )
    assert publish.status_code == 200, publish.text
    body = publish.json()
    assert body["published"] is True
    assert body["rag_indexed"] is True
    assert body["published_by_user_id"] == "user-admin"

    with session_factory() as session:
        art = session.get(PublishedArticle, article_id)
        assert art is not None
        assert art.published is True
        assert art.published_by_user_id == "user-admin"
        assert art.audience == "faculty"
        assert art.rag_indexed is True

    public_id = f"pub:{article_id}"
    student_list = client.get("/kb/articles", headers=student_headers)
    assert student_list.status_code == 200
    student_ids = {item["id"] for item in student_list.json().get("items", [])}
    assert public_id not in student_ids

    faculty_list = client.get("/kb/articles", headers=faculty_headers)
    assert faculty_list.status_code == 200
    faculty_ids = {item["id"] for item in faculty_list.json().get("items", [])}
    assert public_id in faculty_ids

    student_cats = client.get("/kb/categories", headers=student_headers)
    assert student_cats.status_code == 200
    assert student_cats.json().get("published_article_count", 0) == 0

    faculty_cats = client.get("/kb/categories", headers=faculty_headers)
    assert faculty_cats.status_code == 200
    assert faculty_cats.json().get("published_article_count", 0) == 1

    # PATCH edit of a published article must re-index (fail-closed path).
    patch = client.patch(
        f"/admin/kb/articles/{article_id}",
        headers=admin_headers,
        json={
            "content": (
                "Teaching load is assigned per the Faculty Manual. Full-time faculty "
                "carry 18 units per semester unless approved for overload. "
                "Overload requires written approval from the campus director."
            ),
            "audience": "faculty",
        },
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["rag_indexed"] is True
    assert patch.json().get("published_by_user_id") == "user-admin"

    unpublish = client.post(
        "/admin/kb/articles/bulk-unpublish",
        headers=admin_headers,
        json={"article_ids": [article_id]},
    )
    assert unpublish.status_code == 200, unpublish.text
    assert unpublish.json()["success_count"] == 1
    with session_factory() as session:
        art = session.get(PublishedArticle, article_id)
        assert art is not None
        assert art.published is False
        assert art.rag_indexed is False
        ticket = session.get(Ticket, "TKT-E2E-001")
        assert ticket is not None
        assert ticket.kb_conversion_status == "draft"


def test_publish_fail_closed_when_chroma_add_fails(e2e_client):
    client, session_factory, store = e2e_client
    office_headers = _auth("user-office", session_factory)
    admin_headers = _auth("user-admin", session_factory)

    convert = client.post(
        "/tickets/TKT-E2E-001/convert-to-article",
        headers=office_headers,
        json={
            "title": "Faculty teaching load",
            "content": (
                "Teaching load is assigned per the Faculty Manual. Full-time faculty "
                "carry 18 units per semester unless approved for overload."
            ),
            "audience": "faculty",
        },
    )
    assert convert.status_code == 200, convert.text
    article_id = convert.json()["article_id"]

    store.fail_add = True
    publish = client.post(
        f"/admin/kb/articles/{article_id}/publish",
        headers=admin_headers,
    )
    assert publish.status_code == 502, publish.text
    assert "RAG indexing failed" in publish.text

    with session_factory() as session:
        art = session.get(PublishedArticle, article_id)
        assert art is not None
        # Fail closed: do not leave a public article without RAG chunks.
        assert art.published is False
        assert art.rag_indexed is False
        ticket = session.get(Ticket, "TKT-E2E-001")
        assert ticket is not None
        assert ticket.kb_conversion_status == "draft"

    # Retry publish after Chroma is healthy again.
    store.fail_add = False
    reindex = client.post(
        f"/admin/kb/articles/{article_id}/publish",
        headers=admin_headers,
    )
    assert reindex.status_code == 200, reindex.text
    assert reindex.json()["rag_indexed"] is True
    with session_factory() as session:
        art = session.get(PublishedArticle, article_id)
        assert art is not None
        assert art.rag_indexed is True


def test_unpublish_fail_closed_when_chroma_delete_fails(e2e_client):
    client, session_factory, store = e2e_client
    office_headers = _auth("user-office", session_factory)
    admin_headers = _auth("user-admin", session_factory)

    convert = client.post(
        "/tickets/TKT-E2E-001/convert-to-article",
        headers=office_headers,
        json={
            "title": "Faculty teaching load",
            "content": (
                "Teaching load is assigned per the Faculty Manual. Full-time faculty "
                "carry 18 units per semester unless approved for overload."
            ),
            "audience": "faculty",
        },
    )
    assert convert.status_code == 200, convert.text
    article_id = convert.json()["article_id"]

    publish = client.post(
        f"/admin/kb/articles/{article_id}/publish",
        headers=admin_headers,
    )
    assert publish.status_code == 200, publish.text

    store.fail_delete = True
    unpublish = client.post(
        f"/admin/kb/articles/{article_id}/unpublish",
        headers=admin_headers,
    )
    # Postgres unpublish commits first; Chroma cleanup is best-effort.
    assert unpublish.status_code == 200, unpublish.text
    assert unpublish.json()["published"] is False

    with session_factory() as session:
        art = session.get(PublishedArticle, article_id)
        assert art is not None
        assert art.published is False
        assert art.rag_indexed is False
