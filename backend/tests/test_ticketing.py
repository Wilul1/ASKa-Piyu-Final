"""PostgreSQL ticketing with JWT auth and office-scoped access control."""

from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.db.session import get_db_session, initialize_database
from app.main import app
from app.models.db_models import Office, User
from app.services.auth import create_access_token
from app.services.passwords import hash_password


@pytest.fixture()
def ticket_client(monkeypatch) -> Generator[TestClient, None, None]:
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool

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

    with session_factory() as session:
        _seed_offices_and_users(session)

    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _seed_offices_and_users(session: Session) -> None:
    ict = Office(name="ICT Office")
    registrar = Office(name="Registrar")
    osas = Office(name="Office of Student Affairs")
    session.add_all([ict, registrar, osas])
    session.flush()

    student = User(
        email="student1@aska.local",
        password_hash=hash_password("student123"),
        full_name="Piyu Student",
        role="student",
        student_id="2026-0001",
    )
    other_student = User(
        email="student2@aska.local",
        password_hash=hash_password("student123"),
        full_name="Other Student",
        role="student",
        student_id="2026-0002",
    )
    ict_staff = User(
        email="ict@aska.local",
        password_hash=hash_password("office123"),
        full_name="ICT Staff",
        role="office",
        office_id=ict.id,
    )
    registrar_staff = User(
        email="registrar@aska.local",
        password_hash=hash_password("office123"),
        full_name="Registrar Staff",
        role="office",
        office_id=registrar.id,
    )
    admin = User(
        email="admin@aska.local",
        password_hash=hash_password("admin123"),
        full_name="Admin User",
        role="admin",
    )
    session.add_all([student, other_student, ict_staff, registrar_staff, admin])
    session.commit()


def _auth_headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user)}"}


def _spoof_headers() -> dict[str, str]:
    return {
        "x-user-id": "spoof-admin",
        "x-user-role": "admin",
        "x-user-name": "Spoofed Admin",
    }


def _get_user(session_factory, email: str) -> User:
    with session_factory() as session:
        user = session.query(User).filter(User.email == email).one()
        session.expunge(user)
        return user


