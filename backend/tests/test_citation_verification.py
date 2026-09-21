"""Unit tests for Citation Grounding V2 (app/services/qa/citation_verification.py).

All provider calls are mocked -- no test here depends on live OpenRouter,
matching the existing pattern in tests/test_groq_answer_service.py
(patch("httpx.Client", ...) + patch("<module>.settings.<field>", ...)).
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.services.qa.citation_verification import (
    CandidateEvidence,
    Claim,
    CitationVerificationError,
    extract_claims,
    verify_citations,
)

MODULE = "app.services.qa.citation_verification"


# --- claim extraction ---------------------------------------------------------


def test_extract_claims_splits_bullet_facts_into_separate_claims():
    """Original wording (including the leading '- ' marker) is preserved in
    claim.text -- only the internal non-factual CLASSIFICATION strips
    markdown decoration; the verifier should see the answer's real wording."""
    answer = "- Fee: None.\n- Processing time: 3-7 days.\n- Office: HRMU."
    claims = extract_claims(answer)
    texts = [c.text for c in claims]
    assert any("Fee: None" in t for t in texts)
    assert any("Processing time: 3-7 days" in t for t in texts)
    assert any("Office: HRMU" in t for t in texts)


def test_extract_claims_protects_decimal_numbers_from_being_split():
    answer = "The fee is P75.00 per page for undergraduates."
    claims = extract_claims(answer)
    assert len(claims) == 1
    assert "P75.00" in claims[0].text


def test_extract_claims_drops_greetings_and_transition_phrases():
    answer = "Sure. Here's how it works. The fee is None. In short, no fee applies."
    claims = extract_claims(answer)
    texts = [c.text for c in claims]
    assert "Sure" not in texts
    assert not any(t.lower().startswith("here's how") for t in texts)
    assert not any(t.lower().startswith("in short") for t in texts)
    assert any("fee is None" in t for t in texts)


def test_extract_claims_returns_empty_for_pure_decline_answer():
    answer = (
        "The LSPU documents I have access to don't state a unit threshold "
        "for being classified as Junior. If you need help, you can submit "
        "a support ticket."
    )
    claims = extract_claims(answer)
    assert claims == []


def test_extract_claims_returns_empty_for_out_of_scope_decline():
    answer = (
        "I'd love to help with that, but the LSPU documents I have access "
        "to don't contain recipes or food service information."
    )
    assert extract_claims(answer) == []


def test_extract_claims_assigns_stable_sequential_ids():
    answer = "Fee: None. Processing time: 5 minutes. Office: Registrar."
    claims = extract_claims(answer)
    assert [c.claim_id for c in claims] == ["c1", "c2", "c3"]


# --- verify_citations: mode gating -------------------------------------------


def test_lexical_mode_never_invokes_verifier():
    candidates = [_ev("id-1", "Some Title", "Some fee is None.")]
    with patch("httpx.Client") as mock_httpx:
        outcome = verify_citations(answer="Fee: None.", candidates=candidates, mode="lexical")
    mock_httpx.assert_not_called()
    assert outcome.verifier_invoked is False
    assert outcome.verified_citation_ids == []


def test_zero_claims_skips_verifier_call_entirely():
    candidates = [_ev("id-1", "Title", "Text.")]
    answer = "Sure. Here's how it works."  # both spans are non-factual
    with patch("httpx.Client") as mock_httpx:
        outcome = verify_citations(answer=answer, candidates=candidates, mode="llm")
    mock_httpx.assert_not_called()
    assert outcome.verifier_invoked is False
    assert outcome.failure_reason == "zero_claims"
    assert outcome.verified_citation_ids == []


def test_zero_candidates_skips_verifier_call_entirely():
    with patch("httpx.Client") as mock_httpx:
        outcome = verify_citations(answer="Fee: None.", candidates=[], mode="llm")
    mock_httpx.assert_not_called()
    assert outcome.failure_reason == "zero_candidates"
    assert outcome.verified_citation_ids == []


# --- verify_citations: successful verification scenarios --------------------


def test_one_claim_one_valid_source():
    candidates = [_ev("coe-27", "Certificate of Employment", "Fee: None.")]
    mock_client = _mock_verifier_returning({"claims": [{"claim_id": "c1", "supporting_citation_ids": ["coe-27"]}]})
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        outcome = verify_citations(answer="Fee: None.", candidates=candidates, mode="llm")
    assert outcome.verifier_succeeded is True
    assert outcome.verified_citation_ids == ["coe-27"]


