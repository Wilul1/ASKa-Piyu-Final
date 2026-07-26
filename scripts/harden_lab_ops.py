"""Harden lab ops that do not need a public domain yet.

- Signup policy (campus email domains + invite code)
- Rotate admin / office seed passwords
- Write encrypted-backup passphrase
- Refresh deploy/BOOTSTRAP_CREDENTIALS.txt

Usage (from repo root):
    python scripts/harden_lab_ops.py
    python scripts/harden_lab_ops.py --apply-db

Does not expose lab HTTP publicly — that remains an operator choice.
"""

from __future__ import annotations

import argparse
import os
import re
import secrets
import string
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
PROD_ENV = BACKEND / ".env.production"
DEV_ENV = BACKEND / ".env"
ROOT_ENV = ROOT / ".env"
CRED_FILE = ROOT / "deploy" / "BOOTSTRAP_CREDENTIALS.txt"
BACKUP_PASS_FILE = ROOT / "deploy" / "BACKUP_PASSPHRASE.txt"

# Lab may use aska.local; campus students use lspu.edu.ph.
DEFAULT_SIGNUP_DOMAINS = "lspu.edu.ph,aska.local"


def _gen_password(length: int = 20) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#%*+-_=?"
    while True:
        value = "".join(secrets.choice(alphabet) for _ in range(length))
        if re.search(r"[A-Za-z]", value) and re.search(r"\d", value):
            return value


def _gen_invite() -> str:
    return "ASKA-" + secrets.token_urlsafe(12)


def _gen_backup_pass() -> str:
    return secrets.token_urlsafe(32)


