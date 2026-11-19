# aq_10 — Faculty responsibilities

**Recommended human decision: revise**

This file is source-verification evidence only. It does not change the pending dataset, `labeling_status`, or `evaluation_ready`. **The knowledge-base chunk is not modified.**

## 1. Original question

What are the responsibilities of an LSPU faculty member?

Pending case id: `aq_10_faculty_responsibilities` (`rag_benchmark_10`).

## 2. Source document name and version

- **Document:** LSPU Faculty Manual 2020
- **File:** `LSPU Faculty Manual 2020.pdf`
- **Path:** `backend/data/documents/c67bd8c8-81cd-4c8c-bda1-4f7d2039a406/LSPU Faculty Manual 2020.pdf`
- **Header on every inspected page:** Title *LSPU Faculty Manual 2020*; Date **March 2021**; Doc. No. **LSPU-PM-LFM-01**; Revision **0**
- **PDF metadata:** 106 pages; created/modified `2021-06-21 15:00:32 +08:00`

## 3. Exact PDF page numbers

| What | PDF index | Printed header | Chroma metadata for chunk `::8` |
| --- | --- | --- | --- |
| **II. Historical Development of LSPU** (Wagan, campus integration) | **13** | **Page: 2 of 92** | `page` / `page_start` **13**; title matches this heading |
| Surrounding history continues | 14–15 | Pages 3–4 of 92 | — |
| **III. Commitment of the LSPU Faculty** / A. Commitment of Faculty (items 1–2.6) | **16** | **Page: 5 of 92** | body of chunk `::8` starts here |
| Commitment items 2.7–4.3 and start of B. Code of Ethics | **17** | **Page: 6 of 92** | rest of chunk `::8` body; `page_end` 18 |

Pending supporting passage cites Faculty Manual **page 13**. That PDF page is **not** the responsibilities list.

## 4. Original PDF page images

- `visual_faculty_pdf013_printed_page_2_history.png` — actual page 13
- `visual_faculty_pdf016_printed_page_5_commitment.png` — actual heading + list start
- `visual_faculty_pdf017_printed_page_6_commitment_cont.png` — list remainder

Surrounding pages 14–15 and 18 were also rendered under `../_pages/` (history ends; Code of Ethics continues). They confirm the Commitment chapter begins on PDF 16.

## 5. Exact supporting passages

### PDF page 13 / printed 2 of 92 — what Chroma *titles* as the source

Heading:

> **II. Historical Development of LSPU**

Body (opening, visual):

> The Laguna State Polytechnic University (LSPU) was initially established in 1952 as a provincial secondary school known as Baybay Provincial High School...

This page is institutional history. It does **not** list faculty responsibilities. It does **not** support the proposed answer body.

### PDF page 16 / printed 5 of 92 — actual heading and start of the list

> **III. Commitment of the LSPU Faculty**
>
> **A. Commitment of Faculty**
>
> 1. Teaching is a personal commitment of oneself to others with the intention to fulfill these obligations to satisfaction. As such, the professor/instructor shall:
> 1.1. exemplify mental, social, emotional and professional maturity where he/she recognizes his/her strengths as well as his/her weaknesses;
> 1.2. share ideas, instructional resources to fellow teachers especially those which have been found to be effective;
> 1.3. rise above personal feelings and biases in the interest of group action and group results; and
> 1.4. enhance his/her credibility in the classroom through quality teaching and adequate preparation.
>
> 2. Teaching as a commitment recognizes the centrality of the learner in the educative process. In recognition of this fact, the professor/instructor shall:
> 2.1. respect learners as person and value him/her as such;
> 2.2. enhance the learner’s capacity for growth and create the proper climate for that growth;
> 2.3 accept the learner as s/he is; when s/he shows ignorance, not ridicule him/her, when s/he differs, not to reject him/her, and when s/he is proved wrong, not to condemn him/her;
> 2.4. inspire the best effort from his/her students because their standard of performance is in themselves the motivation to do one’s best;
> 2.5. deviate from the influence of personal friendship, pressure from vested groups and consider only the achievement of students in giving grades;
> 2.6. recognize the differences among students and seek to meet their

### PDF page 17 / printed 6 of 92 — remainder

> individual needs;
> 2.7. encourage students to formulate and work for high individual goals of their physical, intellectual, creative, socio-emotional and spiritual endowments; and
> 2.8. respect the right of every student to withhold confidential information unless required by authorized agency or by law.
>
> 3. The professor /instructor shall share with parents the responsibility of shaping the student’s future and act towards socially acceptable ends. In recognition of this, the professor/instructor shall:
> 3.1. establish friendly and cooperative relationships with the parents;
> 3.2. provide the parents with information that shall serve the best interests of their children and to be discreet about information received from parents;
> 3.3. keep parents informed about the academic progress/ performance of their children; and
> 3.4. exercise tact and utmost sincerity in informing the parents about their children’s academic deficiencies and shortcomings.
>
> 4. The teacher as a vanguard of change should be responsible in the development of the country and its people. In recognition of this, professor/instructor shall:
> 4.1. recognize that the University belongs to the people, therefore, strives to serve the public with genuine concern and dedication;
> 4.2. conduct innovative research, initiate sustainable community extension activities, and assume leadership roles; and
> 4.3. discuss national concerns in the community in order to transform the lives of the people especially the poor and the disadvantaged.
>
> **B. Code of Ethics**
>
> The officials, faculty, and personnel of the Laguna State Polytechnic University shall employ the Code of Ethics to set appropriate guides for ethical conduct.

