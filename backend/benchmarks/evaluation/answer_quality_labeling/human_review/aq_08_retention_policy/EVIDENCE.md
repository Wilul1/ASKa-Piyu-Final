# aq_08 — Retention policy (fail more than 75% of units)

**Recommended human decision: revise**

This file is source-verification evidence only. It does not change the pending dataset, `labeling_status`, or `evaluation_ready`.

## 1. Original question

What happens if I fail more than 75% of my units?

Pending case id: `aq_08_fail_more_than_75_percent` (`rag_benchmark_08`).

## 2. Source document name and version

- **Document:** LSPU Student Handbook 2021
- **File:** `LSPU Student Handbook.pdf`
- **Path:** `backend/data/documents/d9bf05ce-fcab-4629-ad4c-4f869481189f/LSPU Student Handbook.pdf`
- **Header:** Title *LSPU Student Handbook 2021*; Date **December 2021**; Doc. No. **LSPU-PM-LSH-01**; Revision **0**
- **Section (Chroma path):** Undergraduate Academic Policies > Article 5 > Retention Policies

## 3. Exact PDF page numbers

| What | PDF index | Printed header | Chroma `page` |
| --- | --- | --- | --- |
| Sec. 4 Scholastic Delinquency prose, including 4.3 Dismissal | **35** | **Page: 26 of 183** | 35 |
| Scholastic-delinquency **table** | **36** | **Page: 27 of 183** | chunk ::69 `page_start` 35 / `page_end` 36 |

Pending text and Chroma cite page 35. The **table is on the next PDF page (36)**.

## 4. Original PDF page images

Inspected as images, not OCR-only:

- `visual_handbook_pdf035_printed_page_26.png`
- `visual_handbook_pdf036_printed_page_27_table.png`

## 5. Exact supporting passages

### PDF page 35 / printed 26 of 183 — Sec. 4.3 Dismissal (verbatim from the page image)

> 4.3. *Dismissal.* Any student who fails in more than seventy-five percent (75%) of the total academic units enrolled shall be subject for dismissal from the College; provided that an incomplete grade shall not be included in the computation of earned units; provided further, that this shall not apply to students who receive final grades in only nine academic units.

Same page, related but distinct:

> Sec. 5. *Dropped.* Any student dropped from one college/school shall not be admitted to another course in LSPU, unless in the evaluation of the Dean, the student’s aptitude and interest may qualify him/her to another field of study, in which case, he/she may be admitted on probation.
>
> Sec. 7. *Disqualification Exemption.* Permanent disqualification does not apply to cases, where on the recommendation of the Faculty concerned, s/he certifies that the grade of 5.0 is due to the unauthorized dropping off the student and not to poor academic performance.

(The printed page jumps from Sec. 5 to Sec. 7; no Sec. 6 is visible on this page.)

4.1 Warning and 4.2 Probation are on the same page (25%–49% warning; 50%–74% probation).

### PDF page 36 / printed 27 of 183 — table (visual)

See section 6.

## 6. Table headers and relevant rows

Headers (visual):

**Percentage (%) of failure | Number of units enrolled | Status | Allowable load for the following semester**

| Percentage (%) of failure | Number of units enrolled | Status | Allowable load for the following semester |
| --- | --- | --- | --- |
| 25% - 49% | any number of academic units | **Warning** | Less three units from the normal load |
| 50% - 74% | 6 academic units or more | **Probation** | 15 units only |
| **75% or more** | **Nine academic units or more** | **Dismissal from the College** | **not allowed to enroll** |
| **100%** | *(cell blank)* | **Permanent disqualification from the University** | *(cell blank)* |

## 7. OCR text alongside visual evidence

PyMuPDF: `ocr_pymupdf_handbook_pdf035.txt`, `ocr_pymupdf_handbook_pdf036.txt`.

Chroma:

- `cec01713-c1ba-4061-9404-ffaa1d8e70dd::66` — 4.1–4.2 only (`chroma_ocr_cec01713_66.txt`)
- `cec01713-c1ba-4061-9404-ffaa1d8e70dd::67` — 4.3 Dismissal prose, matches the page (`chroma_ocr_cec01713_67.txt`)
- `cec01713-c1ba-4061-9404-ffaa1d8e70dd::69` — mashed table + Sec. 7 (`chroma_ocr_cec01713_69.txt`)

