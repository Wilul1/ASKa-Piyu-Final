"""Seed office staff logins for every office in PostgreSQL.

Run from the backend directory:
    python scripts/seed_office_accounts.py
    python scripts/seed_office_accounts.py --force-reset-password

Password for newly created office accounts:
  - ASKA_SEED_OFFICE_PASSWORD env var if set
  - otherwise a local-dev default (never use that default in production)
"""

from __future__ import annotations

import argparse
import os
import re
import sys

from app.config import settings
from app.db.session import get_session_factory, initialize_database
from app.models.db_models import Office, User
from app.services.passwords import hash_password


_LOCAL_DEV_DEFAULT_PASSWORD = "office123"
PREFERRED_EMAILS = {
    "ICT Office": "ict@aska.local",
    "Registrar": "registrar@aska.local",
    "Office of Student Affairs": "osas@aska.local",
    "Admissions Office": "admissions@aska.local",
    "Admission and Testing Services": "admissions@aska.local",
    "Accounting Unit": "accounting@aska.local",
    "Cashier Unit": "cashier@aska.local",
    "Guidance Office": "guidance@aska.local",
    "Human Resource Management Office": "hr@aska.local",
    "Library": "library@aska.local",
}


def _seed_password() -> str:
    configured = (os.getenv("ASKA_SEED_OFFICE_PASSWORD") or "").strip()
    if configured:
        return configured
    if settings.env == "production":
        print(
            "ERROR: Refusing to seed office accounts in production with the local-dev "
            "default password. Set ASKA_SEED_OFFICE_PASSWORD to a strong unique value.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    print(
        "WARNING: Using local-dev default office password. "
        "Set ASKA_SEED_OFFICE_PASSWORD before any shared/campus deploy.",
        file=sys.stderr,
    )
    return _LOCAL_DEV_DEFAULT_PASSWORD


def _slug_email(office_name: str) -> str:
    preferred = PREFERRED_EMAILS.get(office_name)
    if preferred:
        return preferred
    slug = re.sub(r"[^a-z0-9]+", "-", office_name.lower()).strip("-")
    slug = slug[:48] or "office"
    return f"{slug}@aska.local"


def _ensure_office_user(
    session,
    office: Office,
    *,
    email: str,
    password: str,
    full_name: str | None = None,
    force_reset_password: bool = False,
) -> tuple[User, str]:
    """Create or update an office staff user. Returns (user, action)."""
    user = session.query(User).filter(User.email == email).first()
    display_name = full_name or f"{office.name} Staff"
    if user is None:
        user = User(
            email=email,
            password_hash=hash_password(password),
            full_name=display_name,
            role="office",
            office_id=office.id,
        )
        session.add(user)
        return user, "created"

    user.full_name = display_name
    user.role = "office"
    user.office_id = office.id
    if force_reset_password:
        user.password_hash = hash_password(password)
        if hasattr(user, "is_active"):
            user.is_active = True
        if hasattr(user, "credentials_version"):
            user.credentials_version = int(user.credentials_version or 0) + 1
        return user, "password_reset"
    # Keep existing password — do not reset on every seed run.
    return user, "present"


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed office staff accounts.")
    parser.add_argument(
        "--force-reset-password",
        action="store_true",
        help="Reset password for existing office accounts to ASKA_SEED_OFFICE_PASSWORD.",
    )
    args = parser.parse_args()

    password = _seed_password()
    initialize_database()
    session_factory = get_session_factory()
    session = session_factory()
    created: list[str] = []
    reset: list[str] = []
    present: list[str] = []
    try:
        # Ensure core offices exist even on a fresh DB.
        for office_name in (
            "ICT Office",
            "Registrar",
            "Office of Student Affairs",
        ):
            if session.query(Office).filter(Office.name == office_name).first() is None:
                session.add(Office(name=office_name))
        session.flush()

        offices = session.query(Office).order_by(Office.name.asc()).all()
        used_emails: set[str] = set()
        for office in offices:
            email = _slug_email(office.name)
            # Avoid collisions when two offices share a preferred email mapping.
            if email in used_emails:
                email = f"{re.sub(r'[^a-z0-9]+', '-', office.name.lower()).strip('-')[:40]}@aska.local"
            used_emails.add(email)

            user, action = _ensure_office_user(
                session,
                office,
                email=email,
                password=password,
                force_reset_password=args.force_reset_password,
            )
            label = f"{user.email} -> {office.name}"
            if action == "created":
                created.append(label)
            elif action == "password_reset":
                reset.append(label)
            else:
                present.append(label)

        session.commit()
    finally:
        session.close()

    print("Default password for new office accounts: (hidden — set via ASKA_SEED_OFFICE_PASSWORD)")
    if created:
        print(f"Created ({len(created)}):")
        for item in created:
            print(f"  + {item}")
    if reset:
        print(f"Password reset ({len(reset)}):")
        for item in reset:
            print(f"  * {item}")
    if present:
        print(f"Updated / already present ({len(present)}):")
        for item in present:
            print(f"  ~ {item}")
    if not created and not reset and not present:
        print("No offices found. Seed offices first (e.g. seed_office_aliases.py).")


if __name__ == "__main__":
    main()
