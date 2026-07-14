# ASKa-Piyu Project Memory

## Project Overview

ASKa-Piyu is a Retrieval-Augmented Generation (RAG) knowledge base, technical support system, student help center, and ticket routing system built for Laguna State Polytechnic University (LSPU).

High-level flow:

PDF or image -> OCR/PDF extraction -> cleaning -> structuring -> chunking -> metadata classification -> ChromaDB -> retrieval -> reranking -> Groq QA -> student response -> ticket routing

The repository currently contains:

- `backend/`: FastAPI backend for document processing, ChromaDB storage, knowledge-base browsing, QA, admin tools, and routing metadata.
- `flutter_app/`: Flutter client with student, chatbot, knowledge-base, tickets, and admin-panel screens.

## Current Architecture

The backend is organized around two separate flows:

- Admin knowledge-base creation: source document upload, OCR/PDF extraction, text cleaning, handbook-aware structuring, chunking, taxonomy metadata enrichment, and ChromaDB ingestion.
- Student runtime experience: knowledge-base browsing, question answering over existing ChromaDB chunks, source grounding, fallback handling, and routing metadata.

Important backend components:

- OCR pipeline: EasyOCR and PyMuPDF extraction run only during admin extract/ingest.
- Handbook processor: detects handbook policy structure, logical units, hierarchy, page metadata, campus/program metadata, suspicious units, and validation diagnostics.
- Chunking: splits structured knowledge units into store-compatible chunks while preserving metadata.
- Metadata enrichment: adds category, subcategory, office, responsible office, source document, page, campus, and keywords.
- Taxonomy: config-driven classification from `backend/app/knowledge_base_categories.json`, with rule, similarity, and optional Groq-assisted classification paths.
- ChromaDB: persistent collection managed through `KnowledgeBaseStore`, using the configured collection and Chroma default embeddings.
- Retrieval: Chroma similarity search with query preparation and expansion.
- Reranking: domain-specific boosts and penalties improve relevance for policies, programs, offices, services, records, scholarships, attendance, retention, and out-of-scope queries.
- Groq: `/qa/ask` uses Groq for grounded answers when configured, with extractive fallback when unavailable or rate limited.
- KB browser: `/kb/articles`, `/kb/articles/{article_id}`, `/kb/categories`, and `/kb/popular` serve **PostgreSQL `published_articles` where `published=true` only**. ChromaDB chunks are not listed on the public Knowledge Base. `/kb/classify` remains for support routing. Ask ASKa-Piyu continues to retrieve from ChromaDB.
- QA: `/qa/ask` is the richer production QA endpoint with debug fields; `/student/ask` is the simpler student RAG endpoint.
- Ticket routing: question classification returns category, subcategory, office, responsible office, confidence, and method.
- Smart ticketing: unresolved or low-confidence chatbot questions can become routed support tickets with status updates and replies.

## Stable Components

These components are considered stable and should only be modified for bug fixes or substantial improvements:

- OCR and PDF extraction
- Text cleaning
- Handbook policy extraction and logical-unit structuring
- Chunking
- Metadata enrichment
- Knowledge taxonomy and ticket-routing metadata
- Chroma storage and reset/rebuild mechanics
- Knowledge-base browser
- Focused article grouping
- QA intent detection
- Collection retrieval for broad questions
- Retrieval reranking
- Groq fallback handling
- Out-of-scope handling

## Completed Features

Knowledge Base:

- Student-friendly taxonomy with categories, subcategories, responsible offices, and keywords.
- Focused article browser that avoids giant long-scroll articles.
- Semantic and category-filtered search.
- Natural student-term KB search with query expansion for programs, records, services, admissions, technical support, and common shorthand such as TOR and CCS.
- Category-first help-center browsing in the Flutter Knowledge Base UI.
- Public Knowledge Base lists and details come only from PostgreSQL published articles (`published=true`). Category cards and search use those articles (title, summary, content, category, office). Article cards show `published_articles.title` (never the category as a title fallback). In grouped category views, category chips are omitted on cards to avoid repeating the section heading; search results may still show a category chip. Source/office/document-type chips stay when useful and de-duplicated. Empty state asks admins to publish reviewed articles—not to index Chroma content. Article-identity focused grouping helpers remain available for RAG/tooling over Chroma chunks but are not the public KB source.
- Article detail pages with full content.
- Related focused articles.
- Popular topic support.

