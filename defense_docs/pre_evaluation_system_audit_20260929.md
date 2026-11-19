# ASKa-Piyu — Whole-System Pre-Evaluation Audit

**Date:** 2026-09-29
**Type:** Read-only investigation. No application code, tests, configuration, or data were modified. No production mutation occurred.
**Scope:** Frontend (Flutter), backend (FastAPI/PostgreSQL/Chroma), deployment/ops, and a bounded live-production probe of the public Ask ASKa-Piyu endpoint (anonymous, non-destructive).

---

## A. Executive Readiness Summary

ASKa-Piyu is in materially better shape than a typical pre-evaluation capstone system. Across authentication, authorization, ticket routing/prioritization, SQL/upload security, CORS, secret hygiene, and error-leakage, the codebase shows evidence of prior, deliberate hardening passes — most high-risk areas investigated came back **PASS with concrete evidence**, not assumption. **No P0 (evaluation-blocking) issues were found.**

Four **P1** issues exist, none of which prevent an evaluator from completing a bounded demo, but each has a real, evidence-backed chance of causing confusion or looking unfinished if specifically probed:

1. The staff **"Transfer ticket" dialog is misleadingly named** — office-reassignment capability exists correctly-gated in the backend, but no frontend screen (including the admin path) ever wires it up; every real user, including admins, sees only a status editor.
2. The **known disciplinary-table ingestion defect** is real, has a confirmed root cause (a geometric-heuristic PDF extractor + a paragraph-blind character-slicing chunker), is **not architecturally isolated** to one document, but is **effectively contained today** to dense tables inside Handbook/Faculty-Manual PDFs specifically.
3. **Out-of-scope (OOS) detection is a hand-maintained keyword allowlist** that does not cover creative-writing/task-execution prompts (e.g. "write me a poem") — these fall through to normal generation and rely solely on prompt-level grounding instructions, not a hard refusal.
4. **No rollback script or documentation exists in-repo** — the git-patch/release-branch/backup-then-rsync rollback procedure actually used this session exists only as unwritten operator knowledge.

Twelve **P2** findings (dead code, inconsistent error-message sanitization, missing nginx security headers, minor DB-integrity/performance asymmetries) are documented for post-evaluation cleanup and do not materially affect evaluation readiness.

**Verdict: READY_AFTER_BOUNDED_FIXES** (see §Z for full reasoning, §W for the exact bounded fix list).

---

## B. Verified Production Baseline

Independently discovered via SSH — not assumed from the task prompt.

| Item | Value |
|---|---|
| Branch | `release/auth-redesign-20260929` |
| HEAD SHA | `bcdb4afb84235fc8083089efcccf0e6361c74ade` |
| Tracked working-tree status | Clean — zero modified/staged tracked files |
| Previous release SHA (ancestor) | `822d9ce258f580e00e31fb099777c5269cdf325b` (My Tickets mobile-density) |
| Ancestor lineage confirmed | `bcdb4af` → `822d9ce` → `2fb471d` (portal refresh) → `1ab2cd9` (homepage redesign) → `b0275a1` (office selection) — all prior approved releases present |

**Container health** (`docker ps`):

| Container | Status |
|---|---|
| `aska-piyu-api` | Up 2 days (healthy) |
| `aska-piyu-nginx` | Up 3 weeks |
| `aska-piyu-postgres` | Up 2 months (healthy) |

**Persistent volumes present:** `aska_attachments`, `aska_chroma`, `aska_documents`, `aska_easyocr`, `aska_kb_media`, `aska_pgdata` — all six expected volumes exist.

**Disk:** 66% used, 9.6G available — not a near-term concern.

**Environment variable presence** (values never printed): all expected `ASKA_*` variables are present and non-empty. Spot-checked two specifically dangerous-sounding flags without exposing values — confirmed **not** truthy in production:
- `ASKA_ALLOW_DESTRUCTIVE_RESET` — not truthy
- `ASKA_ALLOW_ADMIN_API_KEY` — not truthy

`ASKA_ALLOW_PUBLIC_SIGNUP` and `ASKA_TRUST_PROXY` are truthy — both expected/intended (public signup is a real feature; trust-proxy is required behind nginx).

**Local repo untracked clutter:** A large amount of pre-existing, unrelated untracked files (citation-grounding benchmark JSON artifacts, stale `.env.bak_*` files, old deploy tarballs) exists in the local working tree from earlier, unrelated development sessions. These are **not a production defect** — they are not deployed, not committed, and were left untouched during this audit — but see §Q for a packaging/handoff hygiene note regarding `.env.bak_*` files specifically.

---

## C. Automated Test/Build Baseline

| Check | Result |
|---|---|
| `flutter analyze` (whole repo) | 67 issues — all pre-existing lints/warnings (unused elements, deprecated `dart:html`, `BuildContext`-across-async-gap infos). Two flagged as `unnecessary_null_comparison`/`invalid_null_aware_operator` in `article_file_drop_web.dart` are type-level dead-code artifacts from `dart:html`'s typing, not runtime logic bugs — drag-and-drop file upload is not broken. |
| `flutter test` (full suite) | **276/276 passing**, 0 failures — matches historical baseline. |
| Flutter release build | Not re-run in this audit (already verified in the immediately preceding deployment task on this exact commit). |
| Backend test suite | **Not executed.** `backend/tests/conftest.py` hardcodes `REQUIRED_TEST_DB_NAME = "aska_piyu_test"` and refuses to run against any other database — a real PostgreSQL test DB, not sqlite/in-memory. Per this audit's explicit caution rule, tests were not run without independently confirming a safe local test DB is provisioned and reachable. Structural review only: 80 test files exist under `backend/tests/`, including dedicated coverage for auth, ticketing, and office resolution (`test_auth.py`, `test_auth_abuse.py`, `test_ticketing.py`, `test_ticket_office_resolver.py`, `test_ticket_kb_e2e.py`). Zero `@pytest.mark.skip`/`xfail` markers found. |
| Test-quality spot check | Flutter test assertions sampled (`widget_test.dart`, `admin_all_tickets_page_test.dart`, `office_account_page_test.dart`) assert on user-visible text/keys/overflow behavior, not private class names or pixel values — a maintainable pattern, not a defect. |

