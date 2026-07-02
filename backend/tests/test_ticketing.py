from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)

STUDENT_HEADERS = {
    "x-user-id": "student-1",
    "x-user-role": "student",
    "x-user-name": "Piyu Student",
    "x-user-email": "piyu@example.edu",
}
OTHER_STUDENT_HEADERS = {
    "x-user-id": "student-2",
    "x-user-role": "student",
    "x-user-name": "Other Student",
}
ICT_HEADERS = {
    "x-user-id": "ict-1",
    "x-user-role": "office",
    "x-user-name": "ICT Staff",
    "x-user-office": "ICT Office",
}
REGISTRAR_HEADERS = {
    "x-user-id": "registrar-1",
    "x-user-role": "office",
    "x-user-name": "Registrar Staff",
    "x-user-office": "Registrar",
}
ADMIN_HEADERS = {
    "x-user-id": "admin-1",
    "x-user-role": "admin",
    "x-user-name": "Admin",
}


def test_ticket_triage_detects_technical_high_priority():
    response = client.post(
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
    assert data["priority"] == "High"


def test_student_can_create_and_list_own_ticket(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.ticketing.settings.ticket_store_path", str(tmp_path / "tickets.json"))

    create_response = client.post(
        "/tickets",
        headers=STUDENT_HEADERS,
        json={
            "original_question": "How can I request a copy of my TOR?",
            "description": "I need it for scholarship application.",
            "source_from_chatbot": True,
            "confidence_score": 0.2,
        },
    )
    list_response = client.get("/tickets", headers=STUDENT_HEADERS)

    assert create_response.status_code == 200
    ticket = create_response.json()
    assert ticket["status"] == "Open"
    assert ticket["assigned_office"] == "Registrar"
    assert list_response.status_code == 200
    assert list_response.json()["total"] == 1
    assert list_response.json()["items"][0]["id"] == ticket["id"]


def test_student_cannot_view_another_students_ticket(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.ticketing.settings.ticket_store_path", str(tmp_path / "tickets.json"))
    created = client.post(
        "/tickets",
        headers=STUDENT_HEADERS,
        json={"original_question": "I need my TOR.", "description": ""},
    ).json()

    response = client.get(f"/tickets/{created['id']}", headers=OTHER_STUDENT_HEADERS)

    assert response.status_code == 403


def test_office_only_sees_assigned_tickets(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.ticketing.settings.ticket_store_path", str(tmp_path / "tickets.json"))
    client.post(
        "/tickets",
        headers=STUDENT_HEADERS,
        json={"original_question": "I cannot login to the student portal.", "description": ""},
    )

    ict_response = client.get("/tickets", headers=ICT_HEADERS)
    registrar_response = client.get("/tickets", headers=REGISTRAR_HEADERS)

    assert ict_response.status_code == 200
    assert ict_response.json()["total"] == 1
    assert registrar_response.status_code == 200
    assert registrar_response.json()["total"] == 0


def test_office_can_reply_and_resolve_ticket(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.ticketing.settings.ticket_store_path", str(tmp_path / "tickets.json"))
    created = client.post(
        "/tickets",
        headers=STUDENT_HEADERS,
        json={"original_question": "I cannot login to the student portal.", "description": ""},
    ).json()

    reply_response = client.post(
        f"/tickets/{created['id']}/replies",
        headers=ICT_HEADERS,
        json={"message": "Please visit the ICT office with your student ID."},
    )
    update_response = client.patch(
        f"/tickets/{created['id']}",
        headers=ICT_HEADERS,
        json={"status": "In Progress"},
    )
    resolved_response = client.patch(
        f"/tickets/{created['id']}",
        headers=ICT_HEADERS,
        json={"status": "Resolved"},
    )

    assert reply_response.status_code == 200
    assert reply_response.json()["messages"][0]["sender_role"] == "office"
    assert update_response.status_code == 200
    assert update_response.json()["status"] == "In Progress"
    assert resolved_response.status_code == 200
    assert resolved_response.json()["resolved_at"] is not None


def test_admin_can_reassign_ticket(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.ticketing.settings.ticket_store_path", str(tmp_path / "tickets.json"))
    created = client.post(
        "/tickets",
        headers=STUDENT_HEADERS,
        json={"original_question": "I need help with my TOR.", "description": ""},
    ).json()

    response = client.patch(
        f"/tickets/{created['id']}",
        headers=ADMIN_HEADERS,
        json={"assigned_office": "Office of Student Affairs", "priority": "Low"},
    )

    assert response.status_code == 200
    assert response.json()["assigned_office"] == "Office of Student Affairs"
    assert response.json()["priority"] == "Low"
