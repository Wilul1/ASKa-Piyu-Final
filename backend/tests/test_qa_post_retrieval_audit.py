"""Post-retrieval audit regressions (separate from Phase 2A retrieval ranking).

Exercises query → role/audience → retrieval slice → rerank scores already on
chunks → service preference → context selection → generation/fallback → answer.
Does not retune Phase 2A.
"""

from __future__ import annotations

import re
from typing import Any
from unittest.mock import patch

import pytest

from app.services.chroma_store import RetrievedChunk, select_role_visible_hits
from app.services.qa.groq_answer_service import GroqAnswerError
from app.services.qa.question_answering import (
    _answer_contradicts_table_records,
    _answer_has_unverifiable_mixed_status_claim,
    _answer_synthesizes_unsupported_range,
    _apply_conservative_classification_reply,
    _canonical_service_names_in_text,
    _confidence_for,
    _evidence_states_single_global_rule,
    _format_structured_tables,
    _is_global_classification_query,
    _looks_like_fee_amount,
    _prefer_active_topic_context,
    _redact_extraction_artifacts,
    _retrieval_quality,
    _structured_table_records_from_text,
    _table_records_evidence_answer,
    answer_qa_question,
    format_retrieved_context,
    resolve_active_topic,
    resolve_followup_question,
    resolve_turn_active_topic,
    select_context_chunks,
)
from app.services.qa.service_answer_formatter import prefer_service_chunks


UNDERGRAD_GRADING_TABLE = """\
Grading System

Undergraduate Academic Policies > Article 7 > Grading System and Other Grade-related Concerns > Sec. 1 > Grading System

The grading system is expressed in Arabic numerals
and is recorded by the Office of the Registrar. The following are the
grades used and their equivalents in percent and respective descrip-
tions.
Average Equivalent Grade Description
1.00 | 99-100 | Excellent
1.25 | 96-98
1.50 | 93-95 | Very Satisfactory
1.75 | 90-92
2.00 | 87-89 | Satisfactory
2.25 | 84-86
2.50 | 81-83 | Fairly Satisfactory
2.75 | 78-80
3.00 | 75-77
4.00 | 70-74 | Conditional Failure
5.00 | 69 and below Failed
INC | Incomplete
DRP | Officially Dropped
"""


def _chunk(
    title: str,
    text: str,
    *,
    score: float = 2.4,
    similarity: float = 0.85,
    audience: str = "student",
    reasons: list[str] | None = None,
    extra_meta: dict | None = None,
) -> RetrievedChunk:
    metadata = {
        "source_section": title,
        "section": title,
        "title": title,
        "audience": audience,
        "page_start": 41,
        "page_number": 41,
    }
    if extra_meta:
        metadata.update(extra_meta)
    return RetrievedChunk(
        document_id=title.lower().replace(" ", "-")[:40],
        title=title,
        source_filename="handbook.pdf",
        chunk_index=0,
        text=text,
        relevance_score=score,
        original_score=similarity,
        reranked_score=score,
        rerank_reasons=reasons or ["title_path_keyword_match", "metadata_category_match"],
        metadata=metadata,
    )


class RoleAwareStore:
    chunk_count = 40

    def __init__(self, chunks: list[RetrievedChunk]) -> None:
        self.chunks = list(chunks)
        self.calls: list[dict] = []

    def search(
        self,
        question: str,
        *,
        top_k: int | None = None,
        raw_k: int | None = None,
        user_role: str | None = None,
    ):
        self.calls.append(
            {
                "question": question,
                "top_k": top_k,
                "raw_k": raw_k,
                "user_role": user_role,
            }
        )
        ranked = sorted(self.chunks, key=lambda item: item.rerank_score, reverse=True)
        return select_role_visible_hits(ranked, user_role=user_role, top_k=top_k or 7)


def _default_grounded_answer(*, context: str = "", **_kwargs) -> str:
    """Default mocked "LLM" answer used by ``_ask`` when a test supplies
    neither ``groq_return`` nor ``groq_side_effect``: faithfully echoes the
    retrieved context so citation-selection (which narrows ``sources`` to
    whatever the *generated answer* actually supports — see
    ``_display_sources_for_answer`` in question_answering.py) finds every
    retrieved chunk supported, matching this suite's original assumption
    that ``result.sources`` mirrors the retrieval/context-selection this
    file actually tests. Tests that pass their own ``groq_return`` already
    use answer text that names the real evidence (office/fee/title words),
    so they are unaffected by this default.
    """
    return context or "Grounded answer from retrieved context."


def _ask(
    store: RoleAwareStore,
    question: str,
    *,
    groq_side_effect=None,
    groq_return: str | None = None,
    history=None,
    client_active_service=None,
):
    groq_kw = {}
    if groq_side_effect is not None:
        groq_kw["side_effect"] = groq_side_effect
    elif groq_return is not None:
        groq_kw["return_value"] = groq_return
    else:
        groq_kw["side_effect"] = _default_grounded_answer
    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch("app.services.qa.question_answering.generate_groq_answer", **groq_kw),
    ):
        return answer_qa_question(
            question,
            user_role="student",
            history=history,
            client_active_service=client_active_service,
        )


def test_first_turn_tor_retrieval_query_canonicalizes():
    resolved = resolve_followup_question("TOR", None)
    assert "transcript" in resolved.casefold()
    assert "terms of reference" not in resolved.casefold()
    names = _canonical_service_names_in_text("magkano ang TOR?")
    assert any("transcript" in name.casefold() for name in names)


def test_tor_best_evidence_survives_service_preference():
    tor = _chunk(
        "Issuance of Transcript of Records",
        "Transcript of Records. Fees: PHP 75.00 / page. Submit at the Registrar.",
        score=4.64,
        extra_meta={"canonical_topic": "Issuance of Transcript of Records", "total_fees": "PHP 75.00 / page"},
    )
    grievance = _chunk(
        "Composition and Terms of Reference (TOR)",
        "The Grievance Committee Terms of Reference (TOR) define membership.",
        score=3.10,
    )
    preferred = prefer_service_chunks([grievance, tor], question="TOR")
    assert preferred[0].metadata["source_section"] == "Issuance of Transcript of Records"
    preferred_fee = prefer_service_chunks([grievance, tor], question="magkano ang TOR?")
    assert preferred_fee[0].metadata["source_section"] == "Issuance of Transcript of Records"
    selected, _ = select_context_chunks("Transcript of Records (tor)", preferred)
    titles = {(chunk.metadata or {}).get("source_section") for chunk in selected}
    assert "Issuance of Transcript of Records" in titles


@pytest.mark.parametrize(
    "question",
    [
        "TOR",
        "magkano ang TOR?",
        "TOR requirements",
        "saan kukuha ng TOR?",
        "saan makakakuha ng TOR?",
        "where can I get my TOR?",
        "where do I request TOR?",
        "where do I submit TOR requirements?",
    ],
)
def test_tor_questions_keep_transcript_in_final_context(question):
    store = RoleAwareStore(
        [
            _chunk(
                "Issuance of Transcript of Records",
                "Transcript of Records is issued by the Registrar. Fees: PHP 75.00 / page.",
                score=4.64,
                extra_meta={
                    "canonical_topic": "Issuance of Transcript of Records",
                    "total_fees": "PHP 75.00 / page",
                    "office": "Registrar",
                },
            ),
            _chunk(
                "Composition and Terms of Reference (TOR)",
                "Grievance Committee Terms of Reference (TOR).",
                score=3.2,
            ),
        ]
    )
    result = _ask(
        store,
        question,
        groq_return="The Registrar issues the Transcript of Records. The listed fee is PHP 75.00 per page.",
    )
    context_titles = " ".join(str(item.get("title") or "") for item in result.retrieved_chunks)
    assert "transcript" in context_titles.casefold()
    assert "grievance" not in result.answer.casefold()
    assert "terms of reference" not in result.answer.casefold()


def test_student_absence_question_survives_faculty_heavy_candidate_pool():
    faculty = [
        _chunk(
            f"Vacation service credits {i}",
            "Faculty vacation service credits of teachers and leave of absence.",
            score=4.8 - (i * 0.05),
            audience="faculty",
            reasons=["boost_valid_source_metadata"],
        )
        for i in range(7)
    ]
    student = _chunk(
        "Absences",
        "A student who incurs absences of more than twenty-five percent (25%) of the required number of class hours in a given subject is dropped from that subject.",
        score=2.5,
        audience="student",
        reasons=["attendance_policy_match", "title_path_keyword_match"],
        extra_meta={"article": "Article 6", "section": "4.1 Absences"},
    )
    store = RoleAwareStore(faculty + [student])
    result = _ask(
        store,
        "How many absences before I am dropped from a subject?",
        groq_return="A student who incurs absences of more than 25% of the required class hours is dropped from the subject.",
    )
    assert result.selected_context_count >= 1
    assert "do not contain enough information" not in result.answer.casefold()
    assert "25" in result.answer
    assert result.fallback_reason != "no_retrieval_context"


def test_faculty_only_chunk_stays_hidden_from_student():
    store = RoleAwareStore(
        [
            _chunk(
                "Faculty salary schedule",
                "Confidential faculty salary steps.",
                score=4.5,
                audience="faculty",
            )
        ]
    )
    result = _ask(
        store,
        "What is the faculty salary schedule?",
        groq_side_effect=GroqAnswerError("Groq answer generation timed out."),
    )
    assert result.selected_context_count == 0 or all(
        (item.get("metadata") or {}).get("audience") != "faculty"
        for item in result.retrieved_chunks
    )


def test_passing_grade_table_keeps_row_associations():
    formatted = _format_structured_tables(UNDERGRAD_GRADING_TABLE)
    rows = [line[2:] for line in formatted.splitlines() if line.startswith("- ")]
    failed = next(row for row in rows if "5.00" in row)
    assert "69" in failed
    assert "fail" in failed.casefold()
    assert "Identifier: 5.00" in failed
    assert "Status: Failed" in failed
    passing_floor = next(row for row in rows if "3.00" in row)
    assert "75" in passing_floor
    conditional = next(row for row in rows if "4.00" in row)
    assert "Conditional Failure" in conditional
    assert "Status:" in conditional
    # The inverted reading that produced "69 and above is passing" is not in the evidence rows.
    assert not any("69" in row and "pass" in row.casefold() for row in rows)
    assert not any("and above" in row.casefold() for row in rows)
    assert "authoritative" in formatted.casefold()
    chunk = _chunk("Grading System", UNDERGRAD_GRADING_TABLE, extra_meta={"subcategory": "Grading System"})
    context = format_retrieved_context([chunk])
    assert "Structured table" in context
    assert "5.00" in context
    assert "Failed" in context
    records = _structured_table_records_from_text(context)
    assert any(item.get("Identifier") == "5.00" and "fail" in (item.get("Status") or "").casefold() for item in records)


def test_passing_grade_question_sends_structured_table_to_generator():
    store = RoleAwareStore(
        [_chunk("Grading System", UNDERGRAD_GRADING_TABLE, extra_meta={"subcategory": "Grading System"})]
    )
    captured: dict[str, str] = {}

    def _capture(question, context, **kwargs):
        captured["context"] = context
        captured["question"] = question
        return (
            "Undergraduate grades are expressed in Arabic numerals. "
            "3.00 covers 75-77. 5.00 is 69 and below, Failed. "
            "4.00 is Conditional Failure (70-74)."
        )

    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch("app.services.qa.question_answering.generate_groq_answer", side_effect=_capture),
    ):
        result = answer_qa_question("What is the passing grade?", user_role="student")

    assert "Structured table" in captured["context"]
    assert "69 and above" not in result.answer.casefold()
    assert "failed" in result.answer.casefold() or "75" in result.answer


def test_good_moral_cost_does_not_clarify_when_source_lists_none():
    store = RoleAwareStore(
        [
            _chunk(
                "Issuance of Good Moral Certificate (Undergraduate)",
                "Good Moral Certificate.\nFees: None\nWho May Avail: Currently enrolled students",
                score=3.04,
                extra_meta={"total_fees": "None", "canonical_topic": "Issuance of Good Moral Certificate"},
                reasons=["title_path_keyword_match", "metadata_category_match"],
            )
        ]
    )
    result = _ask(
        store,
        "How much does a Good Moral Certificate cost?",
        groq_side_effect=GroqAnswerError("Groq answer generation timed out."),
    )
    assert "which part do you need" not in result.answer.casefold()
    assert "i can help with related topics" not in result.answer.casefold()
    assert "no listed fee" in result.answer.casefold() or "does not clearly specify" in result.answer.casefold()


def test_vague_help_clarifies_and_is_not_high_confidence():
    store = RoleAwareStore(
        [
            _chunk(
                title,
                f"{title}. Clients may request this service.",
                score=1.07,
                reasons=["boost_valid_source_metadata", "boost_has_page_number"],
            )
            for title in (
                "Provision of Technical Assistance/Expertise",
                "Breastfeeding and Lactating Assistance",
                "Library Reference Assistance",
            )
        ]
    )
    result = _ask(store, "help", groq_return="Here is what LSPU offers.")
    assert result.confidence != "high"
    quality = _retrieval_quality("help", store.chunks, store.chunks, broad_query=False, collection_mode=False)
    assert quality["should_clarify"] is True


def test_contextless_cost_question_is_not_high_confidence():
    evidence = [
        _chunk("Examination Fee", "Amount as indicated.", score=1.06, reasons=["boost_valid_source_metadata"]),
        _chunk("Library Reference Assistance", "Library staff assist clients.", score=1.05, reasons=["boost_has_page_number"]),
    ]
    assert (
        _confidence_for(evidence, evidence, "The fee is P50.00.", "How much does it cost?")
        != "high"
    )
    quality = _retrieval_quality(
        "How much does it cost?", evidence, evidence, broad_query=False, collection_mode=False
    )
    assert quality["should_clarify"] is True


def test_extraction_artifacts_are_not_student_facing_facts():
    raw = "Enrollment\nFees: form. 3\nProcessing Time: [NEEDS REVIEW]\nPerson Responsible: Not specified"
    redacted = _redact_extraction_artifacts(raw)
    assert "form. 3" not in redacted
    assert "[NEEDS REVIEW]" not in redacted
    chunk = _chunk(
        "Enrollment",
        raw,
        extra_meta={"total_fees": "form. 3"},
    )
    context = format_retrieved_context([chunk])
    assert "form. 3" not in context
    assert "[NEEDS REVIEW]" not in context
    store = RoleAwareStore([chunk])
    result = _ask(
        store,
        "How much is enrollment?",
        groq_side_effect=GroqAnswerError("Groq answer generation timed out."),
    )
    assert "form. 3" not in result.answer
    assert "[needs review]" not in result.answer.casefold()
    assert "does not clearly specify" in result.answer.casefold()


@pytest.mark.parametrize(
    "inverted",
    [
        "4.00 Conditional Failure is a passing grade.",
        "Grades of 3.00 and above are passing.",
        "A grade of 5.00 is passing because it is above 3.00.",
        "69 and above is passing.",
    ],
)
def test_inverted_passing_grade_answers_are_rejected(inverted):
    formatted = format_retrieved_context(
        [_chunk("Grading System", UNDERGRAD_GRADING_TABLE, extra_meta={"subcategory": "Grading System"})]
    )
    records = _structured_table_records_from_text(formatted)
    assert records
    assert _answer_contradicts_table_records(inverted, records)
    replacement = _table_records_evidence_answer(records)
    assert "4.00" in replacement and "Conditional Failure" in replacement
    assert any(item.get("Identifier") == "5.00" for item in records)
    assert "5.00" in replacement
    assert "Failed" in replacement
    assert "3.00 and above" not in replacement.casefold()
    assert "passing grade" not in replacement.casefold()


def test_passing_grade_generator_inversion_is_replaced():
    store = RoleAwareStore(
        [_chunk("Grading System", UNDERGRAD_GRADING_TABLE, extra_meta={"subcategory": "Grading System"})]
    )
    result = _ask(
        store,
        "What is the passing grade?",
        groq_return="4.00 Conditional Failure is a passing grade. Grades of 3.00 and above are passing.",
    )
    assert "4.00 Conditional Failure is a passing" not in result.answer
    assert "3.00 and above" not in result.answer.casefold()
    assert "Failed" in result.answer
    assert "Conditional Failure" in result.answer


# --- generic structured-table inversion guards (synthetic, non-LSPU fixtures) ---
#
# These use a made-up "Widget Quality Tiers" domain specifically so the tests
# validate the table-interpretation *algorithm* rather than accidentally
# memorizing LSPU's actual grade values. No institutional facts are encoded
# in the application code by these fixes — only the general "a Status label
# is authoritative for its own row only" reasoning.

SYNTHETIC_TIER_TABLE_NO_HEADER = """\
Widget Quality Tiers

Program Handbook > Article 3 > Widget Quality Tiers > Sec. 1 > Widget Quality Tiers

1.00 | 90-100 | Excellent
2.00 | 75-89 | Good
3.00 | 60-74 | Conditional Failure
4.00 | 0-59 | Failed
"""

SYNTHETIC_TIER_TABLE_WITH_HEADER = """\
Widget Quality Tiers

Program Handbook > Article 3 > Widget Quality Tiers > Sec. 1 > Widget Quality Tiers

Tier Code | Score Range | Rating
1.00 | 90-100 | Excellent
2.00 | 75-89 | Good
3.00 | 60-74 | Conditional Failure
4.00 | 0-59 | Failed
"""


@pytest.mark.parametrize(
    "table_text",
    [SYNTHETIC_TIER_TABLE_NO_HEADER, SYNTHETIC_TIER_TABLE_WITH_HEADER],
    ids=["no-header", "with-header"],
)
def test_range_based_inversion_is_caught_regardless_of_header(table_text):
    """Root-cause fix #1: the detector used to check only the Identifier
    column for a passing claim, so an answer that restates the row using its
    *Range* value instead (a very natural LLM phrasing) slipped through
    undetected. Also proves the detector works whether or not the source
    table happened to include a header row — a table headered "Tier Code /
    Score Range / Rating" describes the same shape of row as one with no
    header, and must not be a blind spot for this check.
    """
    formatted = format_retrieved_context(
        [_chunk("Widget Quality Tiers", table_text, extra_meta={"subcategory": "Widget Quality Tiers"})]
    )
    records = _structured_table_records_from_text(formatted)
    assert records
    assert any(r.get("Identifier") == "3.00" and "conditional" in (r.get("Status") or "").casefold() for r in records)

    # Restates the row via its Range value ("60-74"), not its Identifier ("3.00").
    range_based_inversion = "A rating above the 60-74 (Conditional Failure) tier is required to pass."
    assert _answer_contradicts_table_records(range_based_inversion, records)

    # A correct statement using either the Identifier or the Range must not be flagged.
    correct_identifier = "A rating of 1.00 (90-100) is Excellent."
    correct_range = "A score of 90-100 earns an Excellent rating."
    assert not _answer_contradicts_table_records(correct_identifier, records)
    assert not _answer_contradicts_table_records(correct_range, records)


@pytest.mark.parametrize(
    "inverted_answer",
    [
        "Any score above 59 (60 and higher) is passing.",
        "A score of 60 or higher is considered passing.",
        "The minimum passing score is 60.",
        "Anything below 90 fails.",
    ],
    ids=[
        "above-x-is-passing",
        "x-and-higher",
        "minimum-passing-score",
        "anything-below-x-fails",
    ],
)
def test_boundary_number_paraphrases_are_caught_without_reproducing_the_marker_string(
    inverted_answer,
):
    """Root-cause fix #2 (safety-blocker follow-up): the detector required the
    generated answer to reproduce a record's *whole* captured marker string
    ("69 and below") verbatim. A model that instead extracts just the
    boundary *number* out of a range ("above 69", "70 and higher") never
    reproduced that phrase, so it slipped through — this was the exact
    reported live failure ("passing is any score above 69 (70 and
    higher)"). Detection is now number-level, tied to the same one record's
    own Identifier/Range, not merely phrase-level string matching. Every
    paraphrase here is checked against a fabricated, non-LSPU domain.
    """
    formatted = format_retrieved_context(
        [_chunk("Widget Quality Tiers", SYNTHETIC_TIER_TABLE_NO_HEADER, extra_meta={"subcategory": "Widget Quality Tiers"})]
    )
    records = _structured_table_records_from_text(formatted)
    assert records
    assert _answer_contradicts_table_records(inverted_answer, records)


