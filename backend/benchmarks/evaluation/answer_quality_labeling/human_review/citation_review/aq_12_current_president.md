# Citation evidence — aq_12_university_president

**Recommended human decision: insufficient citation evidence**

The approved reference answer is **JSON `null`**. Do **not** create `gold_citation_ids` for a current-president answer from these 2021 lists.

## Case

| Field | Value |
| --- | --- |
| Case ID | `aq_12_university_president` |
| Question | Who is the current LSPU president? |
| Approved reference answer | `null` |
| Requires up-to-date authoritative source | yes |

These two passages establish only that **Dr. Mario R. Briones was named University President in the 2021 manuals.** They do **not** establish who is president in 2026.

---

## Dated reference 1 — Faculty Manual, March 2021

| Field | Value |
| --- | --- |
| Claim (dated only; not a current-president gold claim) | DR. MARIO R. BRIONES, University President, on the Administrative Officials plate |
| Exact source passage | **ADMINISTRATIVE OFFICIALS** / **DR. MARIO R. BRIONES** / **University President** |
| Source document ID (Chroma) | `97e32a29-fa86-458c-9fe9-dba48f9605ce` |
| Source title / edition | LSPU Faculty Manual 2020; header Date **March 2021**; Doc. LSPU-PM-LFM-01 Rev 0 |
| Chroma chunk ID | `97e32a29-fa86-458c-9fe9-dba48f9605ce::6` |
| Chroma page | **11** (`page_end` 12) |
| PDF page index | **11** |
| Printed page | **vii of 92** |
| Student-visible citation ID | Expected `97e32a29-fa86-458c-9fe9-dba48f9605ce::6` |
| Student-visible page | **11** (not printed vii) |
| Establishes current 2026 president? | **No** |
| Gold for the approved (null) answer? | **No. Do not assign.** |
| Independently citable as a 2021 naming? | Yes, as an identity, if a different dated question were asked. Not this question’s gold. |

Chunk `::6` also concatenates campus descriptions after the officials list.

---

## Dated reference 2 — Student Handbook, December 2021

| Field | Value |
| --- | --- |
| Claim (dated only; not a current-president gold claim) | DR. MARIO R. BRIONES, University President, on the Administrative Officials plate |
| Exact source passage | **ADMINISTRATIVE OFFICIALS** / **DR. MARIO R. BRIONES** / **University President** |
| Source document ID (Chroma) | `cec01713-c1ba-4061-9404-ffaa1d8e70dd` |
| Source title / edition | LSPU Student Handbook 2021; header Date **December 2021**; Doc. LSPU-PM-LSH-01 Rev 0 |
| Chroma chunk ID | `cec01713-c1ba-4061-9404-ffaa1d8e70dd::10` |
| Chroma page | **18** |
| PDF page index | **18** |
| Printed page | **9 of 183** |
| Student-visible citation ID | Expected `cec01713-c1ba-4061-9404-ffaa1d8e70dd::10` |
| Student-visible page | **18** (not printed 9) |
| Establishes current 2026 president? | **No** |
| Gold for the approved (null) answer? | **No. Do not assign.** |
| Independently citable as a 2021 naming? | Yes, as an identity. Not this question’s gold. |

---

## Staleness evidence (not part of a president gold set)

VP for Research Development and Extension already disagrees: **Dr. Corazon N. San Agustin** (Faculty `::6`, March 2021) vs **Dr. Robert C. Agatep** (Handbook `::10`, December 2021). That conflict is recorded only to show the directories are stale. Do not gold-cite either VP name for this question.

## Evaluation implication

Citation-set precision/recall **must not** be scored for this case until a non-null current-president answer and matching gold IDs exist. Empty gold is excluded by `citation_metrics_from_outcome`. Leave gold unset.

## Recommended human decision: **insufficient citation evidence**

Do not mint gold citations from `::6` or `::10` for “who is the current president.” Record the two 2021 plates as dated, non-current evidence only.
