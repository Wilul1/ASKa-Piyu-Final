# Stage 2 — QA & citation loaders and pure metric tests

Implemented 2026-11-09. Additive only. Targeted corrections after the independent audit bind corpus identity and extract membership. No evaluation run, no product integration.

## Scope

Stage 2 implements the loader, validation, and pure metric functions for the future live file `qa_citation_eval_dataset.json`. It does **not** create that live file. Contract examples remain `example_only` and are rejected if loaded as evaluation data.

## Corpus identity

Required live `corpus` fields:

| Field | Locked value |
|---|---|
| `path` | `backend/data/chroma_evaluation` (intended evaluation Chroma path) |
| `collection` | `aska_evaluation` |
| `expected_chunk_count` | `691` (integer; strings are not coerced) |
| `extract_artifact` | `backend/benchmarks/results/chroma_record_extraction_20261104T104214Z.json` |
| `identity_digest` | `fcb324dad73c41684e771defec0a36937ddde014df858c3f020aaf914774c85b` |
| `metadata_text_digest` | `7cec45b38d017d17f4f7b39abf3dc2d52a4f6f832b179ea2b70c37c6086262d7` |

Both digests are required. Missing, malformed, or incorrect values are rejected. The loader also compares them to `validation.*` on the extract file. Optional `hash` / `snapshot_id` / `manifest_hash` strings are rejected.

`QaCitationDataset.dataset_json_sha256` is the hash of the dataset JSON bytes. It is not the corpus identity.

### Provenance

- Source extraction artifact: the locked extract JSON (authoritative for Stage 2 membership).
- Source collection as recorded in that extract: `aska_knowledge_base` from `chroma.sqlite3` (machine-local path stored in `extract.source.path`).
- Intended evaluation store: `backend/data/chroma_evaluation` / `aska_evaluation` / 691 chunks.

**Limitation:** Stage 2 does not open Chroma. Matching chunk count and collection name does not prove `chroma_evaluation` bytes equal the extract. Corpus identity is the two extract digests.

## Citation identifiers

Parse `document_id::chunk_index` on the **final** `::` (`rsplit("::", 1)`), matching production. `faq:uuid::0` is valid. Missing `::`, empty sides, whitespace, and non-integer indexes are rejected.

## Membership validation

For labeled student-support cases, every supporting chunk ID must exist in the locked extract. Document ID and chunk index must match that record. If an excerpt is supplied, it must be a **verbatim contiguous substring** of the extract record `text` (`EXCERPT_MATCH_RULE`). This is textual membership, not semantic correctness of the reference answer.

Insufficient-evidence cases must have `reference_answer=null` and must not carry supporting IDs or evidence, including when unlabeled.

## Faculty scope

Faculty-as-audience markers are rejected (`faculty member`, `faculty manual`, `teaching load`, `faculty handbook`, `for faculty`, and similar). A student asking which **college or faculty** to contact is allowed.

## Metric formulas

Unchanged from the audited passing behavior.

Every metric returns `{numerator, denominator, value}`. If `denominator == 0`, `value` is `null`.

Claim status consistency for metric inputs:

- `supported` requires at least one supporting displayed ID.
- `unsupported` must not list supporting displayed IDs.
- `not_assessable` must not list supporting displayed IDs (that would collapse into supported). `not_assessable` stays in claim-level denominators.

## Execution / completion rate

| Status | Meaning |
|---|---|
| `ok` | Answer capture completed. Does not establish correctness. |
| `oos_or_refusal` | Refusal/out-of-scope handling completed. Completion, not a correct answer. |
| `error` | Capture failed. |
| `incomplete` | Capture did not complete or produced an incomplete result. |

Successful for completion rate: `ok`, `oos_or_refusal`. Failed statuses must not carry QA or citation scores. Failed rows stay in `case_count`.

**Retry policy:** one final execution record per `case_id` per run. Duplicates are rejected, not overwritten. Retry history is not supported at Stage 2; a later stage must add a distinct attempt identifier if attempts are retained.

## Tests

Deterministic unit tests covering loaders, membership against the real extract, metrics, and execution policy. Contract examples are asserted rejected, not scored.

## Compatibility

Existing `rag_metrics.py` / `datasets.py` / classification / retrieval modules were not modified. `rag_eval_dataset.json` was not populated. No chatbot capture, judge calls, DB models, APIs, Flutter, orchestration, historical edits, commits, or deploys.
