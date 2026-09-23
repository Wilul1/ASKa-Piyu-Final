"""In-process job store for asynchronous Citation Grounding V2 verification.

Per-process only -- does not share state across uvicorn/gunicorn workers,
same documented limitation as ``app.services.qa_rate_limit`` (see that
module's own docstring), which this module deliberately mirrors: a plain
dict guarded by a ``threading.Lock``, no new external dependency.

Purpose: let ``POST /qa/ask`` (and ``/student/ask``) return the generated
answer WITHOUT waiting for semantic citation verification, by freezing the
verifier's inputs into a job record here and running the actual verifier
call in a FastAPI ``BackgroundTasks`` callback -- see ``app.routes.qa``.

Lifecycle (see ``JobStatus``): PENDING -> RUNNING -> one of VERIFIED /
NO_VERIFIED_SUPPORT / FAILED. A job absent from the store (never created,
already swept by TTL, or lost to a process restart) is indistinguishable
from EXPIRED to a caller -- ``get_job`` returns ``None`` in both cases, and
callers must treat that as a safe "verification unavailable" outcome, never
as "verified with nothing to show".

Candidate TEXT (the only sensitive content in a job) is discarded once a
job reaches a terminal state -- only citation_id/title/source_section/
source_filename survive for building the safe, final citations list a poll
response returns. This module never returns candidate text, the verifier
prompt, or raw provider errors to a caller.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

from app.services.qa.citation_verification import (
    CandidateEvidence,
    build_per_claim_supporting_ids_diagnostic,
    verify_citations,
)

logger = logging.getLogger(__name__)


class JobStatus:
    """String constants, not an enum, so job records stay trivially JSON-able."""

    PENDING = "pending"
    RUNNING = "running"
    VERIFIED = "verified"
    NO_VERIFIED_SUPPORT = "no_verified_support"
    FAILED = "failed"


_TERMINAL_STATUSES = frozenset(
    {JobStatus.VERIFIED, JobStatus.NO_VERIFIED_SUPPORT, JobStatus.FAILED}
)

# Orchestration/async mode names (this module's own vocabulary) mapped to the
# semantic verification mode names citation_verification.verify_citations()
# actually recognizes ("shadow"/"llm" only). Deliberately centralized and
# explicit here rather than teaching the semantic verifier about
# transport/orchestration concepts, or scattering the string translation
# across call sites. A job's mode that is NOT a key in this map is passed to
# verify_citations() unchanged -- if it is not itself "shadow"/"llm" either,
# verify_citations()'s own existing mode check (mode not in ("shadow","llm"))
# already fails closed (verifier_invoked stays False), so an unrecognized
# async mode fails closed by construction, with no special-case needed here.
_ASYNC_TO_SEMANTIC_MODE = {
    "async_shadow": "shadow",
    "async_llm": "llm",
}


def _semantic_mode_for(async_mode: str) -> str:
    return _ASYNC_TO_SEMANTIC_MODE.get(async_mode, async_mode)

# Prototype default -- not asserted to be a production-optimal value; a real
# deployment should tune this from observed verifier latency, none of which
# was collected in this investigation (no provider calls were made).
DEFAULT_TTL_SECONDS = 600


@dataclass
class _SafeCitation:
    """The ONLY per-citation fields a poll response may ever return."""

    citation_id: str
    title: str
    source_section: str | None
    source_filename: str | None


@dataclass
class VerificationJob:
    verification_id: str
    status: str
    created_at: float
    mode: str
    # Present only while status is PENDING/RUNNING; discarded (set to None)
    # the moment a terminal state is reached -- see _discard_snapshot().
    _answer: str | None
    _candidates: list[CandidateEvidence] | None
    # V1's displayed citation ids only (never source text) -- diagnostic
    # input for the terminal shadow-comparison log event, discarded (set to
    # an empty list) the moment that event has been emitted; never returned
    # by status_and_citations_for_poll.
    _v1_citation_ids: list[str] = field(default_factory=list)
    completed_at: float | None = None
    verified_citations: list[_SafeCitation] = field(default_factory=list)
    failure_reason: str | None = None
    # Privacy-safe per-claim diagnostic only: claim_index (list order) ->
    # allowlisted real supporting citation_ids. Populated on successful
    # verification; empty on failure. IDs only -- never claim/evidence/
    # answer text. Not returned by status_and_citations_for_poll (API/
    # Flutter unchanged); available on the in-process job for benchmarks
    # and the terminal structured log event.
    per_claim_supporting_ids: list[list[str]] = field(default_factory=list)


_JOBS: dict[str, VerificationJob] = {}
_LOCK = Lock()


def _now() -> float:
    return time.monotonic()


def _sweep_expired_locked(ttl_seconds: float) -> None:
    """Caller must already hold _LOCK.

    A RUNNING job is NEVER swept, regardless of age -- deleting it out from
    under an in-flight verifier call would silently discard an eventually-
    legitimate result (run_verification_job's own final write already
    handles a job disappearing gracefully, but this function should not be
    the one making that happen to an ACTIVE job). PENDING jobs age out from
    ``created_at`` (a job that was created but never started running --
    e.g. because scheduling itself failed -- must not linger forever).
    Terminal jobs (VERIFIED/NO_VERIFIED_SUPPORT/FAILED) age out from
    ``completed_at``, giving every job a full TTL window to be polled
    AFTER it actually finishes, not a window that started ticking before
    the (possibly slow) verification even began.
    """
    cutoff = _now() - ttl_seconds
    expired = []
    for vid, job in _JOBS.items():
        if job.status == JobStatus.RUNNING:
            continue
        reference_time = job.completed_at if job.completed_at is not None else job.created_at
        if reference_time < cutoff:
            expired.append(vid)
    for vid in expired:
        del _JOBS[vid]


def create_job(
    *,
    answer: str,
    candidates: list[CandidateEvidence],
    mode: str,
    v1_citation_ids: list[str] | None = None,
) -> str:
    """Freeze the exact inputs a synchronous verify_citations() call would
    have used, and return a fresh, unguessable verification_id. Does not
    call the verifier -- see run_verification_job for that.

    ``v1_citation_ids`` is diagnostic-only (ids, never text) -- the citation
    ids V1 already decided to display for this same answer, captured at the
    exact point that decision was made (see
    question_answering._display_sources_for_answer). It plays no role in
    verification itself; it exists solely so the terminal log event in
    run_verification_job can report V1 vs V2 side by side.
    """
    verification_id = uuid.uuid4().hex
    with _LOCK:
        _sweep_expired_locked(DEFAULT_TTL_SECONDS)
        _JOBS[verification_id] = VerificationJob(
            verification_id=verification_id,
            status=JobStatus.PENDING,
            created_at=_now(),
            mode=mode,
            _answer=answer,
            _candidates=list(candidates),
            _v1_citation_ids=list(v1_citation_ids) if v1_citation_ids else [],
        )
    return verification_id


# Small, fixed, operator-facing failure categories -- derived from the
# existing failure_reason strings citation_verification.verify_citations()
# already produces, by prefix only. Never logs failure_reason itself (it may
# embed a wrapped provider/exception message); an unrecognized or future
# string safely falls back to "unknown" rather than growing this set ad hoc.
#
# Previously all seven post-transport conditions below shared one bucket,
# "invalid_response" -- collapsing a pure JSON-syntax failure, four distinct
# schema-shape violations, and genuine model-behavior deviations (an
# invented/incorrect id) into a single, undifferentiated label. Split here
# into five narrower categories (still a small, fixed, bounded set -- never
# freeform) so operator-facing telemetry can distinguish "the HTTP envelope
# itself was unusual" from "the JSON didn't parse" from "the JSON parsed but
# violated the schema" from "the model proposed an id it shouldn't have"
# from "the model repeated an id" -- without ever logging the underlying
# failure_reason string (which may embed a wrapped provider/exception
# message) or any provider content. citation_verification.py's own raise
# sites and messages are unchanged by this -- this is a pure telemetry
# refinement, not a change to what can fail or how.
_FAILURE_CATEGORIES_BY_PREFIX: tuple[tuple[tuple[str, ...], str], ...] = (
    (("provider_timeout", "provider_error", "provider_not_configured"), "provider_error"),
    (("unexpected_response_shape",), "response_shape_error"),
    (("malformed_json",), "malformed_json"),
    (("schema_violation",), "schema_violation"),
    (("hallucinated_citation_id", "unknown_claim_id"), "unknown_or_hallucinated_id"),
    (("duplicate_claim_id", "duplicate_citation_id"), "duplicate_id"),
    (("unexpected_error:", "scheduling_failed"), "internal_error"),
)


def _failure_category(failure_reason: str | None) -> str:
    """Maps an existing failure_reason string to one of a small bounded set
    of safe categories (provider_error / response_shape_error /
    malformed_json / schema_violation / unknown_or_hallucinated_id /
    duplicate_id / internal_error / unknown). Pure derivation only -- does
    not change what failure_reason values verify_citations()/
    run_verification_job() can produce."""
    reason = failure_reason or ""
    for prefixes, category in _FAILURE_CATEGORIES_BY_PREFIX:
        if reason.startswith(prefixes):
            return category
    return "unknown"


def _log_async_verification_event(
    *,
    verification_id: str,
    mode: str,
    status: str,
    v1_citation_ids: list[str],
    v2_citation_ids: list[str],
    duration_ms: float | None,
    failure_category: str | None,
    failure_diagnostics: dict[str, Any] | None = None,
    provider_diagnostics: dict[str, Any] | None = None,
    per_claim_supporting_ids: list[list[str]] | None = None,
) -> None:
    """Best-effort, terminal, operator-facing diagnostic event for one
    completed async verification job -- reached by both async_shadow and
    async_llm (identical payload either way; ``mode`` distinguishes them).
    Lets an operator watching ``docker logs`` compare V1's displayed
    citations against V2's verified citations for the same answer, which
    nothing else in the live request path currently records.

    Contains only ids/counts/status/duration -- never answer, question,
    claim, or candidate text, and never a raw provider error body (the
    module-level failure_reason string is mapped through
    ``_failure_category`` first, never logged verbatim).

    ``per_claim_supporting_ids`` -- when present -- is claim_index-ordered
    lists of already-allowlisted real citation_ids only (see
    ``build_per_claim_supporting_ids_diagnostic``). It never includes claim
    text, evidence text, or call-local S1/S2 aliases.

    ``failure_diagnostics`` -- present (non-None) only for a
    ``malformed_json`` failure -- is itself already a small, bounded,
    structural-only dict built by
    ``citation_verification._build_malformed_json_diagnostics`` (counts/
    categories/booleans, never raw text); this function does not inspect
    or transform it further, only passes it through into the payload
    verbatim (or ``None``/absent for every other outcome).

    ``provider_diagnostics`` -- present (non-None) only for a provider/
    transport-layer failure (timeout, HTTP error status, network error, or
    unconfigured provider) -- is itself already a small, bounded dict built
    by ``citation_verification._build_provider_diagnostics`` (an HTTP
    status integer and a fixed ``provider_error_kind`` string only, never a
    response body or raw exception text); passed through verbatim, never
    inspected further here.

    Called strictly AFTER the job record has already been written under
    _LOCK, and wrapped in its own try/except: a logging/serialization
    problem here must never affect job state, verification behavior, or the
    caller -- it can only fail to produce a log line.
    """
    try:
        per_claim = list(per_claim_supporting_ids) if per_claim_supporting_ids else []
        payload = {
            "event": "citation_verification_async_completed",
            "verification_id": verification_id,
            "mode": mode,
            "status": status,
            "v1_citation_ids": list(v1_citation_ids),
            "v2_citation_ids": list(v2_citation_ids),
            "v1_count": len(v1_citation_ids),
            "v2_count": len(v2_citation_ids),
            "per_claim_supporting_ids": per_claim,
            "per_claim_count": len(per_claim),
            "duration_ms": round(duration_ms, 1) if isinstance(duration_ms, (int, float)) else None,
            "failure_category": failure_category,
            "failure_diagnostics": failure_diagnostics,
            "provider_diagnostics": provider_diagnostics,
            "timestamp_unix": round(time.time(), 3),
        }
        logger.info("citation_verification_async_completed %s", json.dumps(payload, sort_keys=True))
    except Exception:  # noqa: BLE001 -- logging must never affect verification/job state
        logger.debug(
            "citation_verification_jobs: failed to emit async verification diagnostic event",
            exc_info=True,
        )


def run_verification_job(verification_id: str) -> None:
    """The BackgroundTasks entry point. Plain sync function -- FastAPI/
    Starlette runs sync background callables in a thread pool automatically
    (``starlette.background.BackgroundTask``), so this does not block the
    event loop; no extra asyncio.to_thread wrapping is needed at the call
    site. Never raises: any failure resolves the job to FAILED, mirroring
    verify_citations()'s own fail-closed contract, plus one more guard layer
    here so a bug in THIS module cannot leave a job stuck in RUNNING forever.
    """
    with _LOCK:
        job = _JOBS.get(verification_id)
        if job is None or job.status != JobStatus.PENDING:
            return
        job.status = JobStatus.RUNNING
        answer = job._answer
        candidates = job._candidates
        async_mode = job.mode
        v1_citation_ids = list(job._v1_citation_ids)

    semantic_mode = _semantic_mode_for(async_mode)
    duration_ms: float | None = None
    failure_diagnostics: dict[str, Any] | None = None
    provider_diagnostics: dict[str, Any] | None = None
    per_claim_supporting_ids: list[list[str]] = []
    try:
        outcome = verify_citations(answer=answer or "", candidates=candidates or [], mode=semantic_mode)
        duration_ms = outcome.latency_ms
        allowlist = {c.citation_id for c in (candidates or [])}
        per_claim_supporting_ids = build_per_claim_supporting_ids_diagnostic(
            outcome, allowlist=allowlist
        )
        if outcome.verifier_succeeded and outcome.verified_citation_ids:
            by_id = {c.citation_id: c for c in (candidates or [])}
            safe = [
                _SafeCitation(
                    citation_id=cid,
                    title=by_id[cid].title,
                    source_section=by_id[cid].source_section,
                    source_filename=by_id[cid].source_filename,
                )
                for cid in outcome.verified_citation_ids
                if cid in by_id
            ]
            new_status = JobStatus.VERIFIED if safe else JobStatus.NO_VERIFIED_SUPPORT
            failure_reason = None
        elif outcome.verifier_succeeded:
            safe = []
            new_status = JobStatus.NO_VERIFIED_SUPPORT
            failure_reason = None
        else:
            safe = []
            new_status = JobStatus.FAILED
            failure_reason = outcome.failure_reason or "verification_failed"
            failure_diagnostics = outcome.failure_diagnostics
            provider_diagnostics = outcome.provider_diagnostics
            per_claim_supporting_ids = []
    except Exception as exc:  # noqa: BLE001 -- fail-closed against literally anything
        logger.warning(
            "citation_verification_jobs: unexpected error running job, failing closed",
            exc_info=True,
        )
        safe = []
        new_status = JobStatus.FAILED
        failure_reason = f"unexpected_error:{type(exc).__name__}"
        per_claim_supporting_ids = []

    with _LOCK:
        current = _JOBS.get(verification_id)
        if current is None:
            # Swept/expired while the (possibly slow) verifier call was in
            # flight -- nothing left to write the result into; discard it
            # rather than resurrecting an expired job.
            return
        current.status = new_status
        current.completed_at = _now()
        current.verified_citations = safe
        current.failure_reason = failure_reason
        current.per_claim_supporting_ids = list(per_claim_supporting_ids)
        # Memory hygiene: candidate text and the answer text are never
        # needed again once a job is terminal. V1's citation ids were only
        # ever retained for the diagnostic event below; discard them too.
        # per_claim_supporting_ids is IDs-only and intentionally kept for
        # benchmark/operator diagnostics until the job TTL sweeps the record.
        current._answer = None
        current._candidates = None
        current._v1_citation_ids = []

    # Best-effort, outside the lock (no I/O while holding it): one terminal
    # diagnostic event per completed async job (async_shadow and async_llm
    # both reach this -- see _log_async_verification_event's own docstring).
    _log_async_verification_event(
        verification_id=verification_id,
        mode=async_mode,
        status=new_status,
        v1_citation_ids=v1_citation_ids,
        v2_citation_ids=[c.citation_id for c in safe],
        duration_ms=duration_ms,
        failure_category=(
            "no_verified_support"
            if new_status == JobStatus.NO_VERIFIED_SUPPORT
            else _failure_category(failure_reason)
            if new_status == JobStatus.FAILED
            else None
        ),
        failure_diagnostics=failure_diagnostics,
        provider_diagnostics=provider_diagnostics,
        per_claim_supporting_ids=per_claim_supporting_ids,
    )


def get_job(verification_id: str, *, ttl_seconds: float = DEFAULT_TTL_SECONDS) -> VerificationJob | None:
    """Returns None for an unknown, malformed-lookup, or TTL-expired id --
    callers must treat None as a safe 'verification unavailable' outcome,
    never as evidence of anything about a real job."""
    with _LOCK:
        _sweep_expired_locked(ttl_seconds)
        return _JOBS.get(verification_id)


def reset_jobs_store() -> None:
    """Test helper only -- simulates a process restart's loss of all jobs."""
    with _LOCK:
        _JOBS.clear()


