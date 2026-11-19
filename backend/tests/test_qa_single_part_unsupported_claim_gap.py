"""Regression documentation for a gap identified in review of commit
d568f27 ("fix(qa): remove lexical grounding gate and improve Filipino
citations"): that commit removed the only synchronous, per-claim lexical/
numeric grounding check (``_answer_has_ungrounded_claim``) that ran
regardless of question structure. What replaced it for the mixed-claim
case (``_append_unverified_facet_caveats``) only ever acts on *multi-facet*
questions -- ``FacetCoverage.has_gap`` is defined as
``bool(self.uncovered) and self.is_multi_facet`` (``multi_facet.py``), and
``is_multi_facet`` requires ``len(self.facets) >= 2``.
``analyze_facet_coverage``'s own comment states this directly: "A
single-part question is retrieved for as a whole, so there is no per-part
evidence to judge and nothing may be reported as unanswered."

This file does NOT change ``question_answering.py`` or ``multi_facet.py``.
It documents the CURRENT, already-shipped behavior for a single-part
question whose generated answer contains a claim with no meaningful
lexical/numeric overlap with the retrieved evidence -- so the gap is
monitored by an explicit, named, currently-PASSING test (describing what
the system does today) rather than left silently undetected. If a future
change adds a narrower, per-claim safeguard for the single-part case (see
the recommendation in the accompanying review), this test's assertions
are exactly what should then be revisited and tightened.
"""

from unittest.mock import patch

from app.config import settings
from app.services.qa.question_answering import answer_qa_question

from tests.test_qa_question_answering import FakeStore, chunk


# A single-part question: no "and"/conjunction joining two distinct asks,
# so split_question_facets never produces >= 2 facets for it, and
# FacetCoverage.has_gap is therefore always False for this test regardless
# of what the retrieved evidence actually supports -- this is the precise
# precondition the identified gap depends on.
SINGLE_PART_QUESTION = "What is the TOR fee per page for undergraduate students?"


def test_single_part_question_unsupported_claim_is_returned_unmodified_with_no_caveat():
    # 1. The retrieved evidence: real, on-topic, and genuinely supports a
    # DIFFERENT fee amount than the one the generated answer will state.
    retrieved_evidence_chunk = chunk(
        "TOR Fees",
        "The Transcript of Records (TOR) fee is PHP 20.00 per page for "
        "undergraduate students.",
    )
    store = FakeStore([retrieved_evidence_chunk])

    # 2. The generated answer: a fixed string standing in for whatever the
    # LLM produced, asserting a specific claim (a late-enrollment penalty)
    # that shares no content word or number with the retrieved evidence
    # above -- a plain, unambiguous hallucination, not an edge case of
    # lexical scoring (no shared terms like "TOR"/"fee"/"PHP" to argue
    # about -- this claim is simply about something else entirely).
    generated_answer = (
        "Late enrollment incurs a penalty of PHP 500.00 payable at the "
        "Accounting Office before the add/drop deadline."
    )

    with (
        patch(
            "app.services.qa.question_answering.get_knowledge_base_store",
            return_value=store,
        ),
        patch(
            "app.services.qa.question_answering.generate_groq_answer",
            return_value=generated_answer,
        ),
        patch.object(settings, "citation_verification_mode", "lexical"),
    ):
        # 3. The answer actually returned to the caller.
        result = answer_qa_question(SINGLE_PART_QUESTION)

    # --- Documents the gap: the unsupported claim is shown verbatim ---
    # No caveat, no partial redaction, no "could not confirm" note -- the
    # fabricated claim is indistinguishable from a grounded one in the
    # returned text. (_append_unverified_facet_caveats is a no-op here
    # because this question never splits into >= 2 facets; this assertion
    # is the gap, not a bug in this test.)
    assert result.answer == generated_answer
    assert "could not confirm" not in result.answer.lower()
    assert "PHP 500.00" in result.answer

    # --- Citation and confidence metadata ---
    # Confidence reflects retrieval quality only (_confidence_for looks at
    # retrieval/selection/domain-match signals and a fixed MISSING_INFO_
    # PHRASES list -- never per-claim lexical support), so a good retrieval
    # hit still yields a non-"low" confidence despite the answer's claim
    # being entirely unsupported by that same retrieval.
    assert result.confidence != "low"
    # Nothing in the retrieved evidence lexically supports the fabricated
    # claim, so the citation-display scorer (_select_supporting_context)
    # finds nothing to cite -- the ONE remaining, implicit signal that
    # something may be wrong, though it is never surfaced as an explicit
    # caveat and confidence is not downgraded to match it.
    assert result.sources == []
    # Unlike the removed gate's behavior, this is never treated as a
    # fallback/refusal condition.
    assert result.fallback_used is False
    assert result.fallback_reason is None
