# Answer-quality approved-subset evaluation

Run ID: `aq_subset_20261104T163426Z`  
Created: 2026-11-04T16:34:26.345650+00:00

## What this run is

This is a real `answer_qa_question()` run against the isolated 691-chunk `chroma_evaluation` index for the only two cases that currently have both a human-approved reference answer and approved gold citations.

It is **not** an LLM-generated answer-quality score. Local OpenRouter returned **401 Unauthorized**, so both cases used the student-facing **generation-error fallback**. Retrieval, selected context, and lexical citations are real. Faithfulness was not scored (verifier also 401). `null` means unavailable, not zero.

Pending dataset SHA-256 unchanged: `D7CDD2EC2CCE20A176FBA7B07B70C6206E7AABF4F36FD8D3C5BC8BD1677E2905`. `evaluation_ready` remains false. `rag_eval_dataset.json` was not used or modified.

## Pipeline

- Function: `answer_qa_question()` with `user_role=student`
- Corpus: `backend/data/chroma_evaluation` / `aska_evaluation` (691 chunks)
- Displayed citations: lexical V1 (`citation_verification_mode=lexical`)
- Generation model configured: `openrouter/free` via OpenRouter
- Generation result: invoked, failed (HTTP 401), fallback used
- RAGAS: not installed, not used

## Per-case results

### aq_04_dropping_fee_multi_document

**Question:** How much does it cost to drop a subject?

**Generation:** invoked, failed, fallback used (`fallback_reason=generation_error`)

**Chatbot answer (fallback):**

The listed fee for Dropping of Subjects is P30.00 (Laguna State Polytechnic University CC 2026 1st Edition).

| Metric | Value | Meaning |
| --- | --- | --- |
| answer_correctness (required-fact coverage vs approved gold) | **0.0** | Fallback states Charter P30.00 but omits `/unit`, Handbook P20/unit, new/transferee limit, BOR 1046, and the conflict/confirm instruction |
| answer_relevancy (question-token overlap) | 0.6667 | Weak proxy only; not RAGAS |
| gold recall in retrieval | 0.5 | Retrieved Charter `::97`; missed Handbook `::82` |
| gold recall in generation context | 0.5 | Same: `::97` present, `::82` absent |
| student-visible citation precision | 0.25 | 1 of 4 displayed IDs is gold (`::97`) |
| student-visible citation recall | 0.5 | Displayed `::97`; did not display `::82` |
| LLM-verifier faithfulness | **null** | Unavailable (401), not zero |

Displayed citation IDs:

- `da4a1832-7242-4e94-8ba6-bc0b9f2294bf::97` (gold hit)
- `cec01713-c1ba-4061-9404-ffaa1d8e70dd::118`
- `da4a1832-7242-4e94-8ba6-bc0b9f2294bf::93`
- `da4a1832-7242-4e94-8ba6-bc0b9f2294bf::92`

Gold citation IDs:

- `da4a1832-7242-4e94-8ba6-bc0b9f2294bf::97`
- `cec01713-c1ba-4061-9404-ffaa1d8e70dd::82`

### aq_08_fail_more_than_75_percent

**Question:** What happens if I fail more than 75% of my units?

**Generation:** invoked, failed, fallback used (`fallback_reason=generation_error`)

**Chatbot answer (fallback):**

At the end of the semester, A student who fails 25% to 49% of the total academic units he registered shall be warned by the Dean and advised to improve his/her performance. At the end of the semester, A student fails 50% to 74% of the total academic units in which he registered shall be placed on probation for the succeeding semester, and the Dean con- cerned shall reduce his/her load accordingly. A student's…

| Metric | Value | Meaning |
| --- | --- | --- |
| answer_correctness (required-fact coverage vs approved gold) | **0.0** | Fallback quotes Warning/Probation (`::66`), not 4.3 “more than 75%” or the 75% table |
| answer_relevancy (question-token overlap) | 1.0 | Tokens `fail`/`units` appear, but the policy band is wrong; not RAGAS |
| gold recall in retrieval | **1.0** | Both gold IDs `::67` and `::69` were retrieved |
| gold recall in generation context | 0.5 | `::69` reached generation context; `::67` did not |
| student-visible citation precision | **0.0** | Displayed only `::66` (explicitly excluded from gold) |
| student-visible citation recall | **0.0** | Neither `::67` nor `::69` was displayed |
| LLM-verifier faithfulness | **null** | Unavailable (401), not zero |

Displayed citation IDs:

- `cec01713-c1ba-4061-9404-ffaa1d8e70dd::66` (excluded from gold on purpose)

Gold citation IDs:

- `cec01713-c1ba-4061-9404-ffaa1d8e70dd::67`
- `cec01713-c1ba-4061-9404-ffaa1d8e70dd::69`

## Aggregate (2 fallback cases)

These averages describe **fallback answers**, not Groq/OpenRouter generations.

| Metric | Aggregate | Contributing cases |
| --- | --- | --- |
| answer_correctness | 0.0 | 2 |
| answer_relevancy | 0.8334 | 2 |
| citation_set_precision (student-visible vs gold) | 0.125 | 2 |
| citation_set_recall (student-visible vs gold) | 0.25 | 2 |
| faithfulness | null | 0 |
| claim_support_rate | null | 0 |
| context_precision / context_recall | null | 0 |

## Excluded cases (not treated as labeled)

- `aq_01_tor_fee`: approved reference answer; citation usability unresolved; no gold citations
- `aq_02_diploma_second_copy_fee`: no human-approved reference answer or gold citations
- `aq_03_enrollment_office`: no human-approved reference answer or gold citations
- `aq_05_library_overdue_fee`: insufficient_evidence; null reference
- `aq_06_entrance_exam_duration`: no human-approved reference answer or gold citations
- `aq_07_id_validation_process`: no human-approved reference answer or gold citations
- `aq_09_faculty_teaching_load`: no human-approved reference answer or gold citations
- `aq_10_faculty_responsibilities`: approved reference answer; citation gold held (wrong title/page/viewer)
- `aq_11_honorable_dismissal`: no human-approved reference answer or gold citations
- `aq_12_university_president`: insufficient_evidence; null reference; no gold citations
- `aq_13_out_of_scope_weather_mars`: out_of_scope
- `aq_14_insufficient_wifi_password`: insufficient_evidence; null reference

## Limitations

- Local LLM credential for OpenRouter returned 401. No generated answers were obtained. Do not interpret 0.0 correctness as a scored Groq answer.
- Only 2 of 14 pending cases have both an approved reference answer and approved gold citations.
- answer_correctness is required-fact coverage against the approved reference, not RAGAS.
- answer_relevancy is distinctive question-token overlap, not RAGAS, and can be high on the wrong policy text.
- Student-visible citations were scored from lexical V1. Local `.env` `async_llm` was not used, because that mode returns zero citations until a background job finishes.
- LLM-verifier faithfulness is unavailable because the same 401 blocked the verifier.
- Postgres citation resolution may still run for PDF viewer URLs against the local database. Retrieval used only `chroma_evaluation`.
- Production Chroma, Heroku, retrieval dataset, classification dataset, and the pending dataset were not modified.

## Files in this run

- `run_metadata.json`
- `raw_evidence.json`
- `per_case_metrics.json`
- `aggregate_metrics.json`
- `REPORT.md`
