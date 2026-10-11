"""Regression tests for the synchronous, fail-closed grounding gate
(_answer_has_ungrounded_claim / INSUFFICIENT_GROUNDING_ANSWER,
app/services/qa/question_answering.py).

Motivating incident: a production answer stated a specific overload limit
("six units or two subjects") for graduating students even though no
retrieved chunk supported that figure. The async citation verifier
(citation_verification.py / citation_verification_jobs.py) could not have
prevented this -- it only ever runs AFTER the /qa/ask response has already
been sent (FastAPI BackgroundTasks). This gate runs synchronously, before
any eligible branch returns, and replaces the answer outright when a
material claim has no lexical/numeric connection to anything retrieved.

Deliberately NOT a single aggregate score against the whole answer: that
would let one well-supported sentence mask a separate, unsupported
numerical/policy claim elsewhere in the same answer -- the exact mistake
this gate exists to avoid. See _answer_has_ungrounded_claim's own
docstring for the full rationale and its documented limitation (lexical/
numeric overlap is a heuristic, not semantic entailment -- it is not proof
against hallucination, and both false positives and false negatives are
possible and are tested for below where feasible with the existing
pure-Python helpers).
"""

from unittest.mock import patch

from app.config import settings
from app.services.chroma_store import RetrievedChunk
from app.services.qa.question_answering import (
    GREETING_ANSWER,
    INSUFFICIENT_GROUNDING_ANSWER,
    OUT_OF_SCOPE_ANSWER,
    _answer_has_ungrounded_claim,
    _non_hedge_claim_parts,
    answer_qa_question,
)

from tests.test_qa_facet_coverage_caveats import FacetAwareFakeStore
from tests.test_qa_question_answering import chunk

TOR_CHUNK = chunk(
    "TOR Fees",
    "The Transcript of Records (TOR) fee is PHP 20.00 per page for undergraduate students.",
)

SINGLE_TOPIC_QUESTION = "What is the TOR fee per page for undergraduate students?"


# --- Part 1: direct unit tests of the pure gate function ---------------------


def test_gate_is_noop_with_no_candidates():
    assert _answer_has_ungrounded_claim("The TOR fee is PHP 20.00 per page.", []) is False


def test_gate_is_noop_for_an_answer_with_no_claim_sized_spans():
    # Too short/trivial to split into a claim at all (see _answer_claims) --
    # conservatively treated as nothing extra to check.
    assert _answer_has_ungrounded_claim("", [TOR_CHUNK]) is False


def test_gate_passes_a_well_supported_single_claim():
    answer = "The Transcript of Records (TOR) fee is PHP 20.00 per page for undergraduate students."
    assert _answer_has_ungrounded_claim(answer, [TOR_CHUNK]) is False


def test_gate_flags_a_claim_with_zero_overlap_with_anything_retrieved():
    answer = "The Landbank LinkBiz processing fee is PHP 25.00 per transaction."
    assert _answer_has_ungrounded_claim(answer, [TOR_CHUNK]) is True


def test_gate_flags_a_mixed_answer_even_though_one_claim_is_well_supported():
    """The core correctness requirement: one strongly-supported claim must
    never mask a separate, unsupported numerical/policy claim."""
    answer = (
        "The TOR fee is PHP 20.00 per page for undergraduate students. "
        "The Landbank LinkBiz processing fee is PHP 25.00 per transaction."
    )
    assert _answer_has_ungrounded_claim(answer, [TOR_CHUNK]) is True


def test_gate_passes_a_mixed_answer_when_every_claim_has_its_own_support():
    other_chunk = chunk(
        "Enrollment Clearance",
        "Enrollment clearance requires the Accounting Office and OSAS Student ID.",
        score=0.82,
    )
    answer = (
        "The TOR fee is PHP 20.00 per page for undergraduate students. "
        "Enrollment clearance requires the Accounting Office and OSAS Student ID."
    )
    assert _answer_has_ungrounded_claim(answer, [TOR_CHUNK, other_chunk]) is False


# --- Part 1b: fix for the no-terminal-punctuation bypass ---------------------
#
# _answer_claims() discards a split fragment identical to the whole (stripped)
# answer -- correct for _select_supporting_context, which scores the whole
# answer separately anyway, but when an answer is one undivided clause with
# NO delimiter at all (no trailing period), that is the ONLY fragment
# splitting ever produces, so _answer_claims() returned [] and the gate
# previously returned False unconditionally -- a single, confidently-stated,
# unsupported sentence (exactly the real incident's shape) slipped through
# untested merely for lacking a trailing period. See
# _answer_has_ungrounded_claim's docstring for the fallback that fixes this.


