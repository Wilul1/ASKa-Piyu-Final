from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import get_db_session, initialize_database
from app.main import app
from app.models.db_models import Office, Ticket, TicketReply, User
from app.services.auth import create_access_token, decode_access_token
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
    # Local .env may set campus gates; keep unit tests open unless a case
    # explicitly re-enables invite/domain restrictions.
    monkeypatch.setattr("app.routes.auth.settings.signup_invite_code", None)
    monkeypatch.setattr("app.routes.auth.settings.signup_allowed_email_domains", None)
    monkeypatch.setattr("app.routes.auth.settings.allow_public_signup", True)
    monkeypatch.setattr("app.routes.auth.generate_verification_code", lambda: "123456")
    monkeypatch.setattr("app.routes.auth.send_verification_email", lambda **kwargs: True)
    app.dependency_overrides[get_db_session] = override_get_db_session

    from app.services.auth_rate_limit import reset_auth_rate_limits

    reset_auth_rate_limits()
    try:
        yield TestClient(app)
    finally:
        reset_auth_rate_limits()
        app.dependency_overrides.clear()


def signup_student(
    client: TestClient,
    email: str = "student@example.edu",
    *,
    verify: bool = True,
) -> dict:
    response = client.post(
        "/auth/signup",
        json={
            "email": email,
            "password": "correct horse battery staple1",
            "full_name": "Piyu Student",
        },
    )
    assert response.status_code == 200
    data = response.json()
    if not verify:
        return data
    verified = client.post(
        "/auth/verify-email",
        headers={"Authorization": f"Bearer {data['access_token']}"},
        json={"code": "123456"},
    )
    assert verified.status_code == 200
    return verified.json()


def test_successful_student_signup(auth_client):
    data = signup_student(auth_client, verify=False)

    assert data["token_type"] == "bearer"
    assert data["access_token"]
    assert data["user"]["email"] == "student@example.edu"
    assert data["user"]["role"] == "student"
    assert data["user"]["email_verified"] is False
    assert "password" not in data["user"]
    assert "password_hash" not in data["user"]


def test_login_unverified_student_stays_unverified(auth_client):
    signup_student(auth_client, email="unverified.login@gmail.com", verify=False)

    login = auth_client.post(
        "/auth/login",
        json={
            "email": "unverified.login@gmail.com",
            "password": "correct horse battery staple1",
        },
    )
    assert login.status_code == 200
    assert login.json()["user"]["email_verified"] is False


def test_student_can_verify_email_with_code(auth_client):
    data = signup_student(auth_client, email="needs.verify@gmail.com", verify=False)
    assert data["user"]["email_verified"] is False
    verified = auth_client.post(
        "/auth/verify-email",
        headers={"Authorization": f"Bearer {data['access_token']}"},
        json={"code": "123456"},
    )
    assert verified.status_code == 200
    assert verified.json()["user"]["email_verified"] is True


