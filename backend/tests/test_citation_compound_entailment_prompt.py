"""Focused tests for the compound-claim entailment verifier-prompt rule.

These tests (1) lock the prompt wording so the rule stays general and
domain-agnostic, and (2) document expected pipeline behavior when the
(mocked) verifier honors that rule -- shared office/actor alone must not
retain wrong-procedure evidence; genuine full-relationship and multi-
source support must still retain.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from app.services.qa.citation_verification import (
    CandidateEvidence,
    _VERIFIER_SYSTEM_PROMPT,
    _build_verifier_messages,
    extract_claims,
    verify_citations,
)

MODULE = "app.services.qa.citation_verification"


def _ev(cid: str, title: str, text: str) -> CandidateEvidence:
    return CandidateEvidence(
        citation_id=cid,
        title=title,
        source_section=None,
        source_filename="doc.pdf",
        text=text,
    )


def _configured_provider():
    return patch.multiple(
        f"{MODULE}.settings",
        groq_api_key="test-key",
        llm_base_url="https://openrouter.ai/api/v1/chat/completions",
        groq_model="test-model",
        groq_timeout_seconds=5.0,
        citation_verifier_model=None,
    )


def _mock_verifier_returning(payload: dict) -> MagicMock:
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {
        "choices": [{"message": {"content": json.dumps(payload)}}]
    }
    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False
    mock_client.post.return_value = mock_response
    return mock_client


# --- prompt content -----------------------------------------------------------


def test_compound_entailment_rule_present_and_general():
    prompt = _VERIFIER_SYSTEM_PROMPT
    assert "compound claim" in prompt.lower()
    assert "relationship" in prompt.lower()
    assert "procedure A" in prompt
    assert "procedure B" in prompt
    banned = (
        "Refunding of Fees",
        "Honorable Dismissal",
        "::117",
        "::118",
        "fg_l1",
    )
    for term in banned:
        assert term not in prompt, f"prompt must not mention {term!r}"


def test_compound_entailment_rule_included_in_built_messages():
    claims = extract_claims("Office X manages policy Y.")
    candidates = [_ev("a", "T", "Office X handles procedure Z only.")]
    messages = _build_verifier_messages(claims, candidates, ["S1"])
    assert messages[0]["role"] == "system"
    assert "compound claim" in messages[0]["content"].lower()
    assert "procedure A" in messages[0]["content"]


# --- A. shared office, different procedure → reject ---------------------------


def test_A_shared_office_different_procedure_rejected():
    proc_a = _ev(
        "proc-a",
        "Procedure A",
        "Office Alpha participates in Procedure A by granting consent.",
    )
    proc_b = _ev(
        "proc-b",
        "Procedure B",
        "Office Alpha manages Procedure B schedules and amounts.",
    )
    answer = "Procedure B schedules and amounts are managed by Office Alpha."
    mock_client = _mock_verifier_returning(
        {"claims": [{"claim_id": "c1", "supporting_citation_ids": ["S2"]}]}
    )
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        outcome = verify_citations(
            answer=answer, candidates=[proc_a, proc_b], mode="llm"
        )
    assert outcome.verifier_succeeded is True
    assert outcome.verified_citation_ids == ["proc-b"]
    assert "proc-a" not in outcome.verified_citation_ids


# --- B. shared actor/action, different relationship → reject ------------------


def test_B_shared_actor_action_different_relationship_rejected():
    wrong = _ev(
        "wd-1",
        "Withdrawal Consent",
        "The Registrar must consent before a student may withdraw permanently.",
    )
    right = _ev(
        "rf-1",
        "Fee Schedule Management",
        "The Registrar publishes the fee-refund schedule and timing windows.",
    )
    answer = (
        "The Registrar manages the fee-refund schedule, and the refund amount "
        "depends on when the withdrawal occurs."
    )
    mock_client = _mock_verifier_returning(
        {"claims": [{"claim_id": "c1", "supporting_citation_ids": ["S2"]}]}
    )
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        outcome = verify_citations(
            answer=answer, candidates=[wrong, right], mode="llm"
        )
    assert outcome.verifier_succeeded is True
    assert outcome.verified_citation_ids == ["rf-1"]
    assert "wd-1" not in outcome.verified_citation_ids


# --- C. evidence supporting entire compound relationship → retain -------------


def test_C_full_compound_relationship_retained():
    full = _ev(
        "full-1",
        "Integrated Policy",
        "The Registrar manages fee refunds. Refund amount depends on the "
        "week of withdrawal from opening of classes (75%/50%/none).",
    )
    distractor = _ev(
        "other-1",
        "Unrelated Consent",
        "The Registrar consents to permanent withdrawal paperwork.",
    )
    answer = (
        "The Registrar manages fee refunds, and the refund amount depends on "
        "the week of withdrawal."
    )
    mock_client = _mock_verifier_returning(
        {"claims": [{"claim_id": "c1", "supporting_citation_ids": ["S1"]}]}
    )
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        outcome = verify_citations(
            answer=answer, candidates=[full, distractor], mode="llm"
        )
    assert outcome.verifier_succeeded is True
    assert outcome.verified_citation_ids == ["full-1"]


# --- D. partial legitimate support where appropriate --------------------------


def test_D_partial_legitimate_support_still_possible():
    half = _ev(
        "half-1",
        "Refund Timing",
        "No refund after the fourth week from the opening of classes.",
    )
    other = _ev(
        "other-2",
        "Consent Rule",
        "Permanent withdrawal requires Registrar consent.",
    )
    answer = "No refund is available after the fourth week from opening of classes."
    mock_client = _mock_verifier_returning(
        {"claims": [{"claim_id": "c1", "supporting_citation_ids": ["S1"]}]}
    )
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        outcome = verify_citations(
            answer=answer, candidates=[half, other], mode="llm"
        )
    assert outcome.verifier_succeeded is True
    assert outcome.verified_citation_ids == ["half-1"]


# --- E. numeric/timing evidence behavior unchanged ----------------------------


def test_E_numeric_timing_evidence_unchanged():
    refund = _ev("refund-52", "Refunding of Fees", "50% refund from 2nd-4th week.")
    classification = _ev(
        "class-34",
        "Classifications of Students",
        "Junior = 50%-75% of units earned.",
    )
    mock_client = _mock_verifier_returning(
        {"claims": [{"claim_id": "c1", "supporting_citation_ids": ["S1"]}]}
    )
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        outcome = verify_citations(
            answer="You get a 50% refund.",
            candidates=[refund, classification],
            mode="llm",
        )
    assert outcome.verified_citation_ids == ["refund-52"]
    assert "class-34" not in outcome.verified_citation_ids


# --- F. multi-source: separate evidence for different components --------------


def test_F_multisource_components_retained():
    grade = _ev(
        "xfer-42",
        "Transferring",
        "Transferring students must satisfy the receiving college's grade requirements.",
    )
    cap = _ev(
        "val-58",
        "Validation Requirements",
        "Credited-without-validation subjects are capped at 50% of total credits.",
    )
    answer = (
        "Transferring students must satisfy the receiving college's grade "
        "requirements.\n"
        "Credited-without-validation subjects are capped at 50% of total credits."
    )
    mock_client = _mock_verifier_returning(
        {
            "claims": [
                {"claim_id": "c1", "supporting_citation_ids": ["S1"]},
                {"claim_id": "c2", "supporting_citation_ids": ["S2"]},
            ]
        }
    )
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        outcome = verify_citations(
            answer=answer, candidates=[grade, cap], mode="llm"
        )
    assert outcome.verifier_succeeded is True
    assert set(outcome.verified_citation_ids) == {"xfer-42", "val-58"}


# --- G. allowlist / fail-closed unchanged -------------------------------------


def test_G_hallucinated_id_still_fails_closed():
    candidates = [_ev("a", "T1", "...")]
    mock_client = _mock_verifier_returning(
        {"claims": [{"claim_id": "c1", "supporting_citation_ids": ["not-real"]}]}
    )
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        outcome = verify_citations(
            answer="Fee: None.", candidates=candidates, mode="llm"
        )
    assert outcome.verifier_succeeded is False
    assert "hallucinated_citation_id" in (outcome.failure_reason or "")
    assert outcome.verified_citation_ids == []
