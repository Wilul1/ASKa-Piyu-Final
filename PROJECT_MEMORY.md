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
- KB browser: `/kb/articles`, `/kb/articles/{article_id}`, `/kb/categories`, `/kb/popular`, and `/kb/classify`.
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
- Article-identity based KB browser results: search and category browsing prefer specific leaf topics such as Scholastic Delinquency, Excuse Slip, Transcript of Records, Good Moral, and College program articles instead of parent taxonomy labels.
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

Admin endpoints require `X-Admin-Key` matching `ASKA_ADMIN_API_KEY`, except the safe debug config endpoint.

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
- Admin API keys must not be hardcoded in Flutter or committed. The admin panel asks for the key at runtime.

## Current Priorities

Current priority: continue ticket/admin management workflows when backend endpoints are ready, while keeping ChromaDB-backed RAG untouched.

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

Latest verified backend test run: `297 passed` using `pytest tests/ -q` from `backend/`.

Latest Flutter verification attempt: `dart format lib`, `flutter analyze`, and `flutter test` from `flutter_app/` timed out in the local tooling environment because the Dart/Flutter tool hung before reporting results. Manual static inspection confirmed admin sidebar role filtering and admin page guards.

## Rules for Future Codex Sessions

Every future coding session should:

- Read `PROJECT_MEMORY.md` first.
- Preserve the stable architecture.
- Avoid unnecessary redesigns.
- Update `PROJECT_MEMORY.md` whenever a major feature is completed.
- Update the Current Priorities section after completing a milestone.
- Update the Completed Features section when new capabilities are added.
- Keep this file concise, current, and useful as the single source of truth for project state.
