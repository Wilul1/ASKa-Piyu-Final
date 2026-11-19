"""Run Model Evaluation against the labeled datasets.

Calls the live classify / retrieve / answer / citation components as
read-only checks. Metrics helpers stay pure; this file owns the I/O.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.config import settings
from app.services.chroma_store import RetrievedChunk, get_knowledge_base_store
from app.services.embeddings import current_embedding_model_label
from app.services.evaluation.classification_metrics import (
    ClassificationMetrics,
    evaluate_classification,
)
from app.services.evaluation.confusion_matrix import ConfusionMatrix, build_confusion_matrix
from app.services.evaluation.datasets import (
    DatasetLoadResult,
    load_classification_dataset,
    load_rag_dataset,
    load_retrieval_dataset,
)
from app.services.evaluation.labeled_retrieval_store import open_labeled_retrieval_store
from app.services.evaluation.performance_metrics import (
    CallRecord,
    PerformanceMetrics,
    evaluate_performance,
)
from app.services.evaluation.rag_metrics import (
    RagCaseResult,
    RagMetrics,
    aggregate_rag_metrics,
    citation_metrics_from_outcome,
)
from app.services.evaluation.retrieval_metrics import (
    RetrievalMetrics,
    RetrievalQueryResult,
    evaluate_retrieval as evaluate_retrieval_metric,
)
from app.services.knowledge_taxonomy import classify_chunk, classify_question
from app.services.qa.citation_verification import CandidateEvidence, verify_citations
from app.services.qa.groq_answer_service import GroqAnswerError, generate_groq_answer
from app.services.qa.question_answering import format_retrieved_context

logger = logging.getLogger(__name__)

_EVALUATION_DIR = Path(__file__).resolve().parents[3] / "benchmarks" / "evaluation"
DEFAULT_CLASSIFICATION_DATASET_PATH = _EVALUATION_DIR / "classification_eval_dataset.json"
DEFAULT_RETRIEVAL_DATASET_PATH = _EVALUATION_DIR / "retrieval_relevance_dataset.json"
DEFAULT_RAG_DATASET_PATH = _EVALUATION_DIR / "rag_eval_dataset.json"

EVALUATED = "evaluated"
NOT_EVALUABLE = "not_evaluable"
FAILED = "failed"

DEFAULT_RETRIEVAL_K = 5
DEFAULT_RETRIEVAL_CANDIDATE_POOL_SIZE = 20
_CASE_TEXT_MAX_CHARS = 2000


def _truncate_case_text(value: str | None) -> str | None:
    if value is None:
        return None
    return value[:_CASE_TEXT_MAX_CHARS]


@dataclass(frozen=True)
class ComponentModelInfo:
    """Model/config used for one evaluated component."""

    component: str
    model_name: str
    shares_model_with: str | None = None
    allow_llm_fallback: bool | None = None


@dataclass(frozen=True)
class CaseResultRecord:
    """Per-case prediction snapshot for reproducibility."""

    case_id: str
    predicted: str | None = None
    expected: str | None = None
    correct: bool | None = None
    latency_ms: float | None = None


@dataclass(frozen=True)
class ComponentEvaluationResult:
    component: str
    status: str  # evaluated | not_evaluable | failed
    reason: str | None
    model_info: ComponentModelInfo
    case_count: int
    skipped_unlabeled_count: int
    note: str | None = None
    classification_metrics: ClassificationMetrics | None = None
    confusion_matrix: ConfusionMatrix | None = None
    retrieval_metrics_embedding_only: RetrievalMetrics | None = None
    retrieval_metrics_reranked: RetrievalMetrics | None = None
    rag_metrics: RagMetrics | None = None
    performance_metrics: PerformanceMetrics | None = None
    case_results: tuple[CaseResultRecord, ...] = ()


@dataclass(frozen=True)
class EvaluationRunResult:
    components: tuple[ComponentEvaluationResult, ...]
    dataset_versions: dict[str, str]
    dataset_sha256: dict[str, str] = field(default_factory=dict)


class CallTracker:
    """Track first vs later calls to each model key within one run."""

    def __init__(self) -> None:
        self._seen: set[str] = set()

    def is_first_call_in_run(self, model_key: str) -> bool:
        first_call = model_key not in self._seen
        self._seen.add(model_key)
        return first_call


def _failed_placeholder(component: str, exc: BaseException) -> ComponentEvaluationResult:
    """Mark one component failed without killing the rest of the run."""
    return ComponentEvaluationResult(
        component=component,
        status=FAILED,
        reason=f"{type(exc).__name__}: {exc}"[:500],
        model_info=ComponentModelInfo(
            component=component,
            model_name="unknown (evaluation raised before model info could be determined)",
        ),
        case_count=0,
        skipped_unlabeled_count=0,
    )


def _chunk_identity(chunk: RetrievedChunk) -> str:
    """Match Chroma chunk ids used in labeled datasets (document_id::index)."""
    metadata = chunk.metadata or {}
    chunk_id = metadata.get("chunk_id")
    if chunk_id:
        return str(chunk_id)
    return f"{chunk.document_id}::{chunk.chunk_index}"


def model_inventory() -> list[ComponentModelInfo]:
    """Components covered by Model Evaluation, from current settings."""
    citation_verifier_model = (settings.citation_verifier_model or "").strip() or None
    return [
        ComponentModelInfo(component="embedding_retrieval", model_name=current_embedding_model_label()),
        ComponentModelInfo(
            component="reranker",
            model_name="rule-based query expansion + heuristic boosting (not a trained model)",
        ),
        ComponentModelInfo(
            component="classify_chunk",
            model_name=f"rule+similarity+optional_llm({settings.groq_model})",
            allow_llm_fallback=True,
        ),
        ComponentModelInfo(
            component="classify_question",
            model_name="rule+similarity (never calls an LLM)",
            allow_llm_fallback=False,
        ),
        ComponentModelInfo(component="answer_generation_llm", model_name=settings.groq_model),
        ComponentModelInfo(
            component="citation_verifier_llm",
            model_name=citation_verifier_model or settings.groq_model,
            shares_model_with="answer_generation_llm" if citation_verifier_model is None else None,
        ),
    ]


def evaluate_classify_chunk(dataset: DatasetLoadResult, *, allow_llm: bool) -> ComponentEvaluationResult:
    cases = [c for c in dataset.labeled_cases if c.get("component") == "classify_chunk"]
    model_info = ComponentModelInfo(
        component="classify_chunk",
        model_name=(
            f"rule+similarity+optional_llm({settings.groq_model})"
            if allow_llm
            else "rule+similarity (LLM fallback disabled for this evaluation run)"
        ),
        allow_llm_fallback=allow_llm,
    )
    if not cases:
        return ComponentEvaluationResult(
            component=f"classify_chunk(allow_llm={allow_llm})",
            status=NOT_EVALUABLE,
            reason="no labeled classify_chunk cases in classification_eval_dataset.json",
            model_info=model_info,
            case_count=0,
            skipped_unlabeled_count=dataset.unlabeled_count,
        )
    y_true = [str(case["true_label"]) for case in cases]
    y_pred = [classify_chunk(case["text"], allow_llm=allow_llm).subcategory for case in cases]
    metrics = evaluate_classification(y_true, y_pred)
    matrix = build_confusion_matrix(y_true, y_pred)
    case_results = tuple(
        CaseResultRecord(case_id=str(case["case_id"]), predicted=pred, expected=true, correct=(pred == true))
        for case, pred, true in zip(cases, y_pred, y_true)
    )
    return ComponentEvaluationResult(
        component=f"classify_chunk(allow_llm={allow_llm})",
        status=EVALUATED,
        reason=None,
        model_info=model_info,
        classification_metrics=metrics,
        confusion_matrix=matrix,
        case_count=len(cases),
        skipped_unlabeled_count=dataset.unlabeled_count,
        case_results=case_results,
    )


def evaluate_classify_question(dataset: DatasetLoadResult) -> ComponentEvaluationResult:
    cases = [c for c in dataset.labeled_cases if c.get("component") == "classify_question"]
    model_info = ComponentModelInfo(
        component="classify_question",
        model_name="rule+similarity (never calls an LLM)",
        allow_llm_fallback=False,
    )
    if not cases:
        return ComponentEvaluationResult(
            component="classify_question",
            status=NOT_EVALUABLE,
            reason="no labeled classify_question cases in classification_eval_dataset.json",
            model_info=model_info,
            case_count=0,
            skipped_unlabeled_count=dataset.unlabeled_count,
        )
    y_true = [str(case["true_label"]) for case in cases]
    y_pred = [classify_question(case["text"]).subcategory for case in cases]
    metrics = evaluate_classification(y_true, y_pred)
    matrix = build_confusion_matrix(y_true, y_pred)
    case_results = tuple(
        CaseResultRecord(case_id=str(case["case_id"]), predicted=pred, expected=true, correct=(pred == true))
        for case, pred, true in zip(cases, y_pred, y_true)
    )
    return ComponentEvaluationResult(
        component="classify_question",
        status=EVALUATED,
        reason=None,
        model_info=model_info,
        classification_metrics=metrics,
        confusion_matrix=matrix,
        case_count=len(cases),
        skipped_unlabeled_count=dataset.unlabeled_count,
        case_results=case_results,
    )


def evaluate_retrieval(
    dataset: DatasetLoadResult,
    *,
    store: Any,
    k: int = DEFAULT_RETRIEVAL_K,
    candidate_pool_size: int = DEFAULT_RETRIEVAL_CANDIDATE_POOL_SIZE,
) -> tuple[ComponentEvaluationResult, ComponentEvaluationResult]:
    """Score embedding-only vs reranked from one search call per query."""
    cases = dataset.labeled_cases
    embedding_model_info = ComponentModelInfo(
        component="embedding_retrieval", model_name=current_embedding_model_label()
    )
    reranker_model_info = ComponentModelInfo(
        component="reranker",
        model_name="rule-based query expansion + heuristic boosting (not a trained model)",
    )
    if not cases:
        reason = "no labeled cases in retrieval_relevance_dataset.json"
        return (
            ComponentEvaluationResult(
                component="embedding_retrieval",
                status=NOT_EVALUABLE,
                reason=reason,
                model_info=embedding_model_info,
                case_count=0,
                skipped_unlabeled_count=dataset.unlabeled_count,
            ),
            ComponentEvaluationResult(
                component="reranker",
                status=NOT_EVALUABLE,
                reason=reason,
                model_info=reranker_model_info,
                case_count=0,
                skipped_unlabeled_count=dataset.unlabeled_count,
            ),
        )

    pool_size = max(candidate_pool_size, k)
    embedding_results: list[RetrievalQueryResult] = []
    reranked_results: list[RetrievalQueryResult] = []
    embedding_case_results: list[CaseResultRecord] = []
    reranked_case_results: list[CaseResultRecord] = []
    total = len(cases)
    for index, case in enumerate(cases, start=1):
        logger.info("evaluate_retrieval: query %s/%s id=%s", index, total, case.get("query_id"))
        candidates = store.search(case["query"], top_k=pool_size, raw_k=pool_size)
        reranked_ids = tuple(_chunk_identity(c) for c in candidates[:k])
        embedding_ordered = sorted(candidates, key=lambda c: c.vector_similarity, reverse=True)
        embedding_ids = tuple(_chunk_identity(c) for c in embedding_ordered[:k])
        relevant = frozenset(str(v) for v in case["relevant_ids"])
        graded = case.get("graded_relevance")
        embedding_results.append(
            RetrievalQueryResult(
                query_id=case["query_id"],
                retrieved_ids=embedding_ids,
                relevant_ids=relevant,
                graded_relevance=graded,
            )
        )
        reranked_results.append(
            RetrievalQueryResult(
                query_id=case["query_id"],
                retrieved_ids=reranked_ids,
                relevant_ids=relevant,
                graded_relevance=graded,
            )
        )
        expected = ",".join(sorted(relevant))
        embedding_case_results.append(
            CaseResultRecord(
                case_id=str(case["query_id"]),
                predicted=",".join(embedding_ids),
                expected=expected,
                correct=any(doc_id in relevant for doc_id in embedding_ids),
            )
        )
        reranked_case_results.append(
            CaseResultRecord(
                case_id=str(case["query_id"]),
                predicted=",".join(reranked_ids),
                expected=expected,
                correct=any(doc_id in relevant for doc_id in reranked_ids),
            )
        )

    embedding_metrics = evaluate_retrieval_metric(embedding_results, k=k)
    reranked_metrics = evaluate_retrieval_metric(reranked_results, k=k)

    embedding_result = ComponentEvaluationResult(
        component="embedding_retrieval",
        status=EVALUATED,
        reason=None,
        model_info=embedding_model_info,
        retrieval_metrics_embedding_only=embedding_metrics,
        case_count=len(cases),
        skipped_unlabeled_count=dataset.unlabeled_count,
        note="Scored on the isolated evaluation corpus for these 12 labels, not live student Chroma.",
        case_results=tuple(embedding_case_results),
    )
    reranker_result = ComponentEvaluationResult(
        component="reranker",
        status=EVALUATED,
        reason=None,
        model_info=reranker_model_info,
        retrieval_metrics_embedding_only=embedding_metrics,
        retrieval_metrics_reranked=reranked_metrics,
        case_count=len(cases),
        skipped_unlabeled_count=dataset.unlabeled_count,
        note="Same queries and corpus; compares embedding-only vs rule-based rerank order.",
        case_results=tuple(reranked_case_results),
    )
    return embedding_result, reranker_result


def evaluate_rag_components(
    dataset: DatasetLoadResult,
    *,
    store: Any,
    call_tracker: CallTracker,
    top_k: int = DEFAULT_RETRIEVAL_K,
) -> tuple[ComponentEvaluationResult, ComponentEvaluationResult]:
    """Run answer generation and citation verifier over labeled RAG cases."""
    cases = dataset.labeled_cases
    citation_verifier_model = (settings.citation_verifier_model or "").strip() or None
    effective_verifier_model = citation_verifier_model or settings.groq_model
    answer_model_info = ComponentModelInfo(component="answer_generation_llm", model_name=settings.groq_model)
    verifier_model_info = ComponentModelInfo(
        component="citation_verifier_llm",
        model_name=effective_verifier_model,
        shares_model_with="answer_generation_llm" if citation_verifier_model is None else None,
    )

    if not cases:
        reason = "no labeled cases in rag_eval_dataset.json"
        return (
            ComponentEvaluationResult(
                component="answer_generation_llm",
                status=NOT_EVALUABLE,
                reason=reason,
                model_info=answer_model_info,
                case_count=0,
                skipped_unlabeled_count=dataset.unlabeled_count,
            ),
            ComponentEvaluationResult(
                component="citation_verifier_llm",
                status=NOT_EVALUABLE,
                reason=reason,
                model_info=verifier_model_info,
                case_count=0,
                skipped_unlabeled_count=dataset.unlabeled_count,
            ),
        )
    if not settings.groq_api_key:
        reason = "ASKA_GROQ_API_KEY is not configured; cannot call the answer-generation/citation-verifier LLM"
        return (
            ComponentEvaluationResult(
                component="answer_generation_llm",
                status=NOT_EVALUABLE,
                reason=reason,
                model_info=answer_model_info,
                case_count=len(cases),
                skipped_unlabeled_count=dataset.unlabeled_count,
            ),
            ComponentEvaluationResult(
                component="citation_verifier_llm",
                status=NOT_EVALUABLE,
                reason=reason,
                model_info=verifier_model_info,
                case_count=len(cases),
                skipped_unlabeled_count=dataset.unlabeled_count,
            ),
        )

    answer_perf_records: list[CallRecord] = []
    verifier_perf_records: list[CallRecord] = []
    answer_case_results: list[CaseResultRecord] = []
    verifier_case_results: list[CaseResultRecord] = []
    rag_cases: list[RagCaseResult] = []
    citation_cases_with_gold = 0
    verifier_succeeded_count = 0

    for case in cases:
        retrieved = store.search(case["question"], top_k=top_k)
        context = format_retrieved_context(retrieved)
        usage_sink: dict[str, Any] = {}
        is_first_call = call_tracker.is_first_call_in_run("answer_generation_llm")
        started = time.perf_counter()
        try:
            answer = generate_groq_answer(question=case["question"], context=context, usage_sink=usage_sink)
            success = True
        except GroqAnswerError:
            answer = None
            success = False
        latency_ms = (time.perf_counter() - started) * 1000.0
        answer_perf_records.append(
            CallRecord(
                success=success,
                latency_ms=latency_ms,
                is_first_call_in_run=is_first_call,
                prompt_tokens=usage_sink.get("prompt_tokens"),
                completion_tokens=usage_sink.get("completion_tokens"),
            )
        )
        answer_case_results.append(
            CaseResultRecord(
                case_id=str(case["case_id"]),
                predicted=_truncate_case_text(answer) if success else None,
                correct=success,
                latency_ms=round(latency_ms, 2),
            )
        )
        if not success:
            rag_cases.append(RagCaseResult(case_id=case["case_id"]))
            continue

        gold_citation_ids = {str(v) for v in (case.get("gold_citation_ids") or [])}
        citation_fields: dict[str, float | None] = {}
        if gold_citation_ids and retrieved:
            candidates = [
                CandidateEvidence(
                    citation_id=_chunk_identity(chunk),
                    title=chunk.title,
                    source_section=(chunk.metadata or {}).get("source_section"),
                    source_filename=chunk.source_filename,
                    text=chunk.text,
                    page_number=(chunk.metadata or {}).get("page_number"),
                )
                for chunk in retrieved
            ]
            verifier_is_first_call = call_tracker.is_first_call_in_run(
                f"citation_verifier_llm:{effective_verifier_model}"
            )
            outcome = verify_citations(answer=answer, candidates=candidates, mode="llm")
            if outcome.verifier_invoked:
                verifier_perf_records.append(
                    CallRecord(
                        success=outcome.verifier_succeeded,
                        latency_ms=outcome.latency_ms or 0.0,
                        is_first_call_in_run=verifier_is_first_call,
                        prompt_tokens=(outcome.usage or {}).get("prompt_tokens"),
                        completion_tokens=(outcome.usage or {}).get("completion_tokens"),
                    )
                )
                if outcome.verifier_succeeded:
                    verifier_succeeded_count += 1
            citation_fields = citation_metrics_from_outcome(outcome, gold_citation_ids=gold_citation_ids)
            citation_cases_with_gold += 1
            verifier_case_results.append(
                CaseResultRecord(
                    case_id=str(case["case_id"]),
                    predicted=",".join(sorted(outcome.verified_citation_ids)) if outcome.verifier_succeeded else None,
                    expected=",".join(sorted(gold_citation_ids)),
                    correct=outcome.verifier_succeeded if outcome.verifier_invoked else None,
                    latency_ms=outcome.latency_ms,
                )
            )

        rag_cases.append(
            RagCaseResult(
                case_id=case["case_id"],
                faithfulness=citation_fields.get("faithfulness"),
                claim_support_rate=citation_fields.get("claim_support_rate"),
                citation_set_precision=citation_fields.get("citation_set_precision"),
                citation_set_recall=citation_fields.get("citation_set_recall"),
                judge_source="llm_judge",
            )
        )

    answer_performance = evaluate_performance(answer_perf_records) if answer_perf_records else None
    answer_result = ComponentEvaluationResult(
        component="answer_generation_llm",
        status=EVALUATED,
        reason=None,
        model_info=answer_model_info,
        performance_metrics=answer_performance,
        case_count=len(cases),
        skipped_unlabeled_count=dataset.unlabeled_count,
        case_results=tuple(answer_case_results),
    )

    if citation_cases_with_gold == 0:
        verifier_result = ComponentEvaluationResult(
            component="citation_verifier_llm",
            status=NOT_EVALUABLE,
            reason=(
                "no case in rag_eval_dataset.json had both a successfully generated "
                "answer and gold_citation_ids; faithfulness/citation-set metrics were "
                "not computed"
            ),
            model_info=verifier_model_info,
            case_count=len(cases),
            skipped_unlabeled_count=dataset.unlabeled_count,
        )
    elif verifier_succeeded_count == 0:
        verifier_result = ComponentEvaluationResult(
            component="citation_verifier_llm",
            status=NOT_EVALUABLE,
            reason=(
                "gold_citation_ids existed for "
                f"{citation_cases_with_gold} case(s), but the LLM verifier was never "
                "successfully invoked (zero checkable claims and/or every call failed); "
                "no LLM citation evaluation occurred"
            ),
            model_info=verifier_model_info,
            case_count=len(cases),
            skipped_unlabeled_count=dataset.unlabeled_count,
            performance_metrics=evaluate_performance(verifier_perf_records) if verifier_perf_records else None,
            case_results=tuple(verifier_case_results),
        )
    else:
        verifier_performance = evaluate_performance(verifier_perf_records) if verifier_perf_records else None
        verifier_result = ComponentEvaluationResult(
            component="citation_verifier_llm",
            status=EVALUATED,
            reason=None,
            model_info=verifier_model_info,
            rag_metrics=aggregate_rag_metrics(rag_cases),
            performance_metrics=verifier_performance,
            case_count=len(cases),
            skipped_unlabeled_count=dataset.unlabeled_count,
            note=(
                "citation_verifier_llm shares the same configured model as "
                "answer_generation_llm (ASKA_CITATION_VERIFIER_MODEL is unset)."
                if citation_verifier_model is None
                else None
            ),
            case_results=tuple(verifier_case_results),
        )
    return answer_result, verifier_result


def run_evaluation(
    *,
    store: Any = None,
    classification_dataset_path: str | Path = DEFAULT_CLASSIFICATION_DATASET_PATH,
    retrieval_dataset_path: str | Path = DEFAULT_RETRIEVAL_DATASET_PATH,
    rag_dataset_path: str | Path = DEFAULT_RAG_DATASET_PATH,
    retrieval_k: int = DEFAULT_RETRIEVAL_K,
    retrieval_candidate_pool_size: int = DEFAULT_RETRIEVAL_CANDIDATE_POOL_SIZE,
) -> EvaluationRunResult:
    """Load datasets and evaluate each component once. Persistence is separate."""
    call_tracker = CallTracker()

    classification_dataset = load_classification_dataset(classification_dataset_path)
    retrieval_dataset = load_retrieval_dataset(retrieval_dataset_path)
    rag_dataset = load_rag_dataset(rag_dataset_path)

    results: list[ComponentEvaluationResult] = []

    try:
        results.append(evaluate_classify_chunk(classification_dataset, allow_llm=True))
        results.append(evaluate_classify_chunk(classification_dataset, allow_llm=False))
        results.append(evaluate_classify_question(classification_dataset))
    except Exception as exc:  # noqa: BLE001
        results.append(_failed_placeholder("classify_chunk(allow_llm=True)", exc))
        results.append(_failed_placeholder("classify_chunk(allow_llm=False)", exc))
        results.append(_failed_placeholder("classify_question", exc))

    try:
        retrieval_store = store
        if retrieval_store is None and retrieval_dataset.labeled_cases:
            retrieval_store = open_labeled_retrieval_store()
        if retrieval_store is None and retrieval_dataset.labeled_cases:
            missing = (
                "labeled retrieval index not found at data/chroma_evaluation; "
                "the 12-question judgments cannot be scored without that corpus"
            )
            embedding_info = ComponentModelInfo(
                component="embedding_retrieval", model_name=current_embedding_model_label()
            )
            reranker_info = ComponentModelInfo(
                component="reranker",
                model_name="rule-based query expansion + heuristic boosting (not a trained model)",
            )
            results.append(
                ComponentEvaluationResult(
                    component="embedding_retrieval",
                    status=NOT_EVALUABLE,
                    reason=missing,
                    model_info=embedding_info,
                    case_count=0,
                    skipped_unlabeled_count=retrieval_dataset.unlabeled_count,
                )
            )
            results.append(
                ComponentEvaluationResult(
                    component="reranker",
                    status=NOT_EVALUABLE,
                    reason=missing,
                    model_info=reranker_info,
                    case_count=0,
                    skipped_unlabeled_count=retrieval_dataset.unlabeled_count,
                )
            )
        else:
            results.extend(
                evaluate_retrieval(
                    retrieval_dataset,
                    store=retrieval_store,
                    k=retrieval_k,
                    candidate_pool_size=retrieval_candidate_pool_size,
                )
            )
    except Exception as exc:  # noqa: BLE001
        results.append(_failed_placeholder("embedding_retrieval", exc))
        results.append(_failed_placeholder("reranker", exc))

    try:
        rag_store = store
        if rag_store is None and rag_dataset.labeled_cases:
            rag_store = get_knowledge_base_store()
        results.extend(
            evaluate_rag_components(rag_dataset, store=rag_store, call_tracker=call_tracker, top_k=retrieval_k)
        )
    except Exception as exc:  # noqa: BLE001
        results.append(_failed_placeholder("answer_generation_llm", exc))
        results.append(_failed_placeholder("citation_verifier_llm", exc))

    return EvaluationRunResult(
        components=tuple(results),
        dataset_versions={
            "classification": classification_dataset.dataset_version,
            "retrieval": retrieval_dataset.dataset_version,
            "rag": rag_dataset.dataset_version,
        },
        dataset_sha256={
            "classification": classification_dataset.sha256,
            "retrieval": retrieval_dataset.sha256,
            "rag": rag_dataset.sha256,
        },
    )
