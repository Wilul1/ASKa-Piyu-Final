"""Tests for the Fresh Gold Benchmark Capture infrastructure
(``scripts/citation_grounding_capture.py``): CAPTURE INFRASTRUCTURE ONLY --
no Citation V2 verifier, no citation-selection/retrieval/reranking/
embeddings/prompts/audience-retrieval change, no public API schema change,
no live Groq/Chroma call anywhere in this file (every external dependency
``answer_qa_question``, ``_run_git``, and ``get_knowledge_base_store``
touches is patched).

Covers (per the approved Stage 3/4 spec):
G-M: the pure excerpt-authorization gate (``is_excerpt_authorized`` /
     ``normalize_audience`` / ``normalize_role``) -- independently testable
     with no pipeline dependency at all. Stage 4 correction: role now fails
     closed exactly as hard as audience does (an earlier version coerced an
     unrecognized/None role to "student", which was a real bug).
N-P: conversation-history handling (standalone vs. follow-up, and the
     before-the-pipeline-call rejection of a followup with no history).
Q-S: exactly-one-pipeline-call, no second retrieval, and the three-layer
     candidate/final-generation-context/displayed distinction (Stage 4:
     final_generation_context, from generation_context_sink, is now the
     sole authority for selected_context_citation_ids -- never
     retrieved_chunks' selected_for_context flags).
T-U: reproducibility metadata, including honest representation of fields
     that could not be obtained, and the Stage 4 dirty-tree content hashes.
V:   the serialized capture record never contains unauthorized evidence
     text, checked by scanning the *entire* serialized JSON string, not
     just the ``evidence_text`` block.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

import scripts.citation_grounding_capture as capture_module
from app.services.qa.question_answering import QAResult
from scripts.citation_grounding_capture import (
    CaptureCase,
    build_run_context,
    capture_case,
    is_excerpt_authorized,
    normalize_audience,
    normalize_role,
)


# ---------------------------------------------------------------------------
# G-M: pure excerpt-authorization gate -- exact matrix from the Stage 4
# authoritative security correction.
# ---------------------------------------------------------------------------


def test_student_role_student_audience_allowed():
    """G: student role + student audience => allowed."""
    assert is_excerpt_authorized("student", "student") is True


def test_student_role_both_audience_allowed():
    """G: student role + both audience => allowed."""
    assert is_excerpt_authorized("both", "student") is True


def test_student_role_faculty_audience_denied():
    """G: student role + faculty audience => denied."""
    assert is_excerpt_authorized("faculty", "student") is False


def test_faculty_role_follows_real_production_authorization():
    """H: faculty role's allowed audiences must match production's own
    filter_chunks_for_audience semantics exactly: {faculty, both} allowed,
    student NOT allowed (faculty does not see student-only content any
    more than a student sees faculty-only content, per that function's
    own allowed-set for the faculty branch)."""
    assert is_excerpt_authorized("faculty", "faculty") is True
    assert is_excerpt_authorized("both", "faculty") is True
    assert is_excerpt_authorized("student", "faculty") is False


def test_office_and_admin_follow_real_production_authorization():
    """I: office/admin see everything, per
    filter_chunks_for_audience's ``role in {"office","admin"}: return
    list(chunks)`` branch -- all three known audiences are allowed."""
    for role in ("office", "admin"):
        assert is_excerpt_authorized("student", role) is True
        assert is_excerpt_authorized("both", role) is True
        assert is_excerpt_authorized("faculty", role) is True


def test_none_role_denied_for_every_known_audience():
    """J/K/L: None role => denied for ALL audiences, including "both" --
    the Stage 4 fix. A prior version of this gate coerced None to
    "student", which would have wrongly allowed this."""
    for audience in ("student", "both", "faculty"):
        assert is_excerpt_authorized(audience, None) is False


def test_empty_role_denied_for_every_known_audience():
    """J: an empty-string role => denied for ALL audiences."""
    for audience in ("student", "both", "faculty"):
        assert is_excerpt_authorized(audience, "") is False


def test_unknown_role_denied_for_every_known_audience():
    """J: an unrecognized role string (not one of the four QA-pipeline
    roles) => denied for ALL audiences, including "both"."""
    for audience in ("student", "both", "faculty"):
        assert is_excerpt_authorized(audience, "some-unrecognized-role") is False
        assert is_excerpt_authorized(audience, "superadmin") is False
        assert is_excerpt_authorized(audience, "guest") is False


def test_malformed_role_denied_for_every_known_audience():
    """J: a non-string role value => denied for ALL audiences."""
    for audience in ("student", "both", "faculty"):
        for malformed_role in (123, ["admin"], {"role": "admin"}, 3.14):
            assert is_excerpt_authorized(audience, malformed_role) is False


def test_normalize_role_classifies_known_roles_case_and_whitespace_tolerant():
    assert normalize_role("student") == "student"
    assert normalize_role(" Faculty ") == "faculty"
    assert normalize_role("OFFICE") == "office"
    assert normalize_role("Admin") == "admin"


def test_normalize_role_unknown_for_missing_empty_or_malformed():
    for value in (None, "", "   ", "guest", 123, ["admin"]):
        assert normalize_role(value) == "unknown"


def test_missing_audience_key_rejected_for_every_role_including_admin():
    """K: a chunk whose metadata never had an 'audience' key at all (so
    ``row.get("audience")`` naturally returns ``None``) must never
    authorize persistence -- not even for admin, which is deliberately
    stricter than production's own retrieval-time defaulting."""
    for role in ("student", "faculty", "office", "admin"):
        assert is_excerpt_authorized(None, role) is False
    # And, per the Stage 4 fix, unknown audience is denied even when role
    # is ALSO unknown/None -- both checks fail closed independently.
    assert is_excerpt_authorized(None, None) is False


