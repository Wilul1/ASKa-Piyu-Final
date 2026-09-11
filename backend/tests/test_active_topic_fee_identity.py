"""Active-topic identity + fee-recovery regression matrix (BUG-R1 / BUG-R2 / STRESS)."""

from __future__ import annotations

import pytest

from app.services.chroma_store import RetrievedChunk
from app.services.qa.groq_answer_service import build_groq_messages
from app.services.qa.question_answering import (
    _prefer_active_topic_context,
    _prefer_structured_fee_recovery,
    _recover_factual_charter_answer,
    _service_matches_active_topic,
    _should_prefer_recovered_factual,
    resolve_active_topic,
    resolve_followup_question,
    resolve_turn_active_topic,
)


def _chunk(
    title: str,
    *,
    fees: str | None = None,
    text: str = "",
    score: float = 0.9,
    requirements: str | None = None,
    processing_time: str | None = None,
) -> RetrievedChunk:
    metadata: dict = {
        "source_section": title,
        "canonical_topic": title,
        "document_type": "citizen_charter_service",
    }
    if fees is not None:
        metadata["total_fees"] = fees
    if requirements is not None:
        metadata["requirements"] = requirements
        metadata["client_steps"] = requirements
    if processing_time is not None:
        metadata["total_processing_time"] = processing_time
    return RetrievedChunk(
        document_id="doc-1",
        title=title,
        source_filename="charter.pdf",
        chunk_index=0,
        text=text or f"{title}. {fees or ''}",
        relevance_score=score,
        metadata=metadata,
    )


def _history(*pairs: tuple[str, str]) -> list[dict[str, str]]:
    turns: list[dict[str, str]] = []
    for user, assistant in pairs:
        turns.append({"role": "user", "content": user})
        turns.append({"role": "assistant", "content": assistant})
    return turns


# ---------------------------------------------------------------------------
# Active topic resolution
# ---------------------------------------------------------------------------


def test_resolve_active_topic_skips_slot_followups():
    history = _history(
        ("How do I get a Good Moral Certificate?", "About Good Moral Certificate…"),
        ("What are the requirements?", "Bring ID and clearance."),
        ("Where do I submit them?", "Submit to OSA."),
    )
    assert "good moral" in resolve_active_topic(history).casefold()
    assert "submit" not in resolve_active_topic(history).casefold()


def test_resolve_active_topic_switches_and_keeps_new_topic():
    history = _history(
        ("How do I get a Good Moral Certificate?", "Good Moral Certificate steps."),
        ("Now tell me about dropping a subject.", "Dropping of Subjects procedure."),
    )
    active = resolve_active_topic(history)
    assert "dropping" in active.casefold()
    assert "good moral" not in active.casefold()


@pytest.mark.parametrize(
    "switch",
    [
        "Now tell me about TOR.",
        "TOR",
        "Enrollment",
        "Clearance",
        "Scholarship",
        "Good Moral",
        "What about Clearance?",
    ],
)
def test_short_explicit_topic_switch_becomes_active(switch):
    history = _history(
        ("How do I drop a subject?", "Dropping overview."),
        (switch, f"Answer about {switch}"),
    )
    active = resolve_active_topic(history)
    markers = [
        tok
        for tok in switch.casefold().replace(".", "").replace("?", "").split()
        if len(tok) >= 3 and tok not in {"now", "tell", "about", "what"}
    ]
    assert any(tok in active.casefold() for tok in markers), active
    assert "drop" not in active.casefold()


@pytest.mark.parametrize(
    ("topic_a", "topic_b", "followup", "b_marker", "a_marker"),
    [
        (
            "How do I drop a subject?",
            "Now tell me about TOR.",
            "How much does it cost?",
            "tor",
            "drop",
        ),
        (
            "How do I enroll as a new student at LSPU?",
            "Now tell me about TOR.",
            "Where do I submit it?",
            "tor",
            "enroll",
        ),
        (
            "How can I request my TOR?",
            "Enrollment",
            "What are the requirements?",
            "enrollment",
            "tor",
        ),
        (
            "How do I get a Good Moral Certificate?",
            "Clearance",
            "How much does it cost?",
            "clearance",
            "good moral",
        ),
        (
            "How do I enroll as a new student?",
            "Scholarship",
            "What are the requirements?",
            "scholarship",
            "enroll",
        ),
    ],
)
def test_short_switch_followup_uses_topic_b_only(topic_a, topic_b, followup, b_marker, a_marker):
    history = _history(
        (topic_a, f"Answer about {topic_a}"),
        (topic_b, f"Answer about {topic_b}"),
    )
    assert b_marker in resolve_active_topic(history).casefold()
    assert a_marker not in resolve_active_topic(history).casefold()
    resolved = resolve_followup_question(followup, history)
    prior = resolved.split("Prior question context:")[-1].casefold()
    assert b_marker in prior
    assert a_marker not in prior


