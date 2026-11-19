# Live production answer-quality evaluation — human-captured judgments

Run ID: `aq_live_prod_human_captured_20261104T164548Z`  
Created: 2026-11-04T16:45:48Z

**Overall: 1 of 2 answers satisfactory.**

These are live-chatbot correctness judgments supplied by the user. They are not local fallback answers and not scores invented by this agent. Full verbatim transcripts were not pasted into the Cursor message, so answer text is not reconstructed here.

## Results

| Case | Question | Answer correctness | Citation verification |
| --- | --- | --- | --- |
| aq_04_dropping_fee_multi_document | How much does it cost to drop a subject? | **PASS** (satisfactory) | **Pending** |
| aq_08_fail_more_than_75_percent | What happens if I fail more than 75% of my units? | **FAIL** | **Pending** |

## aq_04 — PASS (answer correctness)

Human-supplied observation:

- The live chatbot stated the Dropping of Subjects fee as **P30.00**.
- It also provided the procedure and estimated processing time.
- Marked **satisfactory**.

Citation details were not supplied. Citation precision/recall remain **null**, not zero.

Approved gold citation IDs (not verified against the live display):

- `da4a1832-7242-4e94-8ba6-bc0b9f2294bf::97`
- `cec01713-c1ba-4061-9404-ffaa1d8e70dd::82`

## aq_08 — FAIL (answer correctness)

Human-supplied observation:

- The live chatbot returned **fragmented table content**.
- It did **not** clearly explain what happens when a student fails more than 75% of their units.
- No policy consequence was invented. The answer is **not** marked correct.

Citation details were not supplied. Citation precision/recall remain **null**, not zero.

Approved gold citation IDs (not verified against the live display):

- `cec01713-c1ba-4061-9404-ffaa1d8e70dd::67`
- `cec01713-c1ba-4061-9404-ffaa1d8e70dd::69`

## Metrics that remain unavailable

| Metric | Value |
| --- | --- |
| answer_correctness numeric 0–1 | null (human pass/fail only) |
| answer_relevancy | null |
| faithfulness | null |
| citation_set_precision | null (pending) |
| citation_set_recall | null (pending) |

## What this is not

- Not the local OpenRouter-401 fallback run `aq_subset_20261104T163426Z`.
- Not a completed agent login to the live UI (`aq_live_prod_BLOCKED_20261104T164045Z`).
- Not a reconstruction of the live wording.
- Production was not modified. Nothing was deployed. The pending dataset was not changed.
