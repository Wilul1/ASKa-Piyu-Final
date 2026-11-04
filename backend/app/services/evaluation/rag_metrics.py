"""Pure RAG/LLM metric aggregation: faithfulness, answer relevancy, context
precision/recall, answer correctness, citation set precision/recall.

Nothing here calls Groq or any judge model -- every function takes an
already-computed per-case result (a judge score already obtained, or an
already-built ``citation_verification.VerificationOutcome``) and only
aggregates/derives numbers from that data. The real LLM-judge calls and
the real ``citation_verification.verify_citations`` call belong to
``evaluation_service`` (the only module in this package that performs
I/O), which builds the ``RagCaseResult``/``VerificationOutcome`` objects
this module consumes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.services.evaluation.classification_metrics import EmptyDatasetError

if TYPE_CHECKING:
    from app.services.qa.citation_verification import VerificationOutcome


@dataclass(frozen=True)
class RagCaseResult:
    """One evaluated question/answer case's RAG metrics.

    Every metric field is ``None`` when it could not be computed for this
    case (e.g. zero claims for faithfulness, no reference answer for
    answer correctness) -- never a fabricated 0.0 standing in for "not
    computed". ``judge_source`` records how each non-citation score was
    produced, per approval condition 2 (distinguish LLM-as-judge from
    human-verified results) -- it is recorded per case, not assumed
    uniform across a whole run, since a human-reviewed subset can coexist
    with judge-scored cases in the same dataset.
    """

    case_id: str
    faithfulness: float | None = None
    answer_relevancy: float | None = None
    context_precision: float | None = None
    context_recall: float | None = None
    answer_correctness: float | None = None
    citation_set_precision: float | None = None
    citation_set_recall: float | None = None
    claim_support_rate: float | None = None
    judge_source: str = "llm_judge"  # "llm_judge" or "human_verified"


@dataclass(frozen=True)
class RagMetrics:
    case_count: int
    llm_judge_case_count: int
    human_verified_case_count: int
    faithfulness: float | None
    answer_relevancy: float | None
    context_precision: float | None
    context_recall: float | None
    answer_correctness: float | None
    citation_set_precision: float | None
    citation_set_recall: float | None
    claim_support_rate: float | None
    # Per-metric count of cases that actually contributed a value (not None) --
    # lets a consumer see e.g. "answer_correctness averaged over 8 of 20 cases"
    # rather than assuming every metric used the full case_count.
    metric_contributing_counts: dict[str, int]


_METRIC_FIELDS = (
    "faithfulness",
    "answer_relevancy",
    "context_precision",
    "context_recall",
    "answer_correctness",
    "citation_set_precision",
    "citation_set_recall",
    "claim_support_rate",
)


def aggregate_rag_metrics(cases: list[RagCaseResult]) -> RagMetrics:
    if not cases:
        raise EmptyDatasetError("Cannot aggregate RAG metrics on an empty case set.")

    averages: dict[str, float | None] = {}
    contributing_counts: dict[str, int] = {}
    for field in _METRIC_FIELDS:
        values = [v for case in cases if (v := getattr(case, field)) is not None]
        contributing_counts[field] = len(values)
        averages[field] = round(sum(values) / len(values), 4) if values else None

    human_verified_count = sum(1 for case in cases if case.judge_source == "human_verified")

    return RagMetrics(
        case_count=len(cases),
        llm_judge_case_count=len(cases) - human_verified_count,
        human_verified_case_count=human_verified_count,
        faithfulness=averages["faithfulness"],
        answer_relevancy=averages["answer_relevancy"],
        context_precision=averages["context_precision"],
        context_recall=averages["context_recall"],
        answer_correctness=averages["answer_correctness"],
        citation_set_precision=averages["citation_set_precision"],
        citation_set_recall=averages["citation_set_recall"],
        claim_support_rate=averages["claim_support_rate"],
        metric_contributing_counts=contributing_counts,
    )


def citation_metrics_from_outcome(
    outcome: "VerificationOutcome",
    gold_citation_ids: set[str],
) -> dict[str, float | None]:
    """Derive faithfulness/claim-support-rate/citation-set precision+recall
    from an already-computed ``VerificationOutcome`` plus a gold citation
    set for this case.

    ``gold_citation_ids`` must be real, reviewed labels -- a case with no
    gold citation ids has nothing to score citation-set precision/recall
    against and must be excluded by the caller (see
    ``app.services.evaluation.datasets``) before reaching this function,
    the same contract ``retrieval_metrics.evaluate_retrieval`` uses for
    ``relevant_ids``.

    Returns ``None`` for ALL FOUR fields whenever
    ``outcome.verifier_invoked`` and ``outcome.verifier_succeeded`` are not
    both ``True`` -- deliberately, even for ``citation_set_precision``/
    ``citation_set_recall``. A never-invoked or failed verifier leaves
    ``outcome.verified_citation_ids`` empty by fail-closed construction,
    and scoring that empty set against gold would silently read as "the
    LLM checked and found nothing," which is not what happened -- no LLM
    citation evaluation occurred for this case at all. Callers must not
    report an LLM evaluation result when no LLM call occurred.
    """
    if not gold_citation_ids:
        raise ValueError(
            "gold_citation_ids must be non-empty; exclude cases with no gold citation "
            "labels before calling citation_metrics_from_outcome."
        )

    result: dict[str, float | None] = {
        "faithfulness": None,
        "claim_support_rate": None,
        "citation_set_precision": None,
        "citation_set_recall": None,
    }

    if not (outcome.verifier_invoked and outcome.verifier_succeeded):
        return result

    total_claims = len(outcome.claims)
    supported_claims = sum(1 for ids in outcome.per_claim_verified_ids.values() if ids)
    if total_claims:
        support_rate = supported_claims / total_claims
        result["faithfulness"] = round(support_rate, 4)
        result["claim_support_rate"] = round(support_rate, 4)

    predicted = set(outcome.verified_citation_ids)
    gold = set(gold_citation_ids)
    intersection = predicted & gold
    result["citation_set_precision"] = round(len(intersection) / len(predicted), 4) if predicted else 0.0
    result["citation_set_recall"] = round(len(intersection) / len(gold), 4)

    return result