def test_none_audience_literal_rejected_for_every_role_including_admin():
    """L: an explicit ``audience=None`` (as distinct from a merely-absent
    key, though they resolve the same way) is rejected for every role."""
    for role in ("student", "faculty", "office", "admin"):
        assert is_excerpt_authorized(None, role) is False
    assert normalize_audience(None) == "unknown"


def test_malformed_audience_rejected_for_every_role_including_admin():
    """M: any value outside the exact {'student','faculty','both'}
    vocabulary -- an unrecognized string, or a non-string type entirely --
    is treated as unknown and never authorizes persistence, even for
    admin. This is intentionally stricter than production's
    missing-audience retrieval-time handling."""
    malformed_values = ["everyone", "staff-only", "learner", "", 123, ["faculty"], {"a": 1}, 3.14]
    for value in malformed_values:
        assert normalize_audience(value) == "unknown", value
        for role in ("student", "faculty", "office", "admin"):
            assert is_excerpt_authorized(value, role) is False, (value, role)


def test_valid_audience_values_are_case_and_whitespace_tolerant_not_malformed():
    """Robustness check distinguishing 'malformed' from mere formatting:
    case/whitespace variance on an otherwise-valid value is NOT malformed."""
    assert normalize_audience("  Student  ") == "student"
    assert normalize_audience("BOTH") == "both"
    assert normalize_audience("Faculty") == "faculty"


# ---------------------------------------------------------------------------
# Shared fixture: a fake answer_qa_question with a 3-candidate / 2-selected /
# 1-displayed retrieval shape, so the pool/selected/displayed layers are
# provably distinct, and a faculty-restricted chunk whose preview text
# carries a unique marker, so leakage can be checked precisely.
# ---------------------------------------------------------------------------

_RESTRICTED_MARKER = "RESTRICTED_MARKER_9f3e1a_do_not_leak"

_FAKE_RETRIEVED_CHUNKS = [
    {
        "rank": 1,
        "title": "Faculty Load Policy",
        "path": "Faculty Manual > Workload",
        "page": 12,
        "content_preview": f"{_RESTRICTED_MARKER}: faculty-only workload text.",
        "original_score": 0.9,
        "reranked_score": 0.91,
        "boost_reasons": [],
        # Deliberately True here even though this chunk is NOT in the fake
        # generation_context_sink's final_context_chunks below -- this is
        # the Stage 4 fixture's whole point: selected_for_context (an
        # EARLIER, pre-mutation selection-stage flag) must never be read as
        # authoritative for what generation actually received.
        "selected_for_context": True,
        "context_filter_reasons": [],
        "document_id": "faculty-doc",
        "source_filename": "faculty.pdf",
        "chunk_index": 1,
        "citation_id": "faculty-doc::1",
        "citation_id_stamped": True,
        "audience": "faculty",
    },
    {
        "rank": 2,
        "title": "Student Notice",
        "path": "Handbook > General",
        "page": 3,
        "content_preview": "Student-visible notice text about deadlines.",
        "original_score": 0.7,
        "reranked_score": 0.72,
        "boost_reasons": [],
        "selected_for_context": True,
        "context_filter_reasons": [],
        "document_id": "student-doc",
        "source_filename": "handbook.pdf",
        "chunk_index": 2,
        "citation_id": "student-doc::2",
        "citation_id_stamped": True,
        "audience": "student",
    },
    {
        "rank": 3,
        "title": "Unselected Extra",
        "path": "Handbook > Other",
        "page": 9,
        "content_preview": "Unselected extra context, not sent to generation.",
        "original_score": 0.4,
        "reranked_score": 0.41,
        "boost_reasons": [],
        # Deliberately False here even though this chunk IS in the fake
        # generation_context_sink's final_context_chunks below -- e.g.
        # _restore_missing_facet_context added it back after this earlier
        # flag was already set. Same point as faculty-doc::1 above, in the
        # opposite direction.
        "selected_for_context": False,
        "context_filter_reasons": ["below_context_floor"],
        "document_id": "extra-doc",
        "source_filename": "handbook.pdf",
        "chunk_index": 3,
        "citation_id": "extra-doc::3",
        "citation_id_stamped": True,
        "audience": "both",
    },
]

# The AUTHORITATIVE final generation context (layer B), as answer_qa_question
# itself would populate generation_context_sink["final_context_chunks"]
# AFTER _restore_missing_facet_context and _prefer_active_topic_context have
# both already run. Deliberately DIFFERENT from the selected_for_context=True
# subset of _FAKE_RETRIEVED_CHUNKS above (drops faculty-doc::1, adds
# extra-doc::3) -- this is what proves capture_case's
# selected_context_citation_ids is sourced from this sink, never from layer
# A's earlier, pre-mutation flags.
_FAKE_FINAL_GENERATION_CONTEXT = [
    {
        "citation_id": "student-doc::2",
        "chunk_merge_key": "id:student-doc::2",
        "document_id": "student-doc",
        "chunk_index": 2,
        "title": "Student Notice",
        "path": "Handbook > General",
        "audience": "student",
    },
    {
        "citation_id": "extra-doc::3",
        "chunk_merge_key": "id:extra-doc::3",
        "document_id": "extra-doc",
        "chunk_index": 3,
        "title": "Unselected Extra",
        "path": "Handbook > Other",
        "audience": "both",
    },
]

_FAKE_SOURCES = [{"citation_id": "student-doc::2", "title": "Student Notice"}]


def _fake_qa_result() -> QAResult:
    return QAResult(
        answer="Here is the notice.",
        sources=list(_FAKE_SOURCES),
        confidence="high",
        retrieved_chunks=[dict(row) for row in _FAKE_RETRIEVED_CHUNKS],
        normalized_query="notice",
        expanded_query="notice",
        broad_query=False,
        detected_intent="NORMAL_QA",
        fallback_used=False,
        fallback_reason=None,
    )