@pytest.mark.parametrize(
    "correct_answer",
    [
        "A score of 75 or higher earns a Good rating or better.",
        "A rating of 1.00 (90-100) is Excellent.",
        "A rating of 2.00 (75-89) is Good.",
        "A rating of 3.00 (60-74) is Conditional Failure.",
        "The minimum passing score is 75.",
    ],
)
def test_correct_boundary_statements_are_not_flagged_as_contradictions(correct_answer):
    """Guards the fix above from over-firing: a numerically-correct
    restatement of a row (using either its Identifier or Range boundary)
    must not be treated as an inversion just because it shares a number
    with a negative-status row's neighbor."""
    formatted = format_retrieved_context(
        [_chunk("Widget Quality Tiers", SYNTHETIC_TIER_TABLE_NO_HEADER, extra_meta={"subcategory": "Widget Quality Tiers"})]
    )
    records = _structured_table_records_from_text(formatted)
    assert not _answer_contradicts_table_records(correct_answer, records)


def test_boundary_number_inversion_end_to_end_cannot_reach_high_confidence():
    """End-to-end (fabricated domain): a generated answer using the
    boundary-number paraphrase style must be corrected, and confidence must
    not remain "high" for an answer the system had to override."""
    store = RoleAwareStore(
        [_chunk("Widget Quality Tiers", SYNTHETIC_TIER_TABLE_NO_HEADER, extra_meta={"subcategory": "Widget Quality Tiers"})]
    )
    result = _ask(
        store,
        "What is the passing rating for widget quality?",
        groq_return="Any score above 59 (60 and higher) is passing for widget quality.",
    )
    assert "above 59" not in result.answer
    assert "60 and higher" not in result.answer
    assert "Excellent" in result.answer or "Good" in result.answer
    assert result.confidence != "high"


def test_headered_table_inversion_end_to_end_caps_confidence_and_corrects_answer():
    """End-to-end (synthetic domain): the model inverts a headered table by
    claiming the higher/worse tier is the passing one. The corrected answer
    must restate the real rows, and confidence must not remain "high" for an
    answer the system itself had to override.
    """
    store = RoleAwareStore(
        [_chunk("Widget Quality Tiers", SYNTHETIC_TIER_TABLE_WITH_HEADER, extra_meta={"subcategory": "Widget Quality Tiers"})]
    )
    result = _ask(
        store,
        "What is the passing rating for widget quality?",
        groq_return="A passing rating requires a score above the 3.00 (60-74) Conditional Failure tier.",
    )
    assert "above the 3.00" not in result.answer
    assert "Conditional Failure" in result.answer
    assert "1.00" in result.answer or "90-100" in result.answer
    assert result.confidence != "high"


def test_correct_headered_table_answer_is_not_downgraded_or_altered():
    """The confidence cap and correction must only engage on an actual
    detected contradiction — a correct answer over the same headered table
    keeps its own generation and is not forced down defensively."""
    store = RoleAwareStore(
        [_chunk("Widget Quality Tiers", SYNTHETIC_TIER_TABLE_WITH_HEADER, extra_meta={"subcategory": "Widget Quality Tiers"})]
    )
    result = _ask(
        store,
        "What is the passing rating for widget quality?",
        groq_return="A rating of 1.00 (90-100) is Excellent, the top tier.",
    )
    assert "A rating of 1.00 (90-100) is Excellent, the top tier." in result.answer


@pytest.mark.parametrize(
    "question",
    ["help", "How much does it cost?", "requirements?", "Where do I submit it?"],
)
def test_first_turn_underspecified_questions_clarify(question):
    assert resolve_turn_active_topic(question, None) == ""
    assert resolve_active_topic(None, fallback_user=question) == ""
    store = RoleAwareStore(
        [
            _chunk(
                "Provision of Technical Assistance/Expertise",
                "Clients may request technical assistance. Fees: PHP 50.00",
                score=1.08,
                reasons=["boost_valid_source_metadata", "boost_has_page_number"],
            ),
            _chunk(
                "Library Reference Assistance",
                "Library staff assist clients. Submit at the library.",
                score=1.06,
                reasons=["boost_has_page_number"],
            ),
        ]
    )
    result = _ask(store, question, groq_return="Here is a random charter service.")
    assert result.confidence == "low"
    assert result.fallback_used is True
    assert "which university service" in result.answer.casefold()
    assert result.fallback_reason == "underspecified_without_active_topic"


def test_cost_followup_keeps_prior_tor_topic():
    history = [
        {"role": "user", "content": "Tell me about TOR."},
        {"role": "assistant", "content": "The Registrar issues the Transcript of Records."},
    ]
    active = resolve_turn_active_topic("How much does it cost?", history)
    assert "transcript" in active.casefold() or "tor" in active.casefold()
    resolved = resolve_followup_question("How much does it cost?", history)
    assert "transcript" in resolved.casefold() or "tor" in resolved.casefold()
    store = RoleAwareStore(
        [
            _chunk(
                "Issuance of Transcript of Records",
                "Transcript of Records. Fees: PHP 75.00 / page.",
                score=4.2,
                extra_meta={
                    "canonical_topic": "Issuance of Transcript of Records",
                    "total_fees": "PHP 75.00 / page",
                    "document_type": "citizen_charter",
                },
            ),
            _chunk(
                "Examination Fee",
                "Amount as indicated. Fees: PHP 50.00",
                score=3.8,
                extra_meta={"total_fees": "PHP 50.00"},
            ),
        ]
    )
    result = _ask(
        store,
        "How much does it cost?",
        history=history,
        groq_return="The listed fee for Transcript of Records is PHP 75.00 per page.",
    )
    titles = " ".join(str(item.get("title") or "") for item in result.retrieved_chunks)
    assert "transcript" in titles.casefold()
    assert "75" in result.answer


@pytest.mark.parametrize(
    "question",
    [
        "purple helicopter pasta policy",
        "asdfqwer zxcv123 purple helicopter pasta policy",
        "fnord quux zebra pineapple ordinance",
        "who invented the quantum waffle protocol",
    ],
)
def test_nonsense_queries_are_not_high_confidence(question):
    evidence = [
        _chunk(
            "Guidelines for Helping Teachers Transition to Online Learning",
            "Faculty health and wellness guidelines and related policy notes.",
            score=2.1,
            reasons=["title_path_keyword_match", "boost_valid_source_metadata"],
        ),
        _chunk(
            "Mental Health Services/Treatment",
            "Mental health services for students and faculty.",
            score=2.0,
            reasons=["metadata_category_match", "boost_has_page_number"],
        ),
    ]
    assert _confidence_for(evidence, evidence, "Here is a related policy.", question) != "high"
    quality = _retrieval_quality(question, evidence, evidence, broad_query=False, collection_mode=False)
    assert quality["should_clarify"] is True
    assert (
        _confidence_for(evidence, evidence, "Here is a related policy.", question)
        == "low"
    )


def test_tor_location_prefers_issuance_over_crediting_requirement_mention():
    tor = _chunk(
        "Issuance of Transcript of Records",
        "Transcript of Records is issued by the Registrar. Where to Secure: Registrar.",
        score=2.4,
        extra_meta={
            "canonical_topic": "Issuance of Transcript of Records",
            "office": "Registrar",
            "document_type": "citizen_charter",
        },
    )
    crediting = _chunk(
        "Crediting of Subjects / Colleges",
        "Requirements: Transcript of records from previous school. Where to Secure: previous school.",
        score=4.1,
        extra_meta={
            "canonical_topic": "Crediting of Subjects / Colleges",
            "document_type": "citizen_charter",
        },
    )
    for question in (
        "saan kukuha ng TOR?",
        "saan makakakuha ng TOR?",
        "where can I get my TOR?",
        "where do I request TOR?",
        "where do I submit TOR requirements?",
    ):
        preferred = prefer_service_chunks([crediting, tor], question=question)
        assert preferred[0].metadata["source_section"] == "Issuance of Transcript of Records", question


@pytest.mark.parametrize(
    ("topic", "title", "policy_title"),
    [
        ("Good Moral", "Issuance of Good Moral Certificate", "Retention Policy — Good Moral Character"),
        ("TOR", "Issuance of Transcript of Records", "Crediting of Subjects / Colleges"),
        ("Clearance", "Issuance of Student Clearance", "Clearance as a graduation policy note"),
        ("Enrollment", "Enrollment", "Assessment of Fees"),
    ],
)
def test_slot_followup_prefers_service_card_over_policy_name_overlap(topic, title, policy_title):
    service = _chunk(
        title,
        f"{title}.\nFees: None\nOffice: Registrar\nRequirements: Certificate of Registration, Student ID",
        score=2.6,
        extra_meta={
            "canonical_topic": title,
            "total_fees": "None",
            "office": "Registrar",
            "document_type": "citizen_charter",
            "extracted_requirements": '["Certificate of Registration","Student ID"]',
        },
    )
    policy = _chunk(
        policy_title,
        f"Students must maintain {topic} standing under the retention policy.",
        score=3.8,
    )
    preferred = _prefer_active_topic_context([policy, service], topic)
    assert preferred[0].metadata["source_section"] == title
    history = [
        {"role": "user", "content": topic},
        {"role": "assistant", "content": f"Here is {title}."},
    ]
    store = RoleAwareStore([policy, service])
    result = _ask(
        store,
        "requirements?",
        history=history,
        groq_return=f"The required documents for {title} are Certificate of Registration and Student ID.",
    )
    titles = " ".join(str(item.get("title") or "") for item in result.retrieved_chunks)
    assert title.casefold() in titles.casefold()
    assert "retention policy" not in result.answer.casefold()


def test_mid_sentence_form_artifact_and_page_marker_are_not_fees():
    assert _looks_like_fee_amount("form. 3") is False
    assert _looks_like_fee_amount("P137") is False
    assert _looks_like_fee_amount("PHP 75.00 / page") is True
    assert _looks_like_fee_amount("P75.00 / page") is True
    raw = "Enrollment tracking uses form. 3 and cites P137 in the extract."
    redacted = _redact_extraction_artifacts(raw)
    assert "form. 3" not in redacted
    assert "P137" not in redacted
    context = format_retrieved_context([_chunk("Enrollment", raw, extra_meta={"total_fees": "P137"})])
    assert "form. 3" not in context
    assert "P137" not in context
    assert "[NEEDS REVIEW]" not in _redact_extraction_artifacts("Office: [NEEDS REVIEW]")


def test_provider_failure_uses_grounded_service_evidence_not_another_service():
    store = RoleAwareStore(
        [
            _chunk(
                "Issuance of Good Moral Certificate",
                "Good Moral Certificate.\nFees: None\nTotal Processing Time: 1 day\nOffice: Guidance",
                score=3.1,
                extra_meta={
                    "canonical_topic": "Issuance of Good Moral Certificate",
                    "total_fees": "None",
                    "office": "Guidance",
                    "total_processing_time": "1 day",
                    "document_type": "citizen_charter",
                },
            ),
            _chunk(
                "Enrollment",
                "Enrollment.\nFees: PHP 2,000.00",
                score=3.0,
                extra_meta={"canonical_topic": "Enrollment", "total_fees": "PHP 2,000.00"},
            ),
        ]
    )
    history = [
        {"role": "user", "content": "Good Moral"},
        {"role": "assistant", "content": "Issuance of Good Moral Certificate."},
    ]
    result = _ask(
        store,
        "How much does it cost?",
        history=history,
        groq_side_effect=GroqAnswerError("429 Too Many Requests"),
    )
    assert "2,000" not in result.answer
    assert "enrollment" not in result.answer.casefold()
    assert "no listed fee" in result.answer.casefold() or "does not clearly specify" in result.answer.casefold()


# --- P1: active topic survives a truncated conversation window --------------


def test_active_topic_reconstructed_from_assistant_replies_after_history_truncation():
    """The Flutter client caps forwarded history to the last 8 messages
    (chatbot_page.dart `_chatHistoryPayload`). After ~5 Enrollment turns, the
    *original* "How do I enroll" topic-setting question falls outside that
    window, leaving only slot follow-ups ("What documents do I need?",
    "Where do I submit them?") as the remaining user turns — every one of
    which is itself underspecified and skipped by topic resolution. The
    active service must be reconstructed from the assistant's own past
    replies (which restate the resolved service by name) rather than being
    lost, independent of how many raw messages the window held.
    """
    from app.services.qa.question_answering import resolve_turn_active_topic, _has_real_active_topic

    truncated_history = [
        {"role": "assistant", "content": "Go to the Registrar Office with your enrolment slip, "
                                          "good moral certificate, report card. Total processing time: 20 minutes."},
        {"role": "user", "content": "What documents do I need?"},
        {"role": "assistant", "content": "The required documents for Enrollment are: Enrolment Slip, "
                                          "Certificate of Good Moral Character, Report Card."},
        {"role": "user", "content": "Where do I submit them?"},
        {"role": "assistant", "content": "Submit your enrollment documents at the Registrar Office."},
        {"role": "user", "content": "How much does it cost?"},
        {"role": "assistant", "content": "The listed fee for Enrollment is PHP 2,000.00."},
    ]
    topic = resolve_turn_active_topic("Which office handles that?", truncated_history)
    assert _has_real_active_topic(topic)


def test_adjacent_service_mentioned_in_one_reply_does_not_become_active_topic():
    """Safety fix: the assistant-reply fallback above must not trust a
    service name from a single, possibly-incidental mention. A real
    Enrollment reply describing the wider admission process can mention an
    adjacent service (an entrance exam / admission interview step) by name
    without that becoming the conversation's actual topic. Only a service
    corroborated by at least two scanned assistant replies is trusted;
    otherwise no topic is reconstructed at all (safe clarification instead
    of a confidently wrong office), per the independent-validation finding
    that this exact pattern produced misinformation.
    """
    from app.services.qa.question_answering import resolve_turn_active_topic, _has_real_active_topic

    history = [
        {"role": "assistant", "content": "Go to the Registrar Office with your enrolment slip, "
                                          "good moral certificate, report card. Total processing time: 20 minutes."},
        {"role": "user", "content": "What documents do I need?"},
        {"role": "assistant", "content": "The required documents for Enrollment are: Enrolment Slip, "
                                          "Certificate of Good Moral Character, Report Card."},
        {"role": "user", "content": "How does the process work?"},
        {"role": "assistant", "content": "New students must first complete the entrance examination and "
                                          "admission interview at the College before proceeding to "
                                          "Enrollment at the Registrar."},
    ]
    topic = resolve_turn_active_topic("Which office handles that?", history)
    assert "Entrance Examination" not in topic
    assert not _has_real_active_topic(topic)


def test_ambiguous_assistant_history_reconstruction_clarifies_end_to_end():
    """Full-pipeline version of the safety fix above: when the only
    reconstructable "topic" from assistant history is a single,
    uncorroborated adjacent-service mention, the system must return a safe
    clarification rather than confidently answering with the wrong
    service's office."""
    store = RoleAwareStore(
        [
            _chunk(
                "Enrollment",
                "Enrollment. Office / Division Registrar. Fees: PHP 2,000.00.",
                score=3.0,
                extra_meta={"canonical_topic": "Enrollment", "office": "Registrar"},
            ),
            _chunk(
                "Entrance Examination",
                "Entrance Examination. Office / Division Admissions Office.",
                score=3.0,
                extra_meta={"canonical_topic": "Entrance Examination", "office": "Admissions Office"},
            ),
        ]
    )
    history = [
        {"role": "assistant", "content": "Go to the Registrar Office with your enrolment slip, "
                                          "good moral certificate, report card. Total processing time: 20 minutes."},
        {"role": "user", "content": "What documents do I need?"},
        {"role": "assistant", "content": "The required documents for Enrollment are: Enrolment Slip, "
                                          "Certificate of Good Moral Character, Report Card."},
        {"role": "user", "content": "How does the process work?"},
        {"role": "assistant", "content": "New students must first complete the entrance examination and "
                                          "admission interview at the College before proceeding to "
                                          "Enrollment at the Registrar."},
    ]
    result = _ask(
        store,
        "Which office handles that?",
        history=history,
        groq_return="The Admissions Office handles the entrance examination.",
    )
    assert not ("entrance" in result.answer.casefold() and "college" in result.answer.casefold())
    assert result.fallback_reason == "underspecified_without_active_topic"


def test_good_moral_long_followup_chain_still_resolves_correctly():
    """Regression guard: the corroboration tightening above only applies to
    the assistant-reply fallback path. A Good Moral conversation resolves
    its active topic through explicit user turns (the switch message itself)
    and must be entirely unaffected."""
    store = RoleAwareStore(
        [
            _chunk(
                "Issuance of Good Moral Certificate (Undergraduate)",
                "Good Moral Certificate. Office / Division OSAS. Fees: None.",
                score=3.0,
                extra_meta={"canonical_topic": "Issuance of Good Moral Certificate", "total_fees": "None", "office": "OSAS"},
            ),
        ]
    )
    history = [
        {"role": "user", "content": "Now tell me about Good Moral."},
        {"role": "assistant", "content": "The Issuance of Good Moral Certificate is handled by OSAS."},
        {"role": "user", "content": "What are the requirements?"},
        {"role": "assistant", "content": "Requirements: Certificate of Registration, Student ID."},
        {"role": "user", "content": "Where do I submit it?"},
        {"role": "assistant", "content": "Submit at the Office of the Student Affairs and Services."},
    ]
    result = _ask(
        store,
        "How much does it cost?",
        history=history,
        groq_return="There is no listed fee for the Good Moral Certificate.",
    )
    assert result.sources
    assert "good moral" in " ".join(str(s.get("title") or "") for s in result.sources).casefold()


def test_explicit_topic_switch_still_replaces_the_previous_service():
    """An explicit switch must still fully replace the previous active
    topic — the corroboration requirement applies only to the assistant-
    reply fallback, never to an explicit user-stated switch."""
    from app.services.qa.question_answering import resolve_turn_active_topic

    history = [
        {"role": "user", "content": "How do I drop a subject?"},
        {"role": "assistant", "content": "Obtain a Dropping Form from the Registrar, get faculty and Dean "
                                          "approval, submit to the Registrar. Fee: P30.00."},
    ]
    topic = resolve_turn_active_topic("Now tell me about TOR.", history)
    assert "transcript" in topic.casefold() or "tor" in topic.casefold()
    assert "drop" not in topic.casefold()


def test_immediate_followup_after_explicit_switch_retains_the_new_service():
    """The very next slot follow-up after an explicit switch must resolve
    against the *new* service, not the one before it — this resolves via
    the switch message itself (a substantive user turn), independent of the
    assistant-reply corroboration logic."""
    from app.services.qa.question_answering import resolve_turn_active_topic

    history = [
        {"role": "user", "content": "How do I drop a subject?"},
        {"role": "assistant", "content": "Obtain a Dropping Form from the Registrar, get faculty and Dean "
                                          "approval, submit to the Registrar. Fee: P30.00."},
        {"role": "user", "content": "Now tell me about TOR."},
        {"role": "assistant", "content": "The Registrar issues the Transcript of Records. The listed fee is PHP 75.00 per page."},
    ]
    topic = resolve_turn_active_topic("How much does it cost?", history)
    assert "transcript" in topic.casefold() or "tor" in topic.casefold()
    assert "drop" not in topic.casefold()


def test_enrollment_long_followup_after_truncation_does_not_clarify_with_zero_sources():
    """End-to-end reproduction of the reported sidecar failure: five-plus
    Enrollment turns, then "Which office handles that?" with a history
    window that no longer contains the original topic-setting question."""
    store = RoleAwareStore(
        [
            _chunk(
                "Enrollment",
                "Enrollment. Office / Division Registrar. Fees: PHP 2,000.00.",
                score=3.0,
                extra_meta={"canonical_topic": "Enrollment", "office": "Registrar"},
            ),
        ]
    )
    truncated_history = [
        {"role": "assistant", "content": "Go to the Registrar Office with your enrolment slip, "
                                          "good moral certificate, report card. Total processing time: 20 minutes."},
        {"role": "user", "content": "What documents do I need?"},
        {"role": "assistant", "content": "The required documents for Enrollment are: Enrolment Slip, "
                                          "Certificate of Good Moral Character, Report Card."},
        {"role": "user", "content": "Where do I submit them?"},
        {"role": "assistant", "content": "Submit your enrollment documents at the Registrar Office."},
        {"role": "user", "content": "How much does it cost?"},
        {"role": "assistant", "content": "The listed fee for Enrollment is PHP 2,000.00."},
    ]
    result = _ask(
        store,
        "Which office handles that?",
        history=truncated_history,
        groq_return="The Registrar's Office handles enrollment.",
    )
    assert result.sources, "must not clarify with zero sources"
    assert result.fallback_reason != "underspecified_without_active_topic"
    assert "registrar" in result.answer.casefold()


