"""Unit tests for Citation Grounding V2 (app/services/qa/citation_verification.py).

All provider calls are mocked -- no test here depends on live OpenRouter,
matching the existing pattern in tests/test_groq_answer_service.py
(patch("httpx.Client", ...) + patch("<module>.settings.<field>", ...)).
"""

from __future__ import annotations

import json
import re
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.services.qa import citation_verification
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


def test_extract_claims_preserves_audience_heading_on_bullets():
    answer = (
        "For Alumni:\n"
        "- Transcript of Records is required.\n"
        "- Student ID is required."
    )
    claims = extract_claims(answer)
    texts = [c.text for c in claims]
    assert len(claims) >= 2
    assert all(re.search(r"alumni", t, re.I) for t in texts)
    assert any("Transcript of Records" in t for t in texts)
    assert any("Student ID" in t for t in texts)
    # Heading itself is context, not a standalone claim.
    assert not any(re.fullmatch(r"for alumni:?", t.strip(), re.I) for t in texts)


def test_extract_claims_keeps_near_duplicate_audiences_separate():
    answer = (
        "### Undergraduate\n"
        "- Certificate of Registration is required.\n"
        "### Transferee\n"
        "- Certificate of Transfer is required.\n"
        "### Alumni\n"
        "- Transcript of Records is required."
    )
    claims = extract_claims(answer)
    undergrad = [c.text for c in claims if re.search(r"undergraduate", c.text, re.I)]
    transfer = [c.text for c in claims if re.search(r"transferee", c.text, re.I)]
    alumni = [c.text for c in claims if re.search(r"alumni", c.text, re.I)]
    assert undergrad and any("Certificate of Registration" in t for t in undergrad)
    assert transfer and any("Certificate of Transfer" in t for t in transfer)
    assert alumni and any("Transcript of Records" in t for t in alumni)
    # No cross-inheritance of the wrong audience onto another section's document.
    claim_texts = [c.text for c in claims]
    assert not any(
        re.search(r"undergraduate", t, re.I) and "Transcript of Records" in t for t in claim_texts
    )
    assert not any(
        re.search(r"alumni", t, re.I) and "Certificate of Registration" in t for t in claim_texts
    )
    assert not any(
        re.search(r"transferee", t, re.I) and "Certificate of Registration" in t for t in claim_texts
    )


def test_extract_claims_separates_substitution_and_shifting_procedures():
    answer = (
        "Course Substitution\n"
        "- An application letter is required.\n"
        "Shifting\n"
        "- A filled-out shifting form is required."
    )
    claims = extract_claims(answer)
    sub = [c.text for c in claims if re.search(r"substitution", c.text, re.I)]
    shift = [c.text for c in claims if re.search(r"shifting", c.text, re.I)]
    assert sub and any("application letter" in t.lower() for t in sub)
    assert shift and any("shifting form" in t.lower() for t in shift)
    claim_texts = [c.text for c in claims]
    assert not any(
        re.search(r"substitution", t, re.I) and "shifting form" in t.lower() for t in claim_texts
    )
    assert not any(
        re.search(r"shifting", t, re.I)
        and "application letter" in t.lower()
        and not re.search(r"substitution", t, re.I)
        for t in claim_texts
    )


def test_extract_claims_separates_validation_procedures():
    answer = (
        "Subject Validation\n"
        "- There is no fee for subject validation.\n"
        "ID Validation\n"
        "- ID validation takes 4 minutes."
    )
    claims = extract_claims(answer)
    subject = [c.text for c in claims if re.search(r"subject validation", c.text, re.I)]
    id_val = [c.text for c in claims if re.search(r"\bid validation\b", c.text, re.I)]
    assert subject and any("no fee" in t.lower() for t in subject)
    assert id_val and any("4 minutes" in t.lower() for t in id_val)
    claim_texts = [c.text for c in claims]
    assert not any(
        re.search(r"subject validation", t, re.I) and "4 minutes" in t.lower()
        for t in claim_texts
    )


def test_extract_claims_ignores_nonsemantic_generic_heading():
    answer = (
        "### Additional Information\n"
        "- The Registrar office handles the request.\n"
        "- Processing takes five minutes."
    )
    claims = extract_claims(answer)
    texts = [c.text for c in claims]
    assert any("Registrar" in t for t in texts)
    assert any("five minutes" in t for t in texts)
    assert not any(re.search(r"additional information", t, re.I) for t in texts)


def test_extract_claims_ordinary_paragraph_unchanged_shape():
    answer = "The fee is None. Processing time is 5 minutes."
    claims = extract_claims(answer)
    assert [c.claim_id for c in claims] == ["c1", "c2"]
    assert "fee is None" in claims[0].text
    assert "5 minutes" in claims[1].text


def test_extract_claims_qualifier_respects_max_claim_length():
    from app.services.qa.citation_verification import _MAX_CLAIM_CHARS

    long_fact = "Fact token " * 80  # well over remaining room once qualified
    answer = f"Alumni Good Moral Certificate\n- {long_fact.strip()}."
    claims = extract_claims(answer)
    assert claims
    # Either prepend skipped (length guard) or still within ceiling.
    assert all(len(c.text) <= _MAX_CLAIM_CHARS or "Alumni" not in c.text for c in claims)
    assert all(len(c.text) >= 4 for c in claims)


def test_extract_claims_fg_j1_audience_document_distinctions():
    """Structural stand-in for Fresh Gold fg_j1 near-duplicate Good Moral."""
    answer = (
        "Issuance of Good Moral Certificate (Undergraduate)\n"
        "- Certificate of Registration is required.\n"
        "- Student ID is required.\n"
        "Issuance of Good Moral Certificate (Transferee)\n"
        "- Certificate of Transfer is required.\n"
        "- Student ID is required.\n"
        "Issuance of Good Moral Certificate (LSPU Alumni)\n"
        "- Transcript of Records is required.\n"
        "- Student ID is required."
    )
    claims = extract_claims(answer)
    alumni_tor = [
        c.text
        for c in claims
        if re.search(r"alumni", c.text, re.I) and "Transcript of Records" in c.text
    ]
    undergrad_cor = [
        c.text
        for c in claims
        if re.search(r"undergraduate", c.text, re.I)
        and "Certificate of Registration" in c.text
    ]
    transfer_cot = [
        c.text
        for c in claims
        if re.search(r"transferee", c.text, re.I) and "Certificate of Transfer" in c.text
    ]
    assert alumni_tor
    assert undergrad_cor
    assert transfer_cot
    claim_texts = [c.text for c in claims]
    assert not any(
        re.search(r"alumni", t, re.I) and "Certificate of Registration" in t for t in claim_texts
    )


def test_extract_claims_fg_e2_substitution_vs_shifting_structure():
    """Structural stand-in for Fresh Gold fg_e2 multi-procedure answer."""
    answer = (
        "**Course Substitution**\n"
        "- Submit an application letter indicating the reasons.\n"
        "- Requests must be recommended by the Program Coordinator/Dean.\n"
        "**Shifting**\n"
        "- A filled-out shifting form from the Office of the Registrar is required.\n"
        "- No failure of greater than six (6) units during the semester."
    )
    claims = extract_claims(answer)
    claim_texts = [c.text for c in claims]
    assert all("**" not in t for t in claim_texts)
    sub_claims = [t for t in claim_texts if re.search(r"substitution", t, re.I)]
    shift_claims = [
        t
        for t in claim_texts
        if re.search(r"shifting", t, re.I) and not re.search(r"substitution", t, re.I)
    ]
    assert any("application letter" in t.lower() for t in sub_claims)
    assert any(
        re.search(r"^[\-\*•]?\s*shifting\s*:", t, re.I) and "shifting form" in t.lower()
        for t in shift_claims
    )
    assert any("six (6) units" in t or "6) units" in t for t in shift_claims)
    assert not any("shifting form" in t.lower() for t in sub_claims)


