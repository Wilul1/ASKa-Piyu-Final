"""Authoritative OOS refusal must never schedule Citation V2 verification.

Covers stock OOS from early intent, empty retrieval, and post-generation
collapse. Does not expand the OOS intent classifier. Does not cover fg_n2
(generation answered an OOS question as in-scope).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.chroma_store import RetrievedChunk
from app.services.qa import citation_verification_jobs as jobs
from app.services.qa.citation_verification import CandidateEvidence
from app.services.qa.question_answering import (
    OUT_OF_SCOPE_ANSWER,
    OUT_OF_SCOPE_QUESTION,
    QAResult,
    _display_sources_for_answer,
    _is_authoritative_oos_answer,
    answer_qa_question,
    detect_question_intent,
)

VERIFY_AT_DISPLAY_SEAM = "app.services.qa.citation_verification.verify_citations"
VERIFY_AT_JOB_SEAM = "app.services.qa.citation_verification_jobs.verify_citations"
MODE = "app.services.qa.question_answering.settings.citation_verification_mode"
SCHEDULE = "app.routes.qa.citation_verification_jobs.schedule_verification"

client = TestClient(app)

# Pre-existing early-OOS fixture question (not a classifier expansion).
_EARLY_OOS_QUESTION = "Who is the president of the Philippines?"


@pytest.fixture(autouse=True)
def _reset_job_store():
    jobs.reset_jobs_store()
    yield
    jobs.reset_jobs_store()


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


class _FakeStore:
    chunk_count = 1

    def __init__(self, chunks: list[RetrievedChunk]):
        self.chunks = chunks
        self.chunk_count = max(len(chunks), 1)

    def search(self, *args, **kwargs):
        return list(self.chunks)

    def list_chunks(self):
        return []


# --- unit: authoritative signal ----------------------------------------------


def test_stock_oos_answer_is_authoritative_signal():
    assert _is_authoritative_oos_answer(OUT_OF_SCOPE_ANSWER) is True
    assert _is_authoritative_oos_answer("The fee is P75 per page.") is False


def test_preexisting_presidential_query_remains_early_oos_intent():
    assert detect_question_intent(_EARLY_OOS_QUESTION) == OUT_OF_SCOPE_QUESTION


# --- A/E: display seam gates OOS; lexical compatible -------------------------


@pytest.mark.parametrize("mode", ["lexical", "shadow", "llm", "async_shadow", "async_llm"])
def test_display_sources_skips_verification_for_stock_oos_answer(mode: str):
    chunk = _chunk("noise", "Foreword", "LSPU handbook foreword text.")
    sink: dict = {}
    v2_sink: dict = {}
    with patch(VERIFY_AT_DISPLAY_SEAM) as mock_verify, patch(MODE, mode):
        sources = _display_sources_for_answer(
            [chunk],
            OUT_OF_SCOPE_ANSWER,
            async_verification_sink=sink,
            citation_v2_sink=v2_sink,
        )
    assert sources == []
    assert sink == {}
    assert v2_sink == {}
    mock_verify.assert_not_called()


def test_display_sources_in_scope_still_populates_async_llm_sink():
    chunk = _chunk("tor", "Transcript of Records", "Fee: P75/page.")
    answer = "The fee is P75 per page."
    sink: dict = {}
    with patch(MODE, "async_llm"):
        sources = _display_sources_for_answer([chunk], answer, async_verification_sink=sink)
    assert sources == []
    assert sink["mode"] == "async_llm"
    assert sink["answer"] == answer
    assert len(sink["candidates"]) == 1
    assert isinstance(sink["candidates"][0], CandidateEvidence)


# --- early OOS / empty retrieval via answer_qa_question ----------------------


def test_early_oos_refusal_has_no_citations_and_empty_verification_sink():
    store = _FakeStore(
        [_chunk("foreword", "Foreword", "Every educational institution has its mission.")]
    )
    sink: dict = {}
    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch("app.services.qa.question_answering.generate_groq_answer") as mock_generate,
        patch(MODE, "async_llm"),
    ):
        result = answer_qa_question(
            _EARLY_OOS_QUESTION,
            async_verification_sink=sink,
        )
    mock_generate.assert_not_called()
    assert result.answer == OUT_OF_SCOPE_ANSWER
    assert result.out_of_scope_detected is True
    assert result.sources == []
    assert result.citation_status is None
    assert sink == {}


def test_empty_retrieval_stock_oos_has_no_citations_and_empty_sink():
    store = _FakeStore([])
    sink: dict = {}
    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch(
            "app.services.qa.question_answering.detect_question_intent",
            return_value="NORMAL_QA",
        ),
        patch("app.services.qa.question_answering.generate_groq_answer") as mock_generate,
        patch(MODE, "async_llm"),
        patch(VERIFY_AT_DISPLAY_SEAM) as mock_verify,
    ):
        result = answer_qa_question(
            "What is the campus mascot animal?",
            async_verification_sink=sink,
        )
    mock_generate.assert_not_called()
    assert result.answer == OUT_OF_SCOPE_ANSWER
    assert result.out_of_scope_detected is True
    assert result.sources == []
    assert result.citation_status is None
    assert sink == {}
    mock_verify.assert_not_called()


# --- C/D: route-level async_llm / async_shadow -------------------------------


def _fake_oos_answer_qa_question(*args, **kwargs):
    # Real OOS path never populates the sink; mirror that contract.
    return QAResult(
        answer=OUT_OF_SCOPE_ANSWER,
        sources=[],
        confidence="low",
        retrieved_chunks=[],
        out_of_scope_detected=True,
        citation_status=None,
    )


def test_async_llm_oos_refusal_has_no_verification_id_or_verifying_status():
    with (
        patch("app.routes.qa.answer_qa_question", side_effect=_fake_oos_answer_qa_question),
        patch(VERIFY_AT_JOB_SEAM) as mock_verify,
        patch(SCHEDULE, wraps=jobs.schedule_verification) as mock_schedule,
    ):
        response = client.post(
            "/qa/ask",
            json={"question": _EARLY_OOS_QUESTION},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["answer"] == OUT_OF_SCOPE_ANSWER
    assert data["sources"] == []
    assert data["citations"] == []
    assert "citation_status" not in data
    assert "citation_verification_id" not in data
    assert len(jobs._JOBS) == 0
    mock_verify.assert_not_called()
    # schedule may be called with empty sink; it must no-op.
    if mock_schedule.called:
        assert mock_schedule.return_value is None or mock_schedule.call_args[0][1] == {}


def test_async_shadow_oos_refusal_creates_no_background_verifier_job():
    with (
        patch(MODE, "async_shadow"),
        patch("app.routes.qa.answer_qa_question", side_effect=_fake_oos_answer_qa_question),
        patch(VERIFY_AT_JOB_SEAM) as mock_verify,
    ):
        response = client.post(
            "/qa/ask",
            json={"question": _EARLY_OOS_QUESTION},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["sources"] == []
    assert "citation_verification_id" not in data
    assert len(jobs._JOBS) == 0
    mock_verify.assert_not_called()


def test_qa_ask_oos_via_real_answer_path_never_schedules_job():
    """End-to-end through real answer_qa_question (pre-existing early OOS)."""
    store = _FakeStore(
        [_chunk("foreword", "Foreword", "Every educational institution has its mission.")]
    )

    def _answer(*args, **kwargs):
        return answer_qa_question(*args, **kwargs)

    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch("app.routes.qa.answer_qa_question", side_effect=_answer),
        patch(MODE, "async_llm"),
        patch(VERIFY_AT_JOB_SEAM) as mock_verify,
        patch(VERIFY_AT_DISPLAY_SEAM) as mock_display_verify,
    ):
        response = client.post(
            "/qa/ask",
            json={"question": _EARLY_OOS_QUESTION},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["answer"] == OUT_OF_SCOPE_ANSWER
    assert data["sources"] == []
    assert data["citations"] == []
    assert "citation_status" not in data
    assert "citation_verification_id" not in data
    assert len(jobs._JOBS) == 0
    mock_verify.assert_not_called()
    mock_display_verify.assert_not_called()


# --- B: in-scope still schedules normally ------------------------------------


def test_in_scope_async_llm_still_schedules_verification():
    def fake(*args, **kwargs):
        sink = kwargs.get("async_verification_sink")
        if sink is not None:
            sink.update(
                {
                    "mode": "async_llm",
                    "answer": "The fee is P75 per page.",
                    "candidates": [
                        CandidateEvidence(
                            citation_id="tor::0",
                            title="Transcript of Records",
                            source_section="Sec. 1",
                            source_filename="doc.pdf",
                            text="Fee: P75/page.",
                        )
                    ],
                }
            )
        return QAResult(
            answer="The fee is P75 per page.",
            sources=[],
            confidence="high",
            retrieved_chunks=[],
            citation_status="verifying",
            out_of_scope_detected=False,
        )

    from app.services.qa.citation_verification import VerificationOutcome

    outcome = VerificationOutcome(
        mode="async_llm", verifier_succeeded=True, verified_citation_ids=["tor::0"]
    )
    with (
        patch("app.routes.qa.answer_qa_question", side_effect=fake),
        patch(VERIFY_AT_JOB_SEAM, return_value=outcome),
    ):
        response = client.post(
            "/qa/ask", json={"question": "How much is the TOR fee per page?"}
        )
    assert response.status_code == 200
    data = response.json()
    assert data["citation_status"] == "verifying"
    assert data["citation_verification_id"]
    assert len(jobs._JOBS) == 1


def test_collapsed_stock_oos_after_generation_does_not_populate_sink():
    """Post-generation collapse to stock OOS must not schedule V2."""
    store = _FakeStore(
        [
            _chunk(
                "officials",
                "Administrative Officials",
                "DR. MARIO R. BRIONES University President",
            )
        ]
    )
    sink: dict = {}
    short_refusal = (
        "The retrieved context does not contain enough information about this topic."
    )
    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch(
            "app.services.qa.question_answering.generate_groq_answer",
            return_value=short_refusal,
        ),
        patch(
            "app.services.qa.question_answering.detect_question_intent",
            return_value="NORMAL_QA",
        ),
        patch(
            "app.services.qa.question_answering._retrieval_quality",
            return_value={"should_clarify": False, "reason": None},
        ),
        patch(
            "app.services.qa.question_answering._confidence_for",
            return_value="low",
        ),
        patch(
            "app.services.qa.question_answering._recover_factual_charter_answer",
            return_value=None,
        ),
        patch(MODE, "async_llm"),
        patch(VERIFY_AT_DISPLAY_SEAM) as mock_verify,
    ):
        result = answer_qa_question(
            "What is the campus mascot animal?",
            async_verification_sink=sink,
        )
    assert result.answer == OUT_OF_SCOPE_ANSWER
    assert result.out_of_scope_detected is True
    assert result.sources == []
    assert result.citation_status is None
    assert sink == {}
    mock_verify.assert_not_called()