def _fake_answer_qa_question_factory(recorder: list[dict]):
    """Builds a side_effect that also populates the four sinks the way the
    real ``answer_qa_question`` would, and records every call's kwargs so
    tests can assert exactly what was threaded through (history, role,
    active_service)."""

    def _fake(
        question,
        *,
        user_role=None,
        history=None,
        client_active_service=None,
        citation_debug_sink=None,
        generation_usage_sink=None,
        answer_rewrite_sink=None,
        generation_context_sink=None,
    ):
        recorder.append(
            {
                "question": question,
                "user_role": user_role,
                "history": history,
                "client_active_service": client_active_service,
            }
        )
        if citation_debug_sink is not None:
            citation_debug_sink.append(
                {
                    "claim_text": "Here is the notice.",
                    "chunk_id": "id:student-doc::2",
                    "citation_id": "student-doc::2",
                    "shared_words": ["notice"],
                    "shared_numbers": [],
                    "score": 1.0,
                    "min_signals_met": True,
                    "abs_floor_met": True,
                }
            )
        if generation_usage_sink is not None:
            generation_usage_sink.update({"prompt_tokens": 10, "completion_tokens": 5})
        if answer_rewrite_sink is not None:
            answer_rewrite_sink.update(
                {
                    "evidence_bearing_answer": "Here is the notice.",
                    "table_inversion_corrected": False,
                    "classification_template_applied": False,
                    "used_recovered": False,
                }
            )
        if generation_context_sink is not None:
            generation_context_sink.update(
                {
                    "generation_invoked": True,
                    "generation_succeeded": True,
                    "status": "invoked_and_succeeded:generation_answer_used",
                    "final_context_chunks": [dict(c) for c in _FAKE_FINAL_GENERATION_CONTEXT],
                }
            )
        return _fake_qa_result()

    return _fake


# ---------------------------------------------------------------------------
# N-P: conversation-history handling
# ---------------------------------------------------------------------------


def test_standalone_case_calls_pipeline_with_empty_history():
    """N: a standalone (is_followup=False) case with no history is
    perfectly normal and must reach the pipeline with history=[]."""
    calls: list[dict] = []
    case = CaptureCase(
        case_id="standalone-1",
        category="enrollment",
        question="How do I enroll?",
        user_role="student",
        conversation_history=[],
        is_followup=False,
    )
    with patch.object(
        capture_module,
        "answer_qa_question",
        side_effect=_fake_answer_qa_question_factory(calls),
    ) as mock_qa:
        record = capture_case(case, run_context={"captured_at": "test"})

    assert record["captured"] is True
    assert mock_qa.call_count == 1
    assert calls[0]["history"] == []
    assert record["conversation_history"] == []
    assert record["question"]["is_followup"] is False


def test_followup_case_with_real_history_calls_pipeline_with_that_history():
    """O: a follow-up case with real, explicit history is captured
    normally and that exact history is both threaded through to the
    pipeline and recorded verbatim on the capture record."""
    calls: list[dict] = []
    history = [
        {"role": "user", "content": "How do I enroll?"},
        {"role": "assistant", "content": "Go to the Registrar's Office."},
    ]
    case = CaptureCase(
        case_id="followup-1",
        category="topic_switch_followup",
        question="Which office handles that?",
        user_role="student",
        conversation_history=history,
        is_followup=True,
    )
    with patch.object(
        capture_module,
        "answer_qa_question",
        side_effect=_fake_answer_qa_question_factory(calls),
    ) as mock_qa:
        record = capture_case(case, run_context={"captured_at": "test"})

    assert record["captured"] is True
    assert mock_qa.call_count == 1
    assert calls[0]["history"] == history
    assert record["conversation_history"] == history
    assert record["question"]["is_followup"] is True


def test_followup_case_without_history_is_rejected_before_pipeline_call():
    """P: is_followup=True with empty/absent history must fail BEFORE
    answer_qa_question is ever invoked -- never reconstruct/fabricate
    history to make the call succeed anyway."""
    calls: list[dict] = []
    case = CaptureCase(
        case_id="followup-missing-history",
        category="topic_switch_followup",
        question="Now tell me about TOR.",
        user_role="student",
        conversation_history=[],
        is_followup=True,
    )
    with patch.object(
        capture_module,
        "answer_qa_question",
        side_effect=_fake_answer_qa_question_factory(calls),
    ) as mock_qa:
        record = capture_case(case, run_context={"captured_at": "test"})

    assert record["captured"] is False
    assert "history" in record["capture_error"].lower()
    assert mock_qa.call_count == 0
    assert calls == []


# ---------------------------------------------------------------------------
# Q-S: single pipeline call, no second retrieval, three-layer distinction
# ---------------------------------------------------------------------------


def test_capture_case_calls_pipeline_exactly_once():
    """Q + R: exactly one call to answer_qa_question per case -- this
    script never issues a second retrieval/query of any kind to
    reconstruct or verify the candidate pool. The candidate pool captured
    is entirely whatever that single call's result.retrieved_chunks was."""
    calls: list[dict] = []
    case = CaptureCase(
        case_id="single-call",
        category="enrollment",
        question="How do I enroll?",
        user_role="student",
    )
    with patch.object(
        capture_module,
        "answer_qa_question",
        side_effect=_fake_answer_qa_question_factory(calls),
    ) as mock_qa:
        capture_case(case, run_context={"captured_at": "test"})
        capture_case(case, run_context={"captured_at": "test"})

    # Two capture_case() calls -> two pipeline calls, i.e. exactly one per
    # case, never more than one for a single case's own capture.
    assert mock_qa.call_count == 2