---

## D. P0 — Blockers Before Evaluation

**None found.** Every area investigated with evaluation-blocking potential (server-side authorization, ticket ownership, routing/priority contract integrity, SQL injection, upload path traversal, CORS wildcard risk, secret history exposure, citation-verification honesty) came back PASS with concrete evidence. See §I–§R for the full PASS evidence trail.

---

## E. P1 — Important Before Evaluation If Practical

### P1-1: Staff "Transfer ticket" dialog is misleadingly named — reassignment is unreachable in the shipped app
- **Evidence:** Backend: `PATCH /tickets/{ticket_id}` → `update_ticket` (`backend/app/services/ticketing.py:243`) genuinely supports office reassignment, correctly gated to `role == "admin"` (`ticketing.py:262`). Frontend: `flutter_app/lib/screens/staff_ticket_console.dart:1072` titles the dialog `'Transfer ticket'`; the office-reassignment field only renders `if (widget.allowReassignment)` (line 1094). **The only instantiation of `_StaffTicketConsole` anywhere in the codebase** is `admin_management_pages.dart:370-389`, which hardcodes `allowReassignment: false` and `officeOptions: const []`. No other call site exists (confirmed via full-repo grep) — meaning the office-reassignment UI path is dead for every role, including admin.
- **Reproduction:** Static code inspection (definitive — Dart/Flutter has no reflection, so an unreferenced private widget branch cannot be reached dynamically).
- **Expected vs Actual:** A control titled "Transfer ticket" should move a ticket between offices. Actual: it is functionally a status-editor for 100% of real users.
- **Evaluation impact:** High. This is a highly plausible thing for an IT-expert evaluator to click on and test, and the mismatch between the label and the actual behavior reads as either a bug or an incomplete feature.
- **Recommended action:** Rename the dialog for its actual behavior (e.g., "Update status") in the office-staff instantiation, or wire a real admin-facing reassignment entry point if one should exist. Not implemented — description only, per audit scope.

### P1-2: Disciplinary-table ingestion defect — confirmed root cause, confirmed NOT one-document-isolated, but effectively contained today
- **Evidence:** All non-Citizen's-Charter documents (Student Handbook, Faculty Manual) are routed to `build_handbook_policy_document()` (`handbook_policy_processor.py`), which works only on geometrically-flattened text from `pymupdf_extractor.py:156-231` (`_rows_to_text(_cluster_rows(...))`), a Y/X-clustering heuristic. PyMuPDF's native, reliable `page.find_tables()` output (`table_regions`) **is captured but only ever consumed for Citizen's-Charter-classified documents** (`citizen_charter_extractor_v2.py:90`). Chunk boundaries in `chunking.py:96-160` are paragraph-based (`\n\n`); a table with only single-newline rows has no internal paragraph break, so an oversized table block falls to `_slice_oversized_block()` (`chunking.py:72-93`) — **plain character-count slicing with zero row/column awareness** — the most likely point a dense offense/penalty table gets cut mid-row. Real, if imperfect, defensive heuristics do exist in `handbook_policy_processor.py` (`_is_table_style_row`, `_is_continuation_clause`, a `"disciplinary_rule"` classification tag), showing this was not an unacknowledged gap, just an incompletely-solved one.
- **Containment answer:** The defect is architecturally general (any dense table in any Handbook/Faculty-Manual-classified PDF is exposed to the same flattening path), but in practice the blast radius is narrow today: fee schedules and processing-time tables live in the Citizen's Charter, which correctly uses the table-region-aware structured extractor. No separate academic-calendar ingestion path exists in the codebase.
- **Reproduction:** Code inspection only; Chroma/production data was not queried for this item.
- **Evaluation impact:** Moderate-to-high specifically if the evaluator asks a disciplinary/offense-penalty question — a plausible, on-brand question for a "campus support assistant." Confirmed via my own direct DB sample (see §M) that **no standalone disciplinary/offense article exists in `published_articles`** — this content, if surfaced at all, comes only through raw RAG retrieval from the Handbook PDF chunks, not a curated KB article.
- **Severity justification (P1, not P0):** Contained, non-crashing, content-quality degradation in a narrow content class with partial existing mitigation — not a pipeline failure, security issue, or data corruption.
- **Recommended action:** Route Handbook/Faculty-Manual table regions through the same structured path already built for the Citizen's Charter, and/or make the chunker table-boundary-aware so `_slice_oversized_block` can never cut inside a detected table row-run. **Not recommended for pre-evaluation implementation** — see §X.

