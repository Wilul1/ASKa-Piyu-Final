"""Score semantics: what each retrieval score means, and which gates may use it.

Background (measured against the production Chroma store, 751 chunks,
``intfloat/multilingual-e5-small``):

* Cosine similarity (``original_score``) is **not** discriminative with this
  encoder.  A perfectly relevant chunk scores ~0.87 and a completely unrelated
  one (``"Will it rain tomorrow?"`` → ``Infrastructure Project``) scores ~0.80.
  Every chunk in every result set lands in ~0.79-0.91.
* The heuristic rerank score (``reranked_score``) is unbounded — production
  values run ~1.0 to ~4.7 depending only on how many topical boosts fired.

So neither score can carry an absolute "is this good evidence?" threshold.
These tests pin the semantics down and prove the confidence/clarify gates are
driven by evidence *alignment*, which is scale-free.
"""

from __future__ import annotations

import pytest

from app.services.chroma_store import RetrievedChunk
from app.services.knowledge_taxonomy import classify_question
from app.services.qa.question_answering import (
    _confidence_for,
    _context_filter_reasons,
    _has_strong_penalty,
    _positive_reasons,
    _retrieval_quality,
)

# Real (similarity, rerank) pairs captured from the production store.
PROD_STRONG_SIMILARITY = 0.8677
PROD_STRONG_RERANK = 4.6777
PROD_VAGUE_SIMILARITY = 0.8453
PROD_VAGUE_RERANK = 1.0753
PROD_FLAT_TOP_RERANK = 2.2402
PROD_FLAT_TAIL_RERANK = 2.1727

# Every properly ingested chunk carries these three, whatever the question is.
HYGIENE_REASONS = (
    "boost_valid_source_metadata",
    "boost_has_page_number",
    "boost_level2_citation_ready",
)


def chunk(
    section: str,
    text: str,
    *,
    similarity: float,
    rerank: float,
    reasons: tuple[str, ...] = (),
    question_for_taxonomy: str | None = None,
    audience: str = "both",
    document_type: str | None = None,
) -> RetrievedChunk:
    """A chunk shaped like production: cosine in ``original_score``, rerank in both
    ``reranked_score`` and ``relevance_score`` (``rerank_chunks`` overwrites it)."""
    metadata: dict[str, object] = {
        "source_section": section,
        "section": section,
        "audience": audience,
        "page_start": 41,
    }
    if document_type is not None:
        metadata["document_type"] = document_type
    if question_for_taxonomy is not None:
        # Stamp the same taxonomy labels ingest would write for this topic rather
        # than hardcoding a category name this test would have to keep in sync.
        labels = classify_question(question_for_taxonomy)
        metadata["category"] = labels.category
        metadata["subcategory"] = labels.subcategory
    return RetrievedChunk(
        document_id=section.lower().replace(" ", "-"),
        title="LSPU Citizen's Charter",
        source_filename="charter.pdf",
        chunk_index=0,
        text=text,
        relevance_score=rerank,
        original_score=similarity,
        reranked_score=rerank,
        rerank_reasons=list(reasons) or ["semantic_similarity"],
        metadata=metadata,
    )


# --- the three score concepts are distinct and separately readable -----------


def test_similarity_and_rerank_score_are_separate_readable_concepts():
    item = chunk(
        "Issuance of Transcript of Records",
        "The Registrar releases the TOR after payment.",
        similarity=PROD_STRONG_SIMILARITY,
        rerank=PROD_STRONG_RERANK,
    )

    assert item.vector_similarity == pytest.approx(PROD_STRONG_SIMILARITY)
    assert item.rerank_score == pytest.approx(PROD_STRONG_RERANK)
    # How much topical evidence the reranker found, independent of the encoder.
    assert item.heuristic_support == pytest.approx(
        PROD_STRONG_RERANK - PROD_STRONG_SIMILARITY
    )
    # relevance_score stays the ranking score for API/debug back-compat.
    assert item.relevance_score == pytest.approx(item.rerank_score)


def test_similarity_alone_cannot_separate_relevant_from_unrelated_evidence():
    """Guards the reason the gates must not threshold on cosine similarity."""
    relevant = chunk(
        "Issuance of Transcript of Records",
        "TOR fee is paid at the Cashier.",
        similarity=PROD_STRONG_SIMILARITY,
        rerank=PROD_STRONG_RERANK,
    )
    unrelated = chunk(
        "Infrastructure Project",
        "Preparation of detailed architectural and engineering drawings.",
        similarity=0.8044,
        rerank=1.3944,
    )

    assert abs(relevant.vector_similarity - unrelated.vector_similarity) < 0.1


