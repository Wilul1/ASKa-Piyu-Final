"""Active-topic identity + fee-recovery regression matrix (BUG-R1 / BUG-R2)."""

from __future__ import annotations

import pytest

from app.services.chroma_store import RetrievedChunk
from app.services.qa.question_answering import (
    _prefer_structured_fee_recovery,
    _recover_factual_charter_answer,
    _should_prefer_recovered_factual,
    resolve_active_topic,
    resolve_followup_question,
)


def _chunk(
    title: str,
    *,
    fees: str | None = None,
    text: str = "",
    score: float = 0.9,
    requirements: str | None = None,
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
    if matching_fee:
        assert recovered is not None
        assert matching_title.split("(")[0].strip().casefold().split()[0] in recovered.casefold() or any(
            tok in recovered.casefold()
            for tok in matching_title.casefold().split()
            if len(tok) > 4
        )
        # Intruder service title must not be the answered fee owner.
        assert intruder_title.casefold() not in recovered.casefold()
        assert intruder_fee.casefold() not in recovered.casefold()
    else:
        assert recovered is None


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
        # If structured requirements extraction finds nothing, identity gate still
        # forbids the alumni card from winning — assert explicitly.
        from app.services.qa.question_answering import _service_matches_active_topic, _fee_topic_tokens

        tokens = _fee_topic_tokens(question)
        assert _service_matches_active_topic("Dropping of Subjects", tokens)
        assert not _service_matches_active_topic(
            "Issuance of Good Moral Certificate (LSPU Alumni)", tokens
        )