def test_extract_claims_fg_h1_validation_procedure_identity():
    """Structural stand-in for Fresh Gold fg_h1 ID vs subject validation aside."""
    answer = (
        "ID Validation\n"
        "- There is no fee for ID validation.\n"
        "- The total processing time for ID validation is 4 minutes.\n"
        "Subject Validation\n"
        "- Subject validation may be examined during the final exam period."
    )
    claims = extract_claims(answer)
    id_claims = [c.text for c in claims if re.search(r"\bid validation\b", c.text, re.I)]
    subject_claims = [
        c.text for c in claims if re.search(r"subject validation", c.text, re.I)
    ]
    assert any("no fee" in t.lower() for t in id_claims)
    assert any("4 minutes" in t.lower() for t in id_claims)
    assert any("final exam" in t.lower() for t in subject_claims)
    assert not any("4 minutes" in t.lower() for t in subject_claims)


def test_extract_claims_bold_markdown_headings_clean_qualifiers():
    """Regression: balanced **…** must not leave trailing stars in qualifiers."""
    answer = (
        "**Course Substitution**\n"
        "- Application letter is required.\n"
        "**For Alumni:**\n"
        "- TOR is required.\n"
        "**ID Validation**\n"
        "- Processing takes 4 minutes.\n"
        "**Additional Information**\n"
        "- The Registrar office handles the request."
    )
    claims = extract_claims(answer)
    texts = [c.text for c in claims]
    assert all("**" not in t for t in texts)
    assert all("__" not in t for t in texts)
    assert any(
        re.search(r"course substitution\s*:", t, re.I) and "application letter" in t.lower()
        for t in texts
    )
    assert any(
        re.search(r"for alumni\s*:", t, re.I) and "TOR is required" in t for t in texts
    )
    assert any(
        re.search(r"\bid validation\s*:", t, re.I) and "4 minutes" in t.lower()
        for t in texts
    )
    # Bold generic heading is not a claim and must not become a qualifier.
    assert not any(re.search(r"additional information", t, re.I) for t in texts)
    assert any("Registrar" in t for t in texts)
    # Heading labels themselves are not independent factual claims.
    assert not any(re.fullmatch(r"for alumni:?", t.strip(), re.I) for t in texts)
    assert not any(re.fullmatch(r"course substitution:?", t.strip(), re.I) for t in texts)


def test_extract_claims_inline_bold_facts_remain_claims():
    for answer in ("**TOR is required.**", "**Processing takes 3 days.**"):
        claims = extract_claims(answer)
        assert len(claims) >= 1
        joined = " ".join(c.text for c in claims)
        assert "**" not in joined
        # Must be emitted as claims, not swallowed as context-only headings.
        assert claims[0].claim_id.startswith("c")
    tor = extract_claims("**TOR is required.**")
    assert any("TOR is required" in c.text for c in tor)
    proc = extract_claims("**Processing takes 3 days.**")
    assert any("Processing takes 3 days" in c.text for c in proc)
    # Not context-only labels: a following bullet would not inherit them as
    # section qualifiers (they are facts, not headings).
    follow = extract_claims("**TOR is required.**\n- Fee is None.")
    fee = [c.text for c in follow if "Fee is None" in c.text]
    assert fee
    assert not any(re.search(r"\bTOR\s*:", t, re.I) for t in fee)


def test_extract_claims_generic_section_clears_stale_qualifier():
    answer = (
        "For Alumni:\n"
        "- TOR is required.\n"
        "\n"
        "Additional Information:\n"
        "- Processing takes one hour."
    )
    claims = extract_claims(answer)
    texts = [c.text for c in claims]
    alumni_tor = [
        t for t in texts if re.search(r"alumni", t, re.I) and "TOR is required" in t
    ]
    assert alumni_tor
    processing = [t for t in texts if "one hour" in t.lower()]
    assert processing
    assert not any(re.search(r"alumni", t, re.I) for t in processing)
    assert not any(re.search(r"additional information", t, re.I) for t in texts)


def test_extract_claims_summary_clears_stale_qualifier():
    answer = (
        "For Alumni:\n"
        "- TOR is required.\n"
        "Summary:\n"
        "- Processing takes one hour."
    )
    claims = extract_claims(answer)
    texts = [c.text for c in claims]
    assert any(re.search(r"alumni", t, re.I) and "TOR is required" in t for t in texts)
    processing = [t for t in texts if "one hour" in t.lower()]
    assert processing
    assert not any(re.search(r"alumni", t, re.I) for t in processing)
    assert not any(re.search(r"\bsummary\s*:", t, re.I) for t in texts)


def test_extract_claims_structural_generics_are_not_semantic_qualifiers():
    for label in ("Summary:", "Procedure:", "Steps:", "Notes:", "Requirements:"):
        answer = f"{label}\n- Processing takes five minutes."
        claims = extract_claims(answer)
        texts = [c.text for c in claims]
        assert any("five minutes" in t.lower() for t in texts)
        bare = label.rstrip(":").strip()
        assert not any(re.search(rf"\b{re.escape(bare)}\s*:", t, re.I) for t in texts)
        assert not any(re.fullmatch(rf"{re.escape(bare)}:?", t.strip(), re.I) for t in texts)


def test_extract_claims_nested_subsection_scaffolds_preserve_qualifier():
    cases = [
        (
            "For Alumni:\nRequirements:\n- TOR is required.",
            r"alumni",
            "TOR is required",
        ),
        (
            "For Transferees:\nRequirements:\n- Certificate of Transfer is required.",
            r"transferee",
            "Certificate of Transfer",
        ),
        (
            "Course Substitution:\nProcedure:\n- Submit an application letter.",
            r"substitution",
            "application letter",
        ),
        (
            "ID Validation:\nSteps:\n- Present the required ID.",
            r"\bid validation\b",
            "Present the required ID",
        ),
    ]
    for answer, scope_re, fact in cases:
        texts = [c.text for c in extract_claims(answer)]
        assert any(
            re.search(scope_re, t, re.I) and fact.lower() in t.lower() for t in texts
        ), answer
        # Scaffold word must not enter the qualifier stack.
        assert not any(re.search(r"requirements\s*:", t, re.I) for t in texts)
        assert not any(re.search(r"procedure\s*:", t, re.I) for t in texts)
        assert not any(re.search(r"\bsteps\s*:", t, re.I) for t in texts)


def test_extract_claims_notes_important_reminder_preserve_active_qualifier():
    for scaffold in ("Notes:", "Important:", "Reminder:"):
        answer = (
            f"Course Substitution\n{scaffold}\n"
            "- The application must be submitted before the deadline."
        )
        texts = [c.text for c in extract_claims(answer)]
        assert any(
            re.search(r"substitution", t, re.I) and "deadline" in t.lower() for t in texts
        ), scaffold
        bare = scaffold.rstrip(":").strip()
        assert not any(re.search(rf"\b{re.escape(bare)}\s*:", t, re.I) for t in texts)