def _fail_job_locked(verification_id: str, reason: str) -> None:
    """Caller must already hold _LOCK. Marks a job terminal-FAILED directly
    (bypassing run_verification_job's PENDING-only guard) -- used only when
    scheduling itself fails right after a job was created, so that job can
    never linger as a misleadingly permanent PENDING record with no worker
    ever going to touch it."""
    job = _JOBS.get(verification_id)
    if job is None:
        return
    job.status = JobStatus.FAILED
    job.completed_at = _now()
    job.failure_reason = reason
    job._answer = None
    job._candidates = None
    job._v1_citation_ids = []
    job.per_claim_supporting_ids = []


# Modes whose verification_id is offered to the CLIENT at all. async_shadow
# exists purely for server-side diagnostics (comparing V1 vs V2 without any
# user-facing effect) -- its job is still created and run identically to
# async_llm's, but its id is deliberately never handed back to the caller,
# so the client has no way to poll it. Flutter's own polling trigger is
# gated on receiving a non-null verification id (see chatbot_page.dart), so
# withholding the id here is sufficient on its own to guarantee a shadow
# job's result can never surface as a user-facing citation decision --
# no separate mode flag needs to travel to the client at all.
_CLIENT_POLLABLE_ASYNC_MODES = frozenset({"async_llm"})