def test_slot_followup_also_retrieves_using_the_bare_active_topic():
    """A slot follow-up's resolved retrieval text mixes the active service
    with the attribute being asked for into one combined string. A
    dedicated retrieval pass using the active topic alone must also be
    attempted, so a service can still surface when the combined text's own
    embedding would have been diluted by the generic attribute wording."""
    from app.services.qa.question_answering import answer_qa_question

    captured_queries: list[str] = []

    class RecordingStore:
        chunk_count = 5

        def search(self, q, *, top_k=None, raw_k=None, user_role=None):
            captured_queries.append(q)
            return []

    history = [
        {"role": "user", "content": "Now tell me about Good Moral."},
        {"role": "assistant", "content": "The Issuance of Good Moral Certificate is handled by OSAS."},
    ]
    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=RecordingStore()),
        patch("app.services.qa.question_answering.generate_groq_answer", return_value="answer"),
    ):
        answer_qa_question("What are the requirements?", user_role="student", history=history)

    assert any("good moral" in q.casefold() for q in captured_queries)


# --- P1: an explicit service switch must not carry stale procedural context --


def test_explicit_service_switch_excludes_prior_topic_history_from_generation():
    """Reproduces the reported "Dropping steps mixed into TOR answer"
    contamination. On an explicit switch ("Now tell me about TOR." after a
    Dropping conversation), the LLM generation call must not receive the
    prior (Dropping) turns — retrieval/topic resolution are unaffected,
    only what reaches the generation prompt for *this* turn changes.
    """
    store = RoleAwareStore(
        [
            _chunk(
                "Issuance of Transcript of Records/Transfer Credentials",
                "Transcript of Records. Office / Division Registrar. Fees: PHP 75.00 / page.",
                score=3.0,
                extra_meta={"canonical_topic": "Issuance of Transcript of Records", "total_fees": "PHP 75.00 / page"},
            ),
        ]
    )
    history = [
        {"role": "user", "content": "How do I drop a subject?"},
        {"role": "assistant", "content": "Obtain a Dropping Form from the Registrar, get faculty and Dean "
                                          "approval, submit to the Registrar. Fee: P30.00."},
    ]
    captured: dict[str, object] = {}

    def fake_generate(*, question, context, broad_mode=False, history=None, grounding_notes=None, active_topic=None):
        captured["history"] = history
        return "The Registrar issues the Transcript of Records. The listed fee is PHP 75.00 per page."

    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch("app.services.qa.question_answering.generate_groq_answer", side_effect=fake_generate),
    ):
        result = answer_qa_question("Now tell me about TOR.", user_role="student", history=history)

    assert captured["history"] == []
    assert "drop" not in result.answer.casefold()
    assert "75" in result.answer


def test_non_switch_followup_keeps_full_history_for_generation():
    """The history-exclusion above must be scoped to the switch turn only —
    an ordinary slot follow-up in the same (now-updated) topic keeps full
    conversational continuity."""
    store = RoleAwareStore(
        [
            _chunk(
                "Issuance of Transcript of Records/Transfer Credentials",
                "Transcript of Records. Office / Division Registrar. Fees: PHP 75.00 / page.",
                score=3.0,
                extra_meta={"canonical_topic": "Issuance of Transcript of Records", "total_fees": "PHP 75.00 / page"},
            ),
        ]
    )
    history = [
        {"role": "user", "content": "How do I drop a subject?"},
        {"role": "assistant", "content": "Obtain a Dropping Form... Fee: P30.00."},
        {"role": "user", "content": "Now tell me about TOR."},
        {"role": "assistant", "content": "The Registrar issues the Transcript of Records. The listed fee is PHP 75.00 per page."},
    ]
    captured: dict[str, object] = {}

    def fake_generate(*, question, context, broad_mode=False, history=None, grounding_notes=None, active_topic=None):
        captured["history"] = history
        return "The fee is PHP 75.00 per page."

    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch("app.services.qa.question_answering.generate_groq_answer", side_effect=fake_generate),
    ):
        answer_qa_question("How much does it cost?", user_role="student", history=history)

    assert len(captured["history"]) == 4


# --- P1: bare service labels (including a minor typo) must prefer the -------
# --- authoritative service card over a same-named policy/handbook clause ---


@pytest.mark.parametrize(
    "question",
    ["good moral certificate", "good moral certificat", "Good Moral"],
)
def test_bare_good_moral_label_prefers_issuance_card_over_policy(question):
    """Root cause was not the typo itself: `prefer_service_chunks` only
    engaged its authoritative-card preference for question-shaped wording
    ("how much", "what are the requirements"). A bare label — typo or not —
    matched none of those patterns and fell through to plain semantic
    ranking, letting a same-named retention-policy handbook clause outrank
    the real issuance card. Fixed generically (any bare-named service whose
    card is present is preferred), not by pattern-matching this typo.
    """
    from app.services.qa.service_answer_formatter import prefer_service_chunks

    gm_card = _chunk(
        "Issuance of Good Moral Certificate (Undergraduate)",
        "Overview This service provides assistance for Issuance of Good Moral Certificate.",
        score=2.8,
        extra_meta={"document_type": "citizen_charter"},
    )
    gm_policy = _chunk(
        "Good Moral",
        "Retention Policies. Students must maintain good moral character.",
        score=3.0,
        extra_meta={"document_type": "handbook"},
    )
    preferred = prefer_service_chunks([gm_policy, gm_card], question=question)
    assert preferred[0].metadata["source_section"] == "Issuance of Good Moral Certificate (Undergraduate)"


def test_institutional_identity_topics_still_keep_handbook_ranking():
    """Guards the fix above from over-firing: a taxonomy entry that has no
    Citizen's Charter service card at all (e.g. "Vision, Mission, Goals" —
    an institutional-identity topic, not a service) must not have its
    handbook ranking overridden just because the bare name matches a
    taxonomy entry. Only engages when a candidate's own title actually is a
    service-procedure record for the named service.
    """
    from app.services.qa.service_answer_formatter import prefer_service_chunks

    vision = _chunk(
        "VISION",
        "VISION LSPU as a center of technology and innovation.",
        score=0.92,
        extra_meta={"document_type": "student_handbook"},
    )
    unrelated_service = _chunk(
        "LSPU Entrance Examination",
        "Entrance examination requirements.",
        score=0.7,
        extra_meta={"document_type": "citizen_charter", "article_type": "service_procedure"},
    )
    preferred = prefer_service_chunks([vision, unrelated_service], question="What is LSPU's vision?")
    assert preferred[0].metadata["source_section"] == "VISION"


# --- Safety pass: explicit, machine-readable active-service state ----------
#
# These exercise the client-carried, taxonomy-validated `active_service`
# architecture: the backend returns a canonical service identity every turn,
# a client may echo it back, and the backend prefers that validated value
# over scanning assistant prose (a fallback of last resort for clients that
# do not yet carry the new state). No office/service mapping is hardcoded —
# only the identity of *which service* is being discussed is carried; the
# office itself always comes from retrieved evidence.


def _enrollment_and_adjacent_store() -> RoleAwareStore:
    return RoleAwareStore(
        [
            _chunk(
                "Enrollment",
                "Enrollment. Office / Division Registrar. Fees: PHP 2,000.00.",
                score=3.0,
                extra_meta={"canonical_topic": "Enrollment", "office": "Registrar"},
            ),
            _chunk(
                "Entrance Examination",
                "Entrance Examination. Office / Division Admissions Office.",
                score=3.0,
                extra_meta={"canonical_topic": "Entrance Examination", "office": "Admissions Office"},
            ),
        ]
    )


def test_initial_service_question_establishes_machine_readable_active_service():
    """A fresh service question returns a validated, machine-readable
    ``active_service`` — not the raw question text, and not an ambiguous
    first-taxonomy-match guess."""
    from app.services.knowledge_taxonomy import validate_active_service_identity

    result = _ask(
        _enrollment_and_adjacent_store(),
        "How do I enroll as a new student?",
        groq_return="Go to the Registrar Office with your enrolment slip.",
    )
    assert result.active_service
    # Whatever is returned must itself be a real, re-validatable taxonomy name.
    assert validate_active_service_identity(result.active_service) == result.active_service


def test_five_plus_slot_followups_retain_the_client_carried_active_service():
    """Five-plus slot-only follow-ups, each simulating a real client that
    echoes back the validated active_service from the previous response,
    must retain the correct service throughout — this is the long-
    conversation case the sidecar reported failing."""
    store = _enrollment_and_adjacent_store()
    client_active_service = None
    history: list[dict] = []
    questions = [
        "How do I enroll as a new student?",
        "What documents do I need?",
        "Where do I submit them?",
        "How long does it take?",
        "How much does it cost?",
        "Which office handles that?",
    ]
    result = None
    for question in questions:
        result = _ask(
            store,
            question,
            history=history,
            client_active_service=client_active_service,
            groq_return="The Registrar's Office handles enrollment. Fee: PHP 2,000.00.",
        )
        history.append({"role": "user", "content": question})
        history.append({"role": "assistant", "content": result.answer})
        if result.active_service:
            client_active_service = result.active_service

    assert client_active_service == "Registration"
    assert "Enrollment" in " ".join(str(s.get("title") or "") for s in (result.sources or []))


def test_client_supplied_active_service_overrides_adversarial_assistant_prose():
    """The exact reported failure: a long Enrollment conversation whose
    history includes an assistant reply naming an adjacent service
    ("entrance examination and admission interview"). Without client
    state, prose-scanning could (and did, live) latch onto the wrong
    service. With a validated client-supplied active_service, prose
    scanning is bypassed entirely and the correct service is used.
    """
    store = _enrollment_and_adjacent_store()
    adversarial_history = [
        {"role": "user", "content": "How do I enroll as a new student?"},
        {"role": "assistant", "content": "New students must first complete the entrance examination and "
                                          "admission interview at the College before proceeding to "
                                          "Enrollment at the Registrar."},
    ]
    result = _ask(
        store,
        "Which office handles that?",
        history=adversarial_history,
        groq_return="The Registrar's Office handles that.",
    )
    # Backward-compat path (no client state): the corroboration guard from
    # the prior safety pass should still refuse to commit to the single,
    # uncorroborated "Entrance Examination" mention.
    assert not any(
        "Entrance Examination" in str(s.get("title") or "") for s in (result.sources or [])
    )

    from app.services.qa.question_answering import answer_qa_question

    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch("app.services.qa.question_answering.generate_groq_answer", return_value="The Registrar's Office handles that."),
    ):
        result_with_state = answer_qa_question(
            "Which office handles that?",
            user_role="student",
            history=adversarial_history,
            client_active_service="Registration",
        )
    titles = " ".join(str(s.get("title") or "") for s in (result_with_state.sources or []))
    assert "Enrollment" in titles
    assert "Entrance Examination" not in titles


def test_explicit_topic_switch_changes_the_machine_readable_active_service():
    """An explicit switch must replace even a validated client-supplied
    stale service, never the other way around."""
    from app.services.qa.question_answering import answer_qa_question

    store = RoleAwareStore(
        [
            _chunk(
                "Issuance of Transcript of Records/Transfer Credentials",
                "Transcript of Records. Fees: PHP 75.00 / page.",
                score=3.0,
                extra_meta={"canonical_topic": "Issuance of Transcript of Records", "total_fees": "PHP 75.00 / page"},
            ),
        ]
    )
    history = [
        {"role": "user", "content": "How do I drop a subject?"},
        {"role": "assistant", "content": "Obtain a Dropping Form... Fee: P30.00."},
    ]
    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch("app.services.qa.question_answering.generate_groq_answer", return_value="The Registrar issues the Transcript of Records."),
    ):
        result = answer_qa_question(
            "Now tell me about TOR.",
            user_role="student",
            history=history,
            client_active_service="Withdrawal",
        )
    assert result.active_service and "Transcript" in result.active_service


def test_followup_after_switch_keeps_the_new_service_as_client_state():
    """The turn right after an explicit switch must itself return the *new*
    service as active_service, so the client's next echoed value is
    already correct — it must not still carry the pre-switch service."""
    from app.services.qa.question_answering import answer_qa_question

    store = RoleAwareStore(
        [
            _chunk(
                "Issuance of Transcript of Records/Transfer Credentials",
                "Transcript of Records. Fees: PHP 75.00 / page.",
                score=3.0,
                extra_meta={"canonical_topic": "Issuance of Transcript of Records", "total_fees": "PHP 75.00 / page"},
            ),
        ]
    )
    history = [
        {"role": "user", "content": "How do I drop a subject?"},
        {"role": "assistant", "content": "Obtain a Dropping Form... Fee: P30.00."},
        {"role": "user", "content": "Now tell me about TOR."},
        {"role": "assistant", "content": "The Registrar issues the Transcript of Records. The listed fee is PHP 75.00 per page."},
    ]
    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch("app.services.qa.question_answering.generate_groq_answer", return_value="The fee is PHP 75.00 per page."),
    ):
        result = answer_qa_question(
            "How much does it cost?",
            user_role="student",
            history=history,
            client_active_service="Transcript of Records",
        )
    assert result.active_service and "Transcript" in result.active_service
    assert "75" in result.answer


def test_invalid_client_supplied_service_identity_is_safely_ignored():
    """Garbage, spoofed, or stale/removed client-supplied service values
    must never be trusted — they are rejected and the caller falls back to
    ordinary resolution (here: no history at all, so a safe clarification)."""
    from app.services.qa.question_answering import answer_qa_question

    store = _enrollment_and_adjacent_store()
    with patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store):
        result = answer_qa_question(
            "Which office handles that?",
            user_role="student",
            history=[],
            client_active_service="Totally Fake Service Nobody Registered",
        )
    assert result.fallback_reason == "underspecified_without_active_topic"


def test_oos_question_does_not_inherit_or_return_a_stale_active_service():
    """An out-of-scope question must not use a stale client-supplied
    service to answer, and must not echo one back either."""
    from app.services.qa.question_answering import answer_qa_question

    store = _enrollment_and_adjacent_store()
    with patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store):
        result = answer_qa_question(
            "What's the weather today?",
            user_role="student",
            client_active_service="Registration",
        )
    assert result.out_of_scope_detected is True
    assert result.active_service is None


# ---------------------------------------------------------------------------
# P0: complement-of-a-table-row inference must not be synthesized as a
# HIGH-confidence fact ("any grade above 69 is considered passing" from a
# row that only ever states "69 and below = Failed"). All fixtures below use
# a fabricated, non-LSPU "Device Certification" domain with a synthetic
# threshold number (50) so the regression proves the general algorithm, not
# a memorized institutional value. No numeric policy threshold is encoded in
# product code by this fix — only generic English status/direction words
# that were already part of the existing detector.
# ---------------------------------------------------------------------------

# Only the negative-status row states its own boundary ("50 and below");
# nothing else in the table mentions the adjacent number "51" at all, which
# is exactly the shape that let the real paraphrase slip through undetected
# (the previous fix only worked when some *other* row happened to contain
# the adjacent number by coincidence).
SYNTHETIC_ISOLATED_LOWER_BOUND_TABLE = """\
Device Certification Levels

Program Handbook > Article 9 > Device Certification > Sec. 2 > Certification Levels

Score Band Outcome
1.00 | 90-100 | Excellent
2.00 | 50 and below | Failed
"""

# Both sides of the same threshold are stated explicitly by two separate
# rows: the complement of "50 and below = Failed" is directly, textually
# given as "51 and above = Certified", not inferred.
SYNTHETIC_BOTH_SIDES_STATED_TABLE = """\
Device Certification Levels

Program Handbook > Article 9 > Device Certification > Sec. 2 > Certification Levels

1.00 | 51 and above | Certified
2.00 | 50 and below | Failed
"""

# A single Incomplete row alongside an ordinary passing band — nothing here
# states that *every other* row is Passing.
SYNTHETIC_SPECIAL_STATUS_TABLE = """\
Device Certification Levels

Program Handbook > Article 9 > Device Certification > Sec. 2 > Certification Levels

1.00 | 70-100 | Certified
INC | Incomplete
"""

# A positive (">=X = Passing") threshold with nothing else stating the
# below-threshold side explicitly, for the symmetric direction.
SYNTHETIC_ISOLATED_UPPER_BOUND_TABLE = """\
Device Certification Levels

Program Handbook > Article 9 > Device Certification > Sec. 2 > Certification Levels

1.00 | 51 and above | Certified
2.00 | 30-50 | Conditional
"""


@pytest.mark.parametrize(
    "inverted_answer",
    [
        "Any grade above 50 is considered passing.",
        "A device with a score greater than 50 is passing.",
        "A score of 51 and higher is passing.",
        "Anything over 50 is passing certification.",
    ],
    ids=[
        "azure-repro-above-n",
        "greater-than-n",
        "n-plus-1-and-higher",
        "anything-over-n",
    ],
)
def test_isolated_lower_bound_complement_paraphrases_are_caught(inverted_answer):
    """Reproduces the exact reported Azure failure shape ("any grade above
    69 is considered passing") with a synthetic number and an isolated
    "<=X = Failed" row that has no neighboring row mentioning the adjacent
    number. A "<=X = Failed" row alone must never authorize ">X = Passing",
    under any of the common paraphrasings of ">X"."""
    formatted = format_retrieved_context(
        [_chunk("Device Certification Levels", SYNTHETIC_ISOLATED_LOWER_BOUND_TABLE)]
    )
    records = _structured_table_records_from_text(formatted)
    assert records
    assert any(r.get("Status") == "Failed" for r in records)
    assert _answer_contradicts_table_records(inverted_answer, records)


def test_isolated_upper_bound_complement_paraphrases_are_caught():
    """Symmetric direction: a ">=X = Passing/Certified" row alone must not
    authorize "<X = Failed", under common paraphrasings of "<X", even when
    the adjacent number is never printed anywhere in the source table."""
    formatted = format_retrieved_context(
        [_chunk("Device Certification Levels", SYNTHETIC_ISOLATED_UPPER_BOUND_TABLE)]
    )
    records = _structured_table_records_from_text(formatted)
    assert records
    for inverted_answer in (
        "A score of 50 and below fails certification.",
        "A score of 50 or lower fails.",
        "Anything under 51 fails.",
    ):
        assert _answer_contradicts_table_records(inverted_answer, records), inverted_answer


def test_special_status_row_does_not_define_every_other_row():
    """One Incomplete/Conditional/special-status row must not be used to
    infer the status of every *other*, unlisted row — a different flavor of
    complement inference than a numeric boundary, with no number involved
    at all."""
    formatted = format_retrieved_context(
        [_chunk("Device Certification Levels", SYNTHETIC_SPECIAL_STATUS_TABLE)]
    )
    records = _structured_table_records_from_text(formatted)
    assert records
    assert _answer_contradicts_table_records(
        "INC means the record is Incomplete. Every other score is passing.",
        records,
    )
    assert _answer_contradicts_table_records(
        "Aside from Incomplete, all other results are considered successful.",
        records,
    )
    # A plain, correct restatement of the one row that IS labeled must not
    # be flagged just because the table also has other, unrelated rows.
    assert not _answer_contradicts_table_records(
        "INC means the record is Incomplete.",
        records,
    )


@pytest.mark.parametrize(
    "grounded_answer",
    [
        "Any grade above 50 is considered passing.",
        "A score of 50 and below fails, and 51 and above is certified.",
        "A score of 51 and higher is certified.",
    ],
)
def test_explicit_both_sides_summary_is_not_flagged(grounded_answer):
    """When the source table itself states both sides of a threshold across
    two rows (one "<=X = Failed", one ">X = Certified"), summarizing either
    or both sides is grounded, not an invented inference, and must not be
    flagged or downgraded."""
    formatted = format_retrieved_context(
        [_chunk("Device Certification Levels", SYNTHETIC_BOTH_SIDES_STATED_TABLE)]
    )
    records = _structured_table_records_from_text(formatted)
    assert records
    assert not _answer_contradicts_table_records(grounded_answer, records)


def test_azure_repro_phrase_end_to_end_is_corrected_and_capped():
    """End-to-end reproduction of the exact reported production failure
    (Azure returning HIGH confidence for a synthesized "any grade above 69
    is considered passing" claim), using a synthetic non-LSPU table and
    threshold number. The corrected answer must fall back to the grounded
    rows and confidence must not remain "high" for a generation the system
    had to override.
    """
    store = RoleAwareStore(
        [_chunk("Device Certification Levels", SYNTHETIC_ISOLATED_LOWER_BOUND_TABLE)]
    )
    result = _ask(
        store,
        "What is the passing score for device certification?",
        groq_return="Any grade above 50 is considered passing.",
    )
    assert "above 50 is considered passing" not in result.answer.casefold()
    assert "Failed" in result.answer
    assert result.confidence != "high"


