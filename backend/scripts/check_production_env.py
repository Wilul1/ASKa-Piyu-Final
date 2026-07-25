"""Fail if backend/.env is not ready for ASKA_ENV=production.

Run from the backend directory:
    python scripts/check_production_env.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from app.config import is_placeholder_secret, settings


def main() -> None:
    errors: list[str] = []
    env_file = Path(__file__).resolve().parents[1] / ".env"
    if not env_file.is_file():
        errors.append(f"Missing {env_file} — copy from .env.example and fill production values.")

    if settings.env != "production":
        errors.append(f"ASKA_ENV must be 'production' (got {settings.env!r}).")

    if not settings.database_url:
        errors.append("ASKA_DATABASE_URL is required.")
    if settings.database_init_on_startup:
        errors.append("ASKA_DATABASE_INIT_ON_STARTUP must be false in production.")

    if not settings.auth_secret_key or is_placeholder_secret(settings.auth_secret_key):
        errors.append("ASKA_AUTH_SECRET_KEY must be a strong non-placeholder secret.")

    from app.config import admin_api_key_auth_enabled

    if admin_api_key_auth_enabled():
        errors.append(
            "ASKA_ALLOW_ADMIN_API_KEY must be false in production "
            "(admin Bearer login only)."
        )

    origins = list(settings.cors_origins or [])
    if not origins or any(o.strip() == "*" for o in origins):
        errors.append("ASKA_CORS_ORIGINS must be explicit HTTPS origins (not '*').")
    non_local = [
        o
        for o in origins
        if o.strip()
        and "localhost" not in o.lower()
        and "127.0.0.1" not in o
    ]
    if origins and not non_local:
        errors.append("ASKA_CORS_ORIGINS must include a non-localhost production origin.")

    if not (settings.groq_api_key or "").strip():
        errors.append("ASKA_GROQ_API_KEY should be set for production LLM answers.")

    rebuild = (os.getenv("ASKA_KB_REBUILD_DOCUMENT_PATHS") or settings.kb_rebuild_document_paths or "").strip()
    if not rebuild:
        errors.append(
            "ASKA_KB_REBUILD_DOCUMENT_PATHS should be set before Chroma reset/rebuild."
        )

    if not (os.getenv("ASKA_SEED_OFFICE_PASSWORD") or "").strip():
        errors.append(
            "ASKA_SEED_OFFICE_PASSWORD should be set so you can run "
            "scripts/seed_office_accounts.py after migrate (tickets will not route "
            "without office rows/accounts)."
        )

    if errors:
        print("Production env check FAILED:", file=sys.stderr)
        for item in errors:
            print(f"  - {item}", file=sys.stderr)
        raise SystemExit(1)

    print("Production env check OK.")
    print(f"  env={settings.env}")
    print(f"  cors_origins={len(origins)}")
    print(f"  admin_api_key_auth={admin_api_key_auth_enabled()}")
    print("  Next: alembic upgrade head → seed_admin → seed_office_accounts → seed_office_aliases")


if __name__ == "__main__":
    main()
