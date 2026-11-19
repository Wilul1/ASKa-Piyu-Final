# Stage 3.1B — QA evaluation dataset authoring

Implemented 2026-11-09. Dataset authoring and Stage 2 validation only. No chatbot execution, judging, citation scoring, migrations, API/UI changes, commits, pushes, or deploys.

## 1. Dataset file and version

| Field | Value |
|---|---|
| Path | `backend/benchmarks/evaluation/qa_citation_eval_dataset.json` |
| Dataset version | `2026-11-09-v1` |
| Experiment family | `qa_citation_v1` |
| Annotation method | `ai_assisted_grounded_generation` |
| Generation model | `cursor-grok-4.6` |
| Generation prompt version | `qac-gen-v1-stage3.1b-20261109` |
| Dataset JSON sha256 | `34d9885bac22a1ecbc903acdd32876a796db7bc83a055829a506bdf017f34d50` |
| Corpus identity | locked extract digests (not the dataset JSON hash) |
| `evaluation_ready` | `true` |

Audit (not a live dataset): `backend/benchmarks/evaluation/qa_citation_eval_dataset.generation_audit.json`

Authoring helper: `backend/benchmarks/evaluation/qa_citation_contract/build_qa_citation_eval_dataset.py`

## 2. Total cases

**36** unique `case_id`s.

## 3. Category and difficulty distributions

### Category

| Category | Count |
|---|---|
| Academic Policies | 11 |
| Student Services | 8 |
| Fees and Payment | 6 |
| Enrollment and Registration | 4 |
| Student Records | 3 |
| University Forms and Documentary Requirements | 2 |
| Scholarships and Financial Assistance | 1 |
| Admissions | 1 |

### Difficulty

| Difficulty | Count |
|---|---|
| easy | 13 |
| medium | 13 |
| hard | 5 |
| conflict | 1 |
| insufficient_evidence | 4 |

## 4. Answerable vs insufficient-evidence

| Case type | Count |
|---|---|
| `labeled_student_support` (answerable) | 32 |
| `insufficient_evidence` | 4 |

Insufficient-evidence cases have `reference_answer=null` and empty supporting IDs/evidence.

## 5. Evidence verification

For every answerable case:

- Supporting chunk IDs exist in the locked extract (`chroma_record_extraction_20261104T104214Z.json`).
- Document ID and chunk index match the extract record.
- Every excerpt is a verbatim contiguous substring of that record's `text` (no case-folding or whitespace collapsing).
- The Stage 2 loader (`load_qa_citation_dataset`) accepted the file.

Corpus identity on the dataset matches the lock:

- `identity_digest` `fcb324dad73c41684e771defec0a36937ddde014df858c3f020aaf914774c85b`
- `metadata_text_digest` `7cec45b38d017d17f4f7b39abf3dc2d52a4f6f832b179ea2b70c37c6086262d7`

The builder refuses to write a case whose excerpt is missing from the extract.

## 6. Faculty-question exclusion

Loader `faculty_scope_violations` was run on every case `question`, `category`, and `reviewer_notes`: **0 hits**.

Rejected before inclusion (see generation audit):

- Faculty teaching-load / faculty-member questions.
- The `Brand New Article` placeholder FAQ.

A student question about a library service whose Charter *who-may-avail* line also lists other client groups remains a student-audience case. Graduate-student load and LOA questions are student inquiries, not employee policies.

## 7. AI generation provenance

- Candidates were drafted while inspecting locked extract titles and text.
- Kept cases were evidence-checked against the extract (IDs + verbatim excerpts).
- **AI-generated reference answers are not human-verified.** The dataset notes and audit file state this explicitly (`human_verified: false`).
- Rejected or reclassified candidates are listed in the audit file, not mixed into live cases as if they passed.

## 8. Stage 2 loader and tests

```
backend/venv/Scripts/python.exe -m pytest tests/test_qa_citation_dataset.py tests/test_qa_citation_metrics.py tests/test_qa_citation_capture.py -q
86 passed
```

Includes `test_live_qa_citation_eval_dataset_loads_through_stage2_loader`. The validator was not weakened.

## 9. Representative cases

**Easy, single-chunk fee** — `qac_001_tor_undergrad_fee`  
How much does a Transcript of Records cost per page if I am an undergraduate student?  
Chunks: `da4a1832-7242-4e94-8ba6-bc0b9f2294bf::1`

**Medium, multiple cards** — `qac_012_good_moral_by_status`  
What document do I present for a Good Moral certificate if I am still an undergraduate, an alumnus, or a transferee?  
Chunks: `…::15`, `…::16`, `…::17` on the Charter document.

**Hard, two handbook sections** — `qac_024_retention_warning_to_dismissal`  
Warning / probation / dismissal thresholds.  
Chunks: `cec01713-c1ba-4061-9404-ffaa1d8e70dd::66`, `…::67`

**Conflict in the corpus** — `qac_029_absence_drop_threshold_conflict`  
Undergraduate absence text says “twenty percent (25%)”; dropping says 25% of class hours; graduate attendance says 20%. The reference answer reports the clash and does not pick a winner.  
Chunks: `…::107`, `…::81`, `…::162`

**Insufficient evidence** — `qac_033_wifi_password`  
Campus Wi-Fi password. `reference_answer=null`, no chunk IDs. The extract has no password.

## 10. Known limitations

- Reference answers are AI-assisted and extract-grounded, **not** human-reviewed gold.
- Some Citizen's Charter cards are OCR-broken (requirement lines run together). Answers stay inside those lines and do not invent missing labels (for example P30.00/page and P137 on the TOR card are listed but not assigned to a document type).
- Charter “Who May Avail” lines are sometimes broader or narrower than the handbook policy for the same topic; only the absence-percentage clash was labeled `conflict`.
- Coverage is meaningful rather than exhaustive: 36 cases, not every student service.
- `qa_citation_eval_dataset.generation_audit.json` is provenance only. It is not a live dataset and must not be loaded as one.

## 11. Scope confirmation

Did **not** occur:

- Chatbot / `answer_qa_question` benchmark execution
- AI judging
- Citation claim extraction or citation scoring
- Database tables or migrations
- API routes
- Flutter UI changes
- Classification or retrieval evaluation changes
- Historical result edits
- Production data or chatbot behavior changes
- Commits, pushes, or deployments

**Stop.** Wait for explicit approval before executing the live answer-capture benchmark.