def test_old_client_without_active_service_field_remains_safe():
    """A client that never sends ``client_active_service`` at all (the
    parameter's default) must behave exactly as before this change —
    falling back to the existing history-based resolution."""
    from app.services.qa.question_answering import answer_qa_question

    store = RoleAwareStore(
        [
            _chunk(
                "Enrollment",
                "Enrollment. Office / Division Registrar. Fees: PHP 2,000.00.",
                score=3.0,
                extra_meta={"canonical_topic": "Enrollment", "office": "Registrar"},
            ),
        ]
    )
    history = [
        {"role": "assistant", "content": "Go to the Registrar Office with your enrolment slip, "
                                          "good moral certificate, report card. Total processing time: 20 minutes."},
        {"role": "user", "content": "What documents do I need?"},
        {"role": "assistant", "content": "The required documents for Enrollment are: Enrolment Slip, "
                                          "Certificate of Good Moral Character, Report Card."},
        {"role": "user", "content": "How much does it cost?"},
        {"role": "assistant", "content": "The listed fee for Enrollment is PHP 2,000.00."},
    ]
    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch("app.services.qa.question_answering.generate_groq_answer", return_value="The Registrar's Office."),
    ):
        result = answer_qa_question("Which office handles that?", user_role="student", history=history)
    assert result.sources
    assert "Enrollment" in " ".join(str(s.get("title") or "") for s in result.sources)


# ---------------------------------------------------------------------------
# PROD-P0: carried active_service vs. a crowded, higher-scoring intruder pool
# (confirmed production failure on commit 059fd1a — see deploy/_prod_reprobe_enroll.py
# and deploy/_val_active_service_probe.py for the live-traffic reproduction this
# mirrors).
# ---------------------------------------------------------------------------


class _QueryAwareStore(RoleAwareStore):
    """``RoleAwareStore`` ranks purely by a fixed score, regardless of the
    query — fine for most fixtures, but it would make even the *initial*,
    unambiguous "How do I enroll...?" question retrieve the intruder first,
    which no real embedding search would do. This adds a small on-topic
    relevance bonus so a query that actually names a chunk's own title (the
    topic-setting turn's own wording) ranks it appropriately, while a vague
    follow-up with no such wording gets no such help — exactly mirroring why
    the active-topic constraint (not raw relevance) has to carry a vague
    slot follow-up like "Which office handles that?"."""

    def search(self, question, *, top_k=None, raw_k=None, user_role=None):
        self.calls.append(
            {"question": question, "top_k": top_k, "raw_k": raw_k, "user_role": user_role}
        )
        normalized_question = (question or "").casefold()

        def _effective_score(chunk: RetrievedChunk) -> float:
            title = (chunk.title or "").casefold()
            bonus = 5.0 if title[:6] and title[:6] in normalized_question else 0.0
            return chunk.rerank_score + bonus

        ranked = sorted(self.chunks, key=_effective_score, reverse=True)
        return select_role_visible_hits(ranked, user_role=user_role, top_k=top_k or 7)


def _crowded_enrollment_pool_with_examination_fee_intruder() -> RoleAwareStore:
    """A realistic crowded top-k: correct Enrollment/Registrar evidence plus
    several unrelated office/fee cards, one of which (Examination Fee, under
    Graduate Studies) outranks it by raw relevance score alone — the shape a
    vague "which office" query pulls from many charter entries that all
    carry generic office/fee wording."""
    return _QueryAwareStore(
        [
            _chunk(
                "Enrollment",
                "Enrollment. Office / Division Registrar. Fees: PHP 2,000.00. "
                "Requirements: Report Card, Certificate of Good Moral Character.",
                score=2.6,
                extra_meta={"canonical_topic": "Enrollment", "office": "Registrar"},
            ),
            _chunk(
                "Examination Fee",
                "Examination Fee. Office / Division: Office of the Dean, Graduate "
                "Studies. Fees: PHP 500.00 per examination.",
                score=4.9,
                extra_meta={
                    "canonical_topic": "Examination Fee",
                    "office": "Office of the Dean, Graduate Studies",
                },
            ),
            _chunk(
                "Library Reference Assistance",
                "Library Reference Assistance. Office / Division: Library. Fees: None.",
                score=4.2,
                extra_meta={"canonical_topic": "Library Reference Assistance", "office": "Library"},
            ),
            _chunk(
                "Issuance of Good Moral Certificate (Undergraduate)",
                "Issuance of Good Moral Certificate. Office / Division: OSA. Fees: None.",
                score=3.8,
                extra_meta={
                    "canonical_topic": "Issuance of Good Moral Certificate",
                    "office": "OSA",
                },
            ),
        ]
    )


def _run_enrollment_office_chain(
    store: RoleAwareStore,
    first_question: str,
    *,
    questions: list[str] | None = None,
) -> tuple[Any, str | None]:
    """Round-trips ``active_service`` the way the Flutter client does: echo
    back whatever the previous response returned as the next request's
    ``client_active_service``. ``questions`` lets a caller reproduce a
    specific real conversation shape; defaults to the original 6-turn chain."""
    history: list[dict] = []
    client_active_service: str | None = None
    result = None
    turns = questions if questions is not None else [
        first_question,
        "What documents do I need?",
        "Where do I submit them?",
        "How long does it take?",
        "How much does it cost?",
        "Which office handles that?",
    ]
    for question in turns:
        result = _ask(
            store,
            question,
            history=history,
            client_active_service=client_active_service,
            groq_return="The Registrar's Office handles Enrollment.",
        )
        history.append({"role": "user", "content": question})
        history.append({"role": "assistant", "content": result.answer})
        if result.active_service:
            client_active_service = result.active_service
    return result, client_active_service


@pytest.mark.parametrize(
    "first_question",
    ["How do I enroll?", "How do I enroll as a new student at LSPU?"],
)
def test_office_followup_keeps_carried_registration_against_crowded_examination_fee_pool(
    first_question,
):
    """The exact confirmed production failure: after establishing Registration
    through several ordinary Enrollment follow-ups (the client echoing back
    the validated active_service each turn, per the Flutter round-trip), a
    vague "Which office handles that?" turn must not let an unrelated,
    higher-scoring Examination Fee / Graduate Studies card replace the
    carried service, and must not drop it to ``None`` either. Covers both
    reported repro phrasings for the topic-setting turn."""
    store = _crowded_enrollment_pool_with_examination_fee_intruder()
    result, client_active_service = _run_enrollment_office_chain(store, first_question)
    titles = " ".join(str(s.get("title") or "") for s in (result.sources or []))
    assert client_active_service == "Registration"
    assert result.active_service == "Registration"
    assert "Enrollment" in titles
    assert "Examination Fee" not in titles


def test_exact_production_trigger_sequence_keeps_registration_through_fee_then_office():
    """Reproduces the real deployed turn sequence as closely as possible:
    a short topic-setting question, two ordinary Enrollment follow-ups,
    "Does it have a fee?" (a slot-attribute phrasing distinct from "How
    much does it cost?"), then the vague office follow-up — with the
    client echoing back the validated ``active_service`` on every turn,
    exactly as the Flutter app does.

    This intentionally does NOT reuse "How much does it cost?" (already
    correctly classified as a slot follow-up before this fix) so the test
    cannot pass merely because that phrasing was already handled — "Does it
    have a fee?" exercises a different, previously-unprotected turn that
    still had to fall through to the carried service correctly.
    """
    store = _crowded_enrollment_pool_with_examination_fee_intruder()
    questions = [
        "How do I enroll?",
        "What documents do I need?",
        "Where do I submit them?",
        "Does it have a fee?",
        "Which office handles that?",
    ]
    result, client_active_service = _run_enrollment_office_chain(
        store, questions[0], questions=questions
    )
    titles = " ".join(str(s.get("title") or "") for s in (result.sources or []))

    # Resolved active topic for the final turn is Registration, not a raw
    # sentence and not the intruder service.
    from app.services.qa.question_answering import resolve_turn_active_topic

    replay_history: list[dict] = []
    for question in questions[:-1]:
        replay_history.append({"role": "user", "content": question})
        replay_history.append({"role": "assistant", "content": "The Registrar's Office handles Enrollment."})
    resolved_topic = resolve_turn_active_topic(
        "Which office handles that?", replay_history, client_active_service="Registration"
    )
    assert resolved_topic == "Registration"

    # Enrollment evidence is retained/preferred; Examination Fee never
    # becomes the governing context.
    assert "Enrollment" in titles
    assert "Examination Fee" not in titles
    assert client_active_service == "Registration"
    assert result.active_service == "Registration"

    # The office answer is actually derived from Enrollment evidence: the
    # LLM is mocked (it always returns the same canned string, so the
    # *answer text* proves nothing on its own), so what matters is the
    # *context* it was grounded in for this exact final turn — it must
    # contain the Enrollment/Registrar evidence and must not contain the
    # Examination Fee intruder.
    captured_context: dict[str, str] = {}

    def _capture_context(**kwargs):
        captured_context["context"] = kwargs.get("context", "")
        return "The Registrar's Office handles Enrollment."

    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch(
            "app.services.qa.question_answering.generate_groq_answer",
            side_effect=_capture_context,
        ),
    ):
        from app.services.qa.question_answering import answer_qa_question

        final_result = answer_qa_question(
            "Which office handles that?",
            user_role="student",
            history=replay_history,
            client_active_service="Registration",
        )
    assert final_result.active_service == "Registration"
    assert "Enrollment" in captured_context.get("context", "")
    assert "Examination Fee" not in captured_context.get("context", "")


def test_explicit_switch_after_office_followup_still_overrides_carried_registration():
    """An explicit topic switch must still win over a stale carried
    Registration/active_service, even against the same crowded pool."""
    store = _crowded_enrollment_pool_with_examination_fee_intruder()
    store.chunks.append(
        _chunk(
            "Issuance of Transcript of Records",
            "Transcript of Records. Office / Division: Registrar. Fees: PHP 75.00/page.",
            score=3.5,
            extra_meta={
                "canonical_topic": "Issuance of Transcript of Records",
                "office": "Registrar",
            },
        )
    )
    history = [
        {"role": "user", "content": "How do I enroll as a new student at LSPU?"},
        {"role": "assistant", "content": "The Registrar's Office handles Enrollment."},
    ]
    result = _ask(
        store,
        "Now tell me about TOR.",
        history=history,
        client_active_service="Registration",
        groq_return="The Registrar issues the Transcript of Records.",
    )
    assert result.active_service and "Transcript" in result.active_service
    titles = " ".join(str(s.get("title") or "") for s in (result.sources or []))
    assert "Transcript" in titles


def test_invalid_client_active_service_against_crowded_pool_falls_back_safely():
    """A garbage/spoofed client value must not be trusted, and must not
    accidentally let the crowded pool's intruder win the office question
    either — history-based resolution still grounds retrieval correctly."""
    store = _crowded_enrollment_pool_with_examination_fee_intruder()
    history = [
        {"role": "user", "content": "How do I enroll as a new student at LSPU?"},
        {"role": "assistant", "content": "The Registrar's Office handles Enrollment."},
    ]
    result = _ask(
        store,
        "Which office handles that?",
        history=history,
        client_active_service="Totally Fake Service Nobody Registered",
        groq_return="The Registrar's Office handles Enrollment.",
    )
    titles = " ".join(str(s.get("title") or "") for s in (result.sources or []))
    assert "Examination Fee" not in titles


def test_oos_question_ignores_carried_registration_against_crowded_pool():
    """An out-of-scope question must not use a stale carried service to
    answer, and must not echo one back, even with a crowded pool present."""
    store = _crowded_enrollment_pool_with_examination_fee_intruder()
    result = _ask(store, "What's the weather today?", client_active_service="Registration")
    assert result.out_of_scope_detected is True
    assert result.active_service is None


def test_legacy_client_without_active_service_field_against_crowded_pool():
    """A pre-upgrade client that never sends ``active_service`` at all must
    still resolve the office question correctly via history-based
    resolution, even against the crowded intruder pool."""
    store = _crowded_enrollment_pool_with_examination_fee_intruder()
    history = [
        {"role": "assistant", "content": "Go to the Registrar Office with your enrolment slip, "
                                          "good moral certificate, report card."},
        {"role": "user", "content": "What documents do I need?"},
        {"role": "assistant", "content": "The required documents for Enrollment are: Enrolment Slip, "
                                          "Certificate of Good Moral Character, Report Card."},
        {"role": "user", "content": "How much does it cost?"},
        {"role": "assistant", "content": "The listed fee for Enrollment is PHP 2,000.00."},
    ]
    result = _ask(store, "Which office handles that?", history=history)
    titles = " ".join(str(s.get("title") or "") for s in (result.sources or []))
    assert "Examination Fee" not in titles


# ---------------------------------------------------------------------------
# General conversation-state / scope-boundary regression: a confirmed
# production failure where a SHORT, self-contained, out-of-scope question
# ("Who won the latest NBA game?") following a valid Enrollment/Registration
# conversation kept the stale active_service and reused Enrollment context
# instead of clearing to None. The root cause is generic, not NBA-specific:
# ``resolve_followup_question``'s word-count-only ``short_followup`` heuristic
# (<=8 words) misclassified ANY short standalone new-topic question as a
# follow-up whenever it had no explicit follow-up prefix or pronoun, and
# grafted the prior turn's resolved topic onto its retrieval text via
# "(Prior question context: ...)" — even though the question already named
# its own distinct subject. That injected text then made retrieval/scoring
# treat the stale service as relevant evidence for the new, unrelated
# question. None of these examples use sports/NBA wording, so the coverage
# below cannot pass merely by special-casing that one repro sentence.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "standalone_question",
    [
        "Who directs the newest Marvel movie?",
        "What is the boiling point of mercury?",
        "Who painted the Mona Lisa?",
        "What causes volcanic eruptions?",
    ],
)
def test_short_standalone_new_topic_question_does_not_graft_prior_context(standalone_question):
    """A short (<=8 word) question that already names its own subject must
    not have a prior conversational topic appended to its retrieval text,
    regardless of word count — this is the exact mechanism behind the
    confirmed production regression."""
    history = [
        {"role": "user", "content": "How do I enroll?"},
        {"role": "assistant", "content": "Go to the Registrar Office with your requirements."},
    ]
    resolved = resolve_followup_question(
        standalone_question, history, client_active_service="Registration"
    )
    assert resolved == standalone_question
    assert "Prior question context" not in resolved


@pytest.mark.parametrize(
    "starting_question,starting_answer,oos_question",
    [
        (
            "How do I enroll?",
            "Go to the Registrar Office with your requirements.",
            "Who directs the newest Marvel movie?",
        ),
        (
            "How do I get a Good Moral Certificate?",
            "Go to the OSA for a Good Moral Certificate.",
            "What is the boiling point of mercury?",
        ),
    ],
    ids=["from-registration", "from-good-moral"],
)
def test_confidently_oos_short_question_clears_stale_active_service(
    starting_question, starting_answer, oos_question
):
    """D & E: a confirmed-valid active_service from a prior turn (starting
    from two different services, so the fix is not Registration-specific)
    must not survive into a clearly unrelated, short, out-of-scope current
    question — the response must not keep echoing the stale service or its
    context as if it were relevant evidence, even though neither OOS example
    appears on any hardcoded keyword list."""
    store = RoleAwareStore(
        [
            _chunk(
                "Enrollment",
                "Enrollment. Office / Division Registrar. Fees: PHP 2,000.00.",
                score=3.0,
                # Hygiene-only reason (excluded from ``_positive_reasons``), not
                # the default subject-level "*_match" reasons ``_chunk()``
                # otherwise supplies — this simulates a chunk a real reranker
                # found no genuine topical support for.
                reasons=["boost_valid_source_metadata"],
                extra_meta={"canonical_topic": "Enrollment", "office": "Registrar"},
            )
        ]
    )
    history = [
        {"role": "user", "content": starting_question},
        {"role": "assistant", "content": starting_answer},
    ]
    result = _ask(
        store,
        oos_question,
        history=history,
        client_active_service="Registration",
        groq_return="I don't have information about that in the university knowledge base.",
    )
    assert result.active_service is None
    titles = " ".join(str(s.get("title") or "") for s in (result.sources or []))
    assert "Enrollment" not in titles


# ---------------------------------------------------------------------------
# Unsupported global range/category synthesis (distinct from the single-row
# complement-inference bug above). Several *individually* grounded table
# rows must not be synthesized into a broader global range, boundary, or
# category rule the source never states as a unit. All fixtures are
# synthetic and non-LSPU, spanning several unrelated domains (scholarship
# eligibility, fee tiers, device certification, filing deadlines) precisely
# so the fix is proven generic rather than tied to any one institution's
# grading policy. The real UNDERGRAD_GRADING_TABLE is exercised once at the
# end purely as a regression/reproduction case, not as the target of the fix.
# ---------------------------------------------------------------------------

SYNTHETIC_ELIGIBILITY_TABLE_ADJACENT = """\
Scholarship Eligibility Bands

Program Handbook > Article 5 > Scholarship Eligibility > Sec. 1 > Eligibility Bands

1.00 | 90-100 | Eligible
2.00 | 80-89 | Eligible
3.00 | 60-79 | Not Eligible
"""

SYNTHETIC_ELIGIBILITY_TABLE_GAP = """\
Scholarship Eligibility Bands

Program Handbook > Article 5 > Scholarship Eligibility > Sec. 1 > Eligibility Bands

1.00 | 90-100 | Eligible
2.00 | 60-70 | Eligible
3.00 | 0-59 | Not Eligible
"""

SYNTHETIC_FEE_TIER_TABLE = """\
Late Submission Fee Tiers

Program Handbook > Article 11 > Late Submission > Sec. 3 > Fee Tiers

1.00 | 1-5 | No Fee
2.00 | 6-10 | Standard Fee
3.00 | 11-20 | Standard Fee
4.00 | 21-30 | Premium Fee
"""

SYNTHETIC_CERT_WITH_PROBATION_TABLE = """\
Device Certification Bands

Program Handbook > Article 9 > Device Certification > Sec. 4 > Certification Bands

1.00 | 80-100 | Certified
2.00 | 65-79 | Probationary
3.00 | 50-64 | Certified
"""

SYNTHETIC_CERT_CLOSED_TOP_TABLE = """\
Device Certification Levels

Program Handbook > Article 9 > Device Certification > Sec. 5 > Certification Levels

1.00 | 80-100 | Certified
2.00 | 50-79 | Conditional
"""

SYNTHETIC_CERT_WITH_EXPLICIT_RULE_TABLE = """\
Device Certification Levels

Program Handbook > Article 9 > Device Certification > Sec. 5 > Certification Levels

1.00 | 80-100 | Certified
2.00 | 50-79 | Conditional
5.00 | 80 and above | Certified
"""

SYNTHETIC_DEADLINE_TABLE = """\
Appeal Filing Deadline Tiers

Program Handbook > Article 14 > Appeals > Sec. 2 > Filing Deadline Tiers

1.00 | 1-10 | On Time
2.00 | 11-15 | Grace Period
"""


def _records_for(table_text: str, title: str) -> list[dict[str, str]]:
    formatted = format_retrieved_context([_chunk(title, table_text)])
    records = _structured_table_records_from_text(formatted)
    assert records
    return records


def test_adjacent_same_status_rows_may_be_merged_when_coverage_is_complete():
    """Two rows sharing the same Status with no gap and nothing else between
    them are mechanically the same claim as one merged range — summarizing
    them together is grounded, not synthesized."""
    records = _records_for(SYNTHETIC_ELIGIBILITY_TABLE_ADJACENT, "Scholarship Eligibility Bands")
    assert not _answer_synthesizes_unsupported_range(
        "A score of 80 to 100 is Eligible.", records
    )
    assert not _answer_synthesizes_unsupported_range(
        "A score of 90-100 is Eligible, and 80-89 is also Eligible.", records
    )


def test_gap_between_same_status_ranges_prevents_global_merging():
    """The same two Eligible bands, but with an unaccounted-for gap between
    them (71-89 is simply absent from the table) — merging across that gap
    invents coverage the source never states."""
    records = _records_for(SYNTHETIC_ELIGIBILITY_TABLE_GAP, "Scholarship Eligibility Bands")
    assert _answer_synthesizes_unsupported_range(
        "A score of 60 to 100 is Eligible.", records
    )
    # Each row on its own remains fine.
    assert not _answer_synthesizes_unsupported_range(
        "A score of 90-100 is Eligible, and 60-70 is also Eligible.", records
    )


