# Citation evidence — aq_10_faculty_responsibilities

**Recommended human decision: revise citation evidence**

The Commitment list is in Faculty Manual 2020, Section III.A, PDF pages 16–17. The only Chroma chunk that contains that body is tagged Historical Development / page 13. **The chunk was not modified.**

## Case

| Field | Value |
| --- | --- |
| Case ID | `aq_10_faculty_responsibilities` |
| Question | What are the responsibilities of an LSPU faculty member? |
| Approved reference answer | According to the LSPU Faculty Manual 2020, Section III, A. Commitment of Faculty, faculty commitments include: treating teaching as a personal commitment, including professional maturity, sharing instructional resources, setting aside personal bias, and preparing for quality teaching; placing the learner at the center of the educative process, including respecting students, supporting growth, not ridiculing or condemning them, inspiring their best effort, grading without personal friendship or vested-group pressure, meeting individual needs, encouraging high individual goals, and keeping confidential student information unless required by authorized agency or law; sharing with parents the responsibility of shaping the student’s future, including cooperative relationships and keeping parents informed of academic progress and deficiencies; and serving as a vanguard of change through public service, research, extension, and community engagement. |
| Answer null? | no |

## Claim — Section III, A. Commitment of Faculty (PDF 16–17)

| Field | Value |
| --- | --- |
| Exact source passage | Heading **III. Commitment of the LSPU Faculty** / **A. Commitment of Faculty**, items 1.1–1.4, 2.1–2.8, 3.1–3.4, 4.1–4.3 on PDF 16–17 (printed pages 5–6 of 92). B. Code of Ethics is **excluded** from the approved answer. |
| Source document ID (Chroma) | `97e32a29-fa86-458c-9fe9-dba48f9605ce` |
| Source title / edition | LSPU Faculty Manual 2020 (header Date March 2021; Doc. LSPU-PM-LFM-01 Rev 0) |
| Chroma chunk ID | `97e32a29-fa86-458c-9fe9-dba48f9605ce::8` |
| Chroma title / section | `II. Historical Development of LSPU - Part 2` / `II. Historical Development of LSPU` |
| Chroma page metadata | `page` / `page_start` = **13**; `page_end` = **18** |
| PDF page index of **body** | **16–17** |
| PDF page index of **metadata heading** | **13** (Historical Development — does not contain this list) |
| Printed page of body | **5 of 92** and **6 of 92** |
| Printed page of metadata heading | **2 of 92** |
| Student-visible citation ID | Expected `97e32a29-fa86-458c-9fe9-dba48f9605ce::8` |
| Student-visible title | `_display_title` prefers `source_section` / `title` → **Historical Development of LSPU**, not “Commitment of Faculty” |
| Student-visible page | **13–18** (Chroma range), not printed 5–6 |
| PDF viewer target | `extract_citation_pages_pdf` uses the displayed page as **PDF index 13**, which is university history |

## Can the system identify the actual source pages 16–17?

**No.** It has no separate printed-page field and no body-based page repair. It will cite `::8` and open PDF page **13** (plus range through 18 if `page_end` is used). A student can receive the Commitment **excerpt** in `source_excerpt` / chunk text while the **label and viewer landing page** say Historical Development / page 13.

| Question | Answer |
| --- | --- |
| Is `::8` a resolvable citation_id? | **Yes** (identity). |
| Does that ID’s metadata point at Section III.A / PDF 16–17? | **No.** |
| Is there another chunk whose title/page are Commitment / 16–17? | **Not identified** in the extraction IDs used for this case. Not searched by inventing IDs. |
| Was the chunk modified? | **No.** |

## Recommended human decision: **revise**

A human must decide whether `97e32a29-fa86-458c-9fe9-dba48f9605ce::8` is acceptable gold **despite** wrong title/page, because it is the citable body, or whether citation evidence is insufficient until metadata is corrected in a **later, separate** ingestion change. This phase must not retitle or repage the chunk.
