# Stage 3.1C — Targeted QA dataset corrections

Implemented 2026-11-09. Dataset corrections and Stage 2 re-validation only. No chatbot execution, judging, citation scoring, migrations, API/UI changes, commits, pushes, or deploys.

The Stage 3.1B independent audit recommended **DO NOT APPROVE LIVE CAPTURE** because 18 cases needed correction. This stage corrects those cases only.

## 1. Dataset identity

| Field | Value |
|---|---|
| Live path | `backend/benchmarks/evaluation/qa_citation_eval_dataset.json` |
| Corrected version | `2026-11-09-v1.1` (revision of `2026-11-09-v1`) |
| Original preserved | `backend/benchmarks/evaluation/qa_citation_eval_dataset.2026-11-09-v1.json` |
| Original sha256 | `34d9885bac22a1ecbc903acdd32876a796db7bc83a055829a506bdf017f34d50` |
| Corrected sha256 | `81f66f25d007f373512936880edca530c4f2137377ee5601fbb155fe81455972` |
| Experiment family | `qa_citation_v1` |
| Annotation method | `ai_assisted_grounded_generation` |
| Generation provenance | unchanged: `cursor-grok-4.6` / `qac-gen-v1-stage3.1b-20261109` |
| Human verified | **false** |
| `evaluation_ready` | `true` |
| Corpus lock | unchanged (691 chunks; both extract digests) |

Correction audit: `backend/benchmarks/evaluation/qa_citation_eval_dataset.correction_audit.json`

Original generation audit left unmodified: `backend/benchmarks/evaluation/qa_citation_eval_dataset.generation_audit.json` (copy: `qa_citation_eval_dataset.generation_audit.2026-11-09-v1.json`)

Helper: `backend/benchmarks/evaluation/qa_citation_contract/apply_stage3_1c_corrections.py`

## 2. Files modified and created

**Modified**

- `backend/benchmarks/evaluation/qa_citation_eval_dataset.json` — 18 cases corrected; version `2026-11-09-v1.1`

**Created**

- `backend/benchmarks/evaluation/qa_citation_eval_dataset.2026-11-09-v1.json`
- `backend/benchmarks/evaluation/qa_citation_eval_dataset.generation_audit.2026-11-09-v1.json`
- `backend/benchmarks/evaluation/qa_citation_eval_dataset.correction_audit.json`
- `backend/benchmarks/evaluation/qa_citation_contract/apply_stage3_1c_corrections.py`
- `backend/benchmarks/evaluation/qa_citation_contract/STAGE3_1C.md`

**Not modified**

- `qa_citation_eval_dataset.generation_audit.json` (original v1 provenance)
- Stage 2 schema, loader, metrics
- Corpus lock / extract
- The 18 unlisted cases, including all four insufficient-evidence cases
- Supporting chunk ID lists (no silent chunk additions)

## 3. Case-by-case change log

Questions, categories, difficulty, and supporting chunk IDs were not changed.

### Trim gold to the question

| Case | Change |
|---|---|
| `qac_004` | Gold is now Fees None only. Dropped office, who-may-avail, and 10–38 minutes. |
| `qac_008` | Gold is now cum laude 1.46–1.75 only. Sibling honors remain in the table excerpt as context. |
| `qac_009` | Gold is now Guidance and Counseling + walk-in. Dropped requirements and 1–2 hours. |
| `qac_021` | Gold is now Business Affairs Office + Students/Employees/Alumni. Dropped COR, fee, and 4 minutes. |
| `qac_030` | Gold is now who-may-avail and LSPU ID. Dropped fee and 10 minutes. Office line kept as evidence for “Library service.” |

### Expand excerpts from already-cited chunks

| Case | Change |
|---|---|
| `qac_005` | Added ID requirement and “present ID for student-number verification” from `::3`. |
| `qac_014` | Added HD/LOA entitlement and matriculation/registration exception from `::52`. |
| `qac_017` | Added 1.1 prescribed-uniform sentence and extended 1.3 through jeans/maong. |
| `qac_020` | Extended the transferee list through PSA birth/marriage and 2.13 extras. |
| `qac_022` | Added Colleges office, submit-letter, and verify/forward/inform agency action. |
| `qac_023` | Added 3.1–3.3 refund percentages from already-cited `::52`. |
| `qac_025` | Added 5.3.1, 5.3.2, and the full special-removal Dean-petition / P100 sentence. |
| `qac_027` | Expanded excerpt to include the graduate LOA-form sentence. |
| `qac_028` | Added indebtedness and disciplinary-exclusion sentences from `::118`. |

### Preserve OCR / ambiguity

| Case | Change |
|---|---|
| `qac_018` | Gold quotes stored OCR-broken requirement lines, including “and BIR Office,” instead of reconstructing clean form names. |
| `qac_019` | Gold keeps the garbled currently-enrolled / shall-enroll-after sentence and stored “Republic Act No. 10687.” Does not pick RA 10931. |
| `qac_025` | Gold quotes stored 5.3.1 (“from the removed within the prescribed period”) and states that it is OCR-broken. |
| `qac_029` | Gold reports three distinct passages: undergraduate “twenty percent (25%)” day-session wording, undergraduate ≥25% of semester class hours, and graduate 20%. Does not treat them as two competing thresholds for the same student group. Does not pick a winner. |
| `qac_032` | Gold keeps the split “All old College” / “Students, Old GSAR Students” portal lines and does not join them into a returning-college enlistment rule. COR viewing for new/old college students is stated separately. |