def test_gate_flags_an_unsupported_single_claim_with_no_terminal_punctuation():
    answer = "Graduating students may overload up to six units or two subjects with approval"
    assert "." not in answer
    assert _answer_has_ungrounded_claim(answer, [TOR_CHUNK]) is True


def test_gate_flags_the_same_unsupported_claim_with_terminal_punctuation_too():
    # Symmetric check: adding the period back must not change the verdict --
    # confirms the fix did not just special-case the punctuation-free form.
    answer = "Graduating students may overload up to six units or two subjects with approval."
    assert _answer_has_ungrounded_claim(answer, [TOR_CHUNK]) is True


def test_gate_passes_a_supported_single_claim_with_no_terminal_punctuation():
    answer = "The Transcript of Records (TOR) fee is PHP 20.00 per page for undergraduate students"
    assert not answer.endswith((".", "!", "?"))
    assert _answer_has_ungrounded_claim(answer, [TOR_CHUNK]) is False


# --- Part 1c: narrowing the uncertainty-phrase exemption ---------------------
#
# _non_hedge_claim_parts() must not let a hedge phrase ("not mentioned",
# "does not clearly specify", ...) blanket-exempt a whole claim-sized span
# when a separate, smuggled-in factual assertion rides along in the same
# span (no real sentence boundary between them, just a comma). Covers both
# the numeric shape (a specific figure) and the non-numeric shape (a named
# requirement/document/office) -- see _non_hedge_claim_parts's own
# docstring for the comma/semicolon + conjunction split this relies on, and
# its documented limitation (only that one boundary shape is recognized).


def test_gate_flags_an_unsupported_numeric_claim_smuggled_alongside_a_hedge_phrase():
    answer = "The requirement is not mentioned elsewhere, and the fee is P500."
    assert _answer_has_ungrounded_claim(answer, [TOR_CHUNK]) is True


def test_gate_flags_an_unsupported_non_numeric_claim_smuggled_alongside_a_hedge_phrase():
    # The exact previously-confirmed bypass: no number anywhere, so the old
    # number-only check would have exempted this whole span even though the
    # "all transferees must submit..." clause is a separate, unsupported,
    # non-numeric factual assertion riding along with the honest "not
    # mentioned" admission about something else.
    answer = (
        "The policy is not mentioned elsewhere, but all transferees must "
        "submit a certificate of eligibility from their previous school."
    )
    assert _answer_has_ungrounded_claim(answer, [TOR_CHUNK]) is True


def test_gate_passes_a_standalone_honest_uncertainty_statement_with_no_number():
    # The exemption this fix narrows, not removes: a hedge phrase with no
    # coordinating-conjunction boundary and no accompanying number -- the
    # shape every real template in this module actually produces -- must
    # still be exempt, not forced through the fixed refusal on top of its
    # own honest wording.
    answer = "The cited source does not clearly specify a fee for Enrollment."
    assert _answer_has_ungrounded_claim(answer, [TOR_CHUNK]) is False


# --- Part 1d: a hedge phrase used in its ORDINARY sense inside the factual --
# remainder itself must not discard that remainder ---------------------------
#
# Confirmed bypass this closes: an earlier version dropped a whole split
# part merely for *containing* a phrase from _NON_FACTUAL_CLAIM_PHRASES --
# including a part where that phrase (e.g. "could not find") is used
# literally, in an unrelated sentence that also states a separate,
# unsupported assertion. _resolve_hedge_segment (see its docstring) now
# recursively tries a looser, comma-free conjunction split specifically on a
# segment that already matched a hedge phrase, isolating the hedge wording
# from whatever is actually attached to it -- this works for both a numeric
# remainder (this test) and a non-numeric one (the next section), not just
# the numeric case the very first fix for this covered.


def test_gate_flags_a_numeric_fact_smuggled_inside_a_part_that_also_uses_a_hedge_phrase_literally():
    # The exact reported regression: "could not find the office" is an
    # ordinary description of a navigation problem, not an admission of
    # missing information, but it shares a claim-sized span with "must pay
    # P500" -- an unrelated, unsupported fee assertion that must not be
    # discarded merely because the phrase "could not find" is also present.
    answer = (
        "The policy is not mentioned elsewhere, but students could not find "
        "the office without a map and must pay P500."
    )
    assert _answer_has_ungrounded_claim(answer, [TOR_CHUNK]) is True