### P1-3: `list_tickets` has no pagination; combined with frontend polling, creates unbounded read cost
- **Evidence:** `backend/app/services/ticketing.py:186-232` (`list_tickets`) builds `session.query(Ticket).options(joinedload(Ticket.user), joinedload(Ticket.assigned_office_ref), joinedload(Ticket.replies), joinedload(Ticket.attachments))` with status/priority/office filters only — no `.limit()`/`.offset()` anywhere in the function. An admin/office actor receives every ticket ever created, every call. `flutter_app/lib/screens/my_tickets_page.dart:178` and `staff_ticket_console.dart:786` poll this (and the ticket-detail endpoint) every 8s/4s respectively — correctly disposed (`dispose()` cancels all three located timers), but not rate-limited at the nginx layer (only `/auth/*` and `/qa|student/ask` have `limit_req` zones configured; the generic `/tickets` catch-all does not).
- **Reproduction:** Code inspection only — not reproduced against a live DB.
- **Evaluation impact:** Low at current production scale (73 real tickets total, confirmed via direct DB count — see §M) but a real, reproducible-by-inspection scaling risk that would surface as slow admin/office ticket views as history accumulates across semesters.
- **Recommended action:** Add `limit`/`offset` (or cursor) pagination to `list_tickets` and its route caller, matching the pattern `ticket_notifications.py:90` already uses (`.limit(100)`). **Not recommended for pre-evaluation implementation** given the current dataset size makes this unlikely to manifest during a bounded demo — see §X.

### P1-4: No rollback script or documentation exists in-repo
- **Evidence:** Only `scripts/backup_aska.sh`/`.bat` exist under `scripts/`; no `_prod_rollback.sh` or equivalent exists in `deploy/` or `scripts/` in the current checkout. `grep -n -i "rollback" DEPLOY.md README.md SETUP.md` returns zero matches. The actual, working rollback procedure (isolated release branch via `git format-patch`/`git am` against the exact discovered production HEAD, pre-deploy `cp -a` backup of `deploy/web`, `rsync -a --delete` restore for rollback) was executed correctly and repeatedly this session, but exists only as this session's operator knowledge, not as a repo artifact another operator could follow.
- **Evaluation impact:** Real operational-maturity/bus-factor gap. Does not block a functional demo, but is a legitimate finding for a system-evaluation audit of a production deployment.
- **Recommended action:** Document the exact steps into `DEPLOY.md` or a new `deploy/ROLLBACK.md`. Pure documentation — zero code/regression risk. **Recommended for pre-evaluation completion** — see §W.

---

## F. P2 — Post-Evaluation Improvements