def test_candidate_pool_final_generation_context_and_displayed_remain_structurally_distinct():
    """S: role_filtered_candidate_pool (layer A, every retrieved chunk),
    final_generation_context / selected_context_citation_ids (layer B, the
    AUTHORITATIVE subset sent to generation), and v1_displayed_citations
    (layer C, the subset actually shown) must never be collapsed into one
    another -- proven here with a fixture where all three have different
    membership, not just different sizes."""
    calls: list[dict] = []
    case = CaptureCase(
        case_id="three-layers",
        category="multi_claim",
        question="What is the notice?",
        user_role="admin",  # admin sees everything, isolates this test from the audience gate
    )
    with patch.object(
        capture_module,
        "answer_qa_question",
        side_effect=_fake_answer_qa_question_factory(calls),
    ):
        record = capture_case(case, run_context={"captured_at": "test"})

    pool = record["retrieval"]["role_filtered_candidate_pool"]
    final_context = record["retrieval"]["final_generation_context"]
    selected_ids = record["retrieval"]["selected_context_citation_ids"]
    displayed = record["v1_displayed_citations"]

    assert len(pool) == 3
    assert {c["citation_id"] for c in pool} == {"faculty-doc::1", "student-doc::2", "extra-doc::3"}
    assert final_context == _FAKE_FINAL_GENERATION_CONTEXT
    assert selected_ids == ["student-doc::2", "extra-doc::3"]
    assert displayed == [{"citation_id": "student-doc::2", "title": "Student Notice"}]
    # selected_context_citation_ids is a list of plain id strings, never
    # the richer candidate/displayed dict shapes -- confirms it is its own
    # layer, not an alias of either of the other two.
    assert all(isinstance(item, str) for item in selected_ids)
    assert record["retrieval"]["generation_invoked"] is True
    assert record["retrieval"]["generation_succeeded"] is True


def test_selected_context_citation_ids_sourced_from_generation_context_sink_not_selected_for_context_flags():
    """J (Stage 4 item 2/9): selected_context_citation_ids must be derived
    ONLY from generation_context_sink's final_context_chunks -- never from
    retrieved_chunks' selected_for_context flags, which reflect an earlier,
    pre-mutation selection stage. The fixture deliberately makes these two
    sources disagree in BOTH directions (faculty-doc::1 is
    selected_for_context=True in layer A but absent from layer B;
    extra-doc::3 is selected_for_context=False in layer A but present in
    layer B) so this test would fail if the wrong source were used either
    way."""
    calls: list[dict] = []
    case = CaptureCase(
        case_id="sourced-from-sink",
        category="multi_claim",
        question="What is the notice?",
        user_role="admin",
    )
    with patch.object(
        capture_module,
        "answer_qa_question",
        side_effect=_fake_answer_qa_question_factory(calls),
    ):
        record = capture_case(case, run_context={"captured_at": "test"})

    selected_ids = set(record["retrieval"]["selected_context_citation_ids"])
    selected_for_context_true_in_pool = {
        c["citation_id"]
        for c in record["retrieval"]["role_filtered_candidate_pool"]
        if c.get("selected_for_context")
    }

    # The authoritative result must match layer B exactly...
    assert selected_ids == {"student-doc::2", "extra-doc::3"}
    # ...and must NOT match the (stale, pre-mutation) selected_for_context
    # flags from layer A, which disagree with layer B on both chunks.
    assert selected_ids != selected_for_context_true_in_pool
    assert "faculty-doc::1" not in selected_ids  # despite selected_for_context=True in A
    assert "extra-doc::3" in selected_ids  # despite selected_for_context=False in A


# ---------------------------------------------------------------------------
# Identity integrity check (Stage 4 items 4-5): capture-time-only
# qualification, never affects the live QA request, never rewrites an id.
# ---------------------------------------------------------------------------


def _candidate(citation_id, *, stamped, chunk_index=0, title="X", document_id="doc"):
    return {
        "citation_id": citation_id,
        "citation_id_stamped": stamped,
        "title": title,
        "document_id": document_id,
        "chunk_index": chunk_index,
    }


def test_identity_integrity_ok_when_stamped_chunk_index_zero():
    """Stamped chunk_id with chunk_index == 0 is fine -- the danger is the
    FALLBACK formula's chunk_index==0 collision, which only applies when
    the id is NOT stamped."""
    pool = [_candidate("faq:abc::0", stamped=True, chunk_index=0)]
    result = capture_module._identity_integrity_check(pool, [])
    assert result["status"] == "ok"
    assert result["ineligible_for_gold"] is False
    assert result["unstamped_candidates"] == []


def test_identity_integrity_failed_when_unstamped_chunk_index_zero():
    """Unstamped chunk_index == 0 is exactly the collision case: the
    fallback formula's `chunk_index or index` substitutes the loop
    position for a real 0, silently producing the wrong id."""
    pool = [_candidate("doc::0", stamped=False, chunk_index=0)]
    result = capture_module._identity_integrity_check(pool, [])
    assert result["status"] == "failed"
    assert result["ineligible_for_gold"] is True
    assert len(result["unstamped_candidates"]) == 1
    assert result["unstamped_candidates"][0]["citation_id"] == "doc::0"


def test_identity_integrity_failed_for_unstamped_remappable_document():
    """A candidate whose id was never stamped, and whose document_id could
    later be Postgres-remapped, is exactly the divergence risk
    _raw_citation_id's own docstring documents -- must be flagged."""
    pool = [
        _candidate(
            "legacy-doc-uuid::7", stamped=False, chunk_index=7, document_id="legacy-doc-uuid"
        )
    ]
    result = capture_module._identity_integrity_check(pool, [])
    assert result["status"] == "failed"
    assert result["ineligible_for_gold"] is True


