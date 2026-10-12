"""Regression tests probing the three return branches in
``answer_qa_question`` identified in review as architecturally capable of
the same gap the main generation-success path was just fixed for, but not
yet wired to ``_append_unverified_facet_caveats``:

- line ~673: the ``use_typed_now`` typed/template-answer path.
- line ~787: ``GroqAnswerError`` -> typed-answer-as-fallback.
- line ~900: ``GroqAnswerError`` -> conversational/recovered fallback.

Each test forces its specific branch via controlled mocks (never relying
on the real intent-detection heuristics), constructs a genuine two-facet
question where one facet has supporting evidence and the other has none,
and asserts the branch was actually reached (via ``generation_context_sink
["status"]``, the same diagnostic string ``answer_qa_question`` itself
already records) before checking whether the uncovered facet is
acknowledged. A failing acknowledgment assertion here is an intentionally
reproduced, previously-unconfirmed gap -- not a bug in the test.
"""

import re
from unittest.mock import patch

from app.config import settings
from app.services.qa.groq_answer_service import GroqAnswerError
from app.services.qa.question_answering import answer_qa_question

from tests.test_qa_facet_coverage_caveats import FacetAwareFakeStore, TOR_FEE_QUESTION
from tests.test_qa_question_answering import chunk

MONEY_RE = re.compile(r"(?:PHP|₱)\s?\d")


def _tor_only_store():
    tor_chunk = chunk(
        "TOR Fees",
        "The Transcript of Records (TOR) fee is PHP 20.00 per page for undergraduate students.",
    )
    return FacetAwareFakeStore({"tor": [tor_chunk], "transcript": [tor_chunk]}), tor_chunk


# --- Branch ~673: use_typed_now (typed/template answer, Groq never called) ---


def test_typed_answer_path_uncovered_facet_acknowledgment():
    store, _tor_chunk = _tor_only_store()
    typed_text = (
        "The Transcript of Records (TOR) fee is PHP 20.00 per page for undergraduate students. "
        "To obtain a TOR, submit a request form to the Registrar's Office."
    )
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
        result = answer_qa_question(TOR_FEE_QUESTION, generation_context_sink=sink)

    # Confirm the intended branch, and only that branch, actually ran.
    assert sink.get("status") == "not_invoked:typed_answer_used_instead_of_generation"

    # Supported/template content preserved verbatim.
    assert "submit a request form to the Registrar" in result.answer
    # No fabricated Landbank-specific figure anywhere in the answer.
    assert not MONEY_RE.search(result.answer.replace("PHP 20.00", ""))
    # Citations for the genuinely supported facet are preserved.
    cited_titles = {s.get("title") for s in (result.sources or [])}
    assert any("TOR" in (t or "") for t in cited_titles)

    # The actual check: does this branch acknowledge the uncovered facet?
    assert "could not confirm" in result.answer.lower(), (
        "REPRODUCED GAP: the typed-answer path (line ~673) does not "
        "acknowledge an uncovered facet -- it silently returns the typed "
        "template text with no caveat for the Landbank LinkBiz part."
    )


# --- Branch ~787: GroqAnswerError -> typed-answer-as-fallback ---


def test_groq_unavailable_typed_fallback_uncovered_facet_acknowledgment():
    store, _tor_chunk = _tor_only_store()
    typed_text = (
        "The Transcript of Records (TOR) fee is PHP 20.00 per page for undergraduate students. "
        "To obtain a TOR, submit a request form to the Registrar's Office."
    )
    sink: dict = {}

    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch(
            "app.services.qa.question_answering.generate_groq_answer",
            side_effect=GroqAnswerError("Groq API key is not configured."),
        ),
        patch(
            "app.services.qa.question_answering._typed_answer_from_context",
            return_value=typed_text,
        ),
        patch(
            "app.services.qa.question_answering.is_service_howto_query",
            return_value=True,
        ),
        patch.object(settings, "citation_verification_mode", "lexical"),
    ):
        result = answer_qa_question(TOR_FEE_QUESTION, generation_context_sink=sink)

    assert sink.get("status") == "invoked_but_failed:typed_answer_fallback_used_after_groq_error"

    assert "submit a request form to the Registrar" in result.answer
    assert not MONEY_RE.search(result.answer.replace("PHP 20.00", ""))
    cited_titles = {s.get("title") for s in (result.sources or [])}
    assert any("TOR" in (t or "") for t in cited_titles)

    assert "could not confirm" in result.answer.lower(), (
        "REPRODUCED GAP: the Groq-unavailable typed-answer fallback (line "
        "~787) does not acknowledge an uncovered facet."
    )


# --- Branch ~900: GroqAnswerError -> conversational/recovered fallback ---


def test_groq_unavailable_conversational_fallback_uncovered_facet_acknowledgment():
    store, _tor_chunk = _tor_only_store()
    fabricated_fallback = (
        "The TOR fee is PHP 20.00 per page for undergraduate students. "
        "The Landbank LinkBiz processing fee is PHP 25.00 per transaction."
    )
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
            return_value=(fabricated_fallback, "medium", []),
        ),
        # Deterministically keep the offline charter-recovery substitution
        # out of play, so the fabricated fallback text above is exactly
        # what gets returned, not silently swapped for different wording.
        patch(
            "app.services.qa.question_answering._recover_factual_charter_answer",
            return_value=None,
        ),
        patch.object(settings, "citation_verification_mode", "lexical"),
    ):
        result = answer_qa_question(TOR_FEE_QUESTION, generation_context_sink=sink)

    assert sink.get("status") == "invoked_but_failed:conversational_or_recovered_fallback_used"

    assert "PHP 20.00 per page" in result.answer
    cited_titles = {s.get("title") for s in (result.sources or [])}
    assert any("TOR" in (t or "") for t in cited_titles)

    assert "could not confirm" in result.answer.lower(), (
        "REPRODUCED GAP: the Groq-unavailable conversational/recovered "
        "fallback (line ~900) does not acknowledge an uncovered facet -- "
        "the fabricated Landbank LinkBiz sentence stands with no caveat."
    )
