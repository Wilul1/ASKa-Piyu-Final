# Citation evidence — aq_04_dropping_fee_multi_document

**Recommended human decision: revise citation evidence**

Both sides of the fee conflict are independently identifiable as distinct citation IDs. Do not choose a winning rate. Do not assign `gold_citation_ids` in this phase.

## Case

| Field | Value |
| --- | --- |
| Case ID | `aq_04_dropping_fee_multi_document` |
| Question | How much does it cost to drop a subject? |
| Approved reference answer | Official LSPU sources list two different dropping fees and do not establish which amount is currently in force. The Citizen's Charter 2026 lists ₱30.00 per unit for new and transferee students. The Student Handbook 2021 requires a dropping fee of ₱20.00 per unit, citing LSPU BOR Resolution 1046, s.2012. Confirm the applicable fee with the Registrar before paying. |
| Answer null? | no |

The conflict-aware answer contains **two** independently supportable claims. A later gold set, if any, would need **both** citation IDs if Citation Accuracy is scored against that answer.

---

## Claim A — Charter ₱30.00 per unit (new and transferee)

| Field | Value |
| --- | --- |
| Exact source passage (PDF visual) | Service **8. Dropping of Subjects**. Who may avail: **New and Transferee Students**. FEES TO BE PAID: **30/unit**. TOTAL: **P30.00/unit**. |
| Source document ID (Chroma) | `da4a1832-7242-4e94-8ba6-bc0b9f2294bf` |
| Source title / edition | Citizen's Charter 2026, 1st Edition |
| Chroma chunk ID | `da4a1832-7242-4e94-8ba6-bc0b9f2294bf::97` |
| Chroma page metadata | `page` / `page_start` = **98**; `page_end` unavailable |
| PDF page index | **98** |
| Printed page | footer **90** |
| Student-visible citation ID | Expected `da4a1832-7242-4e94-8ba6-bc0b9f2294bf::97` if `chunk_id` is stamped |
| Student-visible page | Chroma **98** (not printed 90) |
| Independently citable? | **Yes**, distinct document and chunk from Claim B |
| Resolvable? | **Partially.** Identity and PDF page index align (98). Chunk **body** stores `Fees P30.00` **without `/unit`**. Who-may-avail “New and Transferee Students” is in the chunk. |

Do not cite Enrollment Advising (fee 60) on the same printed page as dropping.

---

## Claim B — Handbook ₱20.00 per unit (BOR 1046 s.2012)

| Field | Value |
| --- | --- |
| Exact source passage (PDF visual) | **4.3. A dropping fee of P20/unit is required. (LSPU BOR 1046, s.2012)** |
| Source document ID (Chroma) | `cec01713-c1ba-4061-9404-ffaa1d8e70dd` |
| Source title / edition | LSPU Student Handbook 2021 (Doc. LSPU-PM-LSH-01 Rev 0; Date December 2021) |
| Chroma chunk ID | `cec01713-c1ba-4061-9404-ffaa1d8e70dd::82` |
| Chroma page metadata | `page` / `page_start` = **39**; `page_end` = **40** |
| PDF page index | Fee sentence **40**; section start **39** |
| Printed page | Fee sentence **31 of 183**; section start **30 of 183** |
| Student-visible citation ID | Expected `cec01713-c1ba-4061-9404-ffaa1d8e70dd::82` |
| Student-visible page | Would show pages **39–40** (Chroma), not printed 31 |
| Independently citable? | **Yes** |
| Resolvable? | **Yes, as an identity.** The P20/unit sentence is in the chunk body verbatim. Displayed page 39 is the Chroma start, not the printed page. BOR 1046 PDF is **not** a separate citable document in this corpus (`null`). |

---

## Can the current system cite both?

| Question | Finding |
| --- | --- |
| Distinct `citation_id`s? | Yes. Different `document_id` and `chunk_index`. |
| Would V1 display both if both are retrieved? | Likely, if the generated answer mentions both 30 and 20 — lexical overlap hits both chunks. Not live-tested. |
| Would V2 display both? | Only if both chunks are in the retrieved allowlist **and** the verifier entails each claim. Not live-tested. |
| Merge/dedup risk? | `_sources_from_chunks` dedupes on `(title, path, page)` within one document. These are two documents. |

No winner is selected.

## Mismatches

- Charter chunk omits `/unit`; PDF visual has P30.00/unit.
- Handbook Chroma page **39** vs PDF fee page **40** vs printed **31**.
- Printed 90 is never shown for Charter PDF 98.

## Recommended human decision: **revise**

Keep both passages. Decide later whether gold is `{::97, ::82}` for the conflict-aware answer. Do not drop one ID as “wrong.” Flag that `::97`’s stored fee string is weaker than the PDF for the per-unit claim.