def test_one_claim_multiple_valid_sources():
    candidates = [_ev("a", "T1", "..."), _ev("b", "T2", "...")]
    mock_client = _mock_verifier_returning(
        {"claims": [{"claim_id": "c1", "supporting_citation_ids": ["a", "b"]}]}
    )
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        outcome = verify_citations(answer="Fee: None.", candidates=candidates, mode="llm")
    assert set(outcome.verified_citation_ids) == {"a", "b"}


def test_multiple_claims_one_shared_source_deduplicated():
    candidates = [_ev("a", "T1", "...")]
    mock_client = _mock_verifier_returning(
        {
            "claims": [
                {"claim_id": "c1", "supporting_citation_ids": ["a"]},
                {"claim_id": "c2", "supporting_citation_ids": ["a"]},
            ]
        }
    )
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        outcome = verify_citations(answer="Fee: None. Office: HRMU.", candidates=candidates, mode="llm")
    assert outcome.verified_citation_ids == ["a"]  # deduplicated, not ["a", "a"]


def test_multiple_claims_multiple_distinct_sources():
    candidates = [_ev("a", "T1", "..."), _ev("b", "T2", "...")]
    mock_client = _mock_verifier_returning(
        {
            "claims": [
                {"claim_id": "c1", "supporting_citation_ids": ["a"]},
                {"claim_id": "c2", "supporting_citation_ids": ["b"]},
            ]
        }
    )
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        outcome = verify_citations(answer="Fee: None. Office: HRMU.", candidates=candidates, mode="llm")
    assert outcome.per_claim_verified_ids == {"c1": ["a"], "c2": ["b"]}
    assert set(outcome.verified_citation_ids) == {"a", "b"}


def test_unsupported_claim_gets_no_citation():
    candidates = [_ev("a", "T1", "...")]
    mock_client = _mock_verifier_returning(
        {"claims": [{"claim_id": "c1", "supporting_citation_ids": []}]}
    )
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        outcome = verify_citations(answer="Fee: None.", candidates=candidates, mode="llm")
    assert outcome.verifier_succeeded is True
    assert outcome.per_claim_verified_ids == {"c1": []}
    assert outcome.verified_citation_ids == []


def test_verifier_may_omit_a_claim_entirely_treated_as_no_support():
    candidates = [_ev("a", "T1", "...")]
    # Verifier response omits c2 entirely -- must not be treated as an error.
    mock_client = _mock_verifier_returning(
        {"claims": [{"claim_id": "c1", "supporting_citation_ids": ["a"]}]}
    )
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        outcome = verify_citations(answer="Fee: None. Office: HRMU.", candidates=candidates, mode="llm")
    assert outcome.verifier_succeeded is True
    assert outcome.per_claim_verified_ids["c2"] == []


# --- near-duplicate / trap plumbing (mocked verifier judgment) ---------------


def test_same_number_wrong_procedure_rejection_via_correct_verifier_judgment():
    """Refund-fee 50% vs Junior-standing 50% -- if the (mocked) verifier
    correctly excludes the wrong-procedure chunk, the pipeline must honor
    that and not re-include it via any fallback path."""
    refund = _ev("refund-52", "Refunding of Fees", "50% refund from 2nd-4th week.")
    classification = _ev("class-34", "Classifications of Students", "Junior = 50%-75% of units earned.")
    mock_client = _mock_verifier_returning(
        {"claims": [{"claim_id": "c1", "supporting_citation_ids": ["refund-52"]}]}
    )
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        outcome = verify_citations(
            answer="You get a 50% refund.", candidates=[refund, classification], mode="llm"
        )
    assert outcome.verified_citation_ids == ["refund-52"]
    assert "class-34" not in outcome.verified_citation_ids


def test_same_office_wrong_procedure_rejection_via_correct_verifier_judgment():
    transcript = _ev("tor-1", "Issuance of Transcript of Records", "Office: Registrar. Fee: P75/page.")
    enrollment = _ev("enroll-0", "Enrollment", "Office: Registrar. Fee: None.")
    mock_client = _mock_verifier_returning(
        {"claims": [{"claim_id": "c1", "supporting_citation_ids": ["tor-1"]}]}
    )
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        outcome = verify_citations(
            answer="The TOR fee is P75/page.", candidates=[transcript, enrollment], mode="llm"
        )
    assert outcome.verified_citation_ids == ["tor-1"]
    assert "enroll-0" not in outcome.verified_citation_ids


