from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Query, Session, joinedload

from app.models.db_models import PublishedArticle, Ticket, User


def load_kb_editor_actor(session: Session, actor_id: str | None) -> User | None:
    if not actor_id:
        return None
    return (
        session.query(User)
        .options(joinedload(User.office))
        .filter(User.id == actor_id)
        .one_or_none()
    )


def _normalize_office_name(value: str | None) -> str:
    return (value or "").strip().casefold()


def office_actor_name(actor: User) -> str:
    office = getattr(actor, "office", None)
    return (office.name if office else "").strip()


def article_belongs_to_office_actor(
    session: Session,
    actor: User,
    article: PublishedArticle,
) -> bool:
    role = str(actor.role or "").strip().lower()
    if role == "admin":
        return True
    if role != "office":
        return False

    actor_office = _normalize_office_name(office_actor_name(actor))
    article_office = _normalize_office_name(article.office)
    if actor_office and article_office and actor_office == article_office:
        return True

    if str(article.published_by_user_id or "") == str(actor.id):
        return True
    if str(article.created_by_user_id or "") == str(actor.id):
        return True

    ticket_id = str(article.source_ticket_id or "").strip()
    if ticket_id:
        ticket = session.get(Ticket, ticket_id)
        if ticket is not None and actor.office_id:
            if str(ticket.assigned_office_id or "") == str(actor.office_id):
                return True
        if ticket is not None and actor_office:
            if _normalize_office_name(ticket.assigned_office) == actor_office:
                return True

    return False


def filter_articles_for_office_actor(
    session: Session,
    actor: User,
    query: Query,
) -> Query:
    role = str(actor.role or "").strip().lower()
    if role != "office":
        return query

    actor_office = _normalize_office_name(office_actor_name(actor))
    conditions = [
        PublishedArticle.published_by_user_id == actor.id,
        PublishedArticle.created_by_user_id == actor.id,
    ]
    if actor_office:
        conditions.append(func.lower(PublishedArticle.office) == actor_office)

    if actor.office_id:
        ticket_subq = session.query(Ticket.id).filter(
            Ticket.assigned_office_id == actor.office_id
        )
        conditions.append(PublishedArticle.source_ticket_id.in_(ticket_subq))

    return query.filter(or_(*conditions))


def assert_kb_editor_may_access_article(
    session: Session,
    actor: User | None,
    article: PublishedArticle,
) -> None:
    if actor is None:
        return
    role = str(actor.role or "").strip().lower()
    if role == "admin":
        return
    if article_belongs_to_office_actor(session, actor, article):
        return
    raise HTTPException(
        status_code=403,
        detail="You can only view or edit articles published by your office.",
    )


def assert_kb_editor_may_delete_article(actor: User | None) -> None:
    if actor is None:
        return
    role = str(actor.role or "").strip().lower()
    if role == "office":
        raise HTTPException(
            status_code=403,
            detail="Office accounts cannot delete articles. Unpublish instead.",
        )


def office_article_office_name(actor: User) -> str | None:
    name = office_actor_name(actor)
    return name or None
