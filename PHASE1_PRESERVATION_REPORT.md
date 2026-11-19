# ASKa-Piyu Phase 1 — Development Work Preservation Report

**Date:** 2026-11-19  
**Checkout:** `main` @ `d813648` (`feat: add extraction review diagnostics`, 2026-11-03)  
**Dirty tree:** **197** porcelain entries (69 modified, 1 deleted, 127 untracked)  
**Actions taken:** Inspection only — **no** commit, stash, reset, discard, cherry-pick, merge, or source edits.

---

## 1. Dirty file inventory

### Counts

| Kind | Count |
|---|---|
| Modified tracked | 69 |
| Deleted tracked | 1 (`flutter_app/assets/images/lspu_admin_building.png`) |
| Untracked paths | 127 (files + directories as reported by git) |
| **Total porcelain** | **197** |

### Magnitude of tracked diffs (vs this stale `main`)

`git diff --stat` against `HEAD`: **~13,711 insertions / ~2,512 deletions** across 70 paths.

### Critical context (read this first)

This working copy of `main` is **far behind** production-line history:

| Ref | Tip | vs this `HEAD` |
|---|---|---|
| `origin/main` | `7fa68f0` (2026-10-13) | This branch is **ahead 1** of origin/main (local commit only) |
| `heroku/main` | `4a6dd70` (2026-11-16) | **87 commits ahead** of this checkout, **1 behind** |
| `release/ticket-kb-coe-incomplete-ui-v90` | `d657a6d` (2026-11-17, OpenRouter embeds) | **91 commits ahead**, **1 behind**; **pushed** to `origin` |

Many paths that appear **untracked** here already exist as **committed** files on `heroku/main` and/or `v90`. They look “new” only because this `main` tip never received those merges.

**Do not treat this dirty tree as “the full product.”** The newest deployable line is closer to **`v90` / `heroku/main`**, not this Nov-3 `main`.

---

## 2. Feature grouping (what belongs together)

### Group A — Ticketing / office / transfers / ticket→KB

**Modified (on stale main):**  
`ticketing.py`, `ticket_knowledge.py`, `ticket_notifications.py`, `ticket_office_resolver.py`, `routes/tickets.py`, related models/schemas/tests, Flutter `staff_ticket_console`, `admin_all_tickets`, `my_tickets`, office tests.

**Untracked (already on heroku/v90):**  
migrations `20261013_0013_ticket_transfer_requests.py`, `20261014_0014_notification_transfer_request_id.py`, `incoming_transfers_page.dart`, `ticket_transfer_models.dart`, ticket FAQ/privacy tests, backfill script.

**Belong together:** yes — one product area.  
**Caution:** WT `ticket_knowledge.py` / `ticketing.py` are **behind** heroku/v90 (WT is smaller than production versions). Snapshotting WT alone can **lose** later ticket-KB fixes already on v90/heroku.

### Group B — Model Evaluation system

**Untracked packages/UI:**  
`backend/app/services/evaluation/`, `backend/app/routes/admin/evaluation.py`, migration `20261104_0015_evaluation_system.py`, Flutter eval screens/models/api/tests, `backend/benchmarks/evaluation/` (datasets + results).

**Already committed on:** `heroku/main`, `v90`, `deploy/evaluation-metrics-v75`.

**WT-unique within this group:** cleaned dataset notes/versions (`classification_eval_dataset.json` now `2026-11-04-v2`), shortened `evaluation_service.py` / `datasets.py` comments from earlier defense prep.

### Group C — KB ingestion / handbook / charter / chunking / Chroma

**Modified:**  
`digital_ingestion.py`, `knowledge_base_pipeline.py`, `handbook_policy_processor.py`, `citizen_charter_*`, `chroma_store.py`, `article_rag_indexer.py`, `knowledge_document_types.py`, OCR/PDF utils, related tests.

**Untracked:**  
`common_representation/` (WT has **extra** `layout.py`, `pipeline.py`, `reconstruction.py` vs 4 files on heroku),  
`handbook_lightweight_extraction.py` (**not found** on heroku/v90 — **unique to this WT**), chunking tests, chroma recovery scripts.

### Group D — RAG / QA / retrieval / citation

**Modified:**  
`question_answering.py`, `retrieval_reranker.py`, citation/QA tests.

**Untracked:**  
large `backend/benchmarks/citation_*` / `async_shadow_*` / investigation JSON set, citation grounding scripts/tests.

**Note:** OpenRouter Gemini embedding backend is on **`v90` only**, **not** in this WT disk copy of `embeddings.py` (matches HEAD; no OpenRouter symbol on disk/heroku).

### Group E — Flutter public/admin UI redesign