def test_different_statuses_are_not_merged_across_a_shared_boundary():
    """Adjacent Standard Fee bands may be merged, but the claim must not
    cross into the neighboring Premium Fee band just because it sits right
    next to them with no numeric gap."""
    records = _records_for(SYNTHETIC_FEE_TIER_TABLE, "Late Submission Fee Tiers")
    assert not _answer_synthesizes_unsupported_range(
        "A fee of 6 to 20 falls under the Standard Fee tier.", records
    )
    assert _answer_synthesizes_unsupported_range(
        "A fee of 6 to 30 falls under the Standard Fee tier.", records
    )


def test_special_status_row_is_not_absorbed_into_a_broad_normal_range():
    """A Probationary band sits between two Certified bands. Claiming the
    full 50-100 span is Certified would silently absorb the special row
    between them — the two Certified bands must stay separate spans."""
    records = _records_for(SYNTHETIC_CERT_WITH_PROBATION_TABLE, "Device Certification Bands")
    assert _answer_synthesizes_unsupported_range(
        "A score of 50 to 100 is Certified.", records
    )
    assert not _answer_synthesizes_unsupported_range(
        "A score of 80-100 is Certified, and 50-64 is also Certified, "
        "but 65-79 is Probationary.",
        records,
    )


@pytest.mark.parametrize(
    "unbounded_claim",
    ["80 and above is Certified.", "A score above 79 is Certified.", "A score of 80 or higher is Certified."],
)
def test_individually_supported_rows_do_not_create_an_unsupported_overall_boundary(
    unbounded_claim,
):
    """Only a closed 80-100 Certified band is stated. Nothing in the table
    says there is no ceiling — claiming an open-ended "80 and above" rule
    invents a global boundary the individual row never asserted."""
    records = _records_for(SYNTHETIC_CERT_CLOSED_TOP_TABLE, "Device Certification Levels")
    assert _answer_synthesizes_unsupported_range(unbounded_claim, records)


def test_explicit_source_rule_row_authorizes_the_same_global_summary():
    """Same table as above, but the source itself also carries an explicit
    "80 and above = Certified" row alongside the granular bands. That row
    is itself directly-supported evidence, so restating it is not a
    synthesized inference."""
    records = _records_for(SYNTHETIC_CERT_WITH_EXPLICIT_RULE_TABLE, "Device Certification Levels")
    assert not _answer_synthesizes_unsupported_range("80 and above is Certified.", records)
    assert not _answer_synthesizes_unsupported_range("A score above 79 is Certified.", records)


def test_deadline_tiers_different_statuses_are_not_merged():
    """A different, unrelated domain (filing deadlines): an On Time band and
    a Grace Period band sit right next to each other, but must not be
    summarized together as a single uniform rule."""
    records = _records_for(SYNTHETIC_DEADLINE_TABLE, "Appeal Filing Deadline Tiers")
    assert _answer_synthesizes_unsupported_range(
        "A submission made on day 1-15 is On Time.", records
    )
    assert not _answer_synthesizes_unsupported_range(
        "A submission made on day 1-10 is On Time.", records
    )


def test_synthesized_range_end_to_end_is_corrected_and_capped():
    """End-to-end (synthetic domain): the model merges two differently
    labeled fee bands into one overstated claim. The corrected answer must
    fall back to the grounded per-row evidence, and confidence must not
    remain "high" for a generation the system had to override."""
    store = RoleAwareStore(
        [_chunk("Late Submission Fee Tiers", SYNTHETIC_FEE_TIER_TABLE)]
    )
    result = _ask(
        store,
        "What fee applies to a late submission?",
        groq_return="A fee of 6 to 30 falls under the Standard Fee tier.",
    )
    assert "6 to 30 falls under the Standard Fee" not in result.answer
    assert "Premium Fee" in result.answer
    assert result.confidence != "high"


def test_grading_table_global_range_synthesis_repro():
    """Reproduction/regression case only (not the implementation target):
    the real LSPU grading table has several rows with no Status label at
    all (e.g. 87-89 is the only row actually labeled Satisfactory; 84-86
    and 90-92 carry no label). An answer must not stretch "Satisfactory"
    across those unlabeled neighboring rows into one merged range."""
    records = _records_for(UNDERGRAD_GRADING_TABLE, "Grading System")
    assert _answer_synthesizes_unsupported_range(
        "A grade from 84 to 92 is Satisfactory.", records
    )
    # Restating each row on its own remains fine.
    assert not _answer_synthesizes_unsupported_range(
        "1.00 (99-100) is Excellent. 1.50 (93-95) is Very Satisfactory. "
        "2.00 (87-89) is Satisfactory.",
        records,
    )


# ---------------------------------------------------------------------------
# LIVE-P0: live-generation mixed-status global synthesis escape.
#
# Root cause: the post-generation audit had two independent gaps that only
# show up together, not in isolation, which is why the earlier synthetic
# unit fixtures (all single-axis, all reusing the record's own exact number
# string) never exercised them:
#
#   1. Number matching was compared as *exact strings* pulled straight out
#      of regex captures ("4.00" vs a paraphrase written as "4.0" or "4")
#      never matched, even though they are the same value. A generated
#      answer trimming a trailing zero silently defeated every number-based
#      check.
#   2. A table can carry *two independent numeric axes on the same rows* — a
#      Range (e.g. a percentage band) and a separate Identifier code (e.g. a
#      grade point), moving in *opposite* directions of "better". The old
#      merge/authorization logic only ever reasoned about one shared number
#      line built out of both fields at once, so an Identifier-axis claim
#      ("4.00 and above", where a *larger* code is worse) could silently be
#      checked against Range-axis evidence (or nothing at all) instead of
#      against the other Identifier-axis rows it actually needed to agree
#      with.
#
# Separately, the blunt whole-answer "and above" guard is defeated the
# moment *any* row anywhere states an unrelated "X and above" rule (a
# realistic shape for a real institutional document, which the short
# synthetic fixtures never included) — at that point only the per-row
# marker/number matching stood between the claim and going unchecked, and
# that is exactly where gap #1 and #2 above hid.
#
# Fix: numbers are now compared as parsed floats throughout, and the
# Identifier axis is evaluated as its own independent axis (point coverage,
# no gap tolerance — an institution's own code list is a discrete set, not a
# continuous scale) alongside the Range axis (interval spans, gap-aware) —
# each claim is checked against whichever axis its own numbers plausibly
# belong to, using either the table's literal Status wording or, when the
# answer instead uses generic English pass/fail language the table itself
# never spells out, the same general polarity vocabulary already used for
# the single-row complement check.
#
# All fixtures below are synthetic ("Widget..."), reproducing the *shape* of
# the reported live failure with fabricated labels/values, never LSPU's
# grading policy or its exact numbers.
# ---------------------------------------------------------------------------

SYNTHETIC_MIXED_STATUS_BANDS = """\
Widget Status Bands

Program Handbook > Article 6 > Widget Status > Sec. 1 > Widget Status Bands

1.00 | 80-100 | Normal
2.00 | 60-79 | Conditional
3.00 | 0-59 | Failed
"""

# Two independent numeric axes on the same rows: a Range (percentage,
# larger = better) and an Identifier code (grade-point style, larger =
# worse) — the exact shape that let a claim phrased on the Identifier axis
# ("3.00 and above") go unchecked against Range-axis-only reasoning. The
# extra explicit "80 and above | Merit Recognition" row is itself a real,
# legitimate rule the source states — its presence is what defeats the
# blunt whole-answer "and above" guard, which is what let the reported live
# answer through in the first place.
SYNTHETIC_TWO_AXIS_RUBRIC = """\
Widget Grading Rubric

Program Handbook > Article 4 > Widget Grading Rubric > Sec. 1 > Widget Grading Rubric

1.00 | 90-100 | Excellent
2.00 | 75-89 | Good
3.00 | 60-74 | Conditional
4.00 | 59 and below | Failed
80 and above | Merit Recognition
"""


def test_mixed_status_rows_reject_a_through_c_merge():
    """A → Normal, B → Conditional, C → Failed: a claim spanning all three
    bands as one uniform "Normal" outcome must be rejected — the middle and
    tail bands carry different, worse statuses the claim silently erases."""
    records = _records_for(SYNTHETIC_MIXED_STATUS_BANDS, "Widget Status Bands")
    assert _answer_synthesizes_unsupported_range("A score of 0 to 100 is Normal.", records)
    assert _answer_synthesizes_unsupported_range(
        "Scores from 0 through 100 are Normal.", records
    )


def test_open_ended_claim_blocked_when_trailing_rows_are_special_status():
    """"B and above are Normal" must be rejected once the Conditional band
    sits inside that open-ended span — an unbounded claim is only as good as
    every row it actually reaches, not just the row nearest its edge."""
    records = _records_for(SYNTHETIC_MIXED_STATUS_BANDS, "Widget Status Bands")
    assert _answer_synthesizes_unsupported_range("A score of 60 and above is Normal.", records)
    # The narrower, actually-supported closed claim remains fine (the table
    # never states an open-ended "80 and above" rule, only a closed 80-100
    # band, so an unbounded claim still would not be authorized).
    assert not _answer_synthesizes_unsupported_range("A score of 80 to 100 is Normal.", records)


def test_direct_row_contradiction_is_blocked():
    """A generated summary must not assign a status that contradicts any
    single covered row on its own, independent of any merging at all."""
    records = _records_for(SYNTHETIC_MIXED_STATUS_BANDS, "Widget Status Bands")
    assert _answer_synthesizes_unsupported_range("A score of 60-79 is Normal.", records)


def test_all_contiguous_covered_rows_sharing_status_remains_allowed():
    """The positive control: when every row a claim actually spans agrees on
    the same status with no gap and nothing special between them, the merge
    is grounded, not synthesized."""
    records = _records_for(SYNTHETIC_MIXED_STATUS_BANDS, "Widget Status Bands")
    assert not _answer_synthesizes_unsupported_range("A score of 80 to 100 is Normal.", records)


def test_azure_shape_two_axis_parenthetical_claim_is_blocked():
    """Reproduces the exact semantic shape of the reported live failure —
    a claim phrased on a grade-point-style Identifier axis, with a
    parenthetical citing the specific bands it silently merges, using a
    generic "passing" claim the table's own Status column never spells out
    literally (only "Excellent", "Good", "Conditional", "Failed") — with
    entirely synthetic labels and numbers, not LSPU's grading policy.
    """
    records = _records_for(SYNTHETIC_TWO_AXIS_RUBRIC, "Widget Grading Rubric")
    bad = "Codes of 3.00 and above (60-74 and 4.00) represent passing outcomes."
    assert _answer_synthesizes_unsupported_range(bad, records)
    # A paraphrase dropping the trailing zero (the exact live paraphrase
    # shape) must be caught identically — numbers are compared by value.
    assert _answer_synthesizes_unsupported_range(
        "A code of 3.0 and above represents a passing outcome overall.", records
    )
    # The correctly-bounded claim over the genuinely non-negative codes
    # remains fine.
    good = "Codes of 1.00 and above (90-100 and 2.00, 75-89) represent passing outcomes."
    assert not _answer_synthesizes_unsupported_range(good, records)


def test_azure_shape_old_marker_matching_alone_was_blind_to_the_paraphrase():
    """Documents the actual root cause: once the table states any unrelated
    explicit "X and above" rule (a realistic shape for a real institutional
    document), the blunt whole-answer guard in
    ``_answer_contradicts_table_records`` is defeated, and a paraphrase that
    drops the matching row's own exact number string ("3.0" instead of
    "3.00") also defeats that function's per-row literal/number matching —
    this is why the earlier synthetic unit tests (which always reused a
    row's exact number string) never exposed the gap. The new merge-aware,
    axis-aware, value-based checker below is what actually closes it."""
    records = _records_for(SYNTHETIC_TWO_AXIS_RUBRIC, "Widget Grading Rubric")
    paraphrase = "A code of 3.0 and above represents a passing outcome overall."
    assert not _answer_contradicts_table_records(paraphrase, records)
    assert _answer_synthesizes_unsupported_range(paraphrase, records)


def test_explicit_global_rule_row_with_generic_passing_wording_is_allowed():
    """When the source itself explicitly states the combined rule as its own
    row — even phrased with the same generic "passing" wording the rest of
    the table never uses — restating it is grounded, not synthesized, and a
    *different*, unstated boundary must still be rejected."""
    table = UNDERGRAD_GRADING_TABLE + "75 and above | Passing\n"
    records = _records_for(table, "Grading System")
    assert not _answer_synthesizes_unsupported_range(
        "Grades of 75 and above represent passing outcomes.", records
    )
    assert _answer_synthesizes_unsupported_range(
        "Grades of 70 and above represent passing outcomes.", records
    )


def test_azure_shape_end_to_end_is_corrected_and_capped():
    """End-to-end (synthetic domain): the model produces the same semantic
    shape as the reported live failure — a two-axis table, an unrelated
    explicit "and above" rule elsewhere in the source, and a paraphrase that
    drops a row's exact number string. The corrected answer must fall back
    to grounded row-by-row evidence, and confidence must not remain "high"
    for a generation the system had to override."""
    store = RoleAwareStore([_chunk("Widget Grading Rubric", SYNTHETIC_TWO_AXIS_RUBRIC)])
    result = _ask(
        store,
        "What is the passing code for the widget grading rubric?",
        groq_return="A code of 3.0 and above represents a passing outcome overall.",
    )
    assert "3.0 and above" not in result.answer
    assert "Failed" in result.answer or "Conditional" in result.answer
    assert result.confidence != "high"


# ---------------------------------------------------------------------------
# SEMANTIC RANGE-STATUS CONTRADICTION GUARD (Azure re-certification follow-up).
#
# Root cause: the live paraphrase "grades at or above 4.00 represent passing
# performance ... while anything below 4.00 falls into the failed categories"
# still escaped the merge/axis-aware checker above. That checker was already
# axis-aware and wording-tolerant for "N and above"/"above N" — but the
# *boundary arithmetic* itself assumed every axis steps by whole numbers:
# an exclusive edge ("above N"/"below N") was converted to a synthetic
# "N + 1"/"N - 1" inclusive edge before checking coverage. That assumption
# holds for whole-number percentage bands (the only shape the earlier
# fixtures used), but a grade-point-style identifier axis is commonly spaced
# in quarters (...3.50, 3.75, 4.00...). "at or above 4.00" additionally
# matched the *strict* "above" pattern (it contains the substring "above
# 4.00"), so it was treated as excluding 4.00 and shifted to "5.00 and
# above" — a number with no row anywhere near it — so the check found
# nothing to compare against and passed the claim through unexamined.
# "anything below 4.00" was symmetrically shifted down to "3.00 and below",
# skipping every real row strictly between 3.00 and 4.00.
#
# Fix: an excluded edge is now carried through as-is and resolved against
# the source's own actual boundary values (the nearest real value on that
# side), never a hardcoded step — and "at or above"/"at or below" are
# recognized as their own, already-inclusive phrasing so they are never
# routed through the exclusive-edge path at all. All fixtures below are
# synthetic, reproducing only the *shape* of the reported failure.
# ---------------------------------------------------------------------------

SYNTHETIC_FRACTIONAL_RATING_TABLE = """\
Widget Reliability Rating

Program Handbook > Article 7 > Widget Reliability > Sec. 2 > Reliability Rating Codes

1.00 | | Excellent
1.25 | | Excellent
1.50 | | Very Good
1.75 | | Very Good
2.00 | | Good
2.25 | | Good
2.50 | | Satisfactory
2.75 | | Satisfactory
3.00 | | Fair
3.25 | | Fair
3.50 | | Conditional Failure
3.75 | | Conditional Failure
4.00 | | Conditional Failure
"""

SYNTHETIC_REQUEST_APPROVAL_TABLE = """\
Request Processing Status Tiers

Program Handbook > Article 12 > Request Processing > Sec. 2 > Processing Status Tiers

1.00 | 1-7 | Approved
2.00 | 8-14 | Pending
3.00 | 15-30 | Denied
"""


@pytest.mark.parametrize(
    "paraphrase",
    [
        "3.00 and above is passing.",
        "at or above 3.00 represents a passing status.",
        "The practical interpretation is that a rating of 3.00 and above is passing.",
        "Anything from 3.00 upward is passing.",
        "Values of 3.00 or greater count as passing.",
    ],
    ids=[
        "and-above",
        "at-or-above",
        "practical-interpretation-and-above",
        "from-upward",
        "or-greater",
    ],
)
def test_fractional_axis_above_paraphrases_all_rejected(paraphrase):
    """Five different phrasings of the exact same semantic claim ("3.00 and
    above is passing") on a quarter-point identifier axis where 3.50-4.00 are
    all "Conditional Failure". Every wording must be rejected identically —
    the guard must key off the claimed region and status, not the surface
    phrase used to state it. "at or above 3.00" is the exact shape of the
    reported live escape: the old code shifted its excluded edge to a number
    the table never uses and let it through.
    """
    records = _records_for(SYNTHETIC_FRACTIONAL_RATING_TABLE, "Widget Reliability Rating")
    assert _answer_synthesizes_unsupported_range(paraphrase, records)


@pytest.mark.parametrize(
    "paraphrase",
    ["Anything below 3.75 is passing.", "A rating less than 3.75 is passing."],
    ids=["below", "less-than"],
)
def test_fractional_axis_below_paraphrases_all_rejected(paraphrase):
    """The inverse direction of the same bug: "below 3.75" excludes 3.75
    itself, so the nearest real row it actually reaches is 3.50 — still
    "Conditional Failure". The old "N - 1" shortcut would have landed on
    2.75, silently skipping the 3.50/3.75 rows entirely."""
    records = _records_for(SYNTHETIC_FRACTIONAL_RATING_TABLE, "Widget Reliability Rating")
    assert _answer_synthesizes_unsupported_range(paraphrase, records)


def test_fractional_axis_correctly_bounded_claims_remain_allowed():
    """Positive controls on the same fractional axis: a claim that only ever
    reaches genuinely same-status rows is still allowed, whether phrased as
    an inclusive upper bound ("up to") or an explicit closed range
    ("between"), and restating each row individually is always fine."""
    records = _records_for(SYNTHETIC_FRACTIONAL_RATING_TABLE, "Widget Reliability Rating")
    assert not _answer_synthesizes_unsupported_range("Ratings up to 3.25 are passing.", records)
    assert not _answer_synthesizes_unsupported_range(
        "Ratings between 1.00 and 2.75 are passing.", records
    )
    assert not _answer_synthesizes_unsupported_range(
        "1.00 is Excellent. 1.25 is Excellent. 1.50 is Very Good.", records
    )
    # The same "between" phrasing must still be rejected once its span
    # actually reaches a conflicting row.
    assert _answer_synthesizes_unsupported_range(
        "Ratings between 3.00 and 4.00 are passing.", records
    )


def test_explicit_source_rule_row_authorizes_at_or_above_phrasing_too():
    """The explicit-open-row authorization already proven for "above N" must
    hold identically for the newer "at or above N" phrasing — the same
    grounded row, a different paraphrase of the same inclusive edge."""
    records = _records_for(SYNTHETIC_CERT_WITH_EXPLICIT_RULE_TABLE, "Device Certification Levels")
    assert not _answer_synthesizes_unsupported_range("A score at or above 80 is Certified.", records)


@pytest.mark.parametrize(
    "table_text, title, claim",
    [
        (
            SYNTHETIC_ELIGIBILITY_TABLE_ADJACENT,
            "Scholarship Eligibility Bands",
            "Scores at or above 80 are Eligible.",
        ),
        (
            SYNTHETIC_ELIGIBILITY_TABLE_GAP,
            "Scholarship Eligibility Bands",
            "Scores between 60 and 100 are Eligible.",
        ),
        (
            SYNTHETIC_FEE_TIER_TABLE,
            "Late Submission Fee Tiers",
            "Late submissions up to 20 days fall under the Standard Fee tier.",
        ),
        (
            SYNTHETIC_FEE_TIER_TABLE,
            "Late Submission Fee Tiers",
            "Late submissions from 6 upward fall under the Standard Fee tier.",
        ),
        (
            SYNTHETIC_REQUEST_APPROVAL_TABLE,
            "Request Processing Status Tiers",
            "Requests processed at or above 8 days are Pending.",
        ),
        (
            SYNTHETIC_REQUEST_APPROVAL_TABLE,
            "Request Processing Status Tiers",
            "Requests processed up to 7 days are Approved.",
        ),
    ],
    ids=[
        "eligibility-at-or-above-open-ceiling",
        "eligibility-between-across-gap",
        "fee-tier-up-to",
        "fee-tier-from-upward",
        "approval-at-or-above-open-ceiling",
        "approval-up-to-open-floor",
    ],
)
def test_non_grade_domains_reject_the_same_paraphrase_shapes(table_text, title, claim):
    """The same claimed-region-vs-covered-rows invariant, in domains that
    have nothing to do with grading: scholarship eligibility, a late fee
    schedule, and a request-approval status tier. Each claim here either
    reaches beyond the domain's own stated ceiling/floor or bridges an
    unstated gap — never a grade, never a hardcoded threshold number."""
    records = _records_for(table_text, title)
    assert _answer_synthesizes_unsupported_range(claim, records)


