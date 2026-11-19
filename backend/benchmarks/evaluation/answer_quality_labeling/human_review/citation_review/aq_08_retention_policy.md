# Citation evidence — aq_08_fail_more_than_75_percent

**Recommended human decision: revise citation evidence**

Keep each statement tied to its own passage. Do not merge 4.3 and the table into one undifferentiated citation.

## Case

| Field | Value |
| --- | --- |
| Case ID | `aq_08_fail_more_than_75_percent` |
| Question | What happens if I fail more than 75% of my units? |
| Approved reference answer | (Phase 2D promoted draft: both 4.3 and table wordings; nine-unit in two contexts; INC exclusion; dismissal vs permanent disqualification; exact-75% flagged; confirm with Registrar.) |
| Answer null? | no |

Shared document: LSPU Student Handbook 2021. Chroma document ID `cec01713-c1ba-4061-9404-ffaa1d8e70dd`.

---

## Claim 1 — Section 4.3: more than 75%; INC exclusion; nine-unit exemption; dismissal from the College

| Field | Value |
| --- | --- |
| Exact source passage (PDF visual, PDF 35 / printed 26 of 183) | **4.3. Dismissal.** Any student who fails in **more than seventy-five percent (75%)** of the total academic units enrolled shall be subject for **dismissal from the College**; provided that an **incomplete grade shall not be included** in the computation of earned units; provided further, that this **shall not apply to students who receive final grades in only nine academic units**. |
| Chroma chunk ID | `cec01713-c1ba-4061-9404-ffaa1d8e70dd::67` |
| Chunk title / section | Dismissal / `4.3 > Dismissal` |
| Chroma page | `page` / `page_start` / `page_end` = **35** |
| PDF page index | **35** |
| Printed page | **26 of 183** |
| Student-visible citation ID | Expected `cec01713-c1ba-4061-9404-ffaa1d8e70dd::67` |
| Student-visible page | **35** (not printed 26) |
| Resolvable? | **Yes, as identity and as passage.** Chunk body matches 4.3. Displayed page 35 is the PDF index, not the printed number. |

Chunk `cec01713-c1ba-4061-9404-ffaa1d8e70dd::66` is **4.1 Warning / 4.2 Probation only**. It does **not** support the 75% dismissal claims. Do not treat retrieval `relevant_ids` that include `::66` as automatic gold for this answer.

---

## Claim 2 — Table: 75% or more; nine academic units or more; Dismissal from the College; not allowed to enroll

| Field | Value |
| --- | --- |
| Exact source passage (PDF visual, PDF 36 / printed 27 of 183) | Headers: Percentage (%) of failure \| Number of units enrolled \| Status \| Allowable load for the following semester. Row: **75% or more** \| **Nine academic units or more** \| **Dismissal from the College** \| **not allowed to enroll** |
| Chroma chunk ID | `cec01713-c1ba-4061-9404-ffaa1d8e70dd::69` |
| Chunk title / section | **Disqualification Exemption** / `Sec. 7 > Disqualification Exemption` (title does **not** name the table) |
| Chroma page | `page` / `page_start` = **35**; `page_end` = **36** |
| PDF page index | Table on **36** |
| Printed page | **27 of 183** |
| Student-visible citation ID | Expected `cec01713-c1ba-4061-9404-ffaa1d8e70dd::69` |
| Student-visible page | **35–36** |
| Resolvable? | **Partially.** Identity exists. Body contains a **column-scrambled** OCR table plus Sec. 7 text. Visual table is the authoritative passage. |

---

## Claim 3 — Permanent disqualification from the University at 100%

| Field | Value |
| --- | --- |
| Exact source passage (PDF visual, PDF 36 / printed 27 of 183) | Row: **100%** \| (units blank) \| **Permanent disqualification from the University** \| (load blank) |
| Chroma chunk ID | Same `cec01713-c1ba-4061-9404-ffaa1d8e70dd::69` |
| PDF / printed / chroma | Same as Claim 2 |
| Resolvable? | Same as Claim 2. This status is **not** in chunk `::67` (4.3). |

Sec. 7 on PDF 35 (permanent disqualification **exemption** for unauthorized dropping) is in `::69` as well. It is **not** a supporting passage for “100% → permanent disqualification.” Do not use Sec. 7 as gold for Claim 3.

---

## Claim-to-chunk map (for a later gold decision)

| Statement | PDF / printed | Chunk | Clean in chunk body? |
| --- | --- | --- | --- |
| more than 75% | 35 / 26 | `::67` | Yes |
| incomplete grade excluded | 35 / 26 | `::67` | Yes |
| only nine academic units exemption | 35 / 26 | `::67` | Yes |
| dismissal from the College (4.3) | 35 / 26 | `::67` | Yes |
| 75% or more | 36 / 27 | `::69` | Present, OCR-scrambled |
| nine academic units or more (enrolled) | 36 / 27 | `::69` | Present, OCR-scrambled |
| not allowed to enroll | 36 / 27 | `::69` | Present, OCR-scrambled |
| 100% permanent disqualification from the University | 36 / 27 | `::69` | Present, OCR-scrambled |

## Recommended human decision: **revise**

A later gold set, if approved, should distinguish `::67` (4.3 prose) from `::69` (table / 100%). Do not gold `::66` for the 75% dismissal answer. Decide whether mashed `::69` is acceptable gold or insufficient until a cleaner table chunk exists. Do not invent a new chunk ID for PDF 36.
