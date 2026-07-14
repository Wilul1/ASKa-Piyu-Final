"""
Pytest bootstrap — MUST configure the test database before any `app.*` import.

Tests wipe published_articles during cleanup. They must never target aska_piyu.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

BACKEND_DIR = Path(__file__).resolve().parents[1]
DOTENV_PATH = BACKEND_DIR / ".env"
REQUIRED_TEST_DB_NAME = "aska_piyu_test"


def _parse_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _resolve_test_database_url() -> str:
    dotenv = _parse_dotenv(DOTENV_PATH)
    test_url = (
        os.environ.get("ASKA_TEST_DATABASE_URL")
        or dotenv.get("ASKA_TEST_DATABASE_URL")
        or ""
    ).strip()
    if not test_url:
        base = (
            os.environ.get("ASKA_DATABASE_URL")
            or dotenv.get("ASKA_DATABASE_URL")
            or ""
        ).strip()
        if not base:
            raise RuntimeError(
                "ASKA_TEST_DATABASE_URL is not configured and ASKA_DATABASE_URL is missing. "
                f"Set ASKA_TEST_DATABASE_URL to postgresql+psycopg://.../{REQUIRED_TEST_DB_NAME}"
            )
        test_url = make_url(base).set(database=REQUIRED_TEST_DB_NAME).render_as_string(
            hide_password=False
        )

    name = str(make_url(test_url).database or "")
    if name != REQUIRED_TEST_DB_NAME:
        raise RuntimeError(
            f"Refusing to run pytest against database '{name}'. "
            f"ASKA_TEST_DATABASE_URL must point at '{REQUIRED_TEST_DB_NAME}'."
        )
    return test_url


def _ensure_database_exists(database_url: str) -> None:
    url = make_url(database_url)
    db_name = url.database
    if not db_name:
        raise RuntimeError("Test database URL is missing a database name.")
    admin_url = url.set(database="postgres")
    engine = create_engine(
        admin_url.render_as_string(hide_password=False),
        isolation_level="AUTOCOMMIT",
        pool_pre_ping=True,
    )
    try:
        with engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": db_name},
            ).scalar()
            if not exists:
                # Identifiers cannot be parameterized; db_name is constrained to *_test.
                if not db_name.endswith("_test"):
                    raise RuntimeError(f"Refusing to CREATE DATABASE '{db_name}'.")
                conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    finally:
        engine.dispose()


def _bootstrap_test_database_env() -> None:
    test_url = _resolve_test_database_url()
    name = str(make_url(test_url).database or "")
    if not name.endswith("_test"):
        raise RuntimeError(
            f"Aborting pytest: active test database '{name}' does not end with '_test'."
        )

    # Force test mode + isolated URL before Settings / SQLAlchemy engines load.
    os.environ["ASKA_ENV"] = "test"
    os.environ["ASKA_DATABASE_URL"] = test_url
    os.environ.setdefault("ASKA_TEST_DATABASE_URL", test_url)
    # Keep explicit destructive override off; *_test name alone allows cleanup.
    os.environ.setdefault("ASKA_ALLOW_DESTRUCTIVE_RESET", "false")

    _ensure_database_exists(test_url)


_bootstrap_test_database_env()

import pytest

from app.config import settings
from app.db.safety import (
    UnsafeDatabaseOperationError,
    active_database_name,
    assert_test_environment_uses_test_database,
)
from app.db.session import clear_engine_caches, initialize_database


@pytest.fixture(scope="session", autouse=True)
def _isolate_tests_on_aska_piyu_test() -> None:
    clear_engine_caches()
    assert_test_environment_uses_test_database()
    name = active_database_name()
    if name != REQUIRED_TEST_DB_NAME:
        raise UnsafeDatabaseOperationError(
            f"Aborting pytest: expected {REQUIRED_TEST_DB_NAME}, got '{name}'."
        )
    if not (settings.env or "").strip().lower() == "test":
        raise UnsafeDatabaseOperationError(
            f"Aborting pytest: ASKA_ENV must be 'test' during tests (got {settings.env!r})."
        )
    initialize_database()


@pytest.fixture(autouse=True)
def _abort_if_dev_database() -> None:
    """
    Per-test guard against the live SQLAlchemy engine binding.

    Uses the cached engine URL (set at session bootstrap), not monkeypatched
    settings values used by isolation unit tests.
    """
    from app.db.session import get_engine

    name = str(get_engine().url.database or "")
    if name != REQUIRED_TEST_DB_NAME:
        raise UnsafeDatabaseOperationError(
            f"Aborting test: engine is bound to '{name}', expected '{REQUIRED_TEST_DB_NAME}'."
        )
