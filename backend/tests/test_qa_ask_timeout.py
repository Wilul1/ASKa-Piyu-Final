"""Tests for the /qa/ask internal timeout guard (2026-10-04 H12 fix).

Production observed a live /qa/ask request reach Heroku's ~30s router
timeout and get killed with a bare H12/503. These tests mock
app.routes.qa.answer_qa_question directly (the same seam the existing
async-citation tests already patch) and shrink
settings.qa_ask_timeout_seconds so the timeout path is exercised in
milliseconds, never real seconds.
"""

from __future__ import annotations

import time
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.routes.qa import QA_ASK_TIMEOUT_ANSWER
from app.services.qa import citation_verification_jobs as jobs
from app.services.qa.citation_verification import CandidateEvidence, VerificationOutcome
from app.services.qa.question_answering import QAResult

client = TestClient(app)


def _fast_answer_qa_question(*args, **kwargs):
    return QAResult(
        answer="Here is the answer.",
        sources=[],
        confidence="high",
        retrieved_chunks=[],
    )


def _slow_answer_qa_question(*args, **kwargs):
    # Well above the shrunk test timeout, far below any real test runner's
    # own timeout -- just needs to reliably lose the race.
    time.sleep(0.3)
    return QAResult(
        answer="Here is the slow answer that arrived too late.",
        sources=[],
        confidence="high",
        retrieved_chunks=[],
    )


def _fake_answer_qa_question_async_llm(*args, **kwargs):
    """Same fixture shape as test_qa_async_citation_verification.py's, for
    the compatibility test (F) -- confirms the timeout change doesn't
    disturb the existing async_llm citation flow when nothing times out."""
    sink = kwargs.get("async_verification_sink")
    if sink is not None:
        sink.update(
            {
                "mode": "async_llm",
                "answer": "The fee is P75 per page.",
                "candidates": [
                    CandidateEvidence(
                        citation_id="tor::0", title="Transcript of Records",
                        source_section="Sec. 1", source_filename="doc.pdf",
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
    )


# --- D: configured value is safely below Heroku's router deadline ----------


def test_qa_ask_timeout_is_configured_safely_below_herokus_30s_router_limit():
    from app.config import settings

    assert settings.qa_ask_timeout_seconds == 25.0
    assert settings.qa_ask_timeout_seconds < 30


# --- A / F: normal fast completion is completely unaffected -----------------


def test_qa_ask_fast_completion_is_unaffected_by_the_timeout_guard():
    with patch("app.routes.qa.answer_qa_question", side_effect=_fast_answer_qa_question):
        response = client.post("/qa/ask", json={"question": "What are the library hours?"})
    assert response.status_code == 200
    data = response.json()
    assert data["answer"] == "Here is the answer."
    assert data["confidence"] == "high"
    assert data.get("degraded") in (None, False)


def test_qa_ask_async_llm_citation_flow_still_works_when_nothing_times_out():
    """F: existing QA behavior remains compatible -- same scenario as
    test_qa_async_citation_verification.py's async_llm test, re-run against
    the code path that now wraps the call in asyncio.wait_for."""
    outcome = VerificationOutcome(mode="async_llm", verifier_succeeded=True, verified_citation_ids=["tor::0"])
    with patch("app.routes.qa.answer_qa_question", side_effect=_fake_answer_qa_question_async_llm), \
         patch("app.services.qa.citation_verification_jobs.verify_citations", return_value=outcome):
        response = client.post("/qa/ask", json={"question": "How much is the TOR fee per page?"})
    assert response.status_code == 200
    data = response.json()
    assert data["citation_status"] == "verifying"
    assert data["citation_verification_id"]
    job = jobs.get_job(data["citation_verification_id"])
    assert job is not None


# --- B / C / E: simulated upstream timeout ----------------------------------


def test_qa_ask_timeout_returns_degraded_response_not_500_or_raw_exception(monkeypatch):
    monkeypatch.setattr("app.routes.qa.settings.qa_ask_timeout_seconds", 0.05)
    with patch("app.routes.qa.answer_qa_question", side_effect=_slow_answer_qa_question):
        response = client.post("/qa/ask", json={"question": "What are the library hours?"})

    # E: no uncaught exception / no HTTP 500 -- a controlled 200 instead.
    assert response.status_code == 200
    data = response.json()

    # B: the slow (late) answer never appears -- we got OUR fallback, not a
    # half-finished real one.
    assert data["answer"] == QA_ASK_TIMEOUT_ANSWER
    assert "Here is the slow answer" not in data["answer"]

    # C: valid, already-supported degraded-response schema -- no new fields,
    # no secrets/stack traces, no raw exception text.
    assert data["confidence"] == "low"
    assert data["degraded"] is True
    assert data["sources"] == []
    assert data["citations"] == []
    assert "Traceback" not in data["answer"]
    assert "Error" not in data["answer"]


def test_qa_ask_timeout_never_schedules_an_orphaned_citation_job(monkeypatch):
    """Requirement 6: a timed-out request must not create broken/orphaned
    citation jobs -- the response must carry no verification id at all
    (response_model_exclude_none drops it entirely when None)."""
    monkeypatch.setattr("app.routes.qa.settings.qa_ask_timeout_seconds", 0.05)
    with patch("app.routes.qa.answer_qa_question", side_effect=_slow_answer_qa_question):
        response = client.post("/qa/ask", json={"question": "What are the library hours?"})
    data = response.json()
    assert "citation_verification_id" not in data
    assert "citation_status" not in data


def test_qa_ask_timeout_message_is_friendly_and_retry_oriented(monkeypatch):
    monkeypatch.setattr("app.routes.qa.settings.qa_ask_timeout_seconds", 0.05)
    with patch("app.routes.qa.answer_qa_question", side_effect=_slow_answer_qa_question):
        response = client.post("/qa/ask", json={"question": "What are the library hours?"})
    answer = response.json()["answer"].lower()
    assert "again" in answer or "retry" in answer


def test_qa_ask_unrelated_exceptions_still_return_500_not_swallowed_by_the_timeout_guard():
    """Guard against the new nested try/except accidentally widening to
    catch real errors -- a genuine failure in answer_qa_question must still
    surface as the existing 500 behavior, not a silent degraded 200."""

    def _boom(*args, **kwargs):
        raise RuntimeError("synthetic failure unrelated to timing")

    with patch("app.routes.qa.answer_qa_question", side_effect=_boom):
        response = client.post("/qa/ask", json={"question": "What are the library hours?"})
    assert response.status_code == 500
    assert "synthetic failure" not in response.text
