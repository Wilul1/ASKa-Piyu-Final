"""Real-seam integration tests for the async Citation V2 job store.

Unlike test_citation_verification_jobs.py (which mocks verify_citations()
itself at the job-store import location), these tests deliberately do NOT
mock verify_citations() -- they exercise the REAL, unmodified
citation_verification.verify_citations() end to end, mocking only the
lowest-level provider transport (httpx.Client), exactly matching the
existing convention already established in test_citation_verification.py.

This file exists specifically to catch BLOCKER-1 (async mode strings never
reaching the real verifier because citation_verification.verify_citations()
only recognizes "shadow"/"llm", not "async_shadow"/"async_llm") and to make
sure it cannot silently recur: every test here would have FAILED against
the pre-repair code (confirmed manually before writing the fix -- see
citation_v2_async_independent_review.json for the original evidence).
"""

from __future__ import annotations

import json
import logging
from unittest.mock import MagicMock, patch

import pytest

from app.services.qa import citation_verification_jobs as jobs
from app.services.qa.citation_verification import CandidateEvidence

CITATION_MODULE = "app.services.qa.citation_verification"
JOBS_LOGGER = "app.services.qa.citation_verification_jobs"


def _event_payloads(caplog: pytest.LogCaptureFixture) -> list[dict]:
    """Extract every citation_verification_async_completed diagnostic event
    logged during the test, parsed from the JSON each one carries."""
    payloads = []
    for record in caplog.records:
        message = record.getMessage()
        if message.startswith("citation_verification_async_completed "):
            payloads.append(json.loads(message[len("citation_verification_async_completed ") :]))
    return payloads


@pytest.fixture(autouse=True)
def _reset_job_store():
    jobs.reset_jobs_store()
    yield
    jobs.reset_jobs_store()


def _ev(citation_id: str, title: str, text: str) -> CandidateEvidence:
    return CandidateEvidence(
        citation_id=citation_id, title=title, source_section="Sec. 1", source_filename="doc.pdf", text=text
    )


def _configured_provider():
    return patch.multiple(
        f"{CITATION_MODULE}.settings",
        groq_api_key="test-key",
        llm_base_url="https://openrouter.ai/api/v1/chat/completions",
        groq_model="test-model",
        groq_timeout_seconds=5.0,
    )


def _mock_httpx_client_returning(payload: dict) -> MagicMock:
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {"choices": [{"message": {"content": json.dumps(payload)}}]}
    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False
    mock_client.post.return_value = mock_response
    return mock_client


# --- async_llm: real success path -------------------------------------------


def test_async_llm_real_verifier_path_produces_verified_citation():
    """The end-to-end high-value test: async_llm -> job scheduled -> real
    verify_citations() actually invoked (not skipped by a mode mismatch)
    -> mocked provider approves a citation -> job becomes VERIFIED with
    that allowlisted citation. This test FAILS against the pre-repair code
    (mock_client.post would never be called)."""
    candidates = [_ev("tor::1", "Transcript of Records", "Fee: P75 per page.")]
    answer = "The fee is P75 per page."
    mock_client = _mock_httpx_client_returning(
        {"claims": [{"claim_id": "c1", "supporting_citation_ids": ["tor::1"]}]}
    )

    vid = jobs.create_job(answer=answer, candidates=candidates, mode="async_llm")
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        jobs.run_verification_job(vid)

    mock_client.post.assert_called_once()  # the real provider path WAS reached
    job = jobs.get_job(vid)
    assert job.status == jobs.JobStatus.VERIFIED
    assert [c.citation_id for c in job.verified_citations] == ["tor::1"]


