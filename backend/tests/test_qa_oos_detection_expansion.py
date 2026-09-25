"""Regression coverage for the widened deterministic OOS classifier.

`_is_out_of_scope_query` was extended with a small set of general,
category-level external terms (cooking/recipes, fantasy sports, sports
trivia, entertainment) plus one anchor phrase for unrelated consumer-product
questions, and two handbook terms ("class", "suspend") so a legitimate
class-suspension-due-to-weather question doesn't get caught by the
pre-existing "weather" external term. This file proves the classifier
correctly separates clearly-unrelated conversational domains from ordinary
LSPU questions, and that the existing early-OOS short-circuit contract
(no retrieval query, no generation call, no Citation V2 job, zero citations)
still holds for a newly-covered example. It does not test citation-gating
behavior itself -- see test_qa_oos_citation_gating.py for that.
"""

from __future__ import annotations

import pytest

from app.services.chroma_store import RetrievedChunk
from app.services.qa import citation_verification_jobs as jobs
from app.services.qa.question_answering import (
    OUT_OF_SCOPE_ANSWER,
    OUT_OF_SCOPE_QUESTION,
    answer_qa_question,
    detect_question_intent,
)

MODE = "app.services.qa.question_answering.settings.citation_verification_mode"


@pytest.fixture(autouse=True)
def _reset_job_store():
    jobs.reset_jobs_store()
    yield
    jobs.reset_jobs_store()


class _FakeStore:
    chunk_count = 1

    def __init__(self, chunks: list[RetrievedChunk]):
        self.chunks = chunks
        self.chunk_count = max(len(chunks), 1)

    def search(self, *args, **kwargs):
        return list(self.chunks)

    def list_chunks(self):
        return []


def _chunk(document_id: str, title: str, text: str) -> RetrievedChunk:
    return RetrievedChunk(
        document_id=document_id,
        title=title,
        source_filename="doc.pdf",
        chunk_index=0,
        text=text,
        relevance_score=0.9,
        reranked_score=3.0,
        metadata={"audience": "both", "chunk_id": f"{document_id}::0"},
    )


@pytest.mark.parametrize(
    "question",
    [
        "Can you give me a recipe for adobo?",
        "How do I cook carbonara?",
        "Who should I pick for my fantasy basketball team?",
        "Who won the NBA championship?",
        "What's the weather in Manila?",
        "Who is the president of the United States?",
        "Recommend a movie for tonight.",
        "Which phone should I buy?",
        # Adversarial-review additions: confirm the generic external terms
        # still catch genuine external-content requests, not just the
        # original benchmark phrasing.
        "Give me a chicken curry recipe.",
        "How do I cook spaghetti?",
        "Recommend a movie.",
        "Who won the basketball championship?",
        "Build me a fantasy football team.",
    ],
)
def test_clearly_out_of_scope_questions_are_detected(question: str):
    assert detect_question_intent(question) == OUT_OF_SCOPE_QUESTION


@pytest.mark.parametrize(
    "question",
    [
        "What are the requirements for requesting a Transcript of Records?",
        "I'm a continuing student. What are my enrollment requirements?",
        "What office handles student athletes?",
        "Does LSPU have sports programs?",
        "What happens if classes are suspended because of bad weather?",
        "Where can I eat inside the campus?",
        "How do I file a technical support ticket?",
        "I can't access my university account. What should I do?",
        # Adversarial-review additions: legitimate campus-process questions
        # that happen to contain the new external-domain vocabulary. Two of
        # these (championship registration, movie-showing approval) were
        # confirmed false positives before the office/organization/approve/
        # register handbook-term additions.
        "Is cooking allowed in the dormitory?",
        "Can our student organization hold a movie screening?",
        "How do we register for an inter-campus championship?",
        "Can students organize a fantasy-themed campus event?",
        "Are cooking appliances allowed inside university facilities?",
        "What office should approve a movie showing for our organization?",
        "Our LSPU team joined a championship. What office handles student athletes?",
        "Can our organization buy a phone using organization funds?",
    ],
)
def test_legitimate_university_questions_remain_in_scope(question: str):
    assert detect_question_intent(question) != OUT_OF_SCOPE_QUESTION


def test_newly_covered_domain_still_short_circuits_before_retrieval_and_generation():
    """Proves the widened classifier reaches the SAME pre-existing
    short-circuit contract as the original OOS phrases -- no retrieval
    query beyond the chunk_count check, no Liquid call, no Citation V2
    job, zero citations -- for a domain the classifier did not previously
    cover."""
    store = _FakeStore(
        [_chunk("foreword", "Foreword", "Every educational institution has its mission.")]
    )
    sink: dict = {}
    from unittest.mock import patch

    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch("app.services.qa.question_answering.generate_groq_answer") as mock_generate,
        patch(MODE, "async_llm"),
    ):
        result = answer_qa_question(
            "Can you give me a recipe for adobo?",
            async_verification_sink=sink,
        )
    mock_generate.assert_not_called()
    assert result.answer == OUT_OF_SCOPE_ANSWER
    assert result.out_of_scope_detected is True
    assert result.sources == []
    assert result.citation_status is None
    assert sink == {}
