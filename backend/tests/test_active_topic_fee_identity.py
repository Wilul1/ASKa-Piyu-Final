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
    # Short TOR expands via taxonomy to Transcript of Records (not prior Dropping).
    resolved = resolve_followup_question("Now tell me about TOR.", history)
    assert "drop" not in resolved.casefold()
    assert "transcript" in resolved.casefold() or "tor" in resolved.casefold()
    assert resolve_followup_question("TOR", history).casefold().startswith("transcript") or "tor" in resolve_followup_question("TOR", history).casefold()
    assert "drop" not in resolve_followup_question("Clearance", history).casefold()


@pytest.mark.parametrize(
    "question",
    [
        "TOR",
        "Enrollment",
        "Clearance",
        "Scholarship",
        "Good Moral",
    ],
)
def test_first_turn_short_service_labels_canonicalize_without_history(question):
    resolved = resolve_followup_question(question, None)
    assert resolved != question or question.casefold() in resolved.casefold()
    if question == "TOR":
        assert "transcript" in resolved.casefold()
        assert "terms of reference" not in resolved.casefold()
    elif question == "Good Moral":
        assert "good moral" in resolved.casefold()
    else:
        assert question.casefold() in resolved.casefold()


# --- Self-contained-vs-follow-up pronoun fix (QA Test #2 incident investigation) ---
#
# Read-only investigation finding: resending a long, self-contained question
# in the same chat session (e.g. after an unsatisfactory first answer) used
# to change what `resolve_followup_question` returned, because the word "it"
# (here, in "...if it cannot settle a grievance..." -- a same-sentence
# grammatical reference to "the Grievance Committee", not a backward
# reference to prior conversation) matched a blanket pronoun regex once ANY
# prior history existed. FIX: the position-based check this function already
# applied only to "that" (relative-clause "that" vs. demonstrative "that") is
# now applied uniformly to all six pronoun words -- a pronoun only counts as
# a follow-up cue when it appears within the first few words of the
# question; introduced later, it is treated as the question's own
# grammatical reference to something the sentence already established
# itself. These tests exercise the pure, offline string behavior only -- no
# Chroma, embedding, HTTP, database, or LLM call -- and do not reproduce or
# depend on any real production user question/answer; this question text is
# a synthetic test shape, not logged production content.

GRIEVANCE_FOLLOWUP_PRONOUN_QUESTION = (
    "Under the LSPU Student Handbook's Student Internship Program grievance "
    "procedure, who makes up the university-level Grievance Committee, what "
    "is its initial responsibility, and what happens if it cannot settle a "
    "grievance or render a decision?"
)


def test_grievance_question_with_empty_history_is_not_treated_as_a_followup():
    for empty_history in (None, []):
        resolved = resolve_followup_question(GRIEVANCE_FOLLOWUP_PRONOUN_QUESTION, empty_history)
        assert "Prior question context:" not in resolved
        assert resolved.startswith(GRIEVANCE_FOLLOWUP_PRONOUN_QUESTION)


def test_same_grievance_question_resent_with_one_prior_turn_is_left_unchanged():
    # Scenario 3 (fixed): the SAME question was already asked once in this
    # session (and produced some prior answer), and is now being sent again.
    # Before the fix, this appended a truncated copy of the question's own
    # prior occurrence as "prior context." The late, same-sentence "it" is
    # no longer treated as a follow-up cue, so nothing is appended.
    history = _history(
        (
            GRIEVANCE_FOLLOWUP_PRONOUN_QUESTION,
            "The indexed LSPU documents do not contain enough information about this topic.",
        ),
    )
    resolved = resolve_followup_question(GRIEVANCE_FOLLOWUP_PRONOUN_QUESTION, history)
    assert resolved == GRIEVANCE_FOLLOWUP_PRONOUN_QUESTION
    assert "Prior question context:" not in resolved


