# Phase 2B — Human review evidence index

Prepared 2026-11-04. **Stop and wait for human review.**

This directory is read-only inspection output. It does **not** modify:

- `answer_quality_eval_dataset.pending_human_review.json`
- `labeling_status` / `evaluation_ready`
- source PDFs, raw OCR, or Chroma
- chatbot behavior, RAGAS, or evaluation runs

Reviewer drafts in the case files are **not gold**. Do not promote cases until a human decides.

## Source PDFs (all found, left unchanged)

| Document | Path | Pages | Header / PDF date |
| --- | --- | --- | --- |
| Citizen's Charter 2026, 1st Edition | `backend/data/documents/6c3d0f00-fd53-43be-943f-09e1e7ddbce4/Laguna State Polytechnic University-CC_2026-1st Edition.pdf` | 102 | PDF created 2026-03-31 |
| LSPU Student Handbook 2021 | `backend/data/documents/d9bf05ce-fcab-4629-ad4c-4f869481189f/LSPU Student Handbook.pdf` | 198 | Date December 2021; Doc. LSPU-PM-LSH-01 Rev 0 |
| LSPU Faculty Manual 2020 | `backend/data/documents/c67bd8c8-81cd-4c8c-bda1-4f7d2039a406/LSPU Faculty Manual 2020.pdf` | 106 | Date March 2021; Doc. LSPU-PM-LFM-01 Rev 0 |

No listed source PDF was missing. BOR Resolution 1046 s.2012 (cited by the Handbook dropping fee) was **not** in the three PDFs and was not located as a separate file. No 2026 president directory was found.

## Case folders

| Case | Decision | Evidence |
| --- | --- | --- |
| aq_01 TOR fee | **revise** | `aq_01_tor_fee/` |
| aq_04 dropping fee | **revise** (do not pick a winner) | `aq_04_dropping_fee/` |
| aq_08 retention | **revise** | `aq_08_retention_policy/` |
| aq_10 faculty responsibilities | **revise** (do not modify KB chunk) | `aq_10_faculty_responsibilities/` |
| aq_12 current president | **insufficient evidence** for “current” | `aq_12_current_president/` |

Each folder contains `EVIDENCE.md`, `evidence.json`, page-image copies, PyMuPDF text, and Chroma OCR excerpts. Shared renders: `_pages/`.

## Conflicts that require a human decision

1. **aq_01** — Visual table now isolates TOR (P75.00/page undergrad, P150/page graduate). Pending answer still mixes certifications/CAV/diploma and OCR **P137** (actually **F137**). Human must approve a TOR-only revised gold.
2. **aq_04** — Real conflict is **P30.00/unit** (Charter 2026; who may avail: New and Transferee Students) vs **P20/unit** (Handbook 2021 / BOR 1046 s.2012). Flat P30.00 was OCR. Do not pick a winner from this pack.
3. **aq_08** — 4.3 says **more than 75%** and exempts **only nine** final grades; the table says **75% or more** with **nine academic units or more** enrolled. Dismissal from the College ≠ permanent disqualification from the University (100%).
4. **aq_10** — Cited page 13 is Historical Development. The proposed body is **III. Commitment of the LSPU Faculty** on PDF 16–17. Chunk `97e32a29-…::8` title/page vs body mismatch; leave the chunk unchanged.
5. **aq_12** — Both 2021 plates name **DR. MARIO R. BRIONES**, University President. VP-RDE already disagrees (San Agustin vs Agatep). Neither source establishes **current** 2026 status.

## Questions that must be resolved before approving each reference answer

Copied from the case files. Pending dataset stays unlabeled until these are answered.

### aq_01
1. Accept visual grouping: TOR = undergrad P75.00/page and graduate P150/page?
2. Both rates in the student-facing answer, or undergraduate only unless graduate is named?
3. Omit non-TOR fees from the TOR gold answer?
4. Confirm P137 must not appear in gold?
5. Cite Chroma page 12, PDF 13–14, or printed 5–6?

### aq_04
1. Accept Charter **P30.00/unit** from the page image (not flat P30.00)?
2. Does “Who may avail: New and Transferee Students” limit the Charter fee?
3. Is Handbook P20/unit still in force, superseded, or unknown?
4. Gold = conflict statement, single fee, or insufficient evidence?
5. Page numbers: PDF 98 vs printed 90; PDF 40 vs Chroma 39?

### aq_08
1. Trigger **more than 75%** (4.3), **75% or more** (table), or both quoted?
2. Nine units: exemption, enrollment condition, or both?
3. Distinguish dismissal from the College vs permanent disqualification from the University?
4. Include INC exclusion, Sec. 5, and/or Sec. 7?
5. Cite PDF 35, PDF 36, printed 26–27, or Chroma page 35?

### aq_10
1. Does “Commitment of the LSPU Faculty” answer “responsibilities”?
2. Include all of A.1–A.4, the pending shorter summary, or also B. Code of Ethics?
3. May gold cite PDF 16–17 while retrieval still returns chunk `::8` tagged page 13?
4. Confirm the KB chunk stays unmodified?

### aq_12
1. Is a 2026 or later authoritative source available outside these two manuals?
2. If no: leave `proposed_reference_answer` null?
3. If yes: which document/page is gold?
4. If handbook-grounded only: dated 2021 wording, never “current”?
5. Confirm VP-RDE conflict is staleness evidence only?