def test_extract_claims_good_moral_nested_requirements_keep_audiences():
    answer = (
        "Issuance of Good Moral Certificate (Alumni)\n"
        "Requirements:\n"
        "- Transcript of Records is required.\n"
        "- Student ID is required.\n"
        "Issuance of Good Moral Certificate (Undergraduate)\n"
        "Requirements:\n"
        "- Certificate of Registration is required.\n"
        "- Student ID is required.\n"
        "Issuance of Good Moral Certificate (Transferee)\n"
        "Requirements:\n"
        "- Certificate of Transfer is required.\n"
        "- Student ID is required."
    )
    claims = extract_claims(answer)
    texts = [c.text for c in claims]
    assert any(
        re.search(r"alumni", t, re.I) and "Transcript of Records" in t for t in texts
    )
    assert any(
        re.search(r"undergraduate", t, re.I) and "Certificate of Registration" in t
        for t in texts
    )
    assert any(
        re.search(r"transferee", t, re.I) and "Certificate of Transfer" in t for t in texts
    )
    alumni_sid = [
        t
        for t in texts
        if re.search(r"alumni", t, re.I) and "Student ID" in t
    ]
    undergrad_sid = [
        t
        for t in texts
        if re.search(r"undergraduate", t, re.I) and "Student ID" in t
    ]
    transfer_sid = [
        t
        for t in texts
        if re.search(r"transferee", t, re.I) and "Student ID" in t
    ]
    assert alumni_sid and undergrad_sid and transfer_sid
    assert not any(
        re.search(r"alumni", t, re.I) and "Certificate of Registration" in t for t in texts
    )
    assert not any(
        re.search(r"undergraduate", t, re.I) and "Transcript of Records" in t for t in texts
    )
    assert not any(re.search(r"requirements\s*:", t, re.I) for t in texts)


def test_extract_claims_nested_procedure_requirements_and_procedure_scaffolds():
    answer = (
        "Course Substitution\n"
        "Requirements:\n"
        "- Application letter is required.\n"
        "Procedure:\n"
        "- Submit it to the Dean.\n"
        "Shifting\n"
        "Requirements:\n"
        "- Shifting form is required.\n"
        "Procedure:\n"
        "- Submit the form."
    )
    claims = extract_claims(answer)
    texts = [c.text for c in claims]
    sub = [t for t in texts if re.search(r"substitution", t, re.I)]
    shift = [
        t
        for t in texts
        if re.search(r"shifting", t, re.I) and not re.search(r"substitution", t, re.I)
    ]
    assert any("application letter" in t.lower() for t in sub)
    assert any("dean" in t.lower() for t in sub)
    assert any("shifting form" in t.lower() for t in shift)
    assert any(
        re.search(r"shifting\s*:", t, re.I) and "submit the form" in t.lower() for t in shift
    )
    assert not any("shifting form" in t.lower() for t in sub)
    assert not any("application letter" in t.lower() for t in shift)
    assert not any(re.search(r"requirements\s*:", t, re.I) for t in texts)
    assert not any(re.search(r"procedure\s*:", t, re.I) for t in texts)


def test_extract_claims_semantic_reset_wins_over_preserved_subsection():
    answer = (
        "Alumni\n"
        "Requirements:\n"
        "- TOR is required.\n"
        "Transferee\n"
        "Requirements:\n"
        "- Certificate of Transfer is required."
    )
    claims = extract_claims(answer)
    texts = [c.text for c in claims]
    assert any(re.search(r"alumni", t, re.I) and "TOR is required" in t for t in texts)
    assert any(
        re.search(r"transferee", t, re.I) and "Certificate of Transfer" in t for t in texts
    )
    assert not any(
        re.search(r"alumni", t, re.I) and "Certificate of Transfer" in t for t in texts
    )


def test_extract_claims_bullet_and_numbered_list_markers_preserved():
    answer = (
        "- Tuition is free.\n"
        "* Processing takes 3 days.\n"
        "1. Students must register."
    )
    claims = extract_claims(answer)
    texts = [c.text for c in claims]
    assert any(t.startswith("- ") and "Tuition is free" in t for t in texts)
    assert any(t.startswith("* ") and "Processing takes 3 days" in t for t in texts)
    assert any(re.match(r"1\.\s+Students must register", t) for t in texts)
    # Single-star bullets must not be confused with bold Markdown.
    assert all("**" not in t for t in texts)


def test_extract_claims_ordinary_short_facts_remain_claims():
    for sentence in (
        "Tuition is free.",
        "Processing takes 3 days.",
        "Students must register.",
        "TOR is required.",
        "Maximum load is 24 units.",
    ):
        claims = extract_claims(sentence)
        assert len(claims) == 1, sentence
        assert sentence.rstrip(".").casefold() in claims[0].text.casefold()


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
    # The verifier is only ever shown the alias "S1", never the real
    # "coe-27" id -- see _build_citation_aliases.
    mock_client = _mock_verifier_returning({"claims": [{"claim_id": "c1", "supporting_citation_ids": ["S1"]}]})
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        outcome = verify_citations(answer="Fee: None.", candidates=candidates, mode="llm")
    assert outcome.verifier_succeeded is True
    assert outcome.verified_citation_ids == ["coe-27"]  # alias mapped back to the real id


def test_one_claim_multiple_valid_sources():
    candidates = [_ev("a", "T1", "..."), _ev("b", "T2", "...")]
    mock_client = _mock_verifier_returning(
        {"claims": [{"claim_id": "c1", "supporting_citation_ids": ["S1", "S2"]}]}
    )
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        outcome = verify_citations(answer="Fee: None.", candidates=candidates, mode="llm")
    assert set(outcome.verified_citation_ids) == {"a", "b"}


