# Live student-chatbot answer-quality results

Run ID: `aq_live_student_chat_20261105T023200Z`  
Role: **student**  
Evidence: 14 screenshots from the live chatbot

These are human judgments against the pending answer-quality cases. They are **not** RAGAS. `rag_eval_dataset.json` was not filled. The pending dataset remains unlabeled.

On 2026-11-05 these judgments were stored in `backend/benchmarks/evaluation/human_answer_quality_overview.json` and re-applied onto local evaluation runs, including `131ba7a4-2fa2-475d-8d6e-ccc36044733c`. A new Admin **Run Evaluation** copies the same four scores onto the new run so the Overview cards are not wiped. `rag_eval_dataset.json` stays empty.

## Headline

| Outcome | Count | Cases |
| --- | ---: | --- |
| Pass | 5 | Q1 TOR fee, Q2 diploma fee, Q3 enrollment office, Q7 ID validation, Q13 Mars (out of scope) |
| Partial | 4 | Q6 entrance exam, Q11 honorable dismissal, Q12 president, Q14 Wi-Fi |
| Fail | 3 | Q4 dropping fee, Q5 library overdue, Q8 fail 75% |
| Role-gated (expected) | 2 | Q9 teaching load, Q10 faculty responsibilities |

**Student-visible score:** 5 pass / 4 partial / 3 fail out of 12.  
**Faculty-only questions:** 2 expected refusals. Those are not counted as chatbot errors.

Overview cards (human, 12 student-visible cases):

| Card | Value | Meaning |
| --- | ---: | --- |
| Answer Correctness | 0.5833 | (5 + 4×0.5) / 12 |
| Faithfulness | 0.5417 | Invented fees/totals/bio vs stayed in sources |
| Answer Relevance | 0.9167 | 11/12 addressed the question |
| Citation Accuracy | 0.9000 | Document-title match on 5 screenshots that showed sources, not gold chunk IDs |

## Why Q9 and Q10 look empty

The user is correct. Those answers live in the **Faculty Manual**, which is tagged `audience: faculty`. A student session is not allowed to retrieve it. The chatbot is also written so students are **not told that a Faculty Manual exists**. The stock student message is:

> The indexed LSPU documents (Citizen's Charter / student handbook) do not contain enough information about this topic.

That is the designed student refusal, not a missing-document bug. The same questions would need a **faculty** login to be answerable.

## Case-by-case

### Q1 · aq_01_tor_fee · PASS
Asked the TOR fee. Answered undergraduate ₱75.00/page and graduate ₱150.00/page. That matches the Charter fee lines used in the pending case. Extra Registrar / cashier / processing-time detail was not checked against the PDF in this pass. No sources were visible in the screenshot.

### Q2 · aq_02_diploma_second_copy_fee · PASS
Answered ₱100.00 for a second copy of the diploma, which matches the explicit Charter line. Extra process / 2-minute timing was not PDF-checked here. No sources visible.

### Q3 · aq_03_enrollment_office · PASS
Named the Office of the Registrar, including transferees. Sources shown: Citizen's Charter, Enrollment (four duplicate chips). Extra COR / enlisting wording is extra, not a contradiction of the office name.

### Q4 · aq_04_dropping_fee_multi_document · FAIL
Answered only ₱30.00 from the Charter Dropping of Subjects card and gave that process. The pending case requires both amounts: Charter ₱30.00 and Handbook ₱20.00 per unit, plus that which fee is in force is unresolved. The Handbook is student-visible, so this is not a role-gate miss. Citation panel showed 1 source, collapsed.

### Q5 · aq_05_library_overdue_fee · FAIL
The extraction only has “2 pesos per” with the **unit missing**. The chatbot stated **₱2.00 per day**. That invents the missing unit. Insufficient-evidence cases should not fill in “per day.”

### Q6 · aq_06_entrance_exam_duration · PARTIAL
Orientation 15 minutes and examination proper 1.5 hours match the Charter. The chatbot then invented an official total of **1 hour and 45 minutes** and attributed it to the Charter. The Charter records Total Processing Time as **Not specified**. Result issuance 1–3 days was correctly separated. Source: Citizen's Charter, LSPU Entrance Examination.

### Q7 · aq_07_id_validation_process · PASS
COR from Registrar, student ID from Business Affairs, OSAS validation, evaluation form, 4 minutes, no fee. That matches the ID Validation charter card. Visible source title was “Processing of Student ID ID Processing,” which may be a neighboring card rather than ID Validation.

### Q8 · aq_08_fail_more_than_75_percent · FAIL
Returned a broken table dump (“Percentage — load”, “75% or more demic units — to enroll”). It did not say dismissal from the college, the nine-unit condition, or 100% permanent disqualification.

### Q9 · aq_09_faculty_teaching_load · ROLE-GATED
Stock student insufficient-information reply plus ticket prompt. Teaching load is in the Faculty Manual (Dean assigns load; 40 hours/week; 18-hour teaching maximum). **Expected for student role.**

### Q10 · aq_10_faculty_responsibilities · ROLE-GATED
Same student refusal. Faculty commitments are in Faculty Manual Section III.A. **Expected for student role.**

### Q11 · aq_11_honorable_dismissal · PARTIAL
Got the core definition: voluntary withdrawal with Registrar consent. Missed parent/guardian signed petition, settle indebtedness, may not be readmitted, and that suspension / dropping / expulsion does not get honorable dismissal. Added “without being penalized for failure or misconduct” and mixed in Withdrawal Guidelines / Conditions. Sources: Handbook Article 12 Honorable Dismissal plus two withdrawal sections.

### Q12 · aq_12_university_president · PARTIAL
Named Dr. Mario R. Briones, which is what the dated Handbook / Faculty Manual lists say. The pending case treats “current” as unverified. The answer stated he **is** the current president and added May 22 2019, Flexible Learning, and ISO 9001:2015, which are not in the pending supporting passages. Sources: Handbook Administrative Officials and Mission.

### Q13 · aq_13_out_of_scope_weather_mars · PASS
Refused. Did not invent Martian weather. Stock student out-of-scope / insufficient-information message. Ticket prompt is extra, not a factual error.

### Q14 · aq_14_insufficient_wifi_password · PARTIAL
Did not invent a Wi-Fi password. Then added LSPU Portal (`myaccount.lspu.edu.ph`) and IT Support instructions that are not in the evaluation corpus. The pending case has no Wi-Fi passage.

## What this does not do

- Does not fill Admin Overview Answer Correctness / Faithfulness / Relevance / Citation Accuracy.
- Does not mark the 14 cases `labeled` in `rag_eval_dataset.json`.
- Does not produce RAGAS 0–1 scores.
- Does not change retrieval or classification gold.

Citation precision/recall stay **unscored**. Only on-screen source titles were captured, not chunk IDs.
