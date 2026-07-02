from __future__ import annotations

from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.db.base import Base


def safe_database_url(database_url: str | None = None) -> str | None:
    if not database_url:
        return None
    return make_url(database_url).render_as_string(hide_password=True)


def safe_database_error(exc: Exception) -> str:
    detail = str(exc)
    if settings.database_url:
        detail = detail.replace(settings.database_url, safe_database_url(settings.database_url) or "")
    return detail


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    if not settings.database_url:
        raise RuntimeError("ASKA_DATABASE_URL is not configured.")
    return create_engine(settings.database_url, pool_pre_ping=True)


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, autocommit=False, expire_on_commit=False)


def get_db_session() -> Generator[Session, None, None]:
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def initialize_database(engine: Engine | None = None) -> None:
    from app.models import db_models  # noqa: F401

    target_engine = engine or get_engine()
    Base.metadata.create_all(bind=target_engine)


def check_database_connection(engine: Engine | None = None) -> None:
    target_engine = engine or get_engine()
    with target_engine.connect() as connection:
        connection.execute(text("SELECT 1"))


def get_database_health() -> dict:
    if not settings.database_url:
        return {
            "status": "disabled",
            "configured": False,
            "database_url": None,
            "detail": "ASKA_DATABASE_URL is not configured.",
        }

    try:
        check_database_connection()
    except (RuntimeError, SQLAlchemyError) as exc:
        return {
            "status": "error",
            "configured": True,
            "database_url": safe_database_url(settings.database_url),
            "detail": safe_database_error(exc),
        }

    return {
        "status": "ok",
        "configured": True,
        "database_url": safe_database_url(settings.database_url),
    }