def test_multiple_claims_one_shared_source_deduplicated():
    candidates = [_ev("a", "T1", "...")]
    mock_client = _mock_verifier_returning(
        {
            "claims": [
                {"claim_id": "c1", "supporting_citation_ids": ["S1"]},
                {"claim_id": "c2", "supporting_citation_ids": ["S1"]},
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
                {"claim_id": "c1", "supporting_citation_ids": ["S1"]},
                {"claim_id": "c2", "supporting_citation_ids": ["S2"]},
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
        {"claims": [{"claim_id": "c1", "supporting_citation_ids": ["S1"]}]}
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
        {"claims": [{"claim_id": "c1", "supporting_citation_ids": ["S1"]}]}  # alias for refund-52
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
        {"claims": [{"claim_id": "c1", "supporting_citation_ids": ["S1"]}]}  # alias for tor-1
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
        {"claims": [{"claim_id": "c1", "supporting_citation_ids": ["S1"]}]}  # alias for budget-29
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
        {"claims": [{"claim_id": "c1", "supporting_citation_ids": ["S1"]}]}  # alias for gm-16
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
        {"claims": [{"claim_id": "c1", "supporting_citation_ids": ["S1", "S1"]}]}
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
                {"claim_id": "c1", "supporting_citation_ids": ["S1"]},
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
                {"claim_id": "c1", "supporting_citation_ids": ["S1"]},  # valid
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
        {"claims": [{"claim_id": "c1", "supporting_citation_ids": ["S1"]}]}
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
    mock_client = _mock_verifier_returning({"claims": [{"claim_id": "c1", "supporting_citation_ids": ["S1"]}]})
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


# --- citation aliases & dynamic per-call schema --------------------------------


def test_citation_aliases_assigned_deterministically_in_candidate_order():
    from app.services.qa.citation_verification import _build_citation_aliases

    candidates = [_ev("a", "T1", "..."), _ev("b", "T2", "..."), _ev("c", "T3", "...")]
    assert _build_citation_aliases(candidates) == ["S1", "S2", "S3"]


_REALISTIC_PRODUCTION_IDS = [
    "30875c07-409e-45ea-989e-3315a85608c1::58",
    "4a7b432a-03a1-4f58-beac-1da63681e734::0",
    "faq:bf4a12ed-78c9-4f8e-8264-03ffe577f888::1",
    "4a7b432a-03a1-4f58-beac-1da63681e734::1",
    "30875c07-409e-45ea-989e-3315a85608c1::460",
    "faq:ee4bc400-83da-4763-ba6d-55d430f22be5::0",
    "30875c07-409e-45ea-989e-3315a85608c1::447",
    "faq:de410e4a-750f-4e4c-963f-767156880442::0",
    "4a7b432a-03a1-4f58-beac-1da63681e734::92",
    "4a7b432a-03a1-4f58-beac-1da63681e734::2",
    "30875c07-409e-45ea-989e-3315a85608c1::401",
    "4a7b432a-03a1-4f58-beac-1da63681e734::40",
    "30875c07-409e-45ea-989e-3315a85608c1::386",
    "30875c07-409e-45ea-989e-3315a85608c1::462",
    "30875c07-409e-45ea-989e-3315a85608c1::468",
]  # the exact 15 v1_citation_ids observed in the real production failure


def test_realistic_15_candidate_uuid_and_faq_ids_verify_and_map_back_correctly():
    """Mirrors the real production failure's shape exactly: 15 authorized
    candidates using long UUID::index and faq:UUID::index citation_ids. The
    verifier is only ever shown short S1..S15 aliases; a response using an
    alias must still resolve to the correct real citation_id."""
    candidates = [_ev(cid, f"Title {i}", "...") for i, cid in enumerate(_REALISTIC_PRODUCTION_IDS)]
    mock_client = _mock_verifier_returning(
        {"claims": [{"claim_id": "c1", "supporting_citation_ids": ["S1"]}]}
    )
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        outcome = verify_citations(answer="Fee: None.", candidates=candidates, mode="llm")
    assert outcome.verifier_succeeded is True
    assert outcome.verified_citation_ids == [_REALISTIC_PRODUCTION_IDS[0]]


def test_multiple_valid_aliases_map_to_correct_distinct_real_ids():
    real_ids = _REALISTIC_PRODUCTION_IDS[:2]
    candidates = [_ev(real_ids[0], "T1", "..."), _ev(real_ids[1], "T2", "...")]
    mock_client = _mock_verifier_returning(
        {
            "claims": [
                {"claim_id": "c1", "supporting_citation_ids": ["S1"]},
                {"claim_id": "c2", "supporting_citation_ids": ["S2"]},
            ]
        }
    )
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        outcome = verify_citations(answer="Fee: None. Office: HRMU.", candidates=candidates, mode="llm")
    assert outcome.per_claim_verified_ids == {"c1": [real_ids[0]], "c2": [real_ids[1]]}
    assert set(outcome.verified_citation_ids) == set(real_ids)


def test_unknown_citation_alias_fails_closed():
    candidates = [_ev("a", "T1", "...")]
    mock_client = _mock_verifier_returning(
        {"claims": [{"claim_id": "c1", "supporting_citation_ids": ["S99"]}]}
    )
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        outcome = verify_citations(answer="Fee: None.", candidates=candidates, mode="llm")
    assert outcome.verifier_succeeded is False
    assert "hallucinated_citation_id" in outcome.failure_reason
    assert outcome.verified_citation_ids == []


def test_real_citation_id_reproduced_verbatim_is_no_longer_accepted():
    """Confirms the model can no longer succeed by reproducing the real,
    long citation_id verbatim -- only its short alias is now a valid value.
    This is the exact structural gap the fix closes."""
    candidates = [_ev(_REALISTIC_PRODUCTION_IDS[0], "T1", "...")]
    mock_client = _mock_verifier_returning(
        {"claims": [{"claim_id": "c1", "supporting_citation_ids": [_REALISTIC_PRODUCTION_IDS[0]]}]}
    )
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        outcome = verify_citations(answer="Fee: None.", candidates=candidates, mode="llm")
    assert outcome.verifier_succeeded is False
    assert "hallucinated_citation_id" in outcome.failure_reason
    assert outcome.verified_citation_ids == []


def test_mapped_real_id_is_independently_checked_against_original_allowlist():
    """Defense in depth: _parse_and_validate re-checks the mapped real id
    against the original allowlist and must not trust the alias map alone,
    even though alias_to_real is always built from the same candidates as
    allowlist during normal operation."""
    from app.services.qa.citation_verification import _parse_and_validate

    raw_text = json.dumps({"claims": [{"claim_id": "c1", "supporting_citation_ids": ["S1"]}]})
    alias_to_real = {"S1": "not-actually-allowlisted"}
    with pytest.raises(CitationVerificationError, match="hallucinated_citation_id"):
        _parse_and_validate(raw_text, {"c1"}, alias_to_real, {"something-else"})


def test_dynamic_schema_claim_id_enum_contains_only_current_claim_ids():
    candidates = [_ev("a", "T1", "...")]
    mock_client = _mock_verifier_returning(
        {"claims": [{"claim_id": "c1", "supporting_citation_ids": ["S1"]}]}
    )
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        verify_citations(answer="Fee: None.", candidates=candidates, mode="llm")
    _, kwargs = mock_client.post.call_args
    schema = kwargs["json"]["response_format"]["json_schema"]["schema"]
    claim_id_schema = schema["properties"]["claims"]["items"]["properties"]["claim_id"]
    assert claim_id_schema["enum"] == ["c1"]


def test_dynamic_schema_citation_enum_contains_only_current_aliases():
    candidates = [_ev("a", "T1", "..."), _ev("b", "T2", "...")]
    mock_client = _mock_verifier_returning(
        {"claims": [{"claim_id": "c1", "supporting_citation_ids": ["S1"]}]}
    )
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        verify_citations(answer="Fee: None.", candidates=candidates, mode="llm")
    _, kwargs = mock_client.post.call_args
    schema = kwargs["json"]["response_format"]["json_schema"]["schema"]
    citation_schema = schema["properties"]["claims"]["items"]["properties"]["supporting_citation_ids"]
    assert citation_schema["items"]["enum"] == ["S1", "S2"]


def test_dynamic_schema_enums_never_leak_real_citation_ids():
    """The enum the provider is shown must contain only short aliases --
    never the real, long citation_id values -- so the request payload
    itself never asks the model to reproduce them."""
    candidates = [_ev(cid, f"Title {i}", "...") for i, cid in enumerate(_REALISTIC_PRODUCTION_IDS[:3])]
    mock_client = _mock_verifier_returning(
        {"claims": [{"claim_id": "c1", "supporting_citation_ids": ["S1"]}]}
    )
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        verify_citations(answer="Fee: None.", candidates=candidates, mode="llm")
    _, kwargs = mock_client.post.call_args
    schema = kwargs["json"]["response_format"]["json_schema"]["schema"]
    citation_enum = schema["properties"]["claims"]["items"]["properties"]["supporting_citation_ids"]["items"]["enum"]
    assert citation_enum == ["S1", "S2", "S3"]
    for real_id in _REALISTIC_PRODUCTION_IDS[:3]:
        assert real_id not in citation_enum


# --- JSON extraction & content-shape guard --------------------------------------


def test_extract_bare_json():
    from app.services.qa.citation_verification import _extract_first_json_object

    assert _extract_first_json_object('{"a": 1}') == '{"a": 1}'


def test_extract_json_fenced_with_language_tag():
    from app.services.qa.citation_verification import _extract_first_json_object

    text = '```json\n{"a": 1}\n```'
    assert _extract_first_json_object(text) == '{"a": 1}'


def test_extract_json_fenced_generic():
    from app.services.qa.citation_verification import _extract_first_json_object

    text = '```\n{"a": 1}\n```'
    assert _extract_first_json_object(text) == '{"a": 1}'


def test_extract_json_with_leading_prose():
    from app.services.qa.citation_verification import _extract_first_json_object

    text = 'Here is the result: {"a": 1}'
    assert _extract_first_json_object(text) == '{"a": 1}'


def test_extract_json_with_ordinary_trailing_prose():
    from app.services.qa.citation_verification import _extract_first_json_object

    text = '{"a": 1} Hope this helps!'
    assert _extract_first_json_object(text) == '{"a": 1}'


def test_extract_json_with_trailing_prose_containing_a_brace():
    """The exact regression this fix exists for: the old greedy
    \\{.*\\} regex would have spanned all the way to this trailing '}',
    corrupting an otherwise-perfectly-valid object into invalid JSON."""
    from app.services.qa.citation_verification import _extract_first_json_object

    text = '{"a": 1} Note: don\'t forget the closing brace }, thanks!'
    assert _extract_first_json_object(text) == '{"a": 1}'


def test_extract_only_first_of_two_json_objects():
    """Two JSON objects in one response -- must extract ONLY the first
    complete object, never merge them."""
    from app.services.qa.citation_verification import _extract_first_json_object

    text = '{"a": 1}{"b": 2}'
    assert _extract_first_json_object(text) == '{"a": 1}'


def test_extract_nested_object():
    from app.services.qa.citation_verification import _extract_first_json_object

    text = '{"a": {"b": 1}}'
    assert _extract_first_json_object(text) == text


def test_extract_arrays_inside_object():
    from app.services.qa.citation_verification import _extract_first_json_object

    text = '{"a": [1, 2, {"b": 3}]}'
    assert _extract_first_json_object(text) == text


def test_extract_braces_inside_quoted_string_do_not_confuse_depth():
    from app.services.qa.citation_verification import _extract_first_json_object

    text = '{"a": "text with { and } inside"} trailing prose with a } too'
    assert _extract_first_json_object(text) == '{"a": "text with { and } inside"}'


def test_extract_escaped_quotes_inside_string():
    from app.services.qa.citation_verification import _extract_first_json_object

    payload = {"a": 'she said "hi"'}
    text = json.dumps(payload) + " trailing prose"
    assert _extract_first_json_object(text) == json.dumps(payload)


def test_extract_escaped_backslashes():
    from app.services.qa.citation_verification import _extract_first_json_object

    payload = {"a": "path\\to\\file"}
    text = json.dumps(payload) + " trailing prose"
    assert _extract_first_json_object(text) == json.dumps(payload)


def test_extract_truncated_json_no_matching_close_returns_none():
    from app.services.qa.citation_verification import _extract_first_json_object

    assert _extract_first_json_object('{"a": 1, "b": 2') is None


def test_extract_unterminated_string_returns_none():
    from app.services.qa.citation_verification import _extract_first_json_object

    assert _extract_first_json_object('{"a": "unterminated') is None


def test_extract_plain_non_json_text_returns_none():
    from app.services.qa.citation_verification import _extract_first_json_object

    assert _extract_first_json_object("this is not json at all") is None


def test_extract_empty_string_returns_none():
    from app.services.qa.citation_verification import _extract_first_json_object

    assert _extract_first_json_object("") is None


def test_fenced_valid_json_still_verifies_end_to_end():
    """The extraction fix must not just reject bad input -- it must still
    let recoverable, fenced/noisy-but-valid output succeed end-to-end."""
    candidates = [_ev("a", "T1", "...")]
    fenced = '```json\n' + json.dumps({"claims": [{"claim_id": "c1", "supporting_citation_ids": ["S1"]}]}) + '\n```'
    mock_client = _mock_verifier_returning_raw(fenced)
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        outcome = verify_citations(answer="Fee: None.", candidates=candidates, mode="llm")
    assert outcome.verifier_succeeded is True
    assert outcome.verified_citation_ids == ["a"]


def test_trailing_prose_with_brace_still_verifies_end_to_end():
    candidates = [_ev("a", "T1", "...")]
    noisy = (
        json.dumps({"claims": [{"claim_id": "c1", "supporting_citation_ids": ["S1"]}]})
        + " Note: don't forget the closing brace }, thanks!"
    )
    mock_client = _mock_verifier_returning_raw(noisy)
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        outcome = verify_citations(answer="Fee: None.", candidates=candidates, mode="llm")
    assert outcome.verifier_succeeded is True
    assert outcome.verified_citation_ids == ["a"]


def test_two_json_objects_end_to_end_uses_only_the_first():
    candidates = [_ev("a", "T1", "..."), _ev("b", "T2", "...")]
    first = {"claims": [{"claim_id": "c1", "supporting_citation_ids": ["S1"]}]}
    second = {"claims": [{"claim_id": "c1", "supporting_citation_ids": ["S2"]}]}
    mock_client = _mock_verifier_returning_raw(json.dumps(first) + json.dumps(second))
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        outcome = verify_citations(answer="Fee: None.", candidates=candidates, mode="llm")
    assert outcome.verifier_succeeded is True
    assert outcome.verified_citation_ids == ["a"]  # only the first object's alias, never merged


def test_content_none_fails_closed_as_response_shape_error():
    candidates = [_ev("a", "T1", "...")]
    mock_client = _mock_verifier_returning_raw(None)
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        outcome = verify_citations(answer="Fee: None.", candidates=candidates, mode="llm")
    assert outcome.verifier_succeeded is False
    assert "unexpected_response_shape" in outcome.failure_reason
    assert outcome.verified_citation_ids == []


def test_content_list_fails_closed_as_response_shape_error_not_attribute_error():
    """Confirms the content-shape guard catches this cleanly -- an
    AttributeError from .strip() on a list must never escape as a raw,
    uncategorized unexpected_error."""
    candidates = [_ev("a", "T1", "...")]
    mock_client = _mock_verifier_returning_raw([{"type": "text", "text": "{}"}])
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        outcome = verify_citations(answer="Fee: None.", candidates=candidates, mode="llm")
    assert outcome.verifier_succeeded is False
    assert "unexpected_response_shape" in outcome.failure_reason
    assert "unexpected_error" not in outcome.failure_reason
    assert outcome.verified_citation_ids == []


# --- privacy-safe provider-failure diagnostics -----------------------------------


@pytest.mark.parametrize("status_code", [400, 401, 402, 403, 429, 500])
def test_http_status_error_captures_exact_status_and_kind(status_code):
    candidates = [_ev("a", "T1", "...")]
    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "error", request=MagicMock(), response=MagicMock(status_code=status_code)
    )
    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False
    mock_client.post.return_value = mock_response
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        outcome = verify_citations(answer="Fee: None.", candidates=candidates, mode="llm")
    assert outcome.verifier_succeeded is False
    assert outcome.provider_diagnostics == {
        "provider_error_kind": "http_status",
        "http_status": status_code,
        "provider_error_code": None,
        "provider_error_type": None,
    }


def test_timeout_captures_kind_timeout_with_null_status():
    candidates = [_ev("a", "T1", "...")]
    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False
    mock_client.post.side_effect = httpx.TimeoutException("timed out")
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        outcome = verify_citations(answer="Fee: None.", candidates=candidates, mode="llm")
    assert outcome.verifier_succeeded is False
    assert outcome.provider_diagnostics == {
        "provider_error_kind": "timeout",
        "http_status": None,
        "provider_error_code": None,
        "provider_error_type": None,
    }


def test_transport_network_failure_captures_kind_transport_with_null_status():
    """A network/connection-level failure (never got an HTTP response at
    all) is distinct from both a timeout and an HTTP status error."""
    candidates = [_ev("a", "T1", "...")]
    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False
    mock_client.post.side_effect = httpx.ConnectError("connection refused")
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        outcome = verify_citations(answer="Fee: None.", candidates=candidates, mode="llm")
    assert outcome.verifier_succeeded is False
    assert outcome.provider_diagnostics == {
        "provider_error_kind": "transport",
        "http_status": None,
        "provider_error_code": None,
        "provider_error_type": None,
    }


def test_provider_not_configured_captures_kind_not_configured_with_null_status():
    candidates = [_ev("a", "T1", "...")]
    with (
        patch(f"{MODULE}.settings.groq_api_key", None),
        patch("httpx.Client") as mock_httpx,
    ):
        outcome = verify_citations(answer="Fee: None.", candidates=candidates, mode="llm")
    mock_httpx.assert_not_called()
    assert outcome.verifier_succeeded is False
    assert outcome.provider_diagnostics == {
        "provider_error_kind": "not_configured",
        "http_status": None,
        "provider_error_code": None,
        "provider_error_type": None,
    }


def test_malformed_json_leaves_provider_diagnostics_none():
    """provider_diagnostics is specific to provider/transport failures --
    malformed_json (a content-level failure, after a successful HTTP
    response) must leave it None; failure_diagnostics is what applies there."""
    candidates = [_ev("a", "T1", "...")]
    mock_client = _mock_verifier_returning_raw("")
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        outcome = verify_citations(answer="Fee: None.", candidates=candidates, mode="llm")
    assert outcome.verifier_succeeded is False
    assert outcome.provider_diagnostics is None
    assert outcome.failure_diagnostics is not None  # unchanged from the prior fix


def test_successful_verification_leaves_provider_diagnostics_none():
    candidates = [_ev("a", "T1", "...")]
    mock_client = _mock_verifier_returning(
        {"claims": [{"claim_id": "c1", "supporting_citation_ids": ["S1"]}]}
    )
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        outcome = verify_citations(answer="Fee: None.", candidates=candidates, mode="llm")
    assert outcome.verifier_succeeded is True
    assert outcome.provider_diagnostics is None


def test_provider_diagnostics_never_contain_raw_response_or_exception_text():
    """A distinctive marker embedded in the mocked error message/response
    must never appear anywhere in the serialized provider_diagnostics."""
    candidates = [_ev("a", "T1", "...")]
    secret_marker = "SECRET_PROVIDER_ERROR_BODY_MUST_NEVER_LEAK_54321"
    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        f"server error: {secret_marker}", request=MagicMock(), response=MagicMock(status_code=402)
    )
    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False
    mock_client.post.return_value = mock_response
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        outcome = verify_citations(answer="Fee: None.", candidates=candidates, mode="llm")
    assert outcome.provider_diagnostics == {
        "provider_error_kind": "http_status",
        "http_status": 402,
        "provider_error_code": None,
        "provider_error_type": None,
    }
    serialized = json.dumps(outcome.provider_diagnostics)
    assert secret_marker not in serialized
    assert "server error" not in serialized
    assert secret_marker in outcome.failure_reason  # confirms the marker WAS in the raw
    # reason (proving this test would catch a leak), just never in diagnostics


def test_provider_diagnostics_never_contain_credentials():
    candidates = [_ev("a", "T1", "...")]
    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "unauthorized", request=MagicMock(), response=MagicMock(status_code=401)
    )
    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False
    mock_client.post.return_value = mock_response
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        outcome = verify_citations(answer="Fee: None.", candidates=candidates, mode="llm")
    serialized = json.dumps(outcome.provider_diagnostics)
    assert "test-key" not in serialized  # the _configured_provider() api key
    assert "Bearer" not in serialized
    assert "Authorization" not in serialized