def test_identity_integrity_mixed_stamped_and_unstamped_pool():
    """A pool with both stamped and unstamped candidates fails overall,
    but only the unstamped one(s) are named in unstamped_candidates."""
    pool = [
        _candidate("faq:abc::0", stamped=True, chunk_index=0),
        _candidate("legacy::3", stamped=False, chunk_index=3),
    ]
    result = capture_module._identity_integrity_check(pool, [])
    assert result["status"] == "failed"
    assert result["ineligible_for_gold"] is True
    assert [c["citation_id"] for c in result["unstamped_candidates"]] == ["legacy::3"]


def test_identity_integrity_ok_for_fully_stamped_pool():
    pool = [
        _candidate("faq:abc::0", stamped=True, chunk_index=0),
        _candidate("doc::4", stamped=True, chunk_index=4),
    ]
    result = capture_module._identity_integrity_check(pool, [])
    assert result["status"] == "ok"
    assert result["ineligible_for_gold"] is False


def test_identity_integrity_failed_when_displayed_id_not_in_candidate_pool():
    """A displayed citation_id that cannot be found anywhere in the
    captured candidate pool signals identity divergence (e.g. a Postgres
    document remap the pool's un-resolved formula couldn't foresee) --
    flagged, never silently ignored or used to rewrite an id."""
    pool = [_candidate("doc::1", stamped=True, chunk_index=1)]
    displayed = [{"citation_id": "resolved-doc-uuid::1", "title": "X"}]
    result = capture_module._identity_integrity_check(pool, displayed)
    assert result["status"] == "failed"
    assert result["ineligible_for_gold"] is True
    assert result["unreconciled_displayed_citation_ids"] == ["resolved-doc-uuid::1"]


def test_identity_integrity_ok_when_displayed_ids_all_reconcile():
    pool = [_candidate("doc::1", stamped=True, chunk_index=1)]
    displayed = [{"citation_id": "doc::1", "title": "X"}]
    result = capture_module._identity_integrity_check(pool, displayed)
    assert result["status"] == "ok"
    assert result["unreconciled_displayed_citation_ids"] == []


def test_identity_integrity_wired_into_capture_case_record():
    """Integration check: capture_case's returned record actually carries
    identity_integrity, computed from the real candidate pool/displayed
    citations of that capture -- not merely available as a standalone
    function nobody calls."""
    calls: list[dict] = []
    case = CaptureCase(
        case_id="identity-check-wired",
        category="enrollment",
        question="What is the notice?",
        user_role="admin",
    )
    with patch.object(
        capture_module,
        "answer_qa_question",
        side_effect=_fake_answer_qa_question_factory(calls),
    ):
        record = capture_case(case, run_context={"captured_at": "test"})

    # The shared fixture's candidates are all citation_id_stamped=True and
    # its displayed citation reconciles against the candidate pool, so this
    # capture is expected to be identity-clean.
    assert record["identity_integrity"]["status"] == "ok"
    assert record["identity_integrity"]["ineligible_for_gold"] is False


def test_identity_integrity_does_not_fail_the_qa_request_only_flags_capture():
    """Confirms this is capture-time qualification only: even when identity
    integrity fails, capture_case still returns captured: True with the
    full record (still useful diagnostically) -- it never raises, never
    blanks out the answer, never fails the case."""
    calls: list[dict] = []
    case = CaptureCase(
        case_id="unstamped-still-captured",
        category="enrollment",
        question="What is the notice?",
        user_role="admin",
    )

    def _fake(question, **kwargs):
        base = _fake_qa_result()
        mutated = [dict(row) for row in base.retrieved_chunks]
        mutated[0]["citation_id_stamped"] = False
        result = QAResult(
            answer=base.answer,
            sources=base.sources,
            confidence=base.confidence,
            retrieved_chunks=mutated,
        )
        gc_sink = kwargs.get("generation_context_sink")
        if gc_sink is not None:
            gc_sink.update(
                {
                    "generation_invoked": True,
                    "generation_succeeded": True,
                    "status": "invoked_and_succeeded:generation_answer_used",
                    "final_context_chunks": [dict(c) for c in _FAKE_FINAL_GENERATION_CONTEXT],
                }
            )
        return result

    with patch.object(capture_module, "answer_qa_question", side_effect=_fake):
        record = capture_case(case, run_context={"captured_at": "test"})

    assert record["captured"] is True
    assert record["answer"]["final_displayed"] == "Here is the notice."
    assert record["identity_integrity"]["status"] == "failed"
    assert record["identity_integrity"]["ineligible_for_gold"] is True


# ---------------------------------------------------------------------------
# T-U: reproducibility metadata
# ---------------------------------------------------------------------------


class _FakeStoreForRunContext:
    chunk_count = 42


def _fake_run_git_factory(*, status_output: str):
    def fake_run_git(*args):
        if args == ("rev-parse", "HEAD"):
            return "abc123def456", None
        if args == ("status", "--porcelain"):
            return status_output, None
        # Stage 5 fix: `_run_git` runs with cwd=BACKEND_ROOT (already
        # backend/), so the diff pathspec must be "." -- "backend" would
        # look for a nonexistent backend/backend/ and silently match
        # nothing. This fake deliberately only recognizes "." (raising for
        # anything else, including the old "backend" pathspec), so this
        # fixture itself would fail loudly if the bug were reintroduced.
        if args == ("diff", "HEAD", "--", "."):
            return "diff --git a/x b/x\n+changed line\n", None
        raise AssertionError(f"unexpected git args: {args}")

    return fake_run_git


