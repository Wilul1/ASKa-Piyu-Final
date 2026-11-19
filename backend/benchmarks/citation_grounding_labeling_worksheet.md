# Citation Grounding V2 — Stage 2 Human Labeling Worksheet

Source benchmark: `backend/benchmarks/citation_grounding_benchmark.json` (12 cases, `created: 2026-09-17`).

This worksheet is a **proposed labeling instrument**, not a labeling decision. No gold values exist yet.
`gold_supporting_chunk_ids`, `evidence_equivalence_groups`, supported/unsupported verdicts, distractor
calls, and conflict adjudication are **not populated anywhere in this document** — every such field below
is a blank form field for the two independent human labelers (and, on disagreement, the adjudicator) to
fill in per `labeling_methodology.process` in the benchmark file.

## How to read this worksheet

- **Citation identity** is always `result.sources[].citation_id` (e.g.
  `<document_id>::<chunk_index>` or `faq:<uuid>::<chunk_index>`), never bare `document_id`. Two
  citation_ids can share a document_id — they are still distinct evidence instances and must be
  labeled separately. See benchmark `labeling_methodology.citation_identity_definition`.
- **Evidence excerpts are withheld in this worksheet.** The benchmark's own
  `labeling_methodology.restricted_content_policy` states that none of the source dumps captured
  per-chunk audience/restriction metadata, so audience (public vs. faculty-only/restricted) is
  uncertain for every case, and the project's own convention is to fail closed — ID/title/location
  only, never full chunk text — rather than assume public. This worksheet follows that same
  convention for every candidate and displayed citation below, even where the underlying seed JSON
  file (e.g. `_smoke_grade.json`) happens to contain a `source_excerpt` string. Human labelers doing
  the actual adjudication will need to open the source documents (or an authorized, audience-checked
  viewer) directly rather than rely on excerpts pasted into this sheet.
- **"Claims to review" splits are mechanical, not gold.** They are a plain sentence/bullet
  decomposition of whichever answer text was actually captured, to give labelers a checklist
  granularity. They are not an entailment judgment, not a correctness judgment, and must not be
  treated as gold by any future script.
