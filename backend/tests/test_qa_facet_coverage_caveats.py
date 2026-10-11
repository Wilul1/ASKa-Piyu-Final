"""Regression tests for the deterministic unverified-facet caveat.

Production observed a bundled question (TOR fee per page + a Landbank
LinkBiz processing fee with no indexed official-source evidence) where the
generator answered the supported part correctly but also stated the
unsupported part as settled fact. ``build_grounding_notes`` already asks
the generator, as a prompt instruction, not to do this -- but that is only
a request, and the generator did not follow it for this exact production
case (confirmed via the live citation-verification job: only 1 of 7
extracted claims survived verification, and it supported only the TOR
portion).

``_append_unverified_facet_caveats`` is the deterministic backstop: it
never rewrites or removes the generator's own wording, it only appends one
explicit, code-level caveat per facet that ``analyze_facet_coverage``
found zero supporting evidence for -- named from the student's own wording
(``facet.label``), never inventing a replacement fact or figure.

Honest limitation, not hidden: this does not retroactively delete an
already-fabricated sentence from the generator's own text (that would
require reliably mapping a specific generated sentence back to a specific
question facet, which the current architecture cannot do without a risky,
heuristic rewrite -- see the task report). It guarantees the *overall
response* always also carries an explicit, specific "not confirmed from
official sources" caveat for any genuinely uncovered part, rather than
leaving that part stated with no caveat at all.
"""

from unittest.mock import patch

import pytest

from app.config import settings
from app.services.chroma_store import RetrievedChunk
from app.services.qa.multi_facet import FacetCoverage, QuestionFacet
from app.services.qa.question_answering import (
    OUT_OF_SCOPE_ANSWER,
    _append_unverified_facet_caveats,
    answer_qa_question,
)

from tests.test_qa_question_answering import FakeStore, chunk


class FacetAwareFakeStore(FakeStore):
    """Unlike ``FakeStore`` (always returns the same fixed chunks for every
    query, which cannot simulate "this specific sub-topic has no indexed
    evidence"), this returns chunks per-query via simple keyword matching,
    so a genuine per-facet coverage gap can be exercised end-to-end."""

    def __init__(self, chunks_by_keyword: dict[str, list[RetrievedChunk]]) -> None:
        super().__init__([])
        self._by_keyword = chunks_by_keyword

    def search(self, question, *, top_k=None, raw_k=None, user_role=None):
        self.calls.append(
            {"question": question, "top_k": top_k, "raw_k": raw_k, "user_role": user_role}
        )
        q = question.lower()
        for keyword, chunks in self._by_keyword.items():
            if keyword in q:
                return chunks
        return []


TOR_FEE_QUESTION = (
    "What is the TOR fee per page for undergraduate students, "
    "and what is the Landbank LinkBiz processing fee?"
)


# --- Direct unit tests of the pure caveat-appending helper ---


def test_caveat_is_noop_when_no_coverage_gap():
    answer = "The TOR fee is PHP 20.00 per page."
    assert _append_unverified_facet_caveats(answer, FacetCoverage()) == answer


def test_caveat_appends_one_note_per_uncovered_facet_naming_it():
    # has_gap requires >= 2 facets (a single-part question is retrieved for
    # as a whole -- see analyze_facet_coverage's own docstring), so this
    # mirrors a genuine mixed question: one covered facet, one uncovered.
    tor_facet = QuestionFacet(
        key="tor-fee", label="TOR fee per page", retrieval_query="TOR fee per page"
    )
    landbank_facet = QuestionFacet(
        key="landbank-linkbiz-fee", label="Landbank LinkBiz processing fee",
        retrieval_query="Landbank LinkBiz processing fee",
    )
    coverage = FacetCoverage(
        facets=(tor_facet, landbank_facet), covered=(tor_facet,), uncovered=(landbank_facet,),
    )
    answer = "The TOR fee is PHP 20.00 per page."

    result = _append_unverified_facet_caveats(answer, coverage)

    assert result.startswith(answer)  # original wording preserved, untouched
    assert "Landbank LinkBiz processing fee" in result
    assert "could not confirm" in result.lower()


