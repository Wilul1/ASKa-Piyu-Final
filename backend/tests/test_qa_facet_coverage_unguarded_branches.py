"""Regression tests for the three return branches in ``answer_qa_question``
(other than the main generation-success path) that present a factual,
retrieval-derived answer:

- line ~673: the ``use_typed_now`` typed/template-answer path.
- line ~787: ``GroqAnswerError`` -> typed-answer-as-fallback.
- line ~900: ``GroqAnswerError`` -> conversational/recovered fallback.

Originally written to reproduce a gap where these branches did not
acknowledge an uncovered question facet at all (see git history for the
``_append_unverified_facet_caveats`` fix that closed that gap). Now
updated for the STRONGER synchronous grounding gate
(``_answer_has_ungrounded_claim``, see ``question_answering.py`` and
``test_question_answering_grounding_gate.py``): for a genuinely mixed
answer (one claim well-supported, a separate claim with zero
lexical/numeric overlap with anything retrieved), the gate now intercepts
BEFORE the facet-coverage caveat ever gets a chance to run, replacing the
whole answer with the fixed fallback rather than merely annotating it.
These three tests now confirm that supersession holds consistently across
all three branches, not just the main path.

Each test forces its specific branch via controlled mocks (never relying
on the real intent-detection heuristics) and asserts the branch was
actually reached (via ``generation_context_sink["status"]``, the same
diagnostic string ``answer_qa_question`` itself already records) before
checking the gate's outcome.
"""

from unittest.mock import patch

from app.config import settings
from app.services.qa.groq_answer_service import GroqAnswerError
from app.services.qa.question_answering import INSUFFICIENT_GROUNDING_ANSWER, answer_qa_question

from tests.test_qa_facet_coverage_caveats import FacetAwareFakeStore, TOR_FEE_QUESTION
from tests.test_qa_question_answering import chunk

MIXED_CLAIM_ANSWER = (
    "The TOR fee is PHP 20.00 per page for undergraduate students. "
    "The Landbank LinkBiz processing fee is PHP 25.00 per transaction."
)


def _tor_only_store():
    tor_chunk = chunk(
        "TOR Fees",
        "The Transcript of Records (TOR) fee is PHP 20.00 per page for undergraduate students.",
    )
    return FacetAwareFakeStore({"tor": [tor_chunk], "transcript": [tor_chunk]}), tor_chunk


def _assert_gated(result):
    assert result.answer == INSUFFICIENT_GROUNDING_ANSWER
    assert result.confidence == "low"
    assert result.sources == []
    assert result.fallback_used is True
    assert result.fallback_reason == "insufficient_grounding"


# --- Branch ~673: use_typed_now (typed/template answer, Groq never called) ---


def test_typed_answer_path_mixed_claim_answer_is_gated_entirely():
    store, _tor_chunk = _tor_only_store()
    sink: dict = {}

    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch(
            "app.services.qa.question_answering._typed_answer_from_context",
            return_value=MIXED_CLAIM_ANSWER,
        ),
        patch(
            "app.services.qa.question_answering.is_service_howto_query",
            return_value=False,
        ),
        patch.object(settings, "citation_verification_mode", "lexical"),
    ):
        result = answer_qa_question(TOR_FEE_QUESTION, generation_context_sink=sink)

    # Confirm the intended branch, and only that branch, actually ran.
    assert sink.get("status") == "not_invoked:typed_answer_used_instead_of_generation"
    _assert_gated(result)


# --- Branch ~787: GroqAnswerError -> typed-answer-as-fallback ---


def test_groq_unavailable_typed_fallback_mixed_claim_answer_is_gated_entirely():
    store, _tor_chunk = _tor_only_store()
    sink: dict = {}

    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch(
            "app.services.qa.question_answering.generate_groq_answer",
            side_effect=GroqAnswerError("Groq API key is not configured."),
        ),
        patch(
            "app.services.qa.question_answering._typed_answer_from_context",
            return_value=MIXED_CLAIM_ANSWER,
        ),
        patch(
            "app.services.qa.question_answering.is_service_howto_query",
            return_value=True,
        ),
        patch.object(settings, "citation_verification_mode", "lexical"),
    ):
        result = answer_qa_question(TOR_FEE_QUESTION, generation_context_sink=sink)

    assert sink.get("status") == "invoked_but_failed:typed_answer_fallback_used_after_groq_error"
    _assert_gated(result)
    # This branch is already a Groq-unavailable fallback regardless of the
    # gate, so fallback_used was already True before the gate -- confirm
    # the gate's own, more specific reason still wins.
    assert result.fallback_reason == "insufficient_grounding"


# --- Branch ~900: GroqAnswerError -> conversational/recovered fallback ---


def test_groq_unavailable_conversational_fallback_mixed_claim_answer_is_gated_entirely():
    store, _tor_chunk = _tor_only_store()
    sink: dict = {}

    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch(
            "app.services.qa.question_answering.generate_groq_answer",
            side_effect=GroqAnswerError("Groq answer generation timed out."),
        ),
        # Force past the typed-answer-fallback branch (line ~787) so this
        # specific branch, not a neighboring one, is what actually runs.
        patch(
            "app.services.qa.question_answering._typed_answer_from_context",
            return_value=None,
        ),
        patch(
            "app.services.qa.question_answering._fallback_answer_from_context",
            return_value=(MIXED_CLAIM_ANSWER, "medium", []),
        ),
        # Deterministically keep the offline charter-recovery substitution
        # out of play, so the fabricated fallback text above is exactly
        # what gets evaluated, not silently swapped for different wording.
        patch(
            "app.services.qa.question_answering._recover_factual_charter_answer",
            return_value=None,
        ),
        patch.object(settings, "citation_verification_mode", "lexical"),
    ):
        result = answer_qa_question(TOR_FEE_QUESTION, generation_context_sink=sink)

    assert sink.get("status") == "invoked_but_failed:conversational_or_recovered_fallback_used"
    _assert_gated(result)