def test_non_grade_domains_row_accurate_claims_remain_allowed():
    """Positive controls in the same non-grade domains: a claim bounded to
    exactly what the source states, phrased with the newer "between"/"up
    to" wording, is still allowed."""
    eligibility = _records_for(SYNTHETIC_ELIGIBILITY_TABLE_ADJACENT, "Scholarship Eligibility Bands")
    assert not _answer_synthesizes_unsupported_range(
        "Scores between 80 and 100 are Eligible.", eligibility
    )
    deadline = _records_for(SYNTHETIC_DEADLINE_TABLE, "Appeal Filing Deadline Tiers")
    assert not _answer_synthesizes_unsupported_range(
        "A submission made between 1 and 10 days is On Time.", deadline
    )
    approval = _records_for(SYNTHETIC_REQUEST_APPROVAL_TABLE, "Request Processing Status Tiers")
    assert not _answer_synthesizes_unsupported_range(
        "Requests processed between 1 and 7 days are Approved.", approval
    )


# ---------------------------------------------------------------------------
# MIXED-STATUS STRUCTURED-EVIDENCE FALLBACK (Azure re-certification, round 3).
#
# Root cause: every guard above only ever fires once a generated sentence
# matches a *recognized* comparison phrasing (a fixed regex list — "above",
# "below", "at or above", "up to", ...) and that specific, parsed claim is
# then proven wrong. That is precisely why the same live escape kept
# resurfacing under a new wording each time: a phrasing that matches none of
# the recognized patterns is silently skipped by *both* checkers above (their
# loops over "the claims this clause makes" simply never execute), not
# merely mis-evaluated. Chasing this by adding another pattern every time a
# new paraphrase is reported is unbounded — natural language has no fixed
# list of ways to say "greater than".
#
# Fix: a new policy-level guard, ``_answer_has_unverifiable_mixed_status_claim``,
# changes the default for one specific, high-risk evidence shape: once the
# structured source carries more than one distinct Status, a sentence
# asserting a status must be *affirmatively proven* grounded — via a
# recognized phrasing (reusing the exact same checks as above) or, failing
# that, via the plain numbers the sentence itself contains — rather than
# merely not-yet-disproven. A sentence with no recognized phrasing and no
# usable number to anchor it is denied outright. This never depends on
# knowing what a new comparison word means, so it needs no expansion when
# the next paraphrase shows up.
# ---------------------------------------------------------------------------

SYNTHETIC_ABC_DIAGNOSTIC_TABLE = """\
Widget Diagnostic Codes

Program Handbook > Article 6 > Widget Diagnostics > Sec. 1 > Diagnostic Codes

1.00 | | Normal
2.00 | | Conditional
3.00 | | Failed
"""

SYNTHETIC_SINGLE_STATUS_TABLE = """\
Widget Compliance Codes

Program Handbook > Article 6 > Widget Diagnostics > Sec. 2 > Compliance Codes

1.00 | | Compliant
2.00 | | Compliant
3.00 | | Compliant
"""



def test_mixed_status_abc_reproduction_values_below_b_are_normal():
    """The exact reproduction shape requested: rows A -> Normal, B ->
    Conditional, C -> Failed. A generated claim merging A and B together as
    "Normal" must be rejected by the policy guard regardless of the specific
    comparison wording used."""
    records = _records_for(SYNTHETIC_ABC_DIAGNOSTIC_TABLE, "Widget Diagnostic Codes")
    assert _answer_has_unverifiable_mixed_status_claim(
        "Values below 3.00 are Normal.", records
    )
    assert _answer_has_unverifiable_mixed_status_claim(
        "Values of 2.00 and below are Normal.", records
    )


@pytest.mark.parametrize(
    "paraphrase",
    [
        "Widget codes shy of 3.00 are passing.",
        "Widget codes south of 3.00 are passing.",
        "Widget codes north of the halfway mark are passing.",
        "Codes past 2 are passing.",
    ],
    ids=["shy-of", "south-of", "no-numeric-anchor", "bare-integer-past"],
)
def test_unrecognized_paraphrases_are_denied_by_default(paraphrase):
    """None of these phrasings match any comparison pattern this module
    recognizes ("shy of", "south of", "north of the halfway mark", a bare
    integer where the table's own numbers carry decimals) — proving the
    point of the policy guard: it does not need to recognize the wording to
    deny it. Two of these are not caught by either older checker at all,
    which is exactly the gap this guard closes."""
    records = _records_for(SYNTHETIC_ABC_DIAGNOSTIC_TABLE, "Widget Diagnostic Codes")
    assert _answer_has_unverifiable_mixed_status_claim(paraphrase, records)


def test_unrecognized_paraphrases_slip_past_the_older_checkers_alone():
    """Documents the actual gap: these two phrasings are not flagged by
    either pre-existing checker on their own — only the new policy guard
    catches them, because it does not depend on recognizing the specific
    comparison wording used."""
    records = _records_for(SYNTHETIC_ABC_DIAGNOSTIC_TABLE, "Widget Diagnostic Codes")
    for paraphrase in (
        "Widget codes north of the halfway mark are passing.",
        "Codes past 2 are passing.",
    ):
        assert not _answer_contradicts_table_records(paraphrase, records)
        assert not _answer_synthesizes_unsupported_range(paraphrase, records)
        assert _answer_has_unverifiable_mixed_status_claim(paraphrase, records)


def test_row_by_row_facts_remain_allowed_under_the_policy():
    """The policy denies unanchored or multi-row-spanning synthesis, but a
    plain restatement of each row's own fact — however many rows are
    listed, one at a time — is always allowed."""
    records = _records_for(SYNTHETIC_ABC_DIAGNOSTIC_TABLE, "Widget Diagnostic Codes")
    assert not _answer_has_unverifiable_mixed_status_claim("1.00 is Normal.", records)
    assert not _answer_has_unverifiable_mixed_status_claim(
        "1.00 is Normal. 2.00 is Conditional. 3.00 is Failed.", records
    )


def test_explicit_combined_rule_row_still_allows_a_global_summary():
    """When the source itself carries an explicit combined-rule row ("80 and
    above = Certified"), restating that rule is grounded — it is not a
    separate case the policy special-cases, just one more row a claim can
    be checked against, the same as any granular one. Reuses the same
    two-band-plus-explicit-row fixture already proven for the
    ``_answer_synthesizes_unsupported_range`` checker above."""
    records = _records_for(SYNTHETIC_CERT_WITH_EXPLICIT_RULE_TABLE, "Device Certification Levels")
    assert not _answer_has_unverifiable_mixed_status_claim(
        "A score at or above 80 is Certified.", records
    )
    # An entirely unrecognized phrasing of the same, explicitly-stated rule
    # must be allowed too — grounding does not depend on matching a pattern.
    assert not _answer_has_unverifiable_mixed_status_claim(
        "Scores clocking in past 80 are Certified.", records
    )
    # A different, unstated boundary is still denied.
    assert _answer_has_unverifiable_mixed_status_claim(
        "A score at or above 55 is Certified.", records
    )


def test_single_status_table_is_never_subject_to_the_policy():
    """A table where every row shares the same Status has nothing for a
    generated answer to get wrong by generalizing across rows — the policy
    must not fire there even for an entirely unrecognized phrasing."""
    records = _records_for(SYNTHETIC_SINGLE_STATUS_TABLE, "Widget Compliance Codes")
    assert not _answer_has_unverifiable_mixed_status_claim(
        "Widget codes north of the halfway mark are passing.", records
    )
    assert not _answer_has_unverifiable_mixed_status_claim(
        "Any code from 1.00 and up is Compliant.", records
    )


@pytest.mark.parametrize(
    "table_text, title, claim",
    [
        (
            SYNTHETIC_ELIGIBILITY_TABLE_ADJACENT,
            "Scholarship Eligibility Bands",
            "Eligible status is said to cover the zone bounded by 60 and 100.",
        ),
        (
            SYNTHETIC_REQUEST_APPROVAL_TABLE,
            "Request Processing Status Tiers",
            "Requests past the one-week mark are Pending.",
        ),
        (
            SYNTHETIC_CERT_WITH_PROBATION_TABLE,
            "Device Certification Bands",
            "Devices south of a 65 score are Certified.",
        ),
        (
            SYNTHETIC_DEADLINE_TABLE,
            "Appeal Filing Deadline Tiers",
            "Filings past the first ten days are still On Time.",
        ),
        (
            SYNTHETIC_FEE_TIER_TABLE,
            "Late Submission Fee Tiers",
            "The Standard Fee is said to cover the zone bounded by 6 and 30.",
        ),
    ],
    ids=["eligibility", "approval", "certification", "deadline", "fee-tier"],
)
def test_non_grade_domains_deny_unrecognized_paraphrases_too(table_text, title, claim):
    """The same policy, in domains that have nothing to do with grading:
    eligibility, request approval, device certification, filing deadlines,
    and a late fee schedule. None of these phrasings ("bounded by X and Y",
    "past the one-week mark", "south of") match any recognized comparison
    pattern — the guard denies them anyway because the numbers they do
    contain span rows with conflicting statuses."""
    records = _records_for(table_text, title)
    assert _answer_has_unverifiable_mixed_status_claim(claim, records)


def test_mixed_status_end_to_end_replaces_unrecognized_global_claim():
    """End-to-end (synthetic domain): the model asserts the same
    unsupported global rule using wording no comparison regex recognizes.
    The corrected answer must fall back to grounded row-by-row evidence
    (row facts retained), and confidence must not remain "high" for a
    generation the system had to override."""
    store = RoleAwareStore([_chunk("Widget Diagnostic Codes", SYNTHETIC_ABC_DIAGNOSTIC_TABLE)])
    result = _ask(
        store,
        "Which widget diagnostic codes are Normal?",
        groq_return="Widget codes shy of 3.00 are considered passing overall.",
    )
    assert "shy of 3.00" not in result.answer
    assert "Conditional" in result.answer or "Failed" in result.answer
    assert "1.00" in result.answer
    assert result.confidence != "high"


# ---------------------------------------------------------------------------
# LIVE STRUCTURED-EVIDENCE DETECTION (Azure re-certification, round 4).
#
# Root cause: every guard above — including the mixed-status policy guard —
# only ever runs against ``table_records`` parsed out of the retrieved
# context by ``_structured_table_records_from_text``. That parser only reads
# rows out of a "Structured table (...)" block, and ``_format_structured_tables``
# only ever opened that block for a line containing a literal "|" pipe
# character. A real PDF/OCR-extracted institutional table routinely loses
# that pipe entirely — columns survive as plain whitespace, a range's own
# dash gets lost leaving two bare numbers side by side, a "Below N" cell
# reads comparison-word-first instead of "N and below", and a single row can
# even land as several short consecutive lines. None of the guards above
# were wrong; they simply never received any rows at all, so
# ``table_records`` was empty and the entire
# ``if table_records and (...)`` gate at the fallback call site short-circuited
# to False before any of the three checks ran — confidence stayed "high" and
# the public answer was never replaced with the deterministic listing.
#
# Fix: ``_format_structured_tables`` now normalizes each of those flattened
# shapes into the same pipe-delimited row shape it already parses correctly
# (see ``_normalize_flattened_table_lines`` and its helpers), before any
# other parsing runs. A line is only ever treated as a candidate row when it
# *starts* with a bare identifier-shaped token *and* the very next token
# continues in a range-like shape — a guard proven below to leave ordinary
# prose that merely starts with a number untouched.
# ---------------------------------------------------------------------------

FLATTENED_GRADING_TABLE_NO_DASH_RANGE = """\
Grading System

Program Handbook > Article 3 > Grading > Sec. 1 > Grading Scale

1.00 95-100
1.25 92-94
1.50 89-91
2.00 83-85
3.00 77-79
4.00 70-74 Conditional
5.00 Below 70 Failed
"""

FLATTENED_GRADING_TABLE_SPLIT_NUMBERS = """\
Grading System

Program Handbook > Article 3 > Grading > Sec. 1 > Grading Scale

1.00 90 100 Excellent
2.00 80 89 Good
3.00 70 79 Conditional
4.00 0 69 Failed
"""

FLATTENED_GRADING_TABLE_MULTI_SPACE = """\
Grading System

Program Handbook > Article 3 > Grading > Sec. 1 > Grading Scale

1.00    95-100    Excellent
1.25    92-94     Excellent
4.00    70-74     Conditional
5.00    Below 70  Failed
"""

FLATTENED_GRADING_TABLE_MULTILINE_RECORDS = """\
Grading System

Program Handbook > Article 3 > Grading > Sec. 1 > Grading Scale

1.00
95-100
Excellent
2.00
80-94
Good
3.00
Below 80
Failed
"""

FLATTENED_GRADING_TABLE_REPEATED_HEADER = """\
Grading System

Program Handbook > Article 3 > Grading > Sec. 1 > Grading Scale

Code | Range | Status
1.00 | 95-100 | Excellent
2.00 | 80-94 | Good
Code | Range | Status
3.00 | Below 80 | Failed
"""

FLATTENED_ELIGIBILITY_TABLE = """\
Scholarship Eligibility Bands

Program Handbook > Article 5 > Scholarship Eligibility > Sec. 1 > Eligibility Bands

1.00 90-100 Eligible
2.00 80-89 Eligible
3.00 60-79 Not Eligible
"""

FLATTENED_FEE_TABLE = """\
Late Submission Fee Tiers

Program Handbook > Article 11 > Late Submission > Sec. 3 > Fee Tiers

1.00 1-5 No Fee
2.00 6-10 Standard Fee
3.00 11-20 Standard Fee
4.00 21-30 Premium Fee
"""

FLATTENED_APPROVAL_TABLE = """\
Request Processing Status Tiers

Program Handbook > Article 12 > Request Processing > Sec. 2 > Processing Status Tiers

1.00 1-7 Approved
2.00 8-14 Pending
3.00 15-30 Denied
"""

FLATTENED_DEADLINE_TABLE = """\
Appeal Filing Deadline Tiers

Program Handbook > Article 14 > Appeals > Sec. 2 > Filing Deadline Tiers

1.00 1-10 On Time
2.00 11-15 Grace Period
"""


@pytest.mark.parametrize(
    "table_text, title, expected_statuses",
    [
        (FLATTENED_GRADING_TABLE_NO_DASH_RANGE, "Grading System", {"conditional", "failed"}),
        (FLATTENED_GRADING_TABLE_SPLIT_NUMBERS, "Grading System", {"excellent", "good", "conditional", "failed"}),
        (FLATTENED_GRADING_TABLE_MULTI_SPACE, "Grading System", {"excellent", "conditional", "failed"}),
        (FLATTENED_GRADING_TABLE_MULTILINE_RECORDS, "Grading System", {"excellent", "good", "failed"}),
        (FLATTENED_GRADING_TABLE_REPEATED_HEADER, "Grading System", {"excellent", "good", "failed"}),
        (FLATTENED_ELIGIBILITY_TABLE, "Scholarship Eligibility Bands", {"eligible", "not eligible"}),
        (FLATTENED_FEE_TABLE, "Late Submission Fee Tiers", {"no fee", "standard fee", "premium fee"}),
        (FLATTENED_APPROVAL_TABLE, "Request Processing Status Tiers", {"approved", "pending", "denied"}),
        (FLATTENED_DEADLINE_TABLE, "Appeal Filing Deadline Tiers", {"on time", "grace period"}),
    ],
    ids=[
        "no-dash-range-plus-word-first-below",
        "range-split-into-two-bare-numbers",
        "multi-space-columns",
        "identifier-range-status-split-across-lines",
        "repeated-header-mixed-into-content",
        "eligibility-domain",
        "fee-domain",
        "approval-domain",
        "deadline-domain",
    ],
)
def test_flattened_pipe_less_tables_are_recognized_as_structured_rows(
    table_text, title, expected_statuses
):
    """Every one of these fixtures reproduces a real PDF/OCR-extraction shape
    that has no literal pipe character anywhere — the exact gap that let the
    live grading answer through with confidence still "high": the
    structured-table parser found zero rows, so none of the audit checks
    ever ran. Rows must be detected and every distinct Status recovered
    regardless of how the source table's columns happened to be flattened."""
    records = _records_for(table_text, title)
    assert records
    statuses = {status.casefold() for r in records if (status := r.get("Status"))}
    assert statuses == expected_statuses


def test_flattened_grading_table_mixed_status_fallback_fires():
    """The mixed-status policy guard must fire against a *flattened* table
    exactly as it already does against a pipe-delimited one — the guard
    itself is unchanged; only the parsing that feeds it needed the fix."""
    records = _records_for(FLATTENED_GRADING_TABLE_NO_DASH_RANGE, "Grading System")
    assert _answer_has_unverifiable_mixed_status_claim(
        "The passing grades are 1.00-3.00. These represent passing outcomes.",
        records,
    )
    # A plain row-by-row restatement remains allowed.
    assert not _answer_has_unverifiable_mixed_status_claim(
        "4.00 (70-74) is Conditional. 5.00 (70 and below) is Failed.", records
    )


def test_flattened_single_status_table_does_not_unnecessarily_fallback():
    """A flattened table where every row shares the same Status must not
    trigger the mixed-status policy, exactly like its pipe-delimited
    equivalent."""
    records = _records_for(
        """\
Widget Compliance Codes

Program Handbook > Article 6 > Widget Diagnostics > Sec. 2 > Compliance Codes

1.00 90-100 Compliant
2.00 80-89 Compliant
3.00 70-79 Compliant
""",
        "Widget Compliance Codes",
    )
    assert not _answer_has_unverifiable_mixed_status_claim(
        "Any code from 70 and above is Compliant.", records
    )


def test_flattened_explicit_global_rule_row_still_allows_a_global_summary():
    """A flattened table's own explicit combined-rule row still authorizes
    restating that rule, the same as the pipe-delimited fixture already
    proven for this above."""
    records = _records_for(
        """\
Device Certification Levels

Program Handbook > Article 9 > Device Certification > Sec. 5 > Certification Levels

1.00 80-100 Certified
2.00 50-79 Conditional
5.00 80 and above Certified
""",
        "Device Certification Levels",
    )
    assert not _answer_has_unverifiable_mixed_status_claim(
        "A score at or above 80 is Certified.", records
    )
    assert _answer_has_unverifiable_mixed_status_claim(
        "A score at or above 55 is Certified.", records
    )


def test_ordinary_prose_with_leading_numbers_is_never_mistaken_for_a_table():
    """The false-positive guard: prose that merely starts a sentence with a
    number, but does not continue in a range-like shape, must never be
    rewritten into a table row or wrapped in "Structured table" framing —
    the source text must reach the model unchanged."""
    prose = (
        "Enrollment Procedures\n\n"
        "Program Handbook > Article 2 > Enrollment\n\n"
        "3 out of 5 students attended the orientation session.\n"
        "1 form must be submitted at least 30 days before the deadline.\n"
        "2 copies of the requirements are needed for processing.\n"
    )
    formatted = format_retrieved_context([_chunk("Enrollment Procedures", prose)])
    assert "Structured table" not in formatted
    assert "3 out of 5 students attended" in formatted
    records = _structured_table_records_from_text(formatted)
    assert records == []


def test_live_like_grading_regression_end_to_end():
    """The exact live-reported shape: a flattened grading table (no pipes,
    a word-first "Below 70" cell, some rows with no written status) and a
    generated answer merging the passing-looking rows into one global claim.
    Structured evidence must now be recognized, the mixed-status fallback
    must fire, the unsupported classification must be removed, row-
    supported facts must be retained, and confidence must be downgraded."""
    store = RoleAwareStore(
        [_chunk("Grading System", FLATTENED_GRADING_TABLE_NO_DASH_RANGE)]
    )
    result = _ask(
        store,
        "Which grades are considered passing?",
        groq_return="The passing grades are: 1.00-3.00 — These represent passing outcomes.",
    )
    assert "1.00-3.00" not in result.answer or "These represent passing outcomes" not in result.answer
    assert "Conditional" in result.answer or "Failed" in result.answer
    assert result.confidence != "high"