def test_build_run_context_records_dirty_git_state():
    """T: an actually-dirty working tree (non-empty `git status --porcelain`)
    must be recorded as git_dirty: True."""

    with (
        patch.object(
            capture_module,
            "_run_git",
            side_effect=_fake_run_git_factory(status_output=" M some/changed/file.py\n"),
        ),
        patch.object(
            capture_module, "get_knowledge_base_store", return_value=_FakeStoreForRunContext()
        ),
    ):
        context = build_run_context()

    assert context["git_head_sha"] == "abc123def456"
    assert context["git_dirty"] is True
    assert "git_dirty_error" not in context
    assert context["chroma_chunk_count"] == 42
    assert context["tracked_diff_sha256"]
    assert context["stage_files_content_sha256"]


def test_build_run_context_records_clean_git_state():
    with (
        patch.object(
            capture_module, "_run_git", side_effect=_fake_run_git_factory(status_output="")
        ),
        patch.object(
            capture_module, "get_knowledge_base_store", return_value=_FakeStoreForRunContext()
        ),
    ):
        context = build_run_context()

    assert context["git_dirty"] is False


def test_build_run_context_represents_missing_metadata_honestly_not_fabricated():
    """U: when git and Chroma are both unavailable, every affected field is
    explicitly None with a sibling *_error reason -- never a fabricated or
    placeholder-looking value standing in for real identity."""

    def failing_run_git(*args):
        return None, "git command failed to run: FileNotFoundError: no such file: 'git'"

    def failing_store():
        raise RuntimeError("no chroma connection available in this test environment")

    with (
        patch.object(capture_module, "_run_git", side_effect=failing_run_git),
        patch.object(capture_module, "get_knowledge_base_store", side_effect=failing_store),
    ):
        context = build_run_context()

    assert context["git_head_sha"] is None
    assert context["git_head_sha_error"]
    assert context["git_dirty"] is None
    assert context["git_dirty_error"]
    assert context["chroma_chunk_count"] is None
    assert context["chroma_chunk_count_error"]
    assert context["tracked_diff_sha256"] is None
    assert context["tracked_diff_sha256_error"]
    # Never invented: no placeholder string/zero standing in for real identity.
    assert context["git_head_sha"] != "unknown"
    assert context["chroma_chunk_count"] != 0
    assert context["tracked_diff_sha256"] != ""


def test_tracked_diff_hash_calls_git_diff_with_dot_pathspec_not_backend():
    """Stage 5 item 1 regression guard: _run_git must be called with the
    pathspec "." (relative to cwd=BACKEND_ROOT, which is already
    backend/), never "backend" -- the latter silently matched nothing
    (looked for a nonexistent backend/backend/) and hashed the empty diff
    on every run regardless of real tracked changes. This test inspects
    the actual call args _tracked_diff_hash makes, so it would have
    failed against the pre-fix code (which called with "backend")."""
    recorded_calls: list[tuple] = []

    def recording_run_git(*args):
        recorded_calls.append(args)
        return "some diff text", None

    with patch.object(capture_module, "_run_git", side_effect=recording_run_git):
        diff_hash, error = capture_module._tracked_diff_hash()

    assert error is None
    assert recorded_calls == [("diff", "HEAD", "--", ".")]
    assert diff_hash == capture_module.hashlib.sha256(b"some diff text").hexdigest()


def test_tracked_diff_hash_empty_diff_produces_hash_of_empty_string():
    """Sanity check on the hash function itself: an actually-empty diff
    (a genuinely clean tree) legitimately hashes to SHA-256("") -- this is
    the correct, honest value in that case. The bug this fixes was that
    EVERY run hashed to this value, including ones with real tracked
    changes, because the pathspec matched nothing."""
    with patch.object(capture_module, "_run_git", return_value=("", None)):
        diff_hash, error = capture_module._tracked_diff_hash()

    assert error is None
    assert diff_hash == capture_module.hashlib.sha256(b"").hexdigest()


def test_real_tracked_diff_hash_against_actual_working_tree():
    """Stage 5 item 1 + item 5: exercises the REAL, unmocked _run_git /
    _tracked_diff_hash against the actual current working tree (a plain
    git subprocess call and a hash -- no Chroma, no Groq, no file writes,
    nothing mutated). Skips gracefully if git itself is unavailable in
    this environment rather than failing on an environment property this
    suite does not control."""
    diff_text, diff_error = capture_module._run_git("diff", "HEAD", "--", ".")
    if diff_error:
        pytest.skip(f"git unavailable in this environment: {diff_error}")

    empty_hash = capture_module.hashlib.sha256(b"").hexdigest()
    first_hash, first_error = capture_module._tracked_diff_hash()
    second_hash, second_error = capture_module._tracked_diff_hash()

    assert first_error is None
    assert second_error is None
    # Repeated reads of an unchanged tree must produce the same hash.
    assert first_hash == second_hash
    if diff_text:
        # There IS a real tracked diff in this working tree (expected: this
        # whole Stage 1-5 effort is uncommitted) -- its hash must not
        # collapse to the empty-string hash the pre-fix bug always produced.
        assert first_hash != empty_hash
    else:
        # A genuinely clean tree legitimately hashes to the empty-string
        # value -- this is not itself a bug, just an unlikely environment
        # for this particular repo state.
        assert first_hash == empty_hash


# ---------------------------------------------------------------------------
# G (Stage 4 item 6): dirty-tree reproducibility hash
# ---------------------------------------------------------------------------


def test_manifest_hash_same_contents_same_hash():
    contents = {"scripts/a.py": b"print('hello')\n", "tests/b.py": b"assert True\n"}
    first = capture_module._manifest_hash_for_contents(dict(contents))
    second = capture_module._manifest_hash_for_contents(dict(contents))
    assert first == second


def test_manifest_hash_changed_content_different_hash():
    original = {"scripts/a.py": b"print('hello')\n"}
    changed = {"scripts/a.py": b"print('goodbye')\n"}
    assert capture_module._manifest_hash_for_contents(
        original
    ) != capture_module._manifest_hash_for_contents(changed)


