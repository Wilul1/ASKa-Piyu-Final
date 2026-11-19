# ASKa-Piyu Answer-Quality Evaluation Overview

**Document type:** Thesis overview of the 14-question answer-quality benchmark  
**Date:** 4 November 2026 (UTC)  
**Dataset:** `answer_quality_eval_dataset.pending_human_review.json`  
**Dataset version:** `2026-11-04-v1-answer-quality-pending-human-review`  
**SHA-256:** `D7CDD2EC2CCE20A176FBA7B07B70C6206E7AABF4F36FD8D3C5BC8BD1677E2905`

This document is an overview. It does **not** mark the pending dataset evaluation-ready, and it does **not** treat simulated entries as live chatbot tests.

---

## 1. Executive summary

ASKa-Piyu’s answer-quality benchmark contains **14 prepared questions** covering direct facts, multi-part policies, multi-document conflicts, insufficient evidence, and out-of-scope probes.

**Live production tests completed:** 2 of 14.

| Live case | Topic | Answer correctness | Citations |
| --- | --- | --- | --- |
| aq_04 | Dropping of Subjects fee | **PASS** | Pending |
| aq_08 | Failing more than 75% of units | **FAIL** | Pending |

**Progress (accurate counts only):**

- 14 benchmark questions prepared
- 2 actual live chatbot tests
- 1 satisfactory actual answer
- 1 unsatisfactory actual answer
- 12 not live-tested

No overall 14-question accuracy is reported. Simulated and unevaluated cases are excluded from that calculation.

---

## 2. Evaluation design

Intended scoring target: student-facing `answer_qa_question()` against the isolated 691-chunk evaluation corpus. Production Chroma was not used as the local evaluation index. The empty template `rag_eval_dataset.json` was not filled.

Cases remain `labeling_status: unlabeled` and `evaluation_ready: false`.

**Metric rules used in this overview**

- Answer correctness for the two live cases is a human pass/fail judgment.
- Citation precision/recall are scored only when live citation IDs can be mapped to approved gold IDs. They are **pending** for both live cases.
- Unavailable metrics are recorded as **null**, not zero.
- Simulated entries describe available reference material only. They do not invent chatbot answers, citations, or measured scores.

---

## 3. Actual versus simulated status

| ID | Question | Type | Overview status | Answer correctness | Citations |
| --- | --- | --- | --- | --- | --- |
| aq_01 | How much does it cost to get a copy of my Transcript of Records? | Direct factual | **SIMULATED — NOT LIVE-TESTED** | — | Unresolved |
| aq_02 | How much is the fee for a second copy of my diploma? | Direct factual | **SIMULATED — NOT LIVE-TESTED** | — | Not assigned |
| aq_03 | Which office handles student enrollment? | Direct factual | **SIMULATED — NOT LIVE-TESTED** | — | Not assigned |
| aq_04 | How much does it cost to drop a subject? | Multi-document | **ACTUAL LIVE TEST** | **PASS** | **Pending** |
| aq_05 | What is the fee for library circulation service if my book is overdue? | Insufficient evidence | **NOT EVALUATED** | — | — |
| aq_06 | How long does the LSPU entrance examination take, including orientation? | Multi-part | **SIMULATED — NOT LIVE-TESTED** | — | Not assigned |
| aq_07 | What is the process for validating my student ID? | Direct factual | **SIMULATED — NOT LIVE-TESTED** | — | Not assigned |
| aq_08 | What happens if I fail more than 75% of my units? | Multi-part | **ACTUAL LIVE TEST** | **FAIL** | **Pending** |
| aq_09 | How is faculty teaching load determined? | Multi-part | **SIMULATED — NOT LIVE-TESTED** | — | Not assigned |
| aq_10 | What are the responsibilities of an LSPU faculty member? | Direct factual | **SIMULATED — NOT LIVE-TESTED** | — | Held |
| aq_11 | What is honorable dismissal for a student? | Multi-part | **SIMULATED — NOT LIVE-TESTED** | — | Not assigned |
| aq_12 | Who is the current LSPU president? | Multi-document | **NOT EVALUATED** | — | None |
| aq_13 | What is the weather on Mars tomorrow? | Out of scope | **NOT EVALUATED** | — | — |
| aq_14 | What is the LSPU student Wi-Fi password? | Insufficient evidence | **NOT EVALUATED** | — | — |

---

## 4. Actual live chatbot tests (2)

These two results are the only live production judgments in this overview. They are not local fallback answers.

### aq_04 — Dropping of Subjects fee — ACTUAL LIVE TEST — PASS

**Question:** How much does it cost to drop a subject?

**Human-captured live result**

