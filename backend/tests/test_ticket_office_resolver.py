"""Office label resolution for ticket routing (taxonomy → Postgres offices)."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import initialize_database
from app.models.db_models import Office
from app.services.ticket_office_resolver import resolve_office_for_ticket
from app.services.ticketing import triage_ticket


def _session_with_offices(*names: str):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    initialize_database(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = Session()
    for name in names:
        session.add(Office(name=name))
    session.commit()
    return session


def test_resolve_ict_office_label_to_seeded_ict_office():
    session = _session_with_offices(
        "Accounting Unit",
        "ICT Office",
        "Office of Student Affairs",
    )
    try:
        office_id, office_name = resolve_office_for_ticket(session, "ICT Office")
        assert office_name == "ICT Office"
        assert office_id
    finally:
        session.close()


def test_resolve_ict_office_label_to_production_icts_name():
    """Production seeds ICTS under the campus full name, not 'ICT Office'."""
    session = _session_with_offices(
        "Accounting Unit",
        "Information and Communications Technology Services (ICTS)",
        "Office of Student Affairs (OSA)",
        "Registrar's Office",
    )
    try:
        office_id, office_name = resolve_office_for_ticket(session, "ICT Office")
        assert "ICTS" in office_name or "Communications Technology" in office_name
        assert office_name != "Accounting Unit"
        assert office_id
    finally:
        session.close()


def test_resolve_accounting_office_label_to_accounting_unit():
    session = _session_with_offices(
        "Accounting Unit",
        "Information and Communications Technology Services (ICTS)",
        "Office of Student Affairs (OSA)",
    )
    try:
        _, office_name = resolve_office_for_ticket(session, "Accounting Office")
        assert office_name == "Accounting Unit"
    finally:
        session.close()


def test_portal_login_triage_routes_to_icts_not_accounting():
    session = _session_with_offices(
        "Accounting Unit",
        "Information and Communications Technology Services (ICTS)",
        "Office of Student Affairs (OSA)",
        "Registrar's Office",
    )
    try:
        cases = (
            ("I cannot log in to the student portal", True),
            ("My portal account is not working", False),
            ("University system login problem", False),
        )
        for subject, expect_high in cases:
            result = triage_ticket(
                subject,
                "Need access restored for class enrollment.",
                session=session,
            )
            if expect_high:
                assert result["priority"] == "High", subject
            assert "Accounting" not in result["assigned_office"], result
            assert (
                "ICT" in result["assigned_office"]
                or "Communications Technology" in result["assigned_office"]
            ), result
    finally:
        session.close()


def test_fee_refund_still_routes_to_accounting_unit():
    session = _session_with_offices(
        "Accounting Unit",
        "Cashier Unit",
        "Information and Communications Technology Services (ICTS)",
        "Office of Student Affairs (OSA)",
        "Registrar's Office",
    )
    try:
        result = triage_ticket(
            "I need a tuition fee refund for overpayment",
            "Paid twice for the same assessment this semester.",
            session=session,
        )
        assert result["assigned_office"] == "Accounting Unit"
        assert result["priority"] != "High"
    finally:
        session.close()


def test_payment_posting_routes_to_cashier_or_finance():
    session = _session_with_offices(
        "Accounting Unit",
        "Cashier Unit",
        "Information and Communications Technology Services (ICTS)",
        "Office of Student Affairs (OSA)",
    )
    try:
        result = triage_ticket(
            "My tuition payment was posted incorrectly",
            "OR number posted to the wrong assessment; billing needs correction.",
            session=session,
        )
        office = result["assigned_office"]
        assert "OSA" not in office and "Student Affairs" not in office, result
        assert "Cashier" in office or "Accounting" in office, result
    finally:
        session.close()


def test_miscellaneous_billing_routes_to_finance_not_osa():
    """BUG-R3: generic fee/billing concerns must not fall to OSA."""
    from app.services.knowledge_taxonomy import load_taxonomy

    load_taxonomy.cache_clear()
    session = _session_with_offices(
        "Accounting Unit",
        "Cashier Unit",
        "Information and Communications Technology Services (ICTS)",
        "Office of Student Affairs (OSA)",
    )
    try:
        result = triage_ticket(
            "ASKA-REGRESSION I have a question about miscellaneous fee billing",
            "Fee/billing concern about an unexpected miscellaneous charge on my statement of account.",
            session=session,
        )
        office = result["assigned_office"]
        assert "OSA" not in office and "Student Affairs" not in office, result
        assert "Cashier" in office or "Accounting" in office, result
    finally:
        session.close()


def test_student_activity_still_routes_to_osa():
    session = _session_with_offices(
        "Accounting Unit",
        "Cashier Unit",
        "Information and Communications Technology Services (ICTS)",
        "Office of Student Affairs (OSA)",
    )
    try:
        result = triage_ticket(
            "I want to join a student organization campus activity",
            "Looking for accredited student organization activity guidelines this semester.",
            session=session,
        )
        assert "Student Affairs" in result["assigned_office"] or "OSA" in result["assigned_office"]
    finally:
        session.close()


def test_library_reference_routes_to_library_not_icts():
    """STRESS-06: library concerns map to the existing Library office, not ICTS."""
    from app.services.knowledge_taxonomy import classify_question, load_taxonomy

    load_taxonomy.cache_clear()
    # Clear QA-side vocab caches that embed taxonomy snapshots.
    from app.services.qa import question_answering as qa

    qa._service_vocab_sets.cache_clear()
    qa._service_alias_token_map.cache_clear()

    classified = classify_question(
        "I need library reference assistance for thesis research using library databases"
    )
    assert classified.office == "Library"
    assert "library" in classified.subcategory.casefold()

    session = _session_with_offices(
        "Library",
        "Information and Communications Technology Services (ICTS)",
        "Office of Student Affairs (OSA)",
        "Registrar's Office",
    )
    try:
        result = triage_ticket(
            "Library reference assistance for thesis research",
            "Need help using library databases and reference services on campus.",
            session=session,
        )
        assert result["assigned_office"] == "Library"
        assert "ICT" not in result["assigned_office"]
    finally:
        session.close()
