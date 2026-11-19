# Phase 2E — Citation-evidence review index

Prepared 2026-11-05. **Read-only inspection. Stop and wait for human approval of citation labels.**

This directory does **not** assign `gold_citation_ids`, change `labeling_status` or `evaluation_ready`, or modify the pending dataset, Phase 2B evidence, Phase 2C drafts, Phase 2D decisions, Chroma, or application code.

Companion files: one review per case in this folder. Architecture details are in this index.

## Files inspected (read-only)

Application and evaluation:

- `backend/app/services/qa/question_answering.py` (`_raw_citation_id`, `_select_supporting_context`, `_display_sources_for_answer`, `_sources_from_chunks`, `_page_number`, `_display_title`)
- `backend/app/services/qa/citation_verification.py` (Citation V2 entailment, `CandidateEvidence.citation_id`, fail-closed empty list)
- `backend/app/services/qa/citation_verification_jobs.py`
- `backend/app/services/citation_pdf.py` (1-based PDF page index for viewer crop)
- `backend/app/services/chroma_store.py` (`RetrievedChunk`)
- `backend/app/models/schemas.py` (`QASourceSchema`, `QACitationSchema`)
- `backend/app/routes/qa.py` (citation poll resolves `citation_id.rsplit("::", 1)[0]` as document_id)
- `backend/app/config.py` (`citation_verification_mode` default `"lexical"`)
- `backend/app/services/evaluation/rag_metrics.py` (`citation_set_precision` / `citation_set_recall`)
- `backend/app/services/evaluation/evaluation_service.py` (`_chunk_identity`, gold compared to `outcome.verified_citation_ids`)
- `backend/app/services/evaluation/datasets.py`
- `flutter_app/lib/screens/chatbot_page.dart` (`citationLabel` uses API `page` / `page_number`)
- Tests: `test_citation_verification.py`, `test_document_citations.py`, `test_citation_pdf.py`, `test_evaluation_rag_metrics.py`, `test_qa_oos_citation_gating.py`
- `backend/benchmarks/citation_grounding_benchmark.json` (citation identity definition)
- Isolated extraction: `backend/benchmarks/results/chroma_record_extraction_20261104T104214Z.json`

Review records (unchanged):

- Phase 2B evidence packs under `human_review/aq_01_tor_fee/` … `aq_12_current_president/`
- `human_review/INDEX.md`, `HUMAN_REVIEW_DECISIONS.md`, `reference_answers.draft.json`
- Pending dataset (read only): `answer_quality_eval_dataset.pending_human_review.json`

## 1. Citation architecture (actual implementation)

### Identity layers (not interchangeable)

| Layer | What it is | Example |
| --- | --- | --- |
| Source document ID (Chroma) | UUID of the ingested PDF | `da4a1832-7242-4e94-8ba6-bc0b9f2294bf` |
| Postgres `source_documents.id` | May differ after `resolve_citation_document`; used for `/documents/{id}/source` URLs | **not queried this phase** |
| Chroma chunk ID | `metadata.chunk_id`, stored as `{document_id}::{chunk_index}` | `da4a1832-7242-4e94-8ba6-bc0b9f2294bf::1` |
| Student-visible `citation_id` | `metadata.chunk_id` if stamped, else `{resolved_document_id}::{chunk_index}` | Usually **the same string as Chroma chunk ID** |
| Student-visible `document_id` | Postgres-resolved id when a PDF row exists; else Chroma document_id | May **differ** from the left half of `citation_id` |
| Displayed page | `_page_number()` → `page_number` or `page_start` or `page`; charter cards may soft-extend `page_end` by +1 | Chroma metadata integer |
| PDF viewer page | `extract_citation_pages_pdf(page_start)` treats the integer as **1-based PDF index** | Same integer as displayed page |
| Printed page | Footer / header (“Page: 26 of 183”, “5”) | **Not stored. Not shown. Not used.** |

**A Chroma chunk ID is the student-visible citation ID in the common case** (when `metadata.chunk_id` is present). It is **not** a Postgres document ID, not a PDF page, and not a printed page. Evaluation `gold_citation_ids` must live in this `citation_id` / `chunk_id` space (`evaluation_service._chunk_identity` uses the same formula). Bare `document_id` is invalid gold.

### How citations are selected

Default `ASKA_CITATION_VERIFICATION_MODE=lexical`:

1. Retrieve candidates (Chroma + rerank). Generation sees selected context.
2. V1 `_select_supporting_context` scores **already-retrieved** chunks by keyword/number overlap with the **answer text**. It never fetches a new chunk.
3. `_sources_from_chunks` formats surviving chunks into `sources` / `citations`.

Citation V2 (`citation_verification.py`), if mode is `llm`:

- Splits the answer into claims; asks an LLM whether each **allowlisted** candidate **entails** the claim.
- Displayed IDs = `verified_citation_ids` only. Failure → empty list (fail-closed). Never invents IDs.

Evaluation Citation Accuracy (`citation_set_precision` / `recall`) compares `outcome.verified_citation_ids` to labeled `gold_citation_ids`. It is **not** computed unless gold IDs exist and the verifier succeeds. This phase does **not** assign those gold IDs.

### What the student sees

Flutter `citationLabel`: document badge (Charter / Handbook / Faculty Manual from filename/label) + section title + `page N` or `pages N–M`. That N is Chroma metadata, not the printed footer. Opening a source uses `source_page_url` against the **PDF page index**.

### Page-number types (keep separate)

1. **PDF page index** — 1-based page in the PDF file (viewer / PyMuPDF).
2. **Printed page** — what the document prints (Charter footer 5; Handbook “26 of 183”; Faculty “vii”).
3. **Chroma page metadata** — `page` / `page_number` / `page_start` / `page_end` on the chunk.

The implementation never stores printed pages. It never silently maps printed → PDF index. This review does not correct metadata.

## 2. Case files

| Case | Review file | Recommended citation decision |
| --- | --- | --- |
| aq_01 TOR fee | `aq_01_tor_fee.md` | **Revise** |
| aq_04 dropping fee | `aq_04_dropping_fee.md` | **Revise** (both sides independently citable; OCR/page issues) |
| aq_08 retention | `aq_08_retention_policy.md` | **Revise** (split claims across two chunks) |
| aq_10 faculty commitments | `aq_10_faculty_responsibilities.md` | **Revise** (ID resolvable; title/page wrong) |
| aq_12 current president | `aq_12_current_president.md` | **Insufficient** — do not gold-cite a current-president answer |

## 3. Manual citation-label decisions still required

All five cases. None has `gold_citation_ids`. None is evaluation-ready.

## 4. Implementation limitations (discovered, not fixed)

1. Printed page numbers are invisible to students and to gold page fields.
2. Charter displayed page is Chroma page (often service-start), not the fee-table PDF page.
3. V1 selection is lexical overlap, not entailment. A mashed fee block can “support” TOR, certifications, and diploma at once.
4. V2 can only verify chunks already retrieved; it cannot substitute the correct PDF page for wrong metadata.
5. Chunk title/page can disagree with body (aq_10). Display uses title/page metadata, not a body-based correction.
6. Postgres document_id remap can make `citation_id` prefix ≠ `document_id` used in PDF URLs. Not queried this phase.
7. Retrieval was not executed. Chunk IDs below are from the isolated 691-chunk extraction, not from a live `answer_qa_question()` run.
