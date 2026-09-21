"""Unit tests for the in-process async Citation V2 job store
(app.services.qa.citation_verification_jobs). No provider calls -- the
verifier itself is mocked at the exact name run_verification_job imports.
"""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from app.services.qa import citation_verification_jobs as jobs
from app.services.qa.citation_verification import CandidateEvidence, VerificationOutcome

VERIFY = "app.services.qa.citation_verification_jobs.verify_citations"


@pytest.fixture(autouse=True)
def _reset_job_store():
    jobs.reset_jobs_store()
    yield
    jobs.reset_jobs_store()


def _candidates() -> list[CandidateEvidence]:
    return [
        CandidateEvidence(
            citation_id="doc::1", title="Refunding of Fees", source_section="Sec. 3",
            source_filename="handbook.pdf", text="Secret internal chunk text: 75% within week one.",
        )
    ]


def test_create_job_returns_unguessable_id_and_starts_pending():
    vid = jobs.create_job(answer="A 75% refund applies.", candidates=_candidates(), mode="async_llm")
    assert len(vid) >= 32  # uuid4().hex
    job = jobs.get_job(vid)
    assert job is not None
    assert job.status == jobs.JobStatus.PENDING


def test_run_verification_job_success_produces_verified_status_and_safe_citations():
    outcome = VerificationOutcome(mode="async_llm", verifier_succeeded=True, verified_citation_ids=["doc::1"])
    vid = jobs.create_job(answer="A 75% refund applies.", candidates=_candidates(), mode="async_llm")
    with patch(VERIFY, return_value=outcome):
        jobs.run_verification_job(vid)
    job = jobs.get_job(vid)
    assert job.status == jobs.JobStatus.VERIFIED
    assert len(job.verified_citations) == 1
    assert job.verified_citations[0].citation_id == "doc::1"
    assert job.verified_citations[0].title == "Refunding of Fees"


def test_run_verification_job_no_support_is_a_distinct_status_not_verified():
    outcome = VerificationOutcome(mode="async_llm", verifier_succeeded=True, verified_citation_ids=[])
    vid = jobs.create_job(answer="X", candidates=_candidates(), mode="async_llm")
    with patch(VERIFY, return_value=outcome):
        jobs.run_verification_job(vid)
    job = jobs.get_job(vid)
    assert job.status == jobs.JobStatus.NO_VERIFIED_SUPPORT
    assert job.verified_citations == []


def test_run_verification_job_failure_is_a_distinct_status_never_verified():
    outcome = VerificationOutcome(mode="async_llm", verifier_succeeded=False, failure_reason="provider_timeout")
    vid = jobs.create_job(answer="X", candidates=_candidates(), mode="async_llm")
    with patch(VERIFY, return_value=outcome):
        jobs.run_verification_job(vid)
    job = jobs.get_job(vid)
    assert job.status == jobs.JobStatus.FAILED
    assert job.status != jobs.JobStatus.VERIFIED
    assert job.failure_reason == "provider_timeout"


def test_run_verification_job_swallows_unexpected_exception_and_fails_closed():
    vid = jobs.create_job(answer="X", candidates=_candidates(), mode="async_llm")
    with patch(VERIFY, side_effect=RuntimeError("boom")):
        jobs.run_verification_job(vid)  # must not raise
    job = jobs.get_job(vid)
    assert job.status == jobs.JobStatus.FAILED
    assert "unexpected_error" in (job.failure_reason or "")


def test_candidate_text_discarded_after_terminal_state():
    outcome = VerificationOutcome(mode="async_llm", verifier_succeeded=True, verified_citation_ids=["doc::1"])
    vid = jobs.create_job(answer="A 75% refund applies.", candidates=_candidates(), mode="async_llm")
    with patch(VERIFY, return_value=outcome):
        jobs.run_verification_job(vid)
    job = jobs.get_job(vid)
    assert job._candidates is None
    assert job._answer is None


def test_unknown_id_returns_none_never_fabricated_state():
    assert jobs.get_job("does-not-exist") is None
    status, citations = jobs.status_and_citations_for_poll("does-not-exist")
    assert status == "unknown"
    assert citations == []


def test_ttl_expiry_makes_a_real_job_unavailable():
    vid = jobs.create_job(answer="X", candidates=_candidates(), mode="async_llm")
    assert jobs.get_job(vid, ttl_seconds=0.01) is not None
    time.sleep(0.05)
    assert jobs.get_job(vid, ttl_seconds=0.01) is None


