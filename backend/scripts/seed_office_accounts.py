"""Seed office staff logins for every office in PostgreSQL.

Run from the backend directory:
    python scripts/seed_office_accounts.py

Password for newly created office accounts:
  - ASKA_SEED_OFFICE_PASSWORD env var if set
  - otherwise a local-dev default (never use that default in production)
"""

from __future__ import annotations

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
) -> tuple[User, bool]:
    """Create or update an office staff user. Returns (user, created)."""
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
        return user, True

    user.full_name = display_name
    user.role = "office"
    user.office_id = office.id
    # Keep existing password — do not reset on every seed run.
    return user, False


def main() -> None:
    password = _seed_password()
    initialize_database()
    session_factory = get_session_factory()
    session = session_factory()
    created: list[str] = []
    updated: list[str] = []
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

            user, was_created = _ensure_office_user(
                session, office, email=email, password=password
            )
            label = f"{user.email} -> {office.name}"
            if was_created:
                created.append(label)
            else:
                updated.append(label)

        session.commit()
    finally:
        session.close()

    print("Default password for new office accounts: (hidden — set via ASKA_SEED_OFFICE_PASSWORD)")
    if created:
        print(f"Created ({len(created)}):")
        for item in created:
            print(f"  + {item}")
    if updated:
        print(f"Updated / already present ({len(updated)}):")
        for item in updated:
            print(f"  ~ {item}")
    if not created and not updated:
        print("No offices found. Seed offices first (e.g. seed_office_aliases.py).")


if __name__ == "__main__":
    main()
