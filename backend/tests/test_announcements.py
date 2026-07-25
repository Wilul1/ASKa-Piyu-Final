from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app.main import app
from app.models.db_models import Announcement, User


client = TestClient(app)


def _admin() -> User:
    return User(
        id="admin-1",
        email="admin@test.local",
        password_hash="x",
        full_name="Admin",
        role="admin",
        is_active=True,
        credentials_version=0,
    )


def test_list_published_announcements():
    row = Announcement(
        id="a1",
        title="Enrollment open",
        body="Register this week.",
        published=True,
    )
    session = MagicMock()
    query = session.query.return_value
    query.order_by.return_value.filter.return_value.all.return_value = [row]

    from app.db.session import get_db_session
    from app.services.auth import get_optional_user

    def _db():
        yield session

    app.dependency_overrides[get_db_session] = _db
    app.dependency_overrides[get_optional_user] = lambda: None
    try:
        response = client.get("/announcements")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["title"] == "Enrollment open"


def test_create_announcement_as_admin():
    from app.db.session import get_db_session
    from app.services.auth import require_admin_user

    session = MagicMock()

    def _refresh(row):
        row.id = "new-1"
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        row.created_at = now
        row.updated_at = now

    session.refresh.side_effect = _refresh

    def _db():
        yield session

    app.dependency_overrides[get_db_session] = _db
    app.dependency_overrides[require_admin_user] = _admin
    try:
        response = client.post(
            "/announcements",
            json={"title": "Holiday", "body": "Campus closed Friday.", "published": True},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    assert response.json()["id"] == "new-1"
    assert response.json()["title"] == "Holiday"
    session.add.assert_called()
    session.commit.assert_called()
