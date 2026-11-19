"""Unit tests for app.services.evaluation.evaluation_service.

Every external/chatbot dependency (classify_chunk, classify_question,
generate_groq_answer, verify_citations, the Chroma store) is mocked here
-- these tests exercise ONLY evaluation_service's own orchestration logic
(dataset filtering, not_evaluable handling, cold/warm tracking, model-
sharing bookkeeping), never a real network call. citation_verification.py
and knowledge_taxonomy.py's own internals already have their own test
suites; this file does not re-test them.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.services.chroma_store import RetrievedChunk
from app.services.evaluation import evaluation_service as svc
from app.services.evaluation.datasets import load_classification_dataset, load_rag_dataset, load_retrieval_dataset
from app.services.qa.citation_verification import Claim, VerificationOutcome
from app.services.qa.groq_answer_service import GroqAnswerError


def _write_json(tmp_path, name: str, payload: dict) -> str:
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


class _FakeStore:
    """Read-only stand-in for KnowledgeBaseStore -- exposes only .search()."""

    def __init__(self, chunks_by_query: dict[str, list[RetrievedChunk]]) -> None:
        self._chunks_by_query = chunks_by_query
        self.search_calls: list[dict] = []

    def search(self, query, *, top_k=None, raw_k=None, user_role=None, ablation=None):
        self.search_calls.append({"query": query, "top_k": top_k, "raw_k": raw_k})
        return list(self._chunks_by_query.get(query, []))


def _chunk(chunk_id: str, document_id: str, *, original_score: float, text: str = "chunk text") -> RetrievedChunk:
    return RetrievedChunk(
        document_id=document_id,
        title="Some Service",
        source_filename="handbook.pdf",
        chunk_index=0,
        text=text,
        relevance_score=original_score,
        original_score=original_score,
        reranked_score=original_score,
        metadata={"chunk_id": chunk_id, "page_number": 5},
    )


# --- model_inventory ----------------------------------------------------------


def test_model_inventory_marks_citation_verifier_as_sharing_when_unset(monkeypatch):
    monkeypatch.setattr(svc.settings, "citation_verifier_model", None)
    monkeypatch.setattr(svc.settings, "groq_model", "llama-shared")
    inventory = {m.component: m for m in svc.model_inventory()}
    verifier = inventory["citation_verifier_llm"]
    assert verifier.shares_model_with == "answer_generation_llm"
    assert verifier.model_name == "llama-shared"


def test_model_inventory_treats_distinct_verifier_model_as_independent(monkeypatch):
    monkeypatch.setattr(svc.settings, "citation_verifier_model", "distinct-verifier-model")
    inventory = {m.component: m for m in svc.model_inventory()}
    verifier = inventory["citation_verifier_llm"]
    assert verifier.shares_model_with is None
    assert verifier.model_name == "distinct-verifier-model"


# --- classify_chunk / classify_question ---------------------------------------


def test_evaluate_classify_chunk_not_evaluable_without_labeled_cases(tmp_path):
    path = _write_json(tmp_path, "c.json", {"dataset_version": "v1", "cases": []})
    dataset = load_classification_dataset(path)
    result = svc.evaluate_classify_chunk(dataset, allow_llm=True)
    assert result.status == svc.NOT_EVALUABLE
    assert "no labeled classify_chunk" in result.reason


def test_evaluate_classify_chunk_computes_metrics_and_passes_allow_llm_through(tmp_path, monkeypatch):
    path = _write_json(
        tmp_path, "c.json",
        {
            "dataset_version": "v1",
            "cases": [
                {"case_id": "1", "text": "enroll now", "true_label": "Enrollment", "component": "classify_chunk", "labeling_status": "labeled"},
                {"case_id": "2", "text": "library book", "true_label": "Library", "component": "classify_chunk", "labeling_status": "labeled"},
            ],
        },
    )
    dataset = load_classification_dataset(path)
    seen_allow_llm = []

    def _fake_classify_chunk(text, *, allow_llm=True, metadata=None, title=None):
        seen_allow_llm.append(allow_llm)
        return SimpleNamespace(subcategory="Enrollment" if "enroll" in text else "Library")

    monkeypatch.setattr(svc, "classify_chunk", _fake_classify_chunk)
    result = svc.evaluate_classify_chunk(dataset, allow_llm=False)
    assert result.status == svc.EVALUATED
    assert result.classification_metrics.accuracy == 1.0
    assert result.confusion_matrix is not None
    assert seen_allow_llm == [False, False]
    assert result.model_info.allow_llm_fallback is False
    assert len(result.case_results) == 2
    assert {cr.case_id for cr in result.case_results} == {"1", "2"}
    assert all(cr.correct is True for cr in result.case_results)


def test_evaluate_classify_question_never_passes_allow_llm(tmp_path, monkeypatch):
    path = _write_json(
        tmp_path, "c.json",
        {
            "dataset_version": "v1",
            "cases": [
                {"case_id": "1", "text": "where do I enroll", "true_label": "Enrollment", "component": "classify_question", "labeling_status": "labeled"},
            ],
        },
    )
    dataset = load_classification_dataset(path)
    calls = []

    def _fake_classify_question(question):
        calls.append(question)
        return SimpleNamespace(subcategory="Enrollment")

    monkeypatch.setattr(svc, "classify_question", _fake_classify_question)
    result = svc.evaluate_classify_question(dataset)
    assert result.status == svc.EVALUATED
    assert calls == ["where do I enroll"]
    assert result.model_info.allow_llm_fallback is False


# --- retrieval: embedding-only vs. reranked -----------------------------------


def test_evaluate_retrieval_not_evaluable_when_dataset_empty():
    from app.services.evaluation.datasets import DatasetLoadResult

    empty = DatasetLoadResult(dataset_version="v1", kind="retrieval", labeled_cases=(), unlabeled_count=0, total_count=0)
    embedding_result, reranker_result = svc.evaluate_retrieval(empty, store=_FakeStore({}))
    assert embedding_result.status == svc.NOT_EVALUABLE
    assert reranker_result.status == svc.NOT_EVALUABLE


def test_evaluate_retrieval_derives_both_rankings_from_one_search_call(tmp_path):
    path = _write_json(
        tmp_path, "r.json",
        {
            "dataset_version": "v1",
            "cases": [
                {"query_id": "q1", "query": "how do I enroll", "relevant_ids": ["B"], "labeling_status": "labeled"},
            ],
        },
    )
    dataset = load_retrieval_dataset(path)
    # Store's own (reranked) order puts A first; by raw vector similarity B > A.
    chunk_a = _chunk("A", "doc-a", original_score=0.70)
    chunk_b = _chunk("B", "doc-b", original_score=0.95)
    store = _FakeStore({"how do I enroll": [chunk_a, chunk_b]})

    embedding_result, reranker_result = svc.evaluate_retrieval(dataset, store=store, k=1, candidate_pool_size=2)

    assert len(store.search_calls) == 1  # one real call powers both rankings
    assert embedding_result.status == svc.EVALUATED
    assert embedding_result.retrieval_metrics_embedding_only.hit_at_k == 1.0  # B found by vector similarity
    assert reranker_result.retrieval_metrics_reranked.hit_at_k == 0.0  # A (not relevant) wins the rerank order
    assert reranker_result.note is not None
    assert embedding_result.case_results[0].predicted == "B"
    assert embedding_result.case_results[0].correct is True
    assert reranker_result.case_results[0].predicted == "A"
    assert reranker_result.case_results[0].correct is False


# --- RAG/LLM: answer generation + citation verifier ---------------------------


def _rag_dataset(tmp_path, cases):
    path = _write_json(tmp_path, "rag.json", {"dataset_version": "v1", "cases": cases})
    return load_rag_dataset(path)


def test_evaluate_rag_components_not_evaluable_without_api_key(tmp_path, monkeypatch):
    dataset = _rag_dataset(
        tmp_path, [{"case_id": "1", "question": "What is the gambling penalty?", "labeling_status": "labeled"}]
    )
    monkeypatch.setattr(svc.settings, "groq_api_key", None)
    answer_result, verifier_result = svc.evaluate_rag_components(
        dataset, store=_FakeStore({}), call_tracker=svc.CallTracker()
    )
    assert answer_result.status == svc.NOT_EVALUABLE
    assert verifier_result.status == svc.NOT_EVALUABLE
    assert "GROQ_API_KEY" in answer_result.reason


def test_evaluate_rag_components_success_path_computes_faithfulness_and_cold_start(tmp_path, monkeypatch):
    monkeypatch.setattr(svc.settings, "groq_api_key", "fake-key-for-test")
    monkeypatch.setattr(svc.settings, "citation_verifier_model", None)
    dataset = _rag_dataset(
        tmp_path,
        [
            {"case_id": "1", "question": "gambling penalty", "gold_citation_ids": ["doc-a::0"], "labeling_status": "labeled"},
            {"case_id": "2", "question": "gambling penalty again", "gold_citation_ids": ["doc-a::0"], "labeling_status": "labeled"},
        ],
    )
    chunk = _chunk("doc-a::0", "doc-a", original_score=0.9)
    store = _FakeStore({"gambling penalty": [chunk], "gambling penalty again": [chunk]})

    answer_calls = []

    def _fake_generate_groq_answer(*, question, context, usage_sink=None, **kwargs):
        answer_calls.append(question)
        if usage_sink is not None:
            usage_sink.update({"prompt_tokens": 100, "completion_tokens": 20})
        return "Suspension for one week."

    def _fake_verify_citations(*, answer, candidates, mode):
        assert mode == "llm"
        citation_id = candidates[0].citation_id
        return VerificationOutcome(
            mode=mode,
            claims=[Claim(claim_id="c1", text="Suspension for one week.")],
            candidate_citation_ids=[citation_id],
            verifier_invoked=True,
            verifier_succeeded=True,
            per_claim_verified_ids={"c1": [citation_id]},
            verified_citation_ids=[citation_id],
            latency_ms=180.0,
            usage={"prompt_tokens": 300, "completion_tokens": 40},
        )

    monkeypatch.setattr(svc, "generate_groq_answer", _fake_generate_groq_answer)
    monkeypatch.setattr(svc, "verify_citations", _fake_verify_citations)

    tracker = svc.CallTracker()
    answer_result, verifier_result = svc.evaluate_rag_components(dataset, store=store, call_tracker=tracker)

    assert answer_calls == ["gambling penalty", "gambling penalty again"]
    assert answer_result.status == svc.EVALUATED
    assert answer_result.performance_metrics.call_count == 2
    assert answer_result.performance_metrics.first_call_in_run_count == 1
    assert answer_result.performance_metrics.warm_call_count == 1
    assert answer_result.performance_metrics.success_rate == 1.0

    assert verifier_result.status == svc.EVALUATED
    assert verifier_result.rag_metrics.faithfulness == 1.0
    assert verifier_result.rag_metrics.citation_set_precision == 1.0
    assert verifier_result.note is not None and "shares the same configured model" in verifier_result.note
    assert verifier_result.performance_metrics.call_count == 2
    assert len(answer_result.case_results) == 2
    assert answer_result.case_results[0].predicted == "Suspension for one week."
    assert len(verifier_result.case_results) == 2
    assert verifier_result.case_results[0].predicted == "doc-a::0"
    assert verifier_result.case_results[0].expected == "doc-a::0"


def test_evaluate_rag_components_records_answer_failure_without_crashing(tmp_path, monkeypatch):
    monkeypatch.setattr(svc.settings, "groq_api_key", "fake-key-for-test")
    dataset = _rag_dataset(
        tmp_path, [{"case_id": "1", "question": "gambling penalty", "labeling_status": "labeled"}]
    )
    store = _FakeStore({"gambling penalty": []})

    def _fake_generate_groq_answer(*, question, context, usage_sink=None, **kwargs):
        raise GroqAnswerError("synthetic failure")

    monkeypatch.setattr(svc, "generate_groq_answer", _fake_generate_groq_answer)
    answer_result, verifier_result = svc.evaluate_rag_components(dataset, store=store, call_tracker=svc.CallTracker())

    assert answer_result.status == svc.EVALUATED
    assert answer_result.performance_metrics.failure_count == 1
    assert answer_result.performance_metrics.success_rate == 0.0
    # No case had a successful answer + gold ids -> verifier not evaluable.
    assert verifier_result.status == svc.NOT_EVALUABLE


def test_evaluate_rag_components_gold_ids_present_but_verifier_never_succeeds_is_not_evaluable(tmp_path, monkeypatch):
    monkeypatch.setattr(svc.settings, "groq_api_key", "fake-key-for-test")
    dataset = _rag_dataset(
        tmp_path, [{"case_id": "1", "question": "gambling penalty", "gold_citation_ids": ["doc-a::0"], "labeling_status": "labeled"}]
    )
    store = _FakeStore({"gambling penalty": [_chunk("doc-a::0", "doc-a", original_score=0.9)]})

    monkeypatch.setattr(svc, "generate_groq_answer", lambda *, question, context, usage_sink=None, **kwargs: "An answer.")
    # Verifier is invoked but fails -- citation_cases_with_gold > 0, yet no
    # LLM citation evaluation actually succeeded.
    monkeypatch.setattr(
        svc, "verify_citations",
        lambda *, answer, candidates, mode: VerificationOutcome(
            mode=mode, claims=[Claim(claim_id="c1", text=answer)],
            candidate_citation_ids=[c.citation_id for c in candidates],
            verifier_invoked=True, verifier_succeeded=False,
            failure_reason="malformed_json",
            per_claim_verified_ids={}, verified_citation_ids=[],
            latency_ms=50.0, usage=None,
        ),
    )
    answer_result, verifier_result = svc.evaluate_rag_components(dataset, store=store, call_tracker=svc.CallTracker())
    assert answer_result.status == svc.EVALUATED
    assert verifier_result.status == svc.NOT_EVALUABLE
    assert "never successfully invoked" in verifier_result.reason
    # The failed call attempt is still visible via performance metrics.
    assert verifier_result.performance_metrics.call_count == 1
    assert verifier_result.performance_metrics.success_rate == 0.0


def test_evaluate_rag_components_without_gold_citation_ids_skips_verifier(tmp_path, monkeypatch):
    monkeypatch.setattr(svc.settings, "groq_api_key", "fake-key-for-test")
    dataset = _rag_dataset(
        tmp_path, [{"case_id": "1", "question": "gambling penalty", "labeling_status": "labeled"}]
    )
    store = _FakeStore({"gambling penalty": [_chunk("doc-a::0", "doc-a", original_score=0.9)]})
    verify_calls = []

    def _fake_generate_groq_answer(*, question, context, usage_sink=None, **kwargs):
        return "An answer."

    def _fake_verify_citations(*, answer, candidates, mode):
        verify_calls.append(mode)
        raise AssertionError("verify_citations must not be called when no gold_citation_ids exist")

    monkeypatch.setattr(svc, "generate_groq_answer", _fake_generate_groq_answer)
    monkeypatch.setattr(svc, "verify_citations", _fake_verify_citations)
    answer_result, verifier_result = svc.evaluate_rag_components(dataset, store=store, call_tracker=svc.CallTracker())

    assert verify_calls == []
    assert answer_result.status == svc.EVALUATED
    assert verifier_result.status == svc.NOT_EVALUABLE


# --- top-level orchestration ---------------------------------------------------


def test_run_evaluation_wires_all_components_with_no_real_network_calls(tmp_path, monkeypatch):
    monkeypatch.setattr(svc.settings, "groq_api_key", "fake-key-for-test")
    monkeypatch.setattr(svc.settings, "citation_verifier_model", None)

    classification_path = _write_json(
        tmp_path, "classification.json",
        {
            "dataset_version": "cv1",
            "cases": [
                {"case_id": "1", "text": "enroll", "true_label": "Enrollment", "component": "classify_chunk", "labeling_status": "labeled"},
                {"case_id": "2", "text": "enroll question", "true_label": "Enrollment", "component": "classify_question", "labeling_status": "labeled"},
            ],
        },
    )
    retrieval_path = _write_json(
        tmp_path, "retrieval.json",
        {
            "dataset_version": "rv1",
            "cases": [{"query_id": "q1", "query": "enroll query", "relevant_ids": ["doc-a::0"], "labeling_status": "labeled"}],
        },
    )
    rag_path = _write_json(
        tmp_path, "rag.json",
        {
            "dataset_version": "gv1",
            "cases": [{"case_id": "1", "question": "enroll question", "gold_citation_ids": ["doc-a::0"], "labeling_status": "labeled"}],
        },
    )

    chunk = _chunk("doc-a::0", "doc-a", original_score=0.9)
    store = _FakeStore(
        {
            "enroll query": [chunk],
            "enroll question": [chunk],
        }
    )

    monkeypatch.setattr(svc, "classify_chunk", lambda text, **kwargs: SimpleNamespace(subcategory="Enrollment"))
    monkeypatch.setattr(svc, "classify_question", lambda question: SimpleNamespace(subcategory="Enrollment"))
    monkeypatch.setattr(
        svc, "generate_groq_answer",
        lambda *, question, context, usage_sink=None, **kwargs: "An answer about enrollment.",
    )
    monkeypatch.setattr(
        svc, "verify_citations",
        lambda *, answer, candidates, mode: VerificationOutcome(
            mode=mode, claims=[Claim(claim_id="c1", text=answer)],
            candidate_citation_ids=[c.citation_id for c in candidates],
            verifier_invoked=True, verifier_succeeded=True,
            per_claim_verified_ids={"c1": [candidates[0].citation_id]},
            verified_citation_ids=[candidates[0].citation_id],
            latency_ms=100.0, usage={"prompt_tokens": 10, "completion_tokens": 5},
        ),
    )

    result = svc.run_evaluation(
        store=store,
        classification_dataset_path=classification_path,
        retrieval_dataset_path=retrieval_path,
        rag_dataset_path=rag_path,
    )

    components_by_name = {c.component: c for c in result.components}
    assert "classify_chunk(allow_llm=True)" in components_by_name
    assert "classify_chunk(allow_llm=False)" in components_by_name
    assert components_by_name["classify_question"].status == svc.EVALUATED
    assert components_by_name["embedding_retrieval"].status == svc.EVALUATED
    assert components_by_name["reranker"].status == svc.EVALUATED
    assert components_by_name["answer_generation_llm"].status == svc.EVALUATED
    assert components_by_name["citation_verifier_llm"].status == svc.EVALUATED
    assert result.dataset_versions == {"classification": "cv1", "retrieval": "rv1", "rag": "gv1"}
    # Real sha256 of each dataset file's raw bytes, for reproducibility.
    assert all(len(v) == 64 for v in result.dataset_sha256.values())
    assert set(result.dataset_sha256) == {"classification", "retrieval", "rag"}


def test_run_evaluation_isolates_one_groups_failure_as_failed_not_lost(tmp_path, monkeypatch):
    """An unexpected exception in the classification group must not discard
    the retrieval/RAG groups' real results -- it becomes a FAILED
    placeholder for just the affected components."""
    monkeypatch.setattr(svc.settings, "groq_api_key", None)  # keeps RAG group a clean not_evaluable, not a real call

    classification_path = _write_json(
        tmp_path, "classification.json",
        {
            "dataset_version": "cv1",
            "cases": [
                {"case_id": "1", "text": "enroll", "true_label": "Enrollment", "component": "classify_chunk", "labeling_status": "labeled"},
            ],
        },
    )
    retrieval_path = _write_json(tmp_path, "retrieval.json", {"dataset_version": "rv1", "cases": []})
    rag_path = _write_json(tmp_path, "rag.json", {"dataset_version": "gv1", "cases": []})

    def _raise_classify_chunk(text, **kwargs):
        raise RuntimeError("synthetic classify_chunk bug")

    monkeypatch.setattr(svc, "classify_chunk", _raise_classify_chunk)

    result = svc.run_evaluation(
        store=_FakeStore({}),
        classification_dataset_path=classification_path,
        retrieval_dataset_path=retrieval_path,
        rag_dataset_path=rag_path,
    )
    components_by_name = {c.component: c for c in result.components}
    assert components_by_name["classify_chunk(allow_llm=True)"].status == svc.FAILED
    assert "synthetic classify_chunk bug" in components_by_name["classify_chunk(allow_llm=True)"].reason
    assert components_by_name["classify_chunk(allow_llm=False)"].status == svc.FAILED
    assert components_by_name["classify_question"].status == svc.FAILED
    # Other groups still ran and reported their own (clean) results.
    assert components_by_name["embedding_retrieval"].status == svc.NOT_EVALUABLE
    assert components_by_name["answer_generation_llm"].status == svc.NOT_EVALUABLE


def test_run_evaluation_uses_labeled_store_not_live_chroma(monkeypatch, tmp_path):
    labeled_store = object()
    live_calls: list[int] = []

    def _live():
        live_calls.append(1)
        raise AssertionError("live chroma must not open for labeled retrieval")

    monkeypatch.setattr(svc, "open_labeled_retrieval_store", lambda: labeled_store)
    monkeypatch.setattr(svc, "get_knowledge_base_store", _live)

    retrieval_path = _write_json(
        tmp_path,
        "retrieval.json",
        {
            "dataset_version": "v2-test",
            "cases": [
                {
                    "query_id": "q1",
                    "query": "fee",
                    "relevant_ids": ["c1"],
                    "labeling_status": "labeled",
                }
            ],
        },
    )
    classification_path = _write_json(
        tmp_path, "classification.json", {"dataset_version": "empty", "cases": []}
    )
    rag_path = _write_json(tmp_path, "rag.json", {"dataset_version": "empty", "cases": []})

    captured: dict[str, object] = {}

    def fake_eval(dataset, *, store, k=5, candidate_pool_size=20):
        captured["store"] = store
        captured["n"] = len(dataset.labeled_cases)
        info = svc.ComponentModelInfo(component="embedding_retrieval", model_name="mock")
        rerank_info = svc.ComponentModelInfo(component="reranker", model_name="mock")
        return (
            svc.ComponentEvaluationResult(
                component="embedding_retrieval",
                status=svc.EVALUATED,
                reason=None,
                model_info=info,
                case_count=1,
                skipped_unlabeled_count=0,
            ),
            svc.ComponentEvaluationResult(
                component="reranker",
                status=svc.EVALUATED,
                reason=None,
                model_info=rerank_info,
                case_count=1,
                skipped_unlabeled_count=0,
            ),
        )

    monkeypatch.setattr(svc, "evaluate_retrieval", fake_eval)

    result = svc.run_evaluation(
        classification_dataset_path=classification_path,
        retrieval_dataset_path=retrieval_path,
        rag_dataset_path=rag_path,
    )
    assert captured["store"] is labeled_store
    assert captured["n"] == 1
    assert live_calls == []
    assert result.dataset_versions["retrieval"] == "v2-test"
    by_name = {c.component: c for c in result.components}
    assert by_name["embedding_retrieval"].status == svc.EVALUATED
    assert by_name["classify_question"].status == svc.NOT_EVALUABLE
    assert by_name["answer_generation_llm"].status == svc.NOT_EVALUABLE