# --- strong, aligned evidence may still reach high confidence ----------------


STRONG_QUESTION = "How much is the fee for a Transcript of Records?"


def strong_evidence() -> list[RetrievedChunk]:
    """The real top-2 for this question, with the reasons production attaches —
    including ``penalty_unrelated_procedure``, which the reranker puts on every
    service card when the question is not phrased as a how-to."""
    return [
        chunk(
            "Issuance of Transcript of Records/Transfer Credentials/Certifications",
            "Transcript of Records. Fees: PHP 100.00 per page. Client pays at the Cashier.",
            similarity=PROD_STRONG_SIMILARITY,
            rerank=PROD_STRONG_RERANK,
            reasons=(
                "title_path_keyword_match",
                "boost_taxonomy_service_identity",
                "boost_chunk_with_total_fees",
                "metadata_category_match",
                "penalty_unrelated_procedure",
                *HYGIENE_REASONS,
            ),
            question_for_taxonomy=STRONG_QUESTION,
            document_type="citizen_charter",
        ),
        chunk(
            "Authentication of Documents",
            "Authentication of transcript of records and other documents.",
            similarity=0.8581,
            rerank=3.4881,
            reasons=(
                "title_path_keyword_match",
                "metadata_category_match",
                "penalty_unrelated_procedure",
                *HYGIENE_REASONS,
            ),
            question_for_taxonomy=STRONG_QUESTION,
        ),
    ]


def test_strong_aligned_evidence_can_be_high_confidence():
    evidence = strong_evidence()

    assert (
        _confidence_for(evidence, evidence, "The TOR fee is PHP 100.00 per page.", STRONG_QUESTION)
        == "high"
    )


def test_strong_aligned_evidence_is_not_sent_to_clarification():
    evidence = strong_evidence()

    quality = _retrieval_quality(
        STRONG_QUESTION, evidence, evidence, broad_query=False, collection_mode=False
    )

    assert quality["should_clarify"] is False


def test_procedural_wording_penalty_does_not_look_like_noisy_context():
    """``penalty_unrelated_procedure`` lands on the correct rank-1 TOR service
    card, so it must not be read as "the context is noise"."""
    evidence = strong_evidence()

    assert all("penalty_unrelated_procedure" in (item.rerank_reasons or []) for item in evidence)
    assert not any(_has_strong_penalty(item) for item in evidence)


# --- weak evidence must not be high confidence ------------------------------


def test_weak_unaligned_evidence_is_not_high_confidence():
    """Production-scale rerank scores must not buy confidence on their own."""
    question = "How many absences before I am dropped from a subject?"
    evidence = [
        chunk(
            "Stipend: **",
            "Stipend: ** P 5,000.00 per month for the scholar.",
            similarity=0.8581,
            rerank=3.1081,
            reasons=HYGIENE_REASONS,
        ),
        chunk(
            "Vacation service credits of teachers",
            "Vacation service credits are earned during summer.",
            similarity=0.8462,
            rerank=3.0962,
            reasons=HYGIENE_REASONS,
        ),
    ]

    assert _confidence_for(evidence, evidence, "Some answer.", question) != "high"


def test_metadata_hygiene_boosts_are_not_topical_support():
    """They fire on every well-formed chunk, so they cannot stand in for
    "retrieval found something about this question"."""
    item = chunk(
        "Library Reference Assistance",
        "Library staff assist clients with references.",
        similarity=0.8247,
        rerank=1.0547,
        reasons=HYGIENE_REASONS,
    )

    assert _positive_reasons(item) == []


def test_penalised_context_is_not_high_confidence():
    question = "What are the requirements for enrollment?"
    evidence = [
        chunk(
            "Enrollment",
            "Present the registration form at the College.",
            similarity=0.8408,
            rerank=2.9608,
            reasons=("title_path_keyword_match", "metadata_category_match", *HYGIENE_REASONS),
            question_for_taxonomy=question,
        ),
        chunk(
            "Administrative Sanctions",
            "Sanctions for erring personnel.",
            similarity=0.8287,
            rerank=1.0587,
            reasons=("penalty_disciplinary_offense_out_of_domain", *HYGIENE_REASONS),
        ),
    ]

    assert _confidence_for(evidence, evidence, "Some answer.", question) != "high"


# --- vague questions must not inherit confidence from unrelated chunks ------