def test_ticket_triage_detects_technical_high_priority(ticket_client):
    response = ticket_client.post(
        "/tickets/triage",
        json={
            "original_question": "I cannot access my student portal account before enrollment.",
            "description": "",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["category"] == "Technical Support"
    assert data["assigned_office"] == "ICT Office"
    assert data["assigned_office_id"]
    assert data["priority"] == "High"


def test_cannot_log_in_with_spaces_is_high_priority(ticket_client):
    response = ticket_client.post(
        "/tickets/triage",
        json={
            "original_question": "I cannot log in to my student portal.",
            "description": (
                "Correct student number and password, still shows invalid credentials. "
                "Need access for enrollment."
            ),
        },
    )
    assert response.status_code == 200
    assert response.json()["priority"] == "High"
    assert response.json()["assigned_office"] == "ICT Office"


def test_jwt_required_for_ticket_routes(ticket_client):
    response = ticket_client.get("/tickets")
    assert response.status_code == 401

    response = ticket_client.post(
        "/tickets",
        json={"original_question": "Need help", "description": ""},
    )
    assert response.status_code == 401


def test_student_can_create_and_list_own_ticket(ticket_client):
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    session_factory = sessionmaker(bind=engine)
    with engine.connect():
        pass
    # Reuse seeded users via signup path — login instead
    login = ticket_client.post(
        "/auth/login",
        json={"email": "student1@aska.local", "password": "student123"},
    )
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    create_response = ticket_client.post(
        "/tickets",
        headers=headers,
        json={
            "original_question": "How can I request a copy of my TOR?",
            "description": "I need it for scholarship application.",
            "source_from_chatbot": True,
            "confidence_score": 0.2,
        },
    )
    list_response = ticket_client.get("/tickets", headers=headers)

    assert create_response.status_code == 200
    ticket = create_response.json()
    assert ticket["status"] == "Open"
    assert ticket["ticket_id"].startswith("TK-")
    assert ticket["id"] == ticket["ticket_id"]
    assert ticket["assigned_office"] == "Registrar"
    assert ticket["assigned_office_id"]
    assert ticket["assigned_office_name"] == "Registrar"
    assert ticket["created_by"]["full_name"] == "Piyu Student"
    assert ticket["replies_count"] == 0
    assert list_response.status_code == 200
    assert list_response.json()["total"] == 1
    assert list_response.json()["items"][0]["id"] == ticket["id"]


def test_student_cannot_view_another_students_ticket(ticket_client):
    student_login = ticket_client.post(
        "/auth/login",
        json={"email": "student1@aska.local", "password": "student123"},
    )
    other_login = ticket_client.post(
        "/auth/login",
        json={"email": "student2@aska.local", "password": "student123"},
    )
    student_headers = {"Authorization": f"Bearer {student_login.json()['access_token']}"}
    other_headers = {"Authorization": f"Bearer {other_login.json()['access_token']}"}

    created = ticket_client.post(
        "/tickets",
        headers=student_headers,
        json={"original_question": "I need my TOR.", "description": ""},
    ).json()

    response = ticket_client.get(f"/tickets/{created['id']}", headers=other_headers)
    assert response.status_code == 403


def test_header_spoofing_does_not_grant_admin_access(ticket_client):
    student_login = ticket_client.post(
        "/auth/login",
        json={"email": "student1@aska.local", "password": "student123"},
    )
    headers = {
        "Authorization": f"Bearer {student_login.json()['access_token']}",
        **_spoof_headers(),
    }
    response = ticket_client.get("/tickets/statistics", headers=headers)
    assert response.status_code == 403


def test_office_only_sees_assigned_tickets(ticket_client):
    student_login = ticket_client.post(
        "/auth/login",
        json={"email": "student1@aska.local", "password": "student123"},
    )
    ict_login = ticket_client.post(
        "/auth/login",
        json={"email": "ict@aska.local", "password": "office123"},
    )
    registrar_login = ticket_client.post(
        "/auth/login",
        json={"email": "registrar@aska.local", "password": "office123"},
    )
    student_headers = {"Authorization": f"Bearer {student_login.json()['access_token']}"}
    ict_headers = {"Authorization": f"Bearer {ict_login.json()['access_token']}"}
    registrar_headers = {"Authorization": f"Bearer {registrar_login.json()['access_token']}"}

    ticket_client.post(
        "/tickets",
        headers=student_headers,
        json={"original_question": "I cannot login to the student portal.", "description": ""},
    )

    ict_response = ticket_client.get("/tickets", headers=ict_headers)
    registrar_response = ticket_client.get("/tickets", headers=registrar_headers)

    assert ict_response.status_code == 200
    assert ict_response.json()["total"] == 1
    assert registrar_response.status_code == 200
    assert registrar_response.json()["total"] == 0


def test_office_cannot_view_other_office_ticket(ticket_client):
    student_login = ticket_client.post(
        "/auth/login",
        json={"email": "student1@aska.local", "password": "student123"},
    )
    registrar_login = ticket_client.post(
        "/auth/login",
        json={"email": "registrar@aska.local", "password": "office123"},
    )
    student_headers = {"Authorization": f"Bearer {student_login.json()['access_token']}"}
    registrar_headers = {"Authorization": f"Bearer {registrar_login.json()['access_token']}"}

    created = ticket_client.post(
        "/tickets",
        headers=student_headers,
        json={"original_question": "I cannot login to the student portal.", "description": ""},
    ).json()

    response = ticket_client.get(f"/tickets/{created['id']}", headers=registrar_headers)
    assert response.status_code == 403


def test_office_can_reply_and_resolve_ticket(ticket_client):
    student_login = ticket_client.post(
        "/auth/login",
        json={"email": "student1@aska.local", "password": "student123"},
    )
    ict_login = ticket_client.post(
        "/auth/login",
        json={"email": "ict@aska.local", "password": "office123"},
    )
    student_headers = {"Authorization": f"Bearer {student_login.json()['access_token']}"}
    ict_headers = {"Authorization": f"Bearer {ict_login.json()['access_token']}"}

    created = ticket_client.post(
        "/tickets",
        headers=student_headers,
        json={"original_question": "I cannot login to the student portal.", "description": ""},
    ).json()

    reply_response = ticket_client.post(
        f"/tickets/{created['id']}/replies",
        headers=ict_headers,
        json={"message": "Please visit the ICT office with your student ID."},
    )
    update_response = ticket_client.patch(
        f"/tickets/{created['id']}",
        headers=ict_headers,
        json={"status": "In Progress"},
    )
    resolved_response = ticket_client.patch(
        f"/tickets/{created['id']}",
        headers=ict_headers,
        json={"status": "Resolved"},
    )

    assert reply_response.status_code == 200
    assert reply_response.json()["messages"][0]["sender_role"] == "office"
    assert reply_response.json()["replies_count"] == 1
    assert reply_response.json()["latest_reply_preview"]
    assert update_response.status_code == 200
    assert update_response.json()["status"] == "In Progress"
    assert resolved_response.status_code == 200
    assert resolved_response.json()["resolved_at"] is not None


def test_student_can_reply_on_open_ticket(ticket_client):
    student_login = ticket_client.post(
        "/auth/login",
        json={"email": "student1@aska.local", "password": "student123"},
    )
    headers = {"Authorization": f"Bearer {student_login.json()['access_token']}"}

    created = ticket_client.post(
        "/tickets",
        headers=headers,
        json={"original_question": "I need help with enrollment.", "description": "Details here."},
    ).json()

    reply_response = ticket_client.post(
        f"/tickets/{created['id']}/replies",
        headers=headers,
        json={"message": "Here is the additional information you requested."},
    )

    assert reply_response.status_code == 200
    roles = [message["sender_role"] for message in reply_response.json()["messages"]]
    assert "student" in roles
    assert reply_response.json()["replies_count"] == 1


def test_student_cannot_reply_on_closed_ticket(ticket_client):
    student_login = ticket_client.post(
        "/auth/login",
        json={"email": "student1@aska.local", "password": "student123"},
    )
    ict_login = ticket_client.post(
        "/auth/login",
        json={"email": "ict@aska.local", "password": "office123"},
    )
    student_headers = {"Authorization": f"Bearer {student_login.json()['access_token']}"}
    ict_headers = {"Authorization": f"Bearer {ict_login.json()['access_token']}"}

    created = ticket_client.post(
        "/tickets",
        headers=student_headers,
        json={"original_question": "Portal issue", "description": ""},
    ).json()
    ticket_client.patch(
        f"/tickets/{created['id']}",
        headers=ict_headers,
        json={"status": "In Progress"},
    )
    close_response = ticket_client.patch(
        f"/tickets/{created['id']}",
        headers=ict_headers,
        json={"status": "Closed"},
    )
    assert close_response.status_code == 200

    response = ticket_client.post(
        f"/tickets/{created['id']}/replies",
        headers=student_headers,
        json={"message": "One more question"},
    )
    assert response.status_code == 422


def test_admin_can_reassign_ticket(ticket_client):
    student_login = ticket_client.post(
        "/auth/login",
        json={"email": "student1@aska.local", "password": "student123"},
    )
    admin_login = ticket_client.post(
        "/auth/login",
        json={"email": "admin@aska.local", "password": "admin123"},
    )
    student_headers = {"Authorization": f"Bearer {student_login.json()['access_token']}"}
    admin_headers = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}

    created = ticket_client.post(
        "/tickets",
        headers=student_headers,
        json={"original_question": "I need help with my TOR.", "description": ""},
    ).json()

    response = ticket_client.patch(
        f"/tickets/{created['id']}",
        headers=admin_headers,
        json={"assigned_office": "Office of Student Affairs", "priority": "Low"},
    )

    assert response.status_code == 200
    assert response.json()["assigned_office"] == "Office of Student Affairs"
    assert response.json()["assigned_office_name"] == "Office of Student Affairs"
    assert response.json()["assigned_office_id"]
    assert response.json()["priority"] == "Low"


def test_admin_can_view_all_tickets(ticket_client):
    student_login = ticket_client.post(
        "/auth/login",
        json={"email": "student1@aska.local", "password": "student123"},
    )
    admin_login = ticket_client.post(
        "/auth/login",
        json={"email": "admin@aska.local", "password": "admin123"},
    )
    student_headers = {"Authorization": f"Bearer {student_login.json()['access_token']}"}
    admin_headers = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}

    ticket_client.post(
        "/tickets",
        headers=student_headers,
        json={"original_question": "Need TOR", "description": ""},
    )
    response = ticket_client.get("/tickets", headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["total"] >= 1


def test_ticket_persistence_uses_postgres_not_json(ticket_client, tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.ticket_store_path", str(tmp_path / "tickets.json"))

    student_login = ticket_client.post(
        "/auth/login",
        json={"email": "student1@aska.local", "password": "student123"},
    )
    headers = {"Authorization": f"Bearer {student_login.json()['access_token']}"}

    created = ticket_client.post(
        "/tickets",
        headers=headers,
        json={"original_question": "Scholarship question", "description": ""},
    ).json()

    assert not (tmp_path / "tickets.json").exists()

    fetched = ticket_client.get(f"/tickets/{created['id']}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["id"] == created["id"]


def test_student_can_confirm_preferred_office(ticket_client):
    student_login = ticket_client.post(
        "/auth/login",
        json={"email": "student1@aska.local", "password": "student123"},
    )
    headers = {"Authorization": f"Bearer {student_login.json()['access_token']}"}

    offices = ticket_client.get("/tickets/offices", headers=headers)
    assert offices.status_code == 200
    osas = next(item for item in offices.json()["items"] if item["name"] == "Office of Student Affairs")

    created = ticket_client.post(
        "/tickets",
        headers=headers,
        json={
            "original_question": "How can I request a copy of my TOR?",
            "description": "Needed for employment",
            "preferred_office_id": osas["id"],
        },
    )
    assert created.status_code == 200
    ticket = created.json()
    assert ticket["assigned_office"] == "Office of Student Affairs"
    assert ticket["assigned_office_id"] == osas["id"]

    audit = ticket_client.get(f"/tickets/{ticket['id']}/audit", headers=headers)
    assert audit.status_code == 200
    actions = {item["action"] for item in audit.json()}
    assert "created" in actions
    assert "office_confirmed" in actions


def test_urgent_priority_from_strong_urgency_language(ticket_client):
    response = ticket_client.post(
        "/tickets/triage",
        json={
            "original_question": "URGENT emergency: portal is completely down and I cannot graduate",
            "description": "Need help ASAP",
        },
    )
    assert response.status_code == 200
    assert response.json()["priority"] == "Urgent"


def test_office_reply_creates_student_notification(ticket_client):
    student_login = ticket_client.post(
        "/auth/login",
        json={"email": "student1@aska.local", "password": "student123"},
    )
    office_login = ticket_client.post(
        "/auth/login",
        json={"email": "registrar@aska.local", "password": "office123"},
    )
    student_headers = {"Authorization": f"Bearer {student_login.json()['access_token']}"}
    office_headers = {"Authorization": f"Bearer {office_login.json()['access_token']}"}

    offices = ticket_client.get("/tickets/offices", headers=student_headers).json()["items"]
    registrar = next(item for item in offices if item["name"] == "Registrar")

    created = ticket_client.post(
        "/tickets",
        headers=student_headers,
        json={
            "original_question": "I need my TOR for scholarship.",
            "description": "",
            "preferred_office_id": registrar["id"],
        },
    ).json()
    assert created["assigned_office"] == "Registrar"

    patch = ticket_client.patch(
        f"/tickets/{created['id']}",
        headers=office_headers,
        json={"status": "In Progress"},
    )
    assert patch.status_code == 200
    reply = ticket_client.post(
        f"/tickets/{created['id']}/replies",
        headers=office_headers,
        json={"message": "Please visit the Registrar counter tomorrow."},
    )
    assert reply.status_code == 200

    notifications = ticket_client.get("/tickets/notifications", headers=student_headers)
    assert notifications.status_code == 200
    payload = notifications.json()
    assert payload["unread_count"] >= 1
    assert any(item["type"] == "ticket_reply" for item in payload["items"])


def test_student_can_upload_ticket_attachment(ticket_client, tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.ticket_attachments_dir", str(tmp_path / "attachments"))

    student_login = ticket_client.post(
        "/auth/login",
        json={"email": "student1@aska.local", "password": "student123"},
    )
    headers = {"Authorization": f"Bearer {student_login.json()['access_token']}"}

    created = ticket_client.post(
        "/tickets",
        headers=headers,
        json={"original_question": "Portal screenshot issue", "description": "See attached"},
    ).json()

    upload = ticket_client.post(
        f"/tickets/{created['id']}/attachments",
        headers=headers,
        files={"file": ("portal.png", b"fakepngbytes", "image/png")},
    )
    assert upload.status_code == 200
    assert upload.json()["original_filename"] == "portal.png"

    fetched = ticket_client.get(f"/tickets/{created['id']}", headers=headers)
    assert fetched.status_code == 200
    assert len(fetched.json()["attachments"]) == 1

    download = ticket_client.get(
        f"/tickets/{created['id']}/attachments/{upload.json()['id']}/download",
        headers=headers,
    )
    assert download.status_code == 200
    assert download.content == b"fakepngbytes"


def test_triage_rate_limit_returns_429(ticket_client, monkeypatch):
    from app.services import triage_rate_limit

    triage_rate_limit.reset_triage_rate_limits()

    import app.routes.tickets as tickets_routes

    def limited(key: str, *, limit: int = 3, window_seconds: int = 60) -> bool:
        return triage_rate_limit.check_triage_rate_limit(key, limit=limit, window_seconds=window_seconds)

    monkeypatch.setattr(tickets_routes, "check_triage_rate_limit", limited)

    body = {
        "original_question": "Where is the registrar?",
        "description": "",
    }
    assert ticket_client.post("/tickets/triage", json=body).status_code == 200
    assert ticket_client.post("/tickets/triage", json=body).status_code == 200
    assert ticket_client.post("/tickets/triage", json=body).status_code == 200
    assert ticket_client.post("/tickets/triage", json=body).status_code == 429