# ---------------------------------------------------------------------------
# GENERATION-AUDIT EVIDENCE PLUMBING (Azure re-certification, round 5).
#
# Root cause: ``format_retrieved_context`` (the normal-QA context builder)
# runs each selected chunk's text through ``_format_structured_tables``
# before building its "Content:" block, which is what inserts the
# "Structured table (...)" marker every audit check depends on.
# ``format_collection_context`` — the *other* context builder, used whenever
# ``detect_collection_intent`` classifies a question as a listing sweep
# (requirements/policy/scholarship/service/office collections) — built its
# "Content:" block straight from the chunk's raw text and never called
# ``_format_structured_tables`` at all. Both builders assign their result to
# the same ``context`` variable that is later handed to *both*
# ``generate_groq_answer`` and ``_structured_table_records_from_text`` (the
# parser every audit check reads from), so whichever builder ran, its output
# is genuinely the one and only evidence object both generation and the
# audit see — there is no separate, reduced representation the audit reads
# instead. The gap was specific to this one builder: a table-bearing chunk
# retrieved for a collection-style question would reach the model with its
# pipe structure intact (fine for generation) while the audit's parser saw
# zero rows in that exact same text, because the "Structured table" marker
# it looks for was never inserted for this code path.
#
# Direct tracing of the normal-QA path (below and via manual instrumentation
# during this investigation) confirmed it was already sound: the same
# ``context`` string that is built from ``selected_context`` is passed to
# generation and independently re-parsed for the audit with matching row
# counts at every step, and a chunk that loses the relevance contest for
# ``selected_context`` never reaches either side — there is no case where
# generation and audit see different evidence sets, and no second retrieval
# happens for the audit. This is confirmed with a word-overlap store (the
# same style already used in ``tests/test_qa_multi_facet.py``) so each
# question part genuinely competes for its own chunk, rather than the
# fixed-score ``RoleAwareStore`` used elsewhere in this file which returns
# the same top chunks regardless of the query text.
# ---------------------------------------------------------------------------

GRADING_TABLE_ELEVEN_ROWS = """\
Undergraduate Grading System

Program Handbook > Article 5 > Academic Policies > Sec. 2 > Grading System

The table below lists the numerical grade equivalents used to determine a
student's passing or failing standing for the term.

1.00 | 97-100 | Excellent
1.25 | 94-96 | Excellent
1.50 | 91-93 | Very Satisfactory
1.75 | 88-90 | Very Satisfactory
2.00 | 85-87 | Satisfactory
2.25 | 82-84 | Satisfactory
2.50 | 79-81 | Fairly Satisfactory
2.75 | 76-78 | Fairly Satisfactory
3.00 | 75 | Fairly Satisfactory
4.00 | 70-74 | Conditional Failure
5.00 | Below 70 | Failed
"""

GWA_COMPUTATION_PROSE = (
    "The General Weighted Average (GWA) is computed by multiplying each "
    "course's credit units by the numerical grade earned, summing these "
    "products across all enrolled courses, and dividing the total by the "
    "sum of all credit units for the term."
)

GRADE_CHANGE_PETITION_PROSE = (
    "A student who believes a final grade was recorded in error may file a "
    "grade change petition with the Office of the Registrar within one "
    "academic year of the grade's posting."
)

# A second, unrelated table whose own words never overlap the grading
# question at all -- used to prove a chunk that loses the relevance contest
# never reaches the audit either, exactly as it never reaches generation.
UNRELATED_FEE_TABLE = """\
Laboratory Equipment Damage Fee Schedule

Program Handbook > Article 20 > Laboratory Safety > Sec. 3 > Equipment Damage Fees

1.00 | 1-500 | Minor Damage Fee
2.00 | 501-2000 | Major Damage Fee
3.00 | 2001 and above | Full Replacement Cost
"""


class WordOverlapStore:
    """Word-overlap stand-in for the retriever (the same style already used
    in ``tests/test_qa_multi_facet.py``), so each facet query in a bundled
    question genuinely competes for its own best-matching chunk instead of
    ``RoleAwareStore``'s fixed, query-agnostic top-N."""

    def __init__(self, library: dict[str, "RetrievedChunk"]):
        self.library = library
        self.chunk_count = len(library)
        self.queries: list[str] = []

    _STOPWORDS = {
        "a", "an", "the", "is", "are", "and", "or", "how", "what", "of", "to",
        "in", "on", "for", "by", "with", "each", "all", "these", "this",
    }

    def search(self, question: str, *, top_k=None, raw_k=None, user_role=None):
        self.queries.append(question)
        words = set(re.findall(r"[a-z0-9]+", question.lower())) - self._STOPWORDS
        scored = []
        for title, chunk in self.library.items():
            haystack = set(re.findall(r"[a-z0-9]+", f"{title} {chunk.text}".lower())) - self._STOPWORDS
            overlap = len(words & haystack)
            if overlap:
                scored.append((overlap, chunk))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        ranked = [chunk for _, chunk in scored]
        return select_role_visible_hits(ranked, user_role=user_role, top_k=top_k or 7)


def _ask_word_overlap(library: dict, question: str, groq_return: str):
    store = WordOverlapStore(library)
    with (
        patch("app.services.qa.question_answering.get_knowledge_base_store", return_value=store),
        patch(
            "app.services.qa.question_answering.generate_groq_answer",
            return_value=groq_return,
        ) as mock_groq,
    ):
        result = answer_qa_question(question, user_role="student")
    generation_context = mock_groq.call_args.kwargs.get("context", "")
    return result, generation_context, store


def test_selected_table_evidence_survives_into_generation_and_audit_context():
    """The primary pipeline-boundary trace: a structured table chunk, a
    related prose chunk answering the other half of a bundled question, and
    a competing/adjacent chunk. The table's rows must reach the model
    exactly as retrieved, and the audit's structured-row parser must see
    that *same* text — not a reduced or re-retrieved representation."""
    library = {
        "Undergraduate Grading System": _chunk("Undergraduate Grading System", GRADING_TABLE_ELEVEN_ROWS),
        "General Weighted Average Computation": _chunk(
            "General Weighted Average Computation", GWA_COMPUTATION_PROSE
        ),
        "Grade Change Petition Procedure": _chunk(
            "Grade Change Petition Procedure", GRADE_CHANGE_PETITION_PROSE
        ),
    }
    result, generation_context, _ = _ask_word_overlap(
        library,
        "What is the passing grade and how is GWA computed?",
        "Grades from 1.00 to 4.00 are considered passing. GWA is computed by weighted average of grades.",
    )
    assert "Undergraduate Grading System" in generation_context
    assert "Structured table" in generation_context
    audit_records = _structured_table_records_from_text(generation_context)
    assert len(audit_records) == 11
    statuses = {r.get("Status") for r in audit_records if r.get("Status")}
    assert {"Conditional Failure", "Failed"} <= statuses
    # The unsupported "1.00 to 4.00" merge (Conditional Failure at 4.00 is
    # not passing) must trigger the fallback and downgrade confidence.
    assert "1.00 to 4.00" not in result.answer or "considered passing" not in result.answer
    assert "Conditional" in result.answer or "Failed" in result.answer
    assert result.confidence != "high"


def test_unselected_table_evidence_is_not_secretly_introduced_into_audit():
    """A second table chunk whose own words never overlap the question at
    all must lose the relevance contest for ``selected_context`` -- and,
    because the audit reads the same ``context`` used for generation rather
    than re-retrieving anything, its rows must never reach the audit
    either."""
    library = {
        "Undergraduate Grading System": _chunk("Undergraduate Grading System", GRADING_TABLE_ELEVEN_ROWS),
        "General Weighted Average Computation": _chunk(
            "General Weighted Average Computation", GWA_COMPUTATION_PROSE
        ),
        "Laboratory Equipment Damage Fee Schedule": _chunk(
            "Laboratory Equipment Damage Fee Schedule", UNRELATED_FEE_TABLE
        ),
    }
    result, generation_context, _ = _ask_word_overlap(
        library,
        "What is the passing grade and how is GWA computed?",
        "Grades from 1.00 to 4.00 are considered passing.",
    )
    assert "Laboratory Equipment Damage Fee Schedule" not in generation_context
    audit_records = _structured_table_records_from_text(generation_context)
    statuses = {r.get("Status") for r in audit_records if r.get("Status")}
    assert "Full Replacement Cost" not in statuses
    assert "Minor Damage Fee" not in statuses
    # The grading table's own audit outcome is unaffected by the unrelated
    # table's absence.
    assert result.confidence != "high"


def test_ordinary_prose_only_context_behaves_normally():
    """A question whose evidence is pure prose (no structured table
    anywhere) must not be affected by any of this -- no fallback, no forced
    row-listing, confidence driven only by normal retrieval quality."""
    library = {
        "General Weighted Average Computation": _chunk(
            "General Weighted Average Computation", GWA_COMPUTATION_PROSE
        ),
        "Grade Change Petition Procedure": _chunk(
            "Grade Change Petition Procedure", GRADE_CHANGE_PETITION_PROSE
        ),
    }
    result, generation_context, _ = _ask_word_overlap(
        library,
        "How is GWA computed?",
        "GWA is computed by multiplying credit units by grades and dividing by total units.",
    )
    assert "Structured table" not in generation_context
    assert _structured_table_records_from_text(generation_context) == []
    assert "multiplying credit units" in result.answer


def test_multiple_selected_chunks_remain_correctly_bounded_and_separated():
    """Two structured tables both selected for the same answer (a bundled
    question spanning two different tables) must never have their rows
    cross-contaminate -- each table's own Identifier/Range/Status stays
    associated only with its own chunk."""
    library = {
        "Undergraduate Grading System": _chunk("Undergraduate Grading System", GRADING_TABLE_ELEVEN_ROWS),
        "Laboratory Equipment Damage Fee Schedule": _chunk(
            "Laboratory Equipment Damage Fee Schedule", UNRELATED_FEE_TABLE
        ),
    }
    result, generation_context, _ = _ask_word_overlap(
        library,
        "What is the passing grade and what is the laboratory equipment damage fee?",
        "Grades of 1.00 to 3.00 are passing. Damage fees range from 1 to 2000.",
    )
    audit_records = _structured_table_records_from_text(generation_context)
    grading_statuses = {r.get("Status") for r in audit_records if r.get("Identifier") in {"1.00", "4.00", "5.00"} and r.get("Status") in {"Excellent", "Conditional Failure", "Failed"}}
    fee_statuses = {r.get("Status") for r in audit_records if r.get("Status") in {"Minor Damage Fee", "Major Damage Fee", "Full Replacement Cost"}}
    assert "Excellent" in grading_statuses or "Conditional Failure" in grading_statuses
    assert fee_statuses  # the fee table's own rows are present and distinct
    assert not (grading_statuses & fee_statuses)


def test_explicit_global_source_rule_still_works_end_to_end():
    """The source's own explicit combined-rule row must still authorize a
    global summary end-to-end, through the real selection/context/audit
    path, not just the unit-level checker."""
    table = """\
Device Certification Levels

Program Handbook > Article 9 > Device Certification > Sec. 5 > Certification Levels

1.00 | 80-100 | Certified
2.00 | 50-79 | Conditional
5.00 | 80 and above | Certified
"""
    library = {"Device Certification Levels": _chunk("Device Certification Levels", table)}
    result, generation_context, _ = _ask_word_overlap(
        library,
        "What device certification levels are Certified?",
        "A score at or above 80 is Certified.",
    )
    assert "Structured table" in generation_context
    assert "at or above 80" in result.answer
    assert result.confidence != "medium" or "at or above 80" in result.answer


def test_single_status_structured_evidence_does_not_unnecessarily_fallback():
    """A structured table where every row shares the same Status must not
    trigger the fallback end-to-end, even though it is genuinely structured
    evidence."""
    table = """\
Widget Compliance Codes

Program Handbook > Article 6 > Widget Diagnostics > Sec. 2 > Compliance Codes

1.00 | 90-100 | Compliant
2.00 | 80-89 | Compliant
3.00 | 70-79 | Compliant
"""
    library = {"Widget Compliance Codes": _chunk("Widget Compliance Codes", table)}
    result, generation_context, _ = _ask_word_overlap(
        library,
        "What widget compliance codes are Compliant?",
        "Codes from 70 to 100 are Compliant.",
    )
    assert "Codes from 70 to 100 are Compliant." in result.answer


def test_non_grade_domain_collection_style_question_preserves_table_structure():
    """The exact ``format_collection_context`` gap, in a non-grade domain: a
    "what are the requirements" collection-style question (which routes
    through the *other* context builder) that happens to retrieve a
    structured eligibility table. The table's Structured-table marker, and
    therefore the audit, must survive that builder too."""
    table = """\
Scholarship Eligibility Bands

Program Handbook > Article 5 > Scholarship Eligibility > Sec. 1 > Eligibility Bands

1.00 | 90-100 | Eligible
2.00 | 80-89 | Eligible
3.00 | 60-79 | Not Eligible
"""
    library = {
        "Scholarship Eligibility Bands": _chunk("Scholarship Eligibility Bands", table),
    }
    result, generation_context, _ = _ask_word_overlap(
        library,
        "What are the scholarship eligibility requirements?",
        "Eligible status is said to cover the zone bounded by 60 and 100.",
    )
    assert "Structured table" in generation_context
    audit_records = _structured_table_records_from_text(generation_context)
    assert len(audit_records) == 3
    statuses = {r.get("Status") for r in audit_records if r.get("Status")}
    assert statuses == {"Eligible", "Not Eligible"}
    assert "bounded by 60 and 100" not in result.answer
    assert result.confidence != "high"


def test_live_grading_and_gwa_question_reproduction():
    """The exact live Azure regression trigger. Not a grading-specific
    behavior test -- the assertions only check the general pipeline
    invariant (structured evidence recognized end to end, mixed-status
    fallback fires, confidence downgraded), using this specific question
    only as the reproduction shape reported."""
    library = {
        "Undergraduate Grading System": _chunk("Undergraduate Grading System", GRADING_TABLE_ELEVEN_ROWS),
        "General Weighted Average Computation": _chunk(
            "General Weighted Average Computation", GWA_COMPUTATION_PROSE
        ),
    }
    bad_answer = (
        "The passing grades are: 1.00 - 4.00 — These represent passing outcomes."
    )
    result, generation_context, _ = _ask_word_overlap(
        library,
        "What is the passing grade and how is GWA computed?",
        bad_answer,
    )
    audit_records = _structured_table_records_from_text(generation_context)
    assert len(audit_records) == 11
    assert _answer_has_unverifiable_mixed_status_claim(bad_answer, audit_records)
    assert "These represent passing outcomes" not in result.answer
    assert "Conditional" in result.answer or "Failed" in result.answer
    assert result.confidence != "high"


# ---------------------------------------------------------------------------
# UNSAFE BULLET DETECTION REMOVED (Azure re-certification, round 7).
#
# The round-6 bullet/dash-list structured-evidence detector
# (``_normalize_bullet_list_rows`` and its helpers) has been removed
# entirely. It could not tell a genuine status/category table apart from an
# ordinary two-column reference list ("Clearance — Accounting Office",
# "Student ID — OSAS / BAO", "Requirement — SF-Form-002 ICTS") using shape
# alone, because both have the exact same shape: short fields, a consistent
# field count, a dash/colon separator, repeated across consecutive lines.
# Live Enrollment/support content of that ordinary reference-list shape was
# being misclassified as a structured status table, and once misclassified,
# a correct, on-topic generated answer was being wholesale replaced by the
# generic "The retrieved table lists these records..." fallback text —
# a false positive far more damaging than the missed grading detection it
# was trying to fix.
#
# Removed: ``_normalize_bullet_list_rows``, ``_merge_bullet_continuations``,
# ``_merge_adjacent_bare_number_fields``, ``_bullet_line_fields``,
# ``_field_looks_like_row_cell``, ``_bullet_group_is_structured``, and the
# ``_BULLET_*`` regexes, plus their wiring into ``_format_structured_tables``.
#
# Kept (narrow, safe on their own, not implicated in the false positives):
# the header-vs-data heuristic fix for an all-non-numeric *pipe*-delimited
# table (still gated on a literal "|", which ordinary prose never contains),
# the positional Identifier/Status role-inference fix in
# ``_table_record_from_row`` (same "|"-only gate), and the non-numeric
# record-anchor grounding path in the mixed-status policy guard (only ever
# runs once records already exist — it cannot cause a false *detection*).
#
# The grading-table detection gap this was trying to close is NOT
# reintroduced by anything below — it simply does not exist any more,
# exactly as it did not before round 6. See this session's report for the
# architectural finding on why no further heuristic was implemented instead.
# ---------------------------------------------------------------------------

ENROLLMENT_CLEARANCE_REFERENCE_LIST = """\
Enrollment Clearance Requirements

Program Handbook > Article 2 > Enrollment > Sec. 1 > Clearance Requirements

- Clearance — Accounting Office
- Student ID — OSAS / BAO
- Requirement — SF-Form-002 ICTS

Office: Registrar
"""

GOOD_MORAL_REFERENCE_LIST = """\
Good Moral Certificate

Student Services > Good Moral Certificate

- Request Form — OSAS
- Clearance — Accounting Office
- Processing — Office of the Registrar

Office: Office of the Registrar
"""


def test_ordinary_reference_list_bullets_are_not_interpreted_as_structured_table():
    """The exact reported false-positive shape: a short "item — office" or
    "item — form" reference list. It must never produce structured rows —
    this shape is indistinguishable, by structure alone, from a genuine
    status table, which is exactly why the broad bullet detector had to be
    removed rather than tightened further."""
    formatted = format_retrieved_context(
        [_chunk("Enrollment Clearance Requirements", ENROLLMENT_CLEARANCE_REFERENCE_LIST)]
    )
    assert "Structured table" not in formatted
    assert "Accounting Office" in formatted
    assert _structured_table_records_from_text(formatted) == []


def test_enrollment_first_turn_answer_is_not_replaced_by_structured_fallback():
    """A correct, on-topic Enrollment answer grounded in a reference-list
    style chunk must reach the user unchanged — not replaced by the generic
    row-listing fallback text."""
    store = RoleAwareStore(
        [_chunk("Enrollment Clearance Requirements", ENROLLMENT_CLEARANCE_REFERENCE_LIST)]
    )
    good_answer = (
        "To enroll, secure clearance from the Accounting Office, present your "
        "Student ID from OSAS/BAO, and submit SF-Form-002 to ICTS. Coordinate "
        "with the Office of the Registrar for your enrollment record."
    )
    result = _ask(store, "What are the requirements to enroll?", groq_return=good_answer)
    assert result.answer == good_answer
    assert "retrieved table lists these records" not in result.answer.lower()


def test_enrollment_office_followup_still_returns_registrar():
    """A follow-up asking which office handles enrollment must still
    surface the Registrar, unchanged by any structured-evidence audit."""
    store = RoleAwareStore(
        [_chunk("Enrollment Clearance Requirements", ENROLLMENT_CLEARANCE_REFERENCE_LIST)]
    )
    good_answer = "The Office of the Registrar handles enrollment records and processing."
    result = _ask(store, "Which office handles enrollment?", groq_return=good_answer)
    assert "Registrar" in result.answer
    assert result.answer == good_answer


def test_good_moral_answer_is_not_replaced_by_structured_fallback():
    """A correct Good Moral Certificate answer, grounded in the same
    reference-list chunk shape, must not be replaced by the generic
    row-listing fallback."""
    store = RoleAwareStore([_chunk("Good Moral Certificate", GOOD_MORAL_REFERENCE_LIST)])
    good_answer = (
        "Request the Good Moral Certificate form from OSAS, secure clearance "
        "from the Accounting Office, and have it processed at the Office of "
        "the Registrar."
    )
    result = _ask(store, "How do I get a Good Moral Certificate?", groq_return=good_answer)
    assert result.answer == good_answer
    assert "retrieved table lists these records" not in result.answer.lower()


def test_existing_pipe_table_structured_cases_still_work():
    """A genuine pipe-delimited grading table (the original, validated
    representation) must still be recognized and still trigger the
    mixed-status fallback for an unsupported global claim -- proving the
    removal did not regress the core, previously-validated mechanism."""
    records = _records_for(UNDERGRAD_GRADING_TABLE, "Grading System")
    assert records
    assert _answer_synthesizes_unsupported_range(
        "A grade from 84 to 92 is Satisfactory.", records
    )


