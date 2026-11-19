# Human-review decision record

## Phase 2D — Promotion of five approved reference answers

**Approval:** The user explicitly approved the five Phase 2C drafts for promotion into the pending answer-quality dataset.

**Promotion date:** 2026-11-05.

**Source of approved text (unchanged historical draft artifact):** `reference_answers.draft.json`

**Promoted case IDs:**

| Case ID | `proposed_reference_answer` after promotion |
| --- | --- |
| `aq_01_tor_fee` | Approved draft text, copied exactly |
| `aq_04_dropping_fee_multi_document` | Approved draft text, copied exactly |
| `aq_08_fail_more_than_75_percent` | Approved draft text, copied exactly |
| `aq_10_faculty_responsibilities` | Approved draft text, copied exactly |
| `aq_12_university_president` | JSON `null` (not the string `"null"`) |

**Dataset file updated:** `backend/benchmarks/evaluation/answer_quality_labeling/answer_quality_eval_dataset.pending_human_review.json`

**What promotion is not:**

- Promotion is **not** evaluation-ready. Dataset `evaluation_ready` remains `false`.
- `labeling_status` remains `unlabeled` on all cases. These five were not copied into `rag_eval_dataset.json`.
- `gold_citation_ids` were not assigned. Citation-label review and other evaluation prerequisites remain.
- Phase 2B raw evidence packs and `INDEX.md` were not modified.
- `reference_answers.draft.json` was left unchanged as the historical record of the drafts that were reviewed and approved.

**Narrowly necessary status update:** `aq_12_university_president` `review_status` was changed from `pending_human_review` to the existing schema value `insufficient_evidence`, matching `aq_05` and `aq_14` (null answer when evidence is insufficient). No new status value was invented. `aq_01`, `aq_04`, `aq_08`, and `aq_10` keep `review_status: pending_human_review` because the schema has no established “reference-answer-approved” value.

---

# Phase 2C — Human-review decisions and draft reference answers

Prepared 2026-11-05. Historical record of the drafts later approved and promoted in Phase 2D. Companion machine-readable drafts: `reference_answers.draft.json`.

As of Phase 2C (before promotion) this file recorded that drafts were not yet copied into the pending dataset. Phase 2D copied the five `proposed_reference_answer` values and set `aq_12` `review_status` to `insufficient_evidence`.

Evidence inspected: `INDEX.md` and the five case folders under this directory. Schema conventions inspected: pending dataset `proposed_reference_answer` (null when insufficient); `rag_eval_dataset.json` would later use `reference_answer` only for `labeling_status=labeled` cases. Citation gold remains a separate workflow (`gold_citation_ids` is not assigned here).

---

## aq_01_tor_fee

**Question:** How much does it cost to get a copy of my Transcript of Records?

**Human-review decision:** Revise the pending proposed answer. Approve the visual TOR grouping. Include both undergraduate and graduate rates. Exclude certification, authentication, and diploma fees. Treat P137 as OCR confusion with Form F137, not as a fee.

**Draft reference answer (not gold):**

> According to the Citizen's Charter 2026, 1st Edition, a Transcript of Records costs ₱75.00 per page for undergraduate students and ₱150.00 per page for graduate students.

**Sources (do not collapse these page numbers):**

| Kind | Value |
| --- | --- |
| Document | Citizen's Charter 2026, 1st Edition (`Laguna State Polytechnic University-CC_2026-1st Edition.pdf`) |
| Service | Issuance of Transcript of Records/Transfer Credentials/Certifications/CAV/Authenticated Documents (Registrar) |
| PDF page index | 13–14 (fee table). Service title starts on PDF 12. |
| Printed footer | 5–6 (service title on printed 4) |
| Chroma stored `page` | 12 (metadata of chunk `da4a1832-7242-4e94-8ba6-bc0b9f2294bf::1`; not the fee-table page) |

**Ambiguities still on the record:**

- The printed graduate line is `P150/page` (no `.00`); the approved draft uses ₱150.00 per page as the same amount.
- No later BOR supersession of the 2026 Charter TOR rates was inspected.

**Status:** `draft_requires_final_human_approval`. Case remains unlabeled.

---

## aq_04_dropping_fee_multi_document

**Question:** How much does it cost to drop a subject?

**Human-review decision:** Revise. Accept Charter ₱30.00 per unit for new and transferee students. Accept Handbook ₱20.00 per unit citing BOR 1046, s.2012. **Do not choose a winning rate.** The evidence does not establish whether the older rate was superseded. Draft a conflict-aware answer that tells students to confirm with the Registrar.