def _http_status_error_with_body(status_code: int, body) -> httpx.HTTPStatusError:
    """An HTTPStatusError whose .response.json() returns the given body,
    for testing _extract_openrouter_error_fields via the real error path."""
    mock_response = MagicMock(status_code=status_code)
    mock_response.json.return_value = body
    return httpx.HTTPStatusError("error", request=MagicMock(), response=mock_response)


def test_documented_error_type_and_provider_code_are_extracted():
    """The two OpenRouter-documented machine-readable fields
    (error.metadata.error_type / error.metadata.provider_code) are
    extracted when present, exactly as documented."""
    candidates = [_ev("a", "T1", "...")]
    body = {
        "error": {
            "code": 429,
            "message": "Rate limit exceeded",
            "metadata": {"error_type": "rate_limit_exceeded", "provider_code": "rate_limited"},
        }
    }
    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = _http_status_error_with_body(429, body)
    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False
    mock_client.post.return_value = mock_response
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        outcome = verify_citations(answer="Fee: None.", candidates=candidates, mode="llm")
    assert outcome.provider_diagnostics == {
        "provider_error_kind": "http_status",
        "http_status": 429,
        "provider_error_code": "rate_limited",
        "provider_error_type": "rate_limit_exceeded",
    }


@pytest.mark.parametrize(
    "body",
    [
        {"error": {"code": 403, "message": "Forbidden"}},  # metadata missing entirely
        {"error": {"code": 403, "message": "Forbidden", "metadata": {}}},  # metadata empty
        {"error": {"code": 403, "message": "Forbidden", "metadata": {"error_type": "x"}}},  # provider_code missing
        {"error": {"code": 403, "message": "Forbidden", "metadata": {"provider_code": "y"}}},  # error_type missing
    ],
)
def test_missing_documented_fields_yield_null(body):
    from app.services.qa.citation_verification import _extract_openrouter_error_fields

    mock_response = MagicMock()
    mock_response.json.return_value = body
    error_type, provider_code = _extract_openrouter_error_fields(mock_response)
    if "error_type" not in body["error"].get("metadata", {}):
        assert error_type is None
    if "provider_code" not in body["error"].get("metadata", {}):
        assert provider_code is None