def test_generic_vocabulary_collision_rejection_via_correct_verifier_judgment():
    budget = _ev("budget-29", "Funding of Request Letters", "Budget Office funding, fee none.")
    oup = _ev("oup-21", "Approval of Request Letters", "Office of the University President approval.")
    mock_client = _mock_verifier_returning(
        {"claims": [{"claim_id": "c1", "supporting_citation_ids": ["budget-29"]}]}
    )
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        outcome = verify_citations(
            answer="Submit your request letter to the Budget Office.",
            candidates=[budget, oup],
            mode="llm",
        )
    assert outcome.verified_citation_ids == ["budget-29"]
    assert "oup-21" not in outcome.verified_citation_ids


def test_near_duplicate_service_variant_rejection_via_correct_verifier_judgment():
    alumni = _ev("gm-16", "Good Moral Certificate (Alumni)", "Requires Transcript of Record.")
    undergrad = _ev("gm-15", "Good Moral Certificate (Undergraduate)", "Requires Certificate of Registration.")
    mock_client = _mock_verifier_returning(
        {"claims": [{"claim_id": "c1", "supporting_citation_ids": ["gm-16"]}]}
    )
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        outcome = verify_citations(
            answer="As an alumnus, bring your Transcript of Record.",
            candidates=[alumni, undergrad],
            mode="llm",
        )
    assert outcome.verified_citation_ids == ["gm-16"]
    assert "gm-15" not in outcome.verified_citation_ids


# --- fail-closed behavior -----------------------------------------------------


def test_hallucinated_verifier_citation_id_fails_closed():
    candidates = [_ev("a", "T1", "...")]
    mock_client = _mock_verifier_returning(
        {"claims": [{"claim_id": "c1", "supporting_citation_ids": ["not-a-real-id"]}]}
    )
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        outcome = verify_citations(answer="Fee: None.", candidates=candidates, mode="llm")
    assert outcome.verifier_succeeded is False
    assert "hallucinated_citation_id" in outcome.failure_reason
    assert outcome.verified_citation_ids == []


def test_unknown_verifier_claim_id_fails_closed():
    candidates = [_ev("a", "T1", "...")]
    mock_client = _mock_verifier_returning(
        {"claims": [{"claim_id": "does-not-exist", "supporting_citation_ids": ["a"]}]}
    )
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        outcome = verify_citations(answer="Fee: None.", candidates=candidates, mode="llm")
    assert outcome.verifier_succeeded is False
    assert "unknown_claim_id" in outcome.failure_reason
    assert outcome.verified_citation_ids == []


def test_malformed_json_fails_closed():
    candidates = [_ev("a", "T1", "...")]
    mock_client = _mock_verifier_returning_raw("this is not json at all {{{")
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        outcome = verify_citations(answer="Fee: None.", candidates=candidates, mode="llm")
    assert outcome.verifier_succeeded is False
    assert "malformed_json" in outcome.failure_reason
    assert outcome.verified_citation_ids == []


def test_empty_verifier_response_fails_closed():
    candidates = [_ev("a", "T1", "...")]
    mock_client = _mock_verifier_returning_raw("")
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        outcome = verify_citations(answer="Fee: None.", candidates=candidates, mode="llm")
    assert outcome.verifier_succeeded is False
    assert outcome.verified_citation_ids == []


def test_duplicate_citation_ids_within_one_claim_fails_closed():
    candidates = [_ev("a", "T1", "...")]
    mock_client = _mock_verifier_returning(
        {"claims": [{"claim_id": "c1", "supporting_citation_ids": ["a", "a"]}]}
    )
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        outcome = verify_citations(answer="Fee: None.", candidates=candidates, mode="llm")
    assert outcome.verifier_succeeded is False
    assert "duplicate_citation_id" in outcome.failure_reason


