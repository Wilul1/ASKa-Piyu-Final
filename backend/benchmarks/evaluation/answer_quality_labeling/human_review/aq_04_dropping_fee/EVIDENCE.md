# aq_04 — Dropping a subject fee

**Recommended human decision: revise**

This file is source-verification evidence only. It does not change the pending dataset, `labeling_status`, or `evaluation_ready`. No source is selected as the winner.

## 1. Original question

How much does it cost to drop a subject?

Pending case id: `aq_04_dropping_fee_multi_document` (`rag_benchmark_04`).

## 2. Source document names and versions

1. **Citizen's Charter 2026, 1st Edition**
   - File: `Laguna State Polytechnic University-CC_2026-1st Edition.pdf`
   - Path: `backend/data/documents/6c3d0f00-fd53-43be-943f-09e1e7ddbce4/Laguna State Polytechnic University-CC_2026-1st Edition.pdf`
   - PDF created/modified `2026-03-31 +08:00` (102 pages)

2. **LSPU Student Handbook 2021**
   - File: `LSPU Student Handbook.pdf`
   - Path: `backend/data/documents/d9bf05ce-fcab-4629-ad4c-4f869481189f/LSPU Student Handbook.pdf`
   - Header: Title *LSPU Student Handbook 2021*; Date **December 2021**; Doc. No. **LSPU-PM-LSH-01**; Revision **0**
   - PDF created/modified `2022-01-25 +08:00` (198 pages)
   - Cited authority on the fee line: **LSPU BOR 1046, s.2012**

## 3. Exact PDF page numbers

| Source | What | PDF index | Printed page | Chroma `page` |
| --- | --- | --- | --- | --- |
| Charter | 8. Dropping of Subjects (full card) | **98** | footer **90** | 98 |
| Handbook | Sec. 4 Dropping of Students from a Course (start) | **39** | **Page: 30 of 183** | 39 |
| Handbook | 4.3 dropping fee P20/unit | **40** | **Page: 31 of 183** | page_start 39 / page_end 40 |

Pending text says Charter “page 98” and Handbook “page 39”. Charter PDF 98 is correct as a PDF index, but the printed footer is **90**. The P20/unit sentence is on PDF **40**, not 39.

## 4. Original PDF page images

- `visual_charter_pdf098_printed_footer_90.png`
- `visual_handbook_pdf039_printed_page_30.png`
- `visual_handbook_pdf040_printed_page_31.png`

## 5. Exact supporting passages

### Citizen's Charter (visual, PDF 98 / printed 90)

> 8. Dropping of Subjects
>
> Process for students who intend to drop subjects.
>
> Office or Division: Colleges
> Classification: Simple
> Type of Transaction: G2C - Government to Citizen
> Who may avail: **New and Transferee Students**
>
> CHECKLIST OF REQUIREMENTS: Dropping Form — Registrar’s Office
>
> CLIENT STEPS | AGENCY ACTIONS | FEES TO BE PAID | PROCESSING TIME | PERSON RESPONSIBLE
> Student Application for Dropping | Release of dropping form | **30/unit** | 3 min | Registrar’s Office / Cashier’s Office
> Request for the dropping of subjects from the faculty-in-charge | Approval of the faculty-in-charge | N/A | 5 minutes | Faculty-in-charge
> Request for Deans Approval | Approval from the Dean | N/A | 5 Minutes | Dean/Associate Dean
> Submit approved Dropping Form | Receives approved dropping form | N/A | 2 minutes | Registrar’s Office
> **TOTAL: P30.00/unit** | 15 minutes

The same printed page then starts a **different** service, “9. Enrollment Advising”, with who may avail “Students, Shifters, Transferees” and a grades-evaluation fee printed as **60**. That is not the dropping fee.

### Student Handbook (visual, PDF 40 / printed 31 of 183)

> 4.3. A dropping fee of P20/unit is required. (LSPU BOR 1046, s.2012)

Surrounding policy (PDF 39–40, printed 30–31), Article 6 Academic Load and Changes, Sec. 4 Dropping of Students from a Course: dropping after 25% absences; withdraw before midterm without prejudice; 4.2 grade-of-5.0 rules. The fee sentence is a separate numbered item (4.3), not limited on its face to new or transferee students.

## 6. Table headers and relevant rows

