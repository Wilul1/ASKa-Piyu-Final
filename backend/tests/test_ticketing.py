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
    # A staff reply to an Open ticket auto-advances it to In Progress -- no
    # separate PATCH needed (and office staff can no longer PATCH status
    # directly at all, see test_office_cannot_patch_status_directly).
    resolved_response = ticket_client.post(
        f"/tickets/{created['id']}/resolve",
        headers=ict_headers,
    )

    assert reply_response.status_code == 200
    assert reply_response.json()["messages"][0]["sender_role"] == "office"
    assert reply_response.json()["replies_count"] == 1
    assert reply_response.json()["latest_reply_preview"]
    assert reply_response.json()["status"] == "In Progress"
    assert resolved_response.status_code == 200
    assert resolved_response.json()["status"] == "Resolved"
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
    student_headers = {"Authorization": f"Bearer {student_login.json()['access_token']}"}

    created = ticket_client.post(
        "/tickets",
        headers=student_headers,
        json={
            "original_question": "Portal issue",
            "description": "I already tried the student portal and still need assistance.",
        },
    ).json()
    # Office staff can no longer set status via PATCH at all; Close is now
    # a dedicated admin-only action.
    close_response = ticket_client.post(
        f"/tickets/{created['id']}/close",
        headers=_admin_headers(ticket_client),
    )
    assert close_response.status_code == 200
    assert close_response.json()["status"] == "Closed"

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

    # Office staff can no longer PATCH status directly -- replying while
    # Open auto-advances it to In Progress (see below).
    reply = ticket_client.post(
        f"/tickets/{created['id']}/replies",
        headers=office_headers,
        json={"message": "Please visit the Registrar counter tomorrow."},
    )
    assert reply.status_code == 200
    assert reply.json()["status"] == "In Progress"

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


# --- internal-note privacy fix (is_internal full path) -----------------------
#
# Reuses the same "I cannot login to the student portal." question already
# proven elsewhere in this file (test_office_can_reply_and_resolve_ticket,
# test_office_cannot_view_other_office_ticket) to classify to ICT Office, so
# _ict_headers is always the "authorized destination office" and
# _registrar_headers is always an unauthorized "other office" throughout
# this section.

_INTERNAL_NOTE_TEXT = "Escalate to the Registrar quietly before replying to the student."
_PUBLIC_REPLY_TEXT = "Please visit the ICT office with your student ID."


