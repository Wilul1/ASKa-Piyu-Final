"""Authentication routes backed by PostgreSQL application data."""

from __future__ import annotations

import hmac
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.db.session import get_db_session
from app.models.db_models import Office, User, utc_now
from app.models.schemas import (
    AdminResetPasswordRequest,
    AdminSetUserActiveRequest,
    AuthEventListResponse,
    AuthEventSchema,
    AuthResponse,
    AbuseFlagListResponse,
    AbuseFlagSchema,
    AbuseRelatedUserSchema,
    ChangePasswordRequest,
    CreateFacultyAccountRequest,
    CreateOfficeAccountRequest,
    LoginRequest,
    ResendVerificationResponse,
    SignupRequest,
    UserListResponse,
    UserSchema,
    VerifyEmailRequest,
)
from app.services.auth import create_access_token, get_current_user
from app.services.auth_abuse import (
    EVENT_LOGIN_FAIL,
    EVENT_LOGIN_OK,
    EVENT_SIGNUP,
    auth_event_to_dict,
    list_abuse_flags,
    list_auth_events,
    record_auth_event,
)
from app.services.auth_rate_limit import (
    LOGIN_LIMIT,
    SIGNUP_LIMIT,
    check_auth_rate_limit,
)
from app.services.client_ip import client_ip
from app.services.email_service import (
    generate_verification_code,
    hash_verification_code,
    send_verification_email,
    verification_expiry,
)
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
        is_active=bool(getattr(user, "is_active", True)),
        email_verified=bool(getattr(user, "email_verified", True)),
        created_at=_datetime_to_iso(user.created_at),
        updated_at=_datetime_to_iso(user.updated_at),
    )


def _maybe_send_verification_on_login(session: Session, user: User) -> None:
    """Issue + send a code when an unverified student/faculty logs in.

    Respects the resend cooldown so a signup-then-immediate-login does not
    double-send. Failures are logged; login still succeeds.
    """
    role = (user.role or "").strip().lower()
    if role not in ("student", "faculty"):
        return
    if bool(getattr(user, "email_verified", False)):
        return

    sent_at = getattr(user, "email_verification_sent_at", None)
    cooldown = int(getattr(settings, "email_verification_resend_cooldown_seconds", 60) or 60)
    if sent_at is not None:
        age = (utc_now() - _as_utc(sent_at)).total_seconds()
        if age < cooldown:
            return

    code = _issue_verification_code(user)
    session.add(user)
    session.commit()
    sent = send_verification_email(
        to_email=user.email,
        full_name=user.full_name,
        code=code,
    )
    if not sent:
        logger.warning(
            "Login succeeded but verification email was not sent for %s",
            user.email,
        )


def _issue_verification_code(user: User) -> str:
    """Generate + persist a fresh code on the given (already-attached) user.

    Caller is responsible for committing.
    """
    code = generate_verification_code()
    user.email_verification_code_hash = hash_verification_code(code)
    user.email_verification_expires_at = verification_expiry()
    user.email_verification_sent_at = utc_now()
    return code


def _bump_credentials(user: User) -> None:
    user.credentials_version = int(getattr(user, "credentials_version", 0) or 0) + 1


def _datetime_to_iso(value: datetime) -> str:
    return value.isoformat()