def test_async_llm_full_flow_through_schedule_and_poll_apis():
    """Same real seam, but driven through schedule_verification() and
    status_and_citations_for_poll() -- the exact functions app.routes.qa
    actually calls -- rather than the lower-level job functions directly."""
    candidates = [_ev("tor::1", "Transcript of Records", "Fee: P75 per page.")]
    answer = "The fee is P75 per page."
    mock_client = _mock_httpx_client_returning(
        {"claims": [{"claim_id": "c1", "supporting_citation_ids": ["tor::1"]}]}
    )

    class _ImmediateBackgroundTasks:
        """A local test harness's replacement for FastAPI's BackgroundTasks
        that runs its task immediately rather than after a response --
        acceptable here since this test only cares about the job's final
        state, not response-timing (that property is covered separately in
        test_qa_async_citation_verification.py's latency-decoupling test)."""

        def add_task(self, func, *args, **kwargs):
            func(*args, **kwargs)

    sink = {"mode": "async_llm", "answer": answer, "candidates": candidates}
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        vid = jobs.schedule_verification(_ImmediateBackgroundTasks(), sink)

    assert vid is not None
    status, citations = jobs.status_and_citations_for_poll(vid)
    assert status == "verified"
    assert [c.citation_id for c in citations] == ["tor::1"]


# --- async_llm: real fail-closed path ---------------------------------------


def test_async_llm_real_verifier_path_fails_closed_on_malformed_provider_output():
    """Real verify_citations(), mocked provider returns invalid JSON ->
    FAILED, zero citations, never a fabricated 'verified' result and never
    a fallback to any lexical/V1 citation."""
    candidates = [_ev("tor::1", "Transcript of Records", "Fee: P75 per page.")]
    answer = "The fee is P75 per page."
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {"choices": [{"message": {"content": "not valid json{{{"}}]}
    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False
    mock_client.post.return_value = mock_response

    vid = jobs.create_job(answer=answer, candidates=candidates, mode="async_llm")
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        jobs.run_verification_job(vid)

    mock_client.post.assert_called_once()  # real path was reached, not skipped
    job = jobs.get_job(vid)
    assert job.status == jobs.JobStatus.FAILED
    assert job.verified_citations == []
    status, citations = jobs.status_and_citations_for_poll(vid)
    assert status == "failed"
    assert citations == []  # never a lexical/V1 fallback surfaced here


def test_async_llm_real_verifier_path_fails_closed_on_hallucinated_citation_id():
    """The provider returns a citation_id that is NOT in the authorized
    candidate allowlist -- verify_citations()'s own existing strict
    validation must reject the whole response, and this rejection must
    propagate correctly through the real translated-mode path."""
    candidates = [_ev("tor::1", "Transcript of Records", "Fee: P75 per page.")]
    answer = "The fee is P75 per page."
    mock_client = _mock_httpx_client_returning(
        {"claims": [{"claim_id": "c1", "supporting_citation_ids": ["not-an-authorized-id"]}]}
    )

    vid = jobs.create_job(answer=answer, candidates=candidates, mode="async_llm")
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        jobs.run_verification_job(vid)

    job = jobs.get_job(vid)
    assert job.status == jobs.JobStatus.FAILED
    assert job.verified_citations == []


# --- async_shadow: real path, diagnostic only -------------------------------


def test_async_shadow_real_verifier_path_actually_executes():
    """async_shadow must ALSO reach the real verifier (translated to
    'shadow'), not just async_llm -- this was equally broken pre-repair."""
    candidates = [_ev("tor::1", "Transcript of Records", "Fee: P75 per page.")]
    answer = "The fee is P75 per page."
    mock_client = _mock_httpx_client_returning(
        {"claims": [{"claim_id": "c1", "supporting_citation_ids": ["tor::1"]}]}
    )

    vid = jobs.create_job(answer=answer, candidates=candidates, mode="async_shadow")
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        jobs.run_verification_job(vid)

    mock_client.post.assert_called_once()
    job = jobs.get_job(vid)
    assert job.status == jobs.JobStatus.VERIFIED  # the diagnostic result is real