def test_concurrent_jobs_remain_independent():
    outcome_a = VerificationOutcome(mode="async_llm", verifier_succeeded=True, verified_citation_ids=["doc::1"])
    outcome_b = VerificationOutcome(mode="async_llm", verifier_succeeded=False, failure_reason="provider_timeout")
    vid_a = jobs.create_job(answer="A", candidates=_candidates(), mode="async_llm")
    vid_b = jobs.create_job(answer="B", candidates=_candidates(), mode="async_llm")

    with patch(VERIFY, return_value=outcome_b):
        jobs.run_verification_job(vid_b)  # B finishes first
    with patch(VERIFY, return_value=outcome_a):
        jobs.run_verification_job(vid_a)  # A finishes later

    job_a = jobs.get_job(vid_a)
    job_b = jobs.get_job(vid_b)
    assert job_a.status == jobs.JobStatus.VERIFIED
    assert job_a.verified_citations[0].citation_id == "doc::1"
    assert job_b.status == jobs.JobStatus.FAILED
    # No cross-attachment: A's success must not leak into B's record or vice versa.
    assert job_b.verified_citations == []


def test_one_failed_job_does_not_affect_a_sibling_pending_job():
    vid_ok = jobs.create_job(answer="ok", candidates=_candidates(), mode="async_llm")
    vid_fail = jobs.create_job(answer="fail", candidates=_candidates(), mode="async_llm")
    with patch(VERIFY, side_effect=RuntimeError("boom")):
        jobs.run_verification_job(vid_fail)
    still_pending = jobs.get_job(vid_ok)
    assert still_pending.status == jobs.JobStatus.PENDING


def test_process_restart_simulation_loses_jobs_safely():
    vid = jobs.create_job(answer="X", candidates=_candidates(), mode="async_llm")
    assert jobs.get_job(vid) is not None
    jobs.reset_jobs_store()  # simulates process restart
    assert jobs.get_job(vid) is None
    status, citations = jobs.status_and_citations_for_poll(vid)
    assert status == "unknown"
    assert citations == []


def test_schedule_verification_returns_none_for_empty_sink():
    class _FakeBackgroundTasks:
        def add_task(self, *a, **k):
            raise AssertionError("must not schedule anything for an empty sink")

    result = jobs.schedule_verification(_FakeBackgroundTasks(), {})
    assert result is None


def test_schedule_verification_creates_and_schedules_a_real_job():
    calls = []

    class _FakeBackgroundTasks:
        def add_task(self, func, *args, **kwargs):
            calls.append((func, args, kwargs))

    sink = {"mode": "async_llm", "answer": "X", "candidates": _candidates()}
    vid = jobs.schedule_verification(_FakeBackgroundTasks(), sink)
    assert vid is not None
    assert jobs.get_job(vid) is not None
    assert len(calls) == 1
    assert calls[0][0] is jobs.run_verification_job
    assert calls[0][1] == (vid,)


# --- BLOCKER-1 repair: mode translation -------------------------------------


def test_semantic_mode_for_translates_async_names():
    assert jobs._semantic_mode_for("async_llm") == "llm"
    assert jobs._semantic_mode_for("async_shadow") == "shadow"


def test_semantic_mode_for_passes_through_unrecognized_names_unchanged():
    # No special-casing needed here -- an untranslated, unrecognized mode
    # string is exactly what verify_citations()'s own existing
    # `mode not in ("shadow", "llm")` check already fails closed on.
    assert jobs._semantic_mode_for("some_future_mode") == "some_future_mode"


def test_run_verification_job_calls_verify_citations_with_translated_mode():
    outcome = VerificationOutcome(mode="llm", verifier_succeeded=True, verified_citation_ids=["doc::1"])
    vid = jobs.create_job(answer="X", candidates=_candidates(), mode="async_llm")
    with patch(VERIFY, return_value=outcome) as mock_verify:
        jobs.run_verification_job(vid)
    assert mock_verify.call_args.kwargs["mode"] == "llm"  # NOT "async_llm"


def test_run_verification_job_translates_async_shadow_too():
    outcome = VerificationOutcome(mode="shadow", verifier_succeeded=True, verified_citation_ids=["doc::1"])
    vid = jobs.create_job(answer="X", candidates=_candidates(), mode="async_shadow")
    with patch(VERIFY, return_value=outcome) as mock_verify:
        jobs.run_verification_job(vid)
    assert mock_verify.call_args.kwargs["mode"] == "shadow"  # NOT "async_shadow"


def test_unrecognized_async_mode_fails_closed_never_a_crash_never_unsafe_citation():
    """A future/unexpected mode string that isn't in the translation map is
    passed through unchanged to verify_citations(), which itself already
    rejects anything outside ("shadow", "llm") -- verified end to end here
    with the REAL verify_citations (not mocked), no network call needed
    since the mode check short-circuits before any HTTP attempt."""
    vid = jobs.create_job(answer="X", candidates=_candidates(), mode="some_unrecognized_mode")
    jobs.run_verification_job(vid)  # real verify_citations, no mock, no network call
    job = jobs.get_job(vid)
    assert job.status == jobs.JobStatus.FAILED
    assert job.verified_citations == []


