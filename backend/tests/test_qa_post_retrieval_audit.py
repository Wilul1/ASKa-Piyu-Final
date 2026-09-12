"""Post-retrieval audit regressions (separate from Phase 2A retrieval ranking).

Exercises query → role/audience → retrieval slice → rerank scores already on
chunks → service preference → context selection → generation/fallback → answer.
Does not retune Phase 2A.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services.chroma_store import RetrievedChunk, select_role_visible_hits
from app.services.qa.groq_answer_service import GroqAnswerError
from app.services.qa.question_answering import (
    _answer_contradicts_table_records,
    _canonical_service_names_in_text,
    _confidence_for,
    _format_structured_tables,
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
    else:
        groq_kw["return_value"] = groq_return or "Grounded answer from retrieved context."
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