def test_async_shadow_diagnostic_result_never_reaches_the_client_via_schedule():
    """End-to-end through schedule_verification(): the job runs for real
    and resolves VERIFIED server-side, but its id is withheld from the
    caller -- the client-facing contract (what app.routes.qa returns) never
    exposes it, so lexical citations displayed to the user are unaffected
    regardless of what the background verifier concluded."""
    candidates = [_ev("tor::1", "Transcript of Records", "Fee: P75 per page.")]
    answer = "The fee is P75 per page."
    mock_client = _mock_httpx_client_returning(
        {"claims": [{"claim_id": "c1", "supporting_citation_ids": ["tor::1"]}]}
    )

    class _ImmediateBackgroundTasks:
        def add_task(self, func, *args, **kwargs):
            func(*args, **kwargs)

    sink = {"mode": "async_shadow", "answer": answer, "candidates": candidates}
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        client_facing_id = jobs.schedule_verification(_ImmediateBackgroundTasks(), sink)

    assert client_facing_id is None  # nothing for Flutter to poll
    # But the real job DID run and produce a real diagnostic result,
    # confirming this is "hidden from the client", not "never happened".
    assert mock_client.post.called


# --- async_shadow observability: terminal diagnostic event ------------------
#
# All tests below use the REAL async orchestration path (create_job() ->
# run_verification_job() -> the real, unmocked verify_citations()) -- only
# the provider transport (httpx.Client) is mocked, exactly like the tests
# above. They prove the new citation_verification_async_completed log event
# this task adds, without changing any verification/job-state behavior.


def test_verified_emits_exactly_one_terminal_event_with_correct_v1_and_v2_ids(caplog):
    candidates = [_ev("tor::1", "Transcript of Records", "Fee: P75 per page.")]
    answer = "The fee is P75 per page."
    mock_client = _mock_httpx_client_returning(
        {"claims": [{"claim_id": "c1", "supporting_citation_ids": ["tor::1"]}]}
    )

    vid = jobs.create_job(
        answer=answer, candidates=candidates, mode="async_shadow", v1_citation_ids=["tor::1"]
    )
    with caplog.at_level(logging.INFO, logger=JOBS_LOGGER), \
         patch("httpx.Client", return_value=mock_client), _configured_provider():
        jobs.run_verification_job(vid)

    job = jobs.get_job(vid)
    assert job.status == jobs.JobStatus.VERIFIED

    events = _event_payloads(caplog)
    assert len(events) == 1
    event = events[0]
    assert event["verification_id"] == vid
    assert event["mode"] == "async_shadow"
    assert event["status"] == "verified"
    assert event["v1_citation_ids"] == ["tor::1"]
    assert event["v2_citation_ids"] == ["tor::1"]
    assert event["v1_count"] == 1
    assert event["v2_count"] == 1
    assert event["failure_category"] is None
    assert isinstance(event["duration_ms"], (int, float))
    assert event["duration_ms"] >= 0
    # No source/claim/answer text anywhere in the logged structured payload.
    raw = json.dumps(event)
    assert answer not in raw
    assert "Fee: P75 per page." not in raw
    assert "Transcript of Records" not in raw


def test_no_verified_support_emits_event_with_empty_v2_ids_and_safe_category(caplog):
    candidates = [_ev("tor::1", "Transcript of Records", "Fee: P75 per page.")]
    answer = "The fee is P75 per page."
    mock_client = _mock_httpx_client_returning(
        {"claims": [{"claim_id": "c1", "supporting_citation_ids": []}]}
    )

    vid = jobs.create_job(
        answer=answer, candidates=candidates, mode="async_shadow", v1_citation_ids=["tor::1"]
    )
    with caplog.at_level(logging.INFO, logger=JOBS_LOGGER), \
         patch("httpx.Client", return_value=mock_client), _configured_provider():
        jobs.run_verification_job(vid)

    job = jobs.get_job(vid)
    assert job.status == jobs.JobStatus.NO_VERIFIED_SUPPORT

    events = _event_payloads(caplog)
    assert len(events) == 1
    event = events[0]
    assert event["status"] == "no_verified_support"
    assert event["v1_citation_ids"] == ["tor::1"]
    assert event["v2_citation_ids"] == []
    assert event["v1_count"] == 1
    assert event["v2_count"] == 0
    assert event["failure_category"] == "no_verified_support"
    raw = json.dumps(event)
    assert answer not in raw


