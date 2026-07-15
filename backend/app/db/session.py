from __future__ import annotations

from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.db.base import Base
from app.db.safety import assert_destructive_database_ops_allowed, database_name_from_url


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


def clear_engine_caches() -> None:
    """Clear cached engine/session factory (used when tests rebind the DB URL)."""
    get_engine.cache_clear()
    get_session_factory.cache_clear()


def get_db_session() -> Generator[Session, None, None]:
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def initialize_database(engine: Engine | None = None) -> None:
    """
    Create missing tables only.

    Never drops, truncates, or deletes rows (including published_articles).
    Also applies safe additive column upgrades for citation grounding.
    """
    from app.models import db_models  # noqa: F401

    target_engine = engine or get_engine()
    Base.metadata.create_all(bind=target_engine)
    _ensure_additive_schema_upgrades(target_engine)


def _ensure_additive_schema_upgrades(engine: Engine) -> None:
    """Add newly introduced columns without dropping existing data."""
    dialect = engine.dialect.name
    if dialect == "sqlite":
        # Fresh sqlite create_all already includes new columns; skip ALTER IF NOT EXISTS
        # which older sqlite builds used in unit tests may not support.
        return
    statements = [
        "ALTER TABLE published_articles ADD COLUMN IF NOT EXISTS source_document_id VARCHAR(36)",
        "CREATE INDEX IF NOT EXISTS ix_published_articles_source_document_id "
        "ON published_articles (source_document_id)",
        "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS assigned_office_id VARCHAR(36)",
        "CREATE INDEX IF NOT EXISTS ix_tickets_assigned_office_id ON tickets (assigned_office_id)",
        "CREATE INDEX IF NOT EXISTS ix_tickets_user_id_updated_at ON tickets (user_id, updated_at)",
        "CREATE INDEX IF NOT EXISTS ix_tickets_office_status_updated "
        "ON tickets (assigned_office_id, status, updated_at)",
        "ALTER TABLE tickets DROP CONSTRAINT IF EXISTS ck_tickets_priority",
        "ALTER TABLE tickets ADD CONSTRAINT ck_tickets_priority "
        "CHECK (priority IN ('Urgent', 'High', 'Medium', 'Low'))",
    ]
    with engine.begin() as connection:
        for statement in statements:
            try:
                connection.execute(text(statement))
            except SQLAlchemyError:
                # Constraint may already match or table may be empty on fresh DBs.
                pass


def drop_all_tables(engine: Engine | None = None) -> None:
    """Drop all ORM tables — refused unless targeting a *_test DB (or explicit allow)."""
    from app.models import db_models  # noqa: F401

    target_engine = engine or get_engine()
    url = str(target_engine.url)
    assert_destructive_database_ops_allowed(url)
    Base.metadata.drop_all(bind=target_engine)


def truncate_published_articles(session: Session) -> int:
    """Delete all published_articles rows — refused on non-test databases."""
    from app.models.db_models import PublishedArticle

    assert_destructive_database_ops_allowed()
    deleted = session.query(PublishedArticle).delete()
    session.commit()
    return int(deleted or 0)


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
        "database_name": database_name_from_url(settings.database_url),
    }