## 6. Table headers and relevant rows

Not a fee/status table. Numbered list under **III. Commitment of the LSPU Faculty > A. Commitment of Faculty**, items 1–4 (1.1–1.4, 2.1–2.8, 3.1–3.4, 4.1–4.3), then **B. Code of Ethics**.

## 7. OCR text alongside visual evidence

PyMuPDF: `ocr_pymupdf_faculty_pdf013.txt`, `_016.txt`, `_017.txt`.

Chroma chunk `97e32a29-fa86-458c-9fe9-dba48f9605ce::8`: `chroma_ocr_97e32a29_8.txt`

Mismatch (do not “fix” the chunk in this phase):

| Field | Stored value | Visual PDF |
| --- | --- | --- |
| `title` | II. Historical Development of LSPU - Part 2 | Matches PDF **page 13** heading |
| `source_section` / `chapter` | II. Historical Development of LSPU | Same |
| `page` / `page_start` | 13 | Page 13 is history, not this body |
| `page_end` | 18 | Commitment is 16–17; Code of Ethics continues 17–18 |
| **body text** | “Teaching is a personal commitment…” through Code of Ethics start | Matches PDF **pages 16–17**, not 13 |

Extraction aligned the previous heading/page with the next chapter’s body.

## 8. Proposed reference answer (from pending dataset — not gold)

> The Faculty Manual 2020 extraction at page 13 lists faculty obligations including: treat teaching as a personal commitment; exemplify professional maturity and share instructional resources; respect learners and avoid ridicule; grade without personal friendship or vested-group pressure; meet individual student needs; keep confidential student information unless required by authorized agency or law; and share with parents the responsibility of shaping the student's future, including keeping parents informed of academic progress. Confirm the PDF section title; the chunk metadata title does not match this body.

## 9. Evidence supporting / not supporting that proposed answer

**Page 13 does not support the proposed answer.** Page 13 is Historical Development.

**Pages 16–17 do support the listed obligations**, under the heading **III. Commitment of the LSPU Faculty**, not “responsibilities” and not “Historical Development”.

The pending summary is incomplete relative to the source: it omits 4.1–4.3 (public service, research/extension, community) and does not say whether Code of Ethics is in or out of scope.

Whether “Commitment of Faculty” is an acceptable gold heading for a question that says “responsibilities” is a human wording decision.

## 10. Ambiguities, conflicts, and missing information

- Chunk title/body/page mismatch is confirmed. Knowledge-base chunk left unchanged.
- No heading on pages 13–17 is literally “Faculty Responsibilities”.
- Later Faculty Manual chapters (official time, teaching load, attendance) are other kinds of duties; this case’s supporting chunk is the Commitment list only.
- Code of Ethics begins on page 17 and continues after the Commitment list.

## 11. Recommended human decision: **revise**

Revise the citation from page 13 / Historical Development to **PDF pages 16–17**, heading **III. Commitment of the LSPU Faculty**. Keep the obligation list if the human accepts “commitment” as answering “responsibilities”. Do not treat page 13 as supporting text. Do not modify the KB chunk in this phase.

Draft for the reviewer (not gold):

> The LSPU Faculty Manual 2020, **III. Commitment of the LSPU Faculty**, **A. Commitment of Faculty** (printed pages 5–6 of 92; PDF pages 16–17) states that teaching is a personal commitment and lists obligations of the professor/instructor, including professional maturity and sharing instructional resources; respecting learners and not ridiculing them; grading without personal friendship or vested-group pressure; meeting individual needs; keeping confidential student information unless required by authorized agency or law; sharing with parents the responsibility of shaping the student’s future; and serving the public through concern, research, extension, and community engagement. The stored Chroma chunk for this text is titled “II. Historical Development of LSPU - Part 2” and tagged page 13; that page is university history and does not contain this list.

### Questions to resolve before approving a reference answer

1. Does “Commitment of the LSPU Faculty” count as an answer to “responsibilities”, or is a different chapter required?
2. Include all of A.1–A.4, or the pending shorter summary, or also B. Code of Ethics?
3. May gold cite PDF 16–17 while retrieval still returns chunk `::8` tagged page 13?
4. Confirm the KB chunk stays unmodified in this evaluation phase?