def _as_utc(value: datetime) -> datetime:
    """Normalize SQLite-naive and Postgres-aware timestamps for comparison."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _signup_email_domain_allowed(email: str) -> bool:
    raw = (getattr(settings, "signup_allowed_email_domains", None) or "").strip()
    if not raw:
        return True
    domain = email.rsplit("@", 1)[-1].strip().lower()
    allowed = {
        part.strip().lower().lstrip("@")
        for part in raw.split(",")
        if part.strip()
    }
    return domain in allowed


def _signup_invite_ok(provided: str | None) -> bool:
    expected = (getattr(settings, "signup_invite_code", None) or "").strip()
    if not expected:
        return True
    got = (provided or "").strip()
    if not got:
        return False
    # compare_digest requires equal length; hash both sides to avoid 500s.
    expected_digest = hmac.new(b"aska-invite", expected.encode("utf-8"), "sha256").digest()
    got_digest = hmac.new(b"aska-invite", got.encode("utf-8"), "sha256").digest()
    return hmac.compare_digest(got_digest, expected_digest)


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

    if not bool(getattr(settings, "allow_public_signup", True)):
        raise HTTPException(
            status_code=403,
            detail="Public signup is disabled. Contact your campus administrator.",
        )

    if payload.role != "student":
        raise HTTPException(
            status_code=403,
            detail="Public signup can create student accounts only.",
        )

    if not _signup_invite_ok(payload.invite_code):
        raise HTTPException(
            status_code=403,
            detail="A valid campus invite code is required to sign up.",
        )

    if not _signup_email_domain_allowed(payload.email):
        raise HTTPException(
            status_code=403,
            detail="Use your campus email address to create an account.",
        )

    existing_user = session.query(User).filter(User.email == payload.email).first()
    if existing_user is not None:
        # Same wording as IntegrityError path — avoid precise email enumeration.
        raise HTTPException(
            status_code=409,
            detail="Unable to create an account with that email.",
        )

    # Students must verify email (6-digit code) before tickets work.
    # Ask + public Knowledge Base stay usable without verification.
    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name,
        role="student",
        email_verified=False,
    )
    code = _issue_verification_code(user)
    session.add(user)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Unable to create an account with that email.",
        ) from exc
    session.refresh(user)

    record_auth_event(
        session,
        event_type=EVENT_SIGNUP,
        ip_address=client,
        email=user.email,
        user_id=user.id,
        user_agent=request.headers.get("user-agent"),
    )

    sent = send_verification_email(
        to_email=user.email,
        full_name=user.full_name,
        code=code,
    )
    if not sent:
        logger.warning(
            "Signup succeeded but verification email was not sent for %s",
            user.email,
        )

    return AuthResponse(access_token=create_access_token(user), user=user_to_schema(user))


@router.post("/login", response_model=AuthResponse)
def login(
    payload: LoginRequest,
    request: Request,
    session: Session = Depends(get_db_session),
) -> AuthResponse:
    client = client_ip(request)
    ua = request.headers.get("user-agent")
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
        record_auth_event(
            session,
            event_type=EVENT_LOGIN_FAIL,
            ip_address=client,
            email=payload.email,
            user_id=user.id if user is not None else None,
            user_agent=ua,
        )
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    if not bool(getattr(user, "is_active", True)):
        raise HTTPException(status_code=403, detail="Account is disabled.")

    record_auth_event(
        session,
        event_type=EVENT_LOGIN_OK,
        ip_address=client,
        email=user.email,
        user_id=user.id,
        user_agent=ua,
    )

    # Login of an unverified student should still get a code (signup send can
    # fail, or the account was created before sending was live).
    _maybe_send_verification_on_login(session, user)

    return AuthResponse(
        access_token=create_access_token(user, remember_me=payload.remember_me),
        user=user_to_schema(user),
    )


@router.get("/me", response_model=UserSchema)
def me(current_user: User = Depends(get_current_user)) -> UserSchema:
    return user_to_schema(current_user)


@router.post("/verify-email", response_model=AuthResponse)
def verify_email(
    payload: VerifyEmailRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> AuthResponse:
    """Confirm the 6-digit code emailed at signup. Issues a fresh token."""
    user = session.get(User, current_user.id)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid authentication token.")
    if bool(getattr(user, "email_verified", False)):
        return AuthResponse(access_token=create_access_token(user), user=user_to_schema(user))

    code = (payload.code or "").strip()
    expected_hash = getattr(user, "email_verification_code_hash", None)
    expires_at = getattr(user, "email_verification_expires_at", None)
    if not expected_hash or not expires_at:
        raise HTTPException(
            status_code=400,
            detail="No verification code is pending. Request a new code.",
        )
    if utc_now() > _as_utc(expires_at):
        raise HTTPException(
            status_code=400,
            detail="That verification code has expired. Request a new code.",
        )
    if not hmac.compare_digest(hash_verification_code(code), expected_hash):
        raise HTTPException(status_code=400, detail="Invalid verification code.")

    user.email_verified = True
    user.email_verification_code_hash = None
    user.email_verification_expires_at = None
    session.add(user)
    session.commit()
    session.refresh(user)
    return AuthResponse(access_token=create_access_token(user), user=user_to_schema(user))


@router.post("/resend-verification", response_model=ResendVerificationResponse)
def resend_verification(
    request: Request,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> ResendVerificationResponse:
    """Send a fresh verification code (rate-limited + cooldown)."""
    client = client_ip(request)
    if not check_auth_rate_limit(f"resend-verify:ip:{client}", limit=SIGNUP_LIMIT):
        raise HTTPException(
            status_code=429,
            detail="Too many resend attempts. Please wait a moment and try again.",
        )

    user = session.get(User, current_user.id)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid authentication token.")
    if bool(getattr(user, "email_verified", False)):
        return ResendVerificationResponse(
            sent=False,
            message="Your email is already verified.",
        )

    sent_at = getattr(user, "email_verification_sent_at", None)
    cooldown = int(getattr(settings, "email_verification_resend_cooldown_seconds", 60) or 60)
    if sent_at is not None:
        age = (utc_now() - _as_utc(sent_at)).total_seconds()
        if age < cooldown:
            wait = max(1, int(cooldown - age))
            raise HTTPException(
                status_code=429,
                detail=f"Please wait {wait} seconds before requesting another code.",
            )

    code = _issue_verification_code(user)
    session.add(user)
    session.commit()
    ok = send_verification_email(to_email=user.email, full_name=user.full_name, code=code)
    if not ok:
        return ResendVerificationResponse(
            sent=False,
            message="Could not send the verification email right now. Please try again shortly.",
        )
    return ResendVerificationResponse(
        sent=True,
        message="A new verification code was sent to your email.",
    )


@router.post("/logout", status_code=204)
def logout(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> None:
    """Revoke the current bearer token (and any other JWTs for this credentials version)."""
    user = session.get(User, current_user.id)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid authentication token.")
    _bump_credentials(user)
    session.add(user)
    session.commit()


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
    """Admin: list all users. Office: list staff + faculty for their office."""
    query = session.query(User).order_by(User.created_at.desc())

    if actor.role == "admin":
        if role is not None:
            normalized = role.strip().lower()
            if normalized not in {"student", "faculty", "office", "admin"}:
                raise HTTPException(
                    status_code=422,
                    detail="role must be student, faculty, office, or admin.",
                )
            query = query.filter(User.role == normalized)
    elif actor.role == "office":
        if not actor.office_id:
            raise HTTPException(
                status_code=422,
                detail="Your office account is not assigned to an office.",
            )
        query = query.filter(User.office_id == actor.office_id)
        if role is not None:
            normalized = role.strip().lower()
            if normalized not in {"faculty", "office"}:
                raise HTTPException(
                    status_code=422,
                    detail="Office accounts may list faculty or office roles only.",
                )
            query = query.filter(User.role == normalized)
        else:
            query = query.filter(User.role.in_(("faculty", "office")))
    else:
        raise HTTPException(status_code=403, detail="Not allowed to list users.")

    users = query.all()
    return UserListResponse(
        items=[user_to_schema(user) for user in users],
        total=len(users),
    )


@router.get("/abuse/flags", response_model=AbuseFlagListResponse)
def get_abuse_flags(
    actor: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> AbuseFlagListResponse:
    if actor.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can view abuse flags.")
    raw = list_abuse_flags(session)
    items = [
        AbuseFlagSchema(
            kind=item["kind"],
            ip_address=item["ip_address"],
            count=item["count"],
            window_hours=item["window_hours"],
            reason=item["reason"],
            latest_at=item["latest_at"],
            event_type=item["event_type"],
            related_users=[
                AbuseRelatedUserSchema(**user) for user in item.get("related_users") or []
            ],
        )
        for item in raw
    ]
    return AbuseFlagListResponse(items=items, total=len(items))


@router.get("/abuse/events", response_model=AuthEventListResponse)
def get_abuse_events(
    ip: str | None = None,
    limit: int = 50,
    actor: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> AuthEventListResponse:
    if actor.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can view auth events.")
    rows = list_auth_events(session, ip_address=ip, limit=limit)
    items = [AuthEventSchema(**auth_event_to_dict(row)) for row in rows]
    return AuthEventListResponse(items=items, total=len(items))


@router.post("/faculty-accounts", response_model=UserSchema)
def create_faculty_account(
    payload: CreateFacultyAccountRequest,
    actor: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> UserSchema:
    """Office staff create faculty logins for their own office (not admin)."""
    if actor.role != "office":
        raise HTTPException(
            status_code=403,
            detail="Only office accounts can create faculty logins for their office.",
        )
    if not actor.office_id:
        raise HTTPException(
            status_code=422,
            detail="Your office account is not assigned to an office.",
        )

    if session.query(User).filter(User.email == payload.email).first() is not None:
        raise HTTPException(status_code=409, detail="Email is already registered.")

    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name.strip(),
        role="faculty",
        office_id=actor.office_id,
        email_verified=True,
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
    """Admin: create office staff for any office. Office: create staff for own office."""
    if actor.role not in {"admin", "office"}:
        raise HTTPException(
            status_code=403,
            detail="Only admins or office accounts can create office staff logins.",
        )

    if session.query(User).filter(User.email == payload.email).first() is not None:
        raise HTTPException(status_code=409, detail="Email is already registered.")

    office: Office | None = None
    if actor.role == "office":
        if not actor.office_id:
            raise HTTPException(
                status_code=422,
                detail="Your office account is not assigned to an office.",
            )
        # Always bind new staff to the creator's office (ignore client office fields).
        office = session.get(Office, actor.office_id)
        if office is None:
            raise HTTPException(status_code=422, detail="Office was not found.")
    elif payload.office_id:
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
        email_verified=True,
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
    from app.services.user_lifecycle import hard_delete_user, remove_attachment_files

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
        attachment_paths = hard_delete_user(session, user)
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
    remove_attachment_files(attachment_paths)
    return {"success": True, "deleted_user_id": user_id}
