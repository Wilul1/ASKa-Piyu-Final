# Phase 2F — Citation review decisions

Recorded 2026-11-05 after human approval of the Phase 2E citation-evidence review.

This file records citation-review **decisions**. It does **not** assign `gold_citation_ids`. It does **not** change the pending dataset, `labeling_status`, or `evaluation_ready`. Phase 2B evidence, Phase 2C drafts, Phase 2D decisions, Chroma, and application code are unchanged.

Evidence reviewed: `citation_review/INDEX.md` and the five case files in this folder.

---

## Summary

| Case | Decision | Candidate citation IDs | Gold assigned? |
| --- | --- | --- | --- |
| aq_01 | **Revise.** Keep `::1` as candidate evidence. Citation usability unresolved (mixed fees; incomplete displayed page/viewer range). | `da4a1832-7242-4e94-8ba6-bc0b9f2294bf::1` | No |
| aq_04 | **Accept both** candidates. Preserve fee conflict and new/transferee limitation. | `da4a1832-7242-4e94-8ba6-bc0b9f2294bf::97`, `cec01713-c1ba-4061-9404-ffaa1d8e70dd::82` | No |
| aq_08 | **Accept** `::67` for Section 4.3 and `::69` for the table. Preserve threshold discrepancy. **Exclude** `::66`. | `cec01713-c1ba-4061-9404-ffaa1d8e70dd::67`, `cec01713-c1ba-4061-9404-ffaa1d8e70dd::69` | No |
| aq_10 | **Hold** `::8`. Body relevant; title, page metadata, and PDF viewer destination wrong. | `97e32a29-fa86-458c-9fe9-dba48f9605ce::8` | No |
| aq_12 | **Insufficient evidence.** Assign no gold citations for the current-president question. | none | No |

---

## aq_01_tor_fee

**Decision: revise.** Keep `da4a1832-7242-4e94-8ba6-bc0b9f2294bf::1` as candidate evidence. Citation usability is unresolved because the chunk mixes fee categories and the displayed page/viewer range is incomplete.

**Question:** How much does it cost to get a copy of my Transcript of Records?

**Approved reference answer:** According to the Citizen's Charter 2026, 1st Edition, a Transcript of Records costs ₱75.00 per page for undergraduate students and ₱150.00 per page for graduate students.

**Candidate citation IDs:**

- `da4a1832-7242-4e94-8ba6-bc0b9f2294bf::1`

**Supporting claims and sources:**

- Undergraduate TOR ₱75.00/page and graduate TOR ₱150/page, visually grouped under Transcript of Records on Citizen's Charter 2026, 1st Edition (document ID `da4a1832-7242-4e94-8ba6-bc0b9f2294bf`).
- Certifications, authentication, diploma, and OCR P137/F137 are **not** TOR evidence.

**Page-number distinctions:**

| Kind | Value |
| --- | --- |
| Chroma page metadata | 12 |
| PDF page index (fee table) | 13–14 |
| Printed page (fee table) | 5–6 |
| PDF page index (service title) | 12 |
| Printed page (service title) | 4 |

**Student-visible rendering limitations:**

- Citation ID can be emitted as `da4a1832-…::1`.
- Student page label uses Chroma 12, likely shown as pages 12–13 after charter +1 soft-extend, not printed 5–6.
- Viewer may include PDF 13 (TOR rows) and miss PDF 14.
- Chunk body mashes P75/P150/P30/P137/diploma and does not isolate TOR.

**Remaining work:** Decide later whether `::1` becomes gold despite mash and incomplete viewer range, or remains candidate-only until a cleaner citable unit exists. Do not assign `gold_citation_ids` now.

---

## aq_04_dropping_fee_multi_document

**Decision: accept both candidate citations.** Preserve the fee conflict and the Charter new/transferee limitation. Do not choose a winning rate.

**Question:** How much does it cost to drop a subject?

**Approved reference answer:** Official LSPU sources list two different dropping fees and do not establish which amount is currently in force. The Citizen's Charter 2026 lists ₱30.00 per unit for new and transferee students. The Student Handbook 2021 requires a dropping fee of ₱20.00 per unit, citing LSPU BOR Resolution 1046, s.2012. Confirm the applicable fee with the Registrar before paying.

**Candidate citation IDs (accepted as candidates, not gold):**

