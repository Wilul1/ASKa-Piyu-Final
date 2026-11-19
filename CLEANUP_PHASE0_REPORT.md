# ASKa-Piyu Cleanup Report — Phase 0 (Safe Artifacts Only)

**Date:** 2026-11-19  
**Branch:** `main` @ `d813648` (`feat: add extraction review diagnostics`)  
**Scope executed:** Disposable local artifacts + `.gitignore` hardening only  
**Not executed:** Unused source/dependency dead-code audit (blocked by dirty feature tree)

---

## A. Summary

### What was cleaned
- Removed **68 root scratch files** (audit/probe/smoke/stress/hotfix/regression dumps and Flutter web deploy tarballs) plus **`layout_inspect/`**.
- Removed **3 ad hoc** `_web_only_cleanup_*.sh` helpers (no references in `.github` / `deploy` / `scripts`).
- Deleted **5 local throwaway Python venvs** under `backend/` (~2.7 GB).
- Hardened [`.gitignore`](.gitignore) so those paths stay out of `git status`.

### What was improved
- Working tree noise reduced (status entries **205 → 196**).
- Disk reclaim from venvs + tarballs (~2.8 GB+).
- Clearer ignore rules for Heroku/migration debug venvs and layout scratch.

### Overall repository health
- **Feature work preserved** (59 protected `backend/app|alembic` + `flutter_app/lib` status lines unchanged).
- **Not yet handover-ready** for a full unused-code audit: large unfinished feature diffs remain uncommitted.
- Phase 0 made the tree safer/cleaner for ICT inspection of *local clutter*, not a complete source-quality pass.

---

## B. Removed files

### Root scratch / probe / deploy dumps (safe: already intended ignored; not product source)

| Path pattern | Why safe |
|---|---|
| `aska_*.json` | Local QA/audit/regression captures; listed in `.gitignore` |
| `_audit_*`, `_cert_*`, `_fix_*`, `_hotfix_*`, `_r123_*`, `_regression_*`, `_smoke_*`, `_stress_*`, `_val_*` | Manual verification scratch; may contain session/state filenames |
| `_flutter_web_*.tgz`, `flutter_web_deploy_*.tgz` | Old web build tarballs; regenerable, not source |
| `probe_out*` | Probe outputs |
| `_web_only_cleanup_{backup,install,sync}.sh` | Unreferenced ad hoc helpers; no deploy/CI references |
| `layout_inspect/` | Local PDF layout inspection scratch |

### Local venvs (safe: untracked, not production runtime)

| Path | Why safe |
|---|---|
| `backend/.heroku-web-venv/` | Local Heroku image debug venv (~1.4 GB) |
| `backend/.migration-venv-v1.0.0/` | One-off Alembic check venv |
| `backend/.migration-venv-v1.1.0/` | One-off Alembic check venv |
| `backend/.migration-venv-v1.4.0/` | One-off Alembic check venv |
| `backend/.migration-venv311/` | One-off Alembic check venv |

**Not removed:** `backend/venv/` (active project venv used for smoke tests).

---

## C. Modified files

| File | Purpose |
|---|---|
| [`.gitignore`](.gitignore) | Ignore `backend/.heroku-web-venv/`, `backend/.migration-venv*/`, `/layout_inspect/`, `/_web_only_cleanup_*.sh` |

No application source, Flutter screens, migrations, Docker/Heroku deploy files, evaluation datasets, or env files were edited in Phase 0 (beyond the ignore rules above). Pre-existing dirty feature files were left as-is.

---

## D. Dependencies

**None removed** from `requirements` / `pubspec.yaml`.  
Phase 0 did not audit package usage.

---

## E. Testing results

Commands actually run:

```text
# Ignore rule verification
git check-ignore -v --non-matching backend/.heroku-web-venv/ backend/.migration-venv-v1.0.0/ layout_inspect/
# Result: all three matched new/updated .gitignore rules

# App import smoke
backend\venv\Scripts\python.exe -c "from app.main import app; print(...)"
# Result: APP_OK ASKa-Piyu API

# Narrow pytest
backend\venv\Scripts\python.exe -m pytest tests/test_evaluation_datasets.py -q --tb=line
# Result: 11 passed in 2.96s
```

**Not run (out of Phase 0 scope):** full backend suite, Flutter tests, Heroku deploy, production DB/Chroma checks.

**Protected-path check:** before/after comparison of porcelain lines matching `backend/app/|flutter_app/lib/|backend/alembic/` → **59 → 59, intact**.

---

## F. Remaining issues (manual / next phase)

1. **Commit or branch** the ~196 remaining dirty feature/thesis paths before any unused-code cleanup.
2. **Full backend cleanup** after that: unused modules/imports (verify FastAPI routers, dynamic imports, eval, tickets, RAG).
3. **Full Flutter cleanup:** unused screens/widgets/assets/deps.
4. Decide whether `backend/benchmarks/**` investigation JSON stays in-repo for thesis handover or moves to an archive.
5. Decide policy for `appendix_evidence/` and `defense_smoke_evidence/` (evidence keep vs local-only).
6. Optional: delete `backend/scripts/_tmp_check_eval_tables.py` if confirmed one-off (not done in Phase 0).
7. Many local **git worktrees** remain on Desktop; not deleted (per plan). Prune only with explicit approval.

---

## G. Production safety

| Asset | Status |
|---|---|
| `Dockerfile.heroku-web`, `heroku.yml`, `.github` workflows | **Preserved** (untouched) |
| Alembic migrations / migration history | **Preserved** |
| `backend/data/`, Chroma knowledge-base data | **Preserved** (not touched; still gitignored runtime data) |
| Evaluation datasets / historical results under `backend/benchmarks/evaluation/` | **Preserved** |
| `.env` / secrets | **Preserved** (not read into report; not modified) |
| Auth/security mechanisms | **Preserved** |
| Commits / push / Heroku deploy | **Not performed** |

---

## H. Handover readiness

| Question | Assessment |
|---|---|
| Ready for ICT to inspect *local clutter*? | **Improved** — large junk/venvs gone |
| Ready for professional unused-code handover audit? | **Not yet** — unfinished feature tree must be committed/branched first |
| Ready to claim “clean production source”? | **No** — Phase 0 only |

**Recommended next step for ICT handover:**  
1) Branch/commit current feature work → 2) run full verified unused-code cleanup → 3) full test matrix → 4) Phase 1 report.

---

## Appendix — Phase 0 constraints honored

- No commit, push, deploy, DB migration, or Chroma mutation.
- No worktree/branch deletion.
- No speculative source deletions.
- Full unused-import / dead-module cleanup deferred by design due to dirty tree blocker.