def schedule_verification(background_tasks: Any, async_verification_sink: dict[str, Any] | None) -> str | None:
    """Create a job from a populated async_verification_sink (see
    question_answering._display_sources_for_answer) and schedule it on the
    given FastAPI ``BackgroundTasks``. Returns the new verification_id, or
    None when the sink is empty (nothing was frozen -- e.g. zero claims/zero
    candidates, or async mode was not active for this request) OR when the
    mode is not client-pollable (async_shadow -- see
    _CLIENT_POLLABLE_ASYNC_MODES). The job itself is still created and
    scheduled in the async_shadow case; only its id is withheld from the
    return value. Callers in app.routes.* use this identically for every QA
    endpoint.

    Exception-safe by design: a failure here must never turn an
    already-successfully-generated answer into a 500 for the caller (the
    route that calls this has already finished the try/except around
    answer_qa_question by the time this runs). If job CREATION itself
    fails, nothing was offered to the client (returns None, same as an
    empty sink). If job creation succeeds but SCHEDULING the background
    task fails, the already-created job is immediately marked FAILED
    (never left stuck PENDING with no worker ever going to run it), and
    its id is still returned (for client-pollable modes) so the client can
    poll it and correctly learn verification failed, rather than being left
    with citation_status='verifying' but no way to ever check on it.
    """
    if not async_verification_sink:
        return None
    mode = async_verification_sink.get("mode")
    try:
        verification_id = create_job(
            answer=async_verification_sink["answer"],
            candidates=async_verification_sink["candidates"],
            mode=mode,
            v1_citation_ids=async_verification_sink.get("v1_citation_ids"),
        )
    except Exception:  # noqa: BLE001 -- must never break the caller's already-built answer
        logger.warning(
            "citation_verification_jobs: failed to create a verification job; "
            "no verification will be offered for this answer",
            exc_info=True,
        )
        return None

    try:
        background_tasks.add_task(run_verification_job, verification_id)
    except Exception:  # noqa: BLE001 -- same invariant as above
        logger.warning(
            "citation_verification_jobs: failed to schedule the verification "
            "background task; marking job %s FAILED rather than leaving it "
            "permanently PENDING",
            verification_id,
            exc_info=True,
        )
        with _LOCK:
            _fail_job_locked(verification_id, "scheduling_failed")

    if mode not in _CLIENT_POLLABLE_ASYNC_MODES:
        return None
    return verification_id


def status_and_citations_for_poll(verification_id: str) -> tuple[str, list[_SafeCitation]]:
    """Safe (status, citations) pair for a poll response. 'unknown' covers
    every case that must be treated identically by a caller: never created,
    expired, or lost to a process restart -- see get_job's own docstring."""
    job = get_job(verification_id)
    if job is None:
        return "unknown", []
    return job.status, list(job.verified_citations)
