from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import get_db_session, initialize_database
from app.main import app
from app.models.db_models import Office, PublishedArticle, User
from app.services.auth import create_access_token
from app.services.passwords import hash_password


@pytest.fixture()
def office_article_client(monkeypatch) -> Generator[tuple[TestClient, sessionmaker], None, None]:
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
    monkeypatch.setattr("app.routes.auth.settings.signup_invite_code", None)
    monkeypatch.setattr("app.routes.auth.settings.signup_allowed_email_domains", None)
    monkeypatch.setattr("app.routes.admin.knowledge_base.settings.admin_api_key", None)
    monkeypatch.setattr(
        "app.routes.admin.knowledge_base.get_session_factory",
        lambda: session_factory,
    )
    app.dependency_overrides[get_db_session] = override_get_db_session

    session = session_factory()
    ict = Office(name="ICT Office")
    registrar = Office(name="Registrar")
    session.add_all([ict, registrar])
    session.flush()

    ict_user = User(
        email="ict@example.edu",
        password_hash=hash_password("correct horse battery staple1"),
        full_name="ICT Staff",
        role="office",
        office_id=ict.id,
        email_verified=True,
    )
    session.add(ict_user)
    session.flush()

    session.add(
        PublishedArticle(
            title="ICT Wi-Fi Guide",
            slug="ict-wifi-guide",
            category="ICT Services",
            summary="How to connect",
            content="Connect to campus Wi-Fi.",
            office="ICT Office",
            published=True,
            published_by_user_id=ict_user.id,
            rag_indexed=True,
        )
    )
    session.add(
        PublishedArticle(
            title="Registrar TOR Steps",
            slug="registrar-tor-steps",
            category="Student Records",
            summary="Request TOR",
            content="Visit the registrar.",
            office="Registrar",
            published=True,
            rag_indexed=True,
        )
    )
    session.commit()
    session.close()

    try:
        yield TestClient(app), session_factory
    finally:
        app.dependency_overrides.clear()


def _office_headers(session_factory) -> dict[str, str]:
    session = session_factory()
    try:
        user = session.query(User).filter(User.email == "ict@example.edu").one()
        token = create_access_token(user)
    finally:
        session.close()
    return {"Authorization": f"Bearer {token}"}


def test_office_article_list_is_scoped_to_office(office_article_client):
    client, session_factory = office_article_client
    headers = _office_headers(session_factory)
    response = client.get("/admin/kb/articles", headers=headers)
    assert response.status_code == 200
    titles = {item["title"] for item in response.json()}
    assert titles == {"ICT Wi-Fi Guide"}


def test_office_cannot_edit_other_office_article(office_article_client):
    client, session_factory = office_article_client
    headers = _office_headers(session_factory)
    session = session_factory()
    try:
        other = (
            session.query(PublishedArticle)
            .filter(PublishedArticle.title == "Registrar TOR Steps")
            .one()
        )
        article_id = other.id
    finally:
        session.close()

    response = client.patch(
        f"/admin/kb/articles/{article_id}",
        headers=headers,
        json={"summary": "Hacked"},
    )
    assert response.status_code == 403


def test_office_cannot_delete_articles(office_article_client):
    client, session_factory = office_article_client
    headers = _office_headers(session_factory)
    list_resp = client.get("/admin/kb/articles", headers=headers)
    article_id = list_resp.json()[0]["id"]
    response = client.delete(
        f"/admin/kb/articles/{article_id}",
        headers=headers,
    )
    assert response.status_code == 403