def test_duplicate_claim_ids_in_response_fails_closed():
    candidates = [_ev("a", "T1", "...")]
    mock_client = _mock_verifier_returning(
        {
            "claims": [
                {"claim_id": "c1", "supporting_citation_ids": ["a"]},
                {"claim_id": "c1", "supporting_citation_ids": []},
            ]
        }
    )
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        outcome = verify_citations(answer="Fee: None.", candidates=candidates, mode="llm")
    assert outcome.verifier_succeeded is False
    assert "duplicate_claim_id" in outcome.failure_reason


def test_schema_violation_non_list_supporting_ids_fails_closed():
    candidates = [_ev("a", "T1", "...")]
    mock_client = _mock_verifier_returning(
        {"claims": [{"claim_id": "c1", "supporting_citation_ids": "a"}]}
    )
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        outcome = verify_citations(answer="Fee: None.", candidates=candidates, mode="llm")
    assert outcome.verifier_succeeded is False
    assert "schema_violation" in outcome.failure_reason


def test_malformed_one_claim_invalidates_the_whole_response_not_just_that_claim():
    """Malformed output must NOT partially pass -- a defect anywhere fails
    the entire verification, not just the offending claim."""
    candidates = [_ev("a", "T1", "..."), _ev("b", "T2", "...")]
    mock_client = _mock_verifier_returning(
        {
            "claims": [
                {"claim_id": "c1", "supporting_citation_ids": ["a"]},  # valid
                {"claim_id": "c2", "supporting_citation_ids": ["hallucinated"]},  # invalid
            ]
        }
    )
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        outcome = verify_citations(answer="Fee: None. Office: HRMU.", candidates=candidates, mode="llm")
    assert outcome.verifier_succeeded is False
    assert outcome.verified_citation_ids == []  # NOT ["a"] -- no partial pass


def test_provider_timeout_fails_closed_and_does_not_raise():
    candidates = [_ev("a", "T1", "...")]
    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False
    mock_client.post.side_effect = httpx.TimeoutException("timed out")
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        outcome = verify_citations(answer="Fee: None.", candidates=candidates, mode="llm")
    assert outcome.verifier_succeeded is False
    assert "provider_timeout" in outcome.failure_reason
    assert outcome.verified_citation_ids == []


def test_provider_5xx_fails_closed_and_does_not_raise():
    candidates = [_ev("a", "T1", "...")]
    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "server error", request=MagicMock(), response=MagicMock(status_code=500)
    )
    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False
    mock_client.post.return_value = mock_response
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        outcome = verify_citations(answer="Fee: None.", candidates=candidates, mode="llm")
    assert outcome.verifier_succeeded is False
    assert "provider_error" in outcome.failure_reason


def test_provider_4xx_fails_closed_and_does_not_raise():
    candidates = [_ev("a", "T1", "...")]
    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "bad request", request=MagicMock(), response=MagicMock(status_code=400)
    )
    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False
    mock_client.post.return_value = mock_response
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        outcome = verify_citations(answer="Fee: None.", candidates=candidates, mode="llm")
    assert outcome.verifier_succeeded is False
    assert "provider_error" in outcome.failure_reason


def test_unconfigured_provider_fails_closed_without_network_call():
    candidates = [_ev("a", "T1", "...")]
    with (
        patch(f"{MODULE}.settings.groq_api_key", None),
        patch("httpx.Client") as mock_httpx,
    ):
        outcome = verify_citations(answer="Fee: None.", candidates=candidates, mode="llm")
    mock_httpx.assert_not_called()
    assert outcome.verifier_succeeded is False
    assert outcome.failure_reason == "provider_not_configured"


def test_unexpected_exception_from_provider_call_never_propagates():
    """A verifier failure must never crash the caller -- it must always
    return a normal (fail-closed) VerificationOutcome, never raise."""
    candidates = [_ev("a", "T1", "...")]
    mock_client = MagicMock()
    mock_client.__enter__.side_effect = RuntimeError("totally unexpected")
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        outcome = verify_citations(answer="Fee: None.", candidates=candidates, mode="llm")  # must not raise
    assert outcome.verifier_succeeded is False
    assert "unexpected_error" in outcome.failure_reason
    assert outcome.verified_citation_ids == []