def test_manifest_hash_file_ordering_does_not_change_hash():
    contents_a_then_b = {"scripts/a.py": b"aaa", "tests/b.py": b"bbb"}
    contents_b_then_a = {"tests/b.py": b"bbb", "scripts/a.py": b"aaa"}
    # Dict insertion order differs above; the manifest hash must not.
    assert capture_module._manifest_hash_for_contents(
        contents_a_then_b
    ) == capture_module._manifest_hash_for_contents(contents_b_then_a)


def test_manifest_hash_distinguishes_adjacent_entries_not_just_concatenation():
    """A naive concatenation could produce the same bytes for
    {"ab": b"c"} and {"a": b"bc"} -- the length-prefixed manifest format
    must not collide like that."""
    first = {"ab": b"c"}
    second = {"a": b"bc"}
    assert capture_module._manifest_hash_for_contents(
        first
    ) != capture_module._manifest_hash_for_contents(second)


def test_groq_answer_service_included_in_relevant_stage_glob_patterns():
    """Stage 5 item 2 regression guard: groq_answer_service.py must be
    matched by the manifest's glob patterns, since generation_usage
    telemetry depends on it."""
    assert any(
        pattern.endswith("groq_answer_service.py")
        for pattern in capture_module._RELEVANT_STAGE_GLOB_PATTERNS
    )
    matched = capture_module._relevant_stage_files()
    matched_names = {p.name for p in matched}
    assert "groq_answer_service.py" in matched_names


def test_broad_qa_test_files_excluded_from_manifest_scope():
    """Stage 5 item 2: tests/test_groq_answer_service.py and
    tests/test_qa_question_answering.py are deliberately NOT part of the
    reproducibility-identity manifest -- they are broad, general-purpose
    test suites, not Stage 1/capture-specific artifacts, and including
    them would conflate test-code churn with runtime capture identity."""
    for pattern in capture_module._RELEVANT_STAGE_GLOB_PATTERNS:
        assert "test_groq_answer_service" not in pattern
        assert "test_qa_question_answering" not in pattern


def test_real_content_manifest_hash_against_actual_working_tree():
    """Stage 5 item 5: exercises the REAL, unmocked file-reading manifest
    hash against the actual on-disk relevant stage files -- no Chroma, no
    Groq, nothing mutated. Confirms repeated reads are stable (the files
    are not being modified concurrently by this verification) and that
    groq_answer_service.py is genuinely among the hashed files, not just
    matched by a glob pattern that happens to exist on paper."""
    matched = capture_module._relevant_stage_files()
    matched_names = {p.name for p in matched}
    assert "groq_answer_service.py" in matched_names
    assert "question_answering.py" in matched_names

    first_hash, first_error = capture_module._content_manifest_hash()
    second_hash, second_error = capture_module._content_manifest_hash()

    assert first_error is None
    assert second_error is None
    assert first_hash == second_hash
    assert first_hash  # non-empty real hash


# ---------------------------------------------------------------------------
# V: serialized record never contains unauthorized evidence text
# ---------------------------------------------------------------------------


def test_serialized_record_never_contains_unauthorized_evidence_text():
    """V: for a student-role case, the faculty-only chunk's excerpt marker
    must not appear ANYWHERE in the fully serialized JSON record -- not
    just absent from evidence_text.excerpts, but absent from the whole
    string, proving the candidate pool itself never carries excerpt text
    either (the gate runs before any excerpt text enters the record at
    all, not as a post-hoc redaction pass)."""
    calls: list[dict] = []
    case = CaptureCase(
        case_id="leak-check",
        category="role_restricted_evidence",
        question="What is the notice?",
        user_role="student",
    )
    with patch.object(
        capture_module,
        "answer_qa_question",
        side_effect=_fake_answer_qa_question_factory(calls),
    ):
        record = capture_case(case, run_context={"captured_at": "test"})

    excerpts = record["evidence_text"]["excerpts"]
    included = record["evidence_text"]["included_chunk_ids"]

    # The two authorized chunks (student, both) are present...
    assert "student-doc::2" in included
    assert "extra-doc::3" in included
    # ...but the faculty-only chunk is not, for a student-role case.
    assert "faculty-doc::1" not in included
    assert "faculty-doc::1" not in excerpts

    serialized = json.dumps(record, ensure_ascii=False)
    assert _RESTRICTED_MARKER not in serialized

    # Structural guarantee: candidate-pool entries never carry excerpt text
    # at all, authorized or not -- only evidence_text.excerpts does.
    for candidate in record["retrieval"]["role_filtered_candidate_pool"]:
        assert "content_preview" not in candidate
        assert "source_excerpt" not in candidate