**Modified:**  
`student_home`, `knowledge_base_page`, `chatbot_page`, `public_site_header`, `sidebar`, `design_tokens`, `auth_split_shell`, admin panel/KB workspace screens, layout tests/goldens.

**Untracked:**  
`lspu_admin_building.jpg` (replaces deleted `.png`), `kb_header_crop.png`, goldens.

**Related branches/worktrees:** `deploy/public-ui-redesign-20261108`, `redesign-deploy-candidate`, ticket-KB UI releases.

### Group F — Thesis / appendix / defense evidence (non-runtime)

| Path | Size | Role |
|---|---|---|
| `appendix_evidence/` | ~54 MB, 251 files | Thesis appendix / provenance |
| `defense_smoke_evidence/` | ~130 MB, 1456 files | Defense smoke captures |
| `backend/benchmarks/*.json` (+ evaluation tree) | ~23 MB+ | Eval/citation investigation artifacts |
| `CLEANUP_PHASE0_REPORT.md` | small | Phase 0 report |

### Group G — Repo hygiene / ignore

**Modified:** `.gitignore` (Phase 0 venv/layout ignores), `.dockerignore`.

### Group H — Likely disposable / low value inside dirty tree

- `backend/scripts/_tmp_check_eval_tables.py`
- `__pycache__` under untracked `common_representation/` (should never be committed)
- Possibly regenerable Flutter linux/macos generated plugin files in **other** worktrees (not this WT)

---

## 3. Worktree relationships

| Worktree path | Branch | Tip | Notes |
|---|---|---|---|
| `Desktop/ASKa-piyu` (**this**) | `main` | `d813648` | Dirty; stale vs prod |
| `.../aska-piyu-ticket-kb-coe-incomplete-ui-v90` | `release/ticket-kb-coe-incomplete-ui-v90` | `d657a6d` | OpenRouter embed; **on origin**; lightly dirty (generated registrant files only) |
| `.../aska-piyu-redesign-prod-candidate` | `deploy/public-ui-redesign-20261108` | `ecde692` | UI redesign line |
| `.../aska-piyu-office-review` | `feature/office-transfer-workflow` | `674f95a` | Transfers (older tip) |
| `.../aska-piyu-handbook-release` | `release/handbook-structured-extraction` | `674f95a` | Same tip as office-review |
| Multiple ticket-KB fix/deploy WTs | various `fix/*` / `deploy/*` / `release/*` | — | Incremental ticket-KB history |
| `.../aska-piyu-evaluation-metrics-deploy` | `deploy/evaluation-metrics-v75` | `aed52c3` | **prunable** (broken gitdir) |
| Several other Desktop WTs | citation/oos/office/stage-4a/etc. | — | **prunable** |

**Prunable (broken gitdir) worktrees:** citation-release, evaluation-metrics-deploy, extraction-review-diagnostics, office-release, oos-fix-release, original-page-dialog, stage-4a-4b-deploy.  
Branches may still exist; only the worktree registration is broken. Do not delete branches without explicit approval.

---

## 4. Already committed elsewhere vs genuinely uncommitted

### Already on `heroku/main` and/or `v90` (untracked here only because `main` is stale)

- Full `backend/app/services/evaluation/` (core package)
- Admin evaluation route + evaluation Alembic migration
- Ticket transfer migrations + incoming transfers Flutter pieces
- Much of ticket/KB/eval UI history
- Per-user chat session key prefix (`aska_chat_sessions_v1_`) — present on **v90**; heroku still has older non-prefixed key

### Genuinely unique or newer on **this** working tree (preserve carefully)

1. **`handbook_lightweight_extraction.py`** — absent from heroku/v90 tips checked  
2. **Expanded `common_representation/`** — `layout.py`, `pipeline.py`, `reconstruction.py` beyond heroku’s 4-file package  
3. **Large handbook/charter/ingestion WT diffs** vs both HEAD and heroku (e.g. `handbook_policy_processor.py` still +798 vs heroku)  
4. **Cleaned evaluation datasets / shortened eval module comments** (dataset version string changed to `2026-11-04-v2`)  
5. **Phase 0 `.gitignore` hardening** + `CLEANUP_PHASE0_REPORT.md`  
6. **Speaker script** under `docs/` (see gitignore risk below)  
7. Portions of Flutter UI diffs that are **not** identical to heroku/v90 (chatbot/KB pages still differ)

### On `v90` / origin but **missing from this WT** (must not be lost)

- **OpenRouter Gemini embedding backend** (`OpenRouterGeminiEmbeddingFunction`) — only confirmed on `release/ticket-kb-coe-incomplete-ui-v90` (and origin). **Not** on this disk `embeddings.py`, **not** on `heroku/main` tip checked.

