"""Resolve taxonomy / alias office labels to PostgreSQL ``offices.id``."""

from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.models.db_models import Office
from app.services.office_matcher import match_office_from_text


class UnresolvedOfficeLabelError(LookupError):
    """A specific (non-default) taxonomy office label has no seeded Office row.

    Raised only when ``resolve_office_for_ticket`` is called with
    ``allow_default_fallback=False`` and none of the resolution tiers
    (exact match / alias matcher / substring / taxonomy alias table) found a
    match. Distinguishes "this specific office isn't seeded yet" from the
    deliberate Office-of-Student-Affairs default used for genuinely
    unclassified/general tickets, so callers never have to silently treat a
    missing office as if OSA had been the intended target.
    """

    def __init__(self, label: str) -> None:
        self.label = label
        super().__init__(f"No seeded office matches the taxonomy label {label!r}.")


def _normalize(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


# Taxonomy / shorthand labels → candidate office-name needles (exact or substring).
# Production may seed "ICT Office" *or* "Information and Communications Technology
# Services (ICTS)"; both must resolve from taxonomy label "ICT Office".
_TAXONOMY_OFFICE_CANDIDATES: dict[str, tuple[str, ...]] = {
    "student affairs and services": (
        "office of student affairs",
        "office of the student affairs",
        "student affairs and services",
        "office of student affairs (osa)",
    ),
    "osas": (
        "office of student affairs",
        "office of the student affairs",
        "office of student affairs (osa)",
    ),
    "ict": (
        "ict office",
        "icts",
        "information and communications technology services",
        "information and communications technology",
    ),
    "ict office": (
        "ict office",
        "icts",
        "information and communications technology services",
        "information and communications technology",
    ),
    "technical support": (
        "ict office",
        "icts",
        "information and communications technology services",
        "information and communications technology",
    ),
    "accounting office": (
        "accounting unit",
        "accounting office",
        "accounting",
    ),
    "accounting": (
        "accounting unit",
        "accounting office",
        "accounting",
    ),
    "cashier office": (
        "cashier unit",
        "cashier office",
        "cashier",
    ),
    "cashier": (
        "cashier unit",
        "cashier office",
        "cashier",
    ),
    # Confirmed production naming mismatch: the taxonomy's "Office of the
    # President" label must resolve to the campus's actual seeded office,
    # "Office of the University President (OUP)".
    "office of the president": (
        "office of the university president (oup)",
        "office of the university president",
    ),
    # Substring matching fails here because extra words sit *between* the
    # shared tokens: "scholarship office" is not a substring of
    # "scholarship and financial assistance office", and the reverse is
    # not a substring either. office_aliases.Scholarship also misses:
    # match_office_from_text scores short taxonomy labels below its
    # confidence floor.
    "scholarship office": (
        "scholarship and financial assistance office",
        "scholarship office",
        "scholarships and financial assistance",
    ),
    "scholarships": (
        "scholarship and financial assistance office",
        "scholarships and financial assistance",
    ),
    # Same trap: "admissions office" vs "admission and testing services".
    "admissions office": (
        "admission and testing services",
        "admissions office",
        "office of admissions",
        "admission office",
    ),
    "admission office": (
        "admission and testing services",
        "admissions office",
        "office of admissions",
        "admission office",
    ),
}


def find_explicit_office_in_ticket_text(session: Session, text: str) -> tuple[str, str] | None:
    """Return ``(office_id, office_name)`` when the ticket clearly names one office.

    Prefer alias matches, then longest whole-phrase office-name matches. Ambiguous
    multi-office mentions return ``None`` so taxonomy can decide instead of guessing.
    """
    haystack = _normalize(text)
    if not haystack:
        return None

    alias_match = match_office_from_text(text, session)
    if alias_match is not None:
        return alias_match.office_id, alias_match.office_name

    offices = session.query(Office).order_by(Office.name).all()
    if not offices:
        return None

    matches: list[Office] = []
    for office in offices:
        name = _normalize(office.name)
        if len(name) < 4:
            continue
        bare = re.sub(r"\([^)]*\)", "", name).strip()
        candidates = [name]
        if bare and bare != name and len(bare) >= 4:
            candidates.append(bare)
        for candidate in candidates:
            pattern = r"\b" + r"\s+".join(re.escape(part) for part in candidate.split()) + r"\b"
            if re.search(pattern, haystack):
                matches.append(office)
                break

    if not matches:
        return None
    if len(matches) == 1:
        return matches[0].id, matches[0].name

    # Multiple offices named: keep only when one name clearly dominates by length
    # (e.g. "Cashier Unit" vs a shorter generic fragment). Otherwise abstain.
    ranked = sorted(matches, key=lambda item: len(_normalize(item.name)), reverse=True)
    best = ranked[0]
    second = ranked[1]
    if len(_normalize(best.name)) - len(_normalize(second.name)) >= 4:
        return best.id, best.name
    return None


def resolve_office_for_ticket(
    session: Session,
    office_label: str,
    *,
    allow_default_fallback: bool = True,
) -> tuple[str, str]:
    """Return ``(office_id, office_name)`` for smart routing / reassignment.

    Resolution order:
    1. Exact office name match (case/whitespace insensitive)
    2. Alias matcher on the label text
    3. Substring match against known offices
    4. Taxonomy shorthand → seeded / campus office names
    5. Default to Office of Student Affairs when present

    ``allow_default_fallback`` controls what happens when a non-empty label
    reaches tier 5 without matching anything (tiers 1-4 all missed):

    - ``True`` (default, and the behavior for every pre-existing caller):
      unchanged — silently fall back to the Office of Student Affairs
      default, exactly as before.
    - ``False``: raise :class:`UnresolvedOfficeLabelError` instead of
      defaulting. Intended for callers that already know ``office_label`` is
      a *specific* taxonomy classification (not the deliberate "General"
      fallback label) and want to distinguish "this office isn't seeded yet"
      from "OSA was genuinely the classification target" rather than
      silently conflating the two. An empty ``office_label`` still returns
      the default office either way (there is no specific target to fail to
      resolve).
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

    resolved = _resolve_taxonomy_alias(offices, normalized)
    if resolved is not None:
        return resolved.id, resolved.name

    if not allow_default_fallback:
        raise UnresolvedOfficeLabelError(label)

    return _default_office(session)


def _resolve_taxonomy_alias(offices: list[Office], normalized_label: str) -> Office | None:
    candidates = _TAXONOMY_OFFICE_CANDIDATES.get(normalized_label)
    if not candidates:
        return None

    # Exact name match first (keeps "ICT Office" fixtures working).
    for needle in candidates:
        for office in offices:
            if _normalize(office.name) == needle:
                return office

    # Then distinctive substring (e.g. "icts" inside the ICTS full name).
    for needle in candidates:
        if len(needle) < 3:
            continue
        for office in offices:
            office_norm = _normalize(office.name)
            if needle in office_norm:
                return office
    return None


def _default_office(session: Session) -> tuple[str, str]:
    preferred_names = (
        "Office of Student Affairs",
        "Office of the Student Affairs",
        "Student Affairs and Services",
        "Office of Student Affairs (OSA)",
    )
    offices = session.query(Office).order_by(Office.name).all()
    for name in preferred_names:
        for office in offices:
            if _normalize(office.name) == _normalize(name):
                return office.id, office.name
    # Prefer OSA substring before falling through to alphabetical offices[0]
    # (which is Accounting Unit in many campus seeds).
    for office in offices:
        if "student affairs" in _normalize(office.name):
            return office.id, office.name
    if offices:
        return offices[0].id, offices[0].name
    raise LookupError("No offices are configured. Seed offices before creating tickets.")


def backfill_unresolved_ticket_offices(session: Session) -> list[tuple[str, str, str]]:
    """Attach office ids to tickets whose taxonomy label now resolves.

    Only tickets with ``assigned_office_id IS NULL`` are considered. The OSA
    default fallback is never used, so labels that still have no seeded
    office stay in Needs Routing for admin review.

    Returns ``[(ticket_id, previous_label, resolved_office_name), ...]``.
    """
    from app.models.db_models import Ticket

    updated: list[tuple[str, str, str]] = []
    tickets = session.query(Ticket).filter(Ticket.assigned_office_id.is_(None)).all()
    for ticket in tickets:
        label = (ticket.assigned_office or "").strip()
        if not label:
            continue
        try:
            office_id, office_name = resolve_office_for_ticket(
                session, label, allow_default_fallback=False
            )
        except (UnresolvedOfficeLabelError, LookupError):
            continue
        previous = ticket.assigned_office
        ticket.assigned_office_id = office_id
        ticket.assigned_office = office_name
        updated.append((ticket.id, previous, office_name))
    return updated