def vague_help_evidence() -> list[RetrievedChunk]:
    """Exactly what production returns for ``help``: eight unrelated services,
    all within 0.02 rerank score of each other."""
    titles = [
        ("Provision of Technical Assistance/Expertise", 0.8453, 1.0753),
        ("Breastfeeding and Lactating Assistance", 0.8358, 1.0658),
        ("Provision of Child Friendly Space", 0.8318, 1.0618),
        ("Mental Health Services/Treatment", 0.8292, 1.0592),
        ("Library Reference Assistance", 0.8247, 1.0547),
    ]
    return [
        chunk(
            title,
            f"{title}. Clients may request this service.",
            similarity=sim,
            rerank=rr,
            reasons=HYGIENE_REASONS,
        )
        for title, sim, rr in titles
    ]


def test_vague_help_is_not_high_confidence():
    evidence = vague_help_evidence()

    assert _confidence_for(evidence, evidence, "Here is what LSPU offers.", "help") != "high"


def test_vague_help_is_sent_to_clarification():
    evidence = vague_help_evidence()

    quality = _retrieval_quality(
        "help", evidence, evidence, broad_query=False, collection_mode=False
    )

    assert quality["should_clarify"] is True


def contextless_cost_evidence() -> list[RetrievedChunk]:
    """Production result for a first-turn ``How much does it cost?``: unrelated
    fees from five different documents, rerank spread of 0.18."""
    titles = [
        ("The OJT/SIPP Coordinator conducts regular monitoring", 0.8283, 1.2383),
        ("Examination Fee", 0.8382, 1.0682),
        ("Book Allowance/Internet Fee (maximum):**", 0.8350, 1.0650),
        ("Library Reference Assistance", 0.8287, 1.0587),
        ("Procurement through appropriate mode", 0.8270, 1.0570),
    ]
    return [
        chunk(
            title,
            f"{title}. Amount as indicated.",
            similarity=sim,
            rerank=rr,
            reasons=HYGIENE_REASONS,
        )
        for title, sim, rr in titles
    ]


def test_contextless_cost_question_is_not_high_confidence():
    evidence = contextless_cost_evidence()

    assert (
        _confidence_for(evidence, evidence, "The fee is P50.00.", "How much does it cost?")
        != "high"
    )


def test_contextless_cost_question_is_sent_to_clarification():
    evidence = contextless_cost_evidence()

    quality = _retrieval_quality(
        "How much does it cost?",
        evidence,
        evidence,
        broad_query=False,
        collection_mode=False,
    )

    assert quality["should_clarify"] is True


def test_same_cost_question_is_answerable_once_a_topic_is_active():
    """The fix must not break the Good Moral → requirements → cost chain."""
    question = "How much does the Good Moral Certificate cost?"
    evidence = [
        chunk(
            "Issuance of Good Moral Certificate (Undergraduate)",
            "Good Moral Certificate. Fees: PHP 50.00 per copy.",
            similarity=0.8809,
            rerank=3.0409,
            reasons=(
                "title_path_keyword_match",
                "boost_chunk_with_total_fees",
                "metadata_category_match",
                *HYGIENE_REASONS,
            ),
            question_for_taxonomy=question,
        ),
    ]

    quality = _retrieval_quality(
        question,
        evidence,
        evidence,
        broad_query=False,
        collection_mode=False,
        active_topic="Good Moral Certificate",
    )

    assert quality["should_clarify"] is False
    assert (
        _confidence_for(
            evidence,
            evidence,
            "The Good Moral Certificate costs PHP 50.00 per copy.",
            question,
            active_topic="Good Moral Certificate",
        )
        != "low"
    )


# --- the context keep-window must work on the production score scale --------


def test_close_to_rank_1_keeps_a_flat_cluster_of_correct_sections():
    """Five correct grading sections score 2.17-2.24 in production. The window
    that keeps near-best evidence must recognise them as near-best."""
    tail = chunk(
        "Policies for INC",
        "An INC must be completed within one year.",
        similarity=0.8277,
        rerank=PROD_FLAT_TAIL_RERANK,
    )

    reasons = _context_filter_reasons(
        chunk=tail,
        normalized_query="what is the passing grade",
        query_domain=None,
        top_score=PROD_FLAT_TOP_RERANK,
        rank=4,
    )

    assert "keep_close_to_rank_1" in reasons


def test_close_to_rank_1_still_rejects_a_clearly_weaker_chunk():
    weaker = chunk(
        "Library Reference Assistance",
        "Library staff assist clients with references.",
        similarity=0.8247,
        rerank=PROD_VAGUE_RERANK,
    )

    reasons = _context_filter_reasons(
        chunk=weaker,
        normalized_query="how much is the fee for a transcript of records",
        query_domain=None,
        top_score=PROD_STRONG_RERANK,
        rank=6,
    )

    assert "keep_close_to_rank_1" not in reasons
