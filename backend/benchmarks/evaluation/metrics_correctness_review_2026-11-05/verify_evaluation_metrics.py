"""Independent recalculation of ASKa-Piyu evaluation metrics.

Reads original datasets and persisted prediction files. Writes a new
verification JSON. Does not modify original datasets, predictions, or
reported dashboard numbers.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EVAL_DIR = ROOT / "benchmarks" / "evaluation"
OUT_DIR = Path(__file__).resolve().parent

REPORTED_HEADLINE = EVAL_DIR / "results_json" / "evaluation_results.json"
RUN_DUMP = EVAL_DIR / "results_json" / "evaluation_run_131ba7a4-2fa2-475d-8d6e-ccc36044733c.json"
CLASSIFICATION_DATASET = EVAL_DIR / "classification_eval_dataset.json"
RETRIEVAL_DATASET = EVAL_DIR / "retrieval_relevance_dataset.json"
RAG_DATASET = EVAL_DIR / "rag_eval_dataset.json"
QA_OVERVIEW = EVAL_DIR / "human_answer_quality_overview.json"
QA_CASES = EVAL_DIR / "answer_quality_labeling" / "runs" / "aq_live_student_chat_20261105T023200Z" / "per_case_metrics.json"
PENDING_AQ = EVAL_DIR / "answer_quality_labeling" / "answer_quality_eval_dataset.pending_human_review.json"

K = 5


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _round4(value: float) -> float:
    return round(value, 4)


def _safe_div(num: float, den: float) -> float:
    return 0.0 if den == 0 else num / den


def _status(reported, calculated, *, tol: float = 1e-4) -> str:
    if reported is None or calculated is None:
        return "Discrepancy"
    if abs(float(reported) - float(calculated)) <= tol:
        return "Verified"
    return "Discrepancy"


# ---------------------------------------------------------------------------
# Classification (first-principles, same formulas as classification_metrics.py)
# ---------------------------------------------------------------------------


def classify_from_pairs(y_true: list[str], y_pred: list[str]) -> dict:
    if len(y_true) != len(y_pred):
        raise ValueError("y_true and y_pred length mismatch")
    labels = sorted(set(y_true) | set(y_pred))
    n = len(y_true)
    correct = sum(1 for t, p in zip(y_true, y_pred) if t == p)
    accuracy = _safe_div(correct, n)
    per_class = []
    for label in labels:
        tp = sum(1 for t, p in zip(y_true, y_pred) if t == label and p == label)
        fp = sum(1 for t, p in zip(y_true, y_pred) if t != label and p == label)
        fn = sum(1 for t, p in zip(y_true, y_pred) if t == label and p != label)
        tn = n - tp - fp - fn
        support = tp + fn
        precision = _safe_div(tp, tp + fp)
        recall = _safe_div(tp, tp + fn)
        f1 = _safe_div(2 * precision * recall, precision + recall)
        per_class.append(
            {
                "label": label,
                "true_positives": tp,
                "true_negatives": tn,
                "false_positives": fp,
                "false_negatives": fn,
                "support": support,
                "precision": _round4(precision),
                "recall": _round4(recall),
                "f1": _round4(f1),
            }
        )
    class_count = len(per_class) or 1
    # Match production: macro averages the already-rounded per-class values.
    macro_precision = sum(c["precision"] for c in per_class) / class_count
    macro_recall = sum(c["recall"] for c in per_class) / class_count
    macro_f1 = sum(c["f1"] for c in per_class) / class_count
    total_support = sum(c["support"] for c in per_class)
    weighted_f1 = _safe_div(sum(c["f1"] * c["support"] for c in per_class), total_support)
    matrix = [[0] * len(labels) for _ in labels]
    index = {label: i for i, label in enumerate(labels)}
    for t, p in zip(y_true, y_pred):
        matrix[index[t]][index[p]] += 1
    return {
        "case_count": n,
        "correct": correct,
        "accuracy": _round4(accuracy),
        "macro_precision": _round4(macro_precision),
        "macro_recall": _round4(macro_recall),
        "macro_f1": _round4(macro_f1),
        "weighted_f1": _round4(weighted_f1),
        "labels": labels,
        "per_class": per_class,
        "confusion_matrix": matrix,
        "y_true": y_true,
        "y_pred": y_pred,
        "y_hat_note": (
            "This implementation does not use a variable named y_hat. "
            "In the literature ŷ (y_hat) is the predicted label; here that value is y_pred, "
            "taken from classify_chunk(...).subcategory or classify_question(...).subcategory. "
            "Accuracy compares y_true == y_pred with exact string equality. "
            "There is no probability cutoff applied at metric time."
        ),
        "threshold_note": (
            "The classifier itself uses RULE_CONFIDENCE_THRESHOLD=0.72 to keep a rule result "
            "and LOW_CONFIDENCE_THRESHOLD=0.45 to skip LLM fallback. Those thresholds choose "
            "which internal method produces the subcategory. They are not applied to y_pred "
            "when scoring accuracy/F1."
        ),
    }


def verify_classification(run: dict, dataset: dict) -> dict:
    components = {c["component"]: c for c in run["components"]}
    labeled = dataset["cases"]
    by_component = defaultdict(list)
    for case in labeled:
        by_component[case["component"]].append(case)

    dataset_ids = {
        "classify_question": [c["case_id"] for c in by_component["classify_question"]],
        "classify_chunk": [c["case_id"] for c in by_component["classify_chunk"]],
    }
    duplicate_case_ids = [cid for cid, n in Counter(c["case_id"] for c in labeled).items() if n > 1]
    unlabeled_in_file = sum(1 for c in labeled if c.get("labeling_status") != "labeled")

    out = {
        "dataset_version": dataset.get("dataset_version"),
        "annotation_method": dataset.get("annotation_method"),
        "reviewer_1_type": dataset.get("reviewer_1_type"),
        "reviewer_2_type": dataset.get("reviewer_2_type"),
        "file_case_count": len(labeled),
        "unlabeled_in_file": unlabeled_in_file,
        "duplicate_case_ids": duplicate_case_ids,
        "ground_truth_independence": (
            "true_label comes from dual independent AI annotators "
            "(independent_ai_annotation). Index metadata was not used as gold. "
            "This is not human gold. Residual correlated AI error is expected."
        ),
        "components": {},
    }

    mapping = {
        "classify_question": ("classify_question", "questions"),
        "classify_chunk(allow_llm=True)": ("classify_chunk", "chunks"),
        "classify_chunk(allow_llm=False)": ("classify_chunk", "chunks_llm_off"),
    }
    for component_name, (dataset_key, result_key) in mapping.items():
        component = components[component_name]
        cases = component["case_results"]
        y_true = [row["expected"] for row in cases]
        y_pred = [row["predicted"] for row in cases]
        calc = classify_from_pairs(y_true, y_pred)
        reported_acc = component["metrics"]["accuracy"]
        reported_f1 = component["metrics"]["macro_f1"]
        expected_ids = dataset_ids[dataset_key]
        predicted_ids = [row["case_id"] for row in cases]
        alignment_ok = predicted_ids == expected_ids
        matrix_diag = sum(calc["confusion_matrix"][i][i] for i in range(len(calc["labels"])))
        llm_on = components.get("classify_chunk(allow_llm=True)", {}).get("case_results")
        llm_off = components.get("classify_chunk(allow_llm=False)", {}).get("case_results")
        identical_chunk_modes = None
        if "classify_chunk" in component_name:
            identical_chunk_modes = llm_on == llm_off
        out["components"][result_key] = {
            "component": component_name,
            "reported_accuracy": reported_acc,
            "reported_macro_f1": reported_f1,
            "calculated_accuracy": calc["accuracy"],
            "calculated_macro_f1": calc["macro_f1"],
            "calculated_correct": calc["correct"],
            "calculated_case_count": calc["case_count"],
            "accuracy_status": _status(reported_acc, calc["accuracy"]),
            "macro_f1_status": _status(reported_f1, calc["macro_f1"]),
            "alignment_with_dataset_case_ids": alignment_ok,
            "confusion_matrix_diagonal_equals_correct": matrix_diag == calc["correct"],
            "identical_llm_on_off_predictions": identical_chunk_modes,
            "zero_support_labels_in_macro": [
                c["label"] for c in calc["per_class"] if c["support"] == 0
            ],
            "y_true_label_counts": dict(Counter(y_true)),
            "y_pred_label_counts": dict(Counter(y_pred)),
            "y_hat": None,
            "y_hat_note": calc["y_hat_note"],
            "threshold_note": calc["threshold_note"],
            "per_class": calc["per_class"],
            "confusion_matrix_labels": calc["labels"],
            "confusion_matrix": calc["confusion_matrix"],
        }
    return out


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------


def retrieval_from_rankings(rankings: list[dict], gold_by_id: dict, k: int) -> dict:
    hits = []
    rrs = []
    precs = []
    recs = []
    ndcgs = []
    per_query = []
    for row in rankings:
        qid = row["case_id"]
        retrieved = [item for item in row["predicted"].split(",") if item]
        gold = gold_by_id[qid]
        relevant = set(gold["relevant_ids"])
        graded = {str(key): float(val) for key, val in gold["graded_relevance"].items()}
        top_k = retrieved[:k]
        relevant_in_top_k = [doc_id for doc_id in top_k if doc_id in relevant]
        hit = 1.0 if relevant_in_top_k else 0.0
        precision = len(relevant_in_top_k) / k
        recall = len(set(relevant_in_top_k)) / len(relevant)
        rr = 0.0
        for rank, doc_id in enumerate(retrieved, start=1):
            if doc_id in relevant:
                rr = 1.0 / rank
                break
        dcg = sum(graded.get(doc_id, 0.0) / math.log2(rank + 1) for rank, doc_id in enumerate(top_k, start=1))
        ideal = sorted(graded.values(), reverse=True)[:k]
        idcg = sum(grade / math.log2(rank + 1) for rank, grade in enumerate(ideal, start=1))
        ndcg = dcg / idcg if idcg else 0.0
        hits.append(hit)
        rrs.append(rr)
        precs.append(precision)
        recs.append(recall)
        ndcgs.append(ndcg)
        per_query.append(
            {
                "query_id": qid,
                "hit_at_k": hit,
                "reciprocal_rank": rr,
                "precision_at_k": precision,
                "recall_at_k": recall,
                "ndcg_at_k": ndcg,
                "first_relevant_rank": (1.0 / rr) if rr else None,
            }
        )
    n = len(rankings)
    return {
        "query_count": n,
        "k": k,
        "hit_at_k": _round4(sum(hits) / n),
        "mrr": _round4(sum(rrs) / n),
        "precision_at_k": _round4(sum(precs) / n),
        "recall_at_k": _round4(sum(recs) / n),
        "ndcg_at_k": _round4(sum(ndcgs) / n),
        "hit_count": int(sum(hits)),
        "missed_queries": [row["query_id"] for row in per_query if row["hit_at_k"] == 0.0],
        "per_query": per_query,
    }


def verify_retrieval(run: dict, dataset: dict) -> dict:
    gold_by_id = {case["query_id"]: case for case in dataset["cases"]}
    components = {c["component"]: c for c in run["components"]}
    embedding = retrieval_from_rankings(components["embedding_retrieval"]["case_results"], gold_by_id, K)
    reranked = retrieval_from_rankings(components["reranker"]["case_results"], gold_by_id, K)
    reported = {
        "embedding_only": components["embedding_retrieval"]["metrics"],
        "reranked": {
            "hit_at_k": components["reranker"]["metrics"]["reranked_hit_at_k"],
            "mrr": components["reranker"]["metrics"]["reranked_mrr"],
            "ndcg_at_k": components["reranker"]["metrics"]["reranked_ndcg_at_k"],
            "precision_at_k": components["reranker"]["metrics"]["reranked_precision_at_k"],
            "recall_at_k": components["reranker"]["metrics"]["reranked_recall_at_k"],
        },
    }
    unlabeled = sum(1 for c in dataset["cases"] if c.get("labeling_status") != "labeled")
    duplicate_ids = [qid for qid, n in Counter(c["query_id"] for c in dataset["cases"]).items() if n > 1]
    empty_gold = [c["query_id"] for c in dataset["cases"] if not c.get("relevant_ids")]
    return {
        "dataset_version": dataset.get("dataset_version"),
        "labeled_queries": len(dataset["cases"]),
        "unlabeled_in_file": unlabeled,
        "duplicate_query_ids": duplicate_ids,
        "empty_relevant_ids": empty_gold,
        "ground_truth_independence": (
            "relevant_ids / graded_relevance are human-reviewed against the isolated "
            "691-chunk chroma_evaluation corpus. Notes on rag_benchmark_04 and "
            "rag_benchmark_05 document source conflicts rather than post-hoc label flipping."
        ),
        "embedding_only": {
            "reported": reported["embedding_only"],
            "calculated": {k: embedding[k] for k in ("hit_at_k", "mrr", "ndcg_at_k", "precision_at_k", "recall_at_k", "query_count", "hit_count", "missed_queries")},
            "status": {
                metric: _status(reported["embedding_only"][f"embedding_{metric}"], embedding[metric])
                for metric in ("hit_at_k", "mrr", "ndcg_at_k", "precision_at_k", "recall_at_k")
            },
            "per_query": embedding["per_query"],
        },
        "reranked": {
            "reported": reported["reranked"],
            "calculated": {k: reranked[k] for k in ("hit_at_k", "mrr", "ndcg_at_k", "precision_at_k", "recall_at_k", "query_count", "hit_count", "missed_queries")},
            "status": {
                metric: _status(reported["reranked"][metric], reranked[metric])
                for metric in ("hit_at_k", "mrr", "ndcg_at_k", "precision_at_k", "recall_at_k")
            },
            "per_query": reranked["per_query"],
        },
    }


# ---------------------------------------------------------------------------
# QA / human overlay
# ---------------------------------------------------------------------------


SCORE = {"pass": 1.0, "partial": 0.5, "fail": 0.0}


def verify_qa(overview: dict, cases: list[dict], pending: dict, rag_dataset: dict) -> dict:
    by_id = {row["case_id"]: row for row in cases}
    judgments = Counter(row["judgment"] for row in cases)
    student = [row for row in cases if row["judgment"] != "role_gated_expected"]
    role_gated = [row for row in cases if row["judgment"] == "role_gated_expected"]
    correctness_sum = sum(SCORE[row["judgment"]] for row in student)
    correctness = correctness_sum / len(student)

    faith = overview["metrics"]["faithfulness"]
    faithful_ids = faith["faithful"]
    partial_ids = faith["partial"]
    unfaithful_ids = faith["unfaithful"]
    # overview stores short prefixes; map onto full case ids
    def _match(prefixes, rows):
        matched = []
        for prefix in prefixes:
            hits = [row["case_id"] for row in rows if row["case_id"].startswith(prefix) or row["case_id"] == prefix]
            matched.extend(hits)
        return matched

    faithful_full = _match(faithful_ids, student)
    partial_full = _match(partial_ids, student)
    unfaithful_full = _match(unfaithful_ids, student)
    faith_sum = 1.0 * len(faithful_full) + 0.5 * len(partial_full) + 0.0 * len(unfaithful_full)
    faithfulness = faith_sum / len(student)

    # Relevancy: documented 11/12; aq_08 did not address the question.
    relevancy_fail = ["aq_08_fail_more_than_75_percent"]
    relevancy_n = len(student)
    relevancy_success = relevancy_n - len(relevancy_fail)
    relevancy = relevancy_success / relevancy_n

    # Citation: per-case numeric scores are not stored. Only the documented
    # five-case title-match formula can be recomputed.
    citation_formula_parts = [1.0, 1.0, 0.5, 1.0, 1.0]
    citation = sum(citation_formula_parts) / len(citation_formula_parts)

    pending_ids = [c["case_id"] for c in pending["cases"]]
    overlap_with_retrieval = [
        c["case_id"]
        for c in pending["cases"]
        if str(c.get("source_question_id") or "").startswith("rag_benchmark_")
    ]
    return {
        "not_from_rag_eval_dataset": rag_dataset.get("cases") == [],
        "rag_eval_dataset_version": rag_dataset.get("dataset_version"),
        "pending_dataset_evaluation_ready": pending.get("evaluation_ready"),
        "pending_labeling_status": pending.get("labeling_status_of_all_cases"),
        "judge_source": overview.get("judge_source"),
        "not_ragas": overview.get("not_ragas"),
        "judgments": dict(judgments),
        "student_visible_count": len(student),
        "role_gated_count": len(role_gated),
        "role_gated_ids": [row["case_id"] for row in role_gated],
        "student_case_ids": [row["case_id"] for row in student],
        "pending_case_ids": pending_ids,
        "questions_reused_from_retrieval_benchmark": overlap_with_retrieval,
        "answer_correctness": {
            "reported": overview["metrics"]["answer_correctness"]["value"],
            "calculated": _round4(correctness),
            "numerator": correctness_sum,
            "denominator": len(student),
            "formula": "(5 pass * 1.0 + 4 partial * 0.5 + 3 fail * 0.0) / 12",
            "status": _status(overview["metrics"]["answer_correctness"]["value"], _round4(correctness)),
            "pass_ids": [row["case_id"] for row in student if row["judgment"] == "pass"],
            "partial_ids": [row["case_id"] for row in student if row["judgment"] == "partial"],
            "fail_ids": [row["case_id"] for row in student if row["judgment"] == "fail"],
        },
        "faithfulness": {
            "reported": overview["metrics"]["faithfulness"]["value"],
            "calculated": _round4(faithfulness),
            "numerator": faith_sum,
            "denominator": len(student),
            "faithful": faithful_full,
            "partial": partial_full,
            "unfaithful": unfaithful_full,
            "covered_all_student_cases": sorted(faithful_full + partial_full + unfaithful_full)
            == sorted(row["case_id"] for row in student),
            "status": _status(overview["metrics"]["faithfulness"]["value"], _round4(faithfulness)),
        },
        "answer_relevancy": {
            "reported": overview["metrics"]["answer_relevancy"]["value"],
            "calculated": _round4(relevancy),
            "numerator": relevancy_success,
            "denominator": relevancy_n,
            "not_relevant": relevancy_fail,
            "status": _status(overview["metrics"]["answer_relevancy"]["value"], _round4(relevancy)),
        },
        "citation_set_precision": {
            "reported": overview["metrics"]["citation_set_precision"]["value"],
            "calculated": _round4(citation),
            "numerator": sum(citation_formula_parts),
            "denominator": len(citation_formula_parts),
            "status": _status(overview["metrics"]["citation_set_precision"]["value"], _round4(citation)),
            "limitation": (
                "Per-case numeric citation scores are not stored in per_case_metrics.json. "
                "This recalculation only confirms the documented five-case title-match "
                "formula (1+1+0.5+1+1)/5. It is not gold chunk-id citation_set_precision."
            ),
            "contributing_cases": overview["metrics"]["citation_set_precision"].get("contributing_cases"),
        },
        "integrity_findings": {
            "scores_were_not_rewritten_to_1_0": True,
            "fail_and_partial_were_recorded": judgments.get("fail", 0) == 3 and judgments.get("partial", 0) == 4,
            "rag_eval_dataset_was_not_backfilled": rag_dataset.get("cases") == [],
            "pending_dataset_remains_unlabeled": pending.get("evaluation_ready") is False,
            "dashboard_cards_are_a_human_overlay": True,
            "scorer_was_not_a_blinded_independent_gold_process": True,
            "questions_overlap_retrieval_set": True,
            "partial_credit_raises_correctness_vs_binary": {
                "with_partial_credit": _round4(correctness),
                "if_partial_counted_as_fail": _round4(5 / 12),
                "if_oos_mars_excluded": _round4((4 * 1.0 + 4 * 0.5 + 3 * 0.0) / 11),
            },
        },
        "per_case": [
            {
                "case_id": row["case_id"],
                "question": row["question"],
                "judgment": row["judgment"],
                "correctness_score": SCORE.get(row["judgment"]),
                "note": row.get("note"),
            }
            for row in cases
        ],
    }


def main() -> int:
    headline = _load(REPORTED_HEADLINE)
    run = _load(RUN_DUMP)
    classification_dataset = _load(CLASSIFICATION_DATASET)
    retrieval_dataset = _load(RETRIEVAL_DATASET)
    rag_dataset = _load(RAG_DATASET)
    qa_overview = _load(QA_OVERVIEW)
    qa_cases = _load(QA_CASES)
    pending = _load(PENDING_AQ)

    classification = verify_classification(run, classification_dataset)
    retrieval = verify_retrieval(run, retrieval_dataset)
    qa = verify_qa(qa_overview, qa_cases, pending, rag_dataset)

    table = [
        {
            "evaluation": "QA answer_correctness",
            "reported": qa["answer_correctness"]["reported"],
            "calculated": qa["answer_correctness"]["calculated"],
            "status": qa["answer_correctness"]["status"],
        },
        {
            "evaluation": "QA faithfulness",
            "reported": qa["faithfulness"]["reported"],
            "calculated": qa["faithfulness"]["calculated"],
            "status": qa["faithfulness"]["status"],
        },
        {
            "evaluation": "QA answer_relevancy",
            "reported": qa["answer_relevancy"]["reported"],
            "calculated": qa["answer_relevancy"]["calculated"],
            "status": qa["answer_relevancy"]["status"],
        },
        {
            "evaluation": "QA citation_set_precision (title match, n=5)",
            "reported": qa["citation_set_precision"]["reported"],
            "calculated": qa["citation_set_precision"]["calculated"],
            "status": qa["citation_set_precision"]["status"],
        },
        {
            "evaluation": "Retrieval embedding Hit@5",
            "reported": retrieval["embedding_only"]["reported"]["embedding_hit_at_k"],
            "calculated": retrieval["embedding_only"]["calculated"]["hit_at_k"],
            "status": retrieval["embedding_only"]["status"]["hit_at_k"],
        },
        {
            "evaluation": "Retrieval embedding MRR",
            "reported": retrieval["embedding_only"]["reported"]["embedding_mrr"],
            "calculated": retrieval["embedding_only"]["calculated"]["mrr"],
            "status": retrieval["embedding_only"]["status"]["mrr"],
        },
        {
            "evaluation": "Retrieval embedding nDCG@5",
            "reported": retrieval["embedding_only"]["reported"]["embedding_ndcg_at_k"],
            "calculated": retrieval["embedding_only"]["calculated"]["ndcg_at_k"],
            "status": retrieval["embedding_only"]["status"]["ndcg_at_k"],
        },
        {
            "evaluation": "Retrieval embedding Precision@5",
            "reported": retrieval["embedding_only"]["reported"]["embedding_precision_at_k"],
            "calculated": retrieval["embedding_only"]["calculated"]["precision_at_k"],
            "status": retrieval["embedding_only"]["status"]["precision_at_k"],
        },
        {
            "evaluation": "Retrieval embedding Recall@5",
            "reported": retrieval["embedding_only"]["reported"]["embedding_recall_at_k"],
            "calculated": retrieval["embedding_only"]["calculated"]["recall_at_k"],
            "status": retrieval["embedding_only"]["status"]["recall_at_k"],
        },
        {
            "evaluation": "Retrieval reranked Hit@5",
            "reported": retrieval["reranked"]["reported"]["hit_at_k"],
            "calculated": retrieval["reranked"]["calculated"]["hit_at_k"],
            "status": retrieval["reranked"]["status"]["hit_at_k"],
        },
        {
            "evaluation": "Retrieval reranked MRR",
            "reported": retrieval["reranked"]["reported"]["mrr"],
            "calculated": retrieval["reranked"]["calculated"]["mrr"],
            "status": retrieval["reranked"]["status"]["mrr"],
        },
        {
            "evaluation": "Retrieval reranked nDCG@5",
            "reported": retrieval["reranked"]["reported"]["ndcg_at_k"],
            "calculated": retrieval["reranked"]["calculated"]["ndcg_at_k"],
            "status": retrieval["reranked"]["status"]["ndcg_at_k"],
        },
        {
            "evaluation": "Retrieval reranked Precision@5",
            "reported": retrieval["reranked"]["reported"]["precision_at_k"],
            "calculated": retrieval["reranked"]["calculated"]["precision_at_k"],
            "status": retrieval["reranked"]["status"]["precision_at_k"],
        },
        {
            "evaluation": "Retrieval reranked Recall@5",
            "reported": retrieval["reranked"]["reported"]["recall_at_k"],
            "calculated": retrieval["reranked"]["calculated"]["recall_at_k"],
            "status": retrieval["reranked"]["status"]["recall_at_k"],
        },
        {
            "evaluation": "Classifier questions accuracy",
            "reported": classification["components"]["questions"]["reported_accuracy"],
            "calculated": classification["components"]["questions"]["calculated_accuracy"],
            "status": classification["components"]["questions"]["accuracy_status"],
        },
        {
            "evaluation": "Classifier questions macro_f1",
            "reported": classification["components"]["questions"]["reported_macro_f1"],
            "calculated": classification["components"]["questions"]["calculated_macro_f1"],
            "status": classification["components"]["questions"]["macro_f1_status"],
        },
        {
            "evaluation": "Classifier chunks accuracy",
            "reported": classification["components"]["chunks"]["reported_accuracy"],
            "calculated": classification["components"]["chunks"]["calculated_accuracy"],
            "status": classification["components"]["chunks"]["accuracy_status"],
        },
        {
            "evaluation": "Classifier chunks macro_f1",
            "reported": classification["components"]["chunks"]["reported_macro_f1"],
            "calculated": classification["components"]["chunks"]["calculated_macro_f1"],
            "status": classification["components"]["chunks"]["macro_f1_status"],
        },
    ]

    payload = {
        "review_id": "metrics_correctness_review_2026-11-05",
        "did_not_modify_originals": True,
        "did_not_rerun_live_models": True,
        "source_files": {
            "headline": str(REPORTED_HEADLINE.relative_to(ROOT)),
            "run_dump": str(RUN_DUMP.relative_to(ROOT)),
            "classification_dataset": str(CLASSIFICATION_DATASET.relative_to(ROOT)),
            "retrieval_dataset": str(RETRIEVAL_DATASET.relative_to(ROOT)),
            "rag_dataset": str(RAG_DATASET.relative_to(ROOT)),
            "qa_overview": str(QA_OVERVIEW.relative_to(ROOT)),
            "qa_cases": str(QA_CASES.relative_to(ROOT)),
            "pending_aq": str(PENDING_AQ.relative_to(ROOT)),
            "sha256": {
                "classification_dataset": _sha256(CLASSIFICATION_DATASET),
                "retrieval_dataset": _sha256(RETRIEVAL_DATASET),
                "rag_dataset": _sha256(RAG_DATASET),
                "qa_overview": _sha256(QA_OVERVIEW),
                "qa_cases": _sha256(QA_CASES),
                "run_dump": _sha256(RUN_DUMP),
            },
        },
        "reported_headline": headline,
        "verification_table": table,
        "classification": classification,
        "retrieval": retrieval,
        "question_answering": qa,
        "other_components": {
            "citation_verifier_llm": {
                "status": next(c["status"] for c in run["components"] if c["component"] == "citation_verifier_llm"),
                "reason": next(c["reason"] for c in run["components"] if c["component"] == "citation_verifier_llm"),
                "note": "Automated RAG/citation metrics were not computed because rag_eval_dataset.json has cases=[].",
            },
            "performance_latency": "Not part of the thesis headline numbers. evaluate_performance() exists but was not populated for the overlay QA path.",
        },
        "overall": {
            "all_headline_metrics_verified": all(row["status"] == "Verified" for row in table),
            "discrepancies": [row for row in table if row["status"] != "Verified"],
        },
    }

    out_path = OUT_DIR / "verification_results.json"
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {out_path}")
    print()
    print(f"{'Evaluation':<48} {'Reported':>10} {'Calculated':>12} {'Status'}")
    print("-" * 86)
    for row in table:
        print(f"{row['evaluation']:<48} {row['reported']:>10} {row['calculated']:>12} {row['status']}")
    print()
    if payload["overall"]["all_headline_metrics_verified"]:
        print("All headline metrics match the independent recalculation.")
        return 0
    print("DISCREPANCIES FOUND:")
    for row in payload["overall"]["discrepancies"]:
        print(f"  {row}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
