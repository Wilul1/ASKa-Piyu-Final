# Live production answer-quality evaluation — NOT EXECUTED

Run ID: `aq_live_prod_BLOCKED_20261104T164045Z`  
Created: 2026-11-04T16:40:45Z

**Neither benchmark question was submitted. No live chatbot answers were captured. This is not a successful evaluation.**

## What was checked (read-only)

- Website: https://aska-piyu-6b05cafc5bd1.herokuapp.com/
- Public `/health`: `{"status":"ok","service":"aska-piyu"}`
- Login page URL exists but is a Flutter SPA; this session cannot fill the login form.

## Why the live UI run stopped

1. This Cursor session has **no interactive browser tools**, so credentials cannot be entered into the website login form and the student chatbot cannot be operated.
2. Login credentials were **not present in this Cursor conversation**. The request referred to credentials from a ChatGPT conversation, which is not available here.
3. Repo office/bootstrap credential files were **not used**.
4. Local `answer_qa_question()` was **not** called as a substitute.
5. The previous local fallback run (`aq_subset_20261104T163426Z`) was **not** copied in as live results.

## Intended cases (not submitted)

| Case | Question | Submitted |
| --- | --- | --- |
| aq_04_dropping_fee_multi_document | How much does it cost to drop a subject? | No |
| aq_08_fail_more_than_75_percent | What happens if I fail more than 75% of my units? | No |

## Metrics

All live metrics are **null** (unavailable), not zero:

- answer_correctness: null
- answer_relevancy: null
- faithfulness: null
- citation_set_precision: null
- citation_set_recall: null

Live citation IDs were not observed, so gold-ID precision/recall was not calculated.

## Distinction from the local fallback run

| | This attempted live run | Local run `aq_subset_20261104T163426Z` |
| --- | --- | --- |
| Interface | Production website chatbot | Local `answer_qa_question()` |
| Answers | None captured | Generation-error fallback after OpenRouter 401 |
| Status | not_executed | evaluated (fallback, not Groq) |

## Production safety

No documents, tickets, settings, deploys, or migrations were changed. The pending dataset and previous run artifacts were not modified.

## What is needed to complete this evaluation

1. Paste the authorized student-account email and password into this Cursor chat (they will be used only in the live login form and will not be written into repo files).
2. Enable an interactive browser in this session (Cursor browser tools, or Claude in Chrome) so the login form and chatbot can be operated.
3. Re-run this request after those two items are available.
