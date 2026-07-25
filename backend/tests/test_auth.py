from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import get_db_session, initialize_database
from app.main import app
from app.models.db_models import Office, Ticket, TicketReply, User
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

    from app.services.auth_rate_limit import reset_auth_rate_limits

    reset_auth_rate_limits()
    try:
        yield TestClient(app)
    finally:
        reset_auth_rate_limits()
        app.dependency_overrides.clear()


def signup_student(client: TestClient, email: str = "student@example.edu") -> dict:
    response = client.post(
        "/auth/signup",
        json={
            "email": email,
            "password": "correct horse battery staple1",
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
            "password": "another strong password1",
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
            "password": "correct horse battery staple1",
            "full_name": "Admin User",
            "role": "admin",
        },
    )

    assert response.status_code == 422
    assert "student accounts only" in response.text


def test_public_signup_cannot_create_faculty(auth_client):
    response = auth_client.post(
        "/auth/signup",
        json={
            "email": "faculty@example.edu",
            "password": "correct horse battery staple1",
            "full_name": "Faculty User",
            "role": "faculty",
        },
    )

    assert response.status_code == 422
    assert "student accounts only" in response.text


def test_admin_can_create_faculty_account(auth_client):
    session_generator = app.dependency_overrides[get_db_session]()
    session = next(session_generator)
    try:
        admin = User(
            email="admin@example.edu",
            password_hash=hash_password("admin-password-1"),
            full_name="Admin User",
            role="admin",
        )
        session.add(admin)
        session.commit()
        session.refresh(admin)
        token = create_access_token(admin)
    finally:
        try:
            next(session_generator)
        except StopIteration:
            pass

    response = auth_client.post(
        "/auth/faculty-accounts",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "email": "faculty@example.edu",
            "password": "faculty12345",
            "full_name": "Faculty Member",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["role"] == "faculty"
    assert data["email"] == "faculty@example.edu"


def test_login_rate_limit_returns_429(auth_client, monkeypatch):
    from app.services import auth_rate_limit

    auth_rate_limit.reset_auth_rate_limits()
    signup_student(auth_client)

    import app.routes.auth as auth_routes

    def limited(key: str, *, limit: int, window_seconds: int = 60) -> bool:
        return auth_rate_limit.check_auth_rate_limit(key, limit=3, window_seconds=window_seconds)

    monkeypatch.setattr(auth_routes, "check_auth_rate_limit", limited)

    body = {"email": "student@example.edu", "password": "wrong-password"}
    assert auth_client.post("/auth/login", json=body).status_code == 401
    assert auth_client.post("/auth/login", json=body).status_code == 401
    assert auth_client.post("/auth/login", json=body).status_code == 401
    assert auth_client.post("/auth/login", json=body).status_code == 429


def test_successful_login(auth_client):
    signup_student(auth_client)

    response = auth_client.post(
        "/auth/login",
        json={"email": "STUDENT@example.edu", "password": "correct horse battery staple1"},
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


def _seed_admin(session: Session) -> User:
    admin = User(
        email="admin@aska.local",
        password_hash=hash_password("admin12345"),
        full_name="ASKa Admin",
        role="admin",
    )
    session.add(admin)
    session.commit()
    session.refresh(admin)
    return admin


def test_list_users_admin_only(auth_client):
    signup_student(auth_client)
    student_token = auth_client.post(
        "/auth/login",
        json={"email": "student@example.edu", "password": "correct horse battery staple1"},
    ).json()["access_token"]

    denied = auth_client.get(
        "/auth/users",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert denied.status_code == 403

    session_generator = app.dependency_overrides[get_db_session]()
    session = next(session_generator)
    try:
        admin = _seed_admin(session)
        office = Office(name="Registrar", service_category="Student Records")
        session.add(office)
        session.flush()
        office_user = User(
            email="registrar@aska.local",
            password_hash=hash_password("office123"),
            full_name="Registrar Staff",
            role="office",
            office_id=office.id,
        )
        session.add(office_user)
        session.commit()
        token = create_access_token(admin)
    finally:
        try:
            next(session_generator)
        except StopIteration:
            pass

    response = auth_client.get(
        "/auth/users",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 3
    roles = {item["role"] for item in data["items"]}
    assert {"student", "office", "admin"}.issubset(roles)

    office_only = auth_client.get(
        "/auth/users",
        params={"role": "office"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert office_only.status_code == 200
    office_data = office_only.json()
    assert office_data["total"] >= 1
    assert all(item["role"] == "office" for item in office_data["items"])


def test_create_office_account(auth_client):
    session_generator = app.dependency_overrides[get_db_session]()
    session = next(session_generator)
    try:
        admin = _seed_admin(session)
        office = Office(name="ICT Office", service_category="ICT Services")
        session.add(office)
        session.commit()
        session.refresh(office)
        token = create_access_token(admin)
        office_id = office.id
    finally:
        try:
            next(session_generator)
        except StopIteration:
            pass

    response = auth_client.post(
        "/auth/office-accounts",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "email": "ict.staff@aska.local",
            "password": "office12345",
            "full_name": "ICT Staff",
            "office_id": office_id,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["role"] == "office"
    assert data["email"] == "ict.staff@aska.local"
    assert data["office_id"] == office_id
    assert data["office_name"] == "ICT Office"


def test_hard_delete_user_succeeds_when_user_owns_tickets(auth_client):
    """Ticket FKs must not block admin hard-delete."""
    session_generator = app.dependency_overrides[get_db_session]()
    session = next(session_generator)
    try:
        admin = _seed_admin(session)
        student = User(
            email="doomed@example.edu",
            password_hash=hash_password("student12345"),
            full_name="Doomed Student",
            role="student",
        )
        session.add(student)
        session.flush()
        ticket = Ticket(
            id="TKT-DEL-001",
            user_id=student.id,
            original_question="Where is my TOR?",
            description="Need TOR",
            category="Student Records",
            assigned_office="Registrar",
            priority="Medium",
            status="Open",
        )
        session.add(ticket)
        session.flush()
        session.add(
            TicketReply(
                ticket_id=ticket.id,
                sender_id=student.id,
                sender_role="student",
                sender_name=student.full_name,
                message="Following up",
            )
        )
        session.commit()
        student_id = student.id
        token = create_access_token(admin)
    finally:
        try:
            next(session_generator)
        except StopIteration:
            pass

    response = auth_client.delete(
        f"/auth/users/{student_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["deleted_user_id"] == student_id

    session_generator = app.dependency_overrides[get_db_session]()
    session = next(session_generator)
    try:
        assert session.get(User, student_id) is None
        assert session.get(Ticket, "TKT-DEL-001") is None
    finally:
        try:
            next(session_generator)
        except StopIteration:
            pass
