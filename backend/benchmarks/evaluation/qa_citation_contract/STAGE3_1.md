# Stage 3.1 — QA answer capture

Implemented 2026-11-09. Additive only. Preflight established that `chroma_evaluation` / `aska_evaluation` corresponds to the locked extract. Capture code is ready. The live dataset file does not exist, so the benchmark was not executed.

No judges, citation scoring, metrics beyond the approved execution statuses, DB/migrations, API/UI changes, classification/retrieval changes, historical result edits, chatbot behavior changes, commits, pushes, or deploys.

## 1. Corpus identity verification

**Result: correspondence established. Capture is allowed. The live benchmark was still not run, because `qa_citation_eval_dataset.json` does not exist.**

Evaluation store intended for `LabeledRetrievalStore`:

| Field | Value |
|---|---|
| Path | `backend/data/chroma_evaluation` |
| Collection | `aska_evaluation` |
| sqlite | `backend/data/chroma_evaluation/chroma.sqlite3` |
| sqlite sha256 | `859f54175d7134a082160b19ed4aef8786418f48d408f8bb6b908ef0632b7c9e` |
| Recovered records | 691 |
| Exclusions | 0 |

Locked extract (`backend/benchmarks/results/chroma_record_extraction_20261104T104214Z.json`):

| Field | Value |
|---|---|
| Source path as recorded | `C:\Users\Admin\Desktop\ASKa-piyu\backend\data\chroma\chroma.sqlite3` |
| Source collection as recorded | `aska_knowledge_base` |
| Source sqlite sha256 | `d5cbd6d11e98fac5c0de650d98034ff9315b58c5cf25051c91a16df4d4e23ddd` |
| `identity_digest` | `fcb324dad73c41684e771defec0a36937ddde014df858c3f020aaf914774c85b` |
| `metadata_text_digest` | `7cec45b38d017d17f4f7b39abf3dc2d52a4f6f832b179ea2b70c37c6086262d7` |

What was verified (count 691 was required and **not** treated as sufficient):

- Re-extracted `aska_evaluation` read-only via `open_source_readonly` + `extract_records` + `compute_identity_digest` / `compute_records_digest`.
- Both digests match the Stage 2 lock and the extract file `validation.*` fields.
- Embedding/chunk ID sets are equal (691/691).
- Verbatim text matches for every shared ID (691/691, 0 mismatches).
- Identity metadata matches for every shared ID: `document_id`, `chunk_id`, `chunk_index` (0 mismatches).

Persisted report: `corpus_identity_verification.json`.

### Limitations

- Evaluation sqlite **file bytes** differ from the extract source sqlite. Collection names also differ (`aska_evaluation` vs `aska_knowledge_base`). That is expected: the extract was taken from production `aska_knowledge_base`. Correspondence is the recovered records and the two locked digests, not sqlite-file identity.
- HNSW / vector segment files were not hashed. Identity uses the same sqlite metadata+text extraction as the locked artifact.

## 2. Files created or modified

Created:

- `backend/app/services/evaluation/qa_citation_corpus.py`
- `backend/app/services/evaluation/qa_citation_capture.py`
- `backend/tests/test_qa_citation_capture.py`
- `backend/benchmarks/evaluation/qa_citation_contract/run_qa_citation_capture.py`
- `backend/benchmarks/evaluation/qa_citation_contract/corpus_identity_verification.json`
- `backend/benchmarks/evaluation/qa_citation_contract/STAGE3_1.md`

Modified:

- `backend/app/services/evaluation/qa_citation_dataset.py` — additive `QaCitationDataset.cases` tuple so capture iterates original order (labeled and unlabeled together). Loader rules otherwise unchanged.

## 3. Answer-generation and retrieval functions used

- **Answer path:** `app.services.qa.question_answering.answer_qa_question`
- **Retrieval store:** `LabeledRetrievalStore` (`data/chroma_evaluation`, collection `aska_evaluation`)
- **Store adapter (capture-only):** `EvaluationStudentStore` — adds production `select_role_visible_hits` audience filtering and `list_chunks()`, because `answer_qa_question` calls `get_knowledge_base_store()` with no store argument
- **Injection:** `unittest.mock.patch` of `get_knowledge_base_store` for the duration of each case. Production chatbot code was not modified.
- **Not used as the capture entry point:** `generate_groq_answer()`
- **Role:** `user_role="student"`, `history=[]`

## 4. Whether actual benchmark cases were executed