def test_malformed_json_error_body_yields_null_optional_fields():
    from app.services.qa.citation_verification import _extract_openrouter_error_fields

    mock_response = MagicMock()
    mock_response.json.side_effect = ValueError("not valid json")
    assert _extract_openrouter_error_fields(mock_response) == (None, None)


def test_non_json_error_body_yields_null_optional_fields():
    """.json() raising (the real httpx behavior for a non-JSON body) must
    be handled exactly like malformed JSON -- never propagate, never
    fail verification."""
    from app.services.qa.citation_verification import _extract_openrouter_error_fields

    mock_response = MagicMock()
    mock_response.json.side_effect = json.JSONDecodeError("Expecting value", "not json", 0)
    assert _extract_openrouter_error_fields(mock_response) == (None, None)


def test_unexpected_types_in_metadata_yield_null():
    from app.services.qa.citation_verification import _extract_openrouter_error_fields

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "error": {"metadata": {"error_type": 12345, "provider_code": ["not", "a", "string"]}}
    }
    assert _extract_openrouter_error_fields(mock_response) == (None, None)


def test_oversized_field_values_yield_null():
    from app.services.qa.citation_verification import _extract_openrouter_error_fields

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "error": {"metadata": {"error_type": "x" * 500, "provider_code": "ok"}}
    }
    error_type, provider_code = _extract_openrouter_error_fields(mock_response)
    assert error_type is None  # rejected for exceeding the bound
    assert provider_code == "ok"