def _create_ict_ticket(ticket_client: TestClient) -> dict:
    response = ticket_client.post(
        "/tickets",
        headers=_student_headers(ticket_client),
        json={
            "original_question": "I cannot login to the student portal.",
            "description": "I already tried the student portal and still need assistance.",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _post_internal_reply(ticket_client: TestClient, ticket_id: str) -> dict:
    response = ticket_client.post(
        f"/tickets/{ticket_id}/replies",
        headers=_ict_headers(ticket_client),
        json={"message": _INTERNAL_NOTE_TEXT, "is_internal": True},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_internal_reply_is_stored_with_is_internal_true(ticket_client):
    ticket = _create_ict_ticket(ticket_client)
    reply = _post_internal_reply(ticket_client, ticket["id"])

    # ICT (the assigned office) is authorized to see it, and it must be
    # correctly flagged in their own view.
    internal_messages = [m for m in reply["messages"] if m["message"] == _INTERNAL_NOTE_TEXT]
    assert len(internal_messages) == 1
    assert internal_messages[0]["is_internal"] is True


def test_public_reply_still_visible_with_is_internal_false(ticket_client):
    """Preserve existing behavior for ordinary public replies -- same
    request/response shape as test_office_can_reply_and_resolve_ticket,
    plus the new is_internal field defaulting to False."""
    ticket = _create_ict_ticket(ticket_client)
    reply = ticket_client.post(
        f"/tickets/{ticket['id']}/replies",
        headers=_ict_headers(ticket_client),
        json={"message": _PUBLIC_REPLY_TEXT},
    )
    assert reply.status_code == 200, reply.text
    data = reply.json()
    assert data["messages"][0]["sender_role"] == "office"
    assert data["messages"][0]["is_internal"] is False
    assert data["replies_count"] == 1
    assert data["latest_reply_preview"]


def test_student_cannot_see_internal_note_in_ticket_detail(ticket_client):
    ticket = _create_ict_ticket(ticket_client)
    _post_internal_reply(ticket_client, ticket["id"])

    fetched = ticket_client.get(
        f"/tickets/{ticket['id']}", headers=_student_headers(ticket_client)
    )
    assert fetched.status_code == 200
    data = fetched.json()
    assert all(m["message"] != _INTERNAL_NOTE_TEXT for m in data["messages"])
    assert data["replies_count"] == 0
    assert data["latest_reply_preview"] is None


def test_student_cannot_see_internal_note_in_ticket_list(ticket_client):
    ticket = _create_ict_ticket(ticket_client)
    _post_internal_reply(ticket_client, ticket["id"])

    listing = ticket_client.get("/tickets", headers=_student_headers(ticket_client))
    assert listing.status_code == 200
    item = next(row for row in listing.json()["items"] if row["id"] == ticket["id"])
    assert all(m["message"] != _INTERNAL_NOTE_TEXT for m in item["messages"])
    assert item["replies_count"] == 0


def test_student_cannot_see_internal_note_in_audit_history(ticket_client):
    """The /audit endpoint re-uses the same ticket-visibility check as the
    ticket itself (no separate per-viewer filtering of audit rows), so the
    internal note's content must never be written into an audit event at
    all -- not just hidden from this response, but never present in it."""
    ticket = _create_ict_ticket(ticket_client)
    _post_internal_reply(ticket_client, ticket["id"])

    audit = ticket_client.get(
        f"/tickets/{ticket['id']}/audit", headers=_student_headers(ticket_client)
    )
    assert audit.status_code == 200
    for event in audit.json():
        assert _INTERNAL_NOTE_TEXT not in (event.get("old_value") or "")
        assert _INTERNAL_NOTE_TEXT not in (event.get("new_value") or "")


def test_student_notification_does_not_contain_internal_note_text(ticket_client):
    ticket = _create_ict_ticket(ticket_client)
    _post_internal_reply(ticket_client, ticket["id"])

    notifications = ticket_client.get(
        "/tickets/notifications", headers=_student_headers(ticket_client)
    )
    assert notifications.status_code == 200
    items = notifications.json()["items"]
    for item in items:
        assert _INTERNAL_NOTE_TEXT not in item["title"]
        assert _INTERNAL_NOTE_TEXT not in item["body"]
    # No "new reply" notification at all for an internal-only note -- the
    # requester must not even be told a reply happened, since that reply
    # was never meant for them.
    assert not any(
        item["type"] == "ticket_reply" and item["ticket_id"] == ticket["id"]
        for item in items
    )


def test_office_staff_of_assigned_office_can_see_internal_note(ticket_client):
    ticket = _create_ict_ticket(ticket_client)
    _post_internal_reply(ticket_client, ticket["id"])

    fetched = ticket_client.get(
        f"/tickets/{ticket['id']}", headers=_ict_headers(ticket_client)
    )
    assert fetched.status_code == 200
    data = fetched.json()
    internal_messages = [m for m in data["messages"] if m["message"] == _INTERNAL_NOTE_TEXT]
    assert len(internal_messages) == 1
    assert internal_messages[0]["is_internal"] is True
    assert data["replies_count"] == 1


def test_admin_can_see_internal_note(ticket_client):
    ticket = _create_ict_ticket(ticket_client)
    _post_internal_reply(ticket_client, ticket["id"])

    fetched = ticket_client.get(
        f"/tickets/{ticket['id']}", headers=_admin_headers(ticket_client)
    )
    assert fetched.status_code == 200
    internal_messages = [
        m for m in fetched.json()["messages"] if m["message"] == _INTERNAL_NOTE_TEXT
    ]
    assert len(internal_messages) == 1
    assert internal_messages[0]["is_internal"] is True


def test_unauthorized_office_cannot_view_ticket_or_its_internal_notes(ticket_client):
    """An office other than the one assigned to the ticket must still be
    denied entirely (pre-existing boundary, re-confirmed here with an
    internal note present) -- it must never reach a point where it could
    see the internal note either."""
    ticket = _create_ict_ticket(ticket_client)
    _post_internal_reply(ticket_client, ticket["id"])

    response = ticket_client.get(
        f"/tickets/{ticket['id']}", headers=_registrar_headers(ticket_client)
    )
    assert response.status_code == 403

    listing = ticket_client.get("/tickets", headers=_registrar_headers(ticket_client))
    assert listing.status_code == 200
    assert ticket["id"] not in {row["id"] for row in listing.json()["items"]}


def test_student_cannot_mark_their_own_reply_internal(ticket_client):
    """is_internal is a staff-only authoring tool -- a student payload
    setting it must be silently ignored, never actually hide the student's
    own reply from themselves or from staff."""
    ticket = _create_ict_ticket(ticket_client)
    reply = ticket_client.post(
        f"/tickets/{ticket['id']}/replies",
        headers=_student_headers(ticket_client),
        json={"message": "Trying to hide this.", "is_internal": True},
    )
    assert reply.status_code == 200, reply.text
    data = reply.json()
    student_messages = [m for m in data["messages"] if m["message"] == "Trying to hide this."]
    assert len(student_messages) == 1
    assert student_messages[0]["is_internal"] is False

    # Visible to the office too, confirming it was never actually internal.
    fetched = ticket_client.get(
        f"/tickets/{ticket['id']}", headers=_ict_headers(ticket_client)
    )
    assert any(m["message"] == "Trying to hide this." for m in fetched.json()["messages"])


# --- status workflow (Phase 2) -----------------------------------------------
#
# Reuses _create_ict_ticket/_ict_headers/_registrar_headers/_student_headers/
# _admin_headers from the sections above -- a freshly created ticket always
# starts Open and classifies to ICT Office.


def test_new_ticket_starts_open(ticket_client):
    ticket = _create_ict_ticket(ticket_client)
    assert ticket["status"] == "Open"


def test_staff_reply_moves_open_ticket_to_in_progress(ticket_client):
    ticket = _create_ict_ticket(ticket_client)
    reply = ticket_client.post(
        f"/tickets/{ticket['id']}/replies",
        headers=_ict_headers(ticket_client),
        json={"message": _PUBLIC_REPLY_TEXT},
    )
    assert reply.status_code == 200, reply.text
    assert reply.json()["status"] == "In Progress"


def test_admin_reply_also_moves_open_ticket_to_in_progress(ticket_client):
    ticket = _create_ict_ticket(ticket_client)
    reply = ticket_client.post(
        f"/tickets/{ticket['id']}/replies",
        headers=_admin_headers(ticket_client),
        json={"message": "An admin can act on any ticket."},
    )
    assert reply.status_code == 200, reply.text
    assert reply.json()["status"] == "In Progress"


def test_student_reply_to_resolved_ticket_does_not_reopen_it(ticket_client):
    ticket = _create_ict_ticket(ticket_client)
    ticket_client.post(
        f"/tickets/{ticket['id']}/replies",
        headers=_ict_headers(ticket_client),
        json={"message": _PUBLIC_REPLY_TEXT},
    )
    resolved = ticket_client.post(
        f"/tickets/{ticket['id']}/resolve", headers=_ict_headers(ticket_client)
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "Resolved"

    student_reply = ticket_client.post(
        f"/tickets/{ticket['id']}/replies",
        headers=_student_headers(ticket_client),
        json={"message": "Thank you, one more question though."},
    )
    assert student_reply.status_code == 200, student_reply.text
    assert student_reply.json()["status"] == "Resolved"
    assert student_reply.json()["resolved_at"] is not None


def test_resolve_action_works_for_authorized_office_staff(ticket_client):
    ticket = _create_ict_ticket(ticket_client)
    response = ticket_client.post(
        f"/tickets/{ticket['id']}/resolve", headers=_ict_headers(ticket_client)
    )
    assert response.status_code == 200
    assert response.json()["status"] == "Resolved"
    assert response.json()["resolved_at"] is not None


def test_resolve_action_works_for_admin(ticket_client):
    ticket = _create_ict_ticket(ticket_client)
    response = ticket_client.post(
        f"/tickets/{ticket['id']}/resolve", headers=_admin_headers(ticket_client)
    )
    assert response.status_code == 200
    assert response.json()["status"] == "Resolved"


def test_resolve_rejects_an_unauthorized_other_office(ticket_client):
    ticket = _create_ict_ticket(ticket_client)
    response = ticket_client.post(
        f"/tickets/{ticket['id']}/resolve", headers=_registrar_headers(ticket_client)
    )
    assert response.status_code == 403


def test_resolve_rejects_the_requester(ticket_client):
    ticket = _create_ict_ticket(ticket_client)
    response = ticket_client.post(
        f"/tickets/{ticket['id']}/resolve", headers=_student_headers(ticket_client)
    )
    assert response.status_code == 403


def test_resolve_rejects_an_already_resolved_ticket_with_clear_error(ticket_client):
    ticket = _create_ict_ticket(ticket_client)
    first = ticket_client.post(
        f"/tickets/{ticket['id']}/resolve", headers=_ict_headers(ticket_client)
    )
    assert first.status_code == 200
    second = ticket_client.post(
        f"/tickets/{ticket['id']}/resolve", headers=_ict_headers(ticket_client)
    )
    assert second.status_code == 422
    assert "Resolved" in second.json()["detail"]


def test_only_admin_can_close(ticket_client):
    ticket = _create_ict_ticket(ticket_client)

    for headers in (
        _ict_headers(ticket_client),
        _registrar_headers(ticket_client),
        _student_headers(ticket_client),
    ):
        response = ticket_client.post(f"/tickets/{ticket['id']}/close", headers=headers)
        assert response.status_code == 403

    admin_response = ticket_client.post(
        f"/tickets/{ticket['id']}/close", headers=_admin_headers(ticket_client)
    )
    assert admin_response.status_code == 200
    assert admin_response.json()["status"] == "Closed"
    assert admin_response.json()["closed_at"] is not None


def test_close_is_idempotent_for_an_already_closed_ticket(ticket_client):
    ticket = _create_ict_ticket(ticket_client)
    admin_headers = _admin_headers(ticket_client)
    first = ticket_client.post(f"/tickets/{ticket['id']}/close", headers=admin_headers)
    assert first.status_code == 200
    second = ticket_client.post(f"/tickets/{ticket['id']}/close", headers=admin_headers)
    assert second.status_code == 200
    assert second.json()["status"] == "Closed"


def test_generic_patch_cannot_set_status_for_office_or_student(ticket_client):
    ticket = _create_ict_ticket(ticket_client)

    office_attempt = ticket_client.patch(
        f"/tickets/{ticket['id']}",
        headers=_ict_headers(ticket_client),
        json={"status": "In Progress"},
    )
    assert office_attempt.status_code == 403

    student_attempt = ticket_client.patch(
        f"/tickets/{ticket['id']}",
        headers=_student_headers(ticket_client),
        json={"status": "In Progress"},
    )
    assert student_attempt.status_code == 403

    # Confirmed still Open -- neither forbidden attempt silently applied.
    fetched = ticket_client.get(
        f"/tickets/{ticket['id']}", headers=_student_headers(ticket_client)
    )
    assert fetched.json()["status"] == "Open"


def test_admin_can_still_patch_status_directly(ticket_client):
    """Admin's generic-PATCH status capability is intentionally unchanged
    by this phase."""
    ticket = _create_ict_ticket(ticket_client)
    response = ticket_client.patch(
        f"/tickets/{ticket['id']}",
        headers=_admin_headers(ticket_client),
        json={"status": "In Progress"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "In Progress"


def test_failed_reply_on_closed_ticket_never_changes_status(ticket_client):
    ticket = _create_ict_ticket(ticket_client)
    admin_headers = _admin_headers(ticket_client)
    closed = ticket_client.post(f"/tickets/{ticket['id']}/close", headers=admin_headers)
    assert closed.status_code == 200

    failed_reply = ticket_client.post(
        f"/tickets/{ticket['id']}/replies",
        headers=_student_headers(ticket_client),
        json={"message": "One more question"},
    )
    assert failed_reply.status_code == 422

    fetched = ticket_client.get(f"/tickets/{ticket['id']}", headers=admin_headers)
    assert fetched.json()["status"] == "Closed"


def test_admin_immediate_reassignment_still_works_and_is_audited(ticket_client):
    """Admin's separate immediate office-reassignment override (distinct
    from the Resolve/Close actions above) and its audit logging are
    unchanged by this phase -- re-confirmed here alongside the new status
    rules, on top of the pre-existing test_admin_can_reassign_ticket."""
    ticket = _create_ict_ticket(ticket_client)
    admin_headers = _admin_headers(ticket_client)
    offices = ticket_client.get("/tickets/offices", headers=admin_headers).json()["items"]
    registrar = next(item for item in offices if item["name"] == "Registrar")

    response = ticket_client.patch(
        f"/tickets/{ticket['id']}",
        headers=admin_headers,
        json={"assigned_office_id": registrar["id"]},
    )
    assert response.status_code == 200
    assert response.json()["assigned_office"] == "Registrar"

    audit = ticket_client.get(f"/tickets/{ticket['id']}/audit", headers=admin_headers)
    assert audit.status_code == 200
    assert any(event["action"] == "office_reassigned" for event in audit.json())


# --- office-to-office ticket transfer requests (Phase 3) --------------------
#
# Reuses _create_ict_ticket/_ict_headers/_registrar_headers/_student_headers/
# _admin_headers from the sections above. Every ticket created this way
# starts assigned to ICT Office, so ICT is always the "source" office and
# Registrar is always one valid "destination" office throughout this
# section. "Office of Student Affairs" (seeded but with no staff user) is
# used specifically to prove the destination is not limited to an
# allowlisted pair of offices -- admin can still decide a transfer to it.

_TRANSFER_REASON = "Portal login issue is actually a records-correction request."


def _office_id_by_name(ticket_client: TestClient, headers: dict[str, str], name: str) -> str:
    offices = ticket_client.get("/tickets/offices", headers=headers).json()["items"]
    return next(item["id"] for item in offices if item["name"] == name)


def _request_transfer(
    ticket_client: TestClient,
    ticket_id: str,
    *,
    headers: dict[str, str],
    destination_office_id: str,
    reason: str = _TRANSFER_REASON,
):
    return ticket_client.post(
        f"/tickets/{ticket_id}/transfers",
        headers=headers,
        json={"destination_office_id": destination_office_id, "reason": reason},
    )


def test_office_can_request_transfer_of_its_own_ticket(ticket_client):
    ticket = _create_ict_ticket(ticket_client)
    ict_headers = _ict_headers(ticket_client)
    registrar_id = _office_id_by_name(ticket_client, ict_headers, "Registrar")

    response = _request_transfer(
        ticket_client, ticket["id"], headers=ict_headers, destination_office_id=registrar_id
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "Pending"
    assert body["ticket_id"] == ticket["id"]
    assert body["destination_office_name"] == "Registrar"
    assert body["source_office_name"] == "ICT Office"
    assert body["reason"] == _TRANSFER_REASON
    assert body["decided_at"] is None
    assert body["decided_by_user_id"] is None


def test_admin_can_request_transfer_on_behalf_of_the_source_office(ticket_client):
    ticket = _create_ict_ticket(ticket_client)
    admin_headers = _admin_headers(ticket_client)
    registrar_id = _office_id_by_name(ticket_client, admin_headers, "Registrar")

    response = _request_transfer(
        ticket_client, ticket["id"], headers=admin_headers, destination_office_id=registrar_id
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "Pending"


def test_pending_transfer_request_does_not_change_ticket_assignment(ticket_client):
    ticket = _create_ict_ticket(ticket_client)
    ict_headers = _ict_headers(ticket_client)
    registrar_id = _office_id_by_name(ticket_client, ict_headers, "Registrar")

    _request_transfer(
        ticket_client, ticket["id"], headers=ict_headers, destination_office_id=registrar_id
    )

    fetched = ticket_client.get(f"/tickets/{ticket['id']}", headers=ict_headers)
    assert fetched.status_code == 200
    assert fetched.json()["assigned_office"] == "ICT Office"
    assert fetched.json()["assigned_office_id"] != registrar_id
    assert fetched.json()["status"] == "Open"


def test_transfer_request_can_target_any_existing_office_not_just_an_allowlist(ticket_client):
    """Office of Student Affairs is neither the ticket's source office nor
    one of the two offices otherwise exercised in this file -- proving the
    destination is validated against the real offices table, not a
    hardcoded allowlist."""
    ticket = _create_ict_ticket(ticket_client)
    ict_headers = _ict_headers(ticket_client)
    osas_id = _office_id_by_name(ticket_client, ict_headers, "Office of Student Affairs")

    response = _request_transfer(
        ticket_client, ticket["id"], headers=ict_headers, destination_office_id=osas_id
    )
    assert response.status_code == 200, response.text
    assert response.json()["destination_office_name"] == "Office of Student Affairs"


def test_transfer_request_rejects_nonexistent_destination(ticket_client):
    ticket = _create_ict_ticket(ticket_client)
    ict_headers = _ict_headers(ticket_client)

    response = _request_transfer(
        ticket_client, ticket["id"], headers=ict_headers, destination_office_id="not-a-real-office-id"
    )
    assert response.status_code == 422


def test_transfer_request_rejects_same_office_transfer(ticket_client):
    ticket = _create_ict_ticket(ticket_client)
    ict_headers = _ict_headers(ticket_client)
    ict_id = _office_id_by_name(ticket_client, ict_headers, "ICT Office")

    response = _request_transfer(
        ticket_client, ticket["id"], headers=ict_headers, destination_office_id=ict_id
    )
    assert response.status_code == 422


def test_transfer_request_rejects_empty_reason(ticket_client):
    ticket = _create_ict_ticket(ticket_client)
    ict_headers = _ict_headers(ticket_client)
    registrar_id = _office_id_by_name(ticket_client, ict_headers, "Registrar")

    response = _request_transfer(
        ticket_client, ticket["id"], headers=ict_headers, destination_office_id=registrar_id, reason="   "
    )
    assert response.status_code in (400, 422)


def test_transfer_request_rejects_an_unauthorized_other_office(ticket_client):
    ticket = _create_ict_ticket(ticket_client)
    registrar_headers = _registrar_headers(ticket_client)
    registrar_id = _office_id_by_name(ticket_client, registrar_headers, "Registrar")

    response = _request_transfer(
        ticket_client, ticket["id"], headers=registrar_headers, destination_office_id=registrar_id
    )
    assert response.status_code == 403


def test_transfer_request_rejects_the_requester(ticket_client):
    ticket = _create_ict_ticket(ticket_client)
    student_headers = _student_headers(ticket_client)
    registrar_id = _office_id_by_name(ticket_client, student_headers, "Registrar")

    response = _request_transfer(
        ticket_client, ticket["id"], headers=student_headers, destination_office_id=registrar_id
    )
    assert response.status_code == 403


def test_duplicate_pending_transfer_request_is_rejected(ticket_client):
    ticket = _create_ict_ticket(ticket_client)
    ict_headers = _ict_headers(ticket_client)
    registrar_id = _office_id_by_name(ticket_client, ict_headers, "Registrar")
    osas_id = _office_id_by_name(ticket_client, ict_headers, "Office of Student Affairs")

    first = _request_transfer(
        ticket_client, ticket["id"], headers=ict_headers, destination_office_id=registrar_id
    )
    assert first.status_code == 200

    second = _request_transfer(
        ticket_client, ticket["id"], headers=ict_headers, destination_office_id=osas_id
    )
    assert second.status_code == 422

    listing = ticket_client.get(f"/tickets/{ticket['id']}/transfers", headers=ict_headers)
    assert listing.status_code == 200
    assert listing.json()["total"] == 1


def test_transfer_accept_reassigns_ticket_and_preserves_everything_else(ticket_client):
    ticket = _create_ict_ticket(ticket_client)
    ict_headers = _ict_headers(ticket_client)
    registrar_headers = _registrar_headers(ticket_client)
    registrar_id = _office_id_by_name(ticket_client, ict_headers, "Registrar")

    ticket_client.post(
        f"/tickets/{ticket['id']}/replies",
        headers=ict_headers,
        json={"message": _PUBLIC_REPLY_TEXT},
    )
    _post_internal_reply(ticket_client, ticket["id"])

    created = _request_transfer(
        ticket_client, ticket["id"], headers=ict_headers, destination_office_id=registrar_id
    )
    transfer_id = created.json()["id"]

    accepted = ticket_client.post(
        f"/tickets/transfers/{transfer_id}/accept", headers=registrar_headers
    )
    assert accepted.status_code == 200, accepted.text
    ticket_after = accepted.json()

    assert ticket_after["id"] == ticket["id"]
    assert ticket_after["assigned_office"] == "Registrar"
    assert ticket_after["assigned_office_id"] == registrar_id
    assert ticket_after["status"] == "In Progress"  # preserved from the earlier staff reply
    assert ticket_after["original_question"] == ticket["original_question"]
    assert ticket_after["user_id"] == ticket["user_id"]
    # Registrar is now the current assigned office, so (per the existing
    # Phase 1 rule: "the ticket's currently-assigned office may see
    # internal notes") it can see the pre-existing ICT internal note too --
    # its is_internal flag is preserved untouched, not stripped or hidden.
    messages_by_text = {m["message"]: m for m in ticket_after["messages"]}
    assert _PUBLIC_REPLY_TEXT in messages_by_text
    assert messages_by_text[_PUBLIC_REPLY_TEXT]["is_internal"] is False
    assert _INTERNAL_NOTE_TEXT in messages_by_text
    assert messages_by_text[_INTERNAL_NOTE_TEXT]["is_internal"] is True

    requester_view = ticket_client.get(f"/tickets/{ticket['id']}", headers=_student_headers(ticket_client))
    assert requester_view.status_code == 200
    requester_messages = {m["message"] for m in requester_view.json()["messages"]}
    assert _INTERNAL_NOTE_TEXT not in requester_messages

    transfer_listing = ticket_client.get(
        f"/tickets/{ticket['id']}/transfers", headers=registrar_headers
    )
    assert transfer_listing.status_code == 200
    decided = transfer_listing.json()["items"][0]
    assert decided["status"] == "Accepted"
    assert decided["decided_at"] is not None
    assert decided["decided_by_user_id"] is not None


def test_transfer_accept_works_for_admin(ticket_client):
    ticket = _create_ict_ticket(ticket_client)
    ict_headers = _ict_headers(ticket_client)
    admin_headers = _admin_headers(ticket_client)
    registrar_id = _office_id_by_name(ticket_client, ict_headers, "Registrar")

    created = _request_transfer(
        ticket_client, ticket["id"], headers=ict_headers, destination_office_id=registrar_id
    )
    transfer_id = created.json()["id"]

    accepted = ticket_client.post(
        f"/tickets/transfers/{transfer_id}/accept", headers=admin_headers
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["assigned_office"] == "Registrar"


def test_transfer_accept_rejects_wrong_office(ticket_client):
    ticket = _create_ict_ticket(ticket_client)
    ict_headers = _ict_headers(ticket_client)
    registrar_id = _office_id_by_name(ticket_client, ict_headers, "Registrar")

    created = _request_transfer(
        ticket_client, ticket["id"], headers=ict_headers, destination_office_id=registrar_id
    )
    transfer_id = created.json()["id"]

    # The source office (ICT) is not the destination, and must not be able
    # to accept its own outgoing request.
    response = ticket_client.post(
        f"/tickets/transfers/{transfer_id}/accept", headers=ict_headers
    )
    assert response.status_code == 403


def test_transfer_accept_rejects_an_already_decided_request(ticket_client):
    ticket = _create_ict_ticket(ticket_client)
    ict_headers = _ict_headers(ticket_client)
    registrar_headers = _registrar_headers(ticket_client)
    registrar_id = _office_id_by_name(ticket_client, ict_headers, "Registrar")

    created = _request_transfer(
        ticket_client, ticket["id"], headers=ict_headers, destination_office_id=registrar_id
    )
    transfer_id = created.json()["id"]

    first = ticket_client.post(f"/tickets/transfers/{transfer_id}/accept", headers=registrar_headers)
    assert first.status_code == 200

    second = ticket_client.post(f"/tickets/transfers/{transfer_id}/accept", headers=registrar_headers)
    assert second.status_code == 422


def test_transfer_accept_conflict_when_ticket_reassigned_since_request_created(ticket_client):
    """If an admin direct-reassigns the ticket away from ICT while the
    transfer to Registrar is still Pending, accepting it afterward must be
    rejected with a clear conflict -- never silently transferring from the
    wrong (stale) source office."""
    ticket = _create_ict_ticket(ticket_client)
    ict_headers = _ict_headers(ticket_client)
    admin_headers = _admin_headers(ticket_client)
    registrar_headers = _registrar_headers(ticket_client)
    registrar_id = _office_id_by_name(ticket_client, ict_headers, "Registrar")
    osas_id = _office_id_by_name(ticket_client, ict_headers, "Office of Student Affairs")

    created = _request_transfer(
        ticket_client, ticket["id"], headers=ict_headers, destination_office_id=registrar_id
    )
    transfer_id = created.json()["id"]

    reassigned = ticket_client.patch(
        f"/tickets/{ticket['id']}", headers=admin_headers, json={"assigned_office_id": osas_id}
    )
    assert reassigned.status_code == 200
    assert reassigned.json()["assigned_office"] == "Office of Student Affairs"

    response = ticket_client.post(
        f"/tickets/transfers/{transfer_id}/accept", headers=registrar_headers
    )
    assert response.status_code == 422

    fetched = ticket_client.get(f"/tickets/{ticket['id']}", headers=admin_headers)
    assert fetched.json()["assigned_office"] == "Office of Student Affairs"


def test_transfer_reject_preserves_ticket_and_records_reason(ticket_client):
    ticket = _create_ict_ticket(ticket_client)
    ict_headers = _ict_headers(ticket_client)
    registrar_headers = _registrar_headers(ticket_client)
    registrar_id = _office_id_by_name(ticket_client, ict_headers, "Registrar")

    created = _request_transfer(
        ticket_client, ticket["id"], headers=ict_headers, destination_office_id=registrar_id
    )
    transfer_id = created.json()["id"]

    rejected = ticket_client.post(
        f"/tickets/transfers/{transfer_id}/reject",
        headers=registrar_headers,
        json={"rejection_reason": "Not a records issue, please keep handling this."},
    )
    assert rejected.status_code == 200, rejected.text
    body = rejected.json()
    assert body["status"] == "Rejected"
    assert body["rejection_reason"] == "Not a records issue, please keep handling this."
    assert body["decided_at"] is not None
    assert body["decided_by_user_id"] is not None

    fetched = ticket_client.get(f"/tickets/{ticket['id']}", headers=ict_headers)
    assert fetched.status_code == 200
    assert fetched.json()["assigned_office"] == "ICT Office"
    assert fetched.json()["status"] == "Open"


def test_transfer_reject_without_reason_is_allowed(ticket_client):
    ticket = _create_ict_ticket(ticket_client)
    ict_headers = _ict_headers(ticket_client)
    registrar_headers = _registrar_headers(ticket_client)
    registrar_id = _office_id_by_name(ticket_client, ict_headers, "Registrar")

    created = _request_transfer(
        ticket_client, ticket["id"], headers=ict_headers, destination_office_id=registrar_id
    )
    transfer_id = created.json()["id"]

    rejected = ticket_client.post(f"/tickets/transfers/{transfer_id}/reject", headers=registrar_headers)
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "Rejected"
    assert rejected.json()["rejection_reason"] is None


def test_transfer_reject_rejects_wrong_office(ticket_client):
    ticket = _create_ict_ticket(ticket_client)
    ict_headers = _ict_headers(ticket_client)
    registrar_id = _office_id_by_name(ticket_client, ict_headers, "Registrar")

    created = _request_transfer(
        ticket_client, ticket["id"], headers=ict_headers, destination_office_id=registrar_id
    )
    transfer_id = created.json()["id"]

    response = ticket_client.post(f"/tickets/transfers/{transfer_id}/reject", headers=ict_headers)
    assert response.status_code == 403


def test_transfer_reject_rejects_an_already_decided_request(ticket_client):
    ticket = _create_ict_ticket(ticket_client)
    ict_headers = _ict_headers(ticket_client)
    registrar_headers = _registrar_headers(ticket_client)
    registrar_id = _office_id_by_name(ticket_client, ict_headers, "Registrar")

    created = _request_transfer(
        ticket_client, ticket["id"], headers=ict_headers, destination_office_id=registrar_id
    )
    transfer_id = created.json()["id"]

    first = ticket_client.post(f"/tickets/transfers/{transfer_id}/reject", headers=registrar_headers)
    assert first.status_code == 200

    second = ticket_client.post(f"/tickets/transfers/{transfer_id}/reject", headers=registrar_headers)
    assert second.status_code == 422


def test_transfer_decision_never_changes_ticket_status(ticket_client):
    ticket = _create_ict_ticket(ticket_client)
    ict_headers = _ict_headers(ticket_client)
    registrar_headers = _registrar_headers(ticket_client)
    registrar_id = _office_id_by_name(ticket_client, ict_headers, "Registrar")

    resolved = ticket_client.post(f"/tickets/{ticket['id']}/resolve", headers=ict_headers)
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "Resolved"

    created = _request_transfer(
        ticket_client, ticket["id"], headers=ict_headers, destination_office_id=registrar_id
    )
    transfer_id = created.json()["id"]

    accepted = ticket_client.post(
        f"/tickets/transfers/{transfer_id}/accept", headers=registrar_headers
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "Resolved"
    assert accepted.json()["assigned_office"] == "Registrar"


def test_incoming_transfers_mailbox_shows_pending_requests_for_destination_office(ticket_client):
    ticket = _create_ict_ticket(ticket_client)
    ict_headers = _ict_headers(ticket_client)
    registrar_headers = _registrar_headers(ticket_client)
    registrar_id = _office_id_by_name(ticket_client, ict_headers, "Registrar")

    _request_transfer(
        ticket_client, ticket["id"], headers=ict_headers, destination_office_id=registrar_id
    )

    registrar_incoming = ticket_client.get("/tickets/transfers/incoming", headers=registrar_headers)
    assert registrar_incoming.status_code == 200
    assert any(item["ticket_id"] == ticket["id"] for item in registrar_incoming.json()["items"])

    ict_incoming = ticket_client.get("/tickets/transfers/incoming", headers=ict_headers)
    assert ict_incoming.status_code == 200
    assert not any(item["ticket_id"] == ticket["id"] for item in ict_incoming.json()["items"])


def test_incoming_transfers_mailbox_shows_all_pending_requests_for_admin(ticket_client):
    ticket = _create_ict_ticket(ticket_client)
    ict_headers = _ict_headers(ticket_client)
    admin_headers = _admin_headers(ticket_client)
    registrar_id = _office_id_by_name(ticket_client, ict_headers, "Registrar")

    _request_transfer(
        ticket_client, ticket["id"], headers=ict_headers, destination_office_id=registrar_id
    )

    admin_incoming = ticket_client.get("/tickets/transfers/incoming", headers=admin_headers)
    assert admin_incoming.status_code == 200
    assert any(item["ticket_id"] == ticket["id"] for item in admin_incoming.json()["items"])


def test_admin_immediate_reassignment_is_unaffected_by_transfer_requests(ticket_client):
    """The existing admin-only immediate reassignment override stays
    completely separate from, and unblocked by, the new transfer-request
    workflow -- even with a Pending request outstanding."""
    ticket = _create_ict_ticket(ticket_client)
    ict_headers = _ict_headers(ticket_client)
    admin_headers = _admin_headers(ticket_client)
    registrar_id = _office_id_by_name(ticket_client, ict_headers, "Registrar")
    osas_id = _office_id_by_name(ticket_client, ict_headers, "Office of Student Affairs")

    _request_transfer(
        ticket_client, ticket["id"], headers=ict_headers, destination_office_id=registrar_id
    )

    response = ticket_client.patch(
        f"/tickets/{ticket['id']}", headers=admin_headers, json={"assigned_office_id": osas_id}
    )
    assert response.status_code == 200
    assert response.json()["assigned_office"] == "Office of Student Affairs"

    audit = ticket_client.get(f"/tickets/{ticket['id']}/audit", headers=admin_headers)
    assert audit.status_code == 200
    assert any(event["action"] == "office_reassigned" for event in audit.json())


# --- transfer-history access policy (Phase 4) --------------------------------
#
# Reuses _create_ict_ticket/_ict_headers/_registrar_headers/_student_headers/
# _admin_headers/_office_id_by_name/_request_transfer/_TRANSFER_REASON from
# the Phase 3 transfer-request section above.


def test_student_cannot_view_ticket_transfer_history(ticket_client):
    """Office-internal transfer reasons and rejection commentary must never
    reach the ticket's own requester, even though they can view the ticket
    itself."""
    ticket = _create_ict_ticket(ticket_client)
    ict_headers = _ict_headers(ticket_client)
    registrar_id = _office_id_by_name(ticket_client, ict_headers, "Registrar")
    _request_transfer(
        ticket_client, ticket["id"], headers=ict_headers, destination_office_id=registrar_id
    )

    response = ticket_client.get(
        f"/tickets/{ticket['id']}/transfers", headers=_student_headers(ticket_client)
    )
    assert response.status_code == 403


def test_unrelated_third_office_still_cannot_view_ticket_transfer_history(ticket_client):
    """An office that was never the source or destination of any transfer
    on this ticket, and is not its current assigned office, must not be
    able to browse the ticket's transfer history."""
    ticket = _create_ict_ticket(ticket_client)
    ict_headers = _ict_headers(ticket_client)
    osas_id = _office_id_by_name(ticket_client, ict_headers, "Office of Student Affairs")
    _request_transfer(
        ticket_client, ticket["id"], headers=ict_headers, destination_office_id=osas_id
    )

    response = ticket_client.get(
        f"/tickets/{ticket['id']}/transfers", headers=_registrar_headers(ticket_client)
    )
    assert response.status_code == 403


def test_source_office_can_review_outgoing_transfer_after_acceptance(ticket_client):
    """The whole point of /transfers/outgoing: once Registrar accepts
    ICT's transfer request, ICT loses the per-ticket view (see the test
    above's sibling expectation reversed for admin/current-office), but
    must still be able to review its own outgoing request and its final
    outcome through the dedicated endpoint."""
    ticket = _create_ict_ticket(ticket_client)
    ict_headers = _ict_headers(ticket_client)
    registrar_headers = _registrar_headers(ticket_client)
    registrar_id = _office_id_by_name(ticket_client, ict_headers, "Registrar")

    created = _request_transfer(
        ticket_client, ticket["id"], headers=ict_headers, destination_office_id=registrar_id
    )
    transfer_id = created.json()["id"]
    accepted = ticket_client.post(
        f"/tickets/transfers/{transfer_id}/accept", headers=registrar_headers
    )
    assert accepted.status_code == 200

    # The per-ticket endpoint now 403s for ICT -- it's no longer the
    # ticket's current office.
    per_ticket = ticket_client.get(f"/tickets/{ticket['id']}/transfers", headers=ict_headers)
    assert per_ticket.status_code == 403

    outgoing = ticket_client.get("/tickets/transfers/outgoing", headers=ict_headers)
    assert outgoing.status_code == 200
    items = outgoing.json()["items"]
    assert any(item["id"] == transfer_id for item in items)
    decided = next(item for item in items if item["id"] == transfer_id)
    assert decided["status"] == "Accepted"
    assert decided["source_office_name"] == "ICT Office"
    assert decided["destination_office_name"] == "Registrar"


def test_outgoing_transfers_scoped_to_own_office(ticket_client):
    ticket = _create_ict_ticket(ticket_client)
    ict_headers = _ict_headers(ticket_client)
    registrar_id = _office_id_by_name(ticket_client, ict_headers, "Registrar")
    _request_transfer(
        ticket_client, ticket["id"], headers=ict_headers, destination_office_id=registrar_id
    )

    registrar_outgoing = ticket_client.get(
        "/tickets/transfers/outgoing", headers=_registrar_headers(ticket_client)
    )
    assert registrar_outgoing.status_code == 200
    assert not any(
        item["ticket_id"] == ticket["id"] for item in registrar_outgoing.json()["items"]
    )

    ict_outgoing = ticket_client.get("/tickets/transfers/outgoing", headers=ict_headers)
    assert ict_outgoing.status_code == 200
    assert any(item["ticket_id"] == ticket["id"] for item in ict_outgoing.json()["items"])


def test_outgoing_transfers_admin_sees_all(ticket_client):
    ticket = _create_ict_ticket(ticket_client)
    ict_headers = _ict_headers(ticket_client)
    admin_headers = _admin_headers(ticket_client)
    registrar_id = _office_id_by_name(ticket_client, ict_headers, "Registrar")
    _request_transfer(
        ticket_client, ticket["id"], headers=ict_headers, destination_office_id=registrar_id
    )

    admin_outgoing = ticket_client.get("/tickets/transfers/outgoing", headers=admin_headers)
    assert admin_outgoing.status_code == 200
    assert any(item["ticket_id"] == ticket["id"] for item in admin_outgoing.json()["items"])


def test_student_and_faculty_cannot_call_outgoing_or_incoming_endpoints(ticket_client):
    ticket = _create_ict_ticket(ticket_client)
    ict_headers = _ict_headers(ticket_client)
    registrar_id = _office_id_by_name(ticket_client, ict_headers, "Registrar")
    _request_transfer(
        ticket_client, ticket["id"], headers=ict_headers, destination_office_id=registrar_id
    )

    student_headers = _student_headers(ticket_client)
    outgoing = ticket_client.get("/tickets/transfers/outgoing", headers=student_headers)
    assert outgoing.status_code == 200
    assert outgoing.json()["items"] == []

    incoming = ticket_client.get("/tickets/transfers/incoming", headers=student_headers)
    assert incoming.status_code == 200
    assert incoming.json()["items"] == []


# --- transfer-notification identity, read-sweep, and badge accuracy ---------
#
# These tests need to inspect Notification rows directly (is_read,
# transfer_request_id) which the API never exposes, and to seed a second
# office-B recipient / unrelated notification rows the normal ticket flow
# doesn't produce. Rather than touching the shared ticket_client fixture
# (used by every other test in this file) or _seed_offices_and_users, each
# helper below grabs a session through the SAME dependency override the
# fixture already installed on `app`, and/or inserts rows directly -- fully
# additive, no shared setup touched.


def _notification_session(ticket_client: TestClient) -> Session:
    from app.db.session import get_db_session
    from app.main import app as _app

    return next(_app.dependency_overrides[get_db_session]())


def _fetch_notifications(
    ticket_client: TestClient,
    *,
    user_id: str | None = None,
    type_: str | None = None,
    transfer_request_id: str | None = None,
):
    from app.models.db_models import Notification

    session = _notification_session(ticket_client)
    try:
        query = session.query(Notification)
        if user_id:
            query = query.filter(Notification.user_id == user_id)
        if type_:
            query = query.filter(Notification.type == type_)
        if transfer_request_id:
            query = query.filter(Notification.transfer_request_id == transfer_request_id)
        return query.order_by(Notification.created_at.asc()).all()
    finally:
        session.close()


def _create_extra_office_user(ticket_client: TestClient, *, office_id: str, email: str) -> User:
    session = _notification_session(ticket_client)
    try:
        user = User(
            email=email,
            password_hash=hash_password("office123"),
            full_name=f"Extra staff {email}",
            role="office",
            office_id=office_id,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        session.expunge(user)
        return user
    finally:
        session.close()


def _insert_raw_notification(
    ticket_client: TestClient,
    *,
    user_id: str,
    type_: str,
    is_read: bool = False,
    ticket_id: str | None = None,
    transfer_request_id: str | None = None,
    created_at=None,
) -> str:
    """Inserts a Notification row the normal flow wouldn't produce on its
    own (an unrelated type for isolation checks, or a back-dated
    created_at for the 100-cap test) -- never via the API, since no
    endpoint lets a caller fabricate another type/timestamp."""
    import uuid as _uuid

    from app.models.db_models import Notification, utc_now

    session = _notification_session(ticket_client)
    try:
        item = Notification(
            id=str(_uuid.uuid4()),
            user_id=user_id,
            ticket_id=ticket_id,
            type=type_,
            title="Test notification",
            body="Test body",
            is_read=is_read,
            created_at=created_at or utc_now(),
            transfer_request_id=transfer_request_id,
        )
        session.add(item)
        session.commit()
        return item.id
    finally:
        session.close()


def test_transfer_request_notification_has_correct_transfer_request_id(ticket_client):
    ticket = _create_ict_ticket(ticket_client)
    ict_headers = _ict_headers(ticket_client)
    registrar_id = _office_id_by_name(ticket_client, ict_headers, "Registrar")

    created = _request_transfer(
        ticket_client, ticket["id"], headers=ict_headers, destination_office_id=registrar_id
    )
    transfer_id = created.json()["id"]

    rows = _fetch_notifications(ticket_client, type_="transfer_requested", transfer_request_id=transfer_id)
    assert len(rows) == 1
    assert rows[0].transfer_request_id == transfer_id
    assert rows[0].is_read is False


def test_accept_marks_destination_office_transfer_requested_notifications_read(ticket_client):
    """Clears the notification for EVERY destination-office recipient, not
    just whichever staff member happens to click Accept."""
    ticket = _create_ict_ticket(ticket_client)
    ict_headers = _ict_headers(ticket_client)
    registrar_headers = _registrar_headers(ticket_client)
    registrar_id = _office_id_by_name(ticket_client, ict_headers, "Registrar")
    second_registrar = _create_extra_office_user(
        ticket_client, office_id=registrar_id, email="registrar2@aska.local"
    )

    created = _request_transfer(
        ticket_client, ticket["id"], headers=ict_headers, destination_office_id=registrar_id
    )
    transfer_id = created.json()["id"]

    before = _fetch_notifications(ticket_client, type_="transfer_requested", transfer_request_id=transfer_id)
    assert len(before) == 2
    assert second_registrar.id in {n.user_id for n in before}
    assert all(n.is_read is False for n in before)

    accepted = ticket_client.post(f"/tickets/transfers/{transfer_id}/accept", headers=registrar_headers)
    assert accepted.status_code == 200

    after = _fetch_notifications(ticket_client, type_="transfer_requested", transfer_request_id=transfer_id)
    assert len(after) == 2
    assert all(n.is_read is True for n in after)


def test_reject_marks_destination_office_transfer_requested_notifications_read(ticket_client):
    ticket = _create_ict_ticket(ticket_client)
    ict_headers = _ict_headers(ticket_client)
    registrar_headers = _registrar_headers(ticket_client)
    registrar_id = _office_id_by_name(ticket_client, ict_headers, "Registrar")
    second_registrar = _create_extra_office_user(
        ticket_client, office_id=registrar_id, email="registrar3@aska.local"
    )

    created = _request_transfer(
        ticket_client, ticket["id"], headers=ict_headers, destination_office_id=registrar_id
    )
    transfer_id = created.json()["id"]

    rejected = ticket_client.post(f"/tickets/transfers/{transfer_id}/reject", headers=registrar_headers)
    assert rejected.status_code == 200

    after = _fetch_notifications(ticket_client, type_="transfer_requested", transfer_request_id=transfer_id)
    assert len(after) == 2
    assert all(n.is_read is True for n in after)
    assert second_registrar.id in {n.user_id for n in after}


def test_decision_sweep_does_not_touch_unrelated_requests_or_notification_types(ticket_client):
    ticket = _create_ict_ticket(ticket_client)
    other_ticket = _create_ict_ticket(ticket_client)
    ict_headers = _ict_headers(ticket_client)
    registrar_headers = _registrar_headers(ticket_client)
    registrar_id = _office_id_by_name(ticket_client, ict_headers, "Registrar")
    registrar = _get_user_by_email(ticket_client, "registrar@aska.local")

    # An independent, still-pending transfer request on a DIFFERENT ticket,
    # addressed to the same destination office.
    other_created = _request_transfer(
        ticket_client, other_ticket["id"], headers=ict_headers, destination_office_id=registrar_id
    )
    other_transfer_id = other_created.json()["id"]

    # An unrelated notification TYPE for the same recipient.
    unrelated_id = _insert_raw_notification(
        ticket_client, user_id=registrar.id, type_="ticket_reply", ticket_id=ticket["id"]
    )

    created = _request_transfer(
        ticket_client, ticket["id"], headers=ict_headers, destination_office_id=registrar_id
    )
    transfer_id = created.json()["id"]
    accepted = ticket_client.post(f"/tickets/transfers/{transfer_id}/accept", headers=registrar_headers)
    assert accepted.status_code == 200

    # The OTHER ticket's still-pending request is untouched.
    other_rows = _fetch_notifications(
        ticket_client, type_="transfer_requested", transfer_request_id=other_transfer_id
    )
    assert len(other_rows) == 1
    assert other_rows[0].is_read is False

    # The unrelated notification type for the same user is untouched.
    unrelated_row = _fetch_notifications(ticket_client, user_id=registrar.id)
    unrelated_match = next(n for n in unrelated_row if n.id == unrelated_id)
    assert unrelated_match.is_read is False


def test_new_request_after_earlier_decided_is_isolated(ticket_client):
    ticket = _create_ict_ticket(ticket_client)
    ict_headers = _ict_headers(ticket_client)
    registrar_headers = _registrar_headers(ticket_client)
    registrar_id = _office_id_by_name(ticket_client, ict_headers, "Registrar")
    osas_id = _office_id_by_name(ticket_client, ict_headers, "Office of Student Affairs")

    first = _request_transfer(
        ticket_client, ticket["id"], headers=ict_headers, destination_office_id=registrar_id
    )
    first_id = first.json()["id"]
    accepted = ticket_client.post(f"/tickets/transfers/{first_id}/accept", headers=registrar_headers)
    assert accepted.status_code == 200

    first_rows_after_accept = _fetch_notifications(
        ticket_client, type_="transfer_requested", transfer_request_id=first_id
    )
    assert all(n.is_read is True for n in first_rows_after_accept)

    # A second, later request on the SAME ticket, now that Registrar is the
    # current office -- deciding it must only ever touch its OWN rows.
    second = _request_transfer(
        ticket_client, ticket["id"], headers=registrar_headers, destination_office_id=osas_id
    )
    second_id = second.json()["id"]
    assert second_id != first_id

    rejected = ticket_client.post(f"/tickets/transfers/{second_id}/reject", headers=_admin_headers(ticket_client))
    assert rejected.status_code == 200

    first_rows_final = _fetch_notifications(
        ticket_client, type_="transfer_requested", transfer_request_id=first_id
    )
    second_rows_final = _fetch_notifications(
        ticket_client, type_="transfer_requested", transfer_request_id=second_id
    )
    assert all(n.is_read is True for n in first_rows_final)
    assert all(n.is_read is True for n in second_rows_final)
    assert {n.id for n in first_rows_final}.isdisjoint({n.id for n in second_rows_final})


def test_transfer_mark_read_endpoint_updates_only_caller_transfer_notifications(ticket_client):
    ticket = _create_ict_ticket(ticket_client)
    ict_headers = _ict_headers(ticket_client)
    registrar_headers = _registrar_headers(ticket_client)
    registrar_id = _office_id_by_name(ticket_client, ict_headers, "Registrar")
    registrar = _get_user_by_email(ticket_client, "registrar@aska.local")
    ict_staff = _get_user_by_email(ticket_client, "ict@aska.local")

    _request_transfer(
        ticket_client, ticket["id"], headers=ict_headers, destination_office_id=registrar_id
    )  # leaves registrar's transfer_requested notification unread

    unrelated_id = _insert_raw_notification(
        ticket_client, user_id=registrar.id, type_="ticket_reply", ticket_id=ticket["id"]
    )
    other_user_transfer_id = _insert_raw_notification(
        ticket_client, user_id=ict_staff.id, type_="transfer_accepted", ticket_id=ticket["id"]
    )

    response = ticket_client.post("/tickets/notifications/transfers/read-all", headers=registrar_headers)
    assert response.status_code == 200
    assert response.json()["marked_read"] == 1

    registrar_rows = {n.id: n.is_read for n in _fetch_notifications(ticket_client, user_id=registrar.id)}
    assert registrar_rows[unrelated_id] is False  # unrelated type untouched

    ict_rows = {n.id: n.is_read for n in _fetch_notifications(ticket_client, user_id=ict_staff.id)}
    assert ict_rows[other_user_transfer_id] is False  # another user's transfer notification untouched


def test_unread_transfer_count_accurate_beyond_the_100_notification_cap(ticket_client):
    from datetime import datetime, timedelta, timezone

    registrar = _get_user_by_email(ticket_client, "registrar@aska.local")
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)

    # 15 old, unread transfer notifications...
    for i in range(15):
        _insert_raw_notification(
            ticket_client,
            user_id=registrar.id,
            type_="transfer_requested",
            created_at=base_time + timedelta(minutes=i),
        )
    # ...followed by 100 newer, unread, UNRELATED notifications -- exactly
    # enough that the "most recent 100" page is entirely unrelated rows,
    # pushing all 15 older transfer ones off the end completely.
    for i in range(100):
        _insert_raw_notification(
            ticket_client,
            user_id=registrar.id,
            type_="ticket_reply",
            created_at=base_time + timedelta(hours=1, minutes=i),
        )

    registrar_headers = _registrar_headers(ticket_client)

    # The old paginated-list approach would undercount: only the 100 most
    # recent unread rows are returned, and all 15 transfer ones are older
    # than all 90 unrelated ones, so they'd be entirely excluded.
    paginated = ticket_client.get(
        "/tickets/notifications?unread_only=true", headers=registrar_headers
    )
    assert paginated.status_code == 200
    paginated_items = paginated.json()["items"]
    assert len(paginated_items) == 100
    paginated_transfer_count = sum(
        1 for item in paginated_items if item["type"] == "transfer_requested"
    )
    assert paginated_transfer_count == 0  # proves the old approach would undercount

    # The new dedicated endpoint is unaffected by that windowing.
    response = ticket_client.get("/tickets/notifications/transfers/unread-count", headers=registrar_headers)
    assert response.status_code == 200
    assert response.json()["unread_count"] == 15


def _get_user_by_email(ticket_client: TestClient, email: str) -> User:
    session = _notification_session(ticket_client)
    try:
        user = session.query(User).filter(User.email == email).one()
        session.expunge(user)
        return user
    finally:
        session.close()


def _faculty_headers(ticket_client: TestClient) -> dict[str, str]:
    login = ticket_client.post(
        "/auth/login",
        json={"email": "faculty1@aska.local", "password": "faculty123"},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_transfer_notification_endpoints_reject_student_and_faculty(ticket_client):
    """Explicit route-level role gate, added after code review flagged that
    these two endpoints previously had no role check at all (they were
    harmless no-ops for non-office/admin roles via their user-scoped
    queries, but not explicitly denied)."""
    ticket = _create_ict_ticket(ticket_client)
    ict_headers = _ict_headers(ticket_client)
    registrar_id = _office_id_by_name(ticket_client, ict_headers, "Registrar")
    registrar = _get_user_by_email(ticket_client, "registrar@aska.local")
    student = _get_user_by_email(ticket_client, "student1@aska.local")

    # Leaves registrar's transfer_requested notification unread.
    _request_transfer(
        ticket_client, ticket["id"], headers=ict_headers, destination_office_id=registrar_id
    )
    student_notification_id = _insert_raw_notification(
        ticket_client, user_id=student.id, type_="ticket_reply", ticket_id=ticket["id"]
    )

    for headers in (_student_headers(ticket_client), _faculty_headers(ticket_client)):
        mark_read_response = ticket_client.post(
            "/tickets/notifications/transfers/read-all", headers=headers
        )
        assert mark_read_response.status_code == 403

        count_response = ticket_client.get(
            "/tickets/notifications/transfers/unread-count", headers=headers
        )
        assert count_response.status_code == 403

    # Neither forbidden attempt touched any notification row -- not the
    # destination office's pending one, and not the student's own.
    registrar_rows = _fetch_notifications(
        ticket_client, user_id=registrar.id, type_="transfer_requested"
    )
    assert all(n.is_read is False for n in registrar_rows)

    student_rows = {n.id: n.is_read for n in _fetch_notifications(ticket_client, user_id=student.id)}
    assert student_rows[student_notification_id] is False


def test_transfer_notification_endpoints_allow_office_and_admin(ticket_client):
    ticket = _create_ict_ticket(ticket_client)
    ict_headers = _ict_headers(ticket_client)
    registrar_headers = _registrar_headers(ticket_client)
    admin_headers = _admin_headers(ticket_client)
    registrar_id = _office_id_by_name(ticket_client, ict_headers, "Registrar")

    _request_transfer(
        ticket_client, ticket["id"], headers=ict_headers, destination_office_id=registrar_id
    )

    office_count = ticket_client.get(
        "/tickets/notifications/transfers/unread-count", headers=registrar_headers
    )
    assert office_count.status_code == 200
    assert office_count.json()["unread_count"] == 1

    office_mark_read = ticket_client.post(
        "/tickets/notifications/transfers/read-all", headers=registrar_headers
    )
    assert office_mark_read.status_code == 200
    assert office_mark_read.json()["marked_read"] == 1

    admin_count = ticket_client.get(
        "/tickets/notifications/transfers/unread-count", headers=admin_headers
    )
    assert admin_count.status_code == 200

    admin_mark_read = ticket_client.post(
        "/tickets/notifications/transfers/read-all", headers=admin_headers
    )
    assert admin_mark_read.status_code == 200


def test_accept_conflict_rolls_back_status_and_leaves_notifications_unread(ticket_client):
    """Regression for the exact conflict path accept_ticket_transfer()
    already guards against: the ticket's office assignment changed since
    the request was created (ticketing.py's `ticket.assigned_office_id !=
    request.source_office_id` check), which raises BEFORE any
    notification is created or swept. This reuses the same deterministic
    setup as test_transfer_accept_conflict_when_ticket_reassigned_since_request_created
    above, adding the persisted-state assertions a code review flagged as
    missing: that the claimed-but-then-rolled-back status write on the
    TicketTransferRequest itself reverts to Pending (not left dangling as
    Accepted), and that the destination office's unread transfer_requested
    notification -- which the sweep would otherwise have cleared -- is
    never touched, because the whole transaction (claim UPDATE, ticket
    mutation, notifications, sweep) rolls back together."""
    ticket = _create_ict_ticket(ticket_client)
    ict_headers = _ict_headers(ticket_client)
    admin_headers = _admin_headers(ticket_client)
    registrar_headers = _registrar_headers(ticket_client)
    registrar_id = _office_id_by_name(ticket_client, ict_headers, "Registrar")
    osas_id = _office_id_by_name(ticket_client, ict_headers, "Office of Student Affairs")

    created = _request_transfer(
        ticket_client, ticket["id"], headers=ict_headers, destination_office_id=registrar_id
    )
    transfer_id = created.json()["id"]

    notifications_before = _fetch_notifications(
        ticket_client, type_="transfer_requested", transfer_request_id=transfer_id
    )
    assert len(notifications_before) == 1
    assert notifications_before[0].is_read is False

    # Admin direct-reassigns the ticket away from ICT while the transfer
    # to Registrar is still Pending -- the same stale-source-assignment
    # conflict the existing test above already exercises.
    reassigned = ticket_client.patch(
        f"/tickets/{ticket['id']}", headers=admin_headers, json={"assigned_office_id": osas_id}
    )
    assert reassigned.status_code == 200

    response = ticket_client.post(
        f"/tickets/transfers/{transfer_id}/accept", headers=registrar_headers
    )
    assert response.status_code == 422

    # The transfer request's own status reverted to Pending -- the claim
    # UPDATE that provisionally set it to Accepted was rolled back along
    # with everything else in the same transaction, not left dangling.
    transfer_listing = ticket_client.get(f"/tickets/{ticket['id']}/transfers", headers=admin_headers)
    assert transfer_listing.status_code == 200
    refetched = next(item for item in transfer_listing.json()["items"] if item["id"] == transfer_id)
    assert refetched["status"] == "Pending"
    assert refetched["decided_by_user_id"] is None
    assert refetched["decided_at"] is None

    # The destination office's unread "please decide" notification is
    # untouched -- the sweep that would have cleared it never ran, because
    # it sits after the conflict check that raised first.
    notifications_after = _fetch_notifications(
        ticket_client, type_="transfer_requested", transfer_request_id=transfer_id
    )
    assert len(notifications_after) == 1
    assert notifications_after[0].is_read is False

    # The ticket's assignment is unchanged -- still OSAS, never silently
    # moved to Registrar.
    fetched = ticket_client.get(f"/tickets/{ticket['id']}", headers=admin_headers)
    assert fetched.json()["assigned_office"] == "Office of Student Affairs"
