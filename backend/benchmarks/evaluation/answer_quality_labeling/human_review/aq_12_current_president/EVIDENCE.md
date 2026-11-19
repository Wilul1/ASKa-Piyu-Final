# aq_12 — Current LSPU president

**Recommended human decision: insufficient evidence**

This file is source-verification evidence only. It does not change the pending dataset, `labeling_status`, or `evaluation_ready`. Neither inspected source establishes who is **currently** president as of the evaluation date (2026).

## 1. Original question

Who is the current LSPU president?

Pending case id: `aq_12_university_president` (`rag_benchmark_12`).

## 2. Source document names and versions

1. **LSPU Faculty Manual 2020**
   - File: `LSPU Faculty Manual 2020.pdf`
   - Path: `backend/data/documents/c67bd8c8-81cd-4c8c-bda1-4f7d2039a406/LSPU Faculty Manual 2020.pdf`
   - Header: Title *LSPU Faculty Manual 2020*; Date **March 2021**; Doc. No. **LSPU-PM-LFM-01**; Revision **0**
   - PDF created/modified `2021-06-21 +08:00`

2. **LSPU Student Handbook 2021**
   - File: `LSPU Student Handbook.pdf`
   - Path: `backend/data/documents/d9bf05ce-fcab-4629-ad4c-4f869481189f/LSPU Student Handbook.pdf`
   - Header: Title *LSPU Student Handbook 2021*; Date **December 2021**; Doc. No. **LSPU-PM-LSH-01**; Revision **0**
   - PDF created/modified `2022-01-25 +08:00`

Neither document is a 2026 administrative directory.

## 3. Exact PDF page numbers

| Source | What | PDF index | Printed header | Chroma `page` |
| --- | --- | --- | --- | --- |
| Faculty Manual | ADMINISTRATIVE OFFICIALS | **11** | **Page: vii of 92** | 11 |
| Student Handbook | ADMINISTRATIVE OFFICIALS | **18** | **Page: 9 of 183** | 18 |
| Student Handbook (additional) | BOARD OF REGENTS | **16** | **Page: 7 of 183** | (not the pending supporting chunk) |

Pending citations Faculty page 11 and Handbook page 18 match the **PDF indices** of the Administrative Officials plates. Printed numbers are **vii** and **9 of 183**.

## 4. Original PDF page images

- `visual_faculty_pdf011_printed_page_vii.png`
- `visual_handbook_pdf018_printed_page_9.png`
- `visual_handbook_pdf016_printed_page_7_board.png` (Board of Regents; corroborates the president name, still dated 2021)

## 5. Exact supporting passages

### Faculty Manual, PDF 11 / printed vii of 92 (March 2021)

Heading: **ADMINISTRATIVE OFFICIALS**

- **DR. MARIO R. BRIONES** — University President
- **DR. EDEN C. CALLO** — Vice President for Academic Affairs
- **ENGR. BELTRAN P. PEDRIGAL, MSA** — Vice President for Administration
- **DR. CORAZON N. SAN AGUSTIN** — Vice President for Research Development and Extension

### Student Handbook, PDF 18 / printed 9 of 183 (December 2021)

Heading: **ADMINISTRATIVE OFFICIALS**

- **DR. MARIO R. BRIONES** — University President
- **DR. EDEN C. CALLO** — Vice President for Academic Affairs
- **ENGR. BELTRAN P. PEDRIGAL, MSA** — Vice President for Administration
- **DR. ROBERT C. AGATEP** — Vice President for Research Development and Extension

### Student Handbook, PDF 16 / printed 7 of 183 — Board of Regents (same 2021 edition)

- **HON. MARIO R. BRIONES** — LSPU President, Vice-Chairman

## 6. Table headers and relevant rows

Not a fee table. Name/title pairs as on the Administrative Officials plates:

| Title | Faculty Manual (March 2021) | Student Handbook (December 2021) |
| --- | --- | --- |
| University President | **DR. MARIO R. BRIONES** | **DR. MARIO R. BRIONES** |
| Vice President for Academic Affairs | DR. EDEN C. CALLO | DR. EDEN C. CALLO |
| Vice President for Administration | ENGR. BELTRAN P. PEDRIGAL, MSA | ENGR. BELTRAN P. PEDRIGAL, MSA |
| Vice President for Research Development and Extension | **DR. CORAZON N. SAN AGUSTIN** | **DR. ROBERT C. AGATEP** |

## 7. OCR text alongside visual evidence

PyMuPDF: `ocr_pymupdf_faculty_pdf011.txt`, `ocr_pymupdf_handbook_pdf018.txt`, `ocr_pymupdf_handbook_pdf016.txt`.

Chroma:

- `97e32a29-fa86-458c-9fe9-dba48f9605ce::6` — Faculty officials; names match the plate, then the same chunk continues into campus descriptions (`chroma_ocr_97e32a29_6.txt`)
- `cec01713-c1ba-4061-9404-ffaa1d8e70dd::10` — Handbook officials; names match the plate (`chroma_ocr_cec01713_10.txt`)

OCR of the president’s name is consistent with the photographs/plates. The VP-RDE conflict is in the original pages, not an OCR error.

## 8. Proposed reference answer (from pending dataset — not gold)

> The LSPU Faculty Manual 2020 (Administrative Officials, page 11) and the LSPU Student Handbook (Administrative Officials, page 18) both name DR. MARIO R. BRIONES as University President. A human must confirm this is still current; these source lists are not dated as a 2026 directory. Do not treat the conflicting VP-for-Research names in those same lists as part of this answer.

## 9. Evidence supporting / not supporting that proposed answer

Supports as a **historical naming** in 2021 manuals: both plates print **DR. MARIO R. BRIONES, University President**.

Does **not** support the question word **current**:

- Faculty list dated **March 2021** (manual titled 2020).
- Handbook list dated **December 2021**.
- No “as of 2026” or incumbent-verification language.
- The two 2021 lists already disagree on VP-RDE (**San Agustin** vs **Agatep**), which shows these directories went stale relative to each other within the same calendar year.

## 10. Ambiguities, conflicts, and missing information

- President name agrees across both 2021 sources; VP-RDE does not.
- No 2022–2026 BOR resolution, appointment paper, or current LSPU directory is in the isolated evaluation corpus used for this review.
- A weaker, time-stamped statement (“named as University President in the March 2021 Faculty Manual and December 2021 Student Handbook”) is supportable. A “current president” assertion is not.

**This question requires an up-to-date authoritative source** (for example a 2026 Citizen's Charter officials page, a current BOR/university directory, or an official appointment issuance). Those sources were not found in the three PDFs inspected for this case.

## 11. Recommended human decision: **insufficient evidence**

Do not approve a gold answer that states who the current president is. Keep `proposed_reference_answer` null, or replace it only with a dated-source statement that does not claim currency. Do not use VP-RDE names in this answer.

The pending draft’s caution (“a human must confirm this is still current”) is correct; this inspection did **not** confirm currency.

### Questions to resolve before approving a reference answer

1. Is a 2026 (or later) authoritative source available outside these two manuals?
2. If no: leave the case **insufficient evidence** / `proposed_reference_answer: null`?
3. If yes: which document/page becomes the gold citation?
4. If the human still wants a handbook-grounded answer: accept only a **dated** wording (named in 2021 manuals), never “current”?
5. Confirm the VP-RDE conflict is recorded as staleness evidence and is **not** part of the president answer?