| ID | Title | One-line evidence |
|---|---|---|
| P2-1 | OOS keyword allowlist doesn't cover creative/task prompts | `question_answering.py:6691` `_is_out_of_scope_query()` checks a fixed term tuple (weather, recipe, movie, etc.); no term for "poem"/"write"/"code"/"translate". Falls through to normal generation, relying on the system prompt (§N) as the only safeguard. |
| P2-2 | ~1,600 lines of genuinely unreachable code in `admin_panel_page.dart` | `flutter analyze`'s `unused_element` warnings (`_refreshArticleLibrary`, `_runRetrievalTest`, `_AdminAdvancedOptionsPanel`, `_UploadPanel`, `_SummaryChip`, `_GenerationMetric`, `_ResultPanel`, `_ValidationPanel`, `_StatisticsPanel`) confirmed genuinely dead via full-repo grep — an old retrieval-test harness and superseded panels left in place after the screen was refactored onto `AdminKbWorkspace`/`KbReviewAndPublishSection`. |
| P2-3 | Raw `error.toString()` shown to users on KB/article-admin screens | `admin_kb_article_library_section.dart:324,336,348,371,406,531`, `knowledge_article_edit_page.dart:421,460,491`, `admin_kb_article_shared.dart:526,702` show raw exception text (including raw HTTP response bodies via `AdminArticleRequestException.toString()`) — inconsistent with the `_friendlyError` pattern used on ticket/auth screens. |
| P2-4 | `nginx` container has no Docker healthcheck; `/health` is liveness-only | `docker-compose.yml` — postgres/api have `healthcheck:`, nginx doesn't. `backend/app/main.py:265-268` `/health` returns unconditional `{"status":"ok"}` with no DB check; a DB-aware `/health/database` exists but is admin-key-gated and not what the compose healthcheck polls. Documented design choice (docstring says "liveness probe"), not an accidental gap. |
| P2-5 | No `X-Content-Type-Options`/`X-Frame-Options`/CSP headers at the nginx layer | HSTS is correctly set (`nginx.https.conf:51`); the other three common hardening headers are absent. |
| P2-6 | `ArticleMedia.uploaded_by_user_id` not detached in `hard_delete_user` | `user_lifecycle.py`'s cleanup handles `PublishedArticle`/`Announcement`/ticket-related FKs but not `ArticleMedia`; degrades gracefully to a caught `IntegrityError` → HTTP 409 ("disable instead"), not a crash or corruption. |
| P2-7 | KB articles and ticket-statistics use unbounded Python-side reads instead of SQL-level limit/aggregation | `knowledge_base.py:69-95` fetches all published articles then paginates via Python list-slicing; `ticketing.py:446-459` `ticket_statistics` loads every ticket row to tally counts instead of SQL `GROUP BY`. Low impact at current KB/ticket volume. |
| P2-8 | "Mark all notifications read" silently no-ops on failure | `my_tickets_page.dart:318` — empty `catch (_) {}`, no retry/error feedback if the POST fails. (Sibling catches in the same file for notifications/office-list loading are deliberately and clearly documented as non-blocking; this one specific action-triggered catch has no feedback at all.) |
| P2-9 | `AdminPlaceholderPage` is an unused class | `admin_management_pages.dart:732` — distinct from the actively-used `_AdminPlaceholderPanel`; unreachable, minor cleanup only. |
| P2-10 | Backup script verifies `kb_media` far more rigorously than Postgres/Chroma/documents/attachments | `scripts/backup_aska.sh` does source/archive file-count reconciliation only for `kb_media/`; Postgres (`pg_dump`) and the other three data directories are checked only for nonzero exit / tar-readability. Asymmetric, not a known-broken path. |
| P2-11 | Packaging/handoff hygiene: local `.env.bak_*` files must not reach evaluators | `backend/.env.bak_local_nemotron_*` and similar untracked local backup files exist in the working tree (pre-existing, unrelated to this audit's changes). Not opened/read per credential-hygiene rules; filename pattern strongly suggests real local secrets. Not a code defect — a submission-packaging note. |
| P2-12 | Article-drop web widget has two type-level dead-code lints | `article_file_drop_web.dart:67,98` — `dart:html` typing marks a defensive null-check as unreachable. Cosmetic; drag-and-drop upload is not broken. |

---

## G. Areas That Passed With No Material Finding

Each below has file:line evidence in the source agent reports synthesized into this document; summarized here for brevity.

- **Token-based authentication**: HMAC-signed, expiry-checked, `is_active`-checked, and revocable via a `credentials_version` claim compared against the DB row (logout/password-change/disable invalidates all outstanding tokens).
- **Ticket ownership enforcement**: server-side `_can_view`/`_can_update` checks (not UI-hiding-only) correctly scope students/faculty to their own tickets, offices to their own queue, admin to all; a student passing another student's `ticket_id` gets a 403.
- **Payload-manipulation resistance**: a student cannot set `preferred_priority` (silently ignored unless actor is admin/office), cannot force arbitrary/fuzzy office assignment (ID-only resolution, 404s on invalid IDs), and cannot access the staff-only fuzzy-office-name resolution path.
- **Routing contract**: automatic routing is the true default; unresolved taxonomy labels correctly set `assigned_office_id = null` / `needs_manual_routing = true` **without** silently falling back to OSA (explicit `allow_default_fallback=False` + code comment naming this exact anti-pattern as the bug being prevented).
- **Priority contract**: a lone "urgent"/"asap"/"emergency" does not alone force Urgent priority — requires either a genuinely severe independent term or corroboration between an urgency word and an independent High-tier signal.
- **KB admin authorization**: publish/media endpoints require `role in {admin, office}` via Bearer token; destructive operations (Chroma reset/full rebuild) require `role == admin`; the legacy shared-key bypass auto-disables in production unless explicitly re-enabled, and startup validation refuses to boot in production if that bypass is enabled without a real key.
- **CORS**: no wildcard by default; production startup validation hard-blocks wildcard, empty, or localhost-only origin configuration.
- **SQL injection**: zero raw string-interpolated SQL found across the backend; all queries use SQLAlchemy ORM/parameterized calls.
- **Upload validation**: both ticket attachments and KB media sniff magic bytes (not client-claimed MIME), enforce size caps (10MB/5MB), and reject path-traversal attempts in filenames/IDs with `.resolve().relative_to(root)` re-validation.
- **Rate limiting**: real, in-process sliding-window limiter on login/signup/resend-verification/ticket-triage/KB-classify/QA-ask — not just mentioned in comments. The documented caveat (in-process limiter doesn't span multiple workers) is disclosed in a startup warning, consistent with the app being configured for a single worker.
- **Error leakage**: no route found returning raw exception text/tracebacks to the client on the *backend* side (KB/article-admin *frontend* screens are the exception — see P2-3).
- **Secret hygiene**: no real-looking hardcoded credentials in committed backend source (only test-fixture placeholders); `.env`/`.env.production` confirmed via `git log --all` to have **never** been committed to git history on any branch.
- **Citation verification (V2)**: genuine claim-level LLM entailment checking, not marker/keyword presence; explicitly fail-closed (`verify_citations` never raises — any failure yields an empty verified-citation list, never a blocked or silently-regenerated answer); the frontend maps every terminal verification state to an honest, distinct message and never presents unverified content as verified.
- **Grounding guardrail**: the system prompt sent to the LLM (`groq_answer_service.py`) contains explicit, real anti-fabrication instructions ("Never invent policies, requirements, offices, programs, campuses, dates, amounts, fees, processing times, or procedures") — a real, wired string, not just a comment.
- **LLM/network failure handling**: outbound Groq calls are timeout-wrapped (30s) end-to-end with typed exceptions, never a raw httpx/JSON exception escaping to the client; the orchestrator falls back through typed-answer templates to a context-derived fallback answer before ever surfacing a generic error; the Flutter client has its own 120s timeout with distinct friendly messages for timeout/network/429/401, and a `finally` block that always clears the loading state (no infinite spinner).
- **Ticket-to-KB conversion**: a real, fully wired workflow (not a stub) — resolved/closed tickets show a contextual "Convert to Knowledge Base" flow with a pre-filled FAQ draft and status round-tripping.
- **Admin CRUD screens** (`AdminOfficesPage`, `AdminUsersRolesPage`): complete, with debug-seed hooks marked `@visibleForTesting` and never reachable in the real runtime path.
- **Staff console states**: proper loading/error/three-way empty-state handling confirmed by code and existing widget tests.
- **Responsive/overflow risk in admin tables**: fixed-width table-header `Row`s that look like overflow suspects on paper are already confirmed safe at 400px by existing, passing narrow-layout widget tests (not just static suspicion).
- **Deployment ordering**: Postgres → API → nginx startup is correctly gated by `condition: service_healthy` healthchecks (not `depends_on` alone), with a 90s `start_period` on the API to allow for migration/model warm-up.
- **Postgres network exposure**: never published to a host port in the production compose file; a separate dev-only override file explicitly warns against public-VPS use.
- **Startup configuration validation**: the app refuses to start in production with a placeholder auth secret, a placeholder admin API key (if that auth mode is enabled), `ASKA_DATABASE_INIT_ON_STARTUP=true` (forcing explicit Alembic migrations instead of blind `create_all`), a missing database URL, or any of three CORS misconfiguration shapes.
- **Logging**: structured, level-scoped logging (not print-based), with an in-line comment recording a deliberate decision to keep one specific risky log call site at a lower level because it could embed a raw provider exception string — evidence of an actual security-conscious review, not a blanket fix.
- **No rebuild/fetch-loop bugs**: all 6 `Timer.periodic` call sites in the Flutter app are properly cancelled in `dispose()`; no widget `build()` method found triggering a network call directly (calls are centralized in service classes).

---

## H. Public/Student Journey Assessment

Verified via direct production requests and prior extensive screenshot verification from this session's own portal/homepage/My Tickets/auth redesign work (all still live at the confirmed production baseline):

- **Homepage**: navbar, hero, search, Resources, Quick Links (real live data — confirmed distinct article counts from local dev, e.g. "Academic Policies · 15 articles"), floating "Chat with ASKa-Piyu" control, Sign In/Sign Up entry points — all render correctly, zero console errors, on both desktop (1672px) and mobile (390px).
- **Knowledge Base**: category browsing, article listing, search bar present and functional at the UI level; navbar active-state underline present.
- **Ask ASKa-Piyu**: guest-accessible chat UI reachable without login ("Guests can ask a few questions. Sign in for more."), consistent with the backend's `get_optional_user` design.
- **No dead/broken links** were found in the areas exercised.
- **Mobile**: no horizontal overflow observed on any tested public page at 390px.

---

## I. Authentication/Authorization Assessment

See §G (PASS list) for the full evidence trail. Server-side enforcement — not UI-hiding — is confirmed for role gates, ticket ownership, and KB-admin access. Password visibility toggles, Remember Me, and Forgot Password (a real SnackBar-driven message, not a dead link) were directly functionally verified against production in this session's immediately preceding auth-redesign deployment. **Not independently re-verified in this audit:** whether email-verification status is checked server-side specifically at the ticket-creation code path (general auth/role enforcement was confirmed; this one specific gate was not traced to an exact line by any investigating agent) — see §Y.

---

## J. Ticketing/Routing/Prioritization Assessment

Routing and priority contracts both confirmed to match their intended design exactly (§G). Direct production DB sampling (read-only) cross-validates this empirically:

- 73 total tickets in production; **zero** have `assigned_office_id IS NULL` — meaning the "unresolved taxonomy → manual routing" path has not yet been exercised by real traffic (not a defect; simply means this exact contract hasn't had a live production trigger yet, only code/test coverage).
- Priority distribution: Low 36, Medium 22, High 15, **Urgent 0** — a reassuring empirical signal against false-positive urgency escalation, consistent with the confirmed corroboration-required logic.
- Status distribution: Closed 52, Open 15, Resolved 4, In Progress 2.

---

## K. Staff/Office Assessment

Office ticket queue has correct loading/error/three-way-empty states (§G). The one material finding is **P1-1** (§E) — the "Transfer ticket" dialog's misleading title, since office-reassignment is never actually reachable through it for any role in the shipped app.

---

## L. Admin Assessment

Admin dashboard, Offices, Users & Roles, and Ticket-to-KB conversion are complete, demonstrable workflows (§G). **P2-2** (dead retrieval-test-harness code in `admin_panel_page.dart`) and **P2-3** (raw exception leakage on KB/article-admin screens) are the two admin-surface findings worth a mention; neither prevents an evaluator from completing an admin task, but both would look unpolished if specifically triggered (opening dev tools / forcing a backend error during a demo).

---

## M. KB/Data-Quality Assessment

Direct read-only production sampling (this audit):

- 48 published articles total.
- 0 empty titles, 0 near-empty content, 0 duplicate titles.
- 20 of 48 (42%) have no `office` value — **but all 20 have real, substantive titles and correct categories** (e.g. "Academic Freedom," "Scholarship Grants," "Grading Requirements") — these read as genuine university-wide policy articles that don't map cleanly to one office, not an extraction failure. Not flagged as a defect without further UI-context confirmation of whether "office" is a required display field.
- Shortest article body: 470 characters (a legitimate short FAQ answer), not a truncation artifact.
- **No standalone disciplinary/offense/conduct article exists** in `published_articles` — cross-references P1-2's containment finding.
- Two `source_documents` rows both reference "LSPU Student Handbook.pdf" at 198 pages each, with slightly different `source_label` values (`"LSPU Student Handbook.pdf"` vs `"LSPU Student Handbook"`) — a **possible duplicate ingestion** worth a follow-up check, not confirmed as harmful (not traced further to whether both are referenced by live Chroma chunks).

A separate agent's local-dev-DB sample (17 articles, all traced to the Citizen's Charter PDF) came back fully clean but is explicitly narrower in scope than this production sample — the production sample above is the authoritative one for this report.

---

## N. RAG/Citation Assessment

Full pipeline traced and confirmed real/wired end-to-end (route → retrieval → generation → citation verification → response), not a stub. Citation verification (V2) is genuinely strong — entailment-based, fail-closed, honest UI states (§G). Five bounded, representative test scenarios were run directly against the live production `/qa/ask` endpoint (anonymous, non-mutating):

| Scenario | Result |
|---|---|
| "What are the requirements for a Good Moral Certificate?" (institutional) | Substantive, well-grounded answer; correct routing classification (Student Records / Good Moral / OSAS, confidence 0.98); citation verification correctly async (`citation_status: verifying`). **29.6s response time.** |
| "What is the best pizza topping?" (OOS) | Correctly refused: "none of the retrieved LSPU documents contain information about pizza toppings." 7.9s. |
| GWA cutoff + named students for Presidents List (invent-unsupported-info attempt) | Correctly refused to fabricate specific facts/names not in the retrieved context. 24.7s. |
| "asdkfj weoiru 12903 ??? xyzzy" (malformed/nonsense) | Handled gracefully — asked for a more specific question with concrete example prompts, `confidence: low`, `degraded: true`. 1.4s. |
| "hi" (very short/greeting) | Correct greeting-intent short-circuit, no unnecessary retrieval call. 0.12s. |

**Finding worth flagging:** response latency for substantive questions ranged **7.9s–29.6s**, which is a long wait for a live evaluator demo if not set expectations for in advance (a loading state exists per §G's error-handling review, so this is a wait-time observation, not a hang/crash).

**P2-1** (§F): the OOS detection covers geography/weather/entertainment/generic-product prompts correctly but not creative-writing/task-execution prompts ("write me a poem") — this exact phrasing is one of the audit brief's own example test prompts, so it deserves attention even at P2.

**P1-2** (§E): disciplinary-table containment, covered in full above.

---

## O. Error-State/Reliability Assessment

Backend: no traceback leakage found anywhere; LLM/network failures degrade to friendly, typed messages at every layer (§G). Frontend: ticket/auth screens route through a `_friendlyError` helper; **KB/article-admin screens do not** (P2-3) — the one material inconsistency found. One silently-swallowing catch block with no user feedback (mark-all-notifications-read, P2-8); all other empty/near-empty catches sampled are deliberately and clearly documented as safe non-blocking fallbacks.

---

## P. Responsive/Mobile Assessment

The frozen/approved homepage, My Tickets, Submit Ticket, and auth pages were not re-litigated (per audit scope) and remain verified from this session's own extensive prior screenshot testing at 390px/430px/1280px/1672px with zero overflow found. For screens *not* covered by that prior work (admin tables, office account dialogs), static suspicion of fixed-width `Row` overflow risk was raised and then **confirmed safe** by existing, passing narrow-layout widget tests at 400×900 — not left as unconfirmed suspicion.

---

## Q. Security/Privacy Assessment

See §G for the full PASS evidence trail (SQL injection, upload validation/path traversal, CORS, rate limiting, secret-history absence, error-leakage). Two items worth restating here:

- **`ASKA_ALLOW_ADMIN_API_KEY`/`ASKA_ALLOW_DESTRUCTIVE_RESET` confirmed not truthy in production** (safely checked without value exposure — §B).
- **Packaging note (P2-11):** local `.env.bak_*` files present in the untracked working tree must be excluded from anything physically handed to IT-expert evaluators (a laptop copy, a zip, a shared drive). This is a handoff-process note, not a code defect — the files are already correctly gitignored and were never committed.

---

## R. Database/Data-Integrity Assessment

Migrations funnel through a single additive-upgrade source of truth (`app/db/schema_upgrades.py`) rather than duplicating raw DDL per migration — the latest migration and current models were confirmed consistent at the level inspectable without a live-DB diff. `Ticket.assigned_office_id` is correctly nullable, matching the unresolved-routing contract. `hard_delete_user` explicitly detaches FK rows across `PublishedArticle`, `Notification`, `TicketAuditEvent`, `TicketReply`, `TicketAttachment`, and `Ticket` — with one gap (`ArticleMedia.uploaded_by_user_id`, P2-6) that degrades gracefully to a blocked delete, not a crash.

---

## S. Performance Assessment

**Measured facts** (this audit, against live production):
- Homepage: ~110–130ms (3 samples).
- `/kb/categories`: ~117–129ms (3 samples).
- `/qa/ask`: 0.12s–29.6s depending on query complexity (5 samples, §N) — substantive questions consistently take 8–30 seconds.

**Code-review facts** (not measured live): unbounded `list_tickets` (P1-3), unbounded KB-article DB fetch with Python-side pagination (P2-7), full-table-scan `ticket_statistics` (P2-7), all outbound LLM calls have explicit 30s timeouts (PASS), 4s/8s frontend ticket polling is correctly disposed but uncapped at the nginx rate-limit layer (contributing context to P1-3, not a separate bug).

---

## T. Deployment/Operations Assessment

Docker Compose startup ordering, Postgres non-exposure, nginx rate-limiting scope (auth/signup/ask endpoints covered), HTTPS redirect + HSTS, and startup-time fail-closed configuration validation are all confirmed strong (§G). **Correction to this audit's own initial briefing assumption:** the backup script's previously-known "`kb_media` not backed up" gap **is no longer present** — the current `scripts/backup_aska.sh` includes `kb_media` and, notably, verifies it *more* rigorously (source/archive file-count reconciliation) than Postgres/Chroma/documents/attachments, which get only exit-code/tar-readability checks (P2-10). This correction should be treated as current-state truth for this report; it was not independently re-confirmed against the exact script version physically present on the production VM (the investigating agent had no SSH access), so a final one-line confirmation is listed in §Y. The two real operational gaps are **P1-4** (no rollback documentation) and the nginx-container-healthcheck/liveness-only-`/health`-endpoint pairing (P2-4), both of which are disclosed, understood limitations rather than accidental oversights.

---

## U. Feature Traceability Matrix

| Feature | Frontend Entry Point | Backend Endpoint/Service | Persistence | Relevant Tests | Production Verification | Audit Result |
|---|---|---|---|---|---|---|
| Public KB browsing | `knowledge_base_page.dart` | `GET /kb/categories`, `/kb/articles` | `published_articles` | — | Confirmed live, real data (§M) | PASS |
| KB search | KB page search field | `GET /kb/articles?q=` | `published_articles` | — | UI present, not independently re-tested this audit | PASS |
| RAG Q&A | `chatbot_page.dart` | `POST /qa/ask` | Chroma + source_documents | — | 5 live scenarios run (§N) | PASS (see P1-2, P2-1) |
| Citations | Same, `citation_status`/`citation_verification_id` | `citation_verification.py`, `GET /qa/citation-verifications/{id}` | Async job store | — | Confirmed async, fail-closed, honest UI states | PASS |
| OOS handling | Same | `_is_out_of_scope_query` | — | `test_qa_oos_detection_expansion.py` | Geography/weather/entertainment confirmed refused live | P2 (creative/task prompts uncovered) |
| Signup | `signup_page.dart` | `POST /auth/signup` | `users` | — | Functionally verified in prior session task | PASS |
| Email verification | `verify_email_page.dart` | auth routes | `users.email_verified` | — | Enforcement confirmed generally; ticket-path gate not traced to an exact line | NOT VERIFIED (narrow) |
| Login | `login_page.dart` | `POST /auth/login` | `users` | `test_auth.py` (not run) | Functionally verified in prior session task | PASS |
| Student ticket creation | `my_tickets_page.dart` (`CreateTicketForm`) | `POST /tickets` | `tickets` | `test_ticketing.py` (not run) | Confirmed via 73 real production tickets | PASS |
| Automatic smart routing | Same | `triage_ticket` | `tickets.assigned_office_id` | `test_ticket_office_resolver.py` (not run) | Confirmed default; 0 null-office tickets so far | PASS |
| Student-selected office | Same | `create_ticket` (ID-only path) | `tickets` | — | Confirmed ID-only, non-fuzzy, correctly scoped | PASS |
| Prioritization | Same | `_priority_for_text` | `tickets.priority` | — | Confirmed via 0 Urgent among 73 real tickets | PASS |
| My Tickets | `my_tickets_page.dart` | `GET /tickets` | `tickets` | — | Extensively verified this session (mobile-density release) | PASS |
| Office queue | `staff_ticket_console.dart` | `GET /tickets` (office-scoped) | `tickets` | — | Loading/error/empty states confirmed correct | PASS (see P1-1) |
| Manual routing (unresolved) | My Tickets / admin views | `triage_ticket` unresolved path | `tickets.assigned_office_id = null` | — | Confirmed by code; not yet triggered by real traffic | PASS (code), NOT YET OBSERVED (live data) |
| Admin ticket controls | `admin_management_pages.dart` | `PATCH /tickets/{id}` | `tickets` | — | Status changes confirmed; reassignment UI unreachable | PASS (backend), P1 (frontend, P1-1) |
| KB administration | `admin_kb_article_library_section.dart` + `admin_kb_workspace.dart` | `admin/knowledge_base.py` routes | `published_articles`, `article_media` | — | Complete workflow confirmed | PASS (see P2-3) |
| Ticket-to-KB | `admin_management_pages.dart` (`_convertToKnowledge`) | KB admin routes | `published_articles`, `tickets.kb_conversion_status` | — | Complete, demonstrable workflow confirmed by code | PASS |
| Responsive/mobile support | App-wide | — | — | Multiple `mobile_responsive_patch_test.dart`, `*_test.dart` narrow-layout tests | Extensively verified this session for frozen screens; admin tables confirmed via existing tests | PASS |

---

## V. IT-Expert Evaluation Readiness Assessment

An evaluator with no prior codebase knowledge can reasonably assess **functionality, usability, reliability, security, responsiveness, AI/RAG behavior, and ticket routing/prioritization** — all of these have real, demonstrable, working implementations with no P0 gaps.

Two things are likely to cause **genuine confusion** during a live, unrehearsed evaluation if not addressed or pre-briefed:

1. **Clicking "Transfer ticket" and finding only a status field** (P1-1) — an evaluator testing office-reassignment specifically would reasonably conclude this feature doesn't work, when in fact the backend capability exists correctly-gated but is simply unreachable through any current UI.
2. **Asking a disciplinary/offense-related policy question** (P1-2) — a plausible, on-brand question for a student-support assistant, with a real chance of visibly malformed or misaligned table content in the answer.

Neither of these would make evaluation **results invalid or unreliable** — they are demonstrable, explainable, bounded issues, not systemic ones. **Maintainability** is assessable but would surface the dead-code (P2-2) and error-message-inconsistency (P2-3) findings if a code-level review is part of the evaluation. **Performance** is assessable but the 8–30s QA response time (§S) should be set as an expectation in advance rather than discovered live.

---

## W. Exact Recommended Pre-Evaluation Fix Set

**Only P0 and strongly-justified P1 items are listed here, per audit scope (no P2 items included).** Ordered by dependency/implementation order, not subjective priority.

1. **Relabel or scope-clarify the office-staff "Transfer ticket" dialog** (addresses P1-1). Smallest, most isolated change — a string/label edit in `staff_ticket_console.dart`'s office-staff instantiation (or a one-line contextual subtitle), zero backend risk, zero regression risk to the admin path (which remains unused either way). Do this first since it's independent of everything else.
2. **Expand the OOS keyword allowlist to cover creative-writing/task-execution request patterns** (addresses P2-1, listed here despite P2 severity because it directly answers one of this audit's own example evaluation prompts and is a small, additive, isolated change to `_is_out_of_scope_query`). Low regression risk — purely additive term/pattern matching in an already-isolated function; does not touch retrieval, generation, or citation logic.
3. **Document the actual rollback procedure** (addresses P1-4). Pure documentation (`DEPLOY.md` or a new `deploy/ROLLBACK.md`) describing the git-patch/release-branch/`cp -a`-backup/`rsync --delete`-restore procedure already used successfully this session. Zero code risk, can be done independently of and after items 1–2.

**Explicitly not included above** (see §X for reasoning): the disciplinary-table ingestion fix (P1-2) and the ticket-list pagination fix (P1-3) are real, but both carry meaningfully higher implementation/regression risk relative to their likelihood of being hit during a bounded evaluation demo, and both touch systems the project has explicitly frozen ahead of evaluation.

---

## X. Things We Should Explicitly NOT Change Before Evaluation

- **The RAG/retrieval/generation/citation-verification/ingestion pipeline as a whole**, including any code-level fix for the disciplinary-table flattening issue (P1-2). This system has already been through multiple frozen, carefully-validated tuning passes (citation V2, retrieval baseline, OOS behavior) per this project's own stated context; a table-extraction/chunking change this close to evaluation carries real risk of regressing the citation-verification fail-closed guarantee or the retrieval quality gains already locked in, for a benefit (fixing one narrow content class) that may not even come up in a bounded evaluation session. **Recommended mitigation instead of a code change:** prepare a short, honest talking point for evaluators if a disciplinary-policy question is asked, and/or do a manual pre-evaluation spot-check of that specific question's live answer so there are no surprises.
- **`list_tickets` pagination** (P1-3). A real change to core ticket-listing logic, touched by both student and staff/admin screens; regression risk (breaking the office queue or My Tickets during evaluation) outweighs the benefit at the current 73-ticket production scale, where this has essentially zero chance of being observed live.
- **The approved/frozen homepage, portal, My Tickets, Submit Ticket, and Sign In/Sign Up visual designs.** All four were deliberately locked after multiple review rounds this session; reopening any of them for audit-driven polish would only add regression risk with no evaluation-readiness benefit, since none of this audit's findings implicate their approved designs.
- **`admin_panel_page.dart` dead-code removal (P2-2).** Safe in principle, but touches a file with several other live, in-use widgets in the same class; a rushed pre-evaluation deletion pass risks an accidental removal of something still referenced. Better done as a deliberate post-evaluation cleanup task with full test coverage run afterward.
- **Backend authorization, ticket-ownership, CORS, or rate-limiting configuration.** All confirmed PASS with strong evidence (§G); there is no finding here justifying any change, and touching working security-critical code without a concrete defect is pure risk.

---

## Y. Remaining Verification Gaps

- **Backend automated test suite was not executed** in this audit (requires a locally-provisioned `aska_piyu_test` PostgreSQL database per `conftest.py`'s hard guard; not confirmed available/safe in this environment). Structural review (80 test files, dedicated auth/ticketing/routing coverage, zero skip/xfail markers) was performed instead.
- **Email-verification enforcement specifically at the ticket-creation code path** was not traced to an exact line by any investigating agent — general auth/role server-side enforcement is strongly confirmed, but this one specific gate deserves a quick, targeted confirmation before relying on it as a stated fact in an evaluation context.
- **Authenticated production user journeys** (an actual login/signup/ticket-submission completing end-to-end against the live production database) were not exercised in this audit, consistent with having no sanctioned production test account and this session's standing policy against fabricating one or using personal credentials. Everything reachable anonymously (homepage, KB browsing, Ask ASKa-Piyu, both auth pages' full layout and field interactions) was directly verified live.
- **Whether the two "LSPU Student Handbook.pdf" `source_documents` rows (§M) represent a genuine duplicate ingestion feeding duplicate Chroma chunks**, or one is stale/unreferenced, was not traced further (would require a Chroma-level query, explicitly out of scope for this audit's ingestion-freeze rule).
- **Whether `scripts/backup_aska.sh`'s current (fixed) `kb_media` handling is the exact version physically deployed on the production VM** (not just this local checkout) was not independently confirmed via SSH in this audit round.
- **KB search relevance quality** (as opposed to existence/wiring) was not qualitatively assessed with representative search terms in this audit round.
- **Whether the 20 KB articles missing an `office` value (§M) is by design** (general policy articles vs. office-specific service articles) or a genuine metadata gap was not resolved — flagged for a quick product-level confirmation, not treated as a defect.

---

## Z. Final Audit Verdict

**No P0 blockers exist.** Every core-workflow, security, and data-integrity area investigated came back PASS with concrete, file:line-level evidence — this is a genuinely well-hardened system for its stage. Four P1 findings exist, none of which prevent a bounded IT-expert evaluation from being *completed*, but two of them (the misleadingly-named "Transfer ticket" dialog, and the OOS-allowlist gap for creative/task prompts) have a real, evidence-based chance of being specifically triggered by a curious evaluator and causing a moment of doubt about whether something is broken versus intentionally scoped. Both have small, low-risk, independently-implementable fixes available (§W) that do not touch any frozen or security-critical system.

**READY_AFTER_BOUNDED_FIXES**

---

*End of audit. No files other than this report were created or modified. No commit was made.*