def _read_env(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.is_file():
        return data
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        data[key.strip()] = value.strip()
    return data


def _write_env(path: Path, updates: dict[str, str], append_keys: list[str]) -> None:
    """Upsert keys in an env file; append missing keys at end."""
    if not path.is_file():
        lines = [f"{k}={updates[k]}" for k in append_keys if k in updates]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return

    original = path.read_text(encoding="utf-8").splitlines()
    seen: set[str] = set()
    out: list[str] = []
    for line in original:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                out.append(f"{key}={updates[key]}")
                seen.add(key)
                continue
        out.append(line)
    for key in append_keys:
        if key in updates and key not in seen:
            out.append(f"{key}={updates[key]}")
    path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")


def _upsert_block_note(path: Path) -> None:
    """Ensure a short lab-only warning exists once in the env file."""
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    marker = "# LAB ONLY — do not expose HTTP :8080 on the public internet"
    if marker in text:
        return
    path.write_text(marker + "\n" + text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Harden lab ops without a public domain.")
    parser.add_argument(
        "--apply-db",
        action="store_true",
        help="Reset admin + office passwords in the database using .env.production DB URL.",
    )
    parser.add_argument(
        "--signup-domains",
        default=DEFAULT_SIGNUP_DOMAINS,
        help=f"Comma-separated email domains (default: {DEFAULT_SIGNUP_DOMAINS})",
    )
    args = parser.parse_args()

    if not PROD_ENV.is_file():
        print(
            f"ERROR: {PROD_ENV} missing. Run scripts/bootstrap_campus_deploy.py first.",
            file=sys.stderr,
        )
        return 1

    admin_password = _gen_password()
    office_password = _gen_password()
    invite_code = _gen_invite()
    backup_passphrase = _gen_backup_pass()
    signup_domains = (args.signup_domains or DEFAULT_SIGNUP_DOMAINS).strip()

    updates = {
        "ASKA_ALLOW_PUBLIC_SIGNUP": "true",
        "ASKA_SIGNUP_ALLOWED_EMAIL_DOMAINS": signup_domains,
        "ASKA_SIGNUP_INVITE_CODE": invite_code,
        "ASKA_SEED_ADMIN_PASSWORD": admin_password,
        "ASKA_SEED_OFFICE_PASSWORD": office_password,
        "ASKA_BACKUP_PASSPHRASE": backup_passphrase,
    }
    key_order = [
        "ASKA_ALLOW_PUBLIC_SIGNUP",
        "ASKA_SIGNUP_ALLOWED_EMAIL_DOMAINS",
        "ASKA_SIGNUP_INVITE_CODE",
        "ASKA_SEED_ADMIN_PASSWORD",
        "ASKA_SEED_OFFICE_PASSWORD",
        "ASKA_BACKUP_PASSPHRASE",
    ]

    _write_env(PROD_ENV, updates, key_order)
    _upsert_block_note(PROD_ENV)
    print(f"Updated {PROD_ENV}")

    # Mirror signup policy into daily-dev .env so local uvicorn enforces it.
    if DEV_ENV.is_file():
        dev_updates = {
            "ASKA_ALLOW_PUBLIC_SIGNUP": "true",
            "ASKA_SIGNUP_ALLOWED_EMAIL_DOMAINS": signup_domains,
            "ASKA_SIGNUP_INVITE_CODE": invite_code,
        }
        _write_env(
            DEV_ENV,
            dev_updates,
            [
                "ASKA_ALLOW_PUBLIC_SIGNUP",
                "ASKA_SIGNUP_ALLOWED_EMAIL_DOMAINS",
                "ASKA_SIGNUP_INVITE_CODE",
            ],
        )
        _upsert_block_note(DEV_ENV)
        print(f"Updated signup policy in {DEV_ENV}")

    prod = _read_env(PROD_ENV)
    root = _read_env(ROOT_ENV)
    admin_email = prod.get("ASKA_SEED_ADMIN_EMAIL", "admin@aska.local")
    postgres_password = root.get("POSTGRES_PASSWORD", "(see root .env)")
    public_origin = "https://aska.local"
    cors = prod.get("ASKA_CORS_ORIGINS", "")
    if "https://" in cors:
        # Keep first https origin if present.
        match = re.search(r"https://[^\"'\],\s]+", cors)
        if match:
            public_origin = match.group(0)

    CRED_FILE.parent.mkdir(parents=True, exist_ok=True)
    CRED_FILE.write_text(
        "\n".join(
            [
                f"ASKa-Piyu bootstrap credentials — KEEP PRIVATE — {datetime.now(timezone.utc).isoformat()}",
                f"Public origin: {public_origin}",
                "",
                "WARNING: Lab / laptop only. Do NOT publish docker-compose HTTP :8080",
                "to the campus or public internet. Use HTTPS overlay on a real VPS.",
                "",
                "Admin login:",
                f"  email:    {admin_email}",
                f"  password: {admin_password}",
                "",
                "Office logins (examples): registrar@aska.local, ict@aska.local, osas@aska.local",
                f"  password: {office_password}",
                "",
                "Student signup policy:",
                f"  domains:     {signup_domains}",
                f"  invite code: {invite_code}",
                "  (students need campus email + this invite code)",
                "",
                "Docker Postgres (root .env):",
                f"  POSTGRES_PASSWORD={postgres_password}",
                "",
                "Backup encryption passphrase:",
                f"  ASKA_BACKUP_PASSPHRASE={backup_passphrase}",
                "  (also in deploy/BACKUP_PASSPHRASE.txt — gitignored)",
                "",
                "On the campus VPS, replace aska.local with your real hostname + Lets Encrypt,",
                "update ASKA_CORS_ORIGINS and api_base.url, then compose with the https overlay.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(f"Wrote {CRED_FILE}")

    BACKUP_PASS_FILE.write_text(
        "\n".join(
            [
                "# ASKa-Piyu backup encryption passphrase — KEEP PRIVATE",
                "# Used by scripts/backup_aska.sh and backup_aska.bat when set as",
                "# ASKA_BACKUP_PASSPHRASE (or sourced from this file by the scripts).",
                backup_passphrase,
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(f"Wrote {BACKUP_PASS_FILE}")

    if args.apply_db:
        db_url = prod.get("ASKA_DATABASE_URL", "").strip()
        if not db_url:
            print("ERROR: ASKA_DATABASE_URL missing in .env.production", file=sys.stderr)
            return 1
        env = os.environ.copy()
        env["ASKA_DATABASE_URL"] = db_url
        env["ASKA_ENV"] = prod.get("ASKA_ENV", "production")
        env["ASKA_AUTH_SECRET_KEY"] = prod.get("ASKA_AUTH_SECRET_KEY", "")
        env["ASKA_SEED_ADMIN_EMAIL"] = admin_email
        env["ASKA_SEED_ADMIN_PASSWORD"] = admin_password
        env["ASKA_SEED_OFFICE_PASSWORD"] = office_password
        env["ASKA_DATABASE_INIT_ON_STARTUP"] = "false"
        # Ensure `import app` works when scripts/ is the entrypoint.
        env["PYTHONPATH"] = str(BACKEND) + (
            os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
        )

        print("Applying admin password reset...")
        r1 = subprocess.run(
            [
                sys.executable,
                "scripts/seed_admin.py",
                "--force-reset-password",
                "--email",
                admin_email,
                "--password",
                admin_password,
            ],
            cwd=str(BACKEND),
            env=env,
            check=False,
        )
        if r1.returncode != 0:
            print("WARNING: seed_admin failed — is Postgres running?", file=sys.stderr)

        print("Applying office password reset...")
        r2 = subprocess.run(
            [sys.executable, "scripts/seed_office_accounts.py", "--force-reset-password"],
            cwd=str(BACKEND),
            env=env,
            check=False,
        )
        if r2.returncode != 0:
            print("WARNING: seed_office_accounts failed — is Postgres running?", file=sys.stderr)
        if r1.returncode == 0 and r2.returncode == 0:
            print("Database passwords rotated.")
        else:
            print("Env/files updated; re-run with Postgres up: python scripts/harden_lab_ops.py --apply-db")
    else:
        print("Skipped DB apply (pass --apply-db when Postgres is running).")

    print()
    print("Done. Read deploy/BOOTSTRAP_CREDENTIALS.txt for new passwords + invite code.")
    print("Lab rule: keep compose HTTP :8080 on this PC only — never public.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
