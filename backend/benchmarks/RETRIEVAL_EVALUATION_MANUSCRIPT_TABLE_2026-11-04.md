# ASKa-Piyu Retrieval Evaluation — Manuscript Results

**Evaluation date (UTC):** 2026-11-04T12:44:17Z  
**Dataset:** `backend/benchmarks/evaluation/retrieval_relevance_dataset.json`  
**Dataset version:** `2026-11-04-v2-human-reviewed-rag-benchmark-q1-q12`  
**Labeled queries:** 12 (0 unlabeled)  
**Corpus:** local evaluation index `backend/data/chroma_evaluation`, collection `aska_evaluation`, **691** chunks  
**Embedding model:** `sentence-transformers: intfloat/multilingual-e5-small`  
**Reranker:** rule-based query expansion + heuristic boosting (not a trained model)  
**Top-K:** 5  
**Candidate pool:** 20  

Detailed machine-readable output:

- This run: `backend/benchmarks/results/retrieval_benchmark_20261104T124417Z.json`
- Frozen baseline (same scores): `backend/benchmarks/results/retrieval_benchmark_20261104T121208Z.json`
- Baseline write-up: `backend/benchmarks/RETRIEVAL_BASELINE_2026-11-04.md`

This run **reproduced the frozen baseline exactly**. The baseline files were not modified.

## What was evaluated

The 12 human-reviewed questions in `retrieval_relevance_dataset.json`.  
Classification (`classification_eval_dataset.json`) and RAG answer quality (`rag_eval_dataset.json`) were **not** evaluated: both files are empty templates with no labeled cases.

A confusion matrix is **not applicable**. This task is ranked retrieval with graded relevance, not classification with class labels and predictions.

## Aggregate results

| Metric | Embedding only | With reranker | Δ (reranker − embedding) |
|---|---:|---:|---:|
| Hit@5 | 0.8333 | 0.9167 | +0.0834 |
| MRR | 0.6875 | 0.8125 | +0.1250 |
| Precision@5 | 0.2500 | 0.2333 | −0.0167 |
| Recall@5 | 0.8056 | 0.8056 | 0.0000 |
| nDCG@5 | 0.6871 | 0.7812 | +0.0941 |

Hit@5 is the fraction of the 12 queries with at least one relevant document in the top 5.  
MRR is mean reciprocal rank of the first relevant hit.  
Precision@5 / Recall@5 use binary relevance (`relevant_ids`).  
nDCG@5 uses the human `graded_relevance` scores (0–3).

## Per-query Hit@5

| ID | Question | Embedding Hit@5 | Reranker Hit@5 |
|---|---|---|---|
| Q1 | How much does it cost to get a copy of my Transcript of Records? | Yes | Yes |
| Q2 | How much is the fee for a second copy of my diploma? | Yes | Yes |
| Q3 | Which office handles student enrollment? | No | Yes |
| Q4 | How much does it cost to drop a subject? | Yes | Yes |
| Q5 | What is the fee for library circulation service if my book is overdue? | Yes | Yes |
| Q6 | How long does the LSPU entrance examination take, including orientation? | Yes | Yes |
| Q7 | What is the process for validating my student ID? | Yes | Yes |
| Q8 | What happens if I fail more than 75% of my units? | Yes | Yes |
| Q9 | How is faculty teaching load determined? | Yes | Yes |
| Q10 | What are the responsibilities of an LSPU faculty member? | No | No |
| Q11 | What is honorable dismissal for a student? | Yes | Yes |
| Q12 | Who is the current LSPU president? | Yes | Yes |

Queries without a relevant result in the top 5: **Q3** (embedding only) and **Q10** (both rankings).

## Interpretation for the manuscript

On this 12-question, 691-chunk local evaluation corpus, the existing rule-based reranker improved Hit@5, MRR, and nDCG@5 versus embedding-only ranking of the same candidate pool. Recall@5 was unchanged. Precision@5 decreased slightly. These figures are a **retrieval baseline**, not a claim of production-wide accuracy, RAG answer quality, citation correctness, or classification performance.

## Why `/admin/evaluation/run` was not used

1. A prior PowerShell POST timed out with **no Uvicorn access log**, so the request never reached the local API.
2. That endpoint requires `x-admin-key` and persists a full multi-component run to the **local application database**.
3. `run_evaluation()` calls `get_knowledge_base_store()`, which is the live application Chroma store, **not** `data/chroma_evaluation`. The 12 human labels were judged against the 691-chunk evaluation index. Using the live store would silently evaluate a different corpus.

The compatible, already-existing workflow is `backend/run_retrieval_benchmark_local.py`.
