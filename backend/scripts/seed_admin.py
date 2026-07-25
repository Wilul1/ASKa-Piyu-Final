"""Create the first admin account (bootstrap).

Run from the backend directory:
    python scripts/seed_admin.py

Required env (or prompts via args):
  ASKA_SEED_ADMIN_EMAIL
  ASKA_SEED_ADMIN_PASSWORD  (min 10 chars, letter + digit)

Optional:
  ASKA_SEED_ADMIN_NAME=ASKa Admin
"""

from __future__ import annotations

import argparse
import os
import re
import sys

from app.config import settings
from app.db.session import get_session_factory, initialize_database
from app.models.db_models import User
from app.services.passwords import hash_password


def _validate_password(password: str) -> None:
    if len(password) < 10:
        raise SystemExit("ERROR: Admin password must be at least 10 characters.")
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise SystemExit("ERROR: Admin password must include a letter and a digit.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap the first ASKa-Piyu admin user.")
    parser.add_argument("--email", default=(os.getenv("ASKA_SEED_ADMIN_EMAIL") or "").strip())
    parser.add_argument("--password", default=(os.getenv("ASKA_SEED_ADMIN_PASSWORD") or "").strip())
    parser.add_argument(
        "--name",
        default=(os.getenv("ASKA_SEED_ADMIN_NAME") or "ASKa Admin").strip() or "ASKa Admin",
    )
    parser.add_argument(
        "--force-reset-password",
        action="store_true",
        help="If the admin email already exists, reset its password and role=admin.",
    )
    args = parser.parse_args()

    email = args.email.strip().lower()
    password = args.password
    if not email or "@" not in email:
        raise SystemExit(
            "ERROR: Set ASKA_SEED_ADMIN_EMAIL or pass --email (e.g. admin@aska.local)."
        )
    if not password:
        raise SystemExit(
            "ERROR: Set ASKA_SEED_ADMIN_PASSWORD or pass --password."
        )
    _validate_password(password)

    if settings.env == "production" and password.lower() in {
        "admin123",
        "password",
        "changeme",
        "change-this",
    }:
        raise SystemExit("ERROR: Refusing weak admin password in production.")

    if settings.database_init_on_startup or settings.env != "production":
        initialize_database()

    session = get_session_factory()()
    try:
        existing = session.query(User).filter(User.email == email).first()
        if existing is not None:
            if existing.role == "admin" and not args.force_reset_password:
                print(f"Admin already exists: {email} (id={existing.id})")
                print("Use --force-reset-password to rotate the password.")
                return
            if not args.force_reset_password and existing.role != "admin":
                raise SystemExit(
                    f"ERROR: {email} exists with role={existing.role}. "
                    "Pass --force-reset-password to promote to admin."
                )
            existing.role = "admin"
            existing.password_hash = hash_password(password)
            existing.full_name = args.name
            if hasattr(existing, "is_active"):
                existing.is_active = True
            if hasattr(existing, "credentials_version"):
                existing.credentials_version = int(existing.credentials_version or 0) + 1
            session.commit()
            print(f"Updated admin: {email}")
            return

        user = User(
            email=email,
            password_hash=hash_password(password),
            full_name=args.name,
            role="admin",
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        print(f"Created admin: {email} (id={user.id})")
    finally:
        session.close()


if __name__ == "__main__":
    main()
