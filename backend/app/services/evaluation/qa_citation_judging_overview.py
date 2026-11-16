"""Read-only dashboard overlay for the completed Stage 3.2B-3.6 QA and
citation-claim judging results.

This is NOT part of the DB-backed EvaluationRun/EvaluationComponent
architecture (evaluation_service.py/persistence.py) -- those components
(embedding_retrieval, reranker, classify_chunk, classify_question,
answer_generation_llm, citation_verifier_llm) are created on every run
since the system's original design, so the existing durable-overlay
pattern (labeled_retrieval_overview.py / human_rag_overview.py) can
safely overlay onto them even for historical runs that predate the
overlay.

The Stage 3.2B-3.6 QA/citation-claim judging results have no such
historical component row to attach to, and -- more importantly -- their
content (dual-AI 0-4 QA dimension scores, claim-level citation
precision/completeness/support/validity) is a genuinely different
measurement from the existing `answer_generation_llm` component's
human-graded screenshot overlay (human_rag_overview.py) and from
`citation_verifier_llm`'s original empty slot. Reusing either existing
component name/overlay for this content would conflate two different
evaluation methodologies under one label. Instead this module is read
directly by a dedicated, separate admin endpoint
(GET /admin/evaluation/qa-citation-overview) -- never through
_component_schema()/the run-detail response.

Reads three already-produced, immutable artifacts, fresh, at request
time. Never writes anything, never calls an LLM, never re-runs the
chatbot or the verifier, never creates a database row.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[3]
_RUNS_ROOT = BACKEND_ROOT / "benchmarks" / "evaluation" / "qa_citation_runs"

ACCEPTED_QA_JUDGING_RUN_ID = "qacj_judging_20261110T060752Z_e9d55993"
CITATION_JUDGING_RUN_ID = "qacj_citation_judging_20261110T082650Z"
CITATION_VALIDITY_CORRECTION_RUN_ID = "qacj_citation_validity_correction_20261110T112506Z"
CAPTURE_RUN_ID = "qac_capture_20261110T063448Z_f2dfa9d3"

JUDGE_SOURCE = "ai_evaluator"
JUDGE_PRIMARY_MODEL = "dots-studio/dots-3-note-preview:free"
JUDGE_PRIMARY_PROVIDER = "AtlasCloud"
JUDGE_SECONDARY_MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"
JUDGE_SECONDARY_PROVIDER = "Nvidia"

VERIFIER_METADATA_LIMITATION_NOTE = (
    "The Stage 3.4 production citation_verification.py module that produced "
    "these displayed citations does not record resolved model/provider "
    "identity, a response id, or a call timestamp for its verifier calls -- "
    "only token usage and parsed content. This is a separate, known "
    "limitation of that production module, distinct from the QA/citation "
    "judging runs below, whose own judge calls do have full raw-response "
    "traceability."
)

CITATION_VALIDITY_CORRECTION_NOTE = (
    "citation_validity was originally miscomputed as 0/86 (0%) by a "
    "defect in resolve_citation_validity(), which cross-checked two "
    "unrelated UUID namespaces (a chunk's Chroma-ingestion document id vs. "
    "an unrelated application Document-table id). The defect was found, "
    "fixed, and independently verified: the corrected value is 86/86 "
    "(100%), confirmed to leave the other four citation metrics "
    "byte-identical. This page shows the corrected value only."
)

COVERAGE_VS_CORRECTNESS_NOTE = (
    "Stage 3.4 capture coverage (34/36 cases had at least one displayed "
    "citation) measures whether the chatbot showed any citation at all. "
    "It is a different measurement from citation-claim judging below "
    "(precision, completeness, claim support, validity), which measures "
    "whether what was shown -- or not shown -- was actually correct. Do "
    "not read citation_validity (100%) as citation claim support (63.8%) "
    "-- they answer different questions."
)


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def load_qa_citation_judging_overview() -> dict[str, Any] | None:
    """Returns the combined QA + citation-claim judging overview, or None
    if any of the three required artifacts is unavailable -- an honest
    "not available" signal, never a fabricated placeholder."""
    qa_summary = _read_json(_RUNS_ROOT / ACCEPTED_QA_JUDGING_RUN_ID / "judging_summary.json")
    citation_summary = _read_json(_RUNS_ROOT / CITATION_JUDGING_RUN_ID / "judging_summary.json")
    correction = _read_json(
        _RUNS_ROOT / CITATION_VALIDITY_CORRECTION_RUN_ID / "citation_validity_correction.json"
    )
    if qa_summary is None or citation_summary is None or correction is None:
        return None

    qa_aggregation = qa_summary.get("qa_aggregation") or {}
    ie_aggregation = qa_summary.get("insufficient_evidence_aggregation") or {}
    population = qa_summary.get("population_summary") or {}
    citation_aggregation = citation_summary.get("citation_aggregation") or {}

    corrected_validity = correction.get("corrected_citation_validity") or {}
    original_validity = correction.get("original_citation_validity") or {}

    return {
        "available": True,
        "judge_source": JUDGE_SOURCE,
        "judges": {
            "primary_model": JUDGE_PRIMARY_MODEL,
            "primary_provider": JUDGE_PRIMARY_PROVIDER,
            "secondary_model": JUDGE_SECONDARY_MODEL,
            "secondary_provider": JUDGE_SECONDARY_PROVIDER,
        },
        "qa": {
            "dimension_means": qa_aggregation.get("dimension_means"),
            "dimension_distributions": qa_aggregation.get("dimension_distributions"),
            "judged_count": qa_aggregation.get("judged_count"),
            "judging_failed_partial_count": qa_aggregation.get("judging_failed_partial_count"),
            "judging_failed_total_count": qa_aggregation.get("judging_failed_total_count"),
            "eligible_count": qa_aggregation.get("eligible_count"),
            "excluded_count": qa_aggregation.get("excluded_count"),
            "excluded_counts_by_reason": qa_aggregation.get("excluded_counts_by_reason"),
            "judge_disagreement_rate": qa_aggregation.get("judge_disagreement_rate"),
            "disagreement_by_criterion_counts": qa_aggregation.get("disagreement_by_criterion_counts"),
            "by_category": qa_aggregation.get("by_category"),
            "insufficient_evidence": {
                "total_count": ie_aggregation.get("total_count"),
                "judged_count": ie_aggregation.get("judged_count"),
                "judging_failed_partial_count": ie_aggregation.get("judging_failed_partial_count"),
                "judging_failed_total_count": ie_aggregation.get("judging_failed_total_count"),
                "correctly_declined_agreement_count": ie_aggregation.get(
                    "correctly_declined_agreement_count"
                ),
                "correctly_declined_disagreement_count": ie_aggregation.get(
                    "correctly_declined_disagreement_count"
                ),
                "unsupported_claim_detected_agreement_count": ie_aggregation.get(
                    "unsupported_claim_detected_agreement_count"
                ),
                "unsupported_claim_detected_disagreement_count": ie_aggregation.get(
                    "unsupported_claim_detected_disagreement_count"
                ),
            },
            "fallback_vs_genuine_counts": population.get("fallback_vs_genuine_counts"),
            "ineligible_excluded_by_reason": population.get("ineligible_excluded_by_reason"),
        },
        "citation": {
            "citation_precision": citation_aggregation.get("citation_precision"),
            "citation_completeness": citation_aggregation.get("citation_completeness"),
            "claim_support_rate": citation_aggregation.get("claim_support_rate"),
            "unsupported_claim_rate": citation_aggregation.get("unsupported_claim_rate"),
            "citation_validity": corrected_validity,
            "citation_validity_original_defective": original_validity,
            "judged_case_count": citation_aggregation.get("judged_case_count"),
            "judge_data_points_aggregated": citation_aggregation.get("judge_data_points_aggregated"),
            "judging_failed_partial_count": citation_aggregation.get("judging_failed_partial_count"),
            "judging_failed_total_count": citation_aggregation.get("judging_failed_total_count"),
            "eligible_count": citation_aggregation.get("eligible_count"),
            "excluded_count": citation_aggregation.get("excluded_count"),
        },
        "capture_coverage": {
            "capture_run_id": CAPTURE_RUN_ID,
            "total_cases": 36,
            "cases_with_displayed_citations": 34,
            "note": COVERAGE_VS_CORRECTNESS_NOTE,
        },
        "source_run_ids": {
            "qa_judging_run_id": ACCEPTED_QA_JUDGING_RUN_ID,
            "citation_judging_run_id": CITATION_JUDGING_RUN_ID,
            "citation_validity_correction_run_id": CITATION_VALIDITY_CORRECTION_RUN_ID,
            "capture_run_id": CAPTURE_RUN_ID,
        },
        "limitations": [
            VERIFIER_METADATA_LIMITATION_NOTE,
            CITATION_VALIDITY_CORRECTION_NOTE,
            COVERAGE_VS_CORRECTNESS_NOTE,
        ],
    }