**Draft reference answer (not gold):**

> Official LSPU sources list two different dropping fees and do not establish which amount is currently in force. The Citizen's Charter 2026 lists ₱30.00 per unit for new and transferee students. The Student Handbook 2021 requires a dropping fee of ₱20.00 per unit, citing LSPU BOR Resolution 1046, s.2012. Confirm the applicable fee with the Registrar before paying.

**Sources (do not collapse these page numbers):**

| Kind | Charter 2026 | Handbook 2021 |
| --- | --- | --- |
| Document | Citizen's Charter 2026, 1st Edition | LSPU Student Handbook 2021 (Doc. LSPU-PM-LSH-01 Rev 0; Date December 2021) |
| Passage | Dropping of Subjects; Who may avail: New and Transferee Students; TOTAL P30.00/unit | Sec. 4.3: “A dropping fee of P20/unit is required. (LSPU BOR 1046, s.2012)” |
| PDF page index | 98 | 40 (section starts PDF 39) |
| Printed page | footer 90 | Page: 31 of 183 (section starts printed 30 of 183) |
| Chroma `page` | 98 (`da4a1832-7242-4e94-8ba6-bc0b9f2294bf::97`) | stored 39 (`cec01713-c1ba-4061-9404-ffaa1d8e70dd::82`; `page_end` 40). **Chroma page 39 is the discrepancy:** the fee sentence is on PDF 40 / printed 31. |

**Ambiguities still on the record:**

- Amount conflict is real: ₱30.00/unit vs ₱20.00/unit. Both are per unit. The pending dataset’s flat P30.00 was OCR.
- Charter who-may-avail is limited to new and transferee students; Handbook 4.3 has no such limit on its face.
- BOR Resolution 1046 s.2012 was not located as a standalone PDF.
- The retrieval-relevance note that “the Charter figure is the intended current answer” is a **retrieval** label. It is not used as answer-quality gold here and was not changed.

**Status:** `draft_requires_final_human_approval`. Case remains unlabeled.

---

## aq_08_fail_more_than_75_percent

**Question:** What happens if I fail more than 75% of my units?

**Human-review decision:** Revise. Preserve both wordings (Section 4.3 “more than 75%”; table “75% or more”). Explain the nine-unit condition in its two contexts. Include the incomplete-grade exclusion. Distinguish dismissal from the College from permanent disqualification from the University. Flag the exact-75% discrepancy and recommend confirmation with the Registrar.

**Draft reference answer (not gold):**

> The LSPU Student Handbook 2021 retention policy uses two slightly different failure thresholds.
>
> Section 4.3 states that any student who fails in more than 75% of the total academic units enrolled shall be subject for dismissal from the College. An incomplete grade is not included in the computation of earned units. Section 4.3 also states that this shall not apply to students who receive final grades in only nine academic units.
>
> The scholastic-delinquency table on the following page lists 75% or more, when the student is enrolled in nine academic units or more, as Dismissal from the College (not allowed to enroll). Failing 100% is listed separately as Permanent disqualification from the University, which is not the same as dismissal from the College.
>
> The nine-unit language therefore appears in two contexts: as an exemption in Section 4.3 for students who receive final grades in only nine academic units, and as an enrollment condition in the table (nine academic units or more) for the 75% or more dismissal row.
>
> Because Section 4.3 says “more than 75%” and the table says “75% or more,” these pages do not resolve the exact-75% case. Confirm the applicable rule with the Registrar.

**Sources (do not collapse these page numbers):**

| Kind | Section 4.3 prose | Scholastic-delinquency table |
| --- | --- | --- |
| Document | LSPU Student Handbook 2021, Article 5 Retention Policies | same |
| PDF page index | 35 | 36 |
| Printed page | Page: 26 of 183 | Page: 27 of 183 |
| Chroma `page` | 35 (`cec01713-c1ba-4061-9404-ffaa1d8e70dd::66` and `::67`) | `::69` has `page_start` 35 / `page_end` 36 |

**Ambiguities still on the record:**

- Exact 75% is unresolved between the two wordings.
- Nine units is an exemption in 4.3 and an enrollment condition in the table; the draft reports both and does not merge them.
- Sec. 5 (Dropped) and Sec. 7 (Disqualification Exemption) were inspected but are not part of this draft.

**Status:** `draft_requires_final_human_approval`. Case remains unlabeled.

