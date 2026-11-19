# aq_01 — Transcript of Records fee

**Recommended human decision: revise**

This file is source-verification evidence only. It does not change the pending dataset, `labeling_status`, or `evaluation_ready`.

## 1. Original question

How much does it cost to get a copy of my Transcript of Records?

Pending case id: `aq_01_tor_fee` (`rag_benchmark_01`).

## 2. Source document name and version

- **Document:** Laguna State Polytechnic University Citizen's Charter 2026, 1st Edition
- **File:** `Laguna State Polytechnic University-CC_2026-1st Edition.pdf`
- **Path (unchanged):** `backend/data/documents/6c3d0f00-fd53-43be-943f-09e1e7ddbce4/Laguna State Polytechnic University-CC_2026-1st Edition.pdf`
- **PDF metadata:** 102 pages; created/modified `2026-03-31 16:11:42 +08:00`

## 3. Exact PDF page numbers

| What | PDF index (1-based) | Printed footer | Chroma `page` metadata |
| --- | --- | --- | --- |
| Service title, office, who may avail | 12 | **4** | 12 |
| Fee table: TOR, Certifications, Authentication heading | 13 | **5** | (same service; Chroma stored page 12) |
| Authentication amount + 2nd copy of Diploma + TOTAL | 14 | **6** | (same service; Chroma stored page 12) |

The pending dataset cites Charter page 12. That is the Chroma page and the PDF page where the **service starts**. The fee table itself is on PDF pages **13–14** (printed 5–6).

## 4. Original PDF page images

Inspected visually (not OCR-only):

- `visual_charter_pdf012_printed_footer_4.png`
- `visual_charter_pdf013_printed_footer_5_fees.png`
- `visual_charter_pdf014_printed_footer_6_fees_cont.png`

Shared renders: `../_pages/charter_pdfpage_012.png` through `_014.png`.

## 5. Exact supporting passage

Service title on PDF page 12, printed footer 4:

> 2. Issuance of Transcript of Records/Transfer Credentials/Certifications/CAV/Authenticated Documents
>
> This process provides description and series of steps for assisting the public in the issuance of the pertinent documents such as transcript of records, transfer of credentials, certifications, CAV, and authenticated documents.
>
> Office or Division: Registrar
>
> Who may avail: All (Walk-In students & Graduates)

Client step 2 on PDF page 13, printed footer 5, column **FEES TO BE PAID** (visual grouping):

> Transcript of Records
> - Undergrad students P75.00/page
> - Graduate students P150/page
>
> Certifications P30.00/page
> - Copy of Grades
> - F137
> - CAV
> - Certificate of Transfer
> - General Weighted Ave.
> - Subject description
> - SPES
> - Permit to Study
>
> Authentication

Continuation on PDF page 14, printed footer 6, same **FEES TO BE PAID** column:

> P30.00/page
> 2nd copy of Diploma P100.00
>
> TOTAL: Depends on the document

## 6. Table headers and relevant rows

Headers (PDF page 13): **CLIENT STEPS | AGENCY ACTIONS | FEES TO BE PAID | PROCESSING TIME | PERSON RESPONSIBLE**

Fee rows isolated from that column:

| Document / service | Amount | Applies to TOR? |
| --- | --- | --- |
| Transcript of Records — Undergrad students | **P75.00/page** | Yes — TOR undergraduate |
| Transcript of Records — Graduate students | **P150/page** | Yes — TOR graduate |
| Certifications (Copy of Grades, F137, CAV, Certificate of Transfer, GWA, Subject description, SPES, Permit to Study) | **P30.00/page** | No — certifications, including CAV |
| Authentication | **P30.00/page** (amount printed on next page under the Authentication heading) | No |
| 2nd copy of Diploma | **P100.00** | No |

No footnote on these pages assigns a different TOR amount. TOTAL is “Depends on the document”, not a flat TOR price.

## 7. OCR text alongside visual evidence

PyMuPDF text (same pages): `ocr_pymupdf_charter_pdf012.txt`, `_013.txt`, `_014.txt`.

Chroma isolated-eval OCR (`da4a1832-7242-4e94-8ba6-bc0b9f2294bf::1`, stored page 12): `chroma_ocr_da4a1832_1.txt`.

Chroma mashed the fee column into one string:

> Fees: P75.00/page; P150/page; P30.00/page; **P137**; Second copy of diploma: P100.00

Visual inspection: **P137 is not a fee**. It is OCR of **F137** (Form 137) under Certifications. The TOR heading is present on the page image and is missing from the mashed Chroma fee line.

## 8. Proposed reference answer (from pending dataset — not gold)

Quoted unchanged from `answer_quality_eval_dataset.pending_human_review.json`:

> The Citizen's Charter 2026 1st Edition service 'Issuance of Transcript of Records/Transfer Credentials/Certifications/CAV/Authenticated Documents' (Registrar, page 12) lists these fees: Undergraduate P75.00/page; Graduate P150/page; P30.00/page; P137; Second copy of diploma P100.00. A human must confirm on the PDF which of those lines is the Transcript of Records fee.

## 9. Evidence supporting / not supporting that proposed answer

Supports: the service exists; Registrar; undergraduate P75.00/page and graduate P150/page appear.

Does not support as written:

- It does not assign which line is TOR.
- It treats P30.00/page, P137, and diploma P100.00 as if they might be TOR.
- **P137 is an OCR error** for F137.
- Page 12 is the service start, not the fee table.

Visual grouping now does assign TOR: **P75.00/page undergraduate, P150/page graduate**.

## 10. Ambiguities, conflicts, and missing information

- Graduate line prints **P150/page** (no `.00`); undergraduate prints **P75.00/page**. Same unit (per page).
- The card covers TOR, transfer credentials, certifications, CAV, and authenticated documents. Fees are itemized; CAV is under Certifications at P30.00/page, not under TOR.
- No separate “transfer credentials” amount is printed.
- “All (Walk-In students & Graduates)” is who may avail the service, not a third TOR rate.
- This inspection does not check whether later BOR resolutions superseded the 2026 Charter amounts.

## 11. Recommended human decision: **revise**

Revise the pending proposed answer so TOR is only P75.00/page (undergraduate) and P150/page (graduate). Keep certifications/CAV/authentication/diploma as distinct non-TOR fees. Remove P137. Cite PDF pages 13–14 (printed 5–6) for the table, page 12 (printed 4) for the service title.

Draft for the reviewer (not written into the pending dataset, not gold):

> The Citizen's Charter 2026, 1st Edition, service “Issuance of Transcript of Records/Transfer Credentials/Certifications/CAV/Authenticated Documents” (Registrar) lists Transcript of Records at **P75.00/page for undergraduate students** and **P150/page for graduate students**. Those TOR amounts are separate from Certifications at P30.00/page (Copy of Grades, F137, CAV, Certificate of Transfer, GWA, Subject description, SPES, Permit to Study), Authentication at P30.00/page, and a 2nd copy of Diploma at P100.00.

### Questions to resolve before approving a reference answer

1. Accept visual grouping: TOR = undergrad P75.00/page and graduate P150/page?
2. Should the student-facing answer include both rates, or only undergraduate unless the question names graduate?
3. Should non-TOR fees (P30 certifications/CAV/authentication, P100 diploma) be omitted from the TOR answer?
4. Confirm P137 must not appear in any gold answer?
5. Which page number should gold citations use: Chroma 12, PDF 13–14, or printed 5–6?
