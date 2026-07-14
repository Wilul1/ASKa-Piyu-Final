"""Seed office aliases for dynamic Article Planner office matching.

Aliases live in PostgreSQL so planner/grouping never hardcodes LSPU office names.
"""

from __future__ import annotations

from app.db.session import get_session_factory, initialize_database
from app.models.db_models import Office, OfficeAlias

# Development defaults only — runtime matching always loads from DB.
_SEED_ALIASES: dict[str, tuple[str | None, list[tuple[str, float]]]] = {
    "ICT Office": (
        "Technology Services",
        [
            ("ICT Office", 1.2),
            ("ICT", 1.0),
            ("Information and Communications Technology", 1.1),
        ],
    ),
    "Registrar": (
        "Student Records",
        [
            ("Registrar", 1.2),
            ("Office of the Registrar", 1.3),
            ("University Registrar", 1.1),
        ],
    ),
    "Office of Student Affairs": (
        "Student Services",
        [
            ("Office of Student Affairs", 1.3),
            ("Student Affairs", 1.1),
            ("OSAS", 1.0),
        ],
    ),
}


def seed_office_aliases() -> None:
    initialize_database()
    session = get_session_factory()()
    try:
        for office_name, (service_category, aliases) in _SEED_ALIASES.items():
            office = session.query(Office).filter(Office.name == office_name).first()
            if office is None:
                office = Office(name=office_name, service_category=service_category)
                session.add(office)
                session.flush()
            elif service_category and not office.service_category:
                office.service_category = service_category
            for alias, weight in aliases:
                existing = (
                    session.query(OfficeAlias)
                    .filter(OfficeAlias.office_id == office.id, OfficeAlias.alias == alias)
                    .first()
                )
                if existing is None:
                    session.add(
                        OfficeAlias(office_id=office.id, alias=alias, weight=weight, is_active=True)
                    )
                else:
                    existing.weight = weight
                    existing.is_active = True
        session.commit()
        print("Seeded office_aliases for: " + ", ".join(sorted(_SEED_ALIASES)))
    finally:
        session.close()


if __name__ == "__main__":
    seed_office_aliases()