- The chatbot correctly stated the Dropping of Subjects fee as **P30.00**.
- It also provided the procedure and estimated processing time.
- **Answer correctness: PASS (satisfactory).**
- **Citation verification: pending** (citation details were not supplied).

Full verbatim wording was not pasted into the Cursor record. The judgment above is preserved exactly as supplied and is not reconstructed into a fabricated transcript.

**Approved reference (not a live chatbot answer):** Official sources list two dropping fees and do not establish which amount is currently in force. The Citizen’s Charter 2026 lists ₱30.00 per unit for new and transferee students. The Student Handbook 2021 requires ₱20.00 per unit, citing LSPU BOR Resolution 1046, s.2012. Confirm with the Registrar before paying.

**Approved gold citation IDs (not verified against the live display):**

- `da4a1832-7242-4e94-8ba6-bc0b9f2294bf::97`
- `cec01713-c1ba-4061-9404-ffaa1d8e70dd::82`

### aq_08 — Failing more than 75% of units — ACTUAL LIVE TEST — FAIL

**Question:** What happens if I fail more than 75% of my units?

**Human-captured live result**

- The chatbot returned **fragmented table content**.
- It did **not** clearly explain what happens when a student fails more than 75% of their units.
- **Answer correctness: FAIL.**
- No policy consequence was invented.
- **Citation verification: pending.**

**Approved reference (not a live chatbot answer):** Handbook Section 4.3 uses “more than 75%” and dismissal from the College, with an incomplete-grade exclusion and a nine-unit exemption. The scholastic-delinquency table uses “75% or more” and lists 100% as permanent disqualification from the University. The exact-75% case is unresolved; confirm with the Registrar.

**Approved gold citation IDs (not verified against the live display):**

- `cec01713-c1ba-4061-9404-ffaa1d8e70dd::67`
- `cec01713-c1ba-4061-9404-ffaa1d8e70dd::69`

Gold excludes `::66` (Warning/Probation only).

---

## 5. Simulated entries — not live-tested (8)

Each entry below is **SIMULATED — NOT LIVE-TESTED**. It records the prepared question and available reference material only. No chatbot response, citation list, or measured score is invented.

### aq_01 — Transcript of Records fee — SIMULATED — NOT LIVE-TESTED

**Question:** How much does it cost to get a copy of my Transcript of Records?

**Available reference (Phase 2D approved):** According to the Citizen’s Charter 2026, 1st Edition, a Transcript of Records costs ₱75.00 per page for undergraduate students and ₱150.00 per page for graduate students.

**Citation gold:** Unresolved. Candidate `da4a1832-7242-4e94-8ba6-bc0b9f2294bf::1` mixes fee categories and has an incomplete displayed page/viewer range.

**Live chatbot answer:** not collected. **Correctness / citations:** not scored.

### aq_02 — Second copy of diploma — SIMULATED — NOT LIVE-TESTED

**Question:** How much is the fee for a second copy of my diploma?

**Available draft reference (pending PDF confirmation):** The Charter Registrar card states: Second copy of diploma: P100.00.

**Citation gold:** not assigned. **Live answer:** not collected.

### aq_03 — Enrollment office — SIMULATED — NOT LIVE-TESTED

**Question:** Which office handles student enrollment?

**Available draft reference (pending PDF confirmation):** Charter Enrollment service (page 10) lists Office / Division: Registrar. New college students and transferees proceed to the Office of the Registrar on the scheduled appointment date.

**Citation gold:** not assigned. **Live answer:** not collected.

### aq_06 — Entrance examination duration — SIMULATED — NOT LIVE-TESTED

**Question:** How long does the LSPU entrance examination take, including orientation?

**Available draft reference (pending PDF confirmation):** Orientation — 15 minutes; examination proper — 1 and 1/2 hours; fees — none. Total Processing Time is recorded as Not specified, so a combined official duration must not be invented.

**Citation gold:** not assigned. **Live answer:** not collected.

### aq_07 — Student ID validation — SIMULATED — NOT LIVE-TESTED

**Question:** What is the process for validating my student ID?

**Available draft reference (pending PDF confirmation):** OSAS ID Validation requires a Certificate of Registration and a Student ID. Three steps; fees none; total processing time 4 minutes.

**Citation gold:** not assigned. **Live answer:** not collected.

### aq_09 — Faculty teaching load — SIMULATED — NOT LIVE-TESTED

**Question:** How is faculty teaching load determined?

**Available draft reference (pending PDF confirmation):** Dean / Associate Dean assign loads in the faculty member’s field of specialization. Faculty render 40 service hours a week exclusive of lunch; 18 hours is the maximum actual teaching load, with listed exceptions. Regular-faculty instruction allotment is 18 hours.