@pytest.mark.parametrize(
    "table_text, title, claim",
    [
        (SYNTHETIC_ELIGIBILITY_TABLE_ADJACENT, "Scholarship Eligibility Bands", "Scores at or above 80 are Eligible."),
        (SYNTHETIC_FEE_TIER_TABLE, "Late Submission Fee Tiers", "A fee of 6 to 30 falls under the Standard Fee tier."),
        (SYNTHETIC_REQUEST_APPROVAL_TABLE, "Request Processing Status Tiers", "Requests processed at or above 8 days are Pending."),
    ],
    ids=["eligibility", "fee-tier", "approval"],
)
def test_non_grade_pipe_table_structured_cases_still_work(table_text, title, claim):
    """Non-grade pipe-delimited structured cases (eligibility, fees,
    approval status) must still be detected and still reject an
    unsupported synthesized claim after the bullet-detector removal."""
    records = _records_for(table_text, title)
    assert records
    assert _answer_synthesizes_unsupported_range(claim, records)


def test_audit_cannot_use_evidence_unavailable_to_the_generator():
    """The generation-audit evidence-plumbing invariant, reconfirmed after
    the bullet-detector removal: a chunk that loses the relevance contest
    for selected context must never reach the audit either."""
    library = {
        "Undergraduate Grading System": _chunk("Undergraduate Grading System", GRADING_TABLE_ELEVEN_ROWS),
        "General Weighted Average Computation": _chunk(
            "General Weighted Average Computation", GWA_COMPUTATION_PROSE
        ),
        "Laboratory Equipment Damage Fee Schedule": _chunk(
            "Laboratory Equipment Damage Fee Schedule",
            "Laboratory Equipment Damage Fee Schedule\n\n"
            "Program Handbook > Article 20 > Laboratory Safety > Sec. 3 > Equipment Damage Fees\n\n"
            "1.00 | 1-500 | Minor Damage Fee\n"
            "2.00 | 501-2000 | Major Damage Fee\n"
            "3.00 | 2001 and above | Full Replacement Cost\n",
        ),
    }
    result, generation_context, _ = _ask_word_overlap(
        library,
        "What is the passing grade and how is GWA computed?",
        "Grades from 1.00 to 4.00 are considered passing.",
    )
    assert "Laboratory Equipment Damage Fee Schedule" not in generation_context
    audit_records = _structured_table_records_from_text(generation_context)
    statuses = {r.get("Status") for r in audit_records if r.get("Status")}
    assert "Full Replacement Cost" not in statuses
    assert result.confidence != "high"


def test_generation_and_audit_operate_from_the_same_selected_evidence():
    """Generation and audit must read the identical evidence string -- the
    pipe-delimited grading table reaching the model must be the exact same
    text the audit re-parses, with a matching row count."""
    library = {"Grading System": _chunk("Grading System", UNDERGRAD_GRADING_TABLE)}
    result, generation_context, _ = _ask_word_overlap(
        library, "What is the passing grade?", "A grade from 84 to 92 is Satisfactory."
    )
    audit_records = _structured_table_records_from_text(generation_context)
    direct_records = _records_for(UNDERGRAD_GRADING_TABLE, "Grading System")
    assert len(audit_records) == len(direct_records)
    assert "Structured table" in generation_context


# ---------------------------------------------------------------------------
# PIPE-TABLE PRODUCTION PATH AUDIT (Azure re-certification, round 8).
#
# Finding: production's actual retrieved/selected evidence for "What is the
# passing grade and how is GWA computed?" is the *pipe-delimited* handbook
# chunk (title "Grading System", chapter "Undergraduate Academic Policies") —
# not the bullet/em-dash FAQ article, which is a *separate*, unselected
# stored object and is never forced into selection here. The fixture below
# (``REAL_PIPE_GRADING_TABLE``) is the verbatim text of that chunk, pulled
# directly from the local Chroma store as a read-only architecture-inspection
# step (never modified, no reindex, no ingestion change).
#
# Tracing the *full* ``answer_qa_question`` path with this exact text
# (selection → generation context → audit input → row extraction →
# mixed-status detection → fallback → confidence) end to end, repeatedly and
# under several realistic conditions (a lone chunk, several genuine
# grading-adjacent chunks selected alongside it, an unselected bullet FAQ
# article present in the retrieval pool but not chosen), found no
# divergence: rows are extracted, mixed statuses are detected, the
# unsupported "any score above 69" claim is replaced by the grounded
# row-listing, and confidence is downgraded. The mechanism already
# implemented in this working tree — never yet deployed, per every prior
# round's explicit "do not deploy" — already protects this exact
# production-shaped path. The tests below lock that in as a permanent
# regression, and separately reconfirm every safety invariant from the
# round-7 false-positive removal still holds under this same production
# shape.
# ---------------------------------------------------------------------------

REAL_PIPE_GRADING_TABLE = """\
Grading System

Undergraduate Academic Policies > Article 7 > Grading System and Other Grade-related Concerns > Sec. 1 > Grading System

The grading system is expressed in Arabic numerals
and is recorded by the Office of the Registrar. The following are the
grades used and their equivalents in percent and respective descrip-
tions.
Average Equivalent Grade Description
1.00 | 99-100 | Excellent
1.25 | 96-98
1.50 | 93-95 | Very Satisfactory
1.75 | 90-92
2.00 | 87-89 | Satisfactory
2.25 | 84-86
2.50 | 81-83 | Fairly Satisfactory
2.75 | 78-80
3.00 | 75-77
4.00 | 70-74 | Conditional Failure
5.00 | 69 and below Failed
INC | Incomplete
DRP | Officially Dropped
"""

REAL_GWA_PROSE = (
    "The General Weighted Average or GWA of students refers to the weighted "
    "average of grades in all academic courses taken in a given semester."
)

# The separate, unselected bullet/em-dash FAQ article Azure identified as a
# *different* stored object. It is included in the retrieval pool in the
# "unselected evidence" test below with no keyword overlap, so it loses the
# relevance contest on its own -- it is never forced out or specially
# excluded, and its bullet formatting is irrelevant here since it never
# reaches selection.
UNDERGRADUATE_GRADING_FAQ_BULLET_ARTICLE = """\
Academic Scale Quick Reference

Student Portal Help > Quick Reference

- 1.00 — 99–100 — Excellent
- 1.25 — 96–98
- 1.50 — 93–95 — Very Satisfactory
- 4.00 — 70–74 — Conditional Failure
- 5.00 — 69 and below — Failed
"""


def test_production_shaped_pipe_table_context_is_parsed():
    """Requirement 1: the wrapped generation context built from the real,
    verbatim handbook pipe-table text is parsed into structured rows."""
    library = {"Grading System": _chunk("Grading System", REAL_PIPE_GRADING_TABLE)}
    _, generation_context, _ = _ask_word_overlap(
        library,
        "What is the passing grade and how is GWA computed?",
        "A grade from 87 to 89 is Satisfactory.",
    )
    assert "Structured table" in generation_context
    audit_records = _structured_table_records_from_text(generation_context)
    assert len(audit_records) == 13


def test_production_shaped_mixed_statuses_detected():
    """Requirement 2: mixed statuses are detected from that wrapped
    context — the real table carries Excellent, Very Satisfactory,
    Satisfactory, Fairly Satisfactory, Conditional Failure, Failed,
    Incomplete, and Officially Dropped, all distinct."""
    records = _records_for(REAL_PIPE_GRADING_TABLE, "Grading System")
    statuses = {r.get("Status") for r in records if r.get("Status")}
    assert {"Conditional Failure", "Failed", "Excellent", "Satisfactory"} <= statuses
    assert _answer_has_unverifiable_mixed_status_claim(
        "A passing grade would be any score above 69.", records
    )


@pytest.mark.parametrize(
    "bad_answer",
    [
        "A passing grade would be any score above 69.",
        "The passing range consists of grades 1.00 through 4.00.",
        "Grades of 1.00 and above (up to 4.00) are considered passing.",
    ],
)
def test_production_shaped_unsupported_global_claim_is_replaced_and_downgraded(bad_answer):
    """Requirements 3-4: an unsupported synthesized global passing rule,
    generated over the real production-shaped selected evidence, is
    blocked and replaced by the grounded row listing, with confidence
    downgraded from "high"."""
    library = {
        "Grading System": _chunk("Grading System", REAL_PIPE_GRADING_TABLE, score=4.9),
        "GWA": _chunk("GWA", REAL_GWA_PROSE, score=4.8),
    }
    result, generation_context, _ = _ask_word_overlap(
        library, "What is the passing grade and how is GWA computed?", bad_answer
    )
    assert "Grading System" in [s for s in (r["title"] for r in result.sources)]
    assert bad_answer not in result.answer
    assert "Conditional" in result.answer or "Failed" in result.answer
    assert result.confidence != "high"


def test_production_shaped_explicit_global_rule_remains_allowed():
    """Requirement 5: if the source itself states a combined rule as its
    own row, restating it end to end is still allowed, not replaced. Uses
    the table's own percentage (Range) axis, where the real table's grade
    bands actually live, rather than its GPA-style Identifier axis, whose
    numbers ("1.00".."5.00") share the same numeric scale a naive Range
    open-threshold row would collide with in this particular table."""
    table_with_explicit_rule = REAL_PIPE_GRADING_TABLE + "75-100 | Passing\n"
    library = {"Grading System": _chunk("Grading System", table_with_explicit_rule, score=4.9)}
    result, generation_context, _ = _ask_word_overlap(
        library,
        "What is the passing grade?",
        "Grades from 75 to 100 are Passing.",
    )
    assert result.answer == "Grades from 75 to 100 are Passing."
    assert result.confidence == "high"


def test_production_shaped_ordinary_enrollment_context_does_not_fallback():
    """Requirement 6: ordinary Enrollment reference-list content, run
    through this exact same production-shaped path (real selection,
    generation, and audit call sites), must not trigger the structured
    fallback."""
    library = {
        "Enrollment Clearance Requirements": _chunk(
            "Enrollment Clearance Requirements", ENROLLMENT_CLEARANCE_REFERENCE_LIST
        ),
    }
    good_answer = (
        "To enroll, secure clearance from the Accounting Office, present your "
        "Student ID from OSAS/BAO, and submit SF-Form-002 to ICTS."
    )
    result, generation_context, _ = _ask_word_overlap(
        library, "What are the requirements to enroll?", good_answer
    )
    assert result.answer == good_answer
    assert "Structured table" not in generation_context


def test_production_shaped_good_moral_context_remains_unaffected():
    """Requirement 7: the Good Moral Certificate reference-list content
    must remain unaffected by the structured audit under this same
    production-shaped path."""
    library = {"Good Moral Certificate": _chunk("Good Moral Certificate", GOOD_MORAL_REFERENCE_LIST)}
    good_answer = (
        "Request the Good Moral Certificate form from OSAS, secure clearance "
        "from the Accounting Office, and have it processed at the Office of "
        "the Registrar."
    )
    result, generation_context, _ = _ask_word_overlap(
        library, "How do I get a Good Moral Certificate?", good_answer
    )
    assert result.answer == good_answer
    assert "Structured table" not in generation_context


def test_production_shaped_audit_does_not_introduce_unselected_faq_evidence():
    """Requirement 8: the separate, unselected bullet/em-dash FAQ article
    must never leak into the audit, even though it describes the exact
    same underlying grading facts and is present in the retrieval pool --
    it simply loses the relevance contest on its own (no keyword overlap
    with the question) and is never forced out or force-included."""
    library = {
        "Grading System": _chunk("Grading System", REAL_PIPE_GRADING_TABLE, score=4.9),
        "GWA": _chunk("GWA", REAL_GWA_PROSE, score=4.8),
        "Academic Scale Quick Reference": _chunk(
            "Academic Scale Quick Reference", UNDERGRADUATE_GRADING_FAQ_BULLET_ARTICLE, score=1.0
        ),
    }
    bad_answer = "A passing grade would be any score above 69."
    result, generation_context, store = _ask_word_overlap(
        library, "What is the passing grade and how is GWA computed?", bad_answer
    )
    assert "Academic Scale Quick Reference" not in generation_context
    assert "Student Portal Help" not in generation_context
    audit_records = _structured_table_records_from_text(generation_context)
    assert len(audit_records) == 13
    assert "Conditional" in result.answer or "Failed" in result.answer
    assert result.confidence != "high"


# ---------------------------------------------------------------------------
# QUERY-INTENT GLOBAL-CLASSIFICATION SAFETY (Azure re-certification, round 10).
#
# The round-9 guard activated from the *generated answer's* wording (a
# comparison-shape regex family) and tried to verify each specific claim
# phrase-by-phrase against the evidence. Azure proved this unsafe in both
# directions: it still missed paraphrases no pattern was written for ("70+",
# an enumerated "1.00 ... and 4.00 are passing"), and it could fire on a
# correct, unrelated Enrollment answer merely because Groq generated broad
# wording ("All students ..."), since activation depended on the model's
# unpredictable output rather than anything stable.
#
# This version activates on the *user's own question* instead — fixed,
# known before generation ever runs, and never influenced by what the model
# later says. ``_is_global_classification_query`` recognizes the structural
# shape of a question asking for a global classification/range/boundary
# ("what score is considered eligible", "which tiers count as certified",
# "what is the passing grade") and is completely blind to procedural/
# service questions ("how do I enroll", "what documents do I need"),
# regardless of any word the eventual answer contains. Once gated, the
# decision is made purely from the evidence's own shape
# (``_evidence_states_single_global_rule`` — a plain count of comparison/
# range-shaped statements, never row parsing or "understanding" a table):
# exactly one such statement is treated as an explicit combined rule and the
# answer is left alone; zero or several are treated as "no single global
# rule stated" and every numeric or comparative sentence in the answer is
# replaced with a fixed, generic notice — regardless of its specific
# wording, closing the paraphrase-chasing gap by never trying to match
# specific wording at all.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "question, expected",
    [
        ("What score is considered eligible?", True),
        ("Which tiers count as certified?", True),
        ("What range is considered on time?", True),
        ("What amount requires extra approval?", True),
        ("What is the passing grade and how is GWA computed?", True),
        ("What is the minimum score to qualify?", True),
        ("How do I enroll?", False),
        ("What documents do I need?", False),
        ("Where can I go?", False),
        ("Does it have a fee?", False),
        ("Which office handles it?", False),
        ("How do I request a certificate?", False),
        ("What are the requirements?", False),
    ],
)
def test_query_intent_classification_shape(question, expected):
    """The activation gate depends only on the user's own question shape --
    verified directly against every example named in the requirements,
    both the classification-intent triggers and the procedural
    non-triggers."""
    assert _is_global_classification_query(question) is expected


@pytest.mark.parametrize(
    "domain, question, evidence_text, unsupported_claim",
    [
        (
            "eligibility",
            "What score is considered eligible?",
            "90-100 — Eligible\n80-89 — Conditional\nBelow 80 — Ineligible",
            "Everyone scoring 80 or above is eligible.",
        ),
        (
            "certification",
            "Which tiers count as certified?",
            "Tier A — Certified\nTier B — Conditional\nTier C — Not Certified",
            "Tier B and above are certified.",
        ),
        (
            "deadline",
            "What range is considered on time?",
            "Before March 15 — On Time\nMarch 16 to April 1 — Late\nAfter April 1 — Closed",
            "Anything before April 1 is automatically accepted.",
        ),
        (
            "fees",
            "What amount requires extra approval?",
            "Photocopy — 5 pesos per page\nCertification — 50 pesos\nAuthentication — 100 pesos",
            "All requests above 500 require additional approval.",
        ),
    ],
    ids=["eligibility", "certification", "deadline", "fees"],
)
def test_classification_intent_with_no_explicit_rule_triggers_conservative_reply(
    domain, question, evidence_text, unsupported_claim
):
    """Test cases A-D: a global-classification question, evidence that only
    lists individual categories/ranges with no single unifying statement --
    the conservative reply activates and the specific unsupported claim
    never survives, regardless of whether the boundary is numeric or a
    short category code."""
    assert _is_global_classification_query(question)
    assert not _evidence_states_single_global_rule(evidence_text)
    revised = _apply_conservative_classification_reply(unsupported_claim)
    assert unsupported_claim not in revised
    assert "does not explicitly state" in revised


def test_explicit_global_rule_allows_the_normal_answer():
    """Test case E: when the evidence itself states exactly one combined
    rule, the classification question does not trigger the conservative
    path at all -- the normal generated answer stands."""
    question = "What score is considered eligible?"
    evidence_text = "Scores of 90 and above are eligible for the award."
    assert _is_global_classification_query(question)
    assert _evidence_states_single_global_rule(evidence_text)


@pytest.mark.parametrize(
    "question",
    [
        "How do I enroll?",
        "What documents do I need?",
        "Where can I go?",
        "Does it have a fee?",
        "Which office handles it?",
        "How do I request a certificate?",
        "What are the requirements?",
    ],
    ids=["F", "G", "H", "I", "J", "K", "L"],
)
def test_procedural_intent_never_activates_the_guard(question):
    """Test cases F-L: procedural/service questions never activate this
    guard, regardless of what evidence happens to be selected."""
    assert not _is_global_classification_query(question)


def test_critical_enrollment_false_positive_reproduction():
    """The exact reported false positive: Groq generates broad wording
    ("All students must complete...") in response to a purely procedural
    Enrollment question. The guard must not activate merely because of
    that wording -- activation depends only on the user's query being
    classification-shaped, which this one is not."""
    store = RoleAwareStore(
        [_chunk("Enrollment Clearance Requirements", ENROLLMENT_CLEARANCE_REFERENCE_LIST)]
    )
    broad_wording_answer = (
        "All students must complete clearance from the Accounting Office, "
        "present a Student ID from OSAS/BAO, and submit SF-Form-002 to ICTS "
        "before enrollment is finalized."
    )
    result = _ask(store, "How do I enroll?", groq_return=broad_wording_answer)
    assert result.answer == broad_wording_answer


def test_good_moral_procedural_answer_is_never_rewritten():
    """A Good Moral Certificate procedural answer must never be rewritten
    by this guard either, regardless of generated wording."""
    store = RoleAwareStore([_chunk("Good Moral Certificate", GOOD_MORAL_REFERENCE_LIST)])
    broad_wording_answer = (
        "All students requesting a Good Moral Certificate must secure "
        "clearance from the Accounting Office and have it processed at the "
        "Office of the Registrar."
    )
    result = _ask(store, "How do I get a Good Moral Certificate?", groq_return=broad_wording_answer)
    assert result.answer == broad_wording_answer


@pytest.mark.parametrize(
    "bad_answer",
    [
        "A passing grade would be any score above 69. GWA is the weighted average of all grades.",
        "A passing grade is 70+. GWA is the weighted average of all grades.",
        "The passing grades are 1.00, 2.00, 3.00, and 4.00. GWA is the weighted average of all grades.",
        "The passing range is 1.00 through 4.00. GWA is the weighted average of all grades.",
        "Grades of 1.00 or greater are passing. GWA is the weighted average of all grades.",
    ],
    ids=["above-69", "70-plus", "enumerated-list", "through-phrasing", "or-greater"],
)
def test_real_faq_selected_grading_reproduction_blocks_every_paraphrase(bad_answer):
    """The real Azure reproduction: the selected evidence is the derived
    FAQ's bullet/em-dash representation (the handbook pipe-table chunk is
    not included in this retrieval pool at all -- never forced into
    selection). The structured-row parser is allowed to remain at 0 rows;
    no bullet/table reconstruction is added or needed. Every semantic
    equivalent of the unsupported passing-boundary claim is blocked
    uniformly -- not just the one paraphrase previously reported -- because
    detection never depends on matching the specific wording used. The
    grounded GWA sentence remains usable, and confidence is downgraded."""
    faq_bullet_text = """\
Undergraduate Grading System

Frequently Asked Questions > Passing Grade and GWA

- 1.00 — 99–100 — Excellent
- 1.25 — 96–98
- 1.50 — 93–95 — Very Satisfactory
- 4.00 — 70–74 — Conditional Failure
- 5.00 — 69 and below — Failed
"""
    library = {
        "Undergraduate Grading System": _chunk(
            "Undergraduate Grading System", faq_bullet_text, score=4.9
        ),
        "GWA": _chunk("GWA", GWA_COMPUTATION_PROSE, score=4.8),
    }
    result, generation_context, _ = _ask_word_overlap(
        library, "What is the passing grade and how is GWA computed?", bad_answer
    )
    audit_records = _structured_table_records_from_text(generation_context)
    assert audit_records == []
    for fragment in ("above 69", "70+", "1.00, 2.00, 3.00, and 4.00", "1.00 through 4.00", "or greater"):
        assert fragment not in result.answer
    assert "weighted average of all grades" in result.answer
    assert "does not explicitly state" in result.answer
    assert result.confidence != "high"