def test_grievance_question_after_unrelated_prior_turn_is_left_unchanged():
    # Scenario 2 (fixed): the self-contained grievance question is asked
    # right after a completely unrelated prior exchange (same session,
    # different topic). Before the fix, the unrelated TOR-fee topic was
    # grafted on. Now the question is self-contained enough (long, no
    # followup_prefix, no early pronoun) to stand on its own.
    history = _history(
        (
            "What is the TOR fee per page for undergraduate students?",
            "The TOR fee is PHP 20.00 per page for undergraduate students.",
        ),
    )
    resolved = resolve_followup_question(GRIEVANCE_FOLLOWUP_PRONOUN_QUESTION, history)
    assert resolved == GRIEVANCE_FOLLOWUP_PRONOUN_QUESTION
    assert "Prior question context:" not in resolved


def test_genuine_pronoun_followup_after_grievance_topic_retains_identifiable_context():
    # Scenario 4: a short, genuinely context-dependent follow-up -- "it" is
    # the SECOND word, well within the early-position window, and has no
    # referent at all without the prior turn. Must still resolve correctly
    # after the fix: the fix narrows which pronouns count, it does not
    # disable follow-up resolution for genuine cases.
    history = _history(
        (
            "Under the LSPU Student Handbook, what is the Student Internship "
            "Program grievance procedure?",
            "A university-level Grievance Committee reviews unresolved complaints.",
        ),
    )
    followup = "What happens if it cannot be settled?"
    resolved = resolve_followup_question(followup, history)
    assert "Prior question context:" in resolved
    prior = resolved.split("Prior question context:")[-1]
    assert "grievance" in prior.casefold()


@pytest.mark.parametrize(
    "followup",
    [
        "What about this?",
        "Are those required too?",
        "Do them need to sign?",
        "Is there a deadline?",
        "Is it the same for faculty?",
    ],
)
def test_genuine_short_followups_with_each_pronoun_still_resolve(followup):
    # Scenario 5: every other pronoun the resolver recognizes ("this",
    # "those", "them", "there", "same", and "it" again in combination),
    # used exactly as a short genuine follow-up (pronoun in the first few
    # words, no referent of its own) -- confirms the fix's position check
    # does not accidentally disable these just for introducing the same
    # positional rule "that" already had.
    history = _history(
        ("How do I get a Good Moral Certificate?", "Submit a request form to the Registrar."),
    )
    resolved = resolve_followup_question(followup, history)
    assert "Prior question context:" in resolved
    prior = resolved.split("Prior question context:")[-1]
    assert "good moral" in prior.casefold()


def test_pronoun_free_short_followup_still_depends_on_earlier_topic():
    # Scenario 6: the existing `short_followup` mechanism (length <= 8 words,
    # not standalone, does not name its own service/subject) already
    # supports a follow-up with NO pronoun at all -- this fix only changes
    # pronoun handling and must not regress this independent, pre-existing
    # path.
    history = _history(
        ("How do I get a Good Moral Certificate?", "Submit a request form to the Registrar."),
    )
    resolved = resolve_followup_question("What are the requirements?", history)
    assert "Prior question context:" in resolved
    prior = resolved.split("Prior question context:")[-1]
    assert "good moral" in prior.casefold()


# --- Independent near-exact-repeat guard (deeper, more robust investigation) ---
#
# The pronoun-position fix above only accidentally avoided the self-quote bug
# for the specific grievance question, because its "it" happens to sit deep
# in that one long sentence. It does NOT generalize: a SHORT or MEDIUM
# repeated question whose pronoun happens to fall within the first few words
# still triggered `resolve_active_topic` to return that same prior turn's
# own text, truncated, as "prior context" -- a self-quote. FIX: an explicit,
# independent check -- is the current question a near-exact repeat (case/
# whitespace/trailing-punctuation-insensitive only, no fuzzy matching) of the
# user's own immediately preceding message? -- runs before any pronoun/
# follow-up-cue evaluation at all, so it protects every repeat regardless of
# length or where a pronoun happens to sit.


