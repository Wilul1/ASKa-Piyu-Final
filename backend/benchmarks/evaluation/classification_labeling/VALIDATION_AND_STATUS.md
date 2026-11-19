# Classification evaluation dataset — candidate collection status

**Date:** 2026-11-04
**Status:** CANDIDATES COLLECTED — **not labeled**. Phase 6 evaluation was **not** run.

Human approval is still required. No case in this folder is ground truth.

## Phase 1 findings (actual implementation)

- Taxonomy file: `backend/app/knowledge_base_categories.json` (10 categories, 47 subcategories).
- `classify_question` and `classify_chunk` both return `ClassificationResult.subcategory` (not the parent category).
- Evaluation (`evaluate_classify_question` / `evaluate_classify_chunk`) compares `true_label` to `.subcategory`.
- One JSON file (`classification_eval_dataset.json`) holds both components; cases are split by `"component": "classify_question"` or `"classify_chunk"`.
- `classify_chunk(allow_llm=True)` and `classify_chunk(allow_llm=False)` share the **same** labeled chunk cases and are scored independently.
- Labeled cases require: `case_id`, `text`, `true_label`, `component`, `labeling_status=labeled`.
- Unlabeled cases are counted and excluded; they never become false negatives.
- Dashboard Accuracy / macro F1 / confusion heatmap appear only after labeled classification cases exist.
- Retrieval 12-question labels were not modified.

## Phase 2 collection

### Questions (49 unique after de-duplication)

Sources:

- `backend/benchmarks/citation_grounding_benchmark.json`
- `backend/benchmarks/citation_grounding_fresh_gold_validation_cases.json`
- `backend/benchmarks/citation_grounding_pilot_cases.json`
- `backend/benchmarks/evaluation/retrieval_relevance_dataset.json`

The 12 retrieval queries are included as classification *candidates* only. Their `relevant_ids` / graded relevance are not classification labels.

Some captured questions are out-of-scope probes (e.g. recipes, other universities, national politics). Reviewers should use `MARK_FOR_REVIEW` rather than force a campus subcategory.

### Chunks (47 unique)

Source index: `chroma_record_extraction_20261104T104214Z.json` (691 records, local extraction artifact).

- All chunks cited as retrieval `relevant_ids` for the 12-q set (that exist in the extract, length ≥ 120, not placeholder).
- Plus a stratified sample of up to 3 chunks per **index** metadata category (organizing hint only).
- Placeholder FAQ “Brand New Article” rows were excluded.
- Pink columns on the chunk sheet (`index_metadata_*_HINT_ONLY`) are ingestion stamps. **Do not copy them into true_label.**

Document IDs represented: 3.

## Phase 3–4 — not complete

- `true_label` is null on every candidate.
- `classification_eval_dataset.json` remains the empty v1 template (`cases: []`). A copy is in this folder.
- Do not promote rows into the eval JSON until Review status is `approved` and `true_label` is a Taxonomy subcategory (never `MARK_FOR_REVIEW`).

## Phase 5 validation of *candidates* (not of a labeled set)

| Check | Result |
|---|---|
| Every candidate has provenance | Yes |
| Every candidate `true_label` empty | Yes |
| No `labeling_status=labeled` written | Yes |
| Question vs chunk component assignment | Yes (`classify_question` / `classify_chunk`) |
| Duplicate question text collapsed | Yes (extras listed in `additional_sources`) |
| Duplicate chunk_id collapsed | Yes |
| Each class has enough labeled examples | **N/A — zero labeled cases** |
| Dataset represents all university questions | **Do not claim this.** Candidate pool is small and source-biased (benchmarks + one 691-chunk extract). |

## Phase 6

Not run. Reporting Accuracy / F1 / confusion matrices now would be fabricated.

After humans finish:

1. Copy only approved rows into `classification_eval_dataset.json` with `labeling_status: "labeled"`.
2. Keep a version bump (do not overwrite the empty template without this folder’s backup).
3. Click **Run Evaluation** on the local admin dashboard.
4. Confirm classify_question plus both classify_chunk variants show `evaluated`.
