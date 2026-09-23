"""Privacy-safe per-claim citation verifier diagnostics.

Exercises ``build_per_claim_supporting_ids_diagnostic`` and the async job
surface that stores/logs claim_index → allowlisted real citation_ids.
Does NOT change verifier decisions or displayed citation unions.
"""

from __future__ import annotations

import json
import logging
from unittest.mock import patch

import pytest

from app.services.qa import citation_verification_jobs as jobs
from app.services.qa.citation_verification import (
    CandidateEvidence,
    Claim,
    VerificationOutcome,
    build_per_claim_supporting_ids_diagnostic,
    verify_citations,
)

VERIFY = "app.services.qa.citation_verification_jobs.verify_citations"


@pytest.fixture(autouse=True)
def _reset_job_store():
    jobs.reset_jobs_store()
    yield
    jobs.reset_jobs_store()


def _cand(cid: str, title: str = "T") -> CandidateEvidence:
    return CandidateEvidence(
        citation_id=cid,
        title=title,
        source_section="Sec",
        source_filename="doc.pdf",
        text=f"Evidence body for {cid}",
    )


def _outcome(
    *,
    claims: list[Claim],
    per_claim: dict[str, list[str]],
    candidates: list[str],
    succeeded: bool = True,
) -> VerificationOutcome:
    return VerificationOutcome(
        mode="llm",
        claims=claims,
        candidate_citation_ids=list(candidates),
        verifier_invoked=True,
        verifier_succeeded=succeeded,
        per_claim_verified_ids=dict(per_claim),
        verified_citation_ids=[
            cid
            for cid in candidates
            if any(cid in ids for ids in per_claim.values())
        ]
        if succeeded
        else [],
    )


# --- A–F: diagnostic builder -------------------------------------------------


def test_diagnostic_maps_multiple_claims_to_different_evidence_ids():
    outcome = _outcome(
        claims=[Claim("c1", "claim one"), Claim("c2", "claim two")],
        per_claim={"c1": ["a::1"], "c2": ["b::2"]},
        candidates=["a::1", "b::2"],
    )
    rows = build_per_claim_supporting_ids_diagnostic(outcome)
    assert rows == [["a::1"], ["b::2"]]


def test_diagnostic_unsupported_claim_maps_to_empty_list():
    outcome = _outcome(
        claims=[Claim("c1", "supported"), Claim("c2", "unsupported")],
        per_claim={"c1": ["a::1"], "c2": []},
        candidates=["a::1"],
    )
    rows = build_per_claim_supporting_ids_diagnostic(outcome)
    assert rows == [["a::1"], []]


def test_diagnostic_preserves_multiple_evidence_ids_for_one_claim():
    outcome = _outcome(
        claims=[Claim("c1", "multi")],
        per_claim={"c1": ["a::1", "b::2"]},
        candidates=["a::1", "b::2", "c::3"],
    )
    rows = build_per_claim_supporting_ids_diagnostic(outcome)
    assert rows == [["a::1", "b::2"]]


def test_diagnostic_uses_claim_order_not_dict_key_order():
    outcome = _outcome(
        claims=[Claim("c2", "second"), Claim("c1", "first")],
        per_claim={"c1": ["a::1"], "c2": ["b::2"]},
        candidates=["a::1", "b::2"],
    )
    rows = build_per_claim_supporting_ids_diagnostic(outcome)
    assert rows == [["b::2"], ["a::1"]]


def test_diagnostic_drops_non_allowlisted_and_hallucinated_ids():
    outcome = _outcome(
        claims=[Claim("c1", "x")],
        per_claim={"c1": ["a::1", "hallucinated", "b::2"]},
        candidates=["a::1", "b::2"],
    )
    rows = build_per_claim_supporting_ids_diagnostic(
        outcome, allowlist={"a::1"}  # tighter than candidates
    )
    assert rows == [["a::1"]]
    assert "hallucinated" not in rows[0]
    assert "b::2" not in rows[0]


def test_diagnostic_dedupes_duplicate_ids_consistently():
    outcome = _outcome(
        claims=[Claim("c1", "x")],
        per_claim={"c1": ["a::1", "a::1", "b::2"]},
        candidates=["a::1", "b::2"],
    )
    rows = build_per_claim_supporting_ids_diagnostic(outcome)
    assert rows == [["a::1", "b::2"]]