def test_human_readable_message_never_extracted():
    candidates = [_ev("a", "T1", "...")]
    secret_marker = "THIS_IS_THE_HUMAN_MESSAGE_MUST_NEVER_APPEAR_24680"
    body = {
        "error": {
            "code": 403,
            "message": secret_marker,
            "metadata": {"error_type": "forbidden", "provider_code": "blocked"},
        }
    }
    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = _http_status_error_with_body(403, body)
    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False
    mock_client.post.return_value = mock_response
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        outcome = verify_citations(answer="Fee: None.", candidates=candidates, mode="llm")
    serialized = json.dumps(outcome.provider_diagnostics)
    assert secret_marker not in serialized
    assert outcome.provider_diagnostics["provider_error_code"] == "blocked"
    assert outcome.provider_diagnostics["provider_error_type"] == "forbidden"


def test_arbitrary_metadata_keys_never_extracted():
    """error.metadata may contain arbitrary provider-supplied keys (e.g. a
    guardrail block's own 'patterns' list) -- only the two named,
    documented keys are ever read; everything else must never appear."""
    candidates = [_ev("a", "T1", "...")]
    secret_marker = "ARBITRARY_METADATA_MUST_NEVER_LEAK_112233"
    body = {
        "error": {
            "code": 403,
            "message": "Request blocked",
            "metadata": {
                "error_type": "guardrail_block",
                "provider_code": "blocked",
                "patterns": [secret_marker],
                "reason": secret_marker,
            },
        }
    }
    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = _http_status_error_with_body(403, body)
    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False
    mock_client.post.return_value = mock_response
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        outcome = verify_citations(answer="Fee: None.", candidates=candidates, mode="llm")
    assert outcome.provider_diagnostics == {
        "provider_error_kind": "http_status",
        "http_status": 403,
        "provider_error_code": "blocked",
        "provider_error_type": "guardrail_block",
    }
    serialized = json.dumps(outcome.provider_diagnostics)
    assert secret_marker not in serialized


def test_prompt_and_answer_content_never_appear_in_provider_diagnostics():
    candidates = [_ev("a", "T1", "This is candidate evidence text that must never leak.")]
    secret_answer_marker = "UNIQUE_ANSWER_TEXT_MUST_NEVER_APPEAR_998877"
    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "error", request=MagicMock(), response=MagicMock(status_code=403)
    )
    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False
    mock_client.post.return_value = mock_response
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        outcome = verify_citations(
            answer=f"Fee: None. {secret_answer_marker}", candidates=candidates, mode="llm"
        )
    serialized = json.dumps(outcome.provider_diagnostics)
    assert secret_answer_marker not in serialized
    assert "candidate evidence text" not in serialized


# --- privacy-safe malformed_json diagnostics ------------------------------------


def test_malformed_empty_response_gets_safe_structural_diagnostics():
    candidates = [_ev("a", "T1", "...")]
    mock_client = _mock_verifier_returning_raw("")
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        outcome = verify_citations(answer="Fee: None.", candidates=candidates, mode="llm")
    assert outcome.verifier_succeeded is False
    assert outcome.failure_diagnostics == {
        "content_length_bucket": "empty",
        "complete_top_level_object_found": False,
        "incomplete_top_level_object": False,
        "json_error_category": "expecting_value",
        "json_error_position_bucket": "start",
        "error_near_end": False,
    }


def test_truncated_json_gets_incomplete_top_level_object_true():
    candidates = [_ev("a", "T1", "...")]
    mock_client = _mock_verifier_returning_raw('{"a": 1, "b": 2')
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        outcome = verify_citations(answer="Fee: None.", candidates=candidates, mode="llm")
    assert outcome.verifier_succeeded is False
    diag = outcome.failure_diagnostics
    assert diag["complete_top_level_object_found"] is False
    assert diag["incomplete_top_level_object"] is True
    assert diag["json_error_category"] == "expecting_delimiter"
    assert diag["error_near_end"] is True  # error is at the very end of a cut-off response


def test_unterminated_string_gets_unterminated_string_category():
    candidates = [_ev("a", "T1", "...")]
    mock_client = _mock_verifier_returning_raw('{"a": "unterminated')
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        outcome = verify_citations(answer="Fee: None.", candidates=candidates, mode="llm")
    assert outcome.verifier_succeeded is False
    diag = outcome.failure_diagnostics
    assert diag["json_error_category"] == "unterminated_string"
    assert diag["complete_top_level_object_found"] is False
    # A '{' did begin a candidate object, it just never closed (the value
    # string swallows the rest of the text without ever finding its own
    # closing quote) -- correctly flagged as an incomplete top-level object.
    assert diag["incomplete_top_level_object"] is True


def test_extra_data_case_gets_extra_data_category_when_reachable():
    """Reachable specifically when there is no '{' at all -- extraction
    finds nothing to isolate, so the original text (a complete JSON value
    followed by trailing non-JSON text) reaches json.loads unmodified."""
    candidates = [_ev("a", "T1", "...")]
    mock_client = _mock_verifier_returning_raw('"hello" extra text')
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        outcome = verify_citations(answer="Fee: None.", candidates=candidates, mode="llm")
    assert outcome.verifier_succeeded is False
    diag = outcome.failure_diagnostics
    assert diag["json_error_category"] == "extra_data"
    assert diag["complete_top_level_object_found"] is False
    assert diag["incomplete_top_level_object"] is False  # no '{' at all in this text


def test_valid_json_does_not_report_malformed_diagnostics():
    candidates = [_ev("a", "T1", "...")]
    mock_client = _mock_verifier_returning(
        {"claims": [{"claim_id": "c1", "supporting_citation_ids": ["S1"]}]}
    )
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        outcome = verify_citations(answer="Fee: None.", candidates=candidates, mode="llm")
    assert outcome.verifier_succeeded is True
    assert outcome.failure_diagnostics is None


