"""Seed development office accounts for local ASKa-Piyu testing.

Run from the backend directory:
    python scripts/seed_office_accounts.py
"""

from __future__ import annotations

from app.db.session import get_session_factory, initialize_database
from app.models.db_models import Office, User
from app.services.passwords import hash_password


OFFICE_SEEDS = [
    {
        "office_name": "ICT Office",
        "email": "ict@aska.local",
        "password": "office123",
        "full_name": "ICT Staff",
    },
    {
        "office_name": "Registrar",
        "email": "registrar@aska.local",
        "password": "office123",
        "full_name": "Registrar Staff",
    },
    {
        "office_name": "Office of Student Affairs",
        "email": "osas@aska.local",
        "password": "office123",
        "full_name": "OSAS Staff",
    },
]


def main() -> None:
    initialize_database()
    session_factory = get_session_factory()
    session = session_factory()
    try:
        for seed in OFFICE_SEEDS:
            office = session.query(Office).filter(Office.name == seed["office_name"]).first()
            if office is None:
                office = Office(name=seed["office_name"])
                session.add(office)
                session.flush()

            user = session.query(User).filter(User.email == seed["email"]).first()
            if user is None:
                user = User(
                    email=seed["email"],
                    password_hash=hash_password(seed["password"]),
                    full_name=seed["full_name"],
                    role="office",
                    office_id=office.id,
                )
                session.add(user)
            else:
                user.full_name = seed["full_name"]
                user.role = "office"
                user.office_id = office.id

        session.commit()
    finally:
        session.close()

    print("Seeded development office accounts: ict@aska.local, registrar@aska.local, osas@aska.local")


if __name__ == "__main__":
    main()