QA:

- Query normalization and expansion.
- Intent detection for normal, definition, procedure, requirement, office/service, collection, and out-of-scope questions.
- Retrieval reranking with metadata/domain boosts and noise penalties.
- Collection retrieval for broad questions such as programs, services, scholarships, offices, and requirements.
- Groq answer generation with grounded context.
- Extractive fallback when Groq is unavailable, rate limited, or times out.
- Out-of-scope handbook scope message.
- Debug fields for retrieval, selected context, intent, rerank reasons, and fallback state.

Admin:

- Extract preview endpoint.
- Ingest endpoint.
- Chroma reset endpoint.
- Configured rebuild endpoint.
- Retrieval test endpoint.
- KB statistics endpoint.
- Safe configuration diagnostics.
- Flutter admin sidebar now shows role-specific admin tools: Admin Dashboard, All Tickets, Users & Roles, Offices, and Reports / Statistics.
- Flutter admin management placeholder pages are guarded for `role == "admin"` and use existing ASKa-Piyu card styling.
- Admin Dashboard and Reports / Statistics attempt to read `/tickets/statistics`; All Tickets is prepared to read `/tickets` without changing the existing student ticket flow.
- Flutter Admin All Tickets is now a real admin ticket queue with ticket cards, search, status/priority/office filters, detail dialogs, admin ticket updates, and admin replies using existing `/tickets` endpoints.
- Flutter Knowledge Base Admin sidebar navigation opens the guarded legacy `AdminPanelPage` for document extraction, review, ingestion, indexing, and retrieval testing.
- Knowledge Base Admin tools now accept logged-in admin bearer authentication from Flutter, with the legacy `X-Admin-Key` path retained for scripts/tests.
- Requirement/form extraction no longer forces ICT-specific office names, service options, or sample form values at runtime; offices/options/fields are extracted from uploaded text with unknown office reported when absent.
- Requirement/form extraction now stores detected forms as `requirement`, displays them as "Requirement / Form Document", and dynamically returns form title, office/source, fields, options/services, generated requirements, generic fill-out instructions, related services, source/preview fields, and separated raw extraction without hardcoded service fallbacks.
- Requirement/form indexing excludes raw OCR extraction text from Chroma searchable chunk text and metadata. Raw extraction remains available for admin preview/debug, while Chroma stores only clean structured requirement content plus source/preview references and a `raw_extraction_available` flag.
- **Citizen's Charter** documents (`parser document_type=citizen_charter`, KB type `procedure`) are extracted as **one service article per numbered service block**. **Extraction V2** (`citizen_charter_extractor_v2`) uses PDF word geometry when available: service starts require a real title plus nearby Office/Division, Classification, Type of Transaction, Who May Avail, and Checklist or Client Steps (lookahead stops at TOTAL / next service so table rows cannot borrow the next header). **Numbered headings stay bound** until the next numbered heading: generic description lines (`This process provides…`, `This service provides…`, `Provision of services…`, etc.) never become titles; placeholder `rag_only` title-only objects merge into the following structured block (`merge=title_bound_to_structured_block`). **Step meta cells strip header crumbs** (`BE PAID`, `TIME`, `RESPONSIBLE`, `FEES TO`, `PROCESSING`, `PERSON`, …) before `detected_step_rows` / article body; `BE PAID None` → `None`; OSAS personnel variants normalize to `OSAS Director/Chairperson/Staff`. Step-like numbered lines, sentence fragments, and office-only crumbs are not services. `rejected_fragments` are scoped to the current service block only. **Geometry is the source of truth for table reconstruction** (requirements + steps): word x/y → visual rows → header/body column boundaries → per-word column assignment → column-aware continuation merge (client/agency/person crumbs append to the matching previous column; short trailing nouns like `ID.` attach to unfinished clients such as `Accept the validated`; `Clientele` alone is OCR noise; multi-column rows start a new step only when the prior row is complete). Flattened `|` text is fallback only when words are missing. Priority services dump `visual_table_debug` (page span, visual rows with y, column boundaries, word→column assignments, logical rows, drop reasons, `no_step_rows_reason`) into `parser_debug` and Download TXT. Clean quality requires office + who + at least one complete client/agency step, rejects excessive Not specified slots and page-number fees. Extract & Structure renderer keeps `extraction_blockers` (structural) vs `extraction_warnings` (minor) — clean cannot coexist with structural blockers; priority diagnostics prefer the richer merged service over rag_only placeholders. **Recommended gates stay strict:** rendered article step count must equal clean `detected_step_rows`; `[NEEDS REVIEW]` in `total_fees` or incomplete detected steps blocks Recommended; when repairs change fields, `rescue_successful` and `body_uses_repaired_fields` must be true for Recommended. Detected office (`office_division` / `parser_debug.detected_office` / `extracted_office`) flows into `build_charter_article_body` even when `office_aliases` has no match — planner merge must not wipe extracted office with `None`. Label-only Office/Who lines take the next geometry value line. Intentionally blank checklists (header found with no real requirements, or `None`/`N/A` markers) render `No additional requirements specified in the Citizen's Charter.` in article body and official excerpt (not `Requirement: Not specified`) and may be Recommended only when every step field is complete. Time/person cells like `5mins Records` + `Officer, Staff` become `5mins` / `Records Officer, Staff` at geometry and rescue. **Rescue / repair** (`citizen_charter_rescue`) runs after V2 extraction and before final bucket assignment: reloads `detected_step_rows` dicts and `visual_table_debug` logical rows for deep repair, repairs requirement office suffixes, wrapped step/requirement rows with personnel-first + sparse wrap merging, fee/time/personnel splits, recovers total processing time, cleans titles, classifies audience, syncs repaired fields into `parser_debug.detected_*` and the generated article body, and re-runs semantic + final-body validation — **without loosening Recommended gates**. A **public_priority_service repair pass** runs only for student-facing signals (G2C; Students/Alumni/Applicants/etc.; Registrar/Accounting/Library/OSAS/UHS/etc. offices) and explicitly excludes internal titles (ISO, Procurement/BAC, HR, Legal, Recognition, QA, Supply, etc.). For public priority clean services blocked only by article-body placeholders, rescue prefers `parser_debug.detected_requirements` / `detected_step_rows`, splits glued requirement/where pairs (e.g. `LSPU ID BAO`, `COR Registrar`), recovers totals (clearances → `4 minutes`; entrance exam preserves `1–3 days, 1 hour and 45 minutes`), and rebuilds the body from structured fields. Public priority with minor leftover issues stays Needs Review (Save as Draft/Edit), not Low Quality; Low Quality remains for true fragments/placeholders/garbled rows. Report chips: `public_priority_found` / `recommended` / `needs_review` / `low_quality` / `repaired` / `blocked_by_article_body`. Priority Coverage sorts public priority first and shows final_bucket, publish_allowed, main_failed_field, next_repair_target, suggested_bucket_after_repair, body_has_needs_review, rendered/detected step counts, detected_requirement_count, total_processing_time_detected. `rescue_successful` is true only when repaired fields change, appear in the final body, and both semantic and final-body validation pass with Recommended. Low Quality rescue counts are split: `low_quality_repair_attempted` / `low_quality_repair_changed_fields` / `low_quality_rescued_to_needs_review` / `low_quality_rescued_to_recommended` / `low_quality_repair_failed`; `low_quality_rescue_successful` increments only when the service leaves Low Quality. Charter report includes `priority_service_diagnostics` / **Priority Coverage** matrix (found, extraction_status, final_bucket, publish_allowed, detected_requirements_count, detected_step_count, rendered_step_count, total_processing_time_detected, blockers, next_action, next_repair_target, repairable, main_failed_field, suggested_bucket_after_repair, is_student_priority) for important student-facing titles, sorted student-facing / near-clean first. Generate Articles annotates candidates against `published_articles` using stable keys (`source_filename` + normalized title, or `source_filename` + `source_section` + `article_type` from embedded metadata). Already-published matches show **Already Published**, hide Publish, offer **Update Existing**, and are skipped by Publish All Recommended — regenerate never deletes library/public rows. Matching normalizes filenames to basename and numbered titles; publish_allowed stays false after bucket finalize when already published. Publish writes published_articles.published=true and returns persistence_debug (id/title/source_filename/source_section/published/table). Extract/Generate never delete or unpublish rows. Charter candidates keep extracted Office/Division when office_aliases has no match so bodies are not rebuilt as Not specified. Priority Coverage found services missing from card lists are injected as preview cards. Low Quality and RAG-only preview cards always expose Download TXT. Routine Medical and Dental Services requires 3 detected and rendered steps before Recommended. Public-priority Priority Coverage also shows article_body_status, body_rebuilt_from_detected_fields, required_step_count_met, publish_safety_state, and already_published_match. Candidates carry `original_bucket`, `repaired_bucket`, `rescue_attempted`, `rescue_successful`, `repair_actions_applied`, `remaining_blockers`, `missing_fields`, `row_merge_failure_reason`; charter report includes rescue counts plus repaired-but-not-promoted / repair-failed / semantic-failed / LQ-rescue counts, and report Recommended equals UI Recommended. Needs Review cards show why not recommended; Low Quality keeps true fragments after repair attempts. **Recommended is blocked** when the final article body (excluding Source Information) still contains `Not specified` or `[NEEDS REVIEW]`, or when Total Processing Time is missing. Audience uses G2C vs G2G/transaction type plus office/who signals — internal offices (Procurement, BAC, HR, IAU, Legal, QA, Supply, Board Secretary, etc.) are not auto student_facing. Blocks split on service headings (for example `4. ID Validation`) ending before the next heading or at TOTAL, not on wide excerpt windows. Split Part 1/Part 2/Part 3 blocks merge by normalized title + compatible office. Artifact headings (NEXUS SYSTEM, Classification labels, Official Receipt, Abstract of Quotation, Validation-only, page/table continuations) remain in Full Extraction text but are hard-rejected when the **title/leaf** is an artifact—noisy ancestor path segments alone do not reject a clean service (e.g. `Abstract… > ID Validation` stays eligible). Mixed multi-service bodies are Low Quality candidates (not silent RAG-only). Incomplete but service-shaped blocks use a soft validity gate (office + who/classification + requirements/steps + processing/total) and stay article-eligible as Low Quality / Needs Review. True artifacts stay RAG-only. **Table reconstruction:** drop header crumbs (CLIENT STEPS / FEES TO BE PAID / BE / TIME / RESPONSIBLE) before step parsing; reject label remnants like `or Division` for office; reject numeric-only or fragment titles; rebuild step rows from numbered groups + fee/time/personnel signals; keep `Client` as a valid Where to Secure; split TOTAL into fees vs compound processing time (e.g. `1-3 days, 1 hr and 45 minutes`). Recommended requires a valid title, real office, who/classification, real requirements or steps, no fake header steps, and at least one complete step or step times + total. Download TXT includes parser debug (`raw_service_block`, `cleaned_service_block`, dropped headers, reconstructed rows, rejected fake steps, requirement pairs, total line). **Bucket consistency:** every preview has canonical `final_bucket` (recommended / needs_review / low_quality / rag_only / consolidated_parent) from `decide_charter_bucket`; UI grouping and Publish/Save use `final_bucket` over charter/planner buckets. Flags like `incomplete_structured_fields` and `table_row_fragment`, plus field-label/OCR fragment titles, never enter Recommended and are not publishable. Child table-row fragments are suppressed. Charter report/TXT include final bucket counts, mismatch corrections, and publish/save flags. **Bucket routing:** clean student-facing services → Recommended via a charter-specific gate (not handbook 7.0/7.5 thresholds); non-blocking flags such as `uncertain_office` / `title_too_long` do not force Needs Review; internal/admin-heavy or uncertain audience → Needs Review; mixed/incomplete/truncated titles → Low Quality. Audience uses student vs internal signal scores (`student_facing_score` / `internal_admin_score`). Generate Articles rebuilds charter units from the best available text (`review_text` → `extracted_text` → cleaned/structured → unit join) via `citizen_charter_service_parser` + `build_charter_article_body` only (never handbook_policy / Process / Key Points / Eligibility). Preview metadata: `document_type=citizen_charter`, `article_type=service_procedure`, `parser_used`, `formatter_used`. Charter generation report includes profile, parser, review_text length, knowledge-unit count, detected/valid/rejected/incomplete counts, and generated candidates. Article structure: Overview → Office/Division → Who May Avail → Requirements → Steps → Fees → Total Processing Time → Source Information. Categories map via generic wording (+ optional `office.service_category`). Office publish labels still require `office_aliases` matches.
- Generate Articles preview cards include a temporary development-only **Download TXT** control (browser download; no backend/PostgreSQL). Export includes title, bucket, category, scores, review flags, source metadata, summary, article content, official source excerpt, document_profile / parser_used / formatter_used, and pretty-printed metadata.
- Knowledge Base Admin extraction preview keeps Raw OCR Text out of the main clean preview/editor. Raw OCR is available only in a collapsed admin debug panel and remains excluded from Chroma indexing and chatbot answers.
- Knowledge Base Admin extraction page focuses only on upload, **Extract & Structure**, **Full Extraction Result**, and **Index for Chatbot Retrieval**. Layout (top to bottom): header → Active Document card (matched-height maroon-gradient primary / white-outline secondary buttons) → full-width **Processing Status** row of compact stage cards → main row with wide **Full Extraction Result** (white internal-scroll preview + Copy / Download .txt) and a narrow Document Details / Go to Generate Articles column → full-width **Knowledge Units** review section below extraction. Article Library and Advanced developer options are **not** shown on this page. **Index for Chatbot Retrieval** indexes ChromaDB only and does not publish public KB articles. Generate Article Candidates is **not** on Documents. For `citizen_charter` / `service_process`, Extract & Structure runs geometry-first `citizen_charter_extractor_v2` and **Full Extraction Result / download TXT are rendered from V2 structured services** (`citizen_charter_extraction_renderer`) — Office/Service/Classification/Transaction/Who/Requirements/Steps/Total — not from the older flattened V1 `format_structured_document` text when V2 services exist. Extraction TXT includes priority service diagnostics (found, office, req/step counts, total time, status, blockers). `charter_v2_services` remain in the preview package for Generate Articles.
- Publishing is PostgreSQL-backed (`published_articles.published=true`). Save-as-draft / content-update paths must not silently unpublish already-public articles (use explicit Unpublish). Public Knowledge Base re-fetches categories when returning to the category browse view so newly published articles appear after admin work.
- **Generate Articles** is a separate admin page/sidebar item. Documents → Generate Articles handoff uses a **compact preview package** (`extraction_preview_store.dart` + `AppConfig.lastExtractionPreview` in localStorage): source filename, detected type, document profile, knowledge units, review/extracted text, and `charter_v2_*` fields only (no PDF geometry / word boxes). Empty/invalid payloads never overwrite a valid cache; QuotaExceeded falls back to aggressive compact. Generate Articles auto-loads and **Reload from Documents** reloads that package; if missing, shows “No extracted document found…”. Generate accepts knowledge units **or** V2 services. Runs `POST /admin/kb/articles/generate-preview` (preview-only), and reviews candidates. Article generation uses an **Article Planner**: tags each knowledge unit (`rag_indexable`, `article_eligible`, intents, parent/canonical topic), builds topic blueprints with SHA1 IDs, merges related units into fewer student-facing candidates (~50–90 on large handbooks), and returns a **coverage** report (`generated` / `merged_parent` / `rag_only` / `needs_cleanup`). **Coherence rules** block publish-ready consolidated parents when merged children span too many unrelated topics, article categories, source roots, or article numbers (broad parents like “Graduate Studies” fall through to per-topic blueprints / needs review instead). **Numeric-only titles** (`1.1`, `4.2`) resolve via hierarchy or land in Low Quality / RAG-only—never Recommended, Consolidated Parent, or Needs Review. Office groups use dynamic PostgreSQL `office_aliases` via `match_office_from_text` (high confidence only)—no hardcoded office names in planner logic.
- Generation does not insert into `published_articles` until **Save as Draft** (`published=false`) or **Publish** (`published=true`). Duplicate detection runs on save/publish (409). UI buckets: Recommended, Consolidated Parent, Needs Review, Low Quality / Cleanup, RAG-only. Generate Articles supports **safe bulk actions**: select checkboxes, Save/Publish Selected, and Publish/Save All for Recommended and Consolidated Parent only. Needs Review allows bulk draft save but not bulk publish. Low Quality and RAG-only have no bulk save/publish. Bulk publish uses confirmation dialogs and `POST /admin/kb/articles/bulk-publish` / `bulk-save-draft` (per-item success/failure, duplicate-safe). Generate Articles UI shows only the selected document + **Generate Article Candidates** button; optional **Recommended preview limit** lives in collapsed Advanced developer options only. Action buttons are text-only (no icons). By default all planner blueprint candidates are generated; review priority comes from buckets, collapsed sections, and Load More—not from a visible max-candidates control.
- Admin article summaries are normalized with generic rules (max 2 sentences, ~350 chars, no duplicate of full content, numbered-clause prefixes stripped from summaries). Summaries are composed student-friendly from title plus key terms detected in content (process, requirements, referral, follow-up, etc.), avoid copying opening sentences, use suffix-aware grammar for titles ending in Services/Process/Policy/Procedure, and simplify awkward OCR-derived phrases (for example, "follow-up counselee with cases" -> "follow-up assistance", "case conference" -> "case conferences", referral-to-team fragments -> "students may be referred to a multidisciplinary team when additional support is needed") without inventing facts. **Article content formatting** (`article_content_formatter.py`) detects content patterns and classifies numbered clauses before formatting. `build_clean_overview()` uses generic title-suffix normalization to avoid awkward repeats like "requirements for Admission Requirements". Broad/mixed candidates (multiple topic clusters across source sections/intents/numbered blocks) are marked Needs Review with `mixed_article_scope` and a neutral review summary. Internal role/responsibility articles are Needs Review with `internal_role_list`. Only true action-based lists become Process steps; requirements keep clean numbering and compact requirement labels where safe; eligibility/condition content uses Eligibility / Conditions. Overview stays short; details go under Requirements/Key Points/Eligibility, never as an unlabeled dump under Overview. Official cleaned extracted text remains in embedded metadata as `official_source_excerpt` (also used to ground recommendation foreign-term checks). Admin View/Edit modals show formatted Article Content (scroll starts at top; only section headings and short step labels are bold) plus a collapsed Official Source Excerpt; edits preserve excerpt metadata. Source filename is stored on drafts and in embedded metadata; View modal falls back to upload filename when needed and shows `Not specified` for empty office.
- Only explicitly published articles appear in the public Knowledge Base; drafts and review buckets remain admin-only. Public KB article detail strips embedded metadata blocks and shows formatted article bodies (not raw OCR chunks). **Article Library** supports Published/Draft filters plus Source document, Category, Document type, and Needs Review filters; selection with **Publish Selected** / **Unpublish Selected** (confirmation); single Unpublish keeps rows as drafts (`POST /admin/kb/articles/{id}/unpublish` and `bulk-unpublish`). Delete remains explicit with confirmation. Admin cards can show Public/Draft/Needs Review/Source readiness labels.

Ticketing:

- Routing metadata on QA responses.
- Office and responsible-office metadata from taxonomy.
- `/kb/classify` support for support routing.
- `/tickets` API for creating, listing, reading, replying to, and updating support tickets.
- PostgreSQL foundation exists for application data with SQLAlchemy models for users, offices, tickets, and ticket replies.
- PostgreSQL is configured with `ASKA_DATABASE_URL`; ChromaDB remains the vector store for indexed handbook/document chunks and RAG retrieval.
- `/health/database` reports safe PostgreSQL connection status without exposing credentials.
- `/auth/signup`, `/auth/login`, and `/auth/me` provide PostgreSQL-backed student signup and bearer token authentication.
- Ticket triage uses the existing taxonomy classifier for category/office routing and rule-based priority assignment.
- Student ticket page submits to the backend instead of keeping only local in-memory tickets.
- Low-confidence chatbot answers show a ticket suggestion and pre-fill the ticket form with the original question.
- Office and admin ticket access is enforced through role/identity headers until a full auth system is added.
- Flutter API base is centralized in `AppConfig` using `ASKA_API_BASE_URL`; admin API keys are entered at runtime and are not compiled into the client.
- Student Tickets UI now presents a support-center dashboard with searchable/filterable ticket cards, status and priority chips, ticket detail dialog, conversation history from ticket messages, refresh support, empty/loading/error states, and a clearer backend-connected submit form with required-field validation.
- Flutter login/signup UI is connected to `/auth/signup`, `/auth/login`, and `/auth/me`; bearer tokens are stored in browser local storage, restored on app start, and used as the source of student identity for ticket workflows while Knowledge Base and Ask ASKa-Piyu remain public.
- Ticket and admin navigation is auth-aware: guests are sent to login/signup before Submit Ticket, My Tickets, or Admin Panel, and ticket requests send bearer auth plus temporary `x-user-*` compatibility headers derived from the logged-in user.
- Office users now receive `office_name` from `/auth/me`, send office ticket headers with the assigned office name, and see role-specific Flutter navigation for Office Dashboard and Assigned Tickets while retaining Knowledge Base and Ask ASKa-Piyu access.
- Office Dashboard and Assigned Tickets use existing `/tickets` role filtering to show only tickets assigned to the logged-in office, with office stats, search/status/priority filters, ticket details, replies, and status/priority updates without reassignment controls.
- A local development seed script creates idempotent office records and office users for ICT Office, Registrar, and Office of Student Affairs while public signup remains student-only.
- Student ticket detail dialogs now show a clearer demo-ready conversation thread with a student concern card, highlighted office reply bubbles, office reply counts, empty reply guidance, and resolved/closed status banners without exposing office/admin controls.

## Development Principles

- Do not hardcode handbook content.
- Prefer metadata-driven classification.
- Prefer dynamic retrieval over static mappings.
- Prefer maintainable rule systems.
- Preserve handbook structure, hierarchy, page references, campus metadata, and source document details.
- Keep student-facing UI simple and direct.
- Keep source cards grounded in indexed handbook chunks.
- Do not run OCR or document upload from student flows.
- Treat ChromaDB as the runtime source of indexed institutional knowledge.
- Avoid UI redesign unless retrieval evaluation shows a user-facing comprehension problem.

## Knowledge Base Design

The intended KB experience is focused and browsable. Categories contain many smaller articles rather than one giant article per handbook section.

Examples:

- Academic Policies
  - Attendance
  - Excuse Slip
  - Scholastic Delinquency
  - Graduation Requirements
- Programs & Curricular Offerings
  - College of Engineering Programs
  - College of Computer Studies Programs
  - Graduate Programs
- Student Services
  - Guidance and Counseling
  - Health Services
  - OSAS Services

Avoid giant articles that require long scrolling. Keep article grouping focused by category, subcategory, and specific topic.

## QA Design

Specific questions should retrieve a few highly relevant chunks, generate a short grounded answer, and show source cards.

Broad questions should use collection retrieval and grouped summaries. Examples include questions asking for all programs, offices, services, scholarships, or requirements.

Out-of-scope questions should not hallucinate. They should return a handbook scope message such as: "The LSPU handbook does not contain information about this topic."

Fallback behavior should remain graceful. If Groq is unavailable, rate limited, misconfigured, or times out, return a handbook excerpt or a handbook-missing message based on the selected context.

## Admin Workflow

Standard workflow:

Reset Chroma
-> Extract
-> Review
-> Ingest
-> QA Testing

Alternative workflow:

Reset
-> Rebuild

Important admin endpoints:

- `POST /admin/knowledge-base/extract`: preview OCR/PDF extraction and cleaning without indexing.
- `POST /admin/knowledge-base/ingest`: run the full ingest pipeline and index chunks into ChromaDB.
- `POST /admin/kb/retrieval-test`: test retrieval against indexed chunks.
- `GET /admin/kb/statistics`: inspect collection statistics.
- `POST /admin/kb/rebuild`: reset and rebuild from `ASKA_KB_REBUILD_DOCUMENT_PATHS`.
- `DELETE /admin/chroma/reset`: reset the configured ChromaDB collection.
- `GET /admin/debug/config`: safe diagnostics without exposing secrets.

Admin endpoints accept either `X-Admin-Key` matching `ASKA_ADMIN_API_KEY` or a bearer token for a logged-in user with `role == "admin"`, except the safe debug config endpoint.

## Known Environment Variables

Do not commit or expose real secret values.

- `ASKA_ADMIN_API_KEY`: admin API key required for protected admin endpoints.
- `ASKA_CHROMA_PERSIST_DIR`: ChromaDB persistence directory.
- `ASKA_CHROMA_COLLECTION_NAME`: ChromaDB collection name.
- `ASKA_RAG_TOP_K`: default number of chunks retrieved for RAG.
- `ASKA_GROQ_API_KEY`: Groq API key for QA answer generation and optional taxonomy fallback.
- `ASKA_GROQ_MODEL`: Groq model name.
- `ASKA_GROQ_TIMEOUT_SECONDS`: Groq request timeout.
- `ASKA_CORS_ORIGINS`: allowed CORS origins.
- `ASKA_KB_REBUILD_DOCUMENT_PATHS`: one or more source document paths used by the rebuild flow.
- `ASKA_TICKET_STORE_PATH`: JSON persistence path for smart ticketing data.
- `ASKA_DATABASE_URL`: PostgreSQL application-data URL for users, offices, tickets, replies, auth, audit/statistics.
- `ASKA_DATABASE_INIT_ON_STARTUP`: development-only flag to create SQLAlchemy tables at startup.
- `ASKA_AUTH_SECRET_KEY`: secret key for signing bearer tokens used by login and authenticated app-data workflows.
- `ASKA_AUTH_TOKEN_TTL_MINUTES`: bearer token lifetime in minutes.

## Known Constraints

- Flutter currently uses web-only `dart:html` APIs.
- The current project has no full authentication system; ticket role boundaries use `x-user-*` headers as a replaceable integration layer.
- Admin API keys must not be hardcoded in Flutter or committed. The admin panel uses logged-in admin bearer auth by default and keeps manual key entry only as a legacy option.

## Current Priorities

Current priority: improve the chatbot response card for requirement/form documents using the newly enriched dynamic extraction metadata, while keeping ChromaDB-backed RAG, ticketing, auth, admin, office, and student workflows stable.

Focus:

- Retrieval evaluation
- Benchmark questions
- Chunk quality
- Citation quality

Do not prioritize UI redesign or additional taxonomy unless retrieval evaluation reveals problems.

## Future Roadmap

Knowledge Base
-> QA Accuracy
-> Technical Support
-> Ticket Workflow
-> Analytics
-> Reporting

## Testing

Current expectations:

- Run full backend tests before and after meaningful backend changes.
- Preserve existing admin, KB browser, QA, ticket routing, Chroma, and ingestion behavior.
- Avoid regressions in retrieval, reranking, fallback, and out-of-scope handling.
- Add focused tests when changing shared retrieval, taxonomy, chunking, or QA behavior.

Latest verified backend test collection: `266 tests collected` using `pytest --collect-only -q` from `backend/`.

Latest verified backend test run: `468 passed` using `pytest tests/ -q` from `backend/`.

Latest Flutter verification: `flutter test test/admin_article_models_test.dart` passed (25 tests); changed article model/export files analyze clean; full-project `flutter analyze` still reports pre-existing `dart:html` / `withOpacity` infos and unused legacy admin panel symbols.

## Rules for Future Codex Sessions

Every future coding session should:

- Read `PROJECT_MEMORY.md` first.
- Preserve the stable architecture.
- Avoid unnecessary redesigns.
- Update `PROJECT_MEMORY.md` whenever a major feature is completed.
- Update the Current Priorities section after completing a milestone.
- Update the Completed Features section when new capabilities are added.
- Keep this file concise, current, and useful as the single source of truth for project state.