def test_diagnostic_empty_on_verifier_failure_fail_closed():
    outcome = _outcome(
        claims=[Claim("c1", "secret claim text")],
        per_claim={},
        candidates=["a::1"],
        succeeded=False,
    )
    assert build_per_claim_supporting_ids_diagnostic(outcome) == []


def test_diagnostic_payload_contains_no_claim_or_evidence_text():
    outcome = _outcome(
        claims=[Claim("c1", "SECRET_CLAIM_TEXT_SHOULD_NOT_APPEAR")],
        per_claim={"c1": ["30875c07-409e-45ea-989e-3315a85608c1::117"]},
        candidates=["30875c07-409e-45ea-989e-3315a85608c1::117"],
    )
    rows = build_per_claim_supporting_ids_diagnostic(outcome)
    blob = json.dumps(rows)
    assert "SECRET_CLAIM_TEXT_SHOULD_NOT_APPEAR" not in blob
    assert "Evidence body" not in blob
    assert "S1" not in blob  # aliases never appear


# --- G/H/I/J: job surface + log + hygiene + union equivalence ----------------


def test_job_stores_per_claim_supporting_ids_and_discards_answer_text(caplog):
    candidates = [_cand("doc::1"), _cand("doc::2", title="Other")]
    outcome = VerificationOutcome(
        mode="llm",
        claims=[Claim("c1", "fee claim"), Claim("c2", "office claim")],
        candidate_citation_ids=["doc::1", "doc::2"],
        verifier_invoked=True,
        verifier_succeeded=True,
        per_claim_verified_ids={"c1": ["doc::1"], "c2": ["doc::2"]},
        verified_citation_ids=["doc::1", "doc::2"],
    )
    vid = jobs.create_job(
        answer="SECRET_ANSWER_TEXT",
        candidates=candidates,
        mode="async_llm",
        v1_citation_ids=["doc::1"],
    )
    with (
        caplog.at_level(logging.INFO, logger="app.services.qa.citation_verification_jobs"),
        patch(VERIFY, return_value=outcome),
    ):
        jobs.run_verification_job(vid)

    job = jobs.get_job(vid)
    assert job is not None
    assert job._answer is None
    assert job._candidates is None
    assert job.per_claim_supporting_ids == [["doc::1"], ["doc::2"]]
    # Displayed union unchanged relative to verified_citation_ids order/filter.
    assert [c.citation_id for c in job.verified_citations] == ["doc::1", "doc::2"]

    lines = [
        r.getMessage()
        for r in caplog.records
        if r.getMessage().startswith("citation_verification_async_completed ")
    ]
    assert len(lines) == 1
    event = json.loads(lines[0][len("citation_verification_async_completed ") :])
    assert event["verification_id"] == vid
    assert event["per_claim_supporting_ids"] == [["doc::1"], ["doc::2"]]
    assert event["per_claim_count"] == 2
    event_blob = json.dumps(event)
    assert "SECRET_ANSWER_TEXT" not in event_blob
    assert "fee claim" not in event_blob
    assert "office claim" not in event_blob
    assert "Evidence body" not in event_blob


def test_job_failure_clears_per_claim_diagnostics_and_keeps_empty_union():
    outcome = VerificationOutcome(
        mode="llm",
        claims=[Claim("c1", "x")],
        candidate_citation_ids=["doc::1"],
        verifier_invoked=True,
        verifier_succeeded=False,
        failure_reason="malformed_json: boom",
        per_claim_verified_ids={},
        verified_citation_ids=[],
    )
    vid = jobs.create_job(answer="X", candidates=[_cand("doc::1")], mode="async_llm")
    with patch(VERIFY, return_value=outcome):
        jobs.run_verification_job(vid)
    job = jobs.get_job(vid)
    assert job is not None
    assert job.status == jobs.JobStatus.FAILED
    assert job.verified_citations == []
    assert job.per_claim_supporting_ids == []