# --- Part 1e: semicolon split boundary must not corrupt the following word --
#
# _non_hedge_claim_parts (via _HEDGE_CLAUSE_SPLIT_RE) is unit-tested directly
# here rather than through _answer_has_ungrounded_claim / a full answer:
# _CLAIM_SPLIT_RE (the OUTER sentence/clause split in _answer_claims) already
# splits on every semicolon unconditionally, so by the time a per-claim string
# ever reaches _non_hedge_claim_parts through the real gate, it cannot still
# contain one -- the semicolon branch of _HEDGE_CLAUSE_SPLIT_RE is reachable
# only via a direct call to _non_hedge_claim_parts, not through today's
# end-to-end gate. It is still fixed and tested at that level: another caller
# or a future change to _answer_claims could exercise it, and the previous,
# unguarded version actively corrupted text when it was reachable.


def test_gate_flags_a_non_numeric_fact_smuggled_inside_a_part_that_also_uses_a_hedge_phrase_literally():
    # The regression this round's fix closes: "could not find the office" is
    # an ordinary description of a navigation problem (literal sense), not
    # an admission of missing information, and no number is anywhere in the
    # sentence -- the previous fix (number-presence per part) could not
    # distinguish this from a genuine standalone admission and would have
    # dropped the whole part, silently discarding the separate, unsupported
    # "must submit a certificate of eligibility" requirement along with it.
    answer = (
        "The policy is not mentioned elsewhere, but students could not find "
        "the office and must submit a certificate of eligibility."
    )
    assert _answer_has_ungrounded_claim(answer, [TOR_CHUNK]) is True


def test_gate_passes_a_supported_factual_remainder_following_a_literal_hedge_phrase():
    # Mirror of the test above, but the remainder IS genuinely supported --
    # confirms the recursive bare-conjunction split does not reject clearly
    # grounded content merely because it sits next to a literally-used hedge
    # phrase with no comma separating them.
    answer = (
        "Students could not find the office and the TOR fee is PHP 20.00 "
        "per page for undergraduate students."
    )
    assert _answer_has_ungrounded_claim(answer, [TOR_CHUNK]) is False


def test_gate_flags_an_unsupported_remainder_after_two_separate_hedge_clauses():
    # "Multiple hedge phrases, multiple clauses" coverage: two independent,
    # genuine admissions (both "not mentioned") followed by a third,
    # unsupported factual clause -- every hedge clause must be dropped and
    # the remaining factual clause still independently checked.
    answer = (
        "The deadline is not mentioned elsewhere, and the office is also "
        "not mentioned, but the Landbank LinkBiz fee is PHP 25.00 per transaction."
    )
    assert _answer_has_ungrounded_claim(answer, [TOR_CHUNK]) is True


def test_gate_passes_a_supported_remainder_after_two_separate_hedge_clauses():
    # Same shape, but the trailing factual clause is genuinely grounded --
    # confirms two hedge clauses in a row do not themselves cause a false
    # positive once the real, supported remainder is reached.
    answer = (
        "The deadline is not mentioned elsewhere, and the office is also "
        "not mentioned, but the TOR fee is PHP 20.00 per page for undergraduate students."
    )
    assert _answer_has_ungrounded_claim(answer, [TOR_CHUNK]) is False


def test_gate_passes_two_hedge_clauses_with_no_smuggled_fact_at_all():
    # Purely honest, multi-clause uncertainty with nothing else attached --
    # must stay fully exempt, not become checkable merely because there are
    # two of them joined by a conjunction.
    answer = "The deadline is not mentioned elsewhere, and the office is also not mentioned elsewhere."
    assert _answer_has_ungrounded_claim(answer, [TOR_CHUNK]) is False


def test_non_hedge_claim_parts_preserves_a_word_starting_with_a_conjunction_after_a_semicolon():
    # Before the fix, ";android ..." matched "and" out of "android" with no
    # word boundary required, truncating it to "roid ...". None of "but",
    # "yet", or "however" collide with a common English word this way, but
    # "and" does ("android"), so it is the one that actually catches a
    # regression here.
    claim = (
        "The policy is not mentioned elsewhere; android devices must be "
        "registered with a P500 fee."
    )
    parts = _non_hedge_claim_parts(claim)
    assert parts == ["android devices must be registered with a P500 fee."]


