# Classification labels — annotation methodology and limitations

**These labels are not human-reviewed and not human-validated.**

| Field | Value |
|---|---|
| `annotation_method` | `independent_ai_annotation` |
| `reviewer_1_type` | `AI` (this session, Grok) |
| `reviewer_2_type` | `AI` (separate agent, Grok 4.7) |
| Approval | Auto-accept only if both assign the same taxonomy subcategory, both `evidence_sufficient=true`, and neither used `MARK_FOR_REVIEW` |

## Pipeline

1. 96 real candidates (49 questions, 47 chunks) from existing project files / Chroma extract.
2. Two independent AI passes wrote `reviewer1_annotations.json` and `reviewer2_annotations.json`.
3. `promote_agreed_labels.py` compared them. Disagreements, OOS, and insufficient-evidence rows were **not** promoted.
4. Promoted rows only: `classification_eval_dataset.json` version `2026-11-04-v2-independent-ai-annotation-dual-agreement`.

## Counts (this run)

- Candidates: 96
- Dual-AI auto-accepted: 65 (37 `classify_question`, 28 `classify_chunk`)
- Flagged (not in eval JSON): 31 (25 mark-for-review / OOS / insufficient; 6 disagreements)

Disagreements held out for later manual adjudication:

- Graduate goals chunk: Graduate Programs vs MARK_FOR_REVIEW
- Graduate course requirements: Graduate Policies vs Graduate Programs
- Assist foreign students: Foreign Students vs MARK_FOR_REVIEW
- IB diploma admission: Admission Requirements vs Foreign Students
- Safeguarding/health protocols: Health Services vs MARK_FOR_REVIEW
- TOR/certifications charter page: Transcript of Records vs MARK_FOR_REVIEW

## Limitations (must be stated with any metric)

- Dual AI agreement is **not** human gold. Both annotators are language models; residual correlated error is expected.
- Reviewer 2 used a related Grok model after Reviewer 1 — independence is procedural (separate pass, no R1 file), not two humans.
- 31/96 cases have no approved label; coverage is incomplete and class-imbalanced.
- Index metadata was not used as `true_label`. Retrieval 12-q relevance IDs were not used as classification labels.
- Do not describe dashboard Accuracy / F1 / confusion matrices from this set as human-validated.

## Local evaluation run (not human gold)

Run `6b1ec340-d32a-4bbc-8963-9f7ec856dc14` (completed). Refresh Model Evaluation.

| Component | Cases | Accuracy | Macro F1 | Confusion matrix |
|---|---|---|---|---|
| classify_question | 37 | 0.7027 | 0.5064 | yes |
| classify_chunk allow_llm=True | 28 | 0.6429 | 0.5345 | yes |
| classify_chunk allow_llm=False | 28 | 0.6429 | 0.5345 | yes |

LLM-on and LLM-off chunk scores match because the local Groq/OpenRouter call returned **401 Unauthorized**, so `classify_chunk` fell back to rules+similarity in both modes. That is an environment limitation, not a finding that the LLM adds nothing.

Retrieval 12-q metrics are unchanged in substance (Hit@5 reranked 0.9167). RAG remains not evaluable.

## Files

- `reviewer1_annotations.json`, `reviewer2_annotations.json`
- `agreement_adjudication.json`
- `backend/benchmarks/evaluation/classification_eval_dataset.json` (promoted agreements only)
- Empty-template backup remains in this folder.
