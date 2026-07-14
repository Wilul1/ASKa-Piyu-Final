from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import get_db_session, initialize_database
from app.main import app
from app.models.db_models import Office, User
from app.services.auth import create_access_token
from app.services.passwords import hash_password


@pytest.fixture()
def auth_client(monkeypatch) -> Generator[TestClient, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    initialize_database(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    def override_get_db_session() -> Generator[Session, None, None]:
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setattr("app.services.auth.settings.auth_secret_key", "test-auth-secret")
    monkeypatch.setattr("app.services.auth.settings.auth_token_ttl_minutes", 60)
    app.dependency_overrides[get_db_session] = override_get_db_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def signup_student(client: TestClient, email: str = "student@example.edu") -> dict:
    response = client.post(
        "/auth/signup",
        json={
            "email": email,
            "password": "correct horse battery staple",
            "full_name": "Piyu Student",
            "student_id": "2026-0001",
        },
    )
    assert response.status_code == 200
    return response.json()


def test_successful_student_signup(auth_client):
    data = signup_student(auth_client)

    assert data["token_type"] == "bearer"
    assert data["access_token"]
    assert data["user"]["email"] == "student@example.edu"
    assert data["user"]["role"] == "student"
    assert "password" not in data["user"]
    assert "password_hash" not in data["user"]


def test_duplicate_email_rejected(auth_client):
    signup_student(auth_client)

    response = auth_client.post(
        "/auth/signup",
        json={
            "email": "student@example.edu",
            "password": "another strong password",
            "full_name": "Other Student",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Email is already registered."


def test_public_signup_cannot_create_admin(auth_client):
    response = auth_client.post(
        "/auth/signup",
        json={
            "email": "admin@example.edu",
            "password": "correct horse battery staple",
            "full_name": "Admin User",
            "role": "admin",
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Public signup can create student accounts only."


def test_successful_login(auth_client):
    signup_student(auth_client)

    response = auth_client.post(
        "/auth/login",
        json={"email": "STUDENT@example.edu", "password": "correct horse battery staple"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["access_token"]
    assert data["user"]["email"] == "student@example.edu"


def test_wrong_password_rejected(auth_client):
    signup_student(auth_client)

    response = auth_client.post(
        "/auth/login",
        json={"email": "student@example.edu", "password": "wrong password"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password."


def test_auth_me_works_with_valid_token(auth_client):
    signup_data = signup_student(auth_client)

    response = auth_client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {signup_data['access_token']}"},
    )

    assert response.status_code == 200
    assert response.json()["email"] == "student@example.edu"
    assert response.json()["role"] == "student"
    assert response.json()["office_id"] is None
    assert response.json()["office_name"] is None


def test_auth_me_includes_office_name(auth_client):
    session_generator = app.dependency_overrides[get_db_session]()
    session = next(session_generator)
    try:
        office = Office(name="ICT Office")
        session.add(office)
        session.flush()
        user = User(
            email="ict@aska.local",
            password_hash=hash_password("office123"),
            full_name="ICT Staff",
            role="office",
            office_id=office.id,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        token = create_access_token(user)
    finally:
        try:
            next(session_generator)
        except StopIteration:
            pass

    response = auth_client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["role"] == "office"
    assert data["office_id"]
    assert data["office_name"] == "ICT Office"


def test_auth_me_rejects_missing_token(auth_client):
    response = auth_client.get("/auth/me")

    assert response.status_code == 401
    assert response.json()["detail"] == "Missing bearer authentication token."


def test_auth_me_rejects_invalid_token(auth_client):
    response = auth_client.get("/auth/me", headers={"Authorization": "Bearer invalid-token"})

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid authentication token."
