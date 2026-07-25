"""Authentication routes backed by PostgreSQL application data."""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db_session
from app.models.db_models import Office, User
from app.models.schemas import (
    AdminResetPasswordRequest,
    AdminSetUserActiveRequest,
    AuthResponse,
    ChangePasswordRequest,
    CreateFacultyAccountRequest,
    CreateOfficeAccountRequest,
    LoginRequest,
    SignupRequest,
    UserListResponse,
    UserSchema,
)
from app.services.auth import create_access_token, get_current_user
from app.services.auth_rate_limit import (
    LOGIN_LIMIT,
    SIGNUP_LIMIT,
    check_auth_rate_limit,
)
from app.services.client_ip import client_ip
from app.services.passwords import hash_password, verify_password
from app.services.ticket_office_resolver import resolve_office_for_ticket


logger = logging.getLogger(__name__)
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
        is_active=bool(getattr(user, "is_active", True)),
        created_at=_datetime_to_iso(user.created_at),
        updated_at=_datetime_to_iso(user.updated_at),
    )


def _bump_credentials(user: User) -> None:
    user.credentials_version = int(getattr(user, "credentials_version", 0) or 0) + 1


def _datetime_to_iso(value: datetime) -> str:
    return value.isoformat()


@router.post("/signup", response_model=AuthResponse)
def signup(
    payload: SignupRequest,
    request: Request,
    session: Session = Depends(get_db_session),
) -> AuthResponse:
    client = client_ip(request)
    if not check_auth_rate_limit(f"signup:ip:{client}", limit=SIGNUP_LIMIT):
        raise HTTPException(
            status_code=429,
            detail="Too many signup attempts. Please wait a moment and try again.",
        )

    if payload.role != "student":
        raise HTTPException(
            status_code=403,
            detail="Public signup can create student accounts only.",
        )

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
def login(
    payload: LoginRequest,
    request: Request,
    session: Session = Depends(get_db_session),
) -> AuthResponse:
    client = client_ip(request)
    if not check_auth_rate_limit(f"login:ip:{client}", limit=LOGIN_LIMIT):
        raise HTTPException(
            status_code=429,
            detail="Too many login attempts. Please wait a moment and try again.",
        )
    if not check_auth_rate_limit(f"login:email:{payload.email}", limit=LOGIN_LIMIT):
        raise HTTPException(
            status_code=429,
            detail="Too many login attempts. Please wait a moment and try again.",
        )

    user = session.query(User).filter(User.email == payload.email).first()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    if not bool(getattr(user, "is_active", True)):
        raise HTTPException(status_code=403, detail="Account is disabled.")

    return AuthResponse(access_token=create_access_token(user), user=user_to_schema(user))


@router.get("/me", response_model=UserSchema)
def me(current_user: User = Depends(get_current_user)) -> UserSchema:
    return user_to_schema(current_user)


@router.post("/change-password", response_model=AuthResponse)
def change_password(
    payload: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> AuthResponse:
    user = session.get(User, current_user.id)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid authentication token.")
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=401, detail="Current password is incorrect.")
    user.password_hash = hash_password(payload.new_password)
    _bump_credentials(user)
    session.add(user)
    session.commit()
    session.refresh(user)
    return AuthResponse(access_token=create_access_token(user), user=user_to_schema(user))


@router.patch("/users/{user_id}/active", response_model=UserSchema)
def set_user_active(
    user_id: str,
    payload: AdminSetUserActiveRequest,
    actor: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> UserSchema:
    if actor.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can enable or disable users.")
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    if user.id == actor.id and not payload.is_active:
        raise HTTPException(status_code=400, detail="You cannot disable your own account.")
    user.is_active = bool(payload.is_active)
    if not user.is_active:
        _bump_credentials(user)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user_to_schema(user)


@router.post("/users/{user_id}/reset-password", response_model=UserSchema)
def admin_reset_password(
    user_id: str,
    payload: AdminResetPasswordRequest,
    actor: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> UserSchema:
    if actor.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can reset passwords.")
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    user.password_hash = hash_password(payload.new_password)
    _bump_credentials(user)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user_to_schema(user)


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
        if normalized not in {"student", "faculty", "office", "admin"}:
            raise HTTPException(status_code=422, detail="role must be student, faculty, office, or admin.")
        query = query.filter(User.role == normalized)

    users = query.all()
    return UserListResponse(
        items=[user_to_schema(user) for user in users],
        total=len(users),
    )


@router.post("/faculty-accounts", response_model=UserSchema)
def create_faculty_account(
    payload: CreateFacultyAccountRequest,
    actor: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> UserSchema:
    """Admin-only: create a faculty login (public signup cannot choose faculty)."""
    if actor.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can create faculty accounts.")

    if session.query(User).filter(User.email == payload.email).first() is not None:
        raise HTTPException(status_code=409, detail="Email is already registered.")

    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name.strip(),
        role="faculty",
    )
    session.add(user)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Email is already registered.") from exc
    session.refresh(user)
    return user_to_schema(user)


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


@router.delete("/users/{user_id}")
def delete_user(
    user_id: str,
    actor: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> dict[str, str | bool]:
    """Admin-only hard delete. Prefer disable for normal offboarding."""
    from app.services.user_lifecycle import hard_delete_user

    if actor.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can delete users.")
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    if user.id == actor.id:
        raise HTTPException(status_code=400, detail="You cannot delete your own account.")
    if user.role == "admin":
        other_admins = (
            session.query(User)
            .filter(User.role == "admin", User.id != user.id, User.is_active.is_(True))
            .count()
        )
        if other_admins < 1:
            raise HTTPException(
                status_code=400,
                detail="Cannot delete the last active admin account.",
            )
    try:
        hard_delete_user(session, user)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail=(
                "Could not delete user because related records still reference them. "
                "Disable the account instead, or contact ICT."
            ),
        ) from exc
    return {"success": True, "deleted_user_id": user_id}