**Citation gold:** not assigned. **Live answer:** not collected.

### aq_10 — Faculty responsibilities — SIMULATED — NOT LIVE-TESTED

**Question:** What are the responsibilities of an LSPU faculty member?

**Available reference (Phase 2D approved):** Faculty Manual 2020, Section III, A. Commitment of Faculty (summary of listed commitments). Code of Ethics is excluded by review decision.

**Citation gold:** held. Candidate `97e32a29-fa86-458c-9fe9-dba48f9605ce::8` has a relevant body but wrong title, page metadata, and PDF viewer destination.

**Live answer:** not collected.

### aq_11 — Honorable dismissal — SIMULATED — NOT LIVE-TESTED

**Question:** What is honorable dismissal for a student?

**Available draft reference (pending PDF confirmation):** Voluntary withdrawal with the Registrar’s consent; written petition signed by parent/guardian; settle indebtedness; good standing as to character and conduct; not readmitted if granted; not issued after suspension, dropping, or expulsion.

**Citation gold:** not assigned. **Live answer:** not collected.

---

## 6. Not evaluated (4)

These cases have no live test and no simulated correctness score. Reference answers are null by protocol.

### aq_05 — Library overdue fee — NOT EVALUATED

**Question:** What is the fee for library circulation service if my book is overdue?

The Charter extraction shows “2 pesos per” with the unit missing. The word “overdue” does not appear in the 691-chunk corpus. No unit or overdue policy is invented.

### aq_12 — Current university president — NOT EVALUATED

**Question:** Who is the current LSPU president?

Phase 2D/2F keep the reference answer **null**. 2021 lists name Dr. Mario R. Briones but do not establish who is president in 2026. No gold citations.

### aq_13 — Out of scope — NOT EVALUATED

**Question:** What is the weather on Mars tomorrow?

Not an LSPU policy question. Included for future refusal testing. No live refusal test was run.

### aq_14 — Student Wi-Fi password — NOT EVALUATED

**Question:** What is the LSPU student Wi-Fi password?

No Wi-Fi password passage exists in the evaluation corpus. No password is invented.

---

## 7. Correctness and citation evaluation (supported cases only)

| Scope | Result |
| --- | --- |
| Live answers judged | 2 |
| Satisfactory live answers | 1 (aq_04) |
| Unsatisfactory live answers | 1 (aq_08) |
| Live citation verification | Pending for both |
| Simulated correctness scores | None (not invented) |
| 14-question accuracy | **Not calculated** |

Approved gold citation IDs exist only for aq_04 and aq_08. They were not compared to live displayed IDs because the live interface mapping was not captured.

---

## 8. Limitations

1. Only two questions were live-tested on the deployed chatbot.
2. Live citation titles, pages, and chunk IDs were not captured, so citation metrics remain pending.
3. Full verbatim live transcripts were not stored in this overview; only the supplied human judgments are used.
4. Eight simulated entries are **reference overviews**, not chatbot outputs.
5. Four cases cannot be scored for factual correctness on the current corpus (insufficient evidence or out of scope).
6. The pending dataset is still unlabeled and not evaluation-ready.
7. A local `answer_qa_question()` run against `chroma_evaluation` produced generation-error fallbacks after an OpenRouter 401. Those fallback answers are **not** live production results and are not used as scores here.
8. The approved aq_04 gold answer is conflict-aware (Charter ₱30.00/unit vs Handbook ₱20.00/unit). The live human judgment treated Charter P30.00 plus procedure as satisfactory. That distinction is recorded, not collapsed.

---

## 9. Recommendations

1. Complete live tests for the eight cases that already have reference material, using the student-facing chatbot and capturing verbatim answers plus displayed citations.
2. Resolve aq_01 citation usability and aq_10 metadata/viewer issues before assigning gold citation IDs.
3. Confirm pending PDF drafts (aq_02, aq_03, aq_06, aq_07, aq_09, aq_11) before promoting them to labeled gold.
4. Keep aq_05, aq_12, and aq_14 as insufficient-evidence / refusal cases; do not invent missing facts.
5. Run aq_13 as an out-of-scope refusal check, scored on refusal behavior rather than handbook correctness.
6. After live citation capture, score citation precision/recall only against approved gold IDs.
7. Report accuracy only over live-tested, labeled cases. Do not average in simulated or unevaluated items.

---

## 10. Files and what was not changed

This overview lives in:

`backend/benchmarks/evaluation/answer_quality_labeling/thesis_overview_2026-11-04/`

Unchanged on purpose:

- `answer_quality_eval_dataset.pending_human_review.json`
- `rag_eval_dataset.json`
- retrieval and classification datasets
- previous run folders under `runs/`
- production, deploys, and databases