# --- schedule_verification exception safety ---------------------------------


def test_schedule_verification_returns_none_when_job_creation_raises():
    class _FakeBackgroundTasks:
        def add_task(self, *a, **k):
            raise AssertionError("must not be reached if job creation itself failed")

    with patch("app.services.qa.citation_verification_jobs.create_job", side_effect=RuntimeError("boom")):
        result = jobs.schedule_verification(
            _FakeBackgroundTasks(), {"mode": "async_llm", "answer": "X", "candidates": _candidates()}
        )
    assert result is None


def test_schedule_verification_marks_job_failed_when_add_task_raises_but_still_returns_the_id():
    class _FailingBackgroundTasks:
        def add_task(self, *a, **k):
            raise RuntimeError("scheduler unavailable")

    sink = {"mode": "async_llm", "answer": "X", "candidates": _candidates()}
    vid = jobs.schedule_verification(_FailingBackgroundTasks(), sink)
    assert vid is not None  # still handed back so the client can discover the failure
    job = jobs.get_job(vid)
    assert job.status == jobs.JobStatus.FAILED
    assert job.failure_reason == "scheduling_failed"
    assert job.status != jobs.JobStatus.PENDING  # never left permanently PENDING


# --- async_shadow: never client-pollable -------------------------------------


def test_schedule_verification_withholds_id_for_async_shadow_but_still_runs_the_job():
    calls = []

    class _FakeBackgroundTasks:
        def add_task(self, func, *args, **kwargs):
            calls.append((func, args, kwargs))

    sink = {"mode": "async_shadow", "answer": "X", "candidates": _candidates()}
    result = jobs.schedule_verification(_FakeBackgroundTasks(), sink)
    assert result is None  # withheld from the client
    assert len(calls) == 1  # but the job WAS created and scheduled server-side
    real_vid = calls[0][1][0]
    assert jobs.get_job(real_vid) is not None
    assert jobs.get_job(real_vid).status == jobs.JobStatus.PENDING


def test_schedule_verification_returns_id_for_async_llm_only():
    class _FakeBackgroundTasks:
        def add_task(self, *a, **k):
            pass

    llm_result = jobs.schedule_verification(
        _FakeBackgroundTasks(), {"mode": "async_llm", "answer": "X", "candidates": _candidates()}
    )
    shadow_result = jobs.schedule_verification(
        _FakeBackgroundTasks(), {"mode": "async_shadow", "answer": "X", "candidates": _candidates()}
    )
    assert llm_result is not None
    assert shadow_result is None


# --- TTL: RUNNING jobs must not expire mid-flight ----------------------------


def test_running_job_survives_sweep_even_past_ttl():
    vid = jobs.create_job(answer="X", candidates=_candidates(), mode="async_llm")
    with jobs._LOCK:
        job = jobs._JOBS[vid]
        job.status = jobs.JobStatus.RUNNING
        job.created_at -= 10_000  # far older than any realistic TTL

    # Both create_job and get_job trigger a sweep -- neither may delete a
    # RUNNING job no matter how old it is.
    assert jobs.get_job(vid, ttl_seconds=1) is not None
    jobs.create_job(answer="other", candidates=_candidates(), mode="async_llm")  # triggers another sweep
    assert vid in jobs._JOBS
    assert jobs._JOBS[vid].status == jobs.JobStatus.RUNNING


def test_pending_job_still_expires_normally_by_created_at():
    vid = jobs.create_job(answer="X", candidates=_candidates(), mode="async_llm")
    with jobs._LOCK:
        jobs._JOBS[vid].created_at -= 10_000
    assert jobs.get_job(vid, ttl_seconds=1) is None


def test_terminal_job_expires_from_completed_at_not_created_at():
    outcome = VerificationOutcome(mode="llm", verifier_succeeded=True, verified_citation_ids=["doc::1"])
    vid = jobs.create_job(answer="X", candidates=_candidates(), mode="async_llm")
    with patch(VERIFY, return_value=outcome):
        jobs.run_verification_job(vid)
    # The job is now terminal (VERIFIED). Backdating created_at alone must
    # NOT expire it -- only completed_at governs a terminal job's TTL.
    with jobs._LOCK:
        jobs._JOBS[vid].created_at -= 10_000
    assert jobs.get_job(vid, ttl_seconds=60) is not None
    # But backdating completed_at DOES expire it.
    with jobs._LOCK:
        jobs._JOBS[vid].completed_at -= 10_000
    assert jobs.get_job(vid, ttl_seconds=60) is None