---

## aq_10_faculty_responsibilities

**Question:** What are the responsibilities of an LSPU faculty member?

**Human-review decision:** Revise. Use Faculty Manual 2020, Section III, A. Commitment of Faculty. Prepare a concise, faithful summary of those listed commitments. Do not automatically include B. Code of Ethics. Cite PDF 16–17 / printed 5–6. Record that the retrieved chunk’s title/page metadata points to Historical Development / page 13 while its body contains pages 16–17. **Do not modify the knowledge-base chunk.**

**Draft reference answer (not gold):**

> According to the LSPU Faculty Manual 2020, Section III, A. Commitment of Faculty, faculty commitments include: treating teaching as a personal commitment, including professional maturity, sharing instructional resources, setting aside personal bias, and preparing for quality teaching; placing the learner at the center of the educative process, including respecting students, supporting growth, not ridiculing or condemning them, inspiring their best effort, grading without personal friendship or vested-group pressure, meeting individual needs, encouraging high individual goals, and keeping confidential student information unless required by authorized agency or law; sharing with parents the responsibility of shaping the student’s future, including cooperative relationships and keeping parents informed of academic progress and deficiencies; and serving as a vanguard of change through public service, research, extension, and community engagement.

**Sources (do not collapse these page numbers):**

| Kind | Value |
| --- | --- |
| Document | LSPU Faculty Manual 2020 (header Date March 2021; Doc. LSPU-PM-LFM-01 Rev 0) |
| Heading | III. Commitment of the LSPU Faculty / A. Commitment of Faculty |
| PDF page index | 16–17 |
| Printed page | Page: 5 of 92 and Page: 6 of 92 |
| Chroma metadata of chunk `97e32a29-fa86-458c-9fe9-dba48f9605ce::8` | title “II. Historical Development of LSPU - Part 2”; stored `page` / `page_start` **13**; `page_end` 18. The body text is PDF 16–17, not page 13. Page 13 is Historical Development and does not support this answer. **Chunk not modified.** |

**Ambiguities still on the record:**

- The source heading is “Commitment of Faculty,” not a heading titled “responsibilities.”
- B. Code of Ethics begins on PDF 17 and is excluded from this draft by decision.

**Status:** `draft_requires_final_human_approval`. Case remains unlabeled.

---

## aq_12_university_president

**Question:** Who is the current LSPU president?

**Human-review decision:** Insufficient evidence for a “current” (2026) answer. The two 2021 documents establish that Dr. Mario R. Briones was named University President at that time. They do not establish who is president in 2026. **Keep the proposed / draft reference answer null.** Record the need for an up-to-date authoritative source.

**Draft reference answer:** `null`

**Dated source note (not a reference answer, not gold):**

The LSPU Faculty Manual 2020 (Administrative Officials; PDF page 11 / printed page vii of 92; header Date March 2021) and the LSPU Student Handbook 2021 (Administrative Officials; PDF page 18 / printed Page 9 of 183; header Date December 2021) both name **DR. MARIO R. BRIONES** as University President. Those lists are not a 2026 directory.

**Sources (do not collapse these page numbers):**

| Kind | Faculty Manual 2020 | Student Handbook 2021 |
| --- | --- | --- |
| PDF page index | 11 | 18 |
| Printed page | Page: vii of 92 | Page: 9 of 183 |
| Chroma `page` | 11 (`97e32a29-fa86-458c-9fe9-dba48f9605ce::6`) | 18 (`cec01713-c1ba-4061-9404-ffaa1d8e70dd::10`) |

**Ambiguities still on the record:**

- VP for Research Development and Extension already conflicts: Dr. Corazon N. San Agustin (Faculty, March 2021) vs Dr. Robert C. Agatep (Handbook, December 2021). That conflict is staleness evidence only; it is not part of a president answer.
- No 2026 Charter officials plate, BOR appointment, or current university directory was found in the inspected PDFs.

**Status:** `draft_requires_final_human_approval` with `draft_reference_answer: null`. Case remains unlabeled. An up-to-date authoritative source is required before any non-null gold answer to “current” may be written.

---

## What was not done (Phase 2C; see Phase 2D header for the later promotion)

- As of Phase 2C, the pending dataset was not yet modified.
- No case was set to `labeling_status=labeled`.
- No evaluation was run.
- No Chroma, chatbot, scoring, API, Flutter, or production change.
- Phase 2B evidence files were left unchanged.
