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
from app.services.ticketing import _priority_for_text


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

    from app.services.auth_rate_limit import reset_auth_rate_limits
    from app.services.triage_rate_limit import reset_triage_rate_limits

    reset_auth_rate_limits()
    reset_triage_rate_limits()

    with session_factory() as session:
        _seed_offices_and_users(session)

    try:
        yield TestClient(app)
    finally:
        reset_auth_rate_limits()
        reset_triage_rate_limits()
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
        email_verified=True,
    )
    other_student = User(
        email="student2@aska.local",
        password_hash=hash_password("student123"),
        full_name="Other Student",
        role="student",
        student_id="2026-0002",
        email_verified=True,
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
    faculty = User(
        email="faculty1@aska.local",
        password_hash=hash_password("faculty123"),
        full_name="Faculty Member",
        role="faculty",
        email_verified=True,
    )
    session.add_all([student, other_student, ict_staff, registrar_staff, admin, faculty])
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


def _student_headers(ticket_client: TestClient) -> dict[str, str]:
    from app.services.auth_rate_limit import reset_auth_rate_limits

    reset_auth_rate_limits()
    login = ticket_client.post(
        "/auth/login",
        json={"email": "student1@aska.local", "password": "student123"},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_ticket_triage_requires_auth(ticket_client):
    response = ticket_client.post(
        "/tickets/triage",
        json={
            "original_question": "I cannot access my student portal account before enrollment.",
            "description": "",
        },
    )
    assert response.status_code == 401


def test_ticket_triage_detects_technical_high_priority(ticket_client):
    response = ticket_client.post(
        "/tickets/triage",
        headers=_student_headers(ticket_client),
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
        headers=_student_headers(ticket_client),
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
        json={
            "original_question": "Need help",
            "description": "I already tried the student portal and still need assistance.",
        },
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


def test_student_cannot_submit_unreadable_ticket_description(ticket_client):
    headers = _student_headers(ticket_client)
    response = ticket_client.post(
        "/tickets",
        headers=headers,
        json={
            "original_question": "How can i request Transcript of records?",
            "description": "SIHOFDDOASFNacfcxc mjhisc k x",
        },
    )
    assert response.status_code == 422
    detail = str(response.json().get("detail", "")).lower()
    assert "description" in detail or "words" in detail or "readable" in detail


def test_student_cannot_submit_empty_ticket_description(ticket_client):
    headers = _student_headers(ticket_client)
    response = ticket_client.post(
        "/tickets",
        headers=headers,
        json={
            "original_question": "How can I request my transcript of records?",
            "description": "",
        },
    )
    assert response.status_code == 422

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
        json={
            "original_question": "I need my TOR.",
            "description": "I already tried the student portal and still need assistance.",
        },
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
        json={
            "original_question": "I cannot login to the student portal.",
            "description": "I already tried the student portal and still need assistance.",
        },
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
        json={
            "original_question": "I cannot login to the student portal.",
            "description": "I already tried the student portal and still need assistance.",
        },
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
        json={
            "original_question": "I cannot login to the student portal.",
            "description": "I already tried the student portal and still need assistance.",
        },
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
        json={
            "original_question": "I need help with enrollment.",
            "description": "I already visited the office and still need enrollment help.",
        },
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
        json={
            "original_question": "Portal issue",
            "description": "I already tried the student portal and still need assistance.",
        },
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
        json={
            "original_question": "I need help with my TOR.",
            "description": "I already tried the student portal and still need assistance.",
        },
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
        json={
            "original_question": "Need TOR",
            "description": "I already tried the student portal and still need assistance.",
        },
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
        json={
            "original_question": "Scholarship question",
            "description": "I already tried the student portal and still need assistance.",
        },
    ).json()

    assert not (tmp_path / "tickets.json").exists()

    fetched = ticket_client.get(f"/tickets/{created['id']}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["id"] == created["id"]


def test_student_preferred_office_is_ignored(ticket_client):
    student_login = ticket_client.post(
        "/auth/login",
        json={"email": "student1@aska.local", "password": "student123"},
    )
    headers = {"Authorization": f"Bearer {student_login.json()['access_token']}"}

    offices = ticket_client.get("/tickets/offices", headers=headers)
    assert offices.status_code == 200
    osas = next(item for item in offices.json()["items"] if item["name"] == "Office of Student Affairs")

    triage = ticket_client.post(
        "/tickets/triage",
        headers=headers,
        json={
            "original_question": "How can I request a copy of my TOR?",
            "description": "I need this document for employment purposes.",
        },
    )
    assert triage.status_code == 200
    expected_office = triage.json()["assigned_office"]

    created = ticket_client.post(
        "/tickets",
        headers=headers,
        json={
            "original_question": "How can I request a copy of my TOR?",
            "description": "I need this document for employment purposes.",
            "preferred_office_id": osas["id"],
        },
    )
    assert created.status_code == 200
    ticket = created.json()
    assert ticket["assigned_office"] == expected_office

    audit = ticket_client.get(f"/tickets/{ticket['id']}/audit", headers=headers)
    assert audit.status_code == 200
    actions = {item["action"] for item in audit.json()}
    assert "created" in actions
    assert "office_confirmed" not in actions


def test_student_selected_office_is_honored(ticket_client):
    headers = _student_headers(ticket_client)

    offices = ticket_client.get("/tickets/offices", headers=headers)
    assert offices.status_code == 200
    all_offices = offices.json()["items"]

    triage = ticket_client.post(
        "/tickets/triage",
        headers=headers,
        json={
            "original_question": "How can I request a copy of my TOR?",
            "description": "I need this document for employment purposes.",
        },
    )
    assert triage.status_code == 200
    expected_office = triage.json()["assigned_office"]

    # Pick an office the auto-classifier would NOT have chosen, so a match
    # can only be explained by the explicit selection, not coincidence.
    target = next(item for item in all_offices if item["name"] != expected_office)

    created = ticket_client.post(
        "/tickets",
        headers=headers,
        json={
            "original_question": "How can I request a copy of my TOR?",
            "description": "I need this document for employment purposes.",
            "routing_method": "student_selected",
            "preferred_office_id": target["id"],
        },
    )
    assert created.status_code == 200
    ticket = created.json()
    assert ticket["assigned_office_id"] == target["id"]
    assert ticket["assigned_office"] == target["name"]
    assert ticket["assigned_office"] != expected_office  # not silently overwritten by the classifier

    audit = ticket_client.get(f"/tickets/{ticket['id']}/audit", headers=headers)
    assert audit.status_code == 200
    events = audit.json()
    confirmed = next(item for item in events if item["action"] == "office_confirmed")
    assert confirmed["new_value"] == target["name"]
    assert confirmed["actor_role"] == "student"  # distinguishes this from a staff confirmation


def test_student_selected_nonexistent_office_is_rejected(ticket_client):
    headers = _student_headers(ticket_client)

    created = ticket_client.post(
        "/tickets",
        headers=headers,
        json={
            "original_question": "How can I request a copy of my TOR?",
            "description": "I need this document for employment purposes.",
            "routing_method": "student_selected",
            "preferred_office_id": "00000000-0000-0000-0000-000000000000",
        },
    )
    assert created.status_code == 422


def test_student_cannot_use_fuzzy_office_name_for_direct_selection(ticket_client):
    """routing_method=student_selected with only preferred_office (a name,
    not an id) must NOT activate manual routing -- students are restricted
    to exact preferred_office_id selection only."""
    headers = _student_headers(ticket_client)

    triage = ticket_client.post(
        "/tickets/triage",
        headers=headers,
        json={
            "original_question": "How can I request a copy of my TOR?",
            "description": "I need this document for employment purposes.",
        },
    )
    expected_office = triage.json()["assigned_office"]

    created = ticket_client.post(
        "/tickets",
        headers=headers,
        json={
            "original_question": "How can I request a copy of my TOR?",
            "description": "I need this document for employment purposes.",
            "routing_method": "student_selected",
            "preferred_office": "Registrar",
        },
    )
    assert created.status_code == 200
    assert created.json()["assigned_office"] == expected_office  # fell through to automatic


def test_student_selected_office_visible_in_office_queue(ticket_client):
    student_headers = _student_headers(ticket_client)
    office_login = ticket_client.post(
        "/auth/login",
        json={"email": "registrar@aska.local", "password": "office123"},
    )
    assert office_login.status_code == 200
    office_headers = {"Authorization": f"Bearer {office_login.json()['access_token']}"}

    offices = ticket_client.get("/tickets/offices", headers=student_headers).json()["items"]
    registrar = next(item for item in offices if item["name"] == "Registrar")

    created = ticket_client.post(
        "/tickets",
        headers=student_headers,
        json={
            "original_question": "How can I request a copy of my TOR?",
            "description": "I need this document for employment purposes.",
            "routing_method": "student_selected",
            "preferred_office_id": registrar["id"],
        },
    )
    assert created.status_code == 200
    ticket_id = created.json()["id"]

    queue = ticket_client.get("/tickets", headers=office_headers)
    assert queue.status_code == 200
    assert any(item["id"] == ticket_id for item in queue.json()["items"])


def test_urgent_priority_from_strong_urgency_language(ticket_client):
    response = ticket_client.post(
        "/tickets/triage",
        headers=_student_headers(ticket_client),
        json={
            "original_question": "URGENT emergency: portal is completely down and I cannot graduate",
            "description": "I need urgent help with the portal outage.",
        },
    )
    assert response.status_code == 200
    assert response.json()["priority"] == "Urgent"


# ---------------------------------------------------------------------------
# ASKA-PIYU MINIMAL TICKET ROUTING FIX -- FIX 1: priority self-escalation
#
# Unit-level regression tests against _priority_for_text directly (same
# direct-import pattern already used for triage_ticket in
# tests/test_ticket_office_resolver.py), so these are deterministic and
# independent of taxonomy/office classification.
# ---------------------------------------------------------------------------


def test_mundane_lone_urgent_word_is_not_urgent():
    """A single self-declared 'urgent' with no real severity/blocker must
    not alone escalate a mundane ticket to Urgent."""
    priority = _priority_for_text(
        "I have an urgent question about the library hours "
        "Just wondering what time the library opens on Saturdays, urgent to know."
    )
    assert priority != "Urgent"


def test_lone_asap_and_emergency_words_are_not_urgent():
    """'asap' and 'emergency' are self-declared urgency words too -- alone,
    with no severe condition or corroborating blocker, they must not
    escalate a ticket to Urgent."""
    assert _priority_for_text("Please process this ASAP, thank you.") != "Urgent"
    assert _priority_for_text("This is an emergency, please respond.") != "Urgent"


def test_repeated_urgent_word_alone_is_not_urgent():
    """Repeating the same urgency word must not increase severity -- a
    ticket that is only 'urgent urgent urgent' must not become Urgent
    from repetition alone."""
    priority = _priority_for_text(
        "urgent urgent urgent urgent urgent please help "
        "urgent urgent urgent urgent urgent urgent urgent urgent"
    )
    assert priority != "Urgent"


def test_genuine_severe_outage_is_urgent():
    """A genuinely severe situation (system-wide outage) must still reach
    Urgent on its own, without needing self-declared urgency language."""
    assert _priority_for_text(
        "Our whole campus system is down, this is a system outage. "
        "Nobody can access anything right now."
    ) == "Urgent"


def test_genuine_graduation_blocker_is_urgent():
    """A genuine hard blocker (cannot graduate) must still reach Urgent on
    its own."""
    assert _priority_for_text(
        "I cannot graduate this term because of a missing clearance."
    ) == "Urgent"


def test_locked_out_is_urgent():
    """A genuine access lockout must still reach Urgent on its own."""
    assert _priority_for_text(
        "I am locked out of my account and cannot do anything."
    ) == "Urgent"


def test_urgency_word_with_corroborating_high_blocker_is_urgent():
    """Self-declared urgency language combined with an independent
    High-tier blocker signal (not merely repeating the urgency word) must
    still reach Urgent, preserving legitimate existing behavior."""
    assert _priority_for_text(
        "URGENT: I cannot log in to my account, it shows invalid credentials."
    ) == "Urgent"


def test_existing_priority_behavior_still_passes():
    """Existing priority-relevant behavior (unaffected mundane/High/Low
    cases) must keep working after the Fix 1 rewrite."""
    assert _priority_for_text(
        "I cannot access my student portal account before enrollment."
    ) == "High"
    assert _priority_for_text(
        "I cannot log in to my student portal. Correct student number and "
        "password, still shows invalid credentials. Need access for enrollment."
    ) == "High"
    assert _priority_for_text("I need help with enrollment.") != "Urgent"


def test_faculty_can_list_and_open_own_tickets(ticket_client):
    faculty_login = ticket_client.post(
        "/auth/login",
        json={"email": "faculty1@aska.local", "password": "faculty123"},
    )
    headers = {"Authorization": f"Bearer {faculty_login.json()['access_token']}"}

    created = ticket_client.post(
        "/tickets",
        headers=headers,
        json={
            "original_question": "How do I request teaching load adjustment?",
            "description": "Need guidance for faculty load.",
        },
    )
    assert created.status_code == 200
    ticket_id = created.json()["id"]

    listed = ticket_client.get("/tickets", headers=headers)
    assert listed.status_code == 200
    assert any(item["id"] == ticket_id for item in listed.json()["items"])

    fetched = ticket_client.get(f"/tickets/{ticket_id}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["id"] == ticket_id


def test_requester_preferred_urgent_priority_is_ignored(ticket_client):
    headers = _student_headers(ticket_client)
    response = ticket_client.post(
        "/tickets",
        headers=headers,
        json={
            "original_question": "I need help with enrollment.",
            "description": "Please assist with my enrollment concern today.",
            "preferred_priority": "Urgent",
        },
    )
    assert response.status_code == 200
    assert response.json()["priority"] != "Urgent"


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
            "description": "I already tried the student portal and still need assistance.",
        },
    ).json()

    if created["assigned_office_id"] != registrar["id"]:
        reassigned = ticket_client.patch(
            f"/tickets/{created['id']}",
            headers=office_headers,
            json={"assigned_office_id": registrar["id"]},
        )
        # Office can only reassign tickets already on their queue; use admin if needed.
        if reassigned.status_code != 200:
            admin_login = ticket_client.post(
                "/auth/login",
                json={"email": "admin@aska.local", "password": "admin123"},
            )
            admin_headers = {
                "Authorization": f"Bearer {admin_login.json()['access_token']}"
            }
            reassigned = ticket_client.patch(
                f"/tickets/{created['id']}",
                headers=admin_headers,
                json={"assigned_office_id": registrar["id"]},
            )
        assert reassigned.status_code == 200
        created = reassigned.json()
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
        json={
            "original_question": "Portal screenshot issue",
            "description": "Please review the attached screenshot of the portal error.",
        },
    ).json()

    png_bytes = b"\x89PNG\r\n\x1a\n" + b"fakepngbytes"
    upload = ticket_client.post(
        f"/tickets/{created['id']}/attachments",
        headers=headers,
        files={"file": ("portal.png", png_bytes, "image/png")},
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
    assert download.content == png_bytes


def test_triage_rate_limit_returns_429(ticket_client, monkeypatch):
    from app.services import triage_rate_limit

    triage_rate_limit.reset_triage_rate_limits()

    import app.routes.tickets as tickets_routes

    def limited(key: str, *, limit: int = 3, window_seconds: int = 60) -> bool:
        return triage_rate_limit.check_triage_rate_limit(key, limit=limit, window_seconds=window_seconds)

    monkeypatch.setattr(tickets_routes, "check_triage_rate_limit", limited)

    headers = _student_headers(ticket_client)
    body = {
        "original_question": "Where is the registrar?",
        "description": "",
    }
    assert ticket_client.post("/tickets/triage", headers=headers, json=body).status_code == 200
    assert ticket_client.post("/tickets/triage", headers=headers, json=body).status_code == 200
    assert ticket_client.post("/tickets/triage", headers=headers, json=body).status_code == 200
    assert ticket_client.post("/tickets/triage", headers=headers, json=body).status_code == 429


# ---------------------------------------------------------------------------
# ASKA-PIYU — FIX NULL-OFFICE ROUTING BLOCKER
#
# The ticket_client fixture seeds only three offices (ICT Office, Registrar,
# Office of Student Affairs — see _seed_offices_and_users above), which does
# not include "Admissions Office". A question about admission requirements
# reliably classifies to the specific (non-"General") "Admissions" category
# with taxonomy office "Admissions Office" (confirmed via the real
# classify_question during this fix), so in this fixture it is guaranteed to
# be an unresolved-specific-office ticket: assigned_office_id is None and
# assigned_office is the raw taxonomy label, not silently "Office of Student
# Affairs". These tests exercise the full HTTP lifecycle for that case.
# ---------------------------------------------------------------------------

_UNRESOLVED_OFFICE_SUBJECT = "What are the admission requirements for incoming freshmen?"
_UNRESOLVED_OFFICE_DESCRIPTION = (
    "Asking about the documentary requirements for new student applicants."
)


def _admin_headers(ticket_client: TestClient) -> dict[str, str]:
    login = ticket_client.post(
        "/auth/login",
        json={"email": "admin@aska.local", "password": "admin123"},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _ict_headers(ticket_client: TestClient) -> dict[str, str]:
    login = ticket_client.post(
        "/auth/login",
        json={"email": "ict@aska.local", "password": "office123"},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _registrar_headers(ticket_client: TestClient) -> dict[str, str]:
    login = ticket_client.post(
        "/auth/login",
        json={"email": "registrar@aska.local", "password": "office123"},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _create_unresolved_office_ticket(ticket_client: TestClient) -> dict:
    headers = _student_headers(ticket_client)
    response = ticket_client.post(
        "/tickets",
        headers=headers,
        json={
            "original_question": _UNRESOLVED_OFFICE_SUBJECT,
            "description": _UNRESOLVED_OFFICE_DESCRIPTION,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_unresolved_specific_office_ticket_creation_succeeds_and_is_flagged(ticket_client):
    """Creating a ticket whose classified office (Admissions Office) isn't
    seeded must still succeed (not 503/500), and the response must make the
    unresolved state explicit rather than masquerading as a normal
    assignment."""
    ticket = _create_unresolved_office_ticket(ticket_client)

    assert ticket["category"] != "General"
    assert ticket["assigned_office_id"] is None
    assert ticket["assigned_office"] == "Admissions Office"
    assert ticket["needs_manual_routing"] is True


def test_unresolved_specific_office_ticket_visible_to_admin_not_to_office(ticket_client):
    """Admin must see the unresolved ticket (flagged); office queues must
    not receive it, since it was never actually assigned to them."""
    ticket = _create_unresolved_office_ticket(ticket_client)

    admin_listing = ticket_client.get("/tickets", headers=_admin_headers(ticket_client))
    assert admin_listing.status_code == 200
    admin_items = {item["id"]: item for item in admin_listing.json()["items"]}
    assert ticket["id"] in admin_items
    assert admin_items[ticket["id"]]["needs_manual_routing"] is True
    assert admin_items[ticket["id"]]["assigned_office_id"] is None

    ict_listing = ticket_client.get("/tickets", headers=_ict_headers(ticket_client))
    assert ict_listing.status_code == 200
    assert ticket["id"] not in {item["id"] for item in ict_listing.json()["items"]}

    registrar_listing = ticket_client.get("/tickets", headers=_registrar_headers(ticket_client))
    assert registrar_listing.status_code == 200
    assert ticket["id"] not in {item["id"] for item in registrar_listing.json()["items"]}


def test_admin_can_recover_unresolved_ticket_with_real_office_id(ticket_client):
    """Admin recovers an unresolved ticket by assigning a REAL office id
    (not the raw taxonomy label); the office can then see it."""
    ticket = _create_unresolved_office_ticket(ticket_client)
    admin_headers = _admin_headers(ticket_client)

    offices = ticket_client.get("/tickets/offices", headers=admin_headers).json()["items"]
    registrar = next(item for item in offices if item["name"] == "Registrar")

    response = ticket_client.patch(
        f"/tickets/{ticket['id']}",
        headers=admin_headers,
        json={"assigned_office_id": registrar["id"]},
    )
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["assigned_office_id"] == registrar["id"]
    assert updated["assigned_office"] == "Registrar"
    assert updated["needs_manual_routing"] is False

    registrar_listing = ticket_client.get("/tickets", headers=_registrar_headers(ticket_client))
    assert ticket["id"] in {item["id"] for item in registrar_listing.json()["items"]}


def test_admin_resending_raw_unresolved_label_does_not_silently_become_osa(ticket_client):
    """Re-submitting the SAME raw unresolved taxonomy label through the
    string-based assigned_office field (e.g. an admin form re-saving the
    ticket's currently-displayed office text without changing it) must be
    rejected explicitly, never silently accepted as if it resolved to OSA."""
    ticket = _create_unresolved_office_ticket(ticket_client)
    admin_headers = _admin_headers(ticket_client)

    response = ticket_client.patch(
        f"/tickets/{ticket['id']}",
        headers=admin_headers,
        json={"assigned_office": "Admissions Office"},
    )
    assert response.status_code == 422, response.text

    fetched = ticket_client.get(f"/tickets/{ticket['id']}", headers=admin_headers)
    assert fetched.status_code == 200
    refetched = fetched.json()
    assert refetched["assigned_office_id"] is None
    assert refetched["assigned_office"] == "Admissions Office"
    assert "Student Affairs" not in refetched["assigned_office"]
    assert refetched["needs_manual_routing"] is True


def test_general_fallback_still_goes_to_osa_and_is_not_flagged(ticket_client):
    """A genuinely unclassified/General question must still default to OSA
    with a real resolved office id -- unaffected by this fix. Uses
    /tickets/triage (like the existing priority/office triage tests above)
    since the nonsense text needed to force a genuine classifier miss would
    otherwise be rejected by the unrelated ticket-description readability
    gate in create_ticket, which is not what this test is checking."""
    headers = _student_headers(ticket_client)
    response = ticket_client.post(
        "/tickets/triage",
        headers=headers,
        json={
            "original_question": "asdkjf qwoeiru zxksldjf mnbvqwer",
            "description": "zxcvbnmasdfghjklqwertyuiop random unclassifiable text",
        },
    )
    assert response.status_code == 200, response.text
    triage = response.json()
    assert triage["category"] == "General"
    assert triage["assigned_office_id"] is not None
    assert "Student Affairs" in triage["assigned_office"] or "OSA" in triage["assigned_office"]