def test_running_job_that_finishes_after_being_swept_is_discarded_not_resurrected():
    """Simulates a reset (this codebase's stand-in for a process restart)
    happening WHILE a job's verifier call is genuinely still in flight --
    the mocked verifier itself triggers the reset mid-call, so
    run_verification_job's PENDING->RUNNING transition happens for real
    first, then the store is wiped out from under it, then its tail
    write-back must find nothing to write into and discard the result
    quietly -- never resurrect the job, never raise."""

    def _verify_that_triggers_reset_mid_flight(**kwargs):
        jobs.reset_jobs_store()
        return VerificationOutcome(mode="llm", verifier_succeeded=True, verified_citation_ids=["doc::1"])

    vid = jobs.create_job(answer="X", candidates=_candidates(), mode="async_llm")
    with patch(VERIFY, side_effect=_verify_that_triggers_reset_mid_flight):
        jobs.run_verification_job(vid)  # must not raise
    assert jobs.get_job(vid) is None  # not resurrected under its old id
    assert len(jobs._JOBS) == 0  # no stray state left behind anywhere


# --- _failure_category: finer, still-bounded classification -------------------
#
# Previously all seven of these prefixes shared one bucket, "invalid_response".
# Split into five narrower categories so operator telemetry can distinguish
# an HTTP-envelope-shape problem from a JSON-syntax problem from a
# schema-shape problem from a genuine model-behavior deviation (an invented
# or repeated id) -- citation_verification.py's own raise sites/messages are
# completely unchanged; this only affects which bucket label an existing
# failure_reason string maps to.


@pytest.mark.parametrize(
    "failure_reason,expected_category",
    [
        ("provider_timeout: Read timed out", "provider_error"),
        ("provider_error: 503 Service Unavailable", "provider_error"),
        ("provider_not_configured", "provider_error"),
        ("unexpected_response_shape: 'choices'", "response_shape_error"),
        ("malformed_json: Expecting value: line 1 column 1", "malformed_json"),
        ("schema_violation: root is not an object", "schema_violation"),
        ("schema_violation: 'claims' is not a list", "schema_violation"),
        ("hallucinated_citation_id: 'not-an-authorized-id'", "unknown_or_hallucinated_id"),
        ("unknown_claim_id: 'c99'", "unknown_or_hallucinated_id"),
        ("duplicate_claim_id: 'c1'", "duplicate_id"),
        ("duplicate_citation_id: 'a' for 'c1'", "duplicate_id"),
        ("unexpected_error:ValueError", "internal_error"),
        ("scheduling_failed", "internal_error"),
        ("something_never_seen_before", "unknown"),
        (None, "unknown"),
    ],
)
def test_failure_category_maps_every_known_prefix_to_the_correct_bounded_category(
    failure_reason, expected_category
):
    assert jobs._failure_category(failure_reason) == expected_category


def test_failure_category_set_is_small_and_fixed():
    """Guards against the category set silently growing ad hoc -- exactly
    the 7 non-fallback categories plus the 'unknown' fallback."""
    all_categories = {category for _, category in jobs._FAILURE_CATEGORIES_BY_PREFIX}
    assert all_categories == {
        "provider_error",
        "response_shape_error",
        "malformed_json",
        "schema_violation",
        "unknown_or_hallucinated_id",
        "duplicate_id",
        "internal_error",
    }


def test_schema_violation_failed_job_reports_schema_violation_category_in_real_event(caplog):
    """End-to-end through run_verification_job (not just the pure
    _failure_category function): a schema-shape failure_reason must reach
    the actual logged diagnostic event as failure_category='schema_violation'."""
    import json
    import logging

    outcome = VerificationOutcome(
        mode="async_llm", verifier_succeeded=False,
        failure_reason="schema_violation: 'claims' is not a list",
    )
    vid = jobs.create_job(
        answer="A 75% refund applies.", candidates=_candidates(), mode="async_llm",
        v1_citation_ids=["doc::1"],
    )
    with caplog.at_level(logging.INFO, logger="app.services.qa.citation_verification_jobs"), \
         patch(VERIFY, return_value=outcome):
        jobs.run_verification_job(vid)

    lines = [
        r.getMessage() for r in caplog.records
        if r.getMessage().startswith("citation_verification_async_completed ")
    ]
    assert len(lines) == 1
    event = json.loads(lines[0][len("citation_verification_async_completed ") :])
    assert event["failure_category"] == "schema_violation"
    assert event["status"] == "failed"
