"""Idempotent additive Postgres schema upgrades shared by startup init and Alembic."""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings

logger = logging.getLogger(__name__)

# Keep in sync with ORM models: columns/indexes/constraints introduced after the
# original campus schema. Safe to re-run (IF NOT EXISTS / DROP IF EXISTS).
ADDITIVE_SCHEMA_STATEMENTS: tuple[str, ...] = (
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS credentials_version INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE published_articles ADD COLUMN IF NOT EXISTS source_document_id VARCHAR(36)",
    "CREATE INDEX IF NOT EXISTS ix_published_articles_source_document_id "
    "ON published_articles (source_document_id)",
    "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS assigned_office_id VARCHAR(36)",
    "CREATE INDEX IF NOT EXISTS ix_tickets_assigned_office_id ON tickets (assigned_office_id)",
    "CREATE INDEX IF NOT EXISTS ix_tickets_user_id_updated_at ON tickets (user_id, updated_at)",
    "CREATE INDEX IF NOT EXISTS ix_tickets_office_status_updated "
    "ON tickets (assigned_office_id, status, updated_at)",
    "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS kb_article_id VARCHAR(36)",
    "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS kb_conversion_status VARCHAR(20) DEFAULT 'none'",
    "CREATE INDEX IF NOT EXISTS ix_tickets_kb_article_id ON tickets (kb_article_id)",
    "ALTER TABLE published_articles ADD COLUMN IF NOT EXISTS source_ticket_id VARCHAR(32)",
    "ALTER TABLE published_articles ADD COLUMN IF NOT EXISTS audience VARCHAR(20) DEFAULT 'both'",
    "ALTER TABLE published_articles ADD COLUMN IF NOT EXISTS kb_origin VARCHAR(40) DEFAULT 'document'",
    "ALTER TABLE published_articles ADD COLUMN IF NOT EXISTS resolution_summary TEXT",
    "ALTER TABLE published_articles ADD COLUMN IF NOT EXISTS created_by_user_id VARCHAR(36)",
    "ALTER TABLE published_articles ADD COLUMN IF NOT EXISTS published_by_user_id VARCHAR(36)",
    "ALTER TABLE published_articles ADD COLUMN IF NOT EXISTS rag_indexed BOOLEAN DEFAULT FALSE",
    "ALTER TABLE published_articles ADD COLUMN IF NOT EXISTS rag_document_id VARCHAR(80)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_published_articles_source_ticket_id "
    "ON published_articles (source_ticket_id)",
    "CREATE INDEX IF NOT EXISTS ix_published_articles_audience ON published_articles (audience)",
    "CREATE INDEX IF NOT EXISTS ix_published_articles_kb_origin ON published_articles (kb_origin)",
    "ALTER TABLE tickets DROP CONSTRAINT IF EXISTS ck_tickets_priority",
    "ALTER TABLE tickets ADD CONSTRAINT ck_tickets_priority "
    "CHECK (priority IN ('Urgent', 'High', 'Medium', 'Low'))",
    "ALTER TABLE tickets DROP CONSTRAINT IF EXISTS ck_tickets_kb_conversion_status",
    "ALTER TABLE tickets ADD CONSTRAINT ck_tickets_kb_conversion_status "
    "CHECK (kb_conversion_status IN ('none', 'draft', 'published'))",
    "ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_users_role",
    "ALTER TABLE users ADD CONSTRAINT ck_users_role "
    "CHECK (role IN ('student', 'faculty', 'office', 'admin'))",
    "ALTER TABLE ticket_replies DROP CONSTRAINT IF EXISTS ck_ticket_replies_sender_role",
    "ALTER TABLE ticket_replies ADD CONSTRAINT ck_ticket_replies_sender_role "
    "CHECK (sender_role IN ('student', 'faculty', 'office', 'admin'))",
    "ALTER TABLE published_articles DROP CONSTRAINT IF EXISTS ck_published_articles_audience",
    "ALTER TABLE published_articles ADD CONSTRAINT ck_published_articles_audience "
    "CHECK (audience IN ('student', 'faculty', 'both'))",
    "ALTER TABLE published_articles DROP CONSTRAINT IF EXISTS ck_published_articles_kb_origin",
    "ALTER TABLE published_articles ADD CONSTRAINT ck_published_articles_kb_origin "
    "CHECK (kb_origin IN ('document', 'ticket_resolution'))",
    "UPDATE tickets SET kb_conversion_status = 'none' WHERE kb_conversion_status IS NULL",
    "UPDATE published_articles SET audience = 'student' WHERE audience IS NULL",
    "UPDATE published_articles SET kb_origin = 'document' WHERE kb_origin IS NULL",
    "UPDATE published_articles SET rag_indexed = FALSE WHERE rag_indexed IS NULL",
    # Deduplicate slugs before enforcing uniqueness (keep oldest row's slug).
    """
    UPDATE published_articles AS p
    SET slug = LEFT(p.slug, 200) || '-' || SUBSTRING(REPLACE(p.id::text, '-', '') FROM 1 FOR 8)
    FROM (
        SELECT id,
               ROW_NUMBER() OVER (PARTITION BY slug ORDER BY created_at ASC NULLS LAST, id ASC) AS rn
        FROM published_articles
    ) AS d
    WHERE p.id = d.id AND d.rn > 1
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_published_articles_slug ON published_articles (slug)",
)


def apply_additive_schema_upgrades(connection: Connection) -> None:
    """Apply additive columns/indexes/constraints. No-op on SQLite (tests use create_all)."""
    if connection.dialect.name == "sqlite":
        return

    for statement in ADDITIVE_SCHEMA_STATEMENTS:
        try:
            connection.execute(text(statement))
        except SQLAlchemyError as exc:
            detail = str(exc).lower()
            if any(
                token in detail
                for token in (
                    "already exists",
                    "duplicate",
                    "exists",
                )
            ):
                logger.debug("Schema upgrade skipped (already applied): %s", statement[:80])
                continue
            logger.exception(
                "Additive schema upgrade failed (statement=%s)",
                statement[:120].replace("\n", " "),
            )
            if (settings.env or "").strip().lower() == "production":
                raise
