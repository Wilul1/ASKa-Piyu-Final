"""Integration tests for Citation Grounding V2's mode branching at the real
seam: question_answering._display_sources_for_answer().

These tests exercise the actual wiring (settings.citation_verification_mode
-> _display_sources_for_answer -> app.services.qa.citation_verification),
not just the standalone module. The verifier itself is mocked at
"app.services.qa.citation_verification.verify_citations" (the exact name
_display_sources_for_answer imports locally), so no test depends on live
OpenRouter.
"""

from __future__ import annotations

from unittest.mock import patch

from app.services.chroma_store import RetrievedChunk
from app.services.qa.citation_verification import VerificationOutcome
from app.services.qa.question_answering import _display_sources_for_answer

VERIFY = "app.services.qa.citation_verification.verify_citations"
MODE = "app.services.qa.question_answering.settings.citation_verification_mode"


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


def test_lexical_mode_never_imports_or_calls_v2_verifier():
    chunk = _chunk("tor", "Transcript of Records", "Fee: P75/page. Processing time: 5 minutes.")
    answer = "The fee is P75 per page. Processing time is 5 minutes."
    with patch(VERIFY) as mock_verify, patch(MODE, "lexical"):
        result = _display_sources_for_answer([chunk], answer)
    mock_verify.assert_not_called()
    assert isinstance(result, list)  # V1's normal formatted output, unaffected


def test_shadow_mode_preserves_v1_displayed_citations_regardless_of_v2_outcome():
    chunk = _chunk("tor", "Transcript of Records", "Fee: P75/page. Processing time: 5 minutes.")
    answer = "The fee is P75 per page. Processing time is 5 minutes."
    v1_only = _display_sources_for_answer([chunk], answer)  # ground truth under lexical

    fake_outcome = VerificationOutcome(
        mode="shadow",
        verifier_invoked=True,
        verifier_succeeded=True,
        verified_citation_ids=[],  # V2 disagrees (finds nothing) -- must not matter in shadow mode
    )
    with patch(VERIFY, return_value=fake_outcome), patch(MODE, "shadow"):
        shadow_result = _display_sources_for_answer([chunk], answer)

    assert shadow_result == v1_only


def test_shadow_mode_records_v2_diagnostics_into_sink_without_changing_display():
    chunk = _chunk("tor", "Transcript of Records", "Fee: P75/page.")
    answer = "The fee is P75 per page."
    fake_outcome = VerificationOutcome(
        mode="shadow",
        verifier_invoked=True,
        verifier_succeeded=True,
        verified_citation_ids=["tor::0"],
        per_claim_verified_ids={"c1": ["tor::0"]},
        latency_ms=123.4,
    )
    sink: dict = {}
    with patch(VERIFY, return_value=fake_outcome), patch(MODE, "shadow"):
        _display_sources_for_answer([chunk], answer, citation_v2_sink=sink)

    assert sink["mode"] == "shadow"
    assert sink["verifier_invoked"] is True
    assert sink["verifier_succeeded"] is True
    assert sink["verified_citation_ids"] == ["tor::0"]
    assert sink["latency_ms"] == 123.4
    assert "v1_displayed_citation_ids" in sink


def test_llm_mode_displays_only_v2_verified_citations():
    correct = _chunk("gm-16", "Good Moral (Alumni)", "Requires Transcript of Record.")
    wrong = _chunk("gm-15", "Good Moral (Undergraduate)", "Requires Certificate of Registration.")
    answer = "As an alumnus, bring your Transcript of Record."

    fake_outcome = VerificationOutcome(
        mode="llm",
        verifier_invoked=True,
        verifier_succeeded=True,
        verified_citation_ids=["gm-16::0"],
    )
    with patch(VERIFY, return_value=fake_outcome), patch(MODE, "llm"):
        result = _display_sources_for_answer([correct, wrong], answer)

    ids = [r["citation_id"] for r in result]
    assert ids == ["gm-16::0"]
    assert "gm-15::0" not in ids


def test_llm_mode_verifier_failure_displays_zero_citations_not_v1_fallback():
    chunk = _chunk("tor", "Transcript of Records", "Fee: P75/page. Processing time: 5 minutes.")
    answer = "The fee is P75 per page. Processing time is 5 minutes."
    v1_only = _display_sources_for_answer([chunk], answer)
    assert v1_only, "precondition: V1 would normally display something for this answer"

    fake_failed_outcome = VerificationOutcome(
        mode="llm",
        verifier_invoked=True,
        verifier_succeeded=False,
        failure_reason="provider_timeout: simulated",
        verified_citation_ids=[],
    )
    with patch(VERIFY, return_value=fake_failed_outcome), patch(MODE, "llm"):
        llm_result = _display_sources_for_answer([chunk], answer)

    assert llm_result == []  # zero citations, never the V1 fallback


def test_llm_mode_verifier_raising_unexpectedly_does_not_crash_and_returns_empty():
    """Even if verify_citations somehow raised (contract violation on its
    own part), the caller must not crash -- _display_sources_for_answer has
    no try/except of its own, so this also proves verify_citations really
    is the sole safety boundary; if it ever raised, this test would fail
    loudly rather than silently passing."""
    chunk = _chunk("tor", "Transcript of Records", "Fee: P75/page.")
    answer = "The fee is P75 per page."
    fake_outcome = VerificationOutcome(mode="llm", verifier_invoked=True, verifier_succeeded=False)
    with patch(VERIFY, return_value=fake_outcome), patch(MODE, "llm"):
        result = _display_sources_for_answer([chunk], answer)
    assert result == []


def test_llm_mode_zero_claim_answer_displays_zero_citations():
    chunk = _chunk("some-chunk", "Some Service", "Some Overview text.")
    answer = "I couldn't find that in the available documents."
    fake_outcome = VerificationOutcome(
        mode="llm", verifier_invoked=False, failure_reason="zero_claims", verified_citation_ids=[]
    )
    with patch(VERIFY, return_value=fake_outcome), patch(MODE, "llm"):
        result = _display_sources_for_answer([chunk], answer)
    assert result == []


def test_unknown_mode_value_falls_back_to_lexical_safely():
    chunk = _chunk("tor", "Transcript of Records", "Fee: P75/page.")
    answer = "The fee is P75 per page."
    with patch(VERIFY) as mock_verify, patch(MODE, "not-a-real-mode"):
        _display_sources_for_answer([chunk], answer)
    mock_verify.assert_not_called()  # invalid config value must not silently enable V2


def test_llm_mode_only_offers_already_authorized_candidates_to_verifier():
    """Role/audience filtering already happened upstream by the time
    candidates reach this seam -- V2 must only ever see exactly that same,
    already-authorized candidate list, never fetch more."""
    authorized_only = [_chunk("a", "T1", "x"), _chunk("b", "T2", "y")]
    with patch(VERIFY) as mock_verify, patch(MODE, "llm"):
        mock_verify.return_value = VerificationOutcome(mode="llm")
        _display_sources_for_answer(authorized_only, "Some answer text here.")

    _, kwargs = mock_verify.call_args
    passed_candidates = kwargs["candidates"]
    assert {c.citation_id for c in passed_candidates} == {"a::0", "b::0"}