- Charter: `da4a1832-7242-4e94-8ba6-bc0b9f2294bf::97`
- Handbook: `cec01713-c1ba-4061-9404-ffaa1d8e70dd::82`

**Supporting claims and sources:**

- Charter 2026 Dropping of Subjects (Colleges): ₱30.00/unit; who may avail: new and transferee students. Document ID `da4a1832-7242-4e94-8ba6-bc0b9f2294bf`.
- Handbook 2021 Sec. 4.3: ₱20.00/unit citing BOR 1046, s.2012. Document ID `cec01713-c1ba-4061-9404-ffaa1d8e70dd`.
- Both IDs are independently citable. BOR 1046 is not a separate chunk (`null`).

**Page-number distinctions:**

| Source | Chroma page | PDF page index | Printed page |
| --- | --- | --- | --- |
| Charter `::97` | 98 | 98 | 90 |
| Handbook `::82` | 39 (`page_end` 40) | 40 (fee sentence) | 31 of 183 |

**Student-visible rendering limitations:**

- Charter label shows page 98, not printed 90. Chunk body stores `Fees P30.00` without `/unit`; PDF visual has P30.00/unit.
- Handbook label shows pages 39–40, not printed 31. The P20/unit sentence is in the chunk body.
- Enrollment Advising fee 60 on the same Charter page must not be cited as dropping.

**Remaining work:** If Citation Accuracy is later scored against the conflict-aware answer, a human gold set would need **both** IDs. That promotion is not done here. `gold_citation_ids` remain unassigned.

---

## aq_08_fail_more_than_75_percent

**Decision: accept** `cec01713-c1ba-4061-9404-ffaa1d8e70dd::67` for Section 4.3 and `cec01713-c1ba-4061-9404-ffaa1d8e70dd::69` for the table. Preserve the threshold discrepancy. **Exclude** `cec01713-c1ba-4061-9404-ffaa1d8e70dd::66`.

**Question:** What happens if I fail more than 75% of my units?

**Approved reference answer:** The LSPU Student Handbook 2021 retention policy uses two slightly different failure thresholds. Section 4.3 states that any student who fails in more than 75% of the total academic units enrolled shall be subject for dismissal from the College. An incomplete grade is not included in the computation of earned units. Section 4.3 also states that this shall not apply to students who receive final grades in only nine academic units. The scholastic-delinquency table on the following page lists 75% or more, when the student is enrolled in nine academic units or more, as Dismissal from the College (not allowed to enroll). Failing 100% is listed separately as Permanent disqualification from the University, which is not the same as dismissal from the College. The nine-unit language therefore appears in two contexts: as an exemption in Section 4.3 for students who receive final grades in only nine academic units, and as an enrollment condition in the table (nine academic units or more) for the 75% or more dismissal row. Because Section 4.3 says “more than 75%” and the table says “75% or more,” these pages do not resolve the exact-75% case. Confirm the applicable rule with the Registrar.

**Candidate citation IDs:**

- Accepted for 4.3: `cec01713-c1ba-4061-9404-ffaa1d8e70dd::67`
- Accepted for the table (including 100% permanent disqualification): `cec01713-c1ba-4061-9404-ffaa1d8e70dd::69`
- Excluded: `cec01713-c1ba-4061-9404-ffaa1d8e70dd::66` (Warning/Probation only; not 75% dismissal)

**Supporting claims and sources:**

- 4.3 (`::67`): more than 75%; INC exclusion; only-nine exemption; dismissal from the College. Handbook 2021, Article 5.
- Table (`::69`): 75% or more; nine academic units or more enrolled; Dismissal from the College / not allowed to enroll; 100% permanent disqualification from the University.
- Threshold discrepancy (more than 75% vs 75% or more) is preserved, not resolved.

**Page-number distinctions:**

| Passage | Chroma page | PDF page index | Printed page |
| --- | --- | --- | --- |
| 4.3 `::67` | 35 | 35 | 26 of 183 |
| Table `::69` | 35–36 | 36 | 27 of 183 |

**Student-visible rendering limitations:**

- `::67` displays page 35, not printed 26. Body matches 4.3.
- `::69` displays pages 35–36; chunk **title** is Disqualification Exemption; table OCR is scrambled. Viewer range includes the table page.
- Printed 26–27 never appear in the citation label.