def test_multi_switch_chain_ends_on_enrollment_requirements():
    history = _history(
        ("How do I get a Good Moral Certificate?", "GM"),
        ("Now tell me about TOR.", "TOR"),
        ("Enrollment", "Enrollment overview"),
    )
    active = resolve_active_topic(history)
    assert "enrollment" in active.casefold()
    assert "tor" not in active.casefold()
    assert "good moral" not in active.casefold()
    resolved = resolve_followup_question("What are the requirements?", history)
    prior = resolved.split("Prior question context:")[-1].casefold()
    assert "enrollment" in prior
    assert "tor" not in prior
    assert "good moral" not in prior


def test_switch_back_to_good_moral_for_requirements():
    history = _history(
        ("How do I get a Good Moral Certificate?", "GM"),
        ("Enrollment", "Enrollment"),
        ("Good Moral", "Back to Good Moral"),
    )
    active = resolve_active_topic(history)
    assert "good moral" in active.casefold()
    assert "enrollment" not in active.casefold()
    resolved = resolve_followup_question("What are the requirements?", history)
    prior = resolved.split("Prior question context:")[-1].casefold()
    assert "good moral" in prior
    assert "enrollment" not in prior


def test_topic_setting_turn_does_not_inherit_prior_topic():
    history = _history(("How do I drop a subject?", "Dropping"))
    assert resolve_followup_question("Now tell me about TOR.", history) == "Now tell me about TOR."
    assert resolve_followup_question("TOR", history) == "TOR"
    assert "drop" not in resolve_followup_question("Clearance", history).casefold()


@pytest.mark.parametrize(
    ("topic_a", "topic_b", "followup"),
    [
        (
            "How do I get a Good Moral Certificate?",
            "Now tell me about dropping a subject.",
            "What are the requirements?",
        ),
        (
            "How can I request my TOR?",
            "How do I enroll as a new student at LSPU?",
            "What are the requirements?",
        ),
        (
            "How do I enroll as a new student at LSPU?",
            "How do I get a Good Moral Certificate?",
            "Where do I submit them?",
        ),
        (
            "How do I drop a subject this semester?",
            "How can I request my Transcript of Records?",
            "How much does it cost?",
        ),
    ],
)
def test_followup_after_topic_switch_uses_topic_b_only(topic_a, topic_b, followup):
    history = _history(
        (topic_a, f"Answer about {topic_a}"),
        (topic_b, f"Answer about {topic_b}"),
    )
    resolved = resolve_followup_question(followup, history)
    prior = resolved.split("Prior question context:")[-1].casefold()
    b_tokens = {
        t
        for t in topic_b.casefold().replace("?", "").split()
        if len(t) >= 4 and t not in {"about", "tell", "does", "have", "this", "semester"}
    }
    assert any(tok in prior for tok in b_tokens), resolved
    # Older topic must not remain the active prior context.
    a_markers = []
    if "good moral" in topic_a.casefold():
        a_markers.append("good moral")
    if "tor" in topic_a.casefold() or "transcript" in topic_a.casefold():
        a_markers.extend(["tor", "transcript"])
    if "enroll" in topic_a.casefold():
        a_markers.append("enroll")
    if "drop" in topic_a.casefold():
        a_markers.append("drop")
    for marker in a_markers:
        if marker in topic_b.casefold():
            continue
        assert marker not in prior, resolved


def test_topic_a_multiple_followups_then_topic_b_followup():
    history = _history(
        ("How do I get a Good Moral Certificate?", "Good Moral overview."),
        ("What are the requirements?", "Good Moral requirements."),
        ("Where do I submit them?", "Submit Good Moral docs."),
        ("Now tell me about dropping a subject.", "Dropping overview."),
    )
    resolved = resolve_followup_question("What are the requirements?", history)
    prior = resolved.split("Prior question context:")[-1].casefold()
    assert "dropping" in prior
    assert "good moral" not in prior


def test_answer_framing_prompt_includes_active_topic():
    messages = build_groq_messages(
        question="Where do I submit it? regarding Now tell me about Good Moral.",
        context="Title: Issuance of Good Moral Certificate\nContent: Submit to OSA.",
        history=[
            {"role": "user", "content": "How do I enroll?"},
            {"role": "assistant", "content": "Enrollment is at the Registrar."},
            {"role": "user", "content": "Now tell me about Good Moral."},
            {"role": "assistant", "content": "Good Moral Certificate overview."},
        ],
        active_topic="Now tell me about Good Moral.",
    )
    system = messages[0]["content"]
    user = messages[-1]["content"]
    assert "Active conversational service/topic" in system
    assert "Good Moral" in system
    assert "Active service/topic for this turn: Now tell me about Good Moral." in user
    assert "Ignore stale fees, offices, requirements, or wording from earlier topics" in user