Chroma table OCR is column-scrambled. It does **not** turn “nine academic units or more” into the *failure count*; it places that phrase under units enrolled. The pending review_reason’s worry that OCR inverted nine-units as the failure count is **not** how the visual table reads. The remaining problem is reconciling 4.3 with the table.

## 8. Proposed reference answer (from pending dataset — not gold)

> The Student Handbook (Undergraduate Academic Policies > Article 5 > Retention Policies, page 35) scholastic delinquency table states that failing 75% or more (nine academic units or more) results in dismissal from the College and the student is not allowed to enroll. Failing 100% is listed as permanent disqualification from the University. For context in the same article: 25%–49% is Warning; 50%–74% is Probation (load reduced). Human review must confirm the OCR table against the PDF.

## 9. Evidence supporting / not supporting that proposed answer

Supports: dismissal from the College vs permanent disqualification from the University are distinct; 25–49% Warning and 50–74% Probation; 100% is permanent disqualification.

Does not support as written:

- It equates “75% or more” with “(nine academic units or more)” as if nine units *were* the 75% threshold. On the table, nine units is the **Number of units enrolled** column, not the percentage column.
- It omits 4.3’s exact trigger: **“more than seventy-five percent (75%)”**, INC excluded, and the **exemption** for students who receive final grades in **only nine academic units**.
- It omits table load consequences (“not allowed to enroll”).
- The table is on page **36**, not 35.

## 10. Ambiguities, conflicts, and missing information

Two formulations must be reconciled by a human; this pack does not pick one:

| | 4.3 prose (p.35 / printed 26) | Table (p.36 / printed 27) |
| --- | --- | --- |
| Threshold | **more than 75%** | **75% or more** |
| Nine units | **Exemption:** shall **not apply** to students who receive final grades in **only nine** academic units | **Condition:** enrolled in **nine academic units or more** |
| Consequence at ~75% | **dismissal from the College** | **Dismissal from the College**; not allowed to enroll |
| 100% | not in 4.3 | **Permanent disqualification from the University** |

Plausible reading (not gold): 4.3 “only nine” is an exemption for a light graded load; the table applies dismissal when the student was enrolled in nine or more units and failed 75%+. “More than 75%” vs “75% or more” is still unresolved.

Dismissal from the College is **not** the same as permanent disqualification from the University. Sec. 5 (Dropped from a college) is a further related rule. Sec. 7 carves unauthorized dropping (grade 5.0) out of permanent disqualification.

## 11. Recommended human decision: **revise**

Revise so the gold answer uses 4.3’s wording **and** the table, keeps nine-units in the units-enrolled / exemption sense, and distinguishes college dismissal from university permanent disqualification.

Draft for the reviewer (not gold):

> Under the Student Handbook 2021, Article 5 Retention Policies, Sec. 4.3: any student who fails in **more than 75%** of the total academic units enrolled shall be subject for **dismissal from the College**; an incomplete grade is not included in the computation of earned units; this shall **not apply** to students who receive final grades in **only nine academic units**. The scholastic-delinquency table on the following page lists **75% or more** with **nine academic units or more** enrolled as **Dismissal from the College** (not allowed to enroll), and **100%** as **Permanent disqualification from the University**. Those two statuses are not the same. A human must reconcile “more than 75%” with “75% or more” and the “only nine” exemption with the table’s “nine or more” enrollment condition.

### Questions to resolve before approving a reference answer

1. Is the trigger **more than 75%** (4.3), **75% or more** (table), or both quoted?
2. Does “nine academic units” mean an **exemption** (only nine final grades), an **enrollment condition** (nine or more), or both?
3. Must gold distinguish **dismissal from the College** vs **permanent disqualification from the University**?
4. Include INC exclusion, Sec. 5, and/or Sec. 7?
5. Cite PDF 35, PDF 36, printed 26–27, or Chroma page 35?