@pytest.mark.parametrize(
    "question",
    [
        "How much does it cost to file a leave of absence request?",
        "Is it possible to appeal if it is rejected by the committee?",
    ],
)
def test_short_or_medium_question_repeated_verbatim_is_left_unchanged(question):
    # Confirmed gap in the pronoun-position-only fix: both of these have an
    # early pronoun (position <= 3), so the position check alone still
    # treated a verbatim repeat of either as needing "resolution" against
    # itself. The repeat guard fixes this independently of pronoun position.
    history = _history(
        (question, "The indexed LSPU documents do not contain enough information about this topic."),
    )
    resolved = resolve_followup_question(question, history)
    assert resolved == question
    assert "Prior question context:" not in resolved


def test_repeat_guard_does_not_fire_for_a_genuinely_different_short_question():
    # The repeat guard is exact-match only (ignoring case/whitespace/trailing
    # punctuation) -- it must never suppress a genuine follow-up merely
    # because it shares wording with the prior turn. (The prior turn here
    # must itself set a real, resolvable topic -- a slot question like "How
    # much does it cost?" has none of its own, which would make this test
    # fail for an unrelated reason.)
    history = _history(
        ("How do I get a Good Moral Certificate?", "Submit a request form to the Registrar."),
    )
    resolved = resolve_followup_question("How long does it take?", history)
    assert "Prior question context:" in resolved
    prior = resolved.split("Prior question context:")[-1]
    assert "good moral" in prior.casefold()


def test_followup_after_intervening_unrelated_exchange_still_uses_the_newer_topic():
    # Pre-existing, intentional behavior (documented in resolve_active_topic's
    # own docstring: "Topic A -> Topic B -> follow-up resolves against B
    # only") -- confirmed still intact after both fixes. This is not a
    # "clarify instead of guess" case: the user explicitly switched topics,
    # so assuming the follow-up is about the newest topic is the documented,
    # correct behavior, not an ambiguous one.
    history = _history(
        (
            "Under the LSPU Student Handbook, what is the Student Internship "
            "Program grievance procedure?",
            "A university-level Grievance Committee reviews unresolved complaints.",
        ),
        ("What is the TOR fee per page?", "PHP 20.00 per page."),
    )
    resolved = resolve_followup_question("How much does it cost?", history)
    assert "Prior question context:" in resolved
    prior = resolved.split("Prior question context:")[-1].casefold()
    assert "tor" in prior or "fee" in prior
    assert "grievance" not in prior


def test_ambiguous_prior_turn_with_no_real_topic_is_not_reliably_avoided():
    """Documents a REMAINING, UNRESOLVED gap found during this investigation,
    not a guarantee: when the only prior user turn is a bare greeting with no
    real topic ("hello"), `resolve_active_topic` currently has no dedicated
    signal distinguishing "no usable topic exists" from "the topic IS the
    literal text of that turn" -- it is not recognized as a vague/slot
    question by `_is_underspecified_question`, so it is returned and
    attached as if it were a real topic. An attempted fix (reject a resolved
    topic with fewer than 2 content words) was tried and reverted after it
    broke legitimate single-word topic labels like "Clearance" -- see the
    production-code comment history / investigation report. This test
    pins down CURRENT behavior so a future, better-scoped fix has a
    regression baseline, and documents that "avoid confidently attaching
    unrelated history" is not yet achieved for this specific shape."""
    history = _history(("hello", "Hi! How can I help?"))
    resolved = resolve_followup_question("What about it?", history)
    assert "Prior question context: hello" in resolved


def test_tor_short_label_canonicalizes_to_transcript_of_records():
    from app.services.qa.question_answering import _canonical_service_retrieval_phrase

    phrase = _canonical_service_retrieval_phrase("Now tell me about TOR.")
    assert phrase is not None
    assert "transcript" in phrase.casefold()
    assert "terms of reference" not in phrase.casefold()
    active = resolve_active_topic(
        _history(
            ("How do I drop a subject?", "Dropping"),
            ("Now tell me about TOR.", "About TOR"),
        )
    )
    assert "transcript" in active.casefold()
    assert "drop" not in active.casefold()


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