---

## 5. Potential conflicts / duplicates / abandoned experiments

| Risk | Detail |
|---|---|
| **Stale-base illusion** | Committing this WT onto `main` looks like “adding evaluation,” but prod already has it — high merge conflict / overwrite risk |
| **Ticket-KB divergence** | WT ticket modules are **behind** v90/heroku; “preserving WT” without rebasing can regress production fixes |
| **Embeddings split brain** | Defense OpenRouter work lives on `v90`; this WT still has older embeddings |
| **Duplicate feature history** | Many Desktop worktrees = same themes (ticket-KB, redesign, handbook) at different commits |
| **Broken worktrees** | 7 prunable entries — abandoned checkouts, not abandoned branches |
| **Benchmark JSON sprawl** | Dozens of citation/async_shadow investigation files — thesis archive, not runtime |
| **`__pycache__` in untracked tree** | Under `common_representation/` — noise if someone bulk-adds |

---

## 6. Gitignore blind spots (important work excluded?)

| Path | Ignored? | Risk |
|---|---|---|
| `docs/ASKa_Piyu_FOD_Speaker_Script.docx` | **YES** (`docs/`) | Defense speaker script **will not appear** in `git status` / normal commits |
| `backend/data/`, Chroma eval corpus | YES (correct) | Runtime data — keep ignored |
| `backend/.env` | YES (correct) | Secrets — keep ignored |
| `backend/venv/` | YES (correct) | Local env |
| Eval datasets/results under `backend/benchmarks/evaluation/` | **VISIBLE** | Good — not accidentally ignored |
| `appendix_evidence/`, `defense_smoke_evidence/` | **VISIBLE** | Large; decide archive vs commit |
| `CLEANUP_PHASE0_REPORT.md` | VISIBLE | OK |

**Recommendation:** copy or force-track the speaker script outside ignored `docs/` (e.g. `defense_docs/`) **after approval** — not done in Phase 1.

---

## 7. Preservation recommendations (no actions executed)

### Immediate safety (before any cleanup)

1. **Treat `origin/release/ticket-kb-coe-incomplete-ui-v90` as a protected tip** — it holds OpenRouter defense work and is already on GitHub.  
2. **Treat `heroku/main` (`4a6dd70`) as the production tip** — already on Heroku remote.  
3. **Snapshot this dirty WT** only as an explicit WIP backup (after your approval), e.g. branch name like `wip/main-dirty-snapshot-20261119`, without resetting `main`.  
4. **Do not** `git add -A` blindly — exclude `__pycache__`, and decide separately on `defense_smoke_evidence/` / huge benchmarks.  
5. **Do not** rebase/reset this WT onto heroku/v90 until the WIP snapshot exists.  
6. Rescue **`docs/` speaker script** from ignore blindness (copy path outside `docs/` or approved force-add).

### What “preserving current development work” means here

Preserve **three layers**, not one:

| Layer | Where it lives | Why |
|---|---|---|
| Production | `heroku/main` | Live deploy line |
| Defense/embed tip | `v90` on origin | OpenRouter + latest ticket-KB/UI |
| Local WIP deltas | This dirty WT | Unique extraction/common_representation/dataset cleanups/UI deltas |

---

## 8. Recommended branch strategy (for your approval)

Suggested sequence **after you approve** (Phase 1 stops here):

```text
1) Confirm remotes: origin has v90; heroku has main @ 4a6dd70
2) Create WIP snapshot branch from current HEAD + commit selected dirty paths
   -> wip/main-dirty-snapshot-20261119
3) Create integration base from newest product tip
   -> branch handover/integrate-from-v90  (from v90)
4) Cherry-pick / manually port ONLY unique WT deltas onto that base
   (handbook_lightweight_extraction, extra common_representation modules,
    cleaned datasets if desired, any Flutter deltas still missing)
5) Keep thesis evidence either:
   - on a separate branch archive/thesis-evidence-20261119, or
   - outside git / in appendix packaging
6) Only then run Phase 2 source cleanup on the integration branch
```

**Do not** use this stale `main` as the cleanup base.

**Do not** delete worktrees/branches in Phase 2 without a written keep/drop list.

---

## 9. Stop / wait for approval

Phase 1 complete: inventory, grouping, worktree map, conflict analysis, gitignore review, and preservation strategy are documented.

**No git mutations or source changes were made in Phase 1.**

Please approve one of:

1. **Snapshot WIP branch** from this dirty tree (selected paths), or  
2. **Skip WT snapshot** (rely on v90 + heroku only) and proceed to plan unique-delta porting, or  
3. **Adjust keep/drop** for `appendix_evidence/` / `defense_smoke_evidence/` / benchmarks before any further phase.