Charter Dropping card headers: **CLIENT STEPS | AGENCY ACTIONS | FEES TO BE PAID | PROCESSING TIME | PERSON RESPONSIBLE**

| Source | Charging unit | Amount as printed | Who may avail / scope |
| --- | --- | --- | --- |
| Charter 2026, Dropping of Subjects | **per unit** | **30/unit** in the step cell; **P30.00/unit** in TOTAL | **New and Transferee Students** |
| Handbook 2021, 4.3 + BOR 1046 s.2012 | **per unit** | **P20/unit** | General dropping-from-a-course section; no population limit on the fee sentence |

## 7. OCR text alongside visual evidence

PyMuPDF: `ocr_pymupdf_charter_pdf098.txt`, `ocr_pymupdf_handbook_pdf039.txt`, `ocr_pymupdf_handbook_pdf040.txt`.

Chroma Charter chunk `da4a1832-7242-4e94-8ba6-bc0b9f2294bf::97`: `chroma_ocr_da4a1832_97.txt`

> Fees **P30.00**
> Who May Avail: New and Transferee Students

The `/unit` was dropped. Visual TOTAL is **P30.00/unit**. The pending proposed answer inherited the flat **P30.00**.

Chroma Handbook chunk `cec01713-c1ba-4061-9404-ffaa1d8e70dd::82`: `chroma_ocr_cec01713_82.txt` — 4.3 wording matches the page image.

## 8. Proposed reference answer (from pending dataset — not gold)

> Two official LSPU sources disagree. The Citizen's Charter 2026 1st Edition Dropping of Subjects card (Colleges, page 98) lists Fees: P30.00. The Student Handbook Dropping Grades Policy (page 39) states a dropping fee of P20/unit (LSPU BOR 1046, s.2012). A human reviewer must choose the in-force figure; this draft does not pick a winner.

## 9. Evidence supporting / not supporting that proposed answer

Supports: two official documents disagree on the peso amount; the draft correctly refuses to pick a winner.

Must revise:

- Charter fee is **not** a flat P30.00. Visual evidence is **P30.00/unit**.
- Handbook P20/unit is on PDF page **40** (printed 31), not 39.
- Apparent “P30 vs P20/unit” (flat vs per-unit) is an **OCR artifact**. The real conflict is **P30.00/unit vs P20/unit**.
- Charter who-may-avail is narrower (**New and Transferee Students**). That may be a different circumstance, not a simple later-supersedes-earlier conflict.

## 10. Ambiguities, conflicts, and missing information

The amount conflict is **real**: 30 vs 20, both per unit.

Possible readings (human must choose; this pack does not):

1. Charter 2026 superseded BOR 1046 s.2012 / Handbook 2021 for all students.
2. Charter applies only to **new and transferee** students; Handbook P20/unit remains for other students.
3. Charter who-may-avail is an extraction/layout error, and the fee is university-wide P30.00/unit.
4. Neither figure is known to be in force without a later BOR / accounting schedule.

Also: Enrollment Advising on the same Charter page shows fee **60** — do not merge that into dropping.

No 2012 BOR Resolution 1046 PDF is in this evidence pack.

## 11. Recommended human decision: **revise**

Revise the pending answer so both fees are per-unit, record the Charter population limit, and still **do not select a winning source**. Leave the case unlabeled until the in-force schedule is decided.

Draft for the reviewer (not gold):

> Two official LSPU sources state different per-unit dropping fees and do not, by themselves, establish a single in-force amount. The Citizen's Charter 2026, 1st Edition, “Dropping of Subjects” (Colleges; Who may avail: New and Transferee Students) lists **P30.00/unit**. The Student Handbook 2021, Sec. 4.3, states **P20/unit** is required (LSPU BOR 1046, s.2012). A later authoritative fee schedule is required before this can be a single-number gold answer.

### Questions to resolve before approving a reference answer

1. Is Charter **P30.00/unit** (not flat P30.00) accepted from the page image?
2. Does “Who may avail: New and Transferee Students” limit the P30.00/unit fee, or is it a card-layout error?
3. Is Handbook P20/unit (BOR 1046 s.2012) still in force for continuing students, superseded, or unknown?
4. Should gold be a **conflict statement**, a **single in-force fee**, or **insufficient evidence** until accounting/BOR confirms?
5. Which page numbers should citations use (PDF 98 vs printed 90; PDF 40 vs Chroma 39)?