def test_prefer_active_topic_context_drops_unrelated_service_chunks():
    enrollment = _chunk("Enrollment", processing_time="1 day", score=0.5)
    tor = _chunk(
        "Issuance of Transcript of Records for Graduate Students",
        processing_time="7 days",
        score=0.99,
    )
    preferred = _prefer_active_topic_context(
        [tor, enrollment],
        "How do I enroll as a new student?",
    )
    titles = {str((c.metadata or {}).get("source_section") or c.title) for c in preferred}
    assert "Enrollment" in titles
    assert not any("transcript" in t.casefold() for t in titles)


def test_tor_alias_matches_transcript_title():
    assert _service_matches_active_topic(
        "Issuance of Transcript of Records/Transfer Credentials/Certifications/CAV",
        {"tor"},
    )
    assert not _service_matches_active_topic("Dropping of Subjects", {"tor"})


def test_resolve_turn_active_topic_uses_current_short_switch():
    history = _history(("How do I drop a subject?", "Dropping"))
    assert "tor" in resolve_turn_active_topic("Now tell me about TOR.", history).casefold()
    assert "drop" in resolve_turn_active_topic("How much does it cost?", history).casefold()


# ---------------------------------------------------------------------------
# Fee recovery: service identity compatibility
# ---------------------------------------------------------------------------


def test_fee_recovery_rejects_enrollment_fee_for_good_moral_topic():
    """BUG-R1: active Good Moral topic must not borrow Enrollment fees."""
    enrollment = _chunk(
        "Enrollment",
        fees="Form. 3",
        text="Enrollment fees Form. 3",
        score=0.99,
    )
    good_moral = _chunk(
        "Issuance of Good Moral Certificate (Undergraduate)",
        fees=None,
        text="Issuance of Good Moral Certificate. No fee listed.",
        score=0.7,
    )
    question = (
        "How much does it cost? regarding How do I get a Good Moral Certificate?"
    )
    recovered = _recover_factual_charter_answer(
        question,
        [enrollment, good_moral],
        sources=[{"title": "Citizen Charter", "path": "charter.pdf"}],
    )
    assert recovered is None
    llm = "The available sources do not specify a fee for the Good Moral Certificate."
    assert _should_prefer_recovered_factual(question, llm) is False
    assert _prefer_structured_fee_recovery(
        question,
        "The listed fee for Enrollment is Form. 3 (Citizen Charter).",
        llm,
    ) is False


@pytest.mark.parametrize(
    ("topic_question", "matching_title", "matching_fee", "intruder_title", "intruder_fee"),
    [
        (
            "How do I get a Good Moral Certificate?",
            "Issuance of Good Moral Certificate (Undergraduate)",
            None,
            "Enrollment",
            "Form. 3",
        ),
        (
            "How can I request my Transcript of Records?",
            "Issuance of Transcript of Records/Transfer Credentials/Certifications/CAV",
            "Undergraduate: P75.00/page",
            "Library Reference Assistance",
            "P50.00/hour",
        ),
        (
            "How do I enroll as a new student?",
            "Enrollment",
            "Form. 3",
            "Issuance of Good Moral Certificate (Undergraduate)",
            "P100.00",
        ),
        (
            "Now tell me about TOR.",
            "Issuance of Transcript of Records/Transfer Credentials/Certifications/CAV",
            "Undergraduate: P75.00/page",
            "Dropping of Subjects",
            "P30.00/unit",
        ),
        (
            "Clearance",
            "Student Clearance",
            "None",
            "Issuance of Transcript of Records for Foreign Students",
            "P200.00",
        ),
        (
            "How do I drop a subject?",
            "Dropping of Subjects",
            "P30.00/unit",
            "Enrollment",
            "Form. 3",
        ),
    ],
)
def test_fee_recovery_keeps_topic_service_identity(
    topic_question,
    matching_title,
    matching_fee,
    intruder_title,
    intruder_fee,
):
    matching = _chunk(matching_title, fees=matching_fee, score=0.6)
    intruder = _chunk(intruder_title, fees=intruder_fee, score=0.99)
    question = f"How much does it cost? regarding {topic_question}"
    recovered = _recover_factual_charter_answer(
        question,
        [intruder, matching],
        sources=[{"title": "Citizen Charter", "path": "charter.pdf"}],
    )
    if matching_fee and matching_fee.casefold() != "none":
        assert recovered is not None
        assert matching_title.split("(")[0].strip().casefold().split()[0] in recovered.casefold() or any(
            tok in recovered.casefold()
            for tok in matching_title.casefold().split()
            if len(tok) > 4
        )
        # Intruder service title must not be the answered fee owner.
        assert intruder_title.casefold() not in recovered.casefold()
        assert intruder_fee.casefold() not in recovered.casefold()
    elif matching_fee and matching_fee.casefold() == "none":
        # Explicit none fee may or may not be recovered; never the intruder.
        if recovered:
            assert intruder_fee.casefold() not in recovered.casefold()
            assert "foreign" not in recovered.casefold()
    else:
        assert recovered is None