**No.** `backend/benchmarks/evaluation/qa_citation_eval_dataset.json` does not exist. Capture refuses to invent cases. Contract examples remain `example_only` and are rejected.

Path tests called real `answer_qa_question()` against an in-memory `FakeStore` with `generate_groq_answer` mocked. Those are not live benchmark cases and did not open evaluation Chroma for answering.

## 5. Successful / refused / failed / incomplete counts

Live benchmark:

| Status | Count |
|---|---|
| `ok` | 0 |
| `oos_or_refusal` | 0 |
| `error` | 0 |
| `incomplete` | 0 |
| **total** | **0** |

A successful capture still would not mean the answer is correct.

## 6. Example captured record (fixture; sensitive fields removed)

Not a live evaluation result. Produced by the mocked capture tests:

```json
{
  "run_id": "run_prov",
  "case_id": "qac_test_001_tor_fee",
  "execution_status": "ok",
  "captured_at": "2026-11-09T05:00:00+00:00",
  "pipeline": "answer_qa_question",
  "user_role": "student",
  "dataset_version": "2026-11-09-stage3-1-test",
  "corpus": {
    "path": "backend/data/chroma_evaluation",
    "collection": "aska_evaluation",
    "chunk_count": 691,
    "extract_artifact": "backend/benchmarks/results/chroma_record_extraction_20261104T104214Z.json",
    "identity_digest": "fcb324dad73c41684e771defec0a36937ddde014df858c3f020aaf914774c85b",
    "metadata_text_digest": "7cec45b38d017d17f4f7b39abf3dc2d52a4f6f832b179ea2b70c37c6086262d7"
  },
  "model": {
    "answer_generation_model": "test-model",
    "config_snapshot": { "not_generate_groq_answer": true }
  },
  "generated_answer": "A Transcript of Records costs P75.00 per page for undergraduate students.",
  "retrieved_chunk_ids": ["da4a1832-7242-4e94-8ba6-bc0b9f2294bf::1"],
  "displayed_citation_ids": ["da4a1832-7242-4e94-8ba6-bc0b9f2294bf::1"],
  "error_type": null
}
```

`ok` here means capture completed, not that the answer is correct.

## 7. Tests

```
backend/venv/Scripts/python.exe -m pytest tests/test_qa_citation_capture.py tests/test_qa_citation_dataset.py tests/test_qa_citation_metrics.py -q
85 passed
```

- Stage 2 regression: 67 passed (dataset + metrics).
- Stage 3.1: 18 passed.

Integration (real eval sqlite / locked extract, no LLM):

- `test_eval_chroma_corresponds_to_locked_extract_integration`

Actual `answer_qa_question` path (FakeStore, mocked `generate_groq_answer`):

- `test_actual_answer_qa_question_path_captures_retrieval_and_citations`
- `test_actual_path_student_oos_refusal_is_captured`

Remaining tests are mocked unit tests: loader, student role, statuses, error retention, duplicates, overwrite refusal, provenance, secret stripping, faculty-chunk filtering.

## 8. Known limitations

- No live `qa_citation_eval_dataset.json`, so no live answers were captured.
- `answer_qa_question` has no store parameter; capture patches `get_knowledge_base_store`. That is evaluation-only and does not change production.
- `LabeledRetrievalStore.search` does not apply audience filtering. `EvaluationStudentStore` adds `select_role_visible_hits` so student execution matches production `KnowledgeBaseStore.search`.
- Displayed citation IDs are taken from `QAResult.sources`. The real `answer_qa_question` path can complete with empty `sources` even when generation received context; that empty list is recorded, not filled in from retrieved IDs. Generation context IDs are stored separately as `generation_context_chunk_ids`.
- Vector/HNSW files are not part of corpus identity.
- Capture does not wrap `answer_qa_question` in a wall-clock timeout (Windows has no SIGALRM). A hung call would not produce a row until the process is stopped; a raised exception becomes `error`.
- `QaCitationDataset.cases` was added so unlabeled cases are not dropped by iterating only `labeled_cases`.

## 9. Scope confirmation

Did **not** occur in this checkpoint:

- AI judges
- Citation claim extraction or citation judging
- New evaluation metrics
- Database tables or migrations
- API routes
- Flutter dashboard changes
- Classification or retrieval evaluation changes
- Historical evaluation result edits
- Chatbot behavior / production data changes
- Commits, pushes, or deploys

**Stop.** Wait for explicit approval before Stage 3.2 (AI judging).
