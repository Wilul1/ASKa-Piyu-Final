"""Focused tests for scripts/seed_admin.py's password resolution (CLI arg /
env var / interactive getpass fallback).

None of these tests execute a real reset against a real database:
``get_session_factory`` and ``initialize_database`` are monkeypatched to an
in-memory fake session (or, for the error-path tests, to a function that
raises if ever called at all, proving the database layer was never
reached). The real app database is never imported or connected to here.
"""
from __future__ import annotations

import importlib
import sys

import pytest

seed_admin = importlib.import_module("scripts.seed_admin")


class _FakeQuery:
    def __init__(self, result):
        self._result = result

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self._result


class _FakeSession:
    """In-memory stand-in -- no engine, no connection, no real database."""

    def __init__(self, existing_user=None):
        self.existing_user = existing_user
        self.added = []
        self.committed = False
        self.refreshed = False
        self.closed = False

    def query(self, model):
        return _FakeQuery(self.existing_user)

    def add(self, obj):
        self.added.append(obj)
        obj.id = "fake-id-0001"

    def commit(self):
        self.committed = True

    def refresh(self, obj):
        self.refreshed = True

    def close(self):
        self.closed = True


def _never_touch_db(*args, **kwargs):
    raise AssertionError("A real database function was called -- it must not be for this test.")


@pytest.fixture(autouse=True)
def _isolate_argv_and_env(monkeypatch):
    # Never let a stray ASKA_SEED_ADMIN_* env var from the real environment
    # leak into these tests.
    for key in ("ASKA_SEED_ADMIN_EMAIL", "ASKA_SEED_ADMIN_PASSWORD", "ASKA_SEED_ADMIN_NAME"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(sys, "argv", ["seed_admin.py"])


def _run_main_with_fake_db(monkeypatch, *, existing_user=None):
    fake_session = _FakeSession(existing_user=existing_user)
    monkeypatch.setattr(seed_admin, "get_session_factory", lambda: (lambda: fake_session))
    monkeypatch.setattr(seed_admin, "initialize_database", lambda: None)
    seed_admin.main()
    return fake_session


def test_password_from_cli_arg_skips_getpass_prompt(monkeypatch, capsys):
    monkeypatch.setattr(
        sys, "argv",
        ["seed_admin.py", "--email", "newadmin@example.edu", "--password", "ValidPass123"],
    )

    def _fail_if_called(prompt=""):
        raise AssertionError("getpass.getpass must not be called when --password was given.")

    monkeypatch.setattr(seed_admin.getpass, "getpass", _fail_if_called)

    session = _run_main_with_fake_db(monkeypatch)
    assert session.committed is True
    assert len(session.added) == 1
    created_user = session.added[0]
    from app.services.passwords import verify_password
    assert verify_password("ValidPass123", created_user.password_hash)


def test_password_from_env_var_skips_getpass_prompt(monkeypatch):
    monkeypatch.setenv("ASKA_SEED_ADMIN_EMAIL", "envadmin@example.edu")
    monkeypatch.setenv("ASKA_SEED_ADMIN_PASSWORD", "EnvPassword1")

    def _fail_if_called(prompt=""):
        raise AssertionError("getpass.getpass must not be called when the env var was set.")

    monkeypatch.setattr(seed_admin.getpass, "getpass", _fail_if_called)

    session = _run_main_with_fake_db(monkeypatch)
    assert session.committed is True
    from app.services.passwords import verify_password
    assert verify_password("EnvPassword1", session.added[0].password_hash)


def test_missing_password_falls_back_to_interactive_prompt(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["seed_admin.py", "--email", "prompted@example.edu"])

    prompts_seen = []

    def _fake_getpass(prompt=""):
        prompts_seen.append(prompt)
        return "PromptedPass1"

    monkeypatch.setattr(seed_admin.getpass, "getpass", _fake_getpass)

    session = _run_main_with_fake_db(monkeypatch)

    assert len(prompts_seen) == 1
    # The prompt text itself never contains the password.
    assert "PromptedPass1" not in prompts_seen[0]
    from app.services.passwords import verify_password
    assert verify_password("PromptedPass1", session.added[0].password_hash)

    captured = capsys.readouterr()
    assert "PromptedPass1" not in captured.out
    assert "PromptedPass1" not in captured.err


def test_empty_prompt_response_raises_without_touching_database(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["seed_admin.py", "--email", "nopass@example.edu"])
    monkeypatch.setattr(seed_admin.getpass, "getpass", lambda prompt="": "")
    monkeypatch.setattr(seed_admin, "get_session_factory", _never_touch_db)
    monkeypatch.setattr(seed_admin, "initialize_database", _never_touch_db)

    with pytest.raises(SystemExit, match="enter it at the prompt"):
        seed_admin.main()


def test_weak_prompted_password_is_rejected_without_touching_database(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["seed_admin.py", "--email", "weak@example.edu"])
    monkeypatch.setattr(seed_admin.getpass, "getpass", lambda prompt="": "short1")
    monkeypatch.setattr(seed_admin, "get_session_factory", _never_touch_db)
    monkeypatch.setattr(seed_admin, "initialize_database", _never_touch_db)

    with pytest.raises(SystemExit, match="at least 10 characters"):
        seed_admin.main()


def test_missing_email_errors_before_any_password_prompt(monkeypatch):
    """Preserves the original email-before-password error ordering --
    getpass must never fire when email itself is invalid."""
    monkeypatch.setattr(sys, "argv", ["seed_admin.py", "--password", "ValidPass123"])

    def _fail_if_called(prompt=""):
        raise AssertionError("getpass.getpass must not be called before the email check.")

    monkeypatch.setattr(seed_admin.getpass, "getpass", _fail_if_called)
    monkeypatch.setattr(seed_admin, "get_session_factory", _never_touch_db)
    monkeypatch.setattr(seed_admin, "initialize_database", _never_touch_db)

    with pytest.raises(SystemExit, match="ASKA_SEED_ADMIN_EMAIL"):
        seed_admin.main()