def test_fee_isolation_matrix_rejects_cross_service_fees():
    services = [
        ("How do I get a Good Moral Certificate?", "Issuance of Good Moral Certificate (Undergraduate)", None),
        (
            "Now tell me about TOR.",
            "Issuance of Transcript of Records/Transfer Credentials/Certifications/CAV",
            "P75.00/page",
        ),
        ("Enrollment", "Enrollment", "Form. 3"),
        ("How do I drop a subject?", "Dropping of Subjects", "P30.00/unit"),
        ("Clearance", "Student Clearance", None),
    ]
    for topic, title, fee in services:
        own = _chunk(title, fees=fee, score=0.5)
        for other_topic, other_title, other_fee in services:
            if other_title == title or not other_fee:
                continue
            intruder = _chunk(other_title, fees=other_fee, score=0.99)
            question = f"How much does it cost? regarding {topic}"
            recovered = _recover_factual_charter_answer(
                question,
                [intruder, own],
                sources=[{"title": "Citizen Charter", "path": "charter.pdf"}],
            )
            if recovered and other_fee:
                assert other_fee.casefold() not in recovered.casefold(), (topic, other_title, recovered)


def test_duration_recovery_keeps_enrollment_not_graduate_tor():
    enrollment = _chunk("Enrollment", processing_time="1 day", score=0.6)
    graduate_tor = _chunk(
        "Issuance of Transcript of Records for Graduate Students",
        processing_time="7 working days",
        score=0.99,
    )
    question = "How long does it take? regarding How do I enroll as a new student?"
    recovered = _recover_factual_charter_answer(
        question,
        [graduate_tor, enrollment],
        sources=[{"title": "Citizen Charter", "path": "charter.pdf"}],
    )
    assert recovered is not None
    assert "enrollment" in recovered.casefold()
    assert "graduate" not in recovered.casefold()
    assert "transcript" not in recovered.casefold()


def test_fee_recovery_without_topic_does_not_pick_arbitrary_service():
    enrollment = _chunk("Enrollment", fees="Form. 3", score=0.99)
    library = _chunk("Library Reference Assistance", fees="P50.00/hour", score=0.98)
    recovered = _recover_factual_charter_answer(
        "How much does it cost?",
        [enrollment, library],
        sources=[{"title": "Citizen Charter", "path": "charter.pdf"}],
    )
    assert recovered is None


def test_requirements_recovery_after_switch_uses_dropping_not_good_moral():
    dropping = _chunk(
        "Dropping of Subjects",
        text=(
            "Dropping of Subjects\n"
            "Requirements:\n"
            "- Dropping Form from the Registrar\n"
            "- Approval of instructor\n"
        ),
        score=0.8,
    )
    alumni = _chunk(
        "Issuance of Good Moral Certificate (LSPU Alumni)",
        text=(
            "Issuance of Good Moral Certificate (LSPU Alumni)\n"
            "Requirements:\n"
            "- Transcript of Record (TOR)\n"
            "- Student ID\n"
        ),
        score=0.95,
    )
    question = (
        "What are the requirements? regarding Now tell me about dropping a subject."
    )
    recovered = _recover_factual_charter_answer(
        question,
        [alumni, dropping],
        sources=[{"title": "Citizen Charter", "path": "charter.pdf"}],
    )
    # Must not answer with the older Good Moral Alumni service.
    if recovered:
        assert "alumni" not in recovered.casefold()
        assert "good moral" not in recovered.casefold()
        assert "drop" in recovered.casefold() or "dropping" in recovered.casefold()
    else:
        from app.services.qa.question_answering import _fee_topic_tokens

        tokens = _fee_topic_tokens(question)
        assert _service_matches_active_topic("Dropping of Subjects", tokens)
        assert not _service_matches_active_topic(
            "Issuance of Good Moral Certificate (LSPU Alumni)", tokens
        )