**Remaining work:** Later gold, if any, should list `::67` and `::69` only, mapped to those claims. `::66` stays excluded. `gold_citation_ids` not assigned now. Decide whether mashed `::69` is acceptable gold text or still needs a cleaner table unit.

---

## aq_10_faculty_responsibilities

**Decision: hold** `97e32a29-fa86-458c-9fe9-dba48f9605ce::8`. Its body is relevant, but title, page metadata, and PDF viewer destination are wrong. Knowledge-base chunk not modified.

**Question:** What are the responsibilities of an LSPU faculty member?

**Approved reference answer:** According to the LSPU Faculty Manual 2020, Section III, A. Commitment of Faculty, faculty commitments include: treating teaching as a personal commitment, including professional maturity, sharing instructional resources, setting aside personal bias, and preparing for quality teaching; placing the learner at the center of the educative process, including respecting students, supporting growth, not ridiculing or condemning them, inspiring their best effort, grading without personal friendship or vested-group pressure, meeting individual needs, encouraging high individual goals, and keeping confidential student information unless required by authorized agency or law; sharing with parents the responsibility of shaping the student’s future, including cooperative relationships and keeping parents informed of academic progress and deficiencies; and serving as a vanguard of change through public service, research, extension, and community engagement.

**Candidate citation IDs:**

- Held (not gold): `97e32a29-fa86-458c-9fe9-dba48f9605ce::8`

**Supporting claims and sources:**

- Faculty Manual 2020, Section III, A. Commitment of Faculty (items 1–4). Document ID `97e32a29-fa86-458c-9fe9-dba48f9605ce`.
- B. Code of Ethics is excluded from the approved answer.
- Chunk **body** contains the Commitment list. Chunk **title/section** say II. Historical Development of LSPU.

**Page-number distinctions:**

| Kind | Value |
| --- | --- |
| Chroma page metadata | 13 (`page_end` 18) |
| PDF page index of body | 16–17 |
| Printed page of body | 5 of 92 and 6 of 92 |
| PDF page index of metadata heading | 13 |
| Printed page of metadata heading | 2 of 92 |

**Student-visible rendering limitations:**

- Citation ID can be emitted.
- Label shows Historical Development and pages 13–18, not Commitment / printed 5–6.
- PDF viewer lands on PDF index 13 (history), not 16–17.
- The implementation cannot identify actual source pages 16–17 from this chunk’s metadata.

**Remaining work:** Hold until a later, separate ingestion/metadata fix, or an explicit human decision to gold `::8` despite wrong title/page. Do not modify the chunk in this phase. `gold_citation_ids` not assigned.

---

## aq_12_university_president

**Decision: insufficient evidence.** Assign **no** gold citations for the current-president question.

**Question:** Who is the current LSPU president?

**Approved reference answer:** `null`

**Candidate citation IDs for gold:** none.

Dated 2021 plates (not gold for this question):

- `97e32a29-fa86-458c-9fe9-dba48f9605ce::6` — Faculty Manual 2020, header Date March 2021. PDF 11 / printed vii of 92 / Chroma 11. Names DR. MARIO R. BRIONES, University President.
- `cec01713-c1ba-4061-9404-ffaa1d8e70dd::10` — Student Handbook 2021, header Date December 2021. PDF 18 / printed 9 of 183 / Chroma 18. Same president name.

Those sources do **not** establish who is president in 2026. VP-RDE names already conflict (San Agustin vs Agatep); that is staleness evidence only.

**Page-number distinctions:** Chroma 11 vs printed vii; Chroma 18 vs printed 9. PDF indices 11 and 18 match Chroma for these plates.

**Student-visible rendering limitations:** If cited, labels would show pages 11 and 18, not printed vii/9. They must not be shown as gold support for a “current” 2026 answer.

**Remaining work:** Obtain an up-to-date authoritative source before any non-null reference answer or gold citation set. Citation-set precision/recall must not be scored for this case while gold is empty. `gold_citation_ids` remain unassigned.

---

## What this record does not do

- Does not write `gold_citation_ids` into any dataset.
- Does not change `labeling_status` or set `evaluation_ready` true.
- Does not modify `answer_quality_eval_dataset.pending_human_review.json` or `rag_eval_dataset.json`.
- Does not modify Chroma, citation code, chatbot, Flutter, or production.
- Does not modify Phase 2B evidence, Phase 2C drafts, or Phase 2D decisions.
- Does not run evaluations.