def test_displayed_citation_union_identical_with_instrumentation():
    """Same verifier outcome → same safe citation list as pre-instrumentation."""
    candidates = [_cand("a"), _cand("b"), _cand("c")]
    outcome = VerificationOutcome(
        mode="llm",
        claims=[Claim("c1", "one"), Claim("c2", "two")],
        candidate_citation_ids=["a", "b", "c"],
        verifier_invoked=True,
        verifier_succeeded=True,
        # Union order follows candidate order in verify_citations; job preserves
        # outcome.verified_citation_ids order when building safe citations.
        per_claim_verified_ids={"c1": ["c"], "c2": ["a"]},
        verified_citation_ids=["a", "c"],
    )
    vid = jobs.create_job(answer="X", candidates=candidates, mode="async_llm")
    with patch(VERIFY, return_value=outcome):
        jobs.run_verification_job(vid)
    job = jobs.get_job(vid)
    assert [c.citation_id for c in job.verified_citations] == ["a", "c"]
    assert job.per_claim_supporting_ids == [["c"], ["a"]]


def test_poll_api_surface_unchanged_no_per_claim_leak():
    candidates = [_cand("doc::1")]
    outcome = VerificationOutcome(
        mode="llm",
        claims=[Claim("c1", "secret")],
        candidate_citation_ids=["doc::1"],
        verifier_invoked=True,
        verifier_succeeded=True,
        per_claim_verified_ids={"c1": ["doc::1"]},
        verified_citation_ids=["doc::1"],
    )
    vid = jobs.create_job(answer="X", candidates=candidates, mode="async_llm")
    with patch(VERIFY, return_value=outcome):
        jobs.run_verification_job(vid)
    status, cites = jobs.status_and_citations_for_poll(vid)
    assert status == jobs.JobStatus.VERIFIED
    assert len(cites) == 1
    assert cites[0].citation_id == "doc::1"
    # Poll tuple has no per-claim field — Flutter/API unchanged.
    assert not hasattr(cites[0], "per_claim_supporting_ids")


def test_end_to_end_verify_citations_diagnostic_matches_allowlisted_mapping():
    """Provider returns aliases; diagnostic exposes only allowlisted real ids."""
    candidates = [_cand("real-a"), _cand("real-b")]
    answer = (
        "The fee is seventy five pesos. "
        "Processing time is five minutes. "
        "The office is the Registrar."
    )
    mock_body = {
        "claims": [
            {"claim_id": "c1", "supporting_citation_ids": ["S1"]},
            {"claim_id": "c2", "supporting_citation_ids": ["S2"]},
            {"claim_id": "c3", "supporting_citation_ids": []},
        ]
    }

    def _fake_call(messages, response_schema):
        # Bind aliases to whatever claim_ids the extractor actually produced.
        claim_enum = response_schema["json_schema"]["schema"]["properties"]["claims"][
            "items"
        ]["properties"]["claim_id"]["enum"]
        claims_out = []
        for i, cid in enumerate(claim_enum):
            if i == 0:
                claims_out.append({"claim_id": cid, "supporting_citation_ids": ["S1"]})
            elif i == 1:
                claims_out.append(
                    {"claim_id": cid, "supporting_citation_ids": ["S2", "S1"]}
                )
            else:
                claims_out.append({"claim_id": cid, "supporting_citation_ids": []})
        return json.dumps({"claims": claims_out}), {
            "prompt_tokens": 1,
            "completion_tokens": 1,
        }

    with patch(
        "app.services.qa.citation_verification._call_verifier", side_effect=_fake_call
    ):
        outcome = verify_citations(answer=answer, candidates=candidates, mode="llm")
    assert outcome.verifier_succeeded
    assert len(outcome.claims) >= 2
    rows = build_per_claim_supporting_ids_diagnostic(outcome)
    assert len(rows) == len(outcome.claims)
    allowed = {"real-a", "real-b"}
    for ids in rows:
        assert all(cid in allowed for cid in ids)
    flat = {cid for ids in rows for cid in ids}
    assert flat == set(outcome.verified_citation_ids)
    assert rows[0] == ["real-a"]
    assert rows[1] == ["real-b", "real-a"]
    if len(rows) > 2:
        assert rows[2] == []