def test_caveat_skips_internal_service_annotation_facet():
    """resolve_followup_question can append an internal "(Service: X)"
    disambiguation annotation to the retrieval question (never written by
    the student), which split_question_facets can isolate as its own
    facet. That must never be surfaced to the student as if it were a
    real, uncovered part of their question."""
    real_facet = QuestionFacet(
        key="enrollment-requirements", label="requirements to enroll",
        retrieval_query="requirements to enroll",
    )
    internal_annotation_facet = QuestionFacet(
        key="service-registration", label="(Service: Registration)",
        retrieval_query="(Service: Registration)",
    )
    coverage = FacetCoverage(
        facets=(real_facet, internal_annotation_facet),
        covered=(real_facet,),
        uncovered=(internal_annotation_facet,),
    )
    answer = "To enroll, secure clearance and submit SF-Form-002 to ICTS."

    result = _append_unverified_facet_caveats(answer, coverage)

    assert result == answer  # unchanged -- no confusing caveat appended
    assert "Service" not in result
    assert "(" not in result


def test_caveat_helper_never_invents_a_replacement_amount():
    """The guarantee this helper can actually make: it never fabricates a
    number/figure of its own, regardless of what the generator already said."""
    facet = QuestionFacet(
        key="some-fee", label="some unrelated fee", retrieval_query="some unrelated fee"
    )
    coverage = FacetCoverage(facets=(facet,), covered=(), uncovered=(facet,))

    result = _append_unverified_facet_caveats("Some answer.", coverage)

    import re

    assert not re.search(r"(?:PHP|₱)\s?\d", result)


def test_caveat_is_noop_for_empty_answer():
    assert _append_unverified_facet_caveats("", FacetCoverage()) == ""


# --- End-to-end regression: mixed supported/unsupported question ---


def test_mixed_question_preserves_supported_part_and_caveats_unsupported_part():
    tor_chunk = chunk(
        "TOR Fees",
        "The Transcript of Records (TOR) fee is PHP 20.00 per page for undergraduate students.",
    )
    store = FacetAwareFakeStore({"tor": [tor_chunk], "transcript": [tor_chunk]})

    fabricated_answer = (
        "The TOR fee is PHP 20.00 per page for undergraduate students. "
        "The Landbank LinkBiz processing fee is PHP 25.00 per transaction."
    )

    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch(
            "app.services.qa.question_answering.generate_groq_answer",
            return_value=fabricated_answer,
        ),
        patch.object(settings, "citation_verification_mode", "lexical"),
    ):
        result = answer_qa_question(TOR_FEE_QUESTION)

    # Supported wording is preserved verbatim -- never suppressed or rewritten.
    assert "PHP 20.00 per page" in result.answer
    # The unsupported part now carries an explicit, specific caveat.
    assert "could not confirm" in result.answer.lower()
    assert "landbank" in result.answer.lower() or "linkbiz" in result.answer.lower()
    # Citations still cover the genuinely supported part.
    cited_titles = {s.get("title") for s in (result.sources or [])}
    assert any("TOR" in (t or "") for t in cited_titles)


def test_question_with_no_official_source_evidence_at_all_is_not_fabricated():
    """Single-topic question, zero retrieved chunks: the pre-existing
    empty-retrieval path already returns the stock out-of-scope answer and
    confidence "low" -- confirms this fix does not regress that, and that
    no specific fee/figure is ever fabricated when there is no evidence at
    all to work from."""
    store = FacetAwareFakeStore({})  # no keyword matches anything -> always []

    with patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store):
        result = answer_qa_question("What is the Landbank LinkBiz processing fee?")

    assert result.answer == OUT_OF_SCOPE_ANSWER
    assert result.confidence == "low"
    assert result.sources == []
    import re

    assert not re.search(r"(?:PHP|₱)\s?\d", result.answer)