def test_serialized_record_for_authorized_admin_role_includes_authorized_excerpts_only():
    """Sanity check on the positive side: an admin-role case (sees
    everything per production's own filter_chunks_for_audience semantics)
    is authorized for ALL three fixture chunks, including the
    faculty-tagged one -- confirming the gate is role-sensitive both ways,
    not simply "never persist anything."""
    calls: list[dict] = []
    case = CaptureCase(
        case_id="leak-check-admin",
        category="role_restricted_evidence",
        question="What is the notice?",
        user_role="admin",
    )
    with patch.object(
        capture_module,
        "answer_qa_question",
        side_effect=_fake_answer_qa_question_factory(calls),
    ):
        record = capture_case(case, run_context={"captured_at": "test"})

    included = set(record["evidence_text"]["included_chunk_ids"])
    assert included == {"faculty-doc::1", "student-doc::2", "extra-doc::3"}
    assert _RESTRICTED_MARKER in json.dumps(record, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Stage 4 item 8: strengthened, whole-record security serialization tests
# covering the full role x audience matrix, not just one role/audience pair.
# ---------------------------------------------------------------------------

_STUDENT_TEXT_MARKER = "Student-visible notice text about deadlines."
_BOTH_TEXT_MARKER = "Unselected extra context, not sent to generation."


def _capture_with_role(user_role) -> dict:
    calls: list[dict] = []
    case = CaptureCase(
        case_id=f"role-matrix-{user_role!r}",
        category="role_restricted_evidence",
        question="What is the notice?",
        user_role=user_role,
    )
    with patch.object(
        capture_module,
        "answer_qa_question",
        side_effect=_fake_answer_qa_question_factory(calls),
    ):
        return capture_case(case, run_context={"captured_at": "test"})


def test_unknown_role_cannot_serialize_student_audience_text():
    record = _capture_with_role("totally-not-a-real-role")
    assert _STUDENT_TEXT_MARKER not in json.dumps(record, ensure_ascii=False)


def test_unknown_role_cannot_serialize_both_audience_text():
    record = _capture_with_role("totally-not-a-real-role")
    assert _BOTH_TEXT_MARKER not in json.dumps(record, ensure_ascii=False)


def test_unknown_role_cannot_serialize_faculty_audience_text():
    record = _capture_with_role("totally-not-a-real-role")
    assert _RESTRICTED_MARKER not in json.dumps(record, ensure_ascii=False)


def test_none_role_cannot_serialize_any_audience_text():
    record = _capture_with_role(None)
    serialized = json.dumps(record, ensure_ascii=False)
    assert _STUDENT_TEXT_MARKER not in serialized
    assert _BOTH_TEXT_MARKER not in serialized
    assert _RESTRICTED_MARKER not in serialized


def test_student_role_cannot_serialize_faculty_audience_text():
    record = _capture_with_role("student")
    assert _RESTRICTED_MARKER not in json.dumps(record, ensure_ascii=False)


def test_student_role_can_serialize_its_own_allowed_audience_text():
    """The flip side of the previous test: student role CAN serialize
    student/both-audience text -- proving this is a real, selective gate,
    not a blanket "redact everything" no-op that would trivially pass every
    denial test above."""
    record = _capture_with_role("student")
    serialized = json.dumps(record, ensure_ascii=False)
    assert _STUDENT_TEXT_MARKER in serialized
    assert _BOTH_TEXT_MARKER in serialized


def test_faculty_role_can_serialize_faculty_and_both_audience_text_not_needed_beyond_student_gate():
    """Authorized known role (faculty) can serialize the audiences it is
    actually authorized for (faculty, both) -- and, per production's own
    filter_chunks_for_audience semantics mirrored here, NOT student-only
    text."""
    record = _capture_with_role("faculty")
    serialized = json.dumps(record, ensure_ascii=False)
    assert _RESTRICTED_MARKER in serialized
    assert _BOTH_TEXT_MARKER in serialized
    assert _STUDENT_TEXT_MARKER not in serialized


def test_unknown_audience_cannot_serialize_text_for_admin_either():
    """Unknown/malformed audience denies persistence for ANY role,
    including admin -- proven with a 4th candidate carrying a malformed
    audience value ("everyone", not one of student/faculty/both) and a
    unique marker, confirming even admin cannot see it."""
    unknown_audience_marker = "UNKNOWN_AUDIENCE_MARKER_7c2d"

    def _fake(question, **kwargs):
        base = _fake_qa_result()
        extra_row = dict(_FAKE_RETRIEVED_CHUNKS[0])
        extra_row.update(
            {
                "citation_id": "malformed-audience-doc::9",
                "document_id": "malformed-audience-doc",
                "chunk_index": 9,
                "audience": "everyone",  # not one of student/faculty/both
                "content_preview": unknown_audience_marker,
                "citation_id_stamped": True,
            }
        )
        result = QAResult(
            answer=base.answer,
            sources=base.sources,
            confidence=base.confidence,
            retrieved_chunks=list(base.retrieved_chunks) + [extra_row],
        )
        gc_sink = kwargs.get("generation_context_sink")
        if gc_sink is not None:
            gc_sink.update(
                {
                    "generation_invoked": True,
                    "generation_succeeded": True,
                    "status": "invoked_and_succeeded:generation_answer_used",
                    "final_context_chunks": [dict(c) for c in _FAKE_FINAL_GENERATION_CONTEXT],
                }
            )
        return result

    case = CaptureCase(
        case_id="malformed-audience-admin",
        category="role_restricted_evidence",
        question="What is the notice?",
        user_role="admin",
    )
    with patch.object(capture_module, "answer_qa_question", side_effect=_fake):
        record = capture_case(case, run_context={"captured_at": "test"})

    assert "malformed-audience-doc::9" not in record["evidence_text"]["included_chunk_ids"]
    assert unknown_audience_marker not in json.dumps(record, ensure_ascii=False)


def test_candidate_debug_and_generation_context_structures_carry_no_raw_chunk_body():
    """The candidate pool, citation_selector_debug, and
    final_generation_context structures must never carry raw chunk body
    text anywhere -- only evidence_text.excerpts (and only when
    authorized) ever does."""
    record = _capture_with_role("student")

    for candidate in record["retrieval"]["role_filtered_candidate_pool"]:
        assert "content_preview" not in candidate
        assert "source_excerpt" not in candidate
        assert "text" not in candidate
    for debug_row in record["citation_selector_debug"]:
        # citation_debug_sink rows only ever carry claim_text (the ANSWER's
        # own text, never chunk body) plus shared_words/shared_numbers
        # tokens -- never a chunk's raw content.
        assert "content_preview" not in debug_row
        assert "chunk_text" not in debug_row
    for final_chunk in record["retrieval"]["final_generation_context"]:
        assert "content_preview" not in final_chunk
        assert "source_excerpt" not in final_chunk
        assert "text" not in final_chunk
