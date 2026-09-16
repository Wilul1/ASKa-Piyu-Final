"""Office label resolution for ticket routing (taxonomy → Postgres offices)."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import initialize_database
from app.models.db_models import Office
from app.services.ticket_office_resolver import UnresolvedOfficeLabelError, resolve_office_for_ticket
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


# ---------------------------------------------------------------------------
# ASKA-PIYU MINIMAL TICKET ROUTING FIX -- FIX 2: taxonomy office resolution
#
# Production seeds 49 offices under names that don't always match the
# taxonomy's office labels verbatim. These tests use a realistic subset of
# actual production office names (not synthetic fixture names) to cover:
#   - the confirmed "Office of the President" -> OUP naming mismatch
#   - ICT / Registrar / Accounting / Cashier resolution staying unaffected
#   - the OSA fallback staying intact for genuinely General/unclassified tickets
#   - a specific unresolved taxonomy office being distinguishable from a
#     genuine OSA classification/default, instead of being silently treated
#     as though OSA were the intended office.
# ---------------------------------------------------------------------------

_PRODUCTION_OFFICE_NAMES = (
    "Office of the University President (OUP)",
    "Information and Communications Technology Services (ICTS)",
    "Registrar's Office",
    "Accounting Unit",
    "Cashier Unit",
    "Office of Student Affairs (OSA)",
)


def test_office_of_the_president_resolves_to_oup():
    """Confirmed mismatch: taxonomy 'Office of the President' -> production OUP."""
    session = _session_with_offices(*_PRODUCTION_OFFICE_NAMES)
    try:
        office_id, office_name = resolve_office_for_ticket(session, "Office of the President")
        assert office_name == "Office of the University President (OUP)"
        assert office_id
    finally:
        session.close()


def test_board_of_regents_question_triages_to_oup_end_to_end():
    """End-to-end through the real classifier: a Board of Regents question
    classifies under the taxonomy's 'Office of the President' label and must
    route to production's actual OUP office, not fall back to OSA."""
    session = _session_with_offices(*_PRODUCTION_OFFICE_NAMES)
    try:
        result = triage_ticket(
            "Who are the current members of the Board of Regents?",
            "I want to know about the university's Board of Regents policies.",
            session=session,
        )
        assert result["assigned_office"] == "Office of the University President (OUP)"
        assert result["assigned_office_id"]
    finally:
        session.close()


def test_office_of_the_president_resolves_to_oup_even_without_default_fallback():
    """The OUP mapping resolves via the taxonomy-alias tier, so it must still
    succeed when a caller disallows the OSA default fallback -- it should
    never need that fallback in the first place."""
    session = _session_with_offices(*_PRODUCTION_OFFICE_NAMES)
    try:
        office_id, office_name = resolve_office_for_ticket(
            session, "Office of the President", allow_default_fallback=False
        )
        assert office_name == "Office of the University President (OUP)"
        assert office_id
    finally:
        session.close()


def test_ict_registrar_accounting_cashier_remain_correct_with_production_names():
    """Fix 2 must not disturb resolution for offices that already worked."""
    session = _session_with_offices(*_PRODUCTION_OFFICE_NAMES)
    try:
        _, ict_name = resolve_office_for_ticket(session, "ICT")
        assert "ICTS" in ict_name or "Communications Technology" in ict_name

        _, registrar_name = resolve_office_for_ticket(session, "Registrar's Office")
        assert registrar_name == "Registrar's Office"

        _, accounting_name = resolve_office_for_ticket(session, "Accounting")
        assert accounting_name == "Accounting Unit"

        _, cashier_name = resolve_office_for_ticket(session, "Cashier")
        assert cashier_name == "Cashier Unit"
    finally:
        session.close()


def test_osa_fallback_still_used_for_genuinely_default_label():
    """A genuinely unclassified/'General' label still defaults to OSA -- Fix 2
    only changes behavior for a SPECIFIC office label that fails to resolve."""
    session = _session_with_offices(*_PRODUCTION_OFFICE_NAMES)
    try:
        office_id, office_name = resolve_office_for_ticket(
            session, "Student Affairs and Services", allow_default_fallback=True
        )
        assert "Student Affairs" in office_name or "OSA" in office_name
        assert office_id
    finally:
        session.close()


def test_unresolved_specific_office_raises_instead_of_silently_becoming_osa():
    """A specific taxonomy office with no seeded match must raise, not
    silently resolve to OSA, when the caller opts out of the default
    fallback -- using the confirmed unmatched labels from the audit."""
    session = _session_with_offices(*_PRODUCTION_OFFICE_NAMES)
    try:
        for unmatched_label in (
            "Admissions Office",
            "College of Agriculture",
            "Graduate Studies Office",
        ):
            try:
                resolve_office_for_ticket(
                    session, unmatched_label, allow_default_fallback=False
                )
                raise AssertionError(f"expected UnresolvedOfficeLabelError for {unmatched_label!r}")
            except UnresolvedOfficeLabelError as exc:
                # The original taxonomy label is preserved for diagnostics,
                # not silently discarded/replaced by "OSA".
                assert exc.label == unmatched_label
    finally:
        session.close()


def test_unresolved_specific_office_is_distinguishable_from_genuine_osa_default():
    """End-to-end through triage_ticket: a specific classification that fails
    to resolve (assigned_office_id is None, raw taxonomy label preserved)
    must be distinguishable from a genuine OSA classification/default
    (assigned_office_id set, resolved OSA name) -- they must never collapse
    into the same observable result."""
    session = _session_with_offices(*_PRODUCTION_OFFICE_NAMES)
    try:
        # A specific, classifiable category whose production office (Admissions
        # Office) is a confirmed-unmatched taxonomy label in this session.
        unresolved = triage_ticket(
            "What are the admission requirements for incoming freshmen?",
            "Asking about the documentary requirements for new student applicants.",
            session=session,
        )
        assert unresolved["category"] != "General"
        assert unresolved["assigned_office_id"] is None
        assert unresolved["assigned_office"] == "Admissions Office"

        # A genuinely unclassified/general ticket must still land on OSA,
        # with a real resolved office id -- not collapse into the same shape
        # as the unresolved case above.
        general = triage_ticket(
            "asdkjf qwoeiru zxksldjf mnbvqwer",
            "zxcvbnmasdfghjklqwertyuiop random unclassifiable text",
            session=session,
        )
        assert general["category"] == "General"
        assert general["assigned_office_id"] is not None
        assert "Student Affairs" in general["assigned_office"] or "OSA" in general["assigned_office"]

        # The two must be clearly distinguishable, not silently identical.
        assert unresolved["assigned_office_id"] != general["assigned_office_id"]
        assert unresolved["assigned_office"] != general["assigned_office"]
    finally:
        session.close()
