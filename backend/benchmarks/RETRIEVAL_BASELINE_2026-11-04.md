# ASKa-Piyu — First Local Retrieval Benchmark Baseline

**Date:** November 4, 2026  
**Status:** Completed  
**Evaluation corpus:** 691 records  
**Human-reviewed queries:** 12  
**Unlabeled queries:** 0  
**Top K:** 5

## Purpose

Measure the current retrieval pipeline using human-reviewed relevance judgments. Compare embedding-only retrieval against the existing rule-based reranker.

## Results

| Metric | Embedding only | With reranker |
|---|---:|---:|
| Hit@5 | 0.8333 | 0.9167 |
| MRR | 0.6875 | 0.8125 |
| Precision@5 | 0.2500 | 0.2333 |
| Recall@5 | 0.8056 | 0.8056 |
| nDCG@5 | 0.6871 | 0.7812 |

## Findings

- Reranked Hit@5 improved by 8.34 percentage points.
- MRR improved by 0.1250.
- nDCG@5 improved by 0.0941.
- Precision@5 decreased slightly.
- Recall@5 remained unchanged.
- Two queries did not retrieve a relevant result in the top five: Q3 (enrollment office) and Q10 (faculty responsibilities).

## Interpretation

The current rule-based reranker improves the ordering of relevant results for this benchmark. It does not increase overall recall at five.

The reranker is a heuristic component, not a separately trained embedding model.

## Reproducibility

Detailed result file:

`results/retrieval_benchmark_20261104T121208Z.json`

Dataset:

`evaluation/retrieval_relevance_dataset.json`

Evaluation index:

`data/chroma_evaluation`

The evaluation used a separate local index. The original local Chroma database and production Cloud collection were not modified.

## Limitations

- This is a 12-query benchmark, not a comprehensive evaluation of all university-service questions.
- Results apply to the evaluated local corpus and its reviewed relevance labels.
- RAG answer quality, citation correctness, classification performance, and latency were not measured by this run.
- These scores are a baseline, not a claim of production-wide accuracy.

## Next step

Retain these results as the comparison baseline. Any future retrieval changes should be evaluated against the same dataset and corpus before being considered an improvement.
