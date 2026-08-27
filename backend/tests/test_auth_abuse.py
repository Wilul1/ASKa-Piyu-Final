"""Abuse detection: auth event logging and admin flag APIs."""

from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import get_db_session, initialize_database
from app.main import app
from app.models.db_models import AuthEvent, User
from app.services.auth import create_access_token
from app.services.auth_abuse import (
    EVENT_LOGIN_FAIL,
    EVENT_SIGNUP,
    SIGNUP_IP_LIMIT_24H,
    list_abuse_flags,
    record_auth_event,
)
from app.services.auth_rate_limit import reset_auth_rate_limits
from app.services.passwords import hash_password


@pytest.fixture()
def abuse_client(monkeypatch) -> Generator[TestClient, None, None]:
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

    app.dependency_overrides[get_db_session] = override_get_db_session
    monkeypatch.setattr("app.services.auth.settings.auth_secret_key", "test-auth-secret")
    monkeypatch.setattr("app.services.auth.settings.auth_token_ttl_minutes", 60)
    monkeypatch.setattr("app.routes.auth.settings.signup_invite_code", None)
    monkeypatch.setattr("app.routes.auth.settings.signup_allowed_email_domains", None)
    monkeypatch.setattr("app.routes.auth.settings.allow_public_signup", True)
    reset_auth_rate_limits()
    client = TestClient(app)
    client.session_factory = session_factory  # type: ignore[attr-defined]
    yield client
    app.dependency_overrides.clear()
    reset_auth_rate_limits()


def _admin_headers(session: Session) -> dict[str, str]:
    admin = User(
        email="admin@abuse.test",
        password_hash=hash_password("correct horse battery staple1"),
        full_name="Abuse Admin",
        role="admin",
        email_verified=True,
        is_active=True,
    )
    session.add(admin)
    session.commit()
    session.refresh(admin)
    return {"Authorization": f"Bearer {create_access_token(admin)}"}


def test_signup_and_login_create_auth_events(abuse_client: TestClient):
    signup = abuse_client.post(
        "/auth/signup",
        json={
            "email": "one@example.com",
            "password": "correct horse battery staple1",
            "full_name": "One Student",
        },
    )
    assert signup.status_code == 200

    fail = abuse_client.post(
        "/auth/login",
        json={"email": "one@example.com", "password": "wrong-password-99"},
    )
    assert fail.status_code == 401

    ok = abuse_client.post(
        "/auth/login",
        json={
            "email": "one@example.com",
            "password": "correct horse battery staple1",
        },
    )
    assert ok.status_code == 200

    session = abuse_client.session_factory()  # type: ignore[attr-defined]
    try:
        types = {row.event_type for row in session.query(AuthEvent).all()}
        assert EVENT_SIGNUP in types
        assert EVENT_LOGIN_FAIL in types
        assert "login_ok" in types
    finally:
        session.close()


def test_signup_velocity_flag_and_admin_endpoints(abuse_client: TestClient):
    session = abuse_client.session_factory()  # type: ignore[attr-defined]
    try:
        headers = _admin_headers(session)
        for index in range(SIGNUP_IP_LIMIT_24H):
            record_auth_event(
                session,
                event_type=EVENT_SIGNUP,
                ip_address="203.0.113.10",
                email=f"burst{index}@example.com",
            )
        flags = list_abuse_flags(session)
        assert any(item["kind"] == "signup_velocity" for item in flags)
    finally:
        session.close()

    flagged = abuse_client.get("/auth/abuse/flags", headers=headers)
    assert flagged.status_code == 200
    body = flagged.json()
    assert body["total"] >= 1
    assert body["items"][0]["ip_address"] == "203.0.113.10"

    events = abuse_client.get(
        "/auth/abuse/events",
        headers=headers,
        params={"ip": "203.0.113.10"},
    )
    assert events.status_code == 200
    assert events.json()["total"] >= SIGNUP_IP_LIMIT_24H

    forbidden = abuse_client.get("/auth/abuse/flags")
    assert forbidden.status_code in {401, 403}
