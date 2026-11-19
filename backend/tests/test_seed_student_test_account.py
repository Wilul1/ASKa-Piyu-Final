"""Focused tests for scripts/seed_student_test_account.py.

The real app database is never connected: session and initialize_database
are monkeypatched. Production refusal is asserted before any DB call.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

from app.services.passwords import verify_password

seed_student = importlib.import_module("scripts.seed_student_test_account")


class _FakeQuery:
    def __init__(self, result):
        self._result = result

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self._result


class _FakeSession:
    def __init__(self, existing_user=None):
        self.existing_user = existing_user
        self.added = []
        self.committed = False
        self.closed = False

    def query(self, model):
        return _FakeQuery(self.existing_user)

    def add(self, obj):
        self.added.append(obj)
        obj.id = "student-test-id"

    def commit(self):
        self.committed = True

    def refresh(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = "student-test-id"

    def close(self):
        self.closed = True


class _ExistingUser:
    def __init__(self, *, email, role, password_hash="old-hash"):
        self.id = "existing-id"
        self.email = email
        self.role = role
        self.password_hash = password_hash
        self.full_name = "Existing"
        self.office_id = "office-1"
        self.is_active = True
        self.email_verified = False
        self.email_verification_code_hash = "abc"
        self.email_verification_expires_at = "soon"
        self.credentials_version = 1


def _never_touch_db(*args, **kwargs):
    raise AssertionError("Database helpers must not run for this assertion.")


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch, tmp_path):
    for key in (
        "ASKA_SEED_STUDENT_EMAIL",
        "ASKA_SEED_STUDENT_PASSWORD",
        "ASKA_SEED_STUDENT_NAME",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(sys, "argv", ["seed_student_test_account.py"])
    monkeypatch.setattr(seed_student.settings, "env", "development")
    creds = tmp_path / "student_test_account.txt"
    monkeypatch.setattr(seed_student, "CREDENTIALS_PATH", creds)


def _run(monkeypatch, *, existing_user=None):
    fake_session = _FakeSession(existing_user=existing_user)
    monkeypatch.setattr(seed_student, "get_session_factory", lambda: (lambda: fake_session))
    monkeypatch.setattr(seed_student, "initialize_database", lambda: None)
    seed_student.main()
    return fake_session


def test_refuses_production_without_touching_db(monkeypatch):
    monkeypatch.setattr(seed_student.settings, "env", "production")
    monkeypatch.setattr(seed_student, "get_session_factory", _never_touch_db)
    monkeypatch.setattr(seed_student, "initialize_database", _never_touch_db)
    monkeypatch.setattr(sys, "argv", ["seed_student_test_account.py", "--password", "ValidPass123"])
    with pytest.raises(SystemExit, match="production"):
        seed_student.main()


def test_creates_active_verified_student(monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        ["seed_student_test_account.py", "--password", "ValidPass123"],
    )
    session = _run(monkeypatch)
    assert len(session.added) == 1
    user = session.added[0]
    assert user.email == "student@aska.local"
    assert user.role == "student"
    assert user.is_active is True
    assert user.email_verified is True
    assert user.password_hash != "ValidPass123"
    assert verify_password("ValidPass123", user.password_hash)
    output = capsys.readouterr().out
    assert "ValidPass123" not in output
    assert "Created student test account" in output


def test_idempotent_when_student_already_exists(monkeypatch, capsys):
    existing = _ExistingUser(email="student@aska.local", role="student")
    monkeypatch.setattr(
        sys,
        "argv",
        ["seed_student_test_account.py", "--password", "ValidPass123"],
    )
    session = _run(monkeypatch, existing_user=existing)
    assert session.added == []
    assert existing.password_hash == "old-hash"
    assert "already exists" in capsys.readouterr().out


def test_refuses_to_overwrite_admin_account(monkeypatch):
    existing = _ExistingUser(email="student@aska.local", role="admin")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "seed_student_test_account.py",
            "--password",
            "ValidPass123",
            "--force-reset-password",
        ],
    )
    with pytest.raises(SystemExit, match="non-student"):
        _run(monkeypatch, existing_user=existing)
    assert existing.role == "admin"
    assert existing.password_hash == "old-hash"


def test_force_reset_keeps_student_role(monkeypatch):
    existing = _ExistingUser(email="student@aska.local", role="student")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "seed_student_test_account.py",
            "--password",
            "ValidPass123",
            "--force-reset-password",
        ],
    )
    _run(monkeypatch, existing_user=existing)
    assert existing.role == "student"
    assert existing.office_id is None
    assert existing.email_verified is True
    assert existing.is_active is True
    assert verify_password("ValidPass123", existing.password_hash)
    assert existing.credentials_version == 2


def test_source_does_not_hardcode_a_student_password():
    source = Path(seed_student.__file__).read_text(encoding="utf-8")
    assert "office123" not in source
    assert "StudentPass" not in source
    assert "changeme" not in source.lower()
