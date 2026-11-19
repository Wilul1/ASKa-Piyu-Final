# Citation evidence — aq_01_tor_fee

**Recommended human decision: revise citation evidence**

Do not treat this file as gold. `gold_citation_ids` are not assigned.

## Case

| Field | Value |
| --- | --- |
| Case ID | `aq_01_tor_fee` |
| Question | How much does it cost to get a copy of my Transcript of Records? |
| Approved reference answer | According to the Citizen's Charter 2026, 1st Edition, a Transcript of Records costs ₱75.00 per page for undergraduate students and ₱150.00 per page for graduate students. |
| Answer null? | no |

## Claim 1 — Undergraduate TOR ₱75.00 per page

| Field | Value |
| --- | --- |
| Claim | Undergraduate Transcript of Records fee is ₱75.00 per page |
| Exact source passage (PDF visual, PDF index 13 / printed 5) | Under **FEES TO BE PAID**, heading **Transcript of Records**, line **Undergrad students P75.00/page** |
| Source document ID (Chroma) | `da4a1832-7242-4e94-8ba6-bc0b9f2294bf` |
| Source title / edition | Citizen's Charter 2026, 1st Edition (`Laguna State Polytechnic University-CC_2026-1st Edition.pdf`) |
| Chroma chunk ID | `da4a1832-7242-4e94-8ba6-bc0b9f2294bf::1` |
| Chroma page metadata | `page` / `page_start` = **12**; `page_end` unavailable (`null` in extraction) |
| PDF page index | **13** (fee line). Service title on PDF **12** |
| Printed page | **5** (fee line). Service title printed **4** |
| Student-visible citation ID | Expected `da4a1832-7242-4e94-8ba6-bc0b9f2294bf::1` **if** `metadata.chunk_id` is stamped (it is in the extraction). Not live-verified. |
| Student-visible page | Would show Chroma **12** (and likely pages **12–13** via charter +1 soft-extend), not printed 5 |
| Resolvable by current implementation? | **Partially.** The chunk ID is a valid citation identity. The PDF visual clearly marks the amount as TOR. The **stored chunk body does not.** |

Chunk body fee line (not gold; OCR mash):

> Fees: P75.00/page; P150/page; P30.00/page; P137; Second copy of diploma: P100.00

That line does **not** attach P75.00/page to “Transcript of Records.” P137 is OCR of Form **F137**, not a fee. Certifications, authentication, and diploma must **not** be used as TOR evidence.

## Claim 2 — Graduate TOR ₱150 per page

| Field | Value |
| --- | --- |
| Claim | Graduate Transcript of Records fee is ₱150/page (approved draft writes ₱150.00) |
| Exact source passage (PDF visual, PDF index 13 / printed 5) | Under **Transcript of Records**, line **Graduate students P150/page** |
| Same document / chunk / chroma page as Claim 1 | yes |
| PDF page index | **13** |
| Printed page | **5** |
| Resolvable? | Same as Claim 1: identity yes; chunk body does not isolate graduate TOR from other mashed amounts. |

## What must not be cited as TOR

| Item | PDF location | Amount | Include as TOR evidence? |
| --- | --- | --- | --- |
| Certifications (incl. CAV, F137, Copy of Grades, …) | PDF 13 / printed 5 | P30.00/page | **No** |
| Authentication | PDF 13–14 / printed 5–6 | P30.00/page | **No** |
| 2nd copy of Diploma | PDF 14 / printed 6 | P100.00 | **No** |

Only one Chroma chunk holds this service. There is **no** separate chunk whose body contains only the TOR rows.

## Mismatches

- Chroma page **12** ≠ PDF fee table **13–14** ≠ printed **5–6**.
- Student label would read approximately “LSPU Citizen's Charter, Issuance of Transcript of Records/…, pages 12–13.”
- Viewer opens PDF index 12, not printed page 5. Soft-extend can include PDF 13 (where TOR lines are). PDF 14 is outside that default range.
- V1 lexical overlap can treat this same chunk as support for diploma or certification questions.
- Live retrieval / display was **not** run this phase.

## Recommended human decision: **revise**

Accept the PDF visual as TOR evidence. Do **not** silently treat the mashed Chroma fee string as a clean TOR passage. Decide whether `da4a1832-7242-4e94-8ba6-bc0b9f2294bf::1` is still the only acceptable `gold_citation_id` (best available citable unit) despite the mash and page-12 metadata. Do not invent a second citation ID for PDF page 13.
