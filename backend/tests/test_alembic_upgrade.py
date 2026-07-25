"""Alembic: announcements migration must not fail after baseline create_all."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Column, MetaData, String, Table, create_engine, inspect


def _load_announcements_revision():
    rev_path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "20260725_0002_announcements.py"
    )
    spec = importlib.util.spec_from_file_location("alembic_rev_0002", rev_path)
    assert spec is not None and spec.loader is not None
    rev = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rev)
    return rev


def test_announcements_revision_noop_when_table_already_exists(tmp_path: Path) -> None:
    """Fresh DBs: 0001 create_all already creates announcements; 0002 must skip."""
    from app.db.base import Base
    from app.models import db_models  # noqa: F401

    rev = _load_announcements_revision()
    url = f"sqlite:///{(tmp_path / 'ann.db').as_posix()}"
    engine = create_engine(url)
    with engine.begin() as conn:
        Base.metadata.create_all(bind=conn)
        assert inspect(conn).has_table("announcements")

        context = MigrationContext.configure(conn)
        with Operations.context(context):
            rev.upgrade()  # must not raise DuplicateTable / OperationalError

        assert inspect(conn).has_table("announcements")
    engine.dispose()


def test_additive_schema_revision_wires_shared_upgrades() -> None:
    """Prod path: head includes 0003 which applies the same statements as startup init."""
    import importlib.util

    from app.db.schema_upgrades import ADDITIVE_SCHEMA_STATEMENTS

    rev_path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "20260725_0004_office_alias_is_active.py"
    )
    spec = importlib.util.spec_from_file_location("alembic_rev_0004", rev_path)
    assert spec is not None and spec.loader is not None
    rev = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rev)

    assert rev.revision == "20260725_0004"
    assert rev.down_revision == "20260725_0003"
    # Critical columns that old campus DBs may lack when INIT_ON_STARTUP=false.
    joined = "\n".join(ADDITIVE_SCHEMA_STATEMENTS)
    for needle in (
        "source_document_id",
        "assigned_office_id",
        "kb_article_id",
        "kb_conversion_status",
        "source_ticket_id",
        "audience",
        "kb_origin",
        "rag_indexed",
        "credentials_version",
        "office_aliases",
        "is_active",
    ):
        assert needle in joined


def test_announcements_revision_creates_table_when_missing(tmp_path: Path) -> None:
    """Legacy DBs stamped at 0001 before Announcement model existed still need 0002."""
    rev = _load_announcements_revision()
    url = f"sqlite:///{(tmp_path / 'legacy.db').as_posix()}"
    engine = create_engine(url)
    with engine.begin() as conn:
        # Minimal FK target so create_table(announcements) can succeed.
        md = MetaData()
        Table("users", md, Column("id", String(36), primary_key=True))
        md.create_all(bind=conn)
        assert not inspect(conn).has_table("announcements")

        context = MigrationContext.configure(conn)
        with Operations.context(context):
            rev.upgrade()

        assert inspect(conn).has_table("announcements")
    engine.dispose()
