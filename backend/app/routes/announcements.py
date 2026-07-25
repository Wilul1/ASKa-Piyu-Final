"""Campus announcements — public list + admin CRUD."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db_session
from app.models.db_models import Announcement, User
from app.services.auth import get_optional_user, require_admin_user

router = APIRouter(prefix="/announcements", tags=["Announcements"])


class AnnouncementSchema(BaseModel):
    id: str
    title: str
    body: str
    published: bool
    created_by_user_id: str | None = None
    created_at: str
    updated_at: str


class AnnouncementCreateRequest(BaseModel):
    title: str = Field(..., min_length=3, max_length=240)
    body: str = Field(..., min_length=3, max_length=8000)
    published: bool = True


class AnnouncementUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=240)
    body: str | None = Field(default=None, min_length=3, max_length=8000)
    published: bool | None = None


class AnnouncementListResponse(BaseModel):
    items: list[AnnouncementSchema]
    total: int


def _to_schema(row: Announcement) -> AnnouncementSchema:
    return AnnouncementSchema(
        id=row.id,
        title=row.title,
        body=row.body,
        published=bool(row.published),
        created_by_user_id=row.created_by_user_id,
        created_at=row.created_at.isoformat() if isinstance(row.created_at, datetime) else str(row.created_at),
        updated_at=row.updated_at.isoformat() if isinstance(row.updated_at, datetime) else str(row.updated_at),
    )


@router.get("", response_model=AnnouncementListResponse)
def list_announcements(
    include_unpublished: bool = False,
    actor: User | None = Depends(get_optional_user),
    session: Session = Depends(get_db_session),
) -> AnnouncementListResponse:
    query = session.query(Announcement).order_by(Announcement.created_at.desc())
    if include_unpublished:
        if actor is None or actor.role != "admin":
            raise HTTPException(status_code=403, detail="Admin access required.")
    else:
        query = query.filter(Announcement.published.is_(True))
    rows = query.all()
    return AnnouncementListResponse(items=[_to_schema(r) for r in rows], total=len(rows))


@router.post("", response_model=AnnouncementSchema)
def create_announcement(
    payload: AnnouncementCreateRequest,
    actor: User = Depends(require_admin_user),
    session: Session = Depends(get_db_session),
) -> AnnouncementSchema:
    row = Announcement(
        title=payload.title.strip(),
        body=payload.body.strip(),
        published=bool(payload.published),
        created_by_user_id=actor.id,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return _to_schema(row)


@router.patch("/{announcement_id}", response_model=AnnouncementSchema)
def update_announcement(
    announcement_id: str,
    payload: AnnouncementUpdateRequest,
    _: User = Depends(require_admin_user),
    session: Session = Depends(get_db_session),
) -> AnnouncementSchema:
    row = session.get(Announcement, announcement_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Announcement not found.")
    if payload.title is not None:
        row.title = payload.title.strip()
    if payload.body is not None:
        row.body = payload.body.strip()
    if payload.published is not None:
        row.published = bool(payload.published)
    session.add(row)
    session.commit()
    session.refresh(row)
    return _to_schema(row)


@router.delete("/{announcement_id}")
def delete_announcement(
    announcement_id: str,
    _: User = Depends(require_admin_user),
    session: Session = Depends(get_db_session),
) -> dict[str, str | bool]:
    row = session.get(Announcement, announcement_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Announcement not found.")
    session.delete(row)
    session.commit()
    return {"success": True, "deleted_id": announcement_id}
