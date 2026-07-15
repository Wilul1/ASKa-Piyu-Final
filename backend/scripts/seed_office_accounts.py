"""Seed office staff logins for every office in PostgreSQL.

Run from the backend directory:
    python scripts/seed_office_accounts.py

Default password for all seeded office accounts: office123
"""

from __future__ import annotations

import re

from app.db.session import get_session_factory, initialize_database
from app.models.db_models import Office, User
from app.services.passwords import hash_password


DEFAULT_PASSWORD = "office123"

# Preferred emails for well-known offices (easy to remember for demos).
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


def _slug_email(office_name: str) -> str:
    preferred = PREFERRED_EMAILS.get(office_name)
    if preferred:
        return preferred
    slug = re.sub(r"[^a-z0-9]+", "-", office_name.lower()).strip("-")
    slug = slug[:48] or "office"
    return f"{slug}@aska.local"


def _ensure_office_user(session, office: Office, *, email: str, full_name: str | None = None) -> tuple[User, bool]:
    """Create or update an office staff user. Returns (user, created)."""
    user = session.query(User).filter(User.email == email).first()
    display_name = full_name or f"{office.name} Staff"
    if user is None:
        user = User(
            email=email,
            password_hash=hash_password(DEFAULT_PASSWORD),
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

            user, was_created = _ensure_office_user(session, office, email=email)
            label = f"{user.email} -> {office.name}"
            if was_created:
                created.append(label)
            else:
                updated.append(label)

        session.commit()
    finally:
        session.close()

    print(f"Default password for new office accounts: {DEFAULT_PASSWORD}")
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