- **Any note prefixed "CONTEXT NOTE (not gold)"** reproduces a judgment already recorded in the
  benchmark JSON itself (e.g. gate3's scope-conflict note) so labelers have it as background — it is
  quoted from the existing file, not a new decision made in this pass, and the benchmark JSON itself
  already labels it non-gold.
- Blank fields (`[ ]`, `____`) are for the human labeler to fill in. Do not pre-fill them.

Status legend used below:
- **REPRODUCIBLE STANDALONE** — question can be replayed on its own via
  `scripts/citation_grounding_baseline.py` without needing prior conversation history.
- **NON-REPRODUCIBLE STANDALONE** — replaying the question alone would score a different (context-free)
  turn than the one actually captured; conversation history was not recorded in the source dump.
- **ANSWER TEXT: COMPLETE** — the full answer string was captured in the cited seed artifact.
- **ANSWER TEXT: TRUNCATED SNIPPET ONLY** — only a short snippet (`answer_snip`/`snip`) was captured;
  the full answer text does not exist in any reviewed seed artifact.
- **EVIDENCE INCOMPLETE — REQUIRES AUTHORIZED SOURCE LOOKUP** — per instruction, used wherever a seed
  artifact does not contain enough evidence to adjudicate a case; nothing is invented to fill the gap.

---

## Case 1: `gate3_grading_gwa`

- **CATEGORY:** Grading / GWA (worked example), scope-conflict case
- **PROVENANCE:** `aska_cert_gate3.json` + `_smoke_grade.json` (both reviewed directly for this worksheet)
- **QUESTION:** "What is the passing grade and how is GWA computed?"
- **USER ROLE:** Not recorded in either source dump.
- **REPRODUCIBILITY STATUS:** REPRODUCIBLE STANDALONE (`is_followup: false`)

**FINAL ANSWER** (`aska_cert_gate3.json.final_answer`, ANSWER TEXT: COMPLETE):
> "The available source lists individual categories/ranges, but it does not explicitly state a single overall boundary for that classification."

**RAW ANSWER** (`aska_cert_gate3.json.raw_groq` — the pre-classification-safety-override model
output; `classification_safety_activated: true` and `raw_invented_global: true` are recorded in the
same dump, meaning the system did NOT show this raw text to the user and displayed FINAL ANSWER
above instead). Reproduced here for provenance only, ANSWER TEXT: COMPLETE:
> "The LSPU grading system uses a numeric scale where **5.00** represents the highest grade. According to the Undergraduate Grading System, the grade scale is: [...1.00–5.00 scale as listed in the Undergraduate Grading System chunk...] So while the documents don't explicitly label a single "passing grade," the scale shows that **anything above 69 (i.e., starting at 70)** is considered passing, since 69 and below is classified as Failed. **How GWA (General Weighted Average) is computed:** Cumulative GWA is defined as *the weighted average of the grades in all academic courses taken in a given semester*... Grade "4" (conditional failure) is used as an actual grade when computing a student's GWA... Grade "5" (removal grade) is included in the computation of the GWA together with the grade the student earns after re-enrolling and passing the course."

CONTEXT NOTE (not gold): RAW ANSWER's opening sentence ("5.00 represents the highest grade") appears
inverted relative to the Undergraduate Grading System chunk, which lists 1.00 as the highest
(Excellent) and 5.00 as Failed. This is flagged here only because it is visibly present in the raw
seed text — it is not an adjudicated finding and must be verified by the human labeler against the
actual chunk, not accepted from this note.

**CANDIDATE CITATIONS** (evidence excerpts withheld — see "How to read this worksheet"):

Full-ID candidates captured in `aska_cert_gate3.json.retrieved_grading` / `_smoke_grade.json`:

| citation_id | title | document/source | page/section |
|---|---|---|---|
| `faq:0598f9eb-e5c8-4e79-a1f5-da97ae6b1702::0` | Undergraduate Grading System | LSPU Student Handbook.pdf (document_id `30875c07-409e-45ea-989e-3315a85608c1`) | derived FAQ bullet article, no page captured |
| (no citation_id captured — document_id only: `30875c07-409e-45ea-989e-3315a85608c1`) | Grading System | LSPU Student Handbook.pdf | Undergraduate Academic Policies > Article 7 > Sec. 1 |
| (no citation_id captured — document_id only: `30875c07-409e-45ea-989e-3315a85608c1`) | Grading System | LSPU Student Handbook.pdf | Graduate Studies > Article 12 > Sec. 6 (Comprehensive Examination Guidelines) |

Title-only candidates (no id or text captured in any reviewed seed artifact —
`retrieved_titles` in `aska_cert_gate3.json`, ID NOT CAPTURED IN SEED ARTIFACT):
Completion of INC/Removal – Online System; References and Resources; No Final Examination;
System Information Registration/Modification (Manual Process); Modified Grading Policy;
Change/Rectification of Student Grades; "The awardee obtained substantive academic and non-academic".

**V1 DISPLAYED CITATIONS** (from `_smoke_grade.json`, matches benchmark's `v1_displayed_citation_ids`):

| citation_id | title |
|---|---|
| `4a7b432a-03a1-4f58-beac-1da63681e734::92` | Completion of INC/Removal – Online System |
| `4a7b432a-03a1-4f58-beac-1da63681e734::89` | References and Resources |
| `faq:0598f9eb-e5c8-4e79-a1f5-da97ae6b1702::0` | Undergraduate Grading System |
| `30875c07-409e-45ea-989e-3315a85608c1::96` | Grading Policy |
| `30875c07-409e-45ea-989e-3315a85608c1::100` | Policy on Grades of "4" and "5" |
| `30875c07-409e-45ea-989e-3315a85608c1::99` | Cumulative GWA |
| `30875c07-409e-45ea-989e-3315a85608c1::98` | GWA |

**CLAIMS TO REVIEW** (split of FINAL ANSWER; for HUMAN REVIEW ONLY, not gold):

1. The available source lists individual grading categories/ranges.
2. The available source does not explicitly state a single overall passing-grade boundary.

SUPPORTED? [ ] Yes  [ ] No
SUPPORTING CITATION_ID(S): ____________________
SCOPE: ____________________
NOTES: ____________________

*(repeat the above SUPPORTED?/SUPPORTING/SCOPE/NOTES block per claim on the working copy — one row per claim above)*

**DISTRACTOR / INCORRECTLY DISPLAYED CITATION_ID(S):** ____________________
**EQUIVALENT EVIDENCE GROUPS:** ____________________
**CONFLICTING EVIDENCE?** [ ] None  [ ] Same-scope contradiction  [ ] Different scope/population

CONTEXT NOTE (not gold, quoted verbatim from benchmark JSON's `scope_conflict` field): "gate3's own
retrieved_grading block captures two 'Grading System' chunks under the same document_id
(30875c07-409e-45ea-989e-3315a85608c1): one scoped 'Undergraduate Academic Policies > Article 7'
(1.00-5.00 scale) and one scoped 'Graduate Studies > Article 12 > Comprehensive Examination
Guidelines' (1.00-2.00+ scale). This is a population/scope difference (undergrad vs. graduate), not a
factual contradiction -- but this label is my own reading of the dump during investigation, not a
human labeler's adjudicated judgment, and must not be treated as gold until the real
two-labeler+adjudication process runs it." Status recorded in the benchmark as
`candidate_label_pending_adjudication`.

**LABELER:** ____________________
**DATE:** ____________________

---

## Case 2: `cert_final_enroll_t0`

- **CATEGORY:** Enrollment procedure
- **PROVENANCE:** `aska_cert_final.json` (label `P-enroll/t0`)
- **QUESTION:** "How do I enroll?"
- **USER ROLE:** Not recorded in the source dump.
- **REPRODUCIBILITY STATUS:** REPRODUCIBLE STANDALONE (`is_followup: false`)

**FINAL ANSWER** (ANSWER TEXT: COMPLETE):
> "To enroll at LSPU, you'll work primarily with the **Registrar's Office**. [...] Who may avail: All students, including new college students, transferees, and GSAR students. [...] Key requirements for new students and transferees: Enrolment Slip from the Admission Office School; Original Certificate of Good Moral Character; Original Report Card (new students only); Photocopy of PSA Birth Certificate; Certificate or marriage contract (if married female student); Medical slip or certificate from LSPU Medical Clinic (DOH-accredited); Clearance (Accounting Office); Student ID (OSAS or BAO); Evaluation of grades (Registrar/College). [...] Step-by-step: (1) New college students/transferees schedule an appointment, bring hard copies; Registrar validates documents, creates subject list, issues SF10/F137 request form. (2) New GSAR students bring hard copy of requirements plus a pre-enrolment form from the Dean's Office. (3) Old college/GSAR students log in to the Student Web Portal. [...] No fees for submitting requirements or completing the standard enrollment process. Total estimated processing time is 20 minutes. [...] For enrollment-status concerns, consult the College Dean first, then the Registrar's Office. For deferment of enrollment, write to the Registrar's Office requesting deferment to the following semester."

**RAW ANSWER:** N/A — this dump only records a single `answer` field; no separate raw/pre-safety-override text was captured.

**CANDIDATE CITATIONS:** EVIDENCE INCOMPLETE — REQUIRES AUTHORIZED SOURCE LOOKUP. `retrieved_candidate_titles` is `null` in the benchmark; no candidate pool (beyond what V1 displayed) was captured in this dump.

**V1 DISPLAYED CITATIONS** (titles only — `v1_displayed_citation_ids` is null; this dump recorded only `source_titles`, ID NOT CAPTURED IN SEED ARTIFACT):
- Enrollment
- Enrollment
- Consultation on the Status of Enrolment
- Deferment of Enrolment
- Colleges or departments may commence enrollment immediately

**CLAIMS TO REVIEW** (for HUMAN REVIEW ONLY, not gold):

1. Enrollment at LSPU is handled primarily by the Registrar's Office.
2. All students (new college students, transferees, and GSAR students) may avail of enrollment.
3. New students/transferees must submit: Enrolment Slip from the Admission Office.
4. ...Original Certificate of Good Moral Character from the previously attended/graduated school.
5. ...Original Report Card (new students only).
6. ...Photocopy of PSA Birth Certificate.
7. ...Certificate or marriage contract (married female students).
8. ...Medical slip or certificate from the LSPU Medical Clinic (DOH-accredited).
9. ...Clearance from the Accounting Office.
10. ...Student ID from OSAS or BAO.
11. ...Evaluation of grades handled by the Registrar/College.
12. New college students/transferees schedule an appointment and submit hard copies; Registrar validates documents, creates a subject list, and issues an SF10/F137 request form.
13. New GSAR students bring both hard-copy requirements and a pre-enrolment form from the Dean's Office.
14. Old college/GSAR students log in to the Student Web Portal to finalize subjects.
15. There are no fees for enrollment requirement submission or the standard enrollment process.
16. Total estimated enrollment processing time is 20 minutes.
17. For enrollment-status concerns, consult the College Dean first, then the Registrar's Office.
18. Deferment of enrollment for valid reasons requires writing to the Registrar's Office to request deferment to the following semester.

SUPPORTED? [ ] Yes [ ] No — SUPPORTING CITATION_ID(S): ____ — SCOPE: ____ — NOTES: ____
*(one row per claim above, on the working copy)*

**DISTRACTOR / INCORRECTLY DISPLAYED CITATION_ID(S):** ____________________
**EQUIVALENT EVIDENCE GROUPS:** ____________________
**CONFLICTING EVIDENCE?** [ ] None [ ] Same-scope contradiction [ ] Different scope/population
**LABELER:** ____________________  **DATE:** ____________________

---

## Case 3: `cert_final_switch_tor_followup`

- **CATEGORY:** Topic-switch follow-up (TOR), NON-REPRODUCIBLE
- **PROVENANCE:** `aska_cert_final.json` (label `P-switch/tor`)
- **QUESTION:** "Now tell me about TOR."
- **USER ROLE:** Not recorded in the source dump.
- **REPRODUCIBILITY STATUS:** **NON-REPRODUCIBLE WITHOUT ORIGINAL HISTORY.** This is a topic-switch
  follow-up ("Now tell me about TOR." only makes sense after the preceding enrollment-office turn,
  `P-enroll/t4`, "Which office handles that?"). The captured dump did not record the conversation
  history object needed to replay this through `answer_qa_question`'s `history` parameter. It is
  excluded from executable Stage 1 baseline evaluation and must remain marked non-reproducible
  standalone; no conversation history is fabricated here or anywhere else in this worksheet.

**FINAL ANSWER** (ANSWER TEXT: COMPLETE):
> "# TOR (Transcript of Records) Service Overview — The **Issuance of Transcript of Records** service (also referred to as Transfer Credentials, Certifications, CAV, and Authenticated Documents) is handled by the **Registrar's Office**. Who May Avail: **All** students and graduates (walk-in access available). Fees: Undergraduate transcript pages P75.00/page; Graduate transcript pages P150.00/page; additional page listed as P30.00/page; second copy of diploma P100.00. Total Processing Time: **59 minutes**. Required Steps: (1) Request Slip (LSPU-REG-SF-011), reviewed by Registrar's Staff, ~5 min. (2) Complete request slip with clearance and signatures of heads of offices; fees assessed. (3) Payment at the Cashier's office. (4) Claim Stub issued with release date, ~2 min. (5) Pick up documents at scheduled release. Office: Registrar. The same Registrar office also handles crediting of subjects, document authentication, and issuing copies of documents requested by clients."

**RAW ANSWER:** N/A — only a single `answer` field was captured.

**CANDIDATE CITATIONS:** EVIDENCE INCOMPLETE — REQUIRES AUTHORIZED SOURCE LOOKUP. `retrieved_candidate_titles` is `null`; no broader candidate pool was captured.

**V1 DISPLAYED CITATIONS** (titles only, ID NOT CAPTURED IN SEED ARTIFACT):
- Issuance of Transcript of Records/Transfer Credentials/Certifications/CAV/Authenticated Documents
- Crediting of Subjects
- Authentication of Documents
- Crediting of Subjects
- Issuance of Copy of Documents Requested by Clients
- Dropping of Subjects

**CLAIMS TO REVIEW** (for HUMAN REVIEW ONLY, not gold):

1. The Issuance of Transcript of Records service (incl. Transfer Credentials, Certifications, CAV, Authenticated Documents) is handled by the Registrar's Office.
2. All students and graduates may avail (walk-in access available).
3. Undergraduate transcript pages cost P75.00 per page.
4. Graduate transcript pages cost P150.00 per page.
5. An additional page is listed at P30.00 per page.
6. A second copy of diploma costs P100.00.
7. Total processing time is 59 minutes.
8. Step 1 is obtaining/reviewing the request slip (LSPU-REG-SF-011), handled by Registrar's Staff, ~5 minutes.
9. Step 2 is completing the request slip with clearance and signatures of heads of offices; fees assessed at this stage.
10. Step 3 is paying fees at the Cashier's office.
11. Step 4 is submitting the completed slip + payment receipt to receive a claim stub with release date.
12. Step 5 is picking up documents at the scheduled release time.
13. The same Registrar office also handles crediting of subjects, document authentication, and issuing copies of documents requested by clients.

SUPPORTED? [ ] Yes [ ] No — SUPPORTING CITATION_ID(S): ____ — SCOPE: ____ — NOTES: ____
*(one row per claim above, on the working copy)*

**DISTRACTOR / INCORRECTLY DISPLAYED CITATION_ID(S):** ____________________
**EQUIVALENT EVIDENCE GROUPS:** ____________________
**CONFLICTING EVIDENCE?** [ ] None [ ] Same-scope contradiction [ ] Different scope/population

CONTEXT NOTE (not gold): This case "may still appear in the worksheet, clearly marked
NON-REPRODUCIBLE WITHOUT ORIGINAL HISTORY" per Stage 2 instructions — recorded above. Prior-turn
context (from the benchmark JSON's own `prior_turn_context_note`, not fabricated here): preceding
turn in the same regression sequence was `P-enroll/t4` ("Which office handles that?", about
enrollment).

**LABELER:** ____________________  **DATE:** ____________________

---

## Case 4: `cert_final_oos_stale`

- **CATEGORY:** Out-of-scope / refusal
- **PROVENANCE:** `aska_cert_final.json` (label `P-oos-stale`)
- **QUESTION:** "Who is the president of the Philippines?"
- **USER ROLE:** Not recorded in the source dump.
- **REPRODUCIBILITY STATUS:** REPRODUCIBLE STANDALONE (`is_followup: false`)

**FINAL ANSWER** (ANSWER TEXT: COMPLETE):
> "The indexed LSPU documents (Citizen's Charter / student handbook) do not contain enough information about this topic."

**RAW ANSWER:** N/A.

**CANDIDATE CITATIONS:** None retrieved/displayed (`v1_displayed_citation_titles: []`). No candidate pool captured — EVIDENCE INCOMPLETE — REQUIRES AUTHORIZED SOURCE LOOKUP if a labeler wants to confirm zero relevant candidates existed at retrieval time.

**V1 DISPLAYED CITATIONS:** None.

**CLAIMS TO REVIEW** (for HUMAN REVIEW ONLY, not gold):

1. The indexed LSPU documents (Citizen's Charter / student handbook) do not contain information about who the president of the Philippines is.

Note: this is a meta-claim about corpus coverage, not a factual claim about LSPU policy; the human
labeler should judge it as "supported" only in the sense of whether the refusal was the correct system
behavior given an empty citation set, not against LSPU source content.

SUPPORTED? [ ] Yes [ ] No — SUPPORTING CITATION_ID(S): ____ — SCOPE: ____ — NOTES: ____

**DISTRACTOR / INCORRECTLY DISPLAYED CITATION_ID(S):** ____________________ (N/A — no citations displayed)
**EQUIVALENT EVIDENCE GROUPS:** ____________________
**CONFLICTING EVIDENCE?** [ ] None [ ] Same-scope contradiction [ ] Different scope/population
**LABELER:** ____________________  **DATE:** ____________________

---

## Case 5: `cert_final_good_moral_fee`

- **CATEGORY:** Fee inquiry (Good Moral Certificate)
- **PROVENANCE:** `aska_cert_final.json` (label `L-omit-gm-fee`)
- **QUESTION:** "How much does a Good Moral Certificate cost?"
- **USER ROLE:** Not recorded in the source dump.
- **REPRODUCIBILITY STATUS:** REPRODUCIBLE STANDALONE (`is_followup: false`)

**FINAL ANSWER** (ANSWER TEXT: COMPLETE):
> "Based on the retrieved LSPU documentation, the Good Moral Certificate has **no fee**. Fees: None (as stated in the 'Issuance of Good Moral Certificate (Undergraduate)' document under the Office of the Student Affairs and Services). Total Processing Time: 1 hour. Requirements: Certificate of Registration (from the Registrar's Office), Student ID (from Business Affairs Office), and any other required documents as outlined in the structured requirements. The document explicitly lists 'Fees: None' for the issuance process, and all client steps indicate no fees are charged. So to answer directly: **A Good Moral Certificate costs nothing (free).**"

**RAW ANSWER:** N/A.

**CANDIDATE CITATIONS:** EVIDENCE INCOMPLETE — REQUIRES AUTHORIZED SOURCE LOOKUP (`retrieved_candidate_titles: null`).

**V1 DISPLAYED CITATIONS** (titles only, ID NOT CAPTURED IN SEED ARTIFACT):
- Issuance of Good Moral Certificate (Undergraduate)
- Good Moral
- Enrollment
- UDRRMO
- Open to all Clients
- Signing of Faculty Clearance

**CLAIMS TO REVIEW** (for HUMAN REVIEW ONLY, not gold):

1. The Good Moral Certificate has no fee.
2. Fees are listed as "None" in the "Issuance of Good Moral Certificate (Undergraduate)" document, under the Office of Student Affairs and Services.
3. Total processing time is 1 hour.
4. Requirements include a Certificate of Registration from the Registrar's Office.
5. Requirements include a Student ID from the Business Affairs Office.
6. All client steps associated with obtaining the certificate indicate no fees are charged.

SUPPORTED? [ ] Yes [ ] No — SUPPORTING CITATION_ID(S): ____ — SCOPE: ____ — NOTES: ____
*(one row per claim above)*

CONTEXT NOTE (not gold): this case's `id` (`cert_final_good_moral_fee`) and `source_label`
(`L-omit-gm-fee`) both reference "omit ... fee" — labelers should specifically check whether any
candidate in the true retrieval pool (not captured in this dump) contradicts or qualifies the "no
fee" claim, since the label suggests this scenario was constructed/selected to probe that. This is
a provenance observation about the case's naming, not a correctness judgment.

**DISTRACTOR / INCORRECTLY DISPLAYED CITATION_ID(S):** ____________________
**EQUIVALENT EVIDENCE GROUPS:** ____________________
**CONFLICTING EVIDENCE?** [ ] None [ ] Same-scope contradiction [ ] Different scope/population
**LABELER:** ____________________  **DATE:** ____________________

---

## Case 6: `cert_final_grade_duplicate_of_gate3`

- **CATEGORY:** Grading / GWA (duplicate question of Case 1, separate regression run)
- **PROVENANCE:** `aska_cert_final.json` (label `P-grade`)
- **QUESTION:** "What is the passing grade and how is GWA computed?"
- **USER ROLE:** Not recorded in the source dump.
- **REPRODUCIBILITY STATUS:** REPRODUCIBLE STANDALONE (`is_followup: false`)
- Same question text as `gate3_grading_gwa` (Case 1), captured in a separate regression run. Kept as
  its own case (per benchmark note) to check V1's citation selection stability across runs — not
  merged with Case 1.

**FINAL ANSWER** (ANSWER TEXT: COMPLETE):
> "- **Definition**: GWA refers to the weighted average of grades in all academic courses taken in a given semester (as defined by the Office of the Registrar). The available source lists individual categories/ranges, but it does not explicitly state a single overall boundary for that classification."

**RAW ANSWER:** N/A — only a single `answer` field was captured for this run (unlike Case 1's dump, no separate raw/pre-safety-override text exists here).

**CANDIDATE CITATIONS:** EVIDENCE INCOMPLETE — REQUIRES AUTHORIZED SOURCE LOOKUP (`retrieved_candidate_titles: null` for this run).

**V1 DISPLAYED CITATIONS** (titles only, ID NOT CAPTURED IN SEED ARTIFACT — note: 6 titles here vs. 7 in Case 1's same-question run; "GWA" is present in Case 1 but absent from this run's list):
- Completion of INC/Removal – Online System
- References and Resources
- Undergraduate Grading System
- Grading Policy
- Policy on Grades of "4" and "5"
- Cumulative GWA

**CLAIMS TO REVIEW** (for HUMAN REVIEW ONLY, not gold):

1. GWA refers to the weighted average of grades in all academic courses taken in a given semester, as defined by the Office of the Registrar.
2. The available source lists individual categories/ranges for grade classification.
3. The available source does not explicitly state a single overall passing-grade boundary.

SUPPORTED? [ ] Yes [ ] No — SUPPORTING CITATION_ID(S): ____ — SCOPE: ____ — NOTES: ____
*(one row per claim above)*

CONTEXT NOTE (not gold): the displayed-title-list discrepancy vs. Case 1 (missing "GWA") is a
run-to-run stability question the benchmark deliberately preserved by keeping this as a separate
case; it is not resolved or explained in this worksheet.

**DISTRACTOR / INCORRECTLY DISPLAYED CITATION_ID(S):** ____________________
**EQUIVALENT EVIDENCE GROUPS:** ____________________
**CONFLICTING EVIDENCE?** [ ] None [ ] Same-scope contradiction [ ] Different scope/population
**LABELER:** ____________________  **DATE:** ____________________

---

## Case 7: `val_active_service_enroll_t0`

- **CATEGORY:** Enrollment procedure (validation run)
- **PROVENANCE:** `aska_val_active_service.json` (label `S-enroll/t0`)
- **QUESTION:** "How do I enroll as a new student at LSPU?"
- **USER ROLE:** Not recorded in the source dump.
- **REPRODUCIBILITY STATUS:** REPRODUCIBLE STANDALONE (`is_followup: false`)

**FINAL ANSWER** (ANSWER TEXT: COMPLETE):
> "To enroll as a new student at LSPU, you'll work primarily with the **Registrar's Office**. Key Details — Office: Registrar; Who May Avail: All new and transferring students; Total Processing Time: 20 minutes. Enrollment Steps: (1) Schedule an Appointment — new college students/transferees proceed to the Office of the Registrar on their scheduled appointment date to submit the hard copy of all enrolment requirements. (2) Submit Required Documents — Enrolment Slip from Admission Office; Original Certificate of Good Moral Character; Original Report Card (new students only); Photocopy of PSA Birth Certificate; Certificate/Marriage Contract (married female students); Medical slip or certificate from LSPU Medical Clinic (DOH-accredited); 2×2 photo; Original Certificate of Transfer (transferees only); long brown envelope. (3) Complete the Enrolment Slip — Registrar's staff validate document authenticity and enter information into the system. (4) Old GSAR students may instead log in to the Student Web Portal to finalize subject enrollment. No fees for the initial enrollment process; a Certificate of Registration (COR) is issued once processed."

**RAW ANSWER:** N/A.

**CANDIDATE CITATIONS:** EVIDENCE INCOMPLETE — REQUIRES AUTHORIZED SOURCE LOOKUP (`retrieved_candidate_titles: null`).

**V1 DISPLAYED CITATIONS** (titles only, ID NOT CAPTURED IN SEED ARTIFACT):
- Enrollment
- Enrollment
- Assessment of Fees
- IP Registration Process

**CLAIMS TO REVIEW** (for HUMAN REVIEW ONLY, not gold):

1. New-student enrollment is handled primarily by the Registrar's Office.
2. All new and transferring students may avail.
3. Total processing time is 20 minutes.
4. Step 1: schedule an appointment; new college students/transferees submit hard copies of enrolment requirements on that date.
5. Required documents include the items listed above (Enrolment Slip, Certificate of Good Moral Character, Report Card, PSA Birth Certificate photocopy, Certificate/Marriage Contract, Medical slip/certificate, 2×2 photo, Certificate of Transfer for transferees, long brown envelope).
6. Step 3: Registrar's staff validate document authenticity and enter information into the system.
7. Old GSAR students may instead use the Student Web Portal to finalize subject enrollment.
8. There are no fees for the initial enrollment process.
9. A Certificate of Registration (COR) is issued once the application is processed.

SUPPORTED? [ ] Yes [ ] No — SUPPORTING CITATION_ID(S): ____ — SCOPE: ____ — NOTES: ____
*(one row per claim above)*

**DISTRACTOR / INCORRECTLY DISPLAYED CITATION_ID(S):** ____________________
**EQUIVALENT EVIDENCE GROUPS:** ____________________
**CONFLICTING EVIDENCE?** [ ] None [ ] Same-scope contradiction [ ] Different scope/population
**LABELER:** ____________________  **DATE:** ____________________

---

## Case 8: `merged_chat_institutional_identity`

- **CATEGORY:** Simple institutional / definitional
- **PROVENANCE:** `aska_student_qa_MERGED.json` (`chat[0]`, name "simple institutional")
- **QUESTION:** "What is Laguna State Polytechnic University?"
- **USER ROLE:** Not recorded in the source dump.
- **REPRODUCIBILITY STATUS:** REPRODUCIBLE STANDALONE (`is_followup: false`)

**FINAL ANSWER** (ANSWER TEXT: TRUNCATED SNIPPET ONLY — dump records `answer_len: 1775` but only an
`answer_snip` was captured; full 1775-character answer text does not exist in any reviewed seed
artifact):
> "I've reviewed the retrieved context, and unfortunately, none of the documents provide a general description or definition of what Laguna State Polytechnic University (LSPU) is as an institution. The retrieved materials f[...TRUNCATED, ~1550 characters not captured...]"

**RAW ANSWER:** N/A.

**CANDIDATE CITATIONS:** EVIDENCE INCOMPLETE — REQUIRES AUTHORIZED SOURCE LOOKUP. Only `sources_n: 7` and the rank-1 title were captured; the other 6 candidates were never recorded in any seed dump.

**V1 DISPLAYED CITATIONS** (rank-1/top_source only — `sources_n=7`, `citations_n=7`, but only the top title was captured, ID NOT CAPTURED IN SEED ARTIFACT; 6 of 7 displayed titles are EVIDENCE INCOMPLETE — REQUIRES AUTHORIZED SOURCE LOOKUP):
- Establishment of Linkages and Network (rank 1 of 7)

**CLAIMS TO REVIEW:** EVIDENCE INCOMPLETE — REQUIRES AUTHORIZED SOURCE LOOKUP for a full claim split;
only the following fragment is available from the truncated snippet, offered as a single partial
claim for HUMAN REVIEW ONLY, not gold:

1. (Partial) The retrieved documents do not provide a general description/definition of what LSPU is as an institution.

SUPPORTED? [ ] Yes [ ] No — SUPPORTING CITATION_ID(S): ____ — SCOPE: ____ — NOTES: ____

CONTEXT NOTE (not gold, quoted from benchmark's `historical_relevance_judgment`): a prior
non-adjudicated pass/fail sweep recorded `relevant: true, source_relevant: true` for this case
(part of a 111-row manual QA sweep: 104 passed / 1 failed / 6 warnings). Provenance only — this is
explicitly NOT the two-labeler+adjudication gold process and must not be read as
`gold_supporting_chunk_ids`.

**DISTRACTOR / INCORRECTLY DISPLAYED CITATION_ID(S):** ____________________
**EQUIVALENT EVIDENCE GROUPS:** ____________________
**CONFLICTING EVIDENCE?** [ ] None [ ] Same-scope contradiction [ ] Different scope/population
**LABELER:** ____________________  **DATE:** ____________________

---

## Case 9: `merged_chat_drop_subject_no_evidence`

- **CATEGORY:** Multi-part question, zero-citation refusal
- **PROVENANCE:** `aska_student_qa_MERGED.json` (`chat[3]`, name "multi-part")
- **QUESTION:** "How do I drop a subject and what happens to my grades if I drop late?"
- **USER ROLE:** Not recorded in the source dump.
- **REPRODUCIBILITY STATUS:** REPRODUCIBLE STANDALONE (`is_followup: false`)

**FINAL ANSWER** (ANSWER TEXT: COMPLETE — `answer_len: 117` matches the captured snippet's length,
and this exact wording recurs verbatim as the stock out-of-evidence message elsewhere in the same
dump and in `aska_cert_final.json`'s `P-oos-stale`, confirming it is the full fixed message, not a
cut string):
> "The indexed LSPU documents (Citizen's Charter / student handbook) do not contain enough information about this topic."

**RAW ANSWER:** N/A.

**CANDIDATE CITATIONS:** None retrieved (`sources_n: 0`). EVIDENCE INCOMPLETE — REQUIRES AUTHORIZED SOURCE LOOKUP if confirming zero relevant candidates existed at retrieval time is needed.

**V1 DISPLAYED CITATIONS:** None (`sources_n: 0`, `citations_n: 0`).

**CLAIMS TO REVIEW** (for HUMAN REVIEW ONLY, not gold):

1. The indexed LSPU documents do not contain enough information to answer how to drop a subject and what happens to grades on a late drop.

SUPPORTED? [ ] Yes [ ] No — SUPPORTING CITATION_ID(S): ____ — SCOPE: ____ — NOTES: ____

CONTEXT NOTE (not gold, quoted from benchmark): historical judgment recorded `relevant: true,
source_relevant: false` — "V1 answered but showed no citation for it." The benchmark itself flags
this as "a real 'unsupported claim' case once claim-level Layer B exists; for the V1 lexical
baseline it is simply a case with an empty displayed-citation list." Provenance only, not gold.

**DISTRACTOR / INCORRECTLY DISPLAYED CITATION_ID(S):** ____________________ (N/A — no citations displayed)
**EQUIVALENT EVIDENCE GROUPS:** ____________________
**CONFLICTING EVIDENCE?** [ ] None [ ] Same-scope contradiction [ ] Different scope/population
**LABELER:** ____________________  **DATE:** ____________________

---

## Case 10: `merged_chat_scholarship_surprising_top_source`

- **CATEGORY:** Scholarship application, flagged topical-mismatch case
- **PROVENANCE:** `aska_student_qa_MERGED.json` (`chat[12]`, name "scholarship")
- **QUESTION:** "How do I apply for a scholarship at LSPU?"
- **USER ROLE:** Not recorded in the source dump.
- **REPRODUCIBILITY STATUS:** REPRODUCIBLE STANDALONE (`is_followup: false`)

**FINAL ANSWER** (ANSWER TEXT: TRUNCATED SNIPPET ONLY — no `answer_len` was captured for this entry, so the untruncated length is unknown):
> "To apply for a scholarship at LSPU, you can follow the process outlined by the **Scholarship and Financial Assistance Unit**. Here's how it works: **Who may avail:** All students (no restrictions mentioned) **Total pro[...TRUNCATED, remainder not captured...]"

**RAW ANSWER:** N/A.

**CANDIDATE CITATIONS:** EVIDENCE INCOMPLETE — REQUIRES AUTHORIZED SOURCE LOOKUP. Only `sources_n: 7` and the rank-1 title were captured.

**V1 DISPLAYED CITATIONS** (rank-1/top_source only, ID NOT CAPTURED IN SEED ARTIFACT; 6 of 7 displayed titles are EVIDENCE INCOMPLETE — REQUIRES AUTHORIZED SOURCE LOOKUP):
- Issuance of Good Moral Certificate (LSPU Alumni) (rank 1 of 7)

**CLAIMS TO REVIEW:** EVIDENCE INCOMPLETE — REQUIRES AUTHORIZED SOURCE LOOKUP for a full claim split;
partial claims from the truncated snippet only, for HUMAN REVIEW ONLY, not gold:

1. (Partial) Scholarship applications at LSPU follow a process outlined by the Scholarship and Financial Assistance Unit.
2. (Partial) All students may avail, with no restrictions mentioned.

SUPPORTED? [ ] Yes [ ] No — SUPPORTING CITATION_ID(S): ____ — SCOPE: ____ — NOTES: ____
*(one row per claim above)*

CONTEXT NOTE (not gold, quoted/paraphrased from the benchmark's own `notes` field): the recorded
top_source, "Issuance of Good Moral Certificate (LSPU Alumni)," looks topically mismatched for a
scholarship-application question, yet the historical judgment marks both `relevant: true` and
`source_relevant: true`. The benchmark explicitly flags this "for human re-review during
adjudication -- deliberately NOT overridden by this investigation, since that would just substitute
one unadjudicated guess for another." This worksheet makes the same choice: the flag is surfaced,
not resolved.

**DISTRACTOR / INCORRECTLY DISPLAYED CITATION_ID(S):** ____________________
**EQUIVALENT EVIDENCE GROUPS:** ____________________
**CONFLICTING EVIDENCE?** [ ] None [ ] Same-scope contradiction [ ] Different scope/population
**LABELER:** ____________________  **DATE:** ____________________

---

## Case 11: `merged_chat_request_tor`

- **CATEGORY:** Records request (TOR)
- **PROVENANCE:** `aska_student_qa_MERGED.json` (`chat[13]`, name "records")
- **QUESTION:** "How do I request a Transcript of Records?"
- **USER ROLE:** Not recorded in the source dump.
- **REPRODUCIBILITY STATUS:** REPRODUCIBLE STANDALONE (`is_followup: false`)

**FINAL ANSWER** (ANSWER TEXT: TRUNCATED SNIPPET ONLY — no `answer_len` captured):
> "To request a Transcript of Records at LSPU, you'll need to go through the Registrar's office following these steps: **Who may avail:** All walk-in students and graduates **Process overview:** 1. **Complete the request [...TRUNCATED, remainder not captured...]"

**RAW ANSWER:** N/A.

**CANDIDATE CITATIONS:** EVIDENCE INCOMPLETE — REQUIRES AUTHORIZED SOURCE LOOKUP. Only `sources_n: 7` and the rank-1 title were captured.

**V1 DISPLAYED CITATIONS** (rank-1/top_source only, ID NOT CAPTURED IN SEED ARTIFACT; 6 of 7 displayed titles are EVIDENCE INCOMPLETE — REQUIRES AUTHORIZED SOURCE LOOKUP):
- Issuance of Transcript of Records/Transfer Credentials/Certifications/CAV/Authenticated Documents (rank 1 of 7)

**CLAIMS TO REVIEW:** EVIDENCE INCOMPLETE — REQUIRES AUTHORIZED SOURCE LOOKUP for a full claim split;
partial claims from the truncated snippet only, for HUMAN REVIEW ONLY, not gold:

1. (Partial) Requesting a Transcript of Records is handled through the Registrar's office.
2. (Partial) All walk-in students and graduates may avail.

SUPPORTED? [ ] Yes [ ] No — SUPPORTING CITATION_ID(S): ____ — SCOPE: ____ — NOTES: ____
*(one row per claim above)*

CONTEXT NOTE (not gold, quoted from benchmark's `historical_relevance_judgment`): prior
non-adjudicated sweep recorded `relevant: true, source_relevant: true`. Provenance only.

**DISTRACTOR / INCORRECTLY DISPLAYED CITATION_ID(S):** ____________________
**EQUIVALENT EVIDENCE GROUPS:** ____________________
**CONFLICTING EVIDENCE?** [ ] None [ ] Same-scope contradiction [ ] Different scope/population
**LABELER:** ____________________  **DATE:** ____________________

---

## Case 12: `grade_correction_full_candidate_pool_repro`

- **CATEGORY:** Faculty grade-correction approval process (reconstructed production-incident repro)
- **PROVENANCE:** "reconstructed from a production incident report ... not a raw seed-data dump" — per
  the benchmark's own `source_file` field, this case is NOT drawn from any of the 7 raw seed-data
  files reviewed for this worksheet. No additional artifact was located or opened for it in this
  pass.
- **QUESTION:** "A faculty member needs to correct grades for 30% of a class. Explain the complete
  approval process, including who must approve it, whether an Academic Council meeting is required,
  and every deadline stated in the policy." (`question_is_verbatim_capture: false` — reconstructed,
  not copied verbatim from a raw dump.)
- **USER ROLE:** "faculty" — per benchmark note, set to match the incident report's reproduction
  context; not independently verified against a captured dump.
- **REPRODUCIBILITY STATUS:** REPRODUCIBLE STANDALONE in the sense that `is_followup: false`, but the
  question/candidate pool are themselves a reconstruction, not a captured live run — treat with
  correspondingly lower provenance confidence than Cases 1–11.

**FINAL ANSWER:** EVIDENCE INCOMPLETE — REQUIRES AUTHORIZED SOURCE LOOKUP. No answer text (final or
raw) was captured in the benchmark or in any of the 7 seed artifacts reviewed for this worksheet; the
benchmark record for this case only preserves candidate/displayed **titles**, not answer text. Do not
invent this text.

**RAW ANSWER:** EVIDENCE INCOMPLETE — REQUIRES AUTHORIZED SOURCE LOOKUP (same as above).

**CANDIDATE CITATIONS** (titles only — no citation_id or document/source/page/excerpt exists for this
reconstructed pool; per the benchmark's own note, "no real citation_id values exist for it yet."
ID NOT CAPTURED IN SEED ARTIFACT for all 7):
- Grading Sheets Part 1
- Grading Sheets Part 2
- Completion of INC/Removal
- References and Resources
- Reclassification of position
- System Information Registration
- Administrative sanction

**V1 DISPLAYED CITATIONS** (titles only, ID NOT CAPTURED IN SEED ARTIFACT):
- Grading Sheets Part 1
- Grading Sheets Part 2
- Completion of INC/Removal

**CLAIMS TO REVIEW:** EVIDENCE INCOMPLETE — REQUIRES AUTHORIZED SOURCE LOOKUP. No answer text exists
to split into claims for this case.

**DISTRACTOR / INCORRECTLY DISPLAYED CITATION_ID(S):** ____________________
**EQUIVALENT EVIDENCE GROUPS:** ____________________
**CONFLICTING EVIDENCE?** [ ] None [ ] Same-scope contradiction [ ] Different scope/population

CONTEXT NOTE (not gold, quoted/paraphrased from the benchmark's own `notes` field, which is
unusually long for this case and should be read in full by labelers before adjudicating it): this
case was previously encoded as a V1 production-regression unit test asserting that "Completion of
INC/Removal" must NOT appear in V1's displayed sources. That test was introduced after commit
`54975af` as part of an "abandoned citation-precision experiment" and encoded "a DESIRED Citation
Grounding V2 outcome, not verified V1/54975af behavior" — the benchmark states verified V1 behavior
is the opposite: "Completion of INC/Removal" IS displayed. The unit test was removed from the
production regression suite during Stage 1 cleanup. The benchmark explicitly states: "Whether
'Completion of INC/Removal' is actually a false positive is a labeling question for that process, not
something to assert in a V1 unit test or infer here." This worksheet does not resolve that question
either — it is squarely a Stage 2 human-adjudication decision, and the missing answer text above
makes claim-level review of it impossible until an authorized source lookup fills that gap.

**LABELER:** ____________________  **DATE:** ____________________

---

## Appendix: excluded-from-worksheet source files (unchanged from benchmark)

Per the benchmark's own `excluded_source_files`, these were not seeded as cases and are not treated
as cases here either: `_smoke_tor.json` and `_smoke_oos_t1.json` (question text not recorded in the
dump — a case could not be seeded without reconstructing, not stating, the question), and
`aska_audit_candidate.json` / `aska_audit_candidate_new.json` / ticket/authz rows of
`aska_student_qa_MERGED.json` (not reviewed / out of scope for a citation-grounding benchmark). This
worksheet opened `_smoke_tor.json` and `_smoke_oos_t1.json` only to confirm they indeed lack the
literal question text (consistent with the exclusion reason already on file) — no new case was
created from them, and no question text was reconstructed or guessed.
