"""Stage 3.1 QA answer capture for experiment family ``qa_citation_v1``.

Loads a live ``qa_citation_eval_dataset.json`` through the Stage 2 loader,
runs the production ``answer_qa_question()`` path as a student against
``LabeledRetrievalStore`` (verified evaluation corpus), and writes one
final execution record per case per run.

This module does not call ``generate_groq_answer()`` as a substitute, does
not judge answers or citations, and does not overwrite a previous run.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from unittest.mock import patch

from app.config import settings
from app.services.chroma_store import RetrievedChunk, select_role_visible_hits
from app.services.embeddings import current_embedding_model_label
from app.services.evaluation.labeled_retrieval_store import (
    EXPECTED_LABELED_RETRIEVAL_CHUNK_COUNT,
    LABELED_RETRIEVAL_COLLECTION,
    LABELED_RETRIEVAL_INDEX_PATH,
    LabeledRetrievalStore,
)
from app.services.evaluation.qa_citation_corpus import (
    EVALUATION_CHROMA_DIR,
    PRODUCTION_CHROMA_DIR,
    CorpusIdentityError,
    EvaluationCorpusIdentity,
    verify_evaluation_corpus,
)
from app.services.evaluation.qa_citation_dataset import (
    EXPERIMENT_FAMILY,
    LOCKED_CORPUS_CHUNK_COUNT,
    LOCKED_CORPUS_COLLECTION,
    LOCKED_CORPUS_EXTRACT_ARTIFACT,
    LOCKED_CORPUS_PATH,
    LOCKED_IDENTITY_DIGEST,
    LOCKED_METADATA_TEXT_DIGEST,
    QaCitationCase,
    QaCitationDataset,
    QaCitationDatasetError,
    is_example_artifact,
    load_qa_citation_dataset,
)
from app.services.evaluation.qa_citation_metrics import (
    EXECUTION_STATUS_ERROR,
    EXECUTION_STATUS_INCOMPLETE,
    EXECUTION_STATUS_OK,
    EXECUTION_STATUS_OOS_OR_REFUSAL,
    EXECUTION_STATUSES,
    ExecutionRecord,
    aggregate_execution_records,
)
from app.services.qa.groq_answer_service import ASKA_PIYU_SYSTEM_PROMPT, GroqAnswerError
from app.services.qa.question_answering import (
    FACULTY_SIGNIN_ANSWER,
    OUT_OF_SCOPE_ANSWER,
    QAResult,
    answer_qa_question,
)

_BACKEND_ROOT = Path(__file__).resolve().parents[3]

PIPELINE_NAME = "answer_qa_question"
CAPTURE_USER_ROLE = "student"
DEFAULT_LIVE_DATASET_PATH = (
    _BACKEND_ROOT / "benchmarks" / "evaluation" / "qa_citation_eval_dataset.json"
)
DEFAULT_RUNS_DIR = _BACKEND_ROOT / "benchmarks" / "evaluation" / "qa_citation_runs"
CORPUS_VERIFICATION_REPORT_PATH = (
    _BACKEND_ROOT
    / "benchmarks"
    / "evaluation"
    / "qa_citation_contract"
    / "corpus_identity_verification.json"
)

_OOS_FALLBACK_REASONS = frozenset(
    {
        "faculty_topic_hidden_from_role",
    }
)
_SECRET_KEY_NAMES = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "password",
        "secret",
        "token",
        "access_token",
        "refresh_token",
        "credential",
        "groq_api_key",
        "openai_api_key",
    }
)
_SECRET_KEY_SUFFIXES = (
    "_api_key",
    "_apikey",
    "_password",
    "_secret",
    "_token",
    "_credential",
)


class QaCitationCaptureError(ValueError):
    """Capture cannot proceed, or a run-level rule was violated."""


@dataclass(frozen=True)
class CaptureRunResult:
    run_id: str
    output_dir: Path
    dataset_path: str
    dataset_version: str
    dataset_json_sha256: str
    corpus: dict[str, Any]
    records: tuple[dict[str, Any], ...]
    status_counts: dict[str, int]
    live_benchmark_executed: bool


class EvaluationStudentStore:
    """Capture-only adapter over ``LabeledRetrievalStore``.

    ``answer_qa_question`` calls ``get_knowledge_base_store()`` and then
    ``store.search(..., user_role=)`` plus ``store.list_chunks()``. The
    labeled store is the verified evaluation corpus but does not apply
    production audience filtering or expose ``list_chunks``. This wrapper
    adds those surfaces without writing and without opening production
    Chroma.
    """

    def __init__(self, inner: LabeledRetrievalStore) -> None:
        resolved = Path(LABELED_RETRIEVAL_INDEX_PATH).resolve()
        if resolved == PRODUCTION_CHROMA_DIR.resolve():
            raise QaCitationCaptureError(
                "Refusing to use production Chroma as the evaluation corpus."
            )
        if resolved != EVALUATION_CHROMA_DIR.resolve():
            raise QaCitationCaptureError(
                f"Unexpected evaluation index path: {resolved}"
            )
        self._inner = inner

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
            query,
            top_k=candidate_k,
            raw_k=candidate_k,
            user_role=user_role,
            ablation=ablation,
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


@contextmanager
def _force_synchronous_citation_verification():
    """Capture-process-local override: force synchronous ``llm`` citation
    verification instead of the deployed ``async_llm`` default.

    ``run_answer_capture`` calls ``answer_qa_question()`` directly, never
    through the real ``/qa/ask`` HTTP route, so it never has a
    ``BackgroundTasks`` instance to pass into
    ``citation_verification_jobs.schedule_verification()``. Under
    ``async_llm`` this means citation verification is never scheduled at
    all -- every capture record ends up with empty ``displayed_citation_
    ids``, regardless of whether the chatbot actually produced a well-cited
    answer (confirmed by a live run on 2026-11-09: 35/36 genuine answers,
    0/36 with any displayed citation).

    ``citation_verification_jobs.py``'s own ``_ASYNC_TO_SEMANTIC_MODE``
    mapping (``{"async_llm": "llm"}``) shows the deferred background job,
    if it ran, would call ``verify_citations(mode="llm")`` -- the exact
    same verification decision ``"llm"`` mode makes inline. Running the
    capture process under ``"llm"`` therefore reproduces the real
    verification decision synchronously, with no behavioral difference
    other than timing: the fail-closed rule ("a verifier failure of any
    kind displays zero citations") still applies identically.

    This only ever changes ``settings.citation_verification_mode`` for the
    lifetime of this context manager, inside THIS process. It never writes
    to ``backend/.env`` or changes ``app/config.py``'s default, so the
    deployed application's own ``async_llm`` behavior -- including its
    actual background-job scheduling and execution -- is completely
    unaffected. The original value is always restored, including when an
    exception propagates.
    """
    original_mode = settings.citation_verification_mode
    settings.citation_verification_mode = "llm"
    try:
        yield
    finally:
        settings.citation_verification_mode = original_mode


def new_run_id(*, captured_at: datetime | None = None) -> str:
    stamp = (captured_at or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    return f"qac_capture_{stamp}_{uuid.uuid4().hex[:8]}"


def chatbot_prompt_identity() -> dict[str, str]:
    encoded = ASKA_PIYU_SYSTEM_PROMPT.encode("utf-8")
    return {
        "system_prompt_name": "ASKA_PIYU_SYSTEM_PROMPT",
        "system_prompt_sha256": hashlib.sha256(encoded).hexdigest(),
    }


def model_config_snapshot() -> dict[str, Any]:
    prompt = chatbot_prompt_identity()
    return {
        "answer_generation_model": settings.groq_model,
        "embedding_model": current_embedding_model_label(),
        "embedding_backend": settings.embedding_backend,
        "citation_verification_mode": settings.citation_verification_mode,
        "citation_verifier_model": settings.citation_verifier_model,
        "config_snapshot": {
            "pipeline": PIPELINE_NAME,
            "store": "LabeledRetrievalStore",
            "store_adapter": "EvaluationStudentStore",
            "not_generate_groq_answer": True,
            "user_role": CAPTURE_USER_ROLE,
            "citation_verification_mode": settings.citation_verification_mode,
            "llm_base_url_host": _url_host(settings.llm_base_url),
            "system_prompt_name": prompt["system_prompt_name"],
            "system_prompt_sha256": prompt["system_prompt_sha256"],
        },
    }


def classify_execution_status(
    result: QAResult | None,
    *,
    error: BaseException | None = None,
) -> str:
    """Map a capture attempt to the approved Stage 2 execution statuses.

    ``ok`` means capture completed, not that the answer is correct.
    """
    if error is not None:
        return EXECUTION_STATUS_ERROR
    if result is None:
        return EXECUTION_STATUS_INCOMPLETE
    answer = result.answer
    if answer is None:
        return EXECUTION_STATUS_INCOMPLETE
    if not isinstance(answer, str):
        return EXECUTION_STATUS_INCOMPLETE
    if result.out_of_scope_detected:
        return EXECUTION_STATUS_OOS_OR_REFUSAL
    if (result.fallback_reason or "") in _OOS_FALLBACK_REASONS:
        return EXECUTION_STATUS_OOS_OR_REFUSAL
    if answer in {OUT_OF_SCOPE_ANSWER, FACULTY_SIGNIN_ANSWER}:
        return EXECUTION_STATUS_OOS_OR_REFUSAL
    if not answer.strip():
        return EXECUTION_STATUS_INCOMPLETE
    return EXECUTION_STATUS_OK


def capture_one_case(
    case: QaCitationCase,
    *,
    run_id: str,
    dataset: QaCitationDataset,
    corpus_identity: EvaluationCorpusIdentity,
    store: Any,
    captured_at: str,
    model_snapshot: Mapping[str, Any] | None = None,
    answer_fn: Callable[..., QAResult] | None = None,
) -> dict[str, Any]:
    """Run one case through ``answer_qa_question`` and return a capture record.

    Exceptions become ``error`` records. They are not dropped.
    """
    if answer_fn is None:
        answer_fn = answer_qa_question
    if getattr(answer_fn, "__name__", "") == "generate_groq_answer":
        raise QaCitationCaptureError(
            "Refusing to capture via generate_groq_answer(). "
            "Stage 3.1 must use answer_qa_question()."
        )

    citation_debug_sink: list[dict[str, Any]] = []
    generation_usage_sink: dict[str, Any] = {}
    answer_rewrite_sink: dict[str, Any] = {}
    generation_context_sink: dict[str, Any] = {}
    citation_v2_sink: dict[str, Any] = {}
    async_verification_sink: dict[str, Any] = {}
    timing_sink: dict[str, float] = {}

    result: QAResult | None = None
    error: BaseException | None = None
    try:
        with patch(
            "app.services.qa.question_answering.get_knowledge_base_store",
            return_value=store,
        ):
            result = answer_fn(
                case.question,
                user_role=CAPTURE_USER_ROLE,
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
        error = exc
    except Exception as exc:  # noqa: BLE001 — record the failure, do not drop the case
        error = exc

    return build_capture_record(
        case=case,
        run_id=run_id,
        dataset=dataset,
        corpus_identity=corpus_identity,
        captured_at=captured_at,
        model_snapshot=model_snapshot or model_config_snapshot(),
        result=result,
        error=error,
        citation_debug_sink=citation_debug_sink,
        generation_usage_sink=generation_usage_sink,
        answer_rewrite_sink=answer_rewrite_sink,
        generation_context_sink=generation_context_sink,
        citation_v2_sink=citation_v2_sink,
        timing_sink=timing_sink,
    )


def build_capture_record(
    *,
    case: QaCitationCase,
    run_id: str,
    dataset: QaCitationDataset,
    corpus_identity: EvaluationCorpusIdentity,
    captured_at: str,
    model_snapshot: Mapping[str, Any],
    result: QAResult | None,
    error: BaseException | None,
    citation_debug_sink: Sequence[Mapping[str, Any]] | None = None,
    generation_usage_sink: Mapping[str, Any] | None = None,
    answer_rewrite_sink: Mapping[str, Any] | None = None,
    generation_context_sink: Mapping[str, Any] | None = None,
    citation_v2_sink: Mapping[str, Any] | None = None,
    timing_sink: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    status = classify_execution_status(result, error=error)
    retrieved_rows = list((result.retrieved_chunks if result is not None else None) or [])
    sources = list((result.sources if result is not None else None) or [])
    retrieved_chunk_ids = [
        str(row.get("citation_id") or "")
        for row in retrieved_rows
        if str(row.get("citation_id") or "")
    ]
    displayed_citation_ids = [
        str(source.get("citation_id") or "")
        for source in sources
        if str(source.get("citation_id") or "")
    ]
    generation_context_chunk_ids = [
        str(row.get("citation_id") or "")
        for row in list((generation_context_sink or {}).get("final_context_chunks") or [])
        if str(row.get("citation_id") or "")
    ]
    retrieved_context = _retrieved_context_text(retrieved_rows)
    source_metadata = [_source_metadata(source) for source in sources]

    generated_answer = None
    fallback_reason = None
    out_of_scope_detected = False
    fallback_used = False
    if result is not None:
        generated_answer = result.answer
        fallback_reason = result.fallback_reason
        out_of_scope_detected = bool(result.out_of_scope_detected)
        fallback_used = bool(result.fallback_used)
    # Whether `generated_answer` is genuine LLM output vs. a template/
    # extractive/recovered stand-in `answer_qa_question` substitutes when the
    # real generation call didn't happen or failed (any fallback path --
    # retrieval-quality gating, scope handling, or a Groq/OpenRouter error
    # alike). `execution_status` alone cannot distinguish this: a fallback
    # answer is still a complete, non-empty string, so `classify_execution_
    # status` legitimately reports `ok` (capture completed) even though no
    # genuine generation occurred. None when there is no result to judge
    # (error/incomplete captures). A future judging stage MUST check this
    # before scoring `generated_answer` as reflecting real model behavior.
    is_genuine_model_output = (not fallback_used) if result is not None else None

    record = {
        "run_id": run_id,
        "case_id": case.case_id,
        "execution_status": status,
        "captured_at": captured_at,
        "pipeline": PIPELINE_NAME,
        "user_role": CAPTURE_USER_ROLE,
        "experiment_family": EXPERIMENT_FAMILY,
        "dataset_version": dataset.dataset_version,
        "dataset_json_sha256": dataset.dataset_json_sha256,
        "dataset_source_path": dataset.source_path,
        "case_type": case.case_type,
        "labeling_status": case.labeling_status,
        "corpus": {
            "path": corpus_identity.evaluation_path,
            "collection": corpus_identity.evaluation_collection,
            "chunk_count": corpus_identity.evaluation_record_count,
            "extract_artifact": corpus_identity.extract_artifact,
            "identity_digest": corpus_identity.evaluation_identity_digest,
            "metadata_text_digest": corpus_identity.evaluation_metadata_text_digest,
            "evaluation_sqlite_sha256": corpus_identity.evaluation_sqlite_sha256,
            "corresponds_to_locked_extract": corpus_identity.corresponds,
        },
        "model": dict(model_snapshot),
        "generated_answer": generated_answer,
        "retrieved_context": retrieved_context,
        "retrieved_chunk_ids": retrieved_chunk_ids,
        "displayed_citation_ids": displayed_citation_ids,
        "generation_context_chunk_ids": generation_context_chunk_ids,
        "source_metadata": source_metadata,
        "fallback_reason": fallback_reason,
        "fallback_used": fallback_used,
        "is_genuine_model_output": is_genuine_model_output,
        "out_of_scope_detected": out_of_scope_detected,
        "error_type": type(error).__name__ if error is not None else None,
        "error_message": _safe_error_message(error),
        "raw_qa_result_json": _strip_secrets(
            {
                "qa_result": _qa_result_dump(result),
                "generation_usage_sink": dict(generation_usage_sink or {}),
                "answer_rewrite_sink": dict(answer_rewrite_sink or {}),
                "generation_context_sink": dict(generation_context_sink or {}),
                "citation_v2_sink": dict(citation_v2_sink or {}),
                "timing_sink": dict(timing_sink or {}),
                "citation_debug_sink_count": len(list(citation_debug_sink or [])),
            }
        ),
    }
    if status not in EXECUTION_STATUSES:
        raise QaCitationCaptureError(
            f"Case {case.case_id!r}: invalid execution_status {status!r}."
        )
    return record


def assert_one_record_per_case(records: Sequence[Mapping[str, Any]]) -> None:
    """Reject duplicate case_ids. Do not overwrite a previous record."""
    seen: dict[str, int] = {}
    for index, record in enumerate(records):
        case_id = str(record.get("case_id") or "")
        if not case_id:
            raise QaCitationCaptureError(f"Capture record at index {index} is missing case_id.")
        previous = seen.get(case_id)
        if previous is not None:
            raise QaCitationCaptureError(
                f"Duplicate capture case_id {case_id!r} at index {index} "
                f"(first seen at index {previous}). One final record per case "
                "per run; previous results are not overwritten."
            )
        seen[case_id] = index


def run_answer_capture(
    *,
    dataset_path: str | Path | None = None,
    output_dir: str | Path | None = None,
    run_id: str | None = None,
    store: Any | None = None,
    corpus_identity: EvaluationCorpusIdentity | None = None,
    answer_fn: Callable[..., QAResult] | None = None,
    persist_corpus_report: bool = True,
) -> CaptureRunResult:
    """Load the Stage 2 dataset, capture every case, write a new run directory.

    Never overwrites an existing run. Failed and incomplete cases stay on
    the run. Does not invent a live dataset when the file is absent.
    """
    path = Path(dataset_path) if dataset_path is not None else DEFAULT_LIVE_DATASET_PATH
    if is_example_artifact(None, path):
        raise QaCitationCaptureError(
            f"Refusing to capture from example artifact: {path}"
        )
    if not path.exists():
        raise QaCitationCaptureError(
            f"Live QA/citation dataset not found: {path}. "
            "Stage 3.1 does not invent evaluation cases. Capture was not executed."
        )

    try:
        dataset = load_qa_citation_dataset(path)
    except QaCitationDatasetError as exc:
        raise QaCitationCaptureError(str(exc)) from exc

    if corpus_identity is None:
        report_path = CORPUS_VERIFICATION_REPORT_PATH if persist_corpus_report else None
        try:
            corpus_identity = verify_evaluation_corpus(persist_report_path=report_path)
        except CorpusIdentityError as exc:
            raise QaCitationCaptureError(
                f"Corpus correspondence failed. Do not execute the benchmark. {exc}"
            ) from exc
    if not corpus_identity.corresponds:
        raise QaCitationCaptureError(
            "Corpus identity is not verified. Do not execute the benchmark."
        )

    if store is None:
        labeled = LabeledRetrievalStore(
            index_path=LABELED_RETRIEVAL_INDEX_PATH,
            collection_name=LABELED_RETRIEVAL_COLLECTION,
        )
        if labeled.chunk_count != EXPECTED_LABELED_RETRIEVAL_CHUNK_COUNT:
            raise QaCitationCaptureError(
                f"LabeledRetrievalStore chunk_count={labeled.chunk_count}, "
                f"expected {EXPECTED_LABELED_RETRIEVAL_CHUNK_COUNT}."
            )
        store = EvaluationStudentStore(labeled)

    captured_dt = datetime.now(timezone.utc)
    captured_at = captured_dt.isoformat()
    resolved_run_id = run_id or new_run_id(captured_at=captured_dt)
    runs_root = Path(output_dir) if output_dir is not None else DEFAULT_RUNS_DIR
    run_dir = runs_root / resolved_run_id
    if run_dir.exists():
        raise QaCitationCaptureError(
            f"Capture run directory already exists: {run_dir}. "
            "Previous results are not overwritten. Use a new run_id."
        )

    with _force_synchronous_citation_verification():
        # model_snapshot is computed INSIDE the override so its
        # citation_verification_mode fields accurately report "llm" -- what
        # this run actually used -- not the ambient async_llm default.
        model_snapshot = model_config_snapshot()
        records: list[dict[str, Any]] = []
        for case in dataset.cases:
            records.append(
                capture_one_case(
                    case,
                    run_id=resolved_run_id,
                    dataset=dataset,
                    corpus_identity=corpus_identity,
                    store=store,
                    captured_at=captured_at,
                    model_snapshot=model_snapshot,
                    answer_fn=answer_fn,
                )
            )

    assert_one_record_per_case(records)
    aggregation = aggregate_execution_records(
        [
            ExecutionRecord(
                case_id=str(record["case_id"]),
                execution_status=str(record["execution_status"]),
            )
            for record in records
        ]
    )
    status_counts = _status_counts(records)
    if sum(status_counts.values()) != len(records) or len(records) != dataset.total_count:
        raise QaCitationCaptureError(
            "Capture dropped or duplicated cases. "
            f"dataset.total_count={dataset.total_count} records={len(records)} "
            f"status_counts={status_counts}"
        )

    run_dir.mkdir(parents=True, exist_ok=False)
    captures_path = run_dir / "captures.jsonl"
    summary_path = run_dir / "summary.json"
    captures_path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )
    summary = {
        "run_id": resolved_run_id,
        "experiment_family": EXPERIMENT_FAMILY,
        "pipeline": PIPELINE_NAME,
        "user_role": CAPTURE_USER_ROLE,
        "captured_at": captured_at,
        "dataset_path": str(path),
        "dataset_version": dataset.dataset_version,
        "dataset_json_sha256": dataset.dataset_json_sha256,
        "case_count": aggregation.case_count,
        "successful_executions": aggregation.successful_executions,
        "failed_executions": aggregation.failed_executions,
        "status_counts": status_counts,
        "completion_rate": {
            "numerator": aggregation.completion_rate.numerator,
            "denominator": aggregation.completion_rate.denominator,
            "value": aggregation.completion_rate.value,
        },
        "corpus": corpus_identity.as_dict(),
        "model": model_snapshot,
        "locked_corpus": {
            "path": LOCKED_CORPUS_PATH,
            "collection": LOCKED_CORPUS_COLLECTION,
            "expected_chunk_count": LOCKED_CORPUS_CHUNK_COUNT,
            "extract_artifact": LOCKED_CORPUS_EXTRACT_ARTIFACT,
            "identity_digest": LOCKED_IDENTITY_DIGEST,
            "metadata_text_digest": LOCKED_METADATA_TEXT_DIGEST,
        },
        "live_benchmark_executed": True,
        "notes": (
            "Successful execution (ok / oos_or_refusal) does not mean the "
            "answer is correct. Stage 3.1 does not judge."
        ),
    }
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return CaptureRunResult(
        run_id=resolved_run_id,
        output_dir=run_dir,
        dataset_path=str(path),
        dataset_version=dataset.dataset_version,
        dataset_json_sha256=dataset.dataset_json_sha256,
        corpus=corpus_identity.as_dict(),
        records=tuple(records),
        status_counts=status_counts,
        live_benchmark_executed=True,
    )


def _status_counts(records: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts = {
        EXECUTION_STATUS_OK: 0,
        EXECUTION_STATUS_OOS_OR_REFUSAL: 0,
        EXECUTION_STATUS_ERROR: 0,
        EXECUTION_STATUS_INCOMPLETE: 0,
    }
    for record in records:
        status = str(record.get("execution_status") or "")
        if status not in counts:
            raise QaCitationCaptureError(
                f"Case {record.get('case_id')!r}: unsupported execution_status {status!r}."
            )
        counts[status] += 1
    return counts


def _retrieved_context_text(retrieved_rows: Sequence[Mapping[str, Any]]) -> str | None:
    if not retrieved_rows:
        return None
    selected = [
        row for row in retrieved_rows if row.get("selected_for_context") is True
    ]
    rows = selected or list(retrieved_rows)
    parts: list[str] = []
    for row in rows:
        citation_id = str(row.get("citation_id") or "").strip()
        preview = str(row.get("content_preview") or row.get("text") or "").strip()
        title = str(row.get("title") or "").strip()
        if not preview and not citation_id:
            continue
        header = citation_id or title or "chunk"
        parts.append(f"[{header}] {preview}".strip())
    return "\n\n".join(parts) if parts else None


def _source_metadata(source: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "citation_id": source.get("citation_id"),
        "document_id": source.get("document_id"),
        "title": source.get("title"),
        "source_filename": source.get("source_filename"),
        "page_number": source.get("page_number", source.get("page")),
        "source_section": source.get("source_section"),
    }


def _qa_result_dump(result: QAResult | None) -> dict[str, Any] | None:
    if result is None:
        return None
    payload: dict[str, Any]
    if is_dataclass(result):
        payload = asdict(result)
    else:
        payload = dict(vars(result))
    return _strip_secrets(payload)


def _is_secret_key(key: str) -> bool:
    text = str(key).lower()
    if text in _SECRET_KEY_NAMES:
        return True
    return any(text.endswith(suffix) for suffix in _SECRET_KEY_SUFFIXES)


def _safe_error_message(error: BaseException | None) -> str | None:
    if error is None:
        return None
    text = str(error)
    lowered = text.lower()
    if any(name in lowered for name in ("api_key", "password", "authorization", "secret")):
        return type(error).__name__
    return text


def _strip_secrets(value: Any) -> Any:
    if isinstance(value, Mapping):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            if _is_secret_key(key):
                cleaned[str(key)] = "[redacted]"
            else:
                cleaned[str(key)] = _strip_secrets(item)
        return cleaned
    if isinstance(value, list):
        return [_strip_secrets(item) for item in value]
    if isinstance(value, tuple):
        return [_strip_secrets(item) for item in value]
    return value


def _url_host(url: str | None) -> str | None:
    if not url:
        return None
    try:
        from urllib.parse import urlsplit

        return urlsplit(url).netloc or None
    except Exception:  # noqa: BLE001
        return None