def test_failed_emits_event_with_bounded_category_and_no_provider_body(caplog):
    """Lower-level mocked provider failure: malformed JSON content, so
    verify_citations() itself produces the FAILED outcome, not a bug in this
    module. failure_category must be one of the small bounded set, and the
    raw malformed content / exception text must never appear in the event."""
    candidates = [_ev("tor::1", "Transcript of Records", "Fee: P75 per page.")]
    answer = "The fee is P75 per page."
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "not valid json{{{ SENSITIVE_PROVIDER_TOKEN_xyz"}}]
    }
    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False
    mock_client.post.return_value = mock_response

    vid = jobs.create_job(
        answer=answer, candidates=candidates, mode="async_shadow", v1_citation_ids=["tor::1"]
    )
    with caplog.at_level(logging.INFO, logger=JOBS_LOGGER), \
         patch("httpx.Client", return_value=mock_client), _configured_provider():
        jobs.run_verification_job(vid)

    job = jobs.get_job(vid)
    assert job.status == jobs.JobStatus.FAILED

    events = _event_payloads(caplog)
    assert len(events) == 1
    event = events[0]
    assert event["status"] == "failed"
    assert event["v1_citation_ids"] == ["tor::1"]
    assert event["v2_citation_ids"] == []
    assert event["failure_category"] in {"provider_error", "invalid_response", "internal_error", "unknown"}
    raw = json.dumps(event)
    assert "SENSITIVE_PROVIDER_TOKEN_xyz" not in raw
    assert "not valid json" not in raw
    assert answer not in raw


def test_zero_v1_citations_still_logs_v1_count_zero_and_the_real_v2_outcome(caplog):
    """The critical regression case this whole patch exists to make
    observable: async_shadow with V1 displaying nothing must still produce
    a diagnostic event showing v1_count=0 alongside the real V2 result --
    it must never silently look identical to 'no job ran at all'."""
    candidates = [_ev("tor::1", "Transcript of Records", "Fee: P75 per page.")]
    answer = "The fee is P75 per page."
    mock_client = _mock_httpx_client_returning(
        {"claims": [{"claim_id": "c1", "supporting_citation_ids": ["tor::1"]}]}
    )

    vid = jobs.create_job(
        answer=answer, candidates=candidates, mode="async_shadow", v1_citation_ids=[]
    )
    with caplog.at_level(logging.INFO, logger=JOBS_LOGGER), \
         patch("httpx.Client", return_value=mock_client), _configured_provider():
        jobs.run_verification_job(vid)

    events = _event_payloads(caplog)
    assert len(events) == 1
    event = events[0]
    assert event["v1_citation_ids"] == []
    assert event["v1_count"] == 0
    assert event["v2_citation_ids"] == ["tor::1"]  # the real V2 outcome, unaffected by V1 being empty
    assert event["v2_count"] == 1


def test_async_llm_also_emits_the_same_diagnostic_event_shape(caplog):
    """The logging mechanism is shared by construction (both modes reach the
    same run_verification_job terminal write) -- confirm async_llm gets an
    identical-shape event with mode='async_llm', with zero change to its own
    API-visible behavior (covered separately by the existing async_llm
    tests in this file and in test_qa_async_citation_verification.py)."""
    candidates = [_ev("tor::1", "Transcript of Records", "Fee: P75 per page.")]
    answer = "The fee is P75 per page."
    mock_client = _mock_httpx_client_returning(
        {"claims": [{"claim_id": "c1", "supporting_citation_ids": ["tor::1"]}]}
    )

    vid = jobs.create_job(
        answer=answer, candidates=candidates, mode="async_llm", v1_citation_ids=["tor::1"]
    )
    with caplog.at_level(logging.INFO, logger=JOBS_LOGGER), \
         patch("httpx.Client", return_value=mock_client), _configured_provider():
        jobs.run_verification_job(vid)

    events = _event_payloads(caplog)
    assert len(events) == 1
    assert events[0]["mode"] == "async_llm"
    assert events[0]["status"] == "verified"
