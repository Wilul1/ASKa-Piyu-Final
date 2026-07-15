"""Resolve taxonomy / alias office labels to PostgreSQL ``offices.id``."""

from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.models.db_models import Office
from app.services.office_matcher import match_office_from_text


def _normalize(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def resolve_office_for_ticket(session: Session, office_label: str) -> tuple[str, str]:
    """Return ``(office_id, office_name)`` for smart routing / reassignment.

    Resolution order:
    1. Exact office name match (case/whitespace insensitive)
    2. Alias matcher on the label text
    3. Substring match against known offices
    4. Default to Office of Student Affairs when present
    """
    label = (office_label or "").strip()
    if not label:
        return _default_office(session)

    normalized = _normalize(label)
    offices = session.query(Office).order_by(Office.name).all()
    if not offices:
        raise LookupError("No offices are configured. Seed offices before creating tickets.")

    for office in offices:
        if _normalize(office.name) == normalized:
            return office.id, office.name

    match = match_office_from_text(label, session)
    if match is not None:
        return match.office_id, match.office_name

    for office in offices:
        office_norm = _normalize(office.name)
        if normalized in office_norm or office_norm in normalized:
            return office.id, office.name

    # Common taxonomy shorthand → seeded office names.
    aliases = {
        "student affairs and services": "office of student affairs",
        "osas": "office of student affairs",
        "ict": "ict office",
        "technical support": "ict office",
    }
    mapped = aliases.get(normalized)
    if mapped:
        for office in offices:
            if _normalize(office.name) == mapped:
                return office.id, office.name

    return _default_office(session)


def _default_office(session: Session) -> tuple[str, str]:
    preferred_names = (
        "Office of Student Affairs",
        "Office of the Student Affairs",
        "Student Affairs and Services",
    )
    offices = session.query(Office).order_by(Office.name).all()
    for name in preferred_names:
        for office in offices:
            if _normalize(office.name) == _normalize(name):
                return office.id, office.name
    if offices:
        return offices[0].id, offices[0].name
    raise LookupError("No offices are configured. Seed offices before creating tickets.")