def test_resend_verification_when_already_verified(auth_client):
    data = signup_student(auth_client, email="verify.me@gmail.com")
    token = data["access_token"]
    assert data["user"]["email_verified"] is True

    resend = auth_client.post(
        "/auth/resend-verification",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resend.status_code == 200
    assert resend.json()["sent"] is False
    assert "already verified" in resend.json()["message"].lower()


def test_unverified_student_cannot_create_ticket(auth_client):
    data = signup_student(auth_client, email="ticket.block@gmail.com", verify=False)
    token = data["access_token"]
    ticket_payload = {
        "original_question": "Where do I get an excuse slip?",
        "description": "I need an excuse slip for my class absence this week.",
    }
    blocked = auth_client.post(
        "/tickets",
        headers={"Authorization": f"Bearer {token}"},
        json=ticket_payload,
    )
    assert blocked.status_code == 403
    assert "verify" in blocked.json()["detail"].lower()

    verified = auth_client.post(
        "/auth/verify-email",
        headers={"Authorization": f"Bearer {token}"},
        json={"code": "123456"},
    )
    assert verified.status_code == 200
    after = auth_client.post(
        "/tickets",
        headers={"Authorization": f"Bearer {verified.json()['access_token']}"},
        json=ticket_payload,
    )
    assert after.status_code != 403


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
    assert response.json()["detail"] == "Unable to create an account with that email."


def test_signup_respects_email_domain_allowlist(auth_client, monkeypatch):
    monkeypatch.setattr(
        "app.routes.auth.settings.signup_allowed_email_domains",
        "lspu.edu.ph",
    )
    denied = auth_client.post(
        "/auth/signup",
        json={
            "email": "student@gmail.com",
            "password": "correct horse battery staple1",
            "full_name": "Outside Student",
        },
    )
    assert denied.status_code == 403
    allowed = signup_student(auth_client, email="student@lspu.edu.ph")
    assert allowed["user"]["email"] == "student@lspu.edu.ph"


def test_signup_requires_invite_code_when_configured(auth_client, monkeypatch):
    monkeypatch.setattr("app.routes.auth.settings.signup_invite_code", "campus-invite")
    missing = auth_client.post(
        "/auth/signup",
        json={
            "email": "a@example.edu",
            "password": "correct horse battery staple1",
            "full_name": "No Invite",
        },
    )
    assert missing.status_code == 403
    wrong = auth_client.post(
        "/auth/signup",
        json={
            "email": "b@example.edu",
            "password": "correct horse battery staple1",
            "full_name": "Bad Invite",
            "invite_code": "wrong",
        },
    )
    assert wrong.status_code == 403
    ok = auth_client.post(
        "/auth/signup",
        json={
            "email": "c@example.edu",
            "password": "correct horse battery staple1",
            "full_name": "Good Invite",
            "invite_code": "campus-invite",
        },
    )
    assert ok.status_code == 200


def test_signup_can_be_disabled(auth_client, monkeypatch):
    monkeypatch.setattr("app.routes.auth.settings.allow_public_signup", False)
    response = auth_client.post(
        "/auth/signup",
        json={
            "email": "blocked@example.edu",
            "password": "correct horse battery staple1",
            "full_name": "Blocked",
        },
    )
    assert response.status_code == 403


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


def test_office_can_create_faculty_account(auth_client):
    session_generator = app.dependency_overrides[get_db_session]()
    session = next(session_generator)
    try:
        from app.models.db_models import Office

        office = Office(name="Test Office", service_category="General")
        session.add(office)
        session.flush()
        staff = User(
            email="office@example.edu",
            password_hash=hash_password("office-password-1"),
            full_name="Office Staff",
            role="office",
            office_id=office.id,
        )
        session.add(staff)
        session.commit()
        session.refresh(staff)
        token = create_access_token(staff)
        office_id = office.id
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
    assert data["office_id"] == office_id


def test_office_can_create_office_staff_for_own_office(auth_client):
    session_generator = app.dependency_overrides[get_db_session]()
    session = next(session_generator)
    try:
        from app.models.db_models import Office

        office = Office(name="OSA Office", service_category="Student Affairs")
        other = Office(name="Other Office", service_category="Other")
        session.add_all([office, other])
        session.flush()
        lead = User(
            email="osa.lead@example.edu",
            password_hash=hash_password("office-password-1"),
            full_name="OSA Lead",
            role="office",
            office_id=office.id,
        )
        session.add(lead)
        session.commit()
        session.refresh(lead)
        token = create_access_token(lead)
        office_id = office.id
        other_id = other.id
    finally:
        try:
            next(session_generator)
        except StopIteration:
            pass

    # Client cannot assign staff to a different office — always own office_id.
    response = auth_client.post(
        "/auth/office-accounts",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "email": "osa.clerk@example.edu",
            "password": "office12345",
            "full_name": "OSA Clerk",
            "office_id": other_id,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["role"] == "office"
    assert data["email"] == "osa.clerk@example.edu"
    assert data["office_id"] == office_id
    assert data["office_name"] == "OSA Office"

    listed = auth_client.get(
        "/auth/users",
        params={"role": "office"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert listed.status_code == 200
    emails = {item["email"] for item in listed.json()["items"]}
    assert "osa.lead@example.edu" in emails
    assert "osa.clerk@example.edu" in emails

    login = auth_client.post(
        "/auth/login",
        json={"email": "osa.clerk@example.edu", "password": "office12345"},
    )
    assert login.status_code == 200
    body = login.json()
    assert body["user"]["role"] == "office"
    assert body["user"]["office_id"] == office_id
    assert body["user"]["office_name"] == "OSA Office"


def test_admin_cannot_create_faculty_account(auth_client):
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
            "email": "faculty2@example.edu",
            "password": "faculty12345",
            "full_name": "Faculty Member",
        },
    )
    assert response.status_code == 403


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


def test_login_remember_me_uses_longer_token_ttl(auth_client, monkeypatch):
    monkeypatch.setattr("app.services.auth.settings.auth_token_ttl_minutes", 60)
    monkeypatch.setattr("app.services.auth.settings.auth_remember_token_ttl_minutes", 60 * 24 * 7)
    signup_student(auth_client)

    short = auth_client.post(
        "/auth/login",
        json={
            "email": "student@example.edu",
            "password": "correct horse battery staple1",
            "remember_me": False,
        },
    )
    remembered = auth_client.post(
        "/auth/login",
        json={
            "email": "student@example.edu",
            "password": "correct horse battery staple1",
            "remember_me": True,
        },
    )

    assert short.status_code == 200
    assert remembered.status_code == 200

    short_exp = decode_access_token(short.json()["access_token"])["exp"]
    remembered_exp = decode_access_token(remembered.json()["access_token"])["exp"]
    assert remembered_exp - short_exp >= (60 * 24 * 7 - 60) * 60


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


def test_logout_revokes_bearer_token(auth_client):
    signup_data = signup_student(auth_client)
    token = signup_data["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    assert auth_client.get("/auth/me", headers=headers).status_code == 200

    logout = auth_client.post("/auth/logout", headers=headers)
    assert logout.status_code == 204

    revoked = auth_client.get("/auth/me", headers=headers)
    assert revoked.status_code == 401
    assert revoked.json()["detail"] == "Authentication token has been revoked."


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


def test_hard_delete_user_succeeds_when_user_owns_tickets(auth_client, tmp_path, monkeypatch):
    """Ticket FKs must not block admin hard-delete; attachment files are removed."""
    from app.models.db_models import TicketAttachment
    from app.services.ticket_attachments import resolve_attachment_path

    monkeypatch.setattr(
        "app.services.ticket_attachments.settings.ticket_attachments_dir",
        str(tmp_path / "attachments"),
    )
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
        stored_name = "att1_proof.pdf"
        path = resolve_attachment_path(ticket.id, stored_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"%PDF-1.4 doomed-attachment")
        session.add(
            TicketAttachment(
                id="att-del-001",
                ticket_id=ticket.id,
                uploaded_by_id=student.id,
                original_filename="proof.pdf",
                content_type="application/pdf",
                size_bytes=path.stat().st_size,
                stored_filename=stored_name,
            )
        )
        session.commit()
        student_id = student.id
        token = create_access_token(admin)
        assert path.is_file()
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
    assert not path.is_file()

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
