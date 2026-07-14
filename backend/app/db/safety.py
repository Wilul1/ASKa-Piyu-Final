"""Guards that prevent destructive DB operations against the development database."""

from __future__ import annotations

from sqlalchemy.engine import make_url

from app.config import settings


class UnsafeDatabaseOperationError(RuntimeError):
    """Raised when a destructive DB operation targets a non-test database."""


def database_name_from_url(database_url: str | None) -> str:
    if not database_url:
        return ""
    return str(make_url(database_url).database or "").strip()


def active_database_name() -> str:
    return database_name_from_url(settings.database_url)


def is_test_database_name(name: str | None) -> bool:
    value = (name or "").strip()
    return bool(value) and value.endswith("_test")


def assert_test_environment_uses_test_database() -> None:
    """Abort when ENV=test but the active database is not a *_test database."""
    env = (settings.env or "").strip().lower()
    if env != "test":
        return
    name = active_database_name()
    if not is_test_database_name(name):
        raise UnsafeDatabaseOperationError(
            f"ASKA_ENV=test refuses database '{name or '<unset>'}'. "
            "Configure ASKA_TEST_DATABASE_URL to a database whose name ends with '_test' "
            "(recommended: aska_piyu_test)."
        )


def assert_destructive_database_ops_allowed(database_url: str | None = None) -> None:
    """
    Refuse DELETE/TRUNCATE/DROP/reset against non-test databases unless explicitly allowed.

    Allowed when:
    - database name ends with `_test`, or
    - ASKA_ALLOW_DESTRUCTIVE_RESET=true
    """
    if settings.allow_destructive_reset:
        return
    url = database_url or settings.database_url
    name = database_name_from_url(url)
    if is_test_database_name(name):
        return
    raise UnsafeDatabaseOperationError(
        f"Refusing destructive database operation against '{name or '<unset>'}'. "
        "Use a database whose name ends with '_test' "
        "(recommended ASKA_TEST_DATABASE_URL → aska_piyu_test), "
        "or set ASKA_ALLOW_DESTRUCTIVE_RESET=true."
    )
