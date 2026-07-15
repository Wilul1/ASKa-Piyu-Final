"""Authentication routes backed by PostgreSQL application data."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db_session
from app.models.db_models import Office, User
from app.models.schemas import (
    AuthResponse,
    CreateOfficeAccountRequest,
    LoginRequest,
    SignupRequest,
    UserListResponse,
    UserSchema,
)
from app.services.auth import create_access_token, get_current_user
from app.services.passwords import hash_password, verify_password
from app.services.ticket_office_resolver import resolve_office_for_ticket


router = APIRouter(prefix="/auth", tags=["Authentication"])


def user_to_schema(user: User) -> UserSchema:
    return UserSchema(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        office_id=user.office_id,
        office_name=user.office.name if user.office is not None else None,
        student_id=user.student_id,
        created_at=_datetime_to_iso(user.created_at),
        updated_at=_datetime_to_iso(user.updated_at),
    )


def _datetime_to_iso(value: datetime) -> str:
    return value.isoformat()


@router.post("/signup", response_model=AuthResponse)
def signup(payload: SignupRequest, session: Session = Depends(get_db_session)) -> AuthResponse:
    if payload.role != "student":
        raise HTTPException(status_code=403, detail="Public signup can create student accounts only.")

    existing_user = session.query(User).filter(User.email == payload.email).first()
    if existing_user is not None:
        raise HTTPException(status_code=409, detail="Email is already registered.")

    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name,
        role="student",
        student_id=payload.student_id,
    )
    session.add(user)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Email is already registered.") from exc
    session.refresh(user)

    return AuthResponse(access_token=create_access_token(user), user=user_to_schema(user))


@router.post("/login", response_model=AuthResponse)
def login(payload: LoginRequest, session: Session = Depends(get_db_session)) -> AuthResponse:
    user = session.query(User).filter(User.email == payload.email).first()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    return AuthResponse(access_token=create_access_token(user), user=user_to_schema(user))


@router.get("/me", response_model=UserSchema)
def me(current_user: User = Depends(get_current_user)) -> UserSchema:
    return user_to_schema(current_user)


@router.get("/users", response_model=UserListResponse)
def list_users(
    role: str | None = None,
    actor: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> UserListResponse:
    """Admin-only: list application users (students, office staff, admins)."""
    if actor.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can list users.")

    query = session.query(User).order_by(User.created_at.desc())
    if role is not None:
        normalized = role.strip().lower()
        if normalized not in {"student", "office", "admin"}:
            raise HTTPException(status_code=422, detail="role must be student, office, or admin.")
        query = query.filter(User.role == normalized)

    users = query.all()
    return UserListResponse(
        items=[user_to_schema(user) for user in users],
        total=len(users),
    )


@router.post("/office-accounts", response_model=UserSchema)
def create_office_account(
    payload: CreateOfficeAccountRequest,
    actor: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> UserSchema:
    """Admin-only: create an office staff login linked to an office."""
    if actor.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can create office accounts.")

    if session.query(User).filter(User.email == payload.email).first() is not None:
        raise HTTPException(status_code=409, detail="Email is already registered.")

    office: Office | None = None
    if payload.office_id:
        office = session.get(Office, payload.office_id)
        if office is None:
            raise HTTPException(status_code=422, detail="Office was not found.")
    elif payload.office_name:
        try:
            office_id, _ = resolve_office_for_ticket(session, payload.office_name)
            office = session.get(Office, office_id)
        except LookupError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if office is None:
            raise HTTPException(status_code=422, detail="Office was not found.")
    else:
        raise HTTPException(status_code=422, detail="Provide office_id or office_name.")

    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name.strip(),
        role="office",
        office_id=office.id,
    )
    session.add(user)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Email is already registered.") from exc
    session.refresh(user)
    return user_to_schema(user)
