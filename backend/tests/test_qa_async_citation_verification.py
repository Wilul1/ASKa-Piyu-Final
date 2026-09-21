"""Integration tests for the async Citation V2 local prototype:
question_answering._display_sources_for_answer's async_shadow/async_llm
branches, the /qa/ask and /qa/citation-verifications/{id} routes, and the
architectural latency-decoupling property. No provider calls -- the
verifier is mocked at the exact names each call site imports.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from unittest.mock import patch

import pytest
from fastapi import BackgroundTasks
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.main import app
from app.services.chroma_store import RetrievedChunk
from app.services.qa import citation_verification_jobs as jobs
from app.services.qa.citation_verification import CandidateEvidence, VerificationOutcome
from app.services.qa.question_answering import QAResult, _display_sources_for_answer

VERIFY_AT_DISPLAY_SEAM = "app.services.qa.citation_verification.verify_citations"
VERIFY_AT_JOB_SEAM = "app.services.qa.citation_verification_jobs.verify_citations"
MODE = "app.services.qa.question_answering.settings.citation_verification_mode"

client = TestClient(app)


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


# --- _display_sources_for_answer: async mode wiring ------------------------


def test_async_llm_mode_returns_zero_citations_immediately_never_v1():
    chunk = _chunk("tor", "Transcript of Records", "Fee: P75/page.")
    answer = "The fee is P75 per page."
    with patch(MODE, "async_llm"):
        result = _display_sources_for_answer([chunk], answer)
    assert result == []


def test_async_llm_mode_populates_sink_with_frozen_inputs():
    chunk = _chunk("tor", "Transcript of Records", "Fee: P75/page.")
    answer = "The fee is P75 per page."
    sink: dict = {}
    with patch(MODE, "async_llm"):
        _display_sources_for_answer([chunk], answer, async_verification_sink=sink)
    assert sink["mode"] == "async_llm"
    assert sink["answer"] == answer
    assert len(sink["candidates"]) == 1
    assert isinstance(sink["candidates"][0], CandidateEvidence)
    assert sink["candidates"][0].citation_id == "tor::0"


def test_async_llm_mode_never_calls_verify_citations_inline():
    chunk = _chunk("tor", "Transcript of Records", "Fee: P75/page.")
    answer = "The fee is P75 per page."
    with patch(VERIFY_AT_DISPLAY_SEAM) as mock_verify, patch(MODE, "async_llm"):
        _display_sources_for_answer([chunk], answer)
    mock_verify.assert_not_called()


def test_async_shadow_mode_shows_v1_immediately_and_never_blocks_on_verifier():
    chunk = _chunk("tor", "Transcript of Records", "Fee: P75/page. Processing time: 5 minutes.")
    answer = "The fee is P75 per page. Processing time is 5 minutes."
    with patch(MODE, "lexical"):
        v1_only = _display_sources_for_answer([chunk], answer)
    with patch(VERIFY_AT_DISPLAY_SEAM) as mock_verify, patch(MODE, "async_shadow"):
        shadow_result = _display_sources_for_answer([chunk], answer)
    mock_verify.assert_not_called()
    assert shadow_result == v1_only


def test_async_shadow_mode_also_populates_sink_for_diagnostics():
    chunk = _chunk("tor", "Transcript of Records", "Fee: P75/page.")
    answer = "The fee is P75 per page."
    sink: dict = {}
    with patch(MODE, "async_shadow"):
        _display_sources_for_answer([chunk], answer, async_verification_sink=sink)
    assert sink["mode"] == "async_shadow"


def test_async_shadow_sink_captures_v1_displayed_citation_ids_only():
    """The sink's v1_citation_ids must be exactly the ids V1 actually
    decided to display (same identity formula as the displayed sources
    themselves) -- not all retrieved candidates, not generation context."""
    displayed_chunk = _chunk("tor", "Transcript of Records", "Fee: P75/page.")
    unrelated_chunk = _chunk("library", "Library Hours", "Open 8am to 5pm on weekdays.")
    answer = "The fee is P75 per page."
    sink: dict = {}
    with patch(MODE, "async_shadow"):
        _display_sources_for_answer(
            [displayed_chunk, unrelated_chunk], answer, async_verification_sink=sink
        )
    # V1's lexical selector should only match the fee chunk, not the
    # unrelated library-hours chunk -- confirming v1_citation_ids reflects
    # DISPLAYED citations, not every candidate passed in.
    assert sink["v1_citation_ids"] == ["tor::0"]


def test_async_shadow_with_v1_citations_has_no_client_facing_status():
    """async_shadow displays V1's lexical citations immediately, and
    citation_status must be None -- never "verifying" -- because
    async_shadow's verification_id is withheld from the client (see
    citation_verification_jobs._CLIENT_POLLABLE_ASYNC_MODES), so a non-None
    status here would describe a job the client can never poll."""
    from app.services.qa.question_answering import _citation_status_after_sources

    chunk = _chunk("tor", "Transcript of Records", "Fee: P75/page.")
    answer = "The fee is P75 per page."
    sink: dict = {}
    with patch(MODE, "async_shadow"):
        sources = _display_sources_for_answer([chunk], answer, async_verification_sink=sink)
        status = _citation_status_after_sources(sink)
    assert sources  # V1's lexical citations, displayed immediately
    assert status is None
    assert sink["mode"] == "async_shadow"  # the diagnostic job is still scheduled


def test_async_shadow_with_zero_v1_citations_has_no_client_facing_status():
    """The exact bug this fix targets: when V1 finds nothing to display,
    citation_status must still be None (not "verifying"), because
    async_shadow never hands the client a verification_id to poll -- a
    "verifying" status here would leave Flutter showing "Verifying
    sources..." forever with no way to ever resolve it (see
    evaluateCitationPollTick's polling trigger, which only fires when a
    verification_id is present)."""
    from app.services.qa.question_answering import _citation_status_after_sources

    chunk = _chunk("library", "Library Hours", "The library is open eight to five on weekdays.")
    answer = "To renew your student ID, visit the registrar within thirty days of enrollment."
    sink: dict = {}
    with patch(MODE, "async_shadow"):
        sources = _display_sources_for_answer([chunk], answer, async_verification_sink=sink)
        status = _citation_status_after_sources(sink)
    assert sources == []  # V1 found nothing supporting -- the exact stuck-state trigger
    assert status is None  # must NOT be "verifying"
    assert sink.get("mode") == "async_shadow"  # background verification still runs regardless


def test_zero_claims_or_zero_candidates_leaves_sink_empty_no_job_needed():
    sink: dict = {}
    with patch(MODE, "async_llm"):
        result = _display_sources_for_answer([], "Hi there!", async_verification_sink=sink)
    assert result == []
    assert sink == {}


# --- QAResult.citation_status ----------------------------------------------


def test_citation_status_is_none_for_lexical_mode():
    chunk = _chunk("tor", "TOR", "Fee: P75.")
    with patch(MODE, "lexical"):
        from app.services.qa.question_answering import _citation_status_after_sources

        status = _citation_status_after_sources(None)
    assert status is None


def test_citation_status_verifying_when_sink_populated():
    from app.services.qa.question_answering import _citation_status_after_sources

    with patch(MODE, "async_llm"):
        status = _citation_status_after_sources({"mode": "async_llm", "answer": "x", "candidates": []})
    assert status == "verifying"


def test_citation_status_verification_unavailable_when_sink_empty():
    from app.services.qa.question_answering import _citation_status_after_sources

    with patch(MODE, "async_llm"):
        status = _citation_status_after_sources({})
    assert status == "verification_unavailable"


# --- Route-level: /qa/ask initial response ---------------------------------


def _fake_answer_qa_question_async_llm(*args, **kwargs):
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


def test_qa_ask_async_llm_initial_response_has_empty_citations_and_a_verification_id():
    # NOTE: fastapi.testclient.TestClient runs BackgroundTasks synchronously
    # as part of the same ASGI call before .post() returns (see the
    # architectural-latency-decoupling test below for the full explanation
    # and the direct-route-call test that actually proves decoupling) -- so
    # by the time this assertion runs, the scheduled job has ALREADY been
    # executed. The verifier is mocked here so that execution is fast and
    # deterministic rather than depending on the real fail-closed
    # unconfigured-provider path.
    outcome = VerificationOutcome(mode="async_llm", verifier_succeeded=True, verified_citation_ids=["tor::0"])
    with patch("app.routes.qa.answer_qa_question", side_effect=_fake_answer_qa_question_async_llm), \
         patch(VERIFY_AT_JOB_SEAM, return_value=outcome):
        response = client.post("/qa/ask", json={"question": "How much is the TOR fee per page?"})
    assert response.status_code == 200
    data = response.json()
    assert data["sources"] == []
    assert data["citations"] == []
    assert data["citation_status"] == "verifying"
    assert data["citation_verification_id"]
    # The id resolves to a real job server-side, whose terminal state
    # reflects the (mocked) verifier outcome above.
    job = jobs.get_job(data["citation_verification_id"])
    assert job is not None
    assert job.status == jobs.JobStatus.VERIFIED


def _fake_answer_qa_question_async_shadow(sources, v1_answer="The fee is P75 per page.", v1_citation_ids=None):
    """Builds a fake answer_qa_question for async_shadow route tests that
    computes citation_status through the REAL _citation_status_after_sources
    (not a hand-picked literal), so these tests exercise the actual
    integration point the fix changed, not just a stand-in. v1_citation_ids
    mirrors the real _display_sources_for_answer's sink population -- see
    question_answering.py's async branch -- defaulting to ["tor::0"] (the
    one candidate this fake always builds) unless a test overrides it (e.g.
    with [] for the zero-V1-citations regression case)."""

    def _fake(*args, **kwargs):
        from app.services.qa.question_answering import _citation_status_after_sources

        sink = kwargs.get("async_verification_sink")
        if sink is not None:
            sink.update(
                {
                    "mode": "async_shadow",
                    "answer": v1_answer,
                    "candidates": [
                        CandidateEvidence(
                            citation_id="tor::0", title="Transcript of Records",
                            source_section="Sec. 1", source_filename="doc.pdf",
                            text="Fee: P75/page.",
                        )
                    ],
                    "v1_citation_ids": ["tor::0"] if v1_citation_ids is None else v1_citation_ids,
                }
            )
        return QAResult(
            answer=v1_answer,
            sources=sources,
            confidence="high",
            retrieved_chunks=[],
            citation_status=_citation_status_after_sources(sink),
        )

    return _fake


def test_qa_ask_async_shadow_with_v1_sources_never_returns_verification_id_or_status():
    outcome = VerificationOutcome(mode="shadow", verifier_succeeded=True, verified_citation_ids=["tor::0"])
    sources = [
        {
            "title": "Transcript of Records",
            "path": "doc.pdf",
            "citation_id": "tor::0",
            "source_section": "Sec. 1",
            "source_filename": "doc.pdf",
        }
    ]
    with patch(MODE, "async_shadow"), \
         patch("app.routes.qa.answer_qa_question", side_effect=_fake_answer_qa_question_async_shadow(sources)), \
         patch(VERIFY_AT_JOB_SEAM, return_value=outcome):
        response = client.post("/qa/ask", json={"question": "How much is the TOR fee per page?"})
    assert response.status_code == 200
    data = response.json()
    assert data["sources"]  # V1 lexical citations displayed immediately, unaffected by this fix
    assert "citation_status" not in data  # None -> excluded by response_model_exclude_none=True
    assert "citation_verification_id" not in data  # withheld, exactly as before this fix
    # The diagnostic shadow job still ran server-side -- only its exposure
    # to the client changed, not whether it runs at all.
    assert len(jobs._JOBS) == 1
    (only_job,) = jobs._JOBS.values()
    assert only_job.status == jobs.JobStatus.VERIFIED


def test_qa_ask_async_shadow_with_zero_v1_sources_never_gets_stuck_verifying(caplog):
    """The route-level regression test for the reported bug: previously
    citation_status could be "verifying" here with no verification_id for
    Flutter to ever poll, permanently stuck. Now it must be absent. Also
    covers the observability-patch regression case: even with zero V1
    sources, the diagnostic event must still be emitted (with v1_count=0
    and the real V2 outcome) -- it must never look like no job ran."""
    outcome = VerificationOutcome(mode="shadow", verifier_succeeded=True, verified_citation_ids=[])
    with caplog.at_level(logging.INFO, logger="app.services.qa.citation_verification_jobs"), \
         patch(MODE, "async_shadow"), \
         patch(
             "app.routes.qa.answer_qa_question",
             side_effect=_fake_answer_qa_question_async_shadow([], v1_citation_ids=[]),
         ), \
         patch(VERIFY_AT_JOB_SEAM, return_value=outcome):
        response = client.post("/qa/ask", json={"question": "How much is the TOR fee per page?"})
    assert response.status_code == 200
    data = response.json()
    assert data["sources"] == []
    assert data["citations"] == []
    assert "citation_status" not in data  # THE FIX: never "verifying" with no way to resolve it
    assert "citation_verification_id" not in data
    # Background verification still ran despite V1 finding nothing to display.
    assert len(jobs._JOBS) == 1
    events = [
        record.getMessage() for record in caplog.records
        if record.getMessage().startswith("citation_verification_async_completed ")
    ]
    assert len(events) == 1
    event = json.loads(events[0][len("citation_verification_async_completed ") :])
    assert event["v1_citation_ids"] == []
    assert event["v1_count"] == 0
    assert event["v2_citation_ids"] == []  # the real (mocked) V2 outcome for this test


def test_qa_ask_lexical_mode_response_has_no_new_fields_at_all():
    from app.services.qa.question_answering import QAResult

    def fake(*args, **kwargs):
        return QAResult(
            answer="Answer text.", sources=[], confidence="high", retrieved_chunks=[],
        )  # citation_status defaults to None, exactly as it did before this prototype existed

    with patch("app.routes.qa.answer_qa_question", side_effect=fake):
        response = client.post("/qa/ask", json={"question": "Any question."})
    assert response.status_code == 200
    data = response.json()
    # response_model_exclude_none=True: absent fields simply don't appear.
    assert "citation_status" not in data
    assert "citation_verification_id" not in data


def test_lexical_mode_emits_no_async_shadow_diagnostic_event(caplog):
    """Lexical mode never populates async_verification_sink at all (an
    empty sink), so schedule_verification() short-circuits before any job
    is created -- run_verification_job (and therefore the new diagnostic
    event) is never reached."""
    from app.services.qa.question_answering import QAResult

    def fake(*args, **kwargs):
        return QAResult(answer="Answer text.", sources=[], confidence="high", retrieved_chunks=[])

    with caplog.at_level(logging.INFO, logger="app.services.qa.citation_verification_jobs"), \
         patch(MODE, "lexical"), \
         patch("app.routes.qa.answer_qa_question", side_effect=fake):
        response = client.post("/qa/ask", json={"question": "Any question."})
    assert response.status_code == 200
    assert len(jobs._JOBS) == 0
    events = [
        record.getMessage() for record in caplog.records
        if record.getMessage().startswith("citation_verification_async_completed ")
    ]
    assert events == []


# --- Poll endpoint -----------------------------------------------------------


def test_poll_endpoint_unknown_id_is_safe_never_a_500_never_fabricated():
    response = client.get("/qa/citation-verifications/totally-made-up-id")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "unknown"
    assert data["citations"] == []


def test_poll_endpoint_malformed_id_is_safe():
    response = client.get("/qa/citation-verifications/%00%00not-a-real-uuid")
    assert response.status_code == 200
    assert response.json()["status"] == "unknown"


def test_poll_endpoint_random_uuid_never_reveals_another_jobs_result():
    real_outcome = VerificationOutcome(mode="async_llm", verifier_succeeded=True, verified_citation_ids=["tor::0"])
    real_vid = jobs.create_job(
        answer="X",
        candidates=[CandidateEvidence(citation_id="tor::0", title="T", source_section=None, source_filename=None, text="secret internal text")],
        mode="async_llm",
    )
    with patch(VERIFY_AT_JOB_SEAM, return_value=real_outcome):
        jobs.run_verification_job(real_vid)

    import uuid
    guessed = uuid.uuid4().hex
    response = client.get(f"/qa/citation-verifications/{guessed}")
    assert response.json()["status"] == "unknown"
    assert response.json()["citations"] == []
    # The real job is unaffected and still readable by its own id.
    real_response = client.get(f"/qa/citation-verifications/{real_vid}")
    assert real_response.json()["status"] == "verified"


def test_poll_endpoint_never_exposes_candidate_text():
    outcome = VerificationOutcome(mode="async_llm", verifier_succeeded=True, verified_citation_ids=["tor::0"])
    vid = jobs.create_job(
        answer="X",
        candidates=[CandidateEvidence(citation_id="tor::0", title="T", source_section="S", source_filename="f.pdf", text="THIS MUST NEVER LEAK")],
        mode="async_llm",
    )
    with patch(VERIFY_AT_JOB_SEAM, return_value=outcome):
        jobs.run_verification_job(vid)
    response = client.get(f"/qa/citation-verifications/{vid}")
    assert "THIS MUST NEVER LEAK" not in response.text


def test_poll_endpoint_verified_status():
    outcome = VerificationOutcome(mode="async_llm", verifier_succeeded=True, verified_citation_ids=["tor::0"])
    vid = jobs.create_job(
        answer="X",
        candidates=[CandidateEvidence(citation_id="tor::0", title="TOR", source_section="Sec 1", source_filename="f.pdf", text="t")],
        mode="async_llm",
    )
    with patch(VERIFY_AT_JOB_SEAM, return_value=outcome):
        jobs.run_verification_job(vid)
    data = client.get(f"/qa/citation-verifications/{vid}").json()
    assert data["status"] == "verified"
    assert data["citations"] == [{"citation_id": "tor::0", "title": "TOR", "source_section": "Sec 1", "source_filename": "f.pdf"}]


def test_poll_endpoint_no_verified_support_status():
    outcome = VerificationOutcome(mode="async_llm", verifier_succeeded=True, verified_citation_ids=[])
    vid = jobs.create_job(answer="X", candidates=[CandidateEvidence(citation_id="a::0", title="A", source_section=None, source_filename=None, text="t")], mode="async_llm")
    with patch(VERIFY_AT_JOB_SEAM, return_value=outcome):
        jobs.run_verification_job(vid)
    data = client.get(f"/qa/citation-verifications/{vid}").json()
    assert data["status"] == "no_verified_support"
    assert data["citations"] == []


def test_poll_endpoint_failed_status_never_shows_v1_fallback_citations():
    outcome = VerificationOutcome(mode="async_llm", verifier_succeeded=False, failure_reason="provider_timeout")
    vid = jobs.create_job(answer="X", candidates=[CandidateEvidence(citation_id="a::0", title="A", source_section=None, source_filename=None, text="t")], mode="async_llm")
    with patch(VERIFY_AT_JOB_SEAM, return_value=outcome):
        jobs.run_verification_job(vid)
    data = client.get(f"/qa/citation-verifications/{vid}").json()
    assert data["status"] == "failed"
    assert data["citations"] == []


def test_poll_endpoint_pending_before_run():
    vid = jobs.create_job(answer="X", candidates=[CandidateEvidence(citation_id="a::0", title="A", source_section=None, source_filename=None, text="t")], mode="async_llm")
    data = client.get(f"/qa/citation-verifications/{vid}").json()
    assert data["status"] == "pending"
    assert data["citations"] == []


# --- Out-of-order / concurrency at the route+job level ----------------------


def test_out_of_order_completion_attaches_only_to_the_right_id():
    outcome_a = VerificationOutcome(mode="async_llm", verifier_succeeded=True, verified_citation_ids=["a::0"])
    outcome_b = VerificationOutcome(mode="async_llm", verifier_succeeded=True, verified_citation_ids=["b::0"])
    vid_a = jobs.create_job(answer="A", candidates=[CandidateEvidence(citation_id="a::0", title="A", source_section=None, source_filename=None, text="t")], mode="async_llm")
    vid_b = jobs.create_job(answer="B", candidates=[CandidateEvidence(citation_id="b::0", title="B", source_section=None, source_filename=None, text="t")], mode="async_llm")

    with patch(VERIFY_AT_JOB_SEAM, return_value=outcome_b):
        jobs.run_verification_job(vid_b)  # B (faster) finishes first
    assert client.get(f"/qa/citation-verifications/{vid_a}").json()["status"] == "pending"
    assert client.get(f"/qa/citation-verifications/{vid_b}").json()["status"] == "verified"

    with patch(VERIFY_AT_JOB_SEAM, return_value=outcome_a):
        jobs.run_verification_job(vid_a)  # A (slower) finishes later
    data_a = client.get(f"/qa/citation-verifications/{vid_a}").json()
    data_b = client.get(f"/qa/citation-verifications/{vid_b}").json()
    assert data_a["citations"][0]["citation_id"] == "a::0"
    assert data_b["citations"][0]["citation_id"] == "b::0"


# --- Architectural latency-decoupling -----------------------------------
#
# NOTE: fastapi.testclient.TestClient bridges the whole ASGI call
# synchronously, which includes Starlette's BackgroundTasks execution
# (they run inside Response.__call__, AFTER the body is sent but BEFORE the
# ASGI coroutine returns control) -- empirically confirmed separately: a
# TestClient.post() to a route that schedules a 2s sleep via
# BackgroundTasks.add_task takes ~2s to return, NOT the fast path a real
# deployed server's HTTP client would see (a real client receives the
# response bytes once they hit the socket, independent of when the
# Python coroutine that produced them finishes). Measuring wall-clock time
# through TestClient would therefore be misleading here. Instead, this test
# calls the route COROUTINE directly (bypassing TestClient's ASGI bridge
# entirely) and asserts BackgroundTasks.add_task only SCHEDULES the slow
# verifier -- it is never awaited/executed as part of building the
# response -- which is the actual property that makes a real deployment's
# response latency independent of verifier latency.


def _fake_request() -> Request:
    return Request({"type": "http", "client": ("127.0.0.1", 12345), "headers": []})


def test_qa_ask_route_never_awaits_the_verifier_while_building_its_response():
    from app.models.schemas import QAAskRequest
    from app.routes.qa import qa_ask

    slow_call_happened = {"value": False}

    def slow_verifier(*args, **kwargs):
        slow_call_happened["value"] = True
        time.sleep(3)
        return VerificationOutcome(mode="async_llm", verifier_succeeded=True, verified_citation_ids=["tor::0"])

    background_tasks = BackgroundTasks()
    payload = QAAskRequest(question="How much is the TOR fee per page?")

    async def _call_route():
        return await qa_ask(payload, _fake_request(), background_tasks, debug=None, current_user=None)

    async def _call_route_then_run_background_tasks():
        resp = await _call_route()
        return resp

    with patch("app.routes.qa.answer_qa_question", side_effect=_fake_answer_qa_question_async_llm), \
         patch(VERIFY_AT_JOB_SEAM, side_effect=slow_verifier):
        started = time.perf_counter()
        response = asyncio.run(_call_route_then_run_background_tasks())
        elapsed = time.perf_counter() - started

        # The route coroutine itself must return fast -- it only SCHEDULED
        # the slow verifier via BackgroundTasks, never called/awaited it.
        assert elapsed < 1.0, f"route took {elapsed:.2f}s -- it must not wait for the verifier"
        assert slow_call_happened["value"] is False
        assert response.citations == []
        assert response.citation_status == "verifying"
        assert response.citation_verification_id

        # Now actually run what BackgroundTasks would run after the response
        # is sent (Starlette calls `await background_tasks()`) and confirm
        # the slow verifier DOES eventually resolve the same job. Still
        # inside the patch context, exactly like the real background
        # execution would still be running against live configuration.
        asyncio.run(background_tasks())

    assert slow_call_happened["value"] is True
    job = jobs.get_job(response.citation_verification_id)
    assert job.status == jobs.JobStatus.VERIFIED