def test_non_hedge_claim_parts_does_not_mis_split_ordinary_semicolon_prose():
    # A real coordinating conjunction after a semicolon (with a word
    # boundary) still splits correctly -- the fix narrows the match, it
    # does not disable it.
    claim = "The fee is not mentioned elsewhere; and the office is Room 204."
    assert _non_hedge_claim_parts(claim) == ["the office is Room 204."]


# --- Part 2: end-to-end through the main generation-success path ------------


def test_main_path_ungrounded_answer_is_gated_with_exact_fields():
    store = FacetAwareFakeStore({"tor": [TOR_CHUNK]})
    fabricated = "Graduating students may overload up to six units or two subjects with approval."

    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch("app.services.qa.question_answering.generate_groq_answer", return_value=fabricated),
        patch.object(settings, "citation_verification_mode", "lexical"),
    ):
        result = answer_qa_question(SINGLE_TOPIC_QUESTION)

    assert result.answer == INSUFFICIENT_GROUNDING_ANSWER
    assert result.confidence == "low"
    assert result.sources == []
    assert result.fallback_used is True
    assert result.fallback_reason == "insufficient_grounding"
    assert result.citation_status is None


def test_main_path_well_grounded_answer_passes_through_unchanged():
    store = FacetAwareFakeStore({"tor": [TOR_CHUNK]})
    grounded = "The Transcript of Records (TOR) fee is PHP 20.00 per page for undergraduate students."

    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch("app.services.qa.question_answering.generate_groq_answer", return_value=grounded),
        patch.object(settings, "citation_verification_mode", "lexical"),
    ):
        result = answer_qa_question(SINGLE_TOPIC_QUESTION)

    assert result.fallback_used is False
    assert result.fallback_reason is None
    assert result.answer != INSUFFICIENT_GROUNDING_ANSWER
    assert "PHP 20.00" in result.answer
    assert result.sources  # genuinely supported -- citations still attached


# --- Part 3: intentional non-factual paths must remain completely untouched -

def test_greeting_is_not_gated():
    result = answer_qa_question("hello")
    assert result.answer == GREETING_ANSWER
    assert result.fallback_used is False
    assert result.fallback_reason == "greeting"


def test_empty_retrieval_stock_response_is_not_gated():
    store = FacetAwareFakeStore({})  # nothing matches any query -> always []
    with patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store):
        result = answer_qa_question("What is the Landbank LinkBiz processing fee?")

    assert result.answer == OUT_OF_SCOPE_ANSWER
    assert result.confidence == "low"
    assert result.fallback_used is False
    assert result.out_of_scope_detected is True


def test_clarification_fallback_is_not_gated():
    """retrieval_quality's should_clarify path already asks for more
    information instead of asserting a fact, and returns before the gate's
    call site is ever reached -- forcing the branch directly (rather than
    hoping a fixture happens to trigger the real heuristic) to confirm that
    deterministically."""
    store = FacetAwareFakeStore({"tor": [TOR_CHUNK]})

    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch(
            "app.services.qa.question_answering._retrieval_quality",
            return_value={"should_clarify": True, "reason": "retrieval_evidence_weak"},
        ),
    ):
        result = answer_qa_question(SINGLE_TOPIC_QUESTION)

    assert result.fallback_used is True
    assert result.fallback_reason == "retrieval_evidence_weak"
    assert result.answer != INSUFFICIENT_GROUNDING_ANSWER
    assert result.sources == []


# --- Part 4: typed-answer / model-unavailable paths, well-grounded case -----
#
# (The mixed/ungrounded case for these same branches is covered in
# test_qa_facet_coverage_unguarded_branches.py -- these tests confirm the
# gate does NOT fire for a genuinely well-grounded typed/fallback answer,
# i.e. it is not "unnecessarily gated".)


def test_typed_answer_path_well_grounded_is_not_gated():
    store = FacetAwareFakeStore({"tor": [TOR_CHUNK]})
    typed_text = "The Transcript of Records (TOR) fee is PHP 20.00 per page for undergraduate students."
    sink: dict = {}

    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch(
            "app.services.qa.question_answering._typed_answer_from_context",
            return_value=typed_text,
        ),
        patch(
            "app.services.qa.question_answering.is_service_howto_query",
            return_value=False,
        ),
        patch.object(settings, "citation_verification_mode", "lexical"),
    ):
        result = answer_qa_question(SINGLE_TOPIC_QUESTION, generation_context_sink=sink)

    assert sink.get("status") == "not_invoked:typed_answer_used_instead_of_generation"
    assert result.fallback_used is False
    assert result.answer == typed_text
    assert result.sources
