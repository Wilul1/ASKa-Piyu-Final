"""Separate answer-quality evaluation for the human-approved subset.

This is NOT the production ``run_evaluation`` / ``evaluate_rag_components``
path. That runner:
  * reads only ``rag_eval_dataset.json`` cases with labeling_status=labeled
  * calls ``generate_groq_answer`` instead of student-facing ``answer_qa_question``
  * never computes answer_correctness / answer_relevancy

This script does not mark the pending dataset evaluation-ready, does not
copy unresolved cases into ``rag_eval_dataset.json``, and does not open
production Chroma. It evaluates only aq_04 and aq_08, which currently have
both a human-approved reference answer and approved gold citation IDs.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

from app.config import settings  # noqa: E402
from app.services.chroma_store import RetrievedChunk, select_role_visible_hits  # noqa: E402
from app.services.evaluation.labeled_retrieval_store import (  # noqa: E402
    EXPECTED_LABELED_RETRIEVAL_CHUNK_COUNT,
    LABELED_RETRIEVAL_COLLECTION,
    LABELED_RETRIEVAL_INDEX_PATH,
    LabeledRetrievalStore,
    open_labeled_retrieval_store,
)
from app.services.evaluation.rag_metrics import (  # noqa: E402
    RagCaseResult,
    aggregate_rag_metrics,
    citation_metrics_from_outcome,
)
from app.services.qa.citation_verification import CandidateEvidence, verify_citations  # noqa: E402
from app.services.qa.groq_answer_service import GroqAnswerError  # noqa: E402
from app.services.qa.question_answering import answer_qa_question  # noqa: E402

LABELING_DIR = Path(__file__).resolve().parent
PENDING_DATASET_PATH = LABELING_DIR / "answer_quality_eval_dataset.pending_human_review.json"
EXPECTED_PENDING_SHA256 = "D7CDD2EC2CCE20A176FBA7B07B70C6206E7AABF4F36FD8D3C5BC8BD1677E2905"
PRODUCTION_CHROMA_PATH = (BACKEND_ROOT / "data" / "chroma").resolve()

APPROVED_CASE_IDS = (
    "aq_04_dropping_fee_multi_document",
    "aq_08_fail_more_than_75_percent",
)

# Required facts are taken from the Phase 2D/2F approved reference answers.
# Matching is presence of the gold claim in the chatbot answer, not RAGAS.
REQUIRED_FACTS: dict[str, tuple[dict[str, Any], ...]] = {
    "aq_04_dropping_fee_multi_document": (
        {
            "id": "charter_30_per_unit",
            "from_approved_answer": "Citizen's Charter 2026 lists ₱30.00 per unit",
            "patterns": [r"(?:₱|P)?\s*30(?:\.00)?\s*(?:pesos?)?\s*(?:per|/)\s*unit"],
        },
        {
            "id": "handbook_20_per_unit",
            "from_approved_answer": "Student Handbook 2021 requires a dropping fee of ₱20.00 per unit",
            "patterns": [r"(?:₱|P)?\s*20(?:\.00)?\s*(?:pesos?)?\s*(?:per|/)\s*unit"],
        },
        {
            "id": "new_transferee_limitation",
            "from_approved_answer": "Charter fee is for new and transferee students",
            "patterns": [r"transferee"],
        },
        {
            "id": "bor_1046",
            "from_approved_answer": "Handbook cites LSPU BOR Resolution 1046, s.2012",
            "patterns": [r"1046"],
        },
        {
            "id": "conflict_or_confirm",
            "from_approved_answer": "Do not choose a winning rate; confirm with the Registrar",
            "patterns": [
                r"confirm",
                r"two different",
                r"do not establish",
                r"currently in force",
                r"conflict",
            ],
        },
    ),
    "aq_08_fail_more_than_75_percent": (
        {
            "id": "section_43_more_than_75",
            "from_approved_answer": "Section 4.3: fails in more than 75%",
            "patterns": [r"more than\s*75"],
        },
        {
            "id": "table_75_or_more",
            "from_approved_answer": "Table lists 75% or more",
            "patterns": [r"75\s*%?\s*or more", r"75 percent or more"],
        },
        {
            "id": "dismissal_from_college",
            "from_approved_answer": "Dismissal from the College",
            "patterns": [r"dismissal from the college"],
        },
        {
            "id": "permanent_disqualification",
            "from_approved_answer": "100% is permanent disqualification from the University",
            "patterns": [r"permanent disqualification"],
        },
        {
            "id": "inc_exclusion",
            "from_approved_answer": "Incomplete grade is not included in the computation",
            "patterns": [r"incomplete"],
        },
        {
            "id": "nine_unit_language",
            "from_approved_answer": "Nine academic units exemption and/or enrollment condition",
            "patterns": [r"nine academic units"],
        },
        {
            "id": "exact_75_unresolved_or_confirm",
            "from_approved_answer": "Exact-75% unresolved; confirm with the Registrar",
            "patterns": [r"confirm", r"exact-?75", r"do not resolve", r"slightly different"],
        },
    ),
}


class IsolatedStudentFacingStore:
    """Evaluation-only adapter over chroma_evaluation.

    Adds student-facing audience filtering and ``list_chunks`` so
    ``answer_qa_question`` can run without opening production Chroma.
    Does not mutate the isolated index.
    """

    def __init__(self, inner: LabeledRetrievalStore) -> None:
        self._inner = inner
        resolved = Path(LABELED_RETRIEVAL_INDEX_PATH).resolve()
        if resolved == PRODUCTION_CHROMA_PATH:
            raise RuntimeError("Refusing to use production Chroma as the evaluation corpus.")
        if "chroma_evaluation" not in resolved.as_posix():
            raise RuntimeError(f"Unexpected evaluation index path: {resolved}")

    @property
    def chunk_count(self) -> int:
        return self._inner.chunk_count

    def search(
        self,
        query: str,
        *,
        top_k: int | None = None,
        raw_k: int | None = None,
        user_role: str | None = None,
        ablation: Any = None,
    ) -> list[RetrievedChunk]:
        k = top_k or 5
        candidate_k = max(k, raw_k or k)
        ranked = self._inner.search(
            query, top_k=candidate_k, raw_k=candidate_k, user_role=user_role, ablation=ablation
        )
        if user_role is None:
            return ranked[:k]
        return select_role_visible_hits(ranked, user_role=user_role, top_k=k)

    def list_chunks(self) -> list[dict[str, Any]]:
        collection = self._inner._collection
        data = collection.get(include=["documents", "metadatas"])
        ids = data.get("ids") or []
        documents = data.get("documents") or []
        metadatas = data.get("metadatas") or []
        chunks: list[dict[str, Any]] = []
        for chunk_id, text, metadata in zip(ids, documents, metadatas):
            chunks.append(
                {
                    "id": str(chunk_id),
                    "text": text or "",
                    "metadata": dict(metadata or {}),
                }
            )
        return chunks

    def lookup_text(self, citation_id: str) -> dict[str, Any] | None:
        collection = self._inner._collection
        data = collection.get(ids=[citation_id], include=["documents", "metadatas"])
        ids = data.get("ids") or []
        if ids:
            return {
                "id": str(ids[0]),
                "text": (data.get("documents") or [""])[0] or "",
                "metadata": dict((data.get("metadatas") or [{}])[0] or {}),
            }
        data = collection.get(
            where={"chunk_id": citation_id},
            include=["documents", "metadatas"],
        )
        ids = data.get("ids") or []
        if not ids:
            return None
        return {
            "id": str(ids[0]),
            "text": (data.get("documents") or [""])[0] or "",
            "metadata": dict((data.get("metadatas") or [{}])[0] or {}),
        }


def _as_int(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def load_pending_dataset() -> dict[str, Any]:
    digest = sha256_file(PENDING_DATASET_PATH)
    if digest != EXPECTED_PENDING_SHA256:
        raise RuntimeError(
            f"Pending dataset SHA-256 mismatch. expected={EXPECTED_PENDING_SHA256} actual={digest}. "
            "Refusing to evaluate a different file."
        )
    payload = json.loads(PENDING_DATASET_PATH.read_text(encoding="utf-8"))
    if payload.get("evaluation_ready") is not False:
        raise RuntimeError("Pending dataset evaluation_ready is not false; refusing to treat it as labeled.")
    return payload


def approved_cases(payload: dict[str, Any]) -> list[dict[str, Any]]:
    by_id = {case["case_id"]: case for case in payload["cases"]}
    selected: list[dict[str, Any]] = []
    for case_id in APPROVED_CASE_IDS:
        case = by_id[case_id]
        if case.get("labeling_status") == "labeled":
            raise RuntimeError(f"{case_id} is already labeled; this runner must not treat pending cases as labeled.")
        if not case.get("proposed_reference_answer"):
            raise RuntimeError(f"{case_id} has no approved reference answer.")
        gold = case.get("gold_citation_ids") or []
        if not gold:
            raise RuntimeError(f"{case_id} has no approved gold_citation_ids.")
        selected.append(case)
    return selected


def displayed_citation_ids(sources: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    for source in sources or []:
        citation_id = str(source.get("citation_id") or "").strip()
        if citation_id:
            ids.append(citation_id)
    return ids


def set_precision_recall(predicted: list[str], gold: list[str]) -> dict[str, float | None]:
    if not gold:
        return {
            "citation_set_precision": None,
            "citation_set_recall": None,
            "unavailable_reason": "no gold_citation_ids",
        }
    predicted_set = set(predicted)
    gold_set = set(gold)
    intersection = predicted_set & gold_set
    return {
        "citation_set_precision": round(len(intersection) / len(predicted_set), 4) if predicted_set else 0.0,
        "citation_set_recall": round(len(intersection) / len(gold_set), 4),
        "intersection_ids": sorted(intersection),
        "predicted_ids": predicted,
        "gold_ids": gold,
        "unavailable_reason": None,
    }


def key_fact_coverage(case_id: str, answer: str) -> dict[str, Any]:
    facts = REQUIRED_FACTS[case_id]
    present: list[str] = []
    missing: list[str] = []
    details: list[dict[str, Any]] = []
    for fact in facts:
        matched = any(re.search(pattern, answer, flags=re.I) for pattern in fact["patterns"])
        details.append(
            {
                "id": fact["id"],
                "from_approved_answer": fact["from_approved_answer"],
                "present": matched,
            }
        )
        (present if matched else missing).append(fact["id"])
    score = round(len(present) / len(facts), 4) if facts else None
    return {
        "methodology": (
            "Deterministic presence of required facts copied from the human-approved "
            "reference answer. This is not RAGAS answer_correctness."
        ),
        "score": score,
        "present_fact_ids": present,
        "missing_fact_ids": missing,
        "facts": details,
    }


def answer_on_topic(question: str, answer: str) -> dict[str, Any]:
    question_tokens = [token for token in re.findall(r"[a-zA-Z0-9%]+", question.lower()) if len(token) > 3]
    distinctive = [token for token in question_tokens if token not in {"what", "happens", "does", "cost", "more", "than"}]
    if not distinctive:
        return {"score": None, "unavailable_reason": "no distinctive question tokens"}
    hits = sum(1 for token in distinctive if token in answer.lower())
    return {
        "methodology": (
            "Fraction of distinctive question tokens present in the chatbot answer. "
            "This is not RAGAS answer_relevancy."
        ),
        "score": round(hits / len(distinctive), 4),
        "distinctive_tokens": distinctive,
        "matched_token_count": hits,
    }


def serialize_source(source: dict[str, Any]) -> dict[str, Any]:
    keep = (
        "citation_id",
        "title",
        "page",
        "page_number",
        "page_end",
        "page_range",
        "document_id",
        "source_filename",
        "source_section",
        "source_excerpt",
        "note",
    )
    return {key: source.get(key) for key in keep if key in source}


def run_one_case(
    *,
    case: dict[str, Any],
    store: IsolatedStudentFacingStore,
) -> dict[str, Any]:
    question = case["question"]
    gold_ids = [str(value) for value in case["gold_citation_ids"]]
    citation_debug_sink: list[dict[str, Any]] = []
    generation_usage_sink: dict[str, Any] = {}
    answer_rewrite_sink: dict[str, Any] = {}
    generation_context_sink: dict[str, Any] = {}
    citation_v2_sink: dict[str, Any] = {}
    async_verification_sink: dict[str, Any] = {}
    timing_sink: dict[str, float] = {}

    started = time.perf_counter()
    error: str | None = None
    result = None
    try:
        with patch(
            "app.services.qa.question_answering.get_knowledge_base_store",
            return_value=store,
        ):
            result = answer_qa_question(
                question,
                user_role="student",
                history=[],
                citation_debug_sink=citation_debug_sink,
                generation_usage_sink=generation_usage_sink,
                answer_rewrite_sink=answer_rewrite_sink,
                generation_context_sink=generation_context_sink,
                citation_v2_sink=citation_v2_sink,
                async_verification_sink=async_verification_sink,
                timing_sink=timing_sink,
            )
    except GroqAnswerError as exc:
        error = f"GroqAnswerError: {exc}"
    except Exception as exc:  # noqa: BLE001 — record the failure, do not invent an answer
        error = f"{type(exc).__name__}: {exc}"
    latency_ms = round((time.perf_counter() - started) * 1000.0, 2)

    if result is None:
        return {
            "case_id": case["case_id"],
            "question": question,
            "status": "failed",
            "error": error,
            "latency_ms": latency_ms,
            "chatbot_answer": None,
            "metrics": {
                "answer_correctness": None,
                "answer_relevancy": None,
                "faithfulness": None,
                "claim_support_rate": None,
                "citation_set_precision": None,
                "citation_set_recall": None,
                "unavailable_reason": error,
            },
        }

    displayed_ids = displayed_citation_ids(result.sources)
    generation_context_ids = [
        str(chunk.get("citation_id"))
        for chunk in generation_context_sink.get("final_context_chunks") or []
        if chunk.get("citation_id")
    ]
    retrieved_ids = [
        str(chunk.get("citation_id"))
        for chunk in (result.retrieved_chunks or [])
        if chunk.get("citation_id")
    ]
    student_citation_metrics = set_precision_recall(displayed_ids, gold_ids)
    generation_context_gold = set_precision_recall(generation_context_ids, gold_ids)
    retrieved_gold = set_precision_recall(retrieved_ids, gold_ids)
    fact_coverage = key_fact_coverage(case["case_id"], result.answer)
    relevancy = answer_on_topic(question, result.answer)

    verifier_fields: dict[str, Any] = {
        "faithfulness": None,
        "claim_support_rate": None,
        "citation_set_precision": None,
        "citation_set_recall": None,
        "verifier_invoked": False,
        "verifier_succeeded": False,
        "failure_reason": None,
        "verified_citation_ids": [],
        "claims": [],
    }
    candidate_ids = generation_context_ids or retrieved_ids
    candidates: list[CandidateEvidence] = []
    for citation_id in candidate_ids:
        row = store.lookup_text(citation_id)
        if row is None:
            continue
        metadata = row["metadata"]
        candidates.append(
            CandidateEvidence(
                citation_id=citation_id,
                title=str(metadata.get("title") or ""),
                source_section=str(metadata.get("source_section") or "") or None,
                source_filename=str(metadata.get("source_filename") or "") or None,
                text=str(row["text"] or ""),
                page_number=_as_int(metadata.get("page_number") or metadata.get("page")),
            )
        )
    if candidates and gold_ids:
        outcome = verify_citations(answer=result.answer, candidates=candidates, mode="llm")
        verifier_fields.update(
            {
                "verifier_invoked": outcome.verifier_invoked,
                "verifier_succeeded": outcome.verifier_succeeded,
                "failure_reason": outcome.failure_reason,
                "verified_citation_ids": list(outcome.verified_citation_ids),
                "claims": [{"claim_id": claim.claim_id, "text": claim.text} for claim in outcome.claims],
                "per_claim_verified_ids": outcome.per_claim_verified_ids,
                "latency_ms": outcome.latency_ms,
            }
        )
        if outcome.verifier_invoked and outcome.verifier_succeeded:
            scored = citation_metrics_from_outcome(outcome, gold_citation_ids=set(gold_ids))
            verifier_fields.update(scored)
        elif not outcome.verifier_invoked:
            verifier_fields["unavailable_reason"] = outcome.failure_reason or "verifier not invoked"
        else:
            verifier_fields["unavailable_reason"] = outcome.failure_reason or "verifier failed"

    rag_case = RagCaseResult(
        case_id=case["case_id"],
        faithfulness=verifier_fields.get("faithfulness"),
        answer_relevancy=relevancy.get("score"),
        answer_correctness=fact_coverage.get("score"),
        citation_set_precision=student_citation_metrics.get("citation_set_precision"),
        citation_set_recall=student_citation_metrics.get("citation_set_recall"),
        claim_support_rate=verifier_fields.get("claim_support_rate"),
        judge_source="human_verified",
    )

    return {
        "case_id": case["case_id"],
        "source_question_id": case.get("source_question_id"),
        "question": question,
        "status": "evaluated",
        "error": None,
        "latency_ms": latency_ms,
        "user_role": "student",
        "reference_answer": case["proposed_reference_answer"],
        "gold_citation_ids": gold_ids,
        "chatbot_answer": result.answer,
        "confidence": result.confidence,
        "out_of_scope_detected": result.out_of_scope_detected,
        "llm_generation_invoked": bool(generation_context_sink.get("generation_invoked")),
        "llm_generation_succeeded": bool(generation_context_sink.get("generation_succeeded")),
        "fallback_used": result.fallback_used,
        "fallback_reason": result.fallback_reason,
        "detected_intent": result.detected_intent,
        "selected_context_count": result.selected_context_count,
        "displayed_citations": [serialize_source(source) for source in result.sources],
        "displayed_citation_ids": displayed_ids,
        "retrieved_chunks": result.retrieved_chunks,
        "retrieved_citation_ids": retrieved_ids,
        "generation_context": generation_context_sink,
        "generation_context_citation_ids": generation_context_ids,
        "generation_usage": {
            key: generation_usage_sink.get(key)
            for key in ("prompt_tokens", "completion_tokens", "total_tokens", "model")
            if key in generation_usage_sink
        },
        "answer_rewrite": answer_rewrite_sink,
        "citation_v2_sink": citation_v2_sink,
        "async_verification_sink_keys": sorted(async_verification_sink.keys()),
        "timing_s": timing_sink,
        "metrics": {
            "answer_correctness": {
                "value": fact_coverage["score"],
                "unavailable": False,
                "detail": fact_coverage,
            },
            "answer_relevancy": {
                "value": relevancy.get("score"),
                "unavailable": relevancy.get("score") is None,
                "detail": relevancy,
            },
            "evidence_in_generation_context": {
                "gold_context_recall": generation_context_gold.get("citation_set_recall"),
                "gold_ids_in_generation_context": generation_context_gold.get("intersection_ids"),
                "generation_context_ids": generation_context_ids,
            },
            "evidence_in_retrieval": {
                "gold_retrieval_recall": retrieved_gold.get("citation_set_recall"),
                "gold_ids_in_retrieval": retrieved_gold.get("intersection_ids"),
            },
            "student_visible_citation_quality": student_citation_metrics,
            "llm_verifier_faithfulness": verifier_fields,
            "ragas": {
                "installed": False,
                "answer_correctness": None,
                "answer_relevancy": None,
                "faithfulness": None,
                "note": "RAGAS was not installed and was not used.",
            },
        },
        "_rag_case": rag_case,
    }


def write_report(run_dir: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Answer-quality approved-subset evaluation",
        "",
        f"Run ID: `{report['run_id']}`",
        f"Created: {report['created_at_utc']}",
        "",
        "## Scope",
        "",
        "Evaluated only the human-approved subset with both a reference answer and gold citations:",
        "",
        "- `aq_04_dropping_fee_multi_document`",
        "- `aq_08_fail_more_than_75_percent`",
        "",
        "The pending dataset was not marked evaluation-ready. Unresolved cases were not treated as labeled.",
        "",
        "## Pipeline",
        "",
        "- Function: `answer_qa_question()` (student-facing)",
        "- Corpus: isolated `data/chroma_evaluation` / `aska_evaluation` (691 chunks)",
        "- Role: student",
        "- Displayed citations: lexical V1 (`citation_verification_mode=lexical`)",
        "- Faithfulness scoring: separate `verify_citations(mode='llm')` on generation-context chunks",
        "- Answer correctness: required-fact coverage from the approved reference answers (not RAGAS)",
        "",
        "## Per-case results",
        "",
    ]
    for case in report["cases"]:
        lines.extend(
            [
                f"### {case['case_id']}",
                "",
                f"**Question:** {case['question']}",
                "",
                f"**Status:** {case['status']}",
                "",
            ]
        )
        if case["status"] != "evaluated":
            lines.extend([f"**Error:** {case.get('error')}", ""])
            continue
        metrics = case["metrics"]
        student = metrics["student_visible_citation_quality"]
        faithfulness = metrics["llm_verifier_faithfulness"]
        lines.extend(
            [
                "**Chatbot answer:**",
                "",
                case["chatbot_answer"],
                "",
                "| Metric | Value | Notes |",
                "| --- | --- | --- |",
                f"| answer_correctness (required-fact coverage) | {metrics['answer_correctness']['value']} | {', '.join(metrics['answer_correctness']['detail']['missing_fact_ids']) or 'all required facts present'} |",
                f"| answer_relevancy (question-token overlap) | {metrics['answer_relevancy']['value']} | not RAGAS |",
                f"| gold recall in generation context | {metrics['evidence_in_generation_context']['gold_context_recall']} | |",
                f"| student-visible citation precision | {student.get('citation_set_precision')} | displayed vs gold |",
                f"| student-visible citation recall | {student.get('citation_set_recall')} | displayed vs gold |",
                f"| LLM-verifier faithfulness | {faithfulness.get('faithfulness')} | None means unavailable, not zero |",
                f"| LLM-verifier citation precision | {faithfulness.get('citation_set_precision')} | |",
                f"| LLM-verifier citation recall | {faithfulness.get('citation_set_recall')} | |",
                "",
                f"Displayed citation IDs: `{case['displayed_citation_ids']}`",
                "",
                f"Gold citation IDs: `{case['gold_citation_ids']}`",
                "",
            ]
        )
    aggregate = report["aggregate"]
    lines.extend(
        [
            "## Aggregate (evaluated cases only)",
            "",
            json.dumps(aggregate, indent=2),
            "",
            "## Excluded cases",
            "",
        ]
    )
    for row in report["excluded_cases"]:
        lines.append(f"- `{row['case_id']}`: {row['reason']}")
    lines.extend(
        [
            "",
            "## Limitations",
            "",
            *([f"- {item}" for item in report["limitations"]]),
            "",
        ]
    )
    (run_dir / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    payload = load_pending_dataset()
    cases = approved_cases(payload)
    inner = open_labeled_retrieval_store()
    if inner is None:
        raise FileNotFoundError(f"Isolated evaluation index not found: {LABELED_RETRIEVAL_INDEX_PATH}")
    if inner.chunk_count != EXPECTED_LABELED_RETRIEVAL_CHUNK_COUNT:
        raise RuntimeError(
            f"Expected {EXPECTED_LABELED_RETRIEVAL_CHUNK_COUNT} evaluation chunks, found {inner.chunk_count}."
        )
    store = IsolatedStudentFacingStore(inner)

    # Local .env currently has async_llm, which returns zero citations until a
    # background job finishes. Pin lexical so this run captures the complete
    # student-visible V1 citation list in one call. Do not write this back to
    # .env or production config.
    settings.citation_verification_mode = "lexical"
    settings.groq_timeout_seconds = max(float(settings.groq_timeout_seconds or 30.0), 90.0)

    created = datetime.now(timezone.utc)
    run_id = created.strftime("aq_subset_%Y%m%dT%H%M%SZ")
    run_dir = LABELING_DIR / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    excluded = []
    pending_ids = [case["case_id"] for case in payload["cases"]]
    reasons = {
        "aq_01_tor_fee": "Approved reference answer exists, but citation usability is unresolved; no gold_citation_ids.",
        "aq_02_diploma_second_copy_fee": "No human-approved reference answer or gold citations.",
        "aq_03_enrollment_office": "No human-approved reference answer or gold citations.",
        "aq_05_library_overdue_fee": "insufficient_evidence; proposed_reference_answer is null.",
        "aq_06_entrance_exam_duration": "No human-approved reference answer or gold citations.",
        "aq_07_id_validation_process": "No human-approved reference answer or gold citations.",
        "aq_09_faculty_teaching_load": "No human-approved reference answer or gold citations.",
        "aq_10_faculty_responsibilities": "Approved reference answer exists, but citation gold is held (wrong title/page/viewer).",
        "aq_11_honorable_dismissal": "No human-approved reference answer or gold citations.",
        "aq_12_university_president": "insufficient_evidence; approved reference answer is null; no gold citations.",
        "aq_13_out_of_scope_weather_mars": "out_of_scope; no LSPU reference answer or gold citations.",
        "aq_14_insufficient_wifi_password": "insufficient_evidence; proposed_reference_answer is null.",
    }
    for case_id in pending_ids:
        if case_id not in APPROVED_CASE_IDS:
            excluded.append({"case_id": case_id, "reason": reasons.get(case_id, "Not in the approved citation+answer subset.")})

    evaluated: list[dict[str, Any]] = []
    rag_cases: list[RagCaseResult] = []
    for case in cases:
        print(f"EVALUATING {case['case_id']} ...", flush=True)
        record = run_one_case(case=case, store=store)
        rag_case = record.pop("_rag_case", None)
        evaluated.append(record)
        if rag_case is not None and record["status"] == "evaluated":
            rag_cases.append(rag_case)
        print(f"  status={record['status']} latency_ms={record['latency_ms']}", flush=True)

    aggregate: dict[str, Any]
    if rag_cases:
        metrics = aggregate_rag_metrics(rag_cases)
        aggregate = {
            "case_count": metrics.case_count,
            "answer_correctness": metrics.answer_correctness,
            "answer_relevancy": metrics.answer_relevancy,
            "faithfulness": metrics.faithfulness,
            "claim_support_rate": metrics.claim_support_rate,
            "citation_set_precision": metrics.citation_set_precision,
            "citation_set_recall": metrics.citation_set_recall,
            "metric_contributing_counts": metrics.metric_contributing_counts,
            "null_means_unavailable_not_zero": True,
        }
    else:
        aggregate = {"case_count": 0, "note": "No successfully evaluated cases."}

    report = {
        "run_id": run_id,
        "created_at_utc": created.isoformat(),
        "pipeline": {
            "target_function": "app.services.qa.question_answering.answer_qa_question",
            "not_used": "app.services.qa.groq_answer_service.generate_groq_answer as a standalone eval target",
            "corpus": str(LABELED_RETRIEVAL_INDEX_PATH),
            "collection": LABELED_RETRIEVAL_COLLECTION,
            "chunk_count": inner.chunk_count,
            "user_role": "student",
            "citation_verification_mode_for_display": "lexical",
            "faithfulness_verifier_mode": "llm",
            "generation_model": settings.groq_model,
            "llm_base_url_host": settings.llm_base_url.split("/")[2] if "://" in settings.llm_base_url else "unknown",
            "llm_generation_succeeded_case_count": sum(
                1 for case in evaluated if case.get("llm_generation_succeeded")
            ),
            "fallback_used_case_count": sum(1 for case in evaluated if case.get("fallback_used")),
        },
        "dataset": {
            "path": str(PENDING_DATASET_PATH),
            "dataset_version": payload.get("dataset_version"),
            "evaluation_ready": payload.get("evaluation_ready"),
            "labeling_status_of_all_cases": payload.get("labeling_status_of_all_cases"),
            "sha256": EXPECTED_PENDING_SHA256,
            "pending_dataset_unchanged": True,
            "rag_eval_dataset_unchanged": True,
        },
        "cases": evaluated,
        "excluded_cases": excluded,
        "aggregate": aggregate,
        "limitations": [
            "Only 2 of 14 pending cases have both an approved reference answer and approved gold citations.",
            "answer_correctness is required-fact coverage against the approved reference, not RAGAS.",
            "answer_relevancy is distinctive question-token overlap, not RAGAS.",
            "Student-visible citations were scored from lexical V1; local .env async_llm was not used because it returns zero citations until a background job finishes.",
            "LLM-verifier faithfulness is a separate scoring call and can be unavailable if the verifier fails.",
            "Postgres citation resolution may still run for PDF viewer URLs against the local database; retrieval used only chroma_evaluation.",
            "No production Chroma, Heroku, retrieval dataset, or classification dataset was modified.",
        ],
        "files_not_modified": [
            "backend/benchmarks/evaluation/answer_quality_labeling/answer_quality_eval_dataset.pending_human_review.json",
            "backend/benchmarks/evaluation/rag_eval_dataset.json",
            "backend/benchmarks/evaluation/retrieval_relevance_dataset.json",
            "backend/benchmarks/evaluation/classification_eval_dataset.json",
            "data/chroma_evaluation",
            "data/chroma",
        ],
    }

    (run_dir / "run_metadata.json").write_text(
        json.dumps(
            {key: report[key] for key in ("run_id", "created_at_utc", "pipeline", "dataset", "limitations", "files_not_modified")},
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    (run_dir / "raw_evidence.json").write_text(json.dumps({"cases": evaluated}, indent=2, default=str), encoding="utf-8")
    (run_dir / "per_case_metrics.json").write_text(
        json.dumps(
            [
                {
                    "case_id": case["case_id"],
                    "status": case["status"],
                    "metrics": case.get("metrics"),
                    "displayed_citation_ids": case.get("displayed_citation_ids"),
                    "gold_citation_ids": case.get("gold_citation_ids"),
                }
                for case in evaluated
            ],
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    (run_dir / "aggregate_metrics.json").write_text(json.dumps(aggregate, indent=2, default=str), encoding="utf-8")
    write_report(run_dir, report)

    print(f"RUN_DIR={run_dir}", flush=True)
    print(json.dumps(aggregate, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
