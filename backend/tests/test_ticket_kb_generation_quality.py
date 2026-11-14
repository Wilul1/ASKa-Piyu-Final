"""Focused tests for ticket → KB article generation quality (Phase 1)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.db_models import Office, PublishedArticle, Ticket, TicketReply, User
from app.services.passwords import hash_password
from app.services.ticket_knowledge import (
    _COMPLETION_MARKER,
    _classify_sentence,
    _classify_staff_answer,
    _format_structured_article,
    build_generated_article_from_ticket,
    convert_ticket_to_draft_article,
    generate_article_from_resolved_ticket,
    retry_ticket_kb_generation,
)
from app.services.ticketing import resolve_ticket


_ADVERSARIAL_STAFF_REPLIES = {
    "A": "Please contact the Registrar for the latest requirements.",
    "B": "Submit your completed application form to the Registrar.",
    "C": "The Registrar requires a completed application form.",
    "D": "Please contact the Registrar to obtain the application form.",
    "E": "You must submit your application within five working days.",
    "F": "Your request is being processed. We will update you once it is ready.",
    "G": "The required documents are your valid ID, enrollment form, and payment receipt.",
    # Acknowledgements / hedges must not become substantive FAQ answers.
    "H": "Thank you for contacting the Registrar's Office.",
    "I": "You're welcome!",
    "J": (
        "We recommend confirming the current application form before submitting "
        "your request to avoid using an outdated document."
    ),
    "K": (
        "Please also confirm whether the certificate is needed for employment, "
        "scholarship, or another purpose."
    ),
    "L": (
        "If you have any questions or need further assistance, feel free to "
        "reply to this ticket."
    ),
    "M": (
        "Kindly provide your complete name, student number, program, and "
        "current year level when submitting your request."
    ),
}


@pytest.fixture()
def session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = factory()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def _office(session: Session) -> Office:
    office = Office(id="office-reg", name="Registrar", description="Registrar")
    session.add(office)
    session.commit()
    return office


def _user(session: Session, *, role: str, office_id: str | None = None) -> User:
    user = User(
        id=f"user-{role}-{office_id or 'x'}",
        email=f"{role}@lspu.test",
        password_hash=hash_password("password123"),
        full_name=f"{role.title()} User",
        role=role,
        office_id=office_id,
        student_id="STU-1" if role == "student" else None,
    )
    session.add(user)
    session.commit()
    return user


def _ticket_with_thread(
    session: Session,
    office: Office,
    student: User,
    staff: User,
    *,
    ticket_id: str,
    question: str,
    student_messages: list[str] | None = None,
    staff_messages: list[str] | None = None,
    internal_notes: list[str] | None = None,
) -> Ticket:
    now = datetime.now(timezone.utc)
    ticket = Ticket(
        id=ticket_id,
        user_id=student.id,
        original_question=question,
        description=question,
        category="Student Services",
        assigned_office_id=office.id,
        assigned_office=office.name,
        priority="Medium",
        status="Resolved",
        kb_conversion_status="none",
        created_at=now,
        updated_at=now,
        resolved_at=now,
    )
    session.add(ticket)
    session.flush()
    for message in student_messages or []:
        session.add(
            TicketReply(
                ticket_id=ticket.id,
                sender_id=student.id,
                sender_role="student",
                sender_name=student.full_name,
                message=message,
                created_at=now,
            )
        )
    for message in internal_notes or []:
        session.add(
            TicketReply(
                ticket_id=ticket.id,
                sender_id=staff.id,
                sender_role=staff.role,
                sender_name=staff.full_name,
                message=message,
                is_internal=True,
                created_at=now,
            )
        )
    for message in staff_messages or []:
        session.add(
            TicketReply(
                ticket_id=ticket.id,
                sender_id=staff.id,
                sender_role=staff.role,
                sender_name=staff.full_name,
                message=message,
                created_at=now,
            )
        )
    session.commit()
    session.refresh(ticket)
    return ticket


def test_complete_answer_produces_structured_useful_article(session: Session):
    office = _office(session)
    student = _user(session, role="student")
    staff = _user(session, role="office", office_id=office.id)
    ticket = _ticket_with_thread(
        session,
        office,
        student,
        staff,
        ticket_id="TKT-GQ-COMPLETE",
        question="How do I request an excuse slip?",
        staff_messages=[
            "Good day! Submit the excuse slip form and a medical certificate "
            "to OSAS within three working days of the absence. "
            "Go to the OSAS window and keep a photocopy for your records."
        ],
    )

    generated = build_generated_article_from_ticket(ticket)
    assert generated.needs_manual_completion is False
    assert "excuse slip" in generated.title.casefold()
    assert "(" not in generated.title
    assert "good day" not in generated.content.casefold()
    assert "excuse slip form" in generated.content.casefold()
    assert "medical certificate" in generated.content.casefold()
    assert "##" in generated.content  # structured sections
    assert "needs staff completion" not in generated.content.casefold()
    assert "learn" in generated.summary.casefold() or "how" in generated.summary.casefold() or "osas" in generated.summary.casefold()


def test_incomplete_referral_does_not_invent_official_details(session: Session):
    office = _office(session)
    student = _user(session, role="student")
    staff = _user(session, role="office", office_id=office.id)
    ticket = _ticket_with_thread(
        session,
        office,
        student,
        staff,
        ticket_id="TKT-GQ-REFERRAL",
        question="How do I claim my TOR?",
        staff_messages=[
            "Please inquire at the Registrar for the latest release requirements."
        ],
    )

    generated = build_generated_article_from_ticket(ticket)
    assert generated.needs_manual_completion is True
    assert generated.generation_notes == "incomplete_referral"
    assert "needs staff completion" in generated.content.casefold()
    assert "do not invent" in generated.content.casefold()
    # Must not fabricate concrete TOR claim steps.
    assert "claim stub" not in generated.content.casefold()
    assert "official receipt" not in generated.content.casefold()


def test_followup_question_does_not_pollute_title(session: Session):
    office = _office(session)
    student = _user(session, role="student")
    staff = _user(session, role="office", office_id=office.id)
    ticket = _ticket_with_thread(
        session,
        office,
        student,
        staff,
        ticket_id="TKT-GQ-FOLLOWUP-TITLE",
        question="Request for Certificate of Enrollment",
        student_messages=[
            "Thank you! I need the COE for a scholarship application. "
            "Is there a specific form i need to accomplish?"
        ],
        staff_messages=[
            "Submit the certificate request form at the Registrar, pay the fee "
            "at the cashier, and present the official receipt. Release is the "
            "next working day."
        ],
    )

    generated = build_generated_article_from_ticket(ticket)
    assert generated.title == "Request for Certificate of Enrollment"
    assert "thank you" not in generated.title.casefold()
    assert "scholarship" not in generated.title.casefold()
    assert "specific form" not in generated.title.casefold()


def test_conversational_acknowledgments_stripped_from_body(session: Session):
    office = _office(session)
    student = _user(session, role="student")
    staff = _user(session, role="office", office_id=office.id)
    ticket = _ticket_with_thread(
        session,
        office,
        student,
        staff,
        ticket_id="TKT-GQ-FILLER",
        question="How do I validate my student ID?",
        student_messages=["Thank you!", "Okay noted"],
        staff_messages=[
            "Hi",
            "You're welcome!",
            "Bring your Certificate of Registration and a valid government ID "
            "to OSAS. Validation is processed within one working day.",
        ],
    )

    generated = build_generated_article_from_ticket(ticket)
    body = generated.content.casefold()
    assert "you're welcome" not in body
    assert not body.startswith("hi")
    assert "certificate of registration" in body
    assert "thank you" not in body


def test_contradictory_staff_answers_flagged_for_review(session: Session):
    office = _office(session)
    student = _user(session, role="student")
    staff = _user(session, role="office", office_id=office.id)
    ticket = _ticket_with_thread(
        session,
        office,
        student,
        staff,
        ticket_id="TKT-GQ-CONTRADICT",
        question="How long does ID validation take?",
        staff_messages=[
            "Bring your COR to OSAS. Validation is processed within 1 working day.",
            "Go to OSAS with your COR. Validation is processed within 5 working days.",
        ],
    )

    generated = build_generated_article_from_ticket(ticket)
    assert generated.needs_manual_completion is True
    assert generated.generation_notes == "contradictory_answers"
    assert "conflicting" in generated.content.casefold()
    assert "needs staff completion" in generated.content.casefold()


def test_missing_requirements_are_not_invented(session: Session):
    office = _office(session)
    student = _user(session, role="student")
    staff = _user(session, role="office", office_id=office.id)
    ticket = _ticket_with_thread(
        session,
        office,
        student,
        staff,
        ticket_id="TKT-GQ-NO-INVENT",
        question="What are the requirements for a Certificate of Enrollment?",
        staff_messages=[
            "Please confirm the current requirements with the Registrar office."
        ],
    )

    generated = build_generated_article_from_ticket(ticket)
    blob = f"{generated.title}\n{generated.summary}\n{generated.content}".casefold()
    for invented in (
        "form 138",
        "php 50",
        "₱50",
        "two working days",
        "cashier window 3",
    ):
        assert invented not in blob
    assert generated.needs_manual_completion is True


def test_internal_notes_never_enter_public_article(session: Session):
    office = _office(session)
    student = _user(session, role="student")
    staff = _user(session, role="office", office_id=office.id)
    ticket = _ticket_with_thread(
        session,
        office,
        student,
        staff,
        ticket_id="TKT-GQ-INTERNAL",
        question="How do I request a good moral certificate?",
        internal_notes=[
            "Internal: student is on disciplinary probation, do not publish this."
        ],
        staff_messages=[
            "Submit the good moral request form at OSA with a valid ID. "
            "Release is typically within three working days."
        ],
    )

    generated = build_generated_article_from_ticket(ticket)
    blob = f"{generated.title}\n{generated.summary}\n{generated.content}".casefold()
    assert "disciplinary probation" not in blob
    assert "do not publish this" not in blob
    assert "good moral request form" in generated.content.casefold()


def test_pii_redaction_preserved_in_generated_fields(session: Session):
    office = _office(session)
    student = User(
        id="user-gq-pii",
        email="juan.dela.cruz@lspu.test",
        password_hash=hash_password("password123"),
        full_name="Juan Dela Cruz",
        role="student",
        student_id="2024-998877",
    )
    session.add(student)
    session.commit()
    staff = _user(session, role="office", office_id=office.id)
    ticket = _ticket_with_thread(
        session,
        office,
        student,
        staff,
        ticket_id="TKT-GQ-PII",
        question="How can Juan Dela Cruz get an excuse slip?",
        student_messages=[
            "I am Juan Dela Cruz, student number 2024-998877. "
            "Email juan.dela.cruz@lspu.test or 09181234567."
        ],
        staff_messages=[
            "Submit the excuse slip form and a medical certificate to OSAS "
            "within three working days of the absence."
        ],
    )

    payload = generate_article_from_resolved_ticket(
        session, ticket_id=ticket.id, actor=staff
    )
    blob = " ".join(
        [
            payload["title"] or "",
            payload["content"] or "",
            payload["summary"] or "",
            payload.get("generation_notes") or "",
        ]
    )
    assert "Juan Dela Cruz" not in blob
    assert "2024-998877" not in blob
    assert "09181234567" not in blob
    assert "juan.dela.cruz@lspu.test" not in blob.casefold()


def test_duplicate_protection_still_blocks_specific_topic(session: Session):
    office = _office(session)
    student = _user(session, role="student")
    staff = _user(session, role="office", office_id=office.id)
    now = datetime.now(timezone.utc)
    session.add(
        PublishedArticle(
            id="art-gq-coe",
            title="Certificate of Enrollment",
            slug="certificate-of-enrollment-gq",
            category="Academic Policies",
            summary="How to request a Certificate of Enrollment.",
            content="## Certificate of Enrollment\n\nRequest steps at the Registrar.",
            office="Registrar",
            source_filename="charter.pdf",
            audience="student",
            kb_origin="document",
            published=True,
            published_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    session.commit()

    open_ticket = Ticket(
        id="TKT-GQ-DUP",
        user_id=student.id,
        original_question="Request for Certificate of Enrollment",
        description="COE request",
        category="Student Services",
        assigned_office_id=office.id,
        assigned_office=office.name,
        priority="Medium",
        status="Open",
        kb_conversion_status="none",
        created_at=now,
        updated_at=now,
    )
    session.add(open_ticket)
    session.flush()
    session.add(
        TicketReply(
            ticket_id=open_ticket.id,
            sender_id=staff.id,
            sender_role="office",
            sender_name=staff.full_name,
            message=(
                "Submit the certificate request form at the Registrar, pay the "
                "fee at the cashier, and present the receipt."
            ),
            created_at=now,
        )
    )
    session.commit()

    payload = resolve_ticket(session, open_ticket.id, staff)
    assert payload.status == "Resolved"
    assert payload.kb_conversion_status == "failed"


def test_retry_after_incomplete_draft_reuses_single_article(session: Session):
    office = _office(session)
    student = _user(session, role="student")
    staff = _user(session, role="office", office_id=office.id)
    ticket = _ticket_with_thread(
        session,
        office,
        student,
        staff,
        ticket_id="TKT-GQ-RETRY",
        question="How do I request a Certificate of Enrollment?",
        staff_messages=[
            "Please confirm the current Certificate of Enrollment process "
            "with the Registrar."
        ],
    )

    first = generate_article_from_resolved_ticket(
        session, ticket_id=ticket.id, actor=staff
    )
    assert first["needs_manual_completion"] is True
    second = retry_ticket_kb_generation(session, ticket_id=ticket.id, actor=staff)
    assert first["article_id"] == second["article_id"]
    rows = (
        session.query(PublishedArticle)
        .filter(PublishedArticle.source_ticket_id == ticket.id)
        .all()
    )
    assert len(rows) == 1
    assert rows[0].published is False


def test_coe_reference_scenario_stays_incomplete_and_title_clean(session: Session):
    """Sanitized fixture mirroring TK-20261113-6F6603 conversation shape."""
    office = _office(session)
    student = _user(session, role="student")
    staff = _user(session, role="office", office_id=office.id)
    ticket = _ticket_with_thread(
        session,
        office,
        student,
        staff,
        ticket_id="TKT-GQ-COE-REF",
        question="Request for Certificate of Enrollment",
        student_messages=[
            "Thank you! I need the COE for a scholarship application. "
            "Is there a specific form i need to accomplish?"
        ],
        staff_messages=[
            "Good day! Thank you for contacting the Registrar's Office. "
            "For your request, please check the current Registrar requirements "
            "and confirm the latest process with the office.",
            "You're welcome! For the specific form and latest requirements, "
            "please confirm with the Registrar.",
        ],
    )

    generated = build_generated_article_from_ticket(ticket)
    assert generated.title == "Request for Certificate of Enrollment"
    assert "thank you" not in generated.title.casefold()
    assert "scholarship" not in generated.title.casefold()
    assert generated.needs_manual_completion is True
    assert generated.generation_notes in {
        "incomplete_referral",
        "unanswered_followup",
        "deferred_answer",
    }
    body = generated.content.casefold()
    assert "needs staff completion" in body
    assert "form 138" not in body
    assert "php" not in body
    assert "official requirements were not confirmed" in body
    assert "partial guidance" in generated.summary.casefold() or "incomplete" in generated.summary.casefold()

    payload = generate_article_from_resolved_ticket(
        session, ticket_id=ticket.id, actor=staff
    )
    assert payload["published"] is False
    assert payload["needs_manual_completion"] is True
    assert payload["kb_conversion_status"] == "needs_review"
    assert payload["title"] == "Request for Certificate of Enrollment"


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("A", "referral"),
        ("B", "substantive"),
        ("C", "substantive"),
        ("D", "referral"),
        ("E", "substantive"),
        ("F", "deferred"),
        ("G", "substantive"),
        ("H", "deferred"),
        ("I", "deferred"),
        ("J", "referral"),
        ("K", "deferred"),
        ("L", "deferred"),
        ("M", "deferred"),
    ],
)
def test_adversarial_staff_reply_classification(label: str, expected: str):
    assert _classify_staff_answer(_ADVERSARIAL_STAFF_REPLIES[label]) == expected


@pytest.mark.parametrize(
    "text",
    [
        "Present your student ID at OSAS for validation.",
        "Bring your student number printout to the dean.",
        "Enroll in the nursing program after advising.",
        "Could you please provide the TOR request form at Window 3 and pay at the cashier?",
    ],
)
def test_actionable_id_program_and_provide_form_stay_substantive(text: str):
    """Identity tokens / polite 'provide' must not false-negative actionable guidance."""
    assert _classify_sentence(text) == "substantive"
    assert _classify_staff_answer(text) == "substantive"


@pytest.mark.parametrize(
    "text",
    [
        "Kindly provide your complete name and student number so we can check your record.",
        "Could you please clarify which semester you are applying for?",
        "May we know your program and year level?",
    ],
)
def test_true_identity_intake_and_clarifying_asks_stay_deferred(text: str):
    assert _classify_sentence(text) == "deferred"
    assert _classify_staff_answer(text) == "deferred"


def test_mixed_substantive_with_referral_and_identity_ask(session: Session):
    """Genuine steps stay complete-eligible evidence; referral + intake stay non-inventing."""
    office = _office(session)
    student = _user(session, role="student")
    staff = _user(session, role="office", office_id=office.id)
    ticket = _ticket_with_thread(
        session,
        office,
        student,
        staff,
        ticket_id="TKT-GQ-MIX-ID-REF",
        question="How do I request a good moral certificate?",
        staff_messages=[
            "Present your student ID at OSAS for validation. "
            "Please confirm the current processing fee with the office. "
            "Kindly provide your complete name and student number so we can check your record.",
        ],
    )
    assert (
        _classify_sentence("Present your student ID at OSAS for validation.")
        == "substantive"
    )
    assert (
        _classify_sentence(
            "Kindly provide your complete name and student number so we can check your record."
        )
        == "deferred"
    )
    generated = build_generated_article_from_ticket(ticket)
    body = generated.content.casefold()
    assert "student id" in body or "osas" in body
    assert "where to go" in body or "confirm" in body
    # Identity-intake / status chatter no longer forces incomplete when a
    # substantive reusable step already exists; staff review is the gate.
    assert generated.needs_manual_completion is False
    assert "php" not in body
    assert "kindly provide your complete name" not in body


def test_prod_coe_conversation_stays_incomplete_draft(session: Session):
    """Exact sanitized shape of TK-20261113-6F6603 / article e18a7ad9…"""
    office = _office(session)
    student = _user(session, role="student")
    staff = _user(session, role="office", office_id=office.id)
    ticket = _ticket_with_thread(
        session,
        office,
        student,
        staff,
        ticket_id="TKT-GQ-COE-PROD",
        question="Request for Certificate of Enrollment",
        student_messages=[
            "Thank you! I need the COE for a scholarship application. "
            "Is there a specific form i need to accomplish?"
        ],
        staff_messages=[
            (
                "Good day!\n\n"
                "Thank you for contacting the Registrar's Office.\n\n"
                "For your request for a Certificate of Enrollment (COE), please "
                "check the university's current requirements and application "
                "procedure with the Registrar's Office.\n\n"
                "Kindly provide your complete name, student number, program, and "
                "current year level when submitting your request. Please also "
                "confirm whether the certificate is needed for employment, "
                "scholarship, or another purpose.\n\n"
                "If you have any questions or need further assistance, feel free "
                "to reply to this ticket.\n\n"
                "Thank you!"
            ),
            (
                "You're welcome!\n\n"
                "For the specific form and latest requirements, please coordinate "
                "with the Registrar's Office. We recommend confirming the current "
                "application form before submitting your request to avoid using an "
                "outdated document.\n\n"
                "Thank you!"
            ),
        ],
    )
    # Patch description to match production ticket text used for context.
    ticket.description = (
        "Good day! i would like to request a Certificate of Enrollment (COE) for "
        "the current semester. May I know the requirements and procedure for "
        "requesting one? Also, where should i submit the requirement? Thank you!"
    )
    session.add(ticket)
    session.commit()

    assert _classify_sentence("Thank you for contacting the Registrar's Office.") == "deferred"
    assert _classify_sentence("You're welcome!") == "deferred"
    assert (
        _classify_sentence(
            "We recommend confirming the current application form before submitting "
            "your request to avoid using an outdated document."
        )
        == "referral"
    )

    generated = build_generated_article_from_ticket(ticket)
    assert generated.needs_manual_completion is True
    assert generated.generation_notes in {
        "incomplete_referral",
        "unanswered_followup",
        "deferred_answer",
        "unconfirmed_referral",
    }
    body = generated.content.casefold()
    assert "needs staff completion" in body
    assert _COMPLETION_MARKER.casefold() in body
    assert "where to go" in body
    assert "you're welcome" not in body
    assert "form 138" not in body
    assert "php" not in body

    payload = generate_article_from_resolved_ticket(
        session, ticket_id=ticket.id, actor=staff
    )
    assert payload["published"] is False
    assert payload["needs_manual_completion"] is True
    assert payload["kb_conversion_status"] == "needs_review"
    assert payload["generation_notes"] in {
        "incomplete_referral",
        "unanswered_followup",
        "deferred_answer",
        "unconfirmed_referral",
    }

    # Convert-with-content using the incomplete chat must NOT clear the gate.
    pasted = (
        "1. Thank you for contacting the Registrar's Office. For your request for "
        "a Certificate of Enrollment (COE), please check the university's current "
        "requirements and application procedure with the Registrar's Office.\n"
        "2. You're welcome! For the specific form and latest requirements, please "
        "coordinate with the Registrar's Office."
    )
    converted = convert_ticket_to_draft_article(
        session,
        ticket_id=ticket.id,
        actor=staff,
        content=pasted,
    )
    assert converted["needs_manual_completion"] is True
    assert converted["published"] is False
    assert converted["kb_conversion_status"] == "needs_review"
    assert _COMPLETION_MARKER in (converted.get("content") or "")


def test_ack_plus_referral_never_counts_as_complete_answer(session: Session):
    office = _office(session)
    student = _user(session, role="student")
    staff = _user(session, role="office", office_id=office.id)
    ticket = _ticket_with_thread(
        session,
        office,
        student,
        staff,
        ticket_id="TKT-GQ-ACK-REF",
        question="How do I request a good moral certificate?",
        staff_messages=[
            "You're welcome! Please coordinate with the Office of Student Affairs "
            "for the latest requirements and application form."
        ],
    )
    generated = build_generated_article_from_ticket(ticket)
    assert generated.needs_manual_completion is True
    assert generated.generation_notes == "incomplete_referral"
    body = generated.content.casefold()
    assert "you're welcome" not in body
    assert "where to go" in body
    assert "do not invent" in body


def test_genuine_complete_coe_answer_still_publishes_as_ready(session: Session):
    office = _office(session)
    student = _user(session, role="student")
    staff = _user(session, role="office", office_id=office.id)
    ticket = _ticket_with_thread(
        session,
        office,
        student,
        staff,
        ticket_id="TKT-GQ-COE-COMPLETE",
        question="How do I request a Certificate of Enrollment?",
        student_messages=[
            "Is there a specific form I need, and where do I submit it?"
        ],
        staff_messages=[
            "Submit the Certificate of Enrollment request form at the Registrar "
            "window, bring a valid ID, and pay the assessment fee at the cashier. "
            "Release is the next working day."
        ],
    )
    generated = build_generated_article_from_ticket(ticket)
    assert generated.needs_manual_completion is False
    assert generated.generation_notes is None
    body = generated.content.casefold()
    assert "certificate of enrollment request form" in body
    assert "needs staff completion" not in body
    payload = generate_article_from_resolved_ticket(
        session, ticket_id=ticket.id, actor=staff
    )
    assert payload["needs_manual_completion"] is False
    assert payload["kb_conversion_status"] == "draft"


def test_informational_payment_answer_goes_to_overview_not_procedure():
    """Factual 'payment' answers must not become Procedure via substring 'pay'."""
    body = _format_structured_article(
        [
            "Yes. The Cashier Unit currently accepts cash and over-the-counter "
            "bank payments. Online payment is available only through the "
            "university's officially announced payment channels for the semester."
        ],
        office_name="Cashier Unit",
    )
    assert "## Overview" in body
    assert "## Procedure" not in body
    assert "Cashier Unit" in body


def test_pay_at_cashier_still_counts_as_procedure():
    body = _format_structured_article(
        ["Go to Window 3 and pay at the cashier with your assessment form."],
        office_name="Cashier Unit",
    )
    assert "## Procedure" in body
    assert "pay at the cashier" in body.casefold()


def test_review_message_f_is_deferred_and_incomplete(session: Session):
    office = _office(session)
    student = _user(session, role="student")
    staff = _user(session, role="office", office_id=office.id)
    ticket = _ticket_with_thread(
        session,
        office,
        student,
        staff,
        ticket_id="TKT-GQ-STATUS-F",
        question="Where is my Certificate of Enrollment request?",
        staff_messages=[_ADVERSARIAL_STAFF_REPLIES["F"]],
    )

    generated = build_generated_article_from_ticket(ticket)
    assert _classify_staff_answer(_ADVERSARIAL_STAFF_REPLIES["F"]) == "deferred"
    assert generated.needs_manual_completion is True
    assert generated.generation_notes == "deferred_answer"
    assert "needs staff completion" in generated.content.casefold()
    assert "form 138" not in generated.content.casefold()
    assert "php" not in generated.content.casefold()

    payload = generate_article_from_resolved_ticket(
        session, ticket_id=ticket.id, actor=staff
    )
    assert payload["published"] is False
    assert payload["needs_manual_completion"] is True
    assert payload["kb_conversion_status"] == "needs_review"


@pytest.mark.parametrize(
    "status_message",
    [
        "Your request is being processed.",
        "We will update you once it is ready.",
        "We will notify you when it is available.",
        "Your application is currently under review.",
        "Please wait while your request is being processed.",
        "We will contact you once processing is complete.",
    ],
)
def test_status_only_messages_cannot_look_complete(session: Session, status_message: str):
    office = _office(session)
    student = _user(session, role="student")
    staff = _user(session, role="office", office_id=office.id)
    ticket = _ticket_with_thread(
        session,
        office,
        student,
        staff,
        ticket_id=f"TKT-GQ-STATUS-{abs(hash(status_message)) % 10_000}",
        question="Any update on my TOR request?",
        staff_messages=[status_message],
    )

    assert _classify_staff_answer(status_message) == "deferred"
    generated = build_generated_article_from_ticket(ticket)
    assert generated.needs_manual_completion is True
    assert generated.generation_notes == "deferred_answer"
    assert "needs staff completion" in generated.content.casefold()


def test_substantive_then_separate_referral_is_preserved(session: Session):
    office = _office(session)
    student = _user(session, role="student")
    staff = _user(session, role="office", office_id=office.id)
    ticket = _ticket_with_thread(
        session,
        office,
        student,
        staff,
        ticket_id="TKT-GQ-SUB-THEN-REF",
        question="What are the requirements and fees for enrollment validation?",
        staff_messages=[
            "The required documents are your valid ID and enrollment form.",
            "Please confirm the current processing fee with the Cashier's Office.",
        ],
    )

    generated = build_generated_article_from_ticket(ticket)
    body = generated.content.casefold()
    assert "valid id" in body
    assert "enrollment form" in body
    assert "cashier" in body
    assert "processing fee" in body
    assert "php" not in body
    assert "₱" not in generated.content
    assert "where to go" in body
    assert generated.needs_manual_completion is True
    assert generated.generation_notes == "unconfirmed_referral"


def test_referral_then_substantive_preserves_both(session: Session):
    office = _office(session)
    student = _user(session, role="student")
    staff = _user(session, role="office", office_id=office.id)
    ticket = _ticket_with_thread(
        session,
        office,
        student,
        staff,
        ticket_id="TKT-GQ-REF-THEN-SUB",
        question="How do I request an excuse slip and what is the fee?",
        staff_messages=[
            "Please confirm the current processing fee with the Cashier's Office.",
            "Submit the excuse slip form and a medical certificate to OSAS "
            "within three working days of the absence.",
        ],
    )

    generated = build_generated_article_from_ticket(ticket)
    body = generated.content.casefold()
    assert "excuse slip form" in body
    assert "medical certificate" in body
    assert "cashier" in body
    assert "processing fee" in body
    assert "where to go" in body
    assert generated.needs_manual_completion is True
    assert generated.generation_notes == "unconfirmed_referral"
    assert "php 50" not in body


def test_multiple_referral_replies_do_not_invent_facts(session: Session):
    office = _office(session)
    student = _user(session, role="student")
    staff = _user(session, role="office", office_id=office.id)
    ticket = _ticket_with_thread(
        session,
        office,
        student,
        staff,
        ticket_id="TKT-GQ-MULTI-REF",
        question="How do I claim my TOR and what fee is required for release?",
        staff_messages=[
            "Please inquire at the Registrar for the latest TOR release requirements.",
            "Please confirm the current processing fee with the Cashier's Office.",
        ],
    )

    generated = build_generated_article_from_ticket(ticket)
    body = generated.content.casefold()
    assert generated.needs_manual_completion is True
    assert generated.generation_notes == "incomplete_referral"
    assert "registrar" in body
    assert "cashier" in body
    for invented in ("claim stub", "official receipt", "php 50", "form 138"):
        assert invented not in body


def test_mixed_answer_and_referral_message_keeps_concrete_facts(session: Session):
    office = _office(session)
    student = _user(session, role="student")
    staff = _user(session, role="office", office_id=office.id)
    ticket = _ticket_with_thread(
        session,
        office,
        student,
        staff,
        ticket_id="TKT-GQ-MIXED-MSG",
        question="How do I request a Certificate of Enrollment and what is the fee?",
        staff_messages=[
            "Submit the certificate request form at the Registrar and present "
            "a valid ID. Please confirm the current processing fee with the "
            "Cashier's Office."
        ],
    )

    mixed = (
        "Submit the certificate request form at the Registrar and present "
        "a valid ID. Please confirm the current processing fee with the "
        "Cashier's Office."
    )
    assert _classify_staff_answer(mixed) == "substantive"
    generated = build_generated_article_from_ticket(ticket)
    body = generated.content.casefold()
    assert "certificate request form" in body
    assert "valid id" in body or "present" in body
    assert "cashier" in body
    assert "php" not in body
    assert generated.needs_manual_completion is True
    assert generated.generation_notes == "unconfirmed_referral"


def test_mixed_submit_and_status_keeps_instruction_and_needs_review(session: Session):
    office = _office(session)
    student = _user(session, role="student")
    staff = _user(session, role="office", office_id=office.id)
    mixed = (
        "Please submit your completed form to the Registrar. "
        "We will update you once processing is complete."
    )
    ticket = _ticket_with_thread(
        session,
        office,
        student,
        staff,
        ticket_id="TKT-GQ-MIXED-STATUS-D",
        question="How do I request enrollment validation?",
        staff_messages=[mixed],
    )

    assert _classify_staff_answer(mixed) == "substantive"
    generated = build_generated_article_from_ticket(ticket)
    body = generated.content.casefold()
    assert "submit your completed form" in body
    assert "registrar" in body
    # Status chatter is omitted from reusable FAQ copy and no longer forces
    # incomplete when a substantive answer already exists.
    assert "request status" not in body
    assert "we will update you once processing is complete" not in body
    if "## overview" in body:
        overview = body.split("## overview", 1)[1].split("##", 1)[0]
        assert "we will update you" not in overview
    assert generated.needs_manual_completion is False
    assert "needs staff completion" not in body
    assert generated.generation_notes is None


def test_mixed_requirements_and_status_preserve_documents(session: Session):
    office = _office(session)
    student = _user(session, role="student")
    staff = _user(session, role="office", office_id=office.id)
    mixed = (
        "The required documents are your valid ID and enrollment form. "
        "We will contact you when the request is ready."
    )
    ticket = _ticket_with_thread(
        session,
        office,
        student,
        staff,
        ticket_id="TKT-GQ-MIXED-STATUS-E",
        question="What are the requirements for enrollment validation?",
        staff_messages=[mixed],
    )

    assert _classify_staff_answer(mixed) == "substantive"
    generated = build_generated_article_from_ticket(ticket)
    body = generated.content.casefold()
    assert "valid id" in body
    assert "enrollment form" in body
    assert "required documents" in body
    assert generated.needs_manual_completion is False
    assert "request status" not in body
    assert "we will contact you" not in body
    assert "needs staff completion" not in body
    assert generated.summary.casefold().startswith("we will contact you") is False


def test_unrelated_library_referral_excluded_from_excuse_slip(session: Session):
    office = _office(session)
    student = _user(session, role="student")
    staff = _user(session, role="office", office_id=office.id)
    ticket = _ticket_with_thread(
        session,
        office,
        student,
        staff,
        ticket_id="TKT-GQ-UNRELATED-LIB",
        question="How do I request an excuse slip?",
        staff_messages=[
            "Submit the excuse slip form and a medical certificate to OSAS "
            "within three working days of the absence.",
            "Please confirm the current library fine schedule with the Library Office.",
        ],
    )

    generated = build_generated_article_from_ticket(ticket)
    body = generated.content.casefold()
    assert "excuse slip form" in body
    assert "medical certificate" in body
    assert "library fine" not in body
    assert "library office" not in body
    assert generated.needs_manual_completion is False


def test_coe_registrar_referral_is_preserved(session: Session):
    office = _office(session)
    student = _user(session, role="student")
    staff = _user(session, role="office", office_id=office.id)
    ticket = _ticket_with_thread(
        session,
        office,
        student,
        staff,
        ticket_id="TKT-GQ-COE-REG-REF",
        question="Request for Certificate of Enrollment",
        staff_messages=[
            "Please confirm the current Certificate of Enrollment requirements "
            "with the Registrar.",
        ],
    )

    generated = build_generated_article_from_ticket(ticket)
    body = generated.content.casefold()
    assert generated.needs_manual_completion is True
    assert "certificate of enrollment" in body
    assert "registrar" in body
    assert "form 138" not in body
    assert "php" not in body


def test_duplicate_relevant_referrals_appear_once(session: Session):
    office = _office(session)
    student = _user(session, role="student")
    staff = _user(session, role="office", office_id=office.id)
    referral = "Please confirm the current processing fee with the Cashier's Office."
    ticket = _ticket_with_thread(
        session,
        office,
        student,
        staff,
        ticket_id="TKT-GQ-DUP-REF",
        question="How do I request a Certificate of Enrollment and what is the fee?",
        staff_messages=[
            "Submit the certificate request form at the Registrar.",
            referral,
            referral,
        ],
    )

    generated = build_generated_article_from_ticket(ticket)
    confirm = generated.content.casefold().split("where to go", 1)[-1]
    confirm = confirm.split("needs staff completion", 1)[0]
    assert confirm.count("please confirm the current processing fee") == 1


@pytest.mark.parametrize(
    ("ticket_id", "question", "message"),
    [
        (
            "TKT-GQ-MIX-AND",
            "How do I request enrollment validation?",
            "Submit your completed form to the Registrar and we will update you "
            "once processing is complete.",
        ),
        (
            "TKT-GQ-MIX-AND-REQ",
            "What are the requirements for enrollment validation?",
            "Required documents are valid ID and enrollment form and we will "
            "contact you when the request is ready.",
        ),
        (
            "TKT-GQ-MIX-SEMI",
            "How do I follow up on my application?",
            "Bring your receipt; we will notify you when your application is available.",
        ),
    ],
)
def test_unpunctuated_mixed_status_omits_status_from_faq(
    session: Session, ticket_id: str, question: str, message: str
):
    office = _office(session)
    student = _user(session, role="student")
    staff = _user(session, role="office", office_id=office.id)
    ticket = _ticket_with_thread(
        session,
        office,
        student,
        staff,
        ticket_id=ticket_id,
        question=question,
        staff_messages=[message],
    )

    assert _classify_staff_answer(message) == "substantive"
    generated = build_generated_article_from_ticket(ticket)
    body = generated.content.casefold()
    assert "request status" not in body
    assert "we will update you" not in body
    assert "we will contact you" not in body
    assert "we will notify you" not in body
    # Long reusable remainder stays complete; tiny leftovers may still be
    # answer_too_short after status clauses are scrubbed.
    if generated.needs_manual_completion:
        assert generated.generation_notes == "answer_too_short"
        assert "needs staff completion" in body
    else:
        assert generated.generation_notes is None
        assert "needs staff completion" not in body
    if "## overview" in body:
        overview = body.split("## overview", 1)[1].split("##", 1)[0]
        assert "we will update you" not in overview
        assert "we will contact you" not in overview
        assert "we will notify you" not in overview


def test_status_first_then_requirements_without_period(session: Session):
    office = _office(session)
    student = _user(session, role="student")
    staff = _user(session, role="office", office_id=office.id)
    message = (
        "We will contact you when the request is ready required documents are "
        "valid ID and enrollment form"
    )
    ticket = _ticket_with_thread(
        session,
        office,
        student,
        staff,
        ticket_id="TKT-GQ-STATUS-FIRST",
        question="What are the requirements for enrollment validation?",
        staff_messages=[message],
    )

    generated = build_generated_article_from_ticket(ticket)
    body = generated.content.casefold()
    assert _classify_staff_answer(message) == "substantive"
    assert "valid id" in body
    assert "enrollment form" in body
    assert generated.needs_manual_completion is False
    assert "request status" not in body
    assert "we will contact you" not in body


def test_multi_requirements_and_multi_status_clauses(session: Session):
    office = _office(session)
    student = _user(session, role="student")
    staff = _user(session, role="office", office_id=office.id)
    ticket = _ticket_with_thread(
        session,
        office,
        student,
        staff,
        ticket_id="TKT-GQ-MULTI-MIX",
        question="What are the requirements for enrollment validation?",
        staff_messages=[
            "Bring a valid ID. Bring your enrollment form. "
            "Your request is being processed. We will update you once it is ready."
        ],
    )

    generated = build_generated_article_from_ticket(ticket)
    body = generated.content.casefold()
    assert "valid id" in body
    assert "enrollment form" in body
    assert generated.needs_manual_completion is False
    assert "staff recorded a status update" not in body
    assert "request status" not in body
    assert "being processed" not in body


def test_dormitory_form_referral_excluded_from_excuse_slip(session: Session):
    office = _office(session)
    student = _user(session, role="student")
    staff = _user(session, role="office", office_id=office.id)
    ticket = _ticket_with_thread(
        session,
        office,
        student,
        staff,
        ticket_id="TKT-GQ-DORM-FP",
        question="How do I request an excuse slip?",
        staff_messages=[
            "Submit the excuse slip form and a medical certificate to OSAS "
            "within three working days of the absence.",
            "Please confirm the current dormitory form requirements with the "
            "Housing Office.",
        ],
    )

    generated = build_generated_article_from_ticket(ticket)
    body = generated.content.casefold()
    assert "excuse slip form" in body
    assert "dormitory" not in body
    assert "housing" not in body
    assert generated.needs_manual_completion is False


def test_generic_office_requirements_referral_not_confirmed(session: Session):
    office = _office(session)
    student = _user(session, role="student")
    staff = _user(session, role="office", office_id=office.id)
    referral = "Please check with the office for the latest requirements."
    ticket = _ticket_with_thread(
        session,
        office,
        student,
        staff,
        ticket_id="TKT-GQ-GENERIC-OFFICE",
        question="How do I request an excuse slip?",
        staff_messages=[
            "Submit the excuse slip form and a medical certificate to OSAS "
            "within three working days of the absence.",
            referral,
        ],
    )

    generated = build_generated_article_from_ticket(ticket)
    body = generated.content.casefold()
    assert "excuse slip form" in body
    if "where to go" in body:
        confirm = body.split("where to go", 1)[1]
        assert "latest requirements" not in confirm
    assert "ambiguous" in body or generated.needs_manual_completion is True


def test_guidance_processing_schedule_referral_excluded(session: Session):
    office = _office(session)
    student = _user(session, role="student")
    staff = _user(session, role="office", office_id=office.id)
    ticket = _ticket_with_thread(
        session,
        office,
        student,
        staff,
        ticket_id="TKT-GQ-GUIDANCE-FP",
        question="How do I request an excuse slip?",
        staff_messages=[
            "Submit the excuse slip form and a medical certificate to OSAS "
            "within three working days of the absence.",
            "Please confirm the current processing schedule with the Guidance Office.",
        ],
    )

    generated = build_generated_article_from_ticket(ticket)
    body = generated.content.casefold()
    assert "excuse slip form" in body
    assert "guidance" not in body
    assert "processing schedule" not in body
    assert generated.needs_manual_completion is False


def test_paraphrased_coe_referral_retained(session: Session):
    office = _office(session)
    student = _user(session, role="student")
    staff = _user(session, role="office", office_id=office.id)
    ticket = _ticket_with_thread(
        session,
        office,
        student,
        staff,
        ticket_id="TKT-GQ-COE-PARA",
        question="I need a COE for scholarship",
        staff_messages=[
            "Please verify the latest certificate request steps at the Registrar.",
        ],
    )

    generated = build_generated_article_from_ticket(ticket)
    body = generated.content.casefold()
    assert generated.needs_manual_completion is True
    assert "certificate" in body
    assert "registrar" in body
    assert "form 138" not in body


def test_ambiguous_referral_not_confirmed_guidance(session: Session):
    office = _office(session)
    student = _user(session, role="student")
    staff = _user(session, role="office", office_id=office.id)
    ticket = _ticket_with_thread(
        session,
        office,
        student,
        staff,
        ticket_id="TKT-GQ-AMBIG-REF",
        question="How do I claim my TOR?",
        staff_messages=[
            "Submit the TOR request form at the Registrar.",
            "Please confirm the current window assignment with the Registrar.",
        ],
    )

    generated = build_generated_article_from_ticket(ticket)
    body = generated.content.casefold()
    assert "tor request form" in body
    assert generated.needs_manual_completion is True
    if "where to go" in body:
        confirm = body.split("where to go", 1)[1].split("needs staff", 1)[0]
        assert "window assignment" not in confirm
    assert "ambiguous" in body


def test_a8_status_plus_claim_stub_requires_review(session: Session):
    office = _office(session)
    student = _user(session, role="student")
    staff = _user(session, role="office", office_id=office.id)
    message = (
        "After you submit your completed form to the Registrar we will update "
        "you once processing is complete so please keep your claim stub."
    )
    ticket = _ticket_with_thread(
        session,
        office,
        student,
        staff,
        ticket_id="TKT-GQ-A8",
        question="How do I request enrollment validation?",
        staff_messages=[message],
    )

    generated = build_generated_article_from_ticket(ticket)
    body = generated.content.casefold()
    assert "submit your completed form" in body
    assert "claim stub" in body
    assert "we will update you once processing is complete" not in body
    assert "request status" not in body
    assert generated.needs_manual_completion is False
    assert generated.generation_notes is None
    assert "needs staff completion" not in body
    if "## procedure" in body:
        procedure = body.split("## procedure", 1)[1].split("##", 1)[0]
        assert "we will update you" not in procedure
    assert "we will update you" not in generated.summary.casefold()


@pytest.mark.parametrize(
    ("ticket_id", "message", "must_keep"),
    [
        (
            "TKT-GQ-STATUS-STUB",
            "We will update you once processing is complete so please keep your claim stub.",
            "claim stub",
        ),
        (
            "TKT-GQ-STATUS-ID",
            "We will notify you when it is available so please bring your valid ID.",
            "valid id",
        ),
        (
            "TKT-GQ-STATUS-SO-REQ",
            "Your request is being processed so submit the enrollment form at the Registrar.",
            "enrollment form",
        ),
    ],
)
def test_status_plus_action_tail_keeps_evidence_without_forcing_incomplete(
    session: Session, ticket_id: str, message: str, must_keep: str
):
    office = _office(session)
    student = _user(session, role="student")
    staff = _user(session, role="office", office_id=office.id)
    ticket = _ticket_with_thread(
        session,
        office,
        student,
        staff,
        ticket_id=ticket_id,
        question="How do I request enrollment validation?",
        staff_messages=[message],
    )

    generated = build_generated_article_from_ticket(ticket)
    body = generated.content.casefold()
    assert must_keep in body
    assert "request status" not in body
    assert "we will update you" not in body
    assert "we will notify you" not in body
    assert "being processed" not in body
    if generated.needs_manual_completion:
        assert generated.generation_notes == "answer_too_short"
        assert "needs staff completion" in body
    else:
        assert generated.generation_notes is None
        assert "needs staff completion" not in body


def test_legitimate_so_instruction_without_status_stays_complete(session: Session):
    office = _office(session)
    student = _user(session, role="student")
    staff = _user(session, role="office", office_id=office.id)
    message = (
        "Submit the excuse slip form and a medical certificate to OSAS "
        "within three working days so you have a photocopy for your records."
    )
    ticket = _ticket_with_thread(
        session,
        office,
        student,
        staff,
        ticket_id="TKT-GQ-LEGIT-SO",
        question="How do I request an excuse slip?",
        staff_messages=[message],
    )

    generated = build_generated_article_from_ticket(ticket)
    assert generated.needs_manual_completion is False
    assert generated.generation_notes is None
    assert "excuse slip form" in generated.content.casefold()
    assert "needs staff completion" not in generated.content.casefold()