def test_non_malformed_failure_leaves_diagnostics_none():
    """failure_diagnostics is specific to malformed_json -- every other
    failure category (e.g. a hallucinated alias) must leave it None."""
    candidates = [_ev("a", "T1", "...")]
    mock_client = _mock_verifier_returning(
        {"claims": [{"claim_id": "c1", "supporting_citation_ids": ["S99"]}]}
    )
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        outcome = verify_citations(answer="Fee: None.", candidates=candidates, mode="llm")
    assert outcome.verifier_succeeded is False
    assert "hallucinated_citation_id" in outcome.failure_reason
    assert outcome.failure_diagnostics is None


def test_diagnostics_never_contain_raw_content():
    """A distinctive marker placed right next to the parse failure must
    never appear anywhere in the serialized diagnostics -- proves the
    privacy property empirically, not just by code inspection."""
    candidates = [_ev("a", "T1", "...")]
    secret_marker = "SECRET_SOURCE_EXCERPT_MUST_NEVER_LEAK_12345"
    raw = '{"a": "' + secret_marker + " unterminated"
    mock_client = _mock_verifier_returning_raw(raw)
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        outcome = verify_citations(answer="Fee: None.", candidates=candidates, mode="llm")
    assert outcome.verifier_succeeded is False
    serialized = json.dumps(outcome.failure_diagnostics)
    assert secret_marker not in serialized
    assert secret_marker not in json.dumps(outcome.per_claim_verified_ids)


def test_bucket_content_length_boundaries():
    from app.services.qa.citation_verification import _bucket_content_length

    assert _bucket_content_length(0) == "empty"
    assert _bucket_content_length(1) == "1_100"
    assert _bucket_content_length(100) == "1_100"
    assert _bucket_content_length(101) == "101_500"
    assert _bucket_content_length(500) == "101_500"
    assert _bucket_content_length(501) == "501_1000"
    assert _bucket_content_length(1000) == "501_1000"
    assert _bucket_content_length(1001) == "1001_2000"
    assert _bucket_content_length(2000) == "1001_2000"
    assert _bucket_content_length(2001) == "2001_5000"
    assert _bucket_content_length(5000) == "2001_5000"
    assert _bucket_content_length(5001) == "over_5000"


def test_bucket_error_position_boundaries():
    from app.services.qa.citation_verification import _bucket_error_position

    assert _bucket_error_position(0, 0) == "start"
    assert _bucket_error_position(0, 100) == "start"
    assert _bucket_error_position(30, 100) == "early"
    assert _bucket_error_position(50, 100) == "middle"
    assert _bucket_error_position(80, 100) == "late"
    assert _bucket_error_position(99, 100) == "end"


# --- dedicated citation verifier model ------------------------------------------


def test_verifier_model_unset_falls_back_to_generation_model():
    """settings.citation_verifier_model is None (the _configured_provider
    baseline) -- the HTTP request must use groq_model, exactly as before
    this setting existed."""
    candidates = [_ev("a", "T1", "...")]
    mock_client = _mock_verifier_returning({"claims": [{"claim_id": "c1", "supporting_citation_ids": ["S1"]}]})
    with patch("httpx.Client", return_value=mock_client), _configured_provider():
        verify_citations(answer="Fee: None.", candidates=candidates, mode="llm")
    _, kwargs = mock_client.post.call_args
    assert kwargs["json"]["model"] == "test-model"  # groq_model, unchanged


def test_verifier_model_empty_string_falls_back_to_generation_model():
    """An empty string (e.g. an env var set but blank) must be treated the
    same as unset -- falls back to groq_model, never sent as the model."""
    candidates = [_ev("a", "T1", "...")]
    mock_client = _mock_verifier_returning({"claims": [{"claim_id": "c1", "supporting_citation_ids": ["S1"]}]})
    with patch("httpx.Client", return_value=mock_client), _configured_provider(), \
         patch.object(citation_verification.settings, "citation_verifier_model", ""):
        verify_citations(answer="Fee: None.", candidates=candidates, mode="llm")
    _, kwargs = mock_client.post.call_args
    assert kwargs["json"]["model"] == "test-model"


def test_verifier_model_set_is_used_in_the_http_request():
    candidates = [_ev("a", "T1", "...")]
    mock_client = _mock_verifier_returning({"claims": [{"claim_id": "c1", "supporting_citation_ids": ["S1"]}]})
    with patch("httpx.Client", return_value=mock_client), _configured_provider(), \
         patch.object(citation_verification.settings, "citation_verifier_model", "dedicated-verifier-model"):
        outcome = verify_citations(answer="Fee: None.", candidates=candidates, mode="llm")
    _, kwargs = mock_client.post.call_args
    assert kwargs["json"]["model"] == "dedicated-verifier-model"
    assert outcome.verifier_succeeded is True  # setting it doesn't break anything else


def test_verifier_model_set_leaves_base_url_api_key_timeout_unchanged():
    candidates = [_ev("a", "T1", "...")]
    mock_client = _mock_verifier_returning({"claims": [{"claim_id": "c1", "supporting_citation_ids": ["S1"]}]})
    with patch("httpx.Client", return_value=mock_client) as mock_httpx_client, _configured_provider(), \
         patch.object(citation_verification.settings, "citation_verifier_model", "dedicated-verifier-model"):
        verify_citations(answer="Fee: None.", candidates=candidates, mode="llm")
    args, kwargs = mock_client.post.call_args
    assert args[0] == "https://openrouter.ai/api/v1/chat/completions"  # llm_base_url unchanged
    assert kwargs["headers"]["Authorization"] == "Bearer test-key"  # groq_api_key unchanged
    mock_httpx_client.assert_called_once_with(timeout=5.0)  # groq_timeout_seconds unchanged


def test_verifier_model_set_response_format_and_aliases_still_present():
    """A dedicated verifier model must not disturb any part of the 02d385d/
    ef9fe90 hardening -- structured response_format, S1/S2 aliases, and
    dynamic enums are all still built and sent exactly as before."""
    candidates = [_ev("a", "T1", "..."), _ev("b", "T2", "...")]
    mock_client = _mock_verifier_returning({"claims": [{"claim_id": "c1", "supporting_citation_ids": ["S1"]}]})
    with patch("httpx.Client", return_value=mock_client), _configured_provider(), \
         patch.object(citation_verification.settings, "citation_verifier_model", "dedicated-verifier-model"):
        verify_citations(answer="Fee: None.", candidates=candidates, mode="llm")
    _, kwargs = mock_client.post.call_args
    body = kwargs["json"]
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True
    schema = body["response_format"]["json_schema"]["schema"]
    citation_schema = schema["properties"]["claims"]["items"]["properties"]["supporting_citation_ids"]
    assert citation_schema["items"]["enum"] == ["S1", "S2"]


def test_verifier_model_set_fail_closed_behavior_intact():
    """A dedicated verifier model must not weaken fail-closed validation --
    an unknown alias must still be rejected exactly as before."""
    candidates = [_ev("a", "T1", "...")]
    mock_client = _mock_verifier_returning({"claims": [{"claim_id": "c1", "supporting_citation_ids": ["S99"]}]})
    with patch("httpx.Client", return_value=mock_client), _configured_provider(), \
         patch.object(citation_verification.settings, "citation_verifier_model", "dedicated-verifier-model"):
        outcome = verify_citations(answer="Fee: None.", candidates=candidates, mode="llm")
    assert outcome.verifier_succeeded is False
    assert "hallucinated_citation_id" in outcome.failure_reason
    assert outcome.verified_citation_ids == []


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
        citation_verifier_model=None,  # deterministic baseline: falls back to groq_model
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