## 4. Stage 2 loader and tests

```
backend/venv/Scripts/python.exe -m pytest tests/test_qa_citation_dataset.py tests/test_qa_citation_metrics.py tests/test_qa_citation_capture.py -q
86 passed
```

`load_qa_citation_dataset` accepted `2026-11-09-v1.1` (36 cases). Loader membership is textual, not semantic correctness.

## 5. Evidence verification

- Corpus identity digests unchanged and matched.
- Every excerpt is a verbatim contiguous substring of the locked extract record `text`.
- Every evidence `chunk_id` is in that case’s original `supporting_chunk_ids`.
- No new supporting chunks were added.
- Insufficient-evidence cases remain `reference_answer=null` with empty evidence.

## 6. Independent re-audit (all 36)

Faculty-as-audience check on `case_id` / `question` / `category` / `reviewer_notes`: **0 hits**. `Faculty` appears only in `qac_030` gold, quoting the Charter who-may-avail line for a student-available library service.

Category and difficulty distributions are unchanged: Academic Policies 11, Student Services 8, Fees 6, Enrollment 4, Student Records 3, Forms 2, Scholarships 1, Admissions 1; easy 13, medium 13, hard 5, conflict 1, insufficient_evidence 4.

Near-duplicates remain the same intentional ladders (001/011, 010/028, 014/023, 015/024).

| Case ID | Verdict | Note |
|---|---|---|
| qac_001 | PASS | Undergraduate TOR P75 only. |
| qac_002 | PASS | Enrollment office = Registrar. |
| qac_003 | PASS | ID validation COR + Student ID. |
| qac_004 | PASS | Trimmed to Fees None. |
| qac_005 | PASS | ID presentation now excerpted. |
| qac_006 | PASS | 1.00 = 99–100 Excellent. |
| qac_007 | PASS | Cross-enrollee definition only. |
| qac_008 | PASS | Gold trimmed to cum laude. |
| qac_009 | PASS | Gold trimmed to office + walk-in. |
| qac_010 | PASS | HD definition. |
| qac_011 | PASS | Unlabeled P30/P137 remain unlabeled. |
| qac_012 | PASS | Good Moral docs by status; no invented fee. |
| qac_013 | PASS | Three shifting conditions. |
| qac_014 | PASS | Entitlement exception now excerpted. |
| qac_015 | PASS | Warning vs probation. |
| qac_016 | PASS | Undergraduate overload cap. |
| qac_017 | PASS | 1.1/jeans now excerpted (gold still wider than the asked PE/Wed/Fri schedule because this case was authorized for excerpt expansion, not gold trim). |
| qac_018 | PASS | OCR labels quoted, not cleaned. |
| qac_019 | PASS | Garbled dual eligibility preserved. |
| qac_020 | PASS | PSA/2.13 now excerpted. |
| qac_021 | PASS | Gold trimmed to office + who-may-avail. |
| qac_022 | PASS | Process sentences now excerpted. |
| qac_023 | PASS | 75/50/none schedule now excerpted. |
| qac_024 | PASS | Warning / probation / dismissal. |
| qac_025 | PASS | 5.3.1 kept as stored OCR; special-removal context excerpted. |
| qac_026 | PASS | Graduation rules. |
| qac_027 | PASS | LOA-form sentence now excerpted. |
| qac_028 | PASS | Debt and disciplinary exclusion now excerpted. |
| qac_029 | PASS | Three context-distinct passages; no single threshold. |
| qac_030 | PASS | Gold trimmed to who-may-avail + ID. |
| qac_031 | PASS | Graduate 9-unit load. |
| qac_032 | PASS | Portal enlistment OCR split preserved. |
| qac_033 | PASS | No Wi-Fi password in corpus. |
| qac_034 | PASS | No Sunday shuttle in corpus. |
| qac_035 | PASS | No lost-ID replacement fee in corpus. |
| qac_036 | PASS | No library opening hours in corpus. |

**REMOVE:** none.

Special OCR/fees recheck: TOR `qac_001`/`qac_011` still do not assign P30/P137. Good Moral `qac_012` still keeps COR / TOR / Certificate of Transfer / alumni step options separate.

Special `qac_029` recheck: undergraduate day-session “twenty percent (25%)”, undergraduate semester-hours 25%, and graduate 20% are reported as different stored passages. Gold does not guess which supersedes which.

## 7. Remaining limitations

- Reference answers remain AI-assisted and extract-grounded, **not human-verified**.
- Citizen's Charter OCR is still messy. Corrected gold quotes or conservatively summarizes stored wording; it does not restore a clean source PDF.
- `qac_017` gold still includes prescribed-uniform and jeans sentences because Stage 3.1C authorized excerpt expansion for that case, not gold trim.
- Coverage is unchanged (36 cases). Late-registration fine, Charter dropping-of-subjects, and library circulation remain unused supported topics; size was not increased.
- Passing the Stage 2 loader proves verbatim membership, not that a future chatbot answer is correct.

## 8. Scope confirmation

Did **not** occur:

- Chatbot / `answer_qa_question` execution
- Live answer capture
- AI judging
- QA or citation scoring
- Database tables or migrations
- API routes
- Flutter UI changes
- Classification or retrieval evaluation changes
- Historical result edits
- Production data or chatbot behavior changes
- Commits, pushes, or deployments

**Stop.** Wait for explicit approval before executing live answer capture.