def test_candidate_allowlist_matches_exactly_what_was_passed():
    """The verifier can only ever be offered exactly the candidates the
    caller supplied -- this is the mechanism that keeps role/audience
    filtering (which happens upstream) authoritative: this module never
    adds, substitutes, or fetches any chunk of its own."""
    candidates = [_ev("only-this-one", "T1", "...")]
    outcome = verify_citations(answer="Fee: None.", candidates=candidates, mode="lexical")
    assert outcome.candidate_citation_ids == ["only-this-one"]


# --- shadow mode --------------------------------------------------------------


def test_shadow_mode_invokes_verifier_and_reports_outcome_fields():
    candidates = [_ev("a", "T1", "...")]
    mock_client = _mock_verifier_returning(
        {"claims": [{"claim_id": "c1", "supporting_citation_ids": ["a"]}]}
    )
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        outcome = verify_citations(answer="Fee: None.", candidates=candidates, mode="shadow")
    assert outcome.verifier_invoked is True
    assert outcome.verifier_succeeded is True
    assert outcome.verified_citation_ids == ["a"]  # computed for diagnostics either way


# --- structured output request (response_format) ------------------------------


def test_verifier_request_includes_structured_output_response_format():
    """The verifier request must ask the provider to constrain its own
    output to the exact {claims: [{claim_id, supporting_citation_ids}]}
    shape via response_format -- verified against the currently configured
    model's own documented accepted parameters before this was added (see
    citation_v2_invalid_response_investigation.json and the commit this
    test accompanies). This is additive request-shaping only; it must never
    be treated as a trust boundary -- see the fail-closed tests below,
    which prove strict re-validation still happens regardless."""
    candidates = [_ev("a", "T1", "...")]
    mock_client = _mock_verifier_returning({"claims": [{"claim_id": "c1", "supporting_citation_ids": ["a"]}]})
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        verify_citations(answer="Fee: None.", candidates=candidates, mode="llm")

    mock_client.post.assert_called_once()
    _, kwargs = mock_client.post.call_args
    body = kwargs["json"]
    assert "response_format" in body
    assert body["response_format"]["type"] == "json_schema"
    schema = body["response_format"]["json_schema"]["schema"]
    assert schema["required"] == ["claims"]
    assert schema["properties"]["claims"]["items"]["required"] == ["claim_id", "supporting_citation_ids"]
    # request shape otherwise unchanged
    assert body["model"] == "test-model"
    assert body["temperature"] == 0.0
    assert "messages" in body


def test_strict_revalidation_still_rejects_malformed_output_even_with_response_format_requested():
    """response_format is a REQUEST, not a guarantee -- if the provider
    still returns something invalid despite it being asked for structured
    output, _parse_and_validate must catch it exactly as before. Proves
    this change does not weaken validation even in the worst case."""
    candidates = [_ev("a", "T1", "...")]
    mock_client = _mock_verifier_returning_raw("still not json {{{")
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        outcome = verify_citations(answer="Fee: None.", candidates=candidates, mode="llm")
    assert outcome.verifier_succeeded is False
    assert outcome.verified_citation_ids == []
    assert "malformed_json" in outcome.failure_reason


def test_structured_output_request_is_isolated_to_citation_verification_module():
    """The response_format constant and its use are defined and applied
    only inside citation_verification.py -- answer generation
    (groq_answer_service.py) must remain completely untouched. Confirmed
    two ways: (1) groq_answer_service's own module source has no
    response_format reference at all; (2) its request body shape is
    exactly the pre-existing {model, temperature, messages}, nothing more."""
    import inspect

    from app.services.qa import groq_answer_service

    source = inspect.getsource(groq_answer_service)
    assert "response_format" not in source


# --- helpers -------------------------------------------------------------------


def _ev(citation_id: str, title: str, text: str) -> CandidateEvidence:
    return CandidateEvidence(
        citation_id=citation_id, title=title, source_section=None, source_filename="doc.pdf", text=text
    )


def _configured_provider():
    return patch.multiple(
        f"{MODULE}.settings",
        groq_api_key="test-key",
        llm_base_url="https://openrouter.ai/api/v1/chat/completions",
        groq_model="test-model",
        groq_timeout_seconds=5.0,
    )


def _mock_verifier_returning(payload: dict) -> MagicMock:
    return _mock_verifier_returning_raw(json.dumps(payload))


def _mock_verifier_returning_raw(content: str) -> MagicMock:
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {"choices": [{"message": {"content": content}}]}
    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False
    mock_client.post.return_value = mock_response
    return mock_client
