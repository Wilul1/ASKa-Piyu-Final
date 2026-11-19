"""Fresh Gold Benchmark Capture -- CAPTURE INFRASTRUCTURE ONLY.

This script does NOT implement, call, or simulate the Citation Grounding V2
LLM verifier, does NOT change citation-selection/retrieval/reranking/
embeddings/prompts/audience-retrieval behavior, and does NOT change any
public API schema. It is a standalone, in-process capture tool --
architecturally modeled on ``scripts/citation_grounding_baseline.py`` --
that runs the REAL, unmodified ``answer_qa_question`` pipeline exactly once
per case, using the ``citation_debug_sink`` / ``generation_usage_sink`` /
``answer_rewrite_sink`` / ``generation_context_sink`` instrumentation (all
inert by construction: see ``app/services/qa/question_answering.py`` and its
tests) purely as an observer, and writes one complete capture record per
case for later human adjudication (Stage 2's worksheet process).

There is exactly ONE ``generate_groq_answer`` call site in
``answer_qa_question`` (verified by inspection, not assumed -- a single
``grep`` for the call finds it once, at the try block inside that
function). This script therefore never has to disambiguate between
multiple generation calls for one request.

RETRIEVED CONTEXT != DISPLAYED CITATIONS: every capture record keeps three
explicitly distinct layers, never collapsed into one another --

* ``retrieval.role_filtered_candidate_pool`` (layer A) -- every chunk in
  ``result.retrieved_chunks`` (already role-filtered by the real pipeline;
  this script never issues a second Chroma query to reconstruct or verify
  that pool). Its ``selected_for_context`` flags are diagnostic only, from
  an EARLIER selection stage -- see the next bullet.
* ``retrieval.final_generation_context`` (layer B, AUTHORITATIVE) -- the
  exact final chunks actually passed as the ``context`` argument to
  ``generate_groq_answer``, captured by ``answer_qa_question`` itself
  strictly AFTER both ``_restore_missing_facet_context`` and (when
  applicable) ``_prefer_active_topic_context`` have already run (see
  ``question_answering._record_generation_context``). Layer A's
  ``selected_for_context`` flags predate those mutations and must never be
  used as a stand-in for this layer.
  ``retrieval.selected_context_citation_ids`` is a convenience projection
  of layer B's citation_ids only.
* ``v1_displayed_citations`` (layer C) -- the subset V1 actually showed.

Citation identity is ``citation_id`` everywhere in this file; ``document_id``
is carried only as metadata, never as identity (matching
``benchmarks/citation_grounding_benchmark.json``'s own
``labeling_methodology.citation_identity_definition``).

SECURITY -- evidence excerpt persistence (authoritative correction applied,
TWO independent fail-closed checks -- audience AND role):

    audience == "student"  -> may persist if the case's ROLE is a
                               recognized, authorized role
    audience == "both"     -> may persist if the case's ROLE is a
                               recognized, authorized role
    audience == "faculty"  -> may ONLY persist when the case ran under a
                               recognized faculty/office/admin role, per the
                               same allowed-audience semantics already
                               enforced in production retrieval
                               (``app.services.article_rag_indexer.
                               filter_chunks_for_audience``)
    missing/None/unknown/malformed AUDIENCE -> NEVER persist, for ANY role,
                               including admin.
    missing/None/empty/unknown/malformed ROLE -> NEVER persist, for ANY
                               audience, including "both". This is the
                               Stage 4 correction: an earlier version of
                               this gate coerced an unrecognized role to
                               "student", which would have let
                               student/both excerpts persist for a
                               null/malformed role. Role now fails closed
                               exactly as hard as audience does.

Both rules are deliberately stricter than production RETRIEVAL, which
defaults a missing/None role to "student" for filtering purposes only and
treats a missing chunk-audience tag as student-visible for *retrieval*
only. Neither default is reused here -- this is a capture-time,
storage-time rule about what gets written to disk, not a retrieval-time
one, and production audience retrieval behavior is unchanged by this file.

``is_excerpt_authorized`` (below) is a small, pure, independently
unit-tested function that implements exactly this rule, and it is always
evaluated BEFORE any excerpt text is added to a capture record --
``role_filtered_candidate_pool`` entries never carry excerpt/preview text at
all (by construction, this script never copies that field into a candidate
dict); only ``evidence_text.excerpts``, gated by this function, ever does.
There is no "build the full record, then sanitize" step anywhere in this
module.

IDENTITY QUALIFICATION (capture-time only, never affects the live QA
request): every capture record also carries ``identity_integrity``, which
flags -- without rewriting any id or failing the request -- (a) any
candidate whose ``citation_id`` was not backed by a stamped
``metadata["chunk_id"]`` (fell back to ``document_id::chunk_index``,
unstable/collision-prone), and (b) any displayed citation_id that could not
be reconciled against the captured candidate pool. Either sets
``ineligible_for_gold: true`` on that case so a future scoring script does
not silently trust an identity that was never actually gold-quality.

Per the approved Stage 3/4 scope: this script must NOT be executed against
live Groq/Chroma as part of implementing it -- it is reviewed as
infrastructure first, then piloted on 3-5 cases separately.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import settings
from app.services.chroma_store import get_knowledge_base_store
from app.services.qa.question_answering import answer_qa_question

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES_PATH = BACKEND_ROOT / "benchmarks" / "citation_grounding_capture_cases.json"
DEFAULT_OUT = BACKEND_ROOT / "benchmarks" / "results" / "citation_grounding_capture.json"

CAPTURE_SCRIPT_IDENTIFIER = "backend/scripts/citation_grounding_capture.py"
CAPTURE_SCRIPT_VERSION = "citation_grounding_capture/1.0.0"

# Glob patterns (relative to BACKEND_ROOT) covering the Stage 1 + capture
# infrastructure files this run's content-manifest hash is over. Stage 1
# and this capture infrastructure are currently uncommitted, so git_dirty
# alone cannot distinguish "unrelated local changes elsewhere" from "the
# actual capture/benchmark code differs between two runs" -- this manifest
# hash covers the specific files that matter for that question, tracked or
# not.
#
# Scope rule (Stage 5 item 2): mandatory here are PRODUCTION/instrumentation
# files that can change a captured VALUE -- question_answering.py (the
# pipeline itself, its sinks) and groq_answer_service.py (generation_usage
# telemetry, the raw Groq call this capture observes, depends on it).
# Deliberately EXCLUDED: tests/test_groq_answer_service.py and
# tests/test_qa_question_answering.py. Both are broad, general-purpose test
# suites (not specific to Stage 1/capture); a change to their test code
# does not change what a live capture run would actually produce, so
# folding them into a hash meant to answer "did the capture-affecting code
# change between two runs" would conflate test-code churn with runtime
# capture identity -- exactly what this rule exists to avoid. The narrower
# tests/test_citation_grounding_*.py files ARE included below because they
# are themselves Stage 1/capture-specific artifacts, not general QA tests.
_RELEVANT_STAGE_GLOB_PATTERNS = (
    "scripts/citation_grounding_*.py",
    "benchmarks/citation_grounding_*.json",
    "benchmarks/citation_grounding_*.md",
    "tests/test_citation_grounding_*.py",
    "app/services/qa/question_answering.py",
    "app/services/qa/groq_answer_service.py",
)

# --- Case definition ---------------------------------------------------------


@dataclass
class CaptureCase:
    """One question to capture. Mirrors the fields the approved design
    (Stage 3 §D) requires at minimum: case_id, category, question,
    user_role, conversation_history, optional active_service."""

    case_id: str
    category: str
    question: str
    user_role: str | None = None
    conversation_history: list[dict[str, str]] = field(default_factory=list)
    active_service: str | None = None
    is_followup: bool = False


def load_cases(path: Path) -> list[CaptureCase]:
    """Load case definitions from a JSON file shaped like
    ``{"cases": [ {case_id, category, question, ...}, ... ]}``.

    Required keys (``case_id``, ``category``, ``question``) are validated
    up front so a malformed case definition fails loudly here, not deep
    inside a live pipeline call.
    """
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    raw_cases = payload.get("cases", payload if isinstance(payload, list) else [])
    cases: list[CaptureCase] = []
    for raw in raw_cases:
        missing = {"case_id", "category", "question"} - set(raw.keys())
        if missing:
            raise ValueError(f"case definition missing required fields {missing}: {raw!r}")
        cases.append(
            CaptureCase(
                case_id=raw["case_id"],
                category=raw["category"],
                question=raw["question"],
                user_role=raw.get("user_role"),
                conversation_history=list(raw.get("conversation_history") or []),
                active_service=raw.get("active_service"),
                is_followup=bool(raw.get("is_followup", False)),
            )
        )
    return cases


# --- Evidence excerpt authorization (security gate) --------------------------

_KNOWN_AUDIENCE_VALUES = {"student", "faculty", "both"}

# Mirrors (does NOT call) the allowed-audience semantics already enforced by
# ``app.services.article_rag_indexer.filter_chunks_for_audience`` at
# retrieval time: office/admin see everything, faculty sees
# {faculty, both}, and student sees {student, both}. ``None`` here means
# "no restriction" (office/admin). Unlike production retrieval (which
# defaults a missing/None role to "student"), an unrecognized role here
# never falls into this table at all -- see ``normalize_role`` /
# ``is_excerpt_authorized`` below.
_ROLE_ALLOWED_AUDIENCES: dict[str, frozenset[str] | None] = {
    "admin": None,
    "office": None,
    "faculty": frozenset({"faculty", "both"}),
    "student": frozenset({"student", "both"}),
}

# The same role vocabulary the QA pipeline itself recognizes (see
# ``filter_chunks_for_audience`` / ``is_faculty_restricted_query`` in
# ``app.services.article_rag_indexer`` and ``app.services.qa.
# question_answering``) -- no new roles are invented here.
_KNOWN_ROLES = frozenset({"student", "faculty", "office", "admin"})


def normalize_audience(raw_audience: Any) -> str:
    """Normalize a raw chunk ``audience`` metadata value to a known label.

    Returns one of ``"student"`` | ``"faculty"`` | ``"both"``, or
    ``"unknown"`` for anything missing, ``None``, non-string, empty, or not
    exactly one of those three values. ``"unknown"`` always fails closed in
    ``is_excerpt_authorized`` regardless of role -- this function only
    classifies the raw value, it never grants access.
    """
    if not isinstance(raw_audience, str):
        return "unknown"
    value = raw_audience.strip().lower()
    return value if value in _KNOWN_AUDIENCE_VALUES else "unknown"


def normalize_role(raw_role: Any) -> str:
    """Normalize a raw case ``user_role`` value to a known QA-pipeline role.

    Returns one of ``"student"`` | ``"faculty"`` | ``"office"`` |
    ``"admin"``, or ``"unknown"`` for anything missing, ``None``,
    non-string, empty, or not exactly one of those four values.
    ``"unknown"`` always fails closed in ``is_excerpt_authorized``,
    regardless of audience -- including ``"both"``, which every recognized
    role is otherwise allowed to see. This function only classifies the
    raw value, it never grants access, and it never coerces an
    unrecognized value into a real role.
    """
    if not isinstance(raw_role, str):
        return "unknown"
    value = raw_role.strip().lower()
    return value if value in _KNOWN_ROLES else "unknown"


def is_excerpt_authorized(raw_audience: Any, case_role: str | None) -> bool:
    """Pure authorization check: may this chunk's excerpt be persisted?

    Two independent fail-closed checks, BOTH must pass:

    1. ``audience`` must normalize to a known value (student/faculty/both)
       -- an unknown/missing/None/malformed audience never authorizes
       persistence, for ANY role, including admin.
    2. ``case_role`` must normalize to a known QA-pipeline role
       (student/faculty/office/admin) -- an unknown/missing/None/malformed
       role never authorizes persistence, for ANY audience, including
       "both".

    Both checks are deliberately stricter than production RETRIEVAL, which
    defaults a missing/None role to "student" for filtering purposes
    (``(user_role or "student")`` in ``filter_chunks_for_audience`` and in
    ``is_faculty_restricted_query`` call sites) and treats a missing
    chunk-audience tag as student-visible. Those defaults are safe for
    scoping a live retrieval to a real, already-authenticated request; they
    are NOT safe to reuse here for deciding what text gets written into an
    on-disk benchmark/capture artifact, where "we don't actually know who
    this was for" must never quietly become "assume the
    least-restricted normal user." An earlier version of this function did
    exactly that coercion for an unrecognized role (silently treating it as
    "student", which would have let student/both excerpts persist for a
    null/malformed role) -- this is corrected here: role fails closed
    exactly as hard as audience does.

    This function takes no I/O, mutates nothing, and has no side effects,
    so it can be (and is) unit tested directly without any pipeline,
    Chroma, or Groq dependency.
    """
    audience = normalize_audience(raw_audience)
    if audience == "unknown":
        return False
    role = normalize_role(case_role)
    if role == "unknown":
        return False
    allowed = _ROLE_ALLOWED_AUDIENCES[role]
    return allowed is None or audience in allowed


# --- Reproducibility metadata -------------------------------------------------


def _run_git(*args: str) -> tuple[str | None, str | None]:
    """Run a git command; return (stdout, None) or (None, error_reason).

    Never raises -- a missing git binary, a non-repo working directory, or
    any other failure is reported as an explicit reason, never silently
    swallowed into a fabricated value.
    """
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=BACKEND_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"git command failed to run: {type(exc).__name__}: {exc}"
    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        return None, f"git exited {completed.returncode}: {stderr or 'no stderr output'}"
    return completed.stdout.strip(), None


def _manifest_hash_for_contents(contents: dict[str, bytes]) -> str:
    """Deterministic SHA-256 over a manifest of ``{relative_path: content}``.

    Deterministic for unchanged contents regardless of the dict's own
    iteration/insertion order: entries are always processed sorted by
    path. Each entry is hashed as ``path\\n<byte-length>\\n<content>\\n``
    so two adjacent entries can never be confused by an accidental
    delimiter collision inside file content. No mtimes, no absolute
    paths, no timestamps are ever part of the hashed material, so the
    same file contents always produce the same hash regardless of when or
    on which machine they are hashed.
    """
    hasher = hashlib.sha256()
    for rel_path in sorted(contents):
        content = contents[rel_path]
        hasher.update(rel_path.encode("utf-8"))
        hasher.update(b"\n")
        hasher.update(str(len(content)).encode("utf-8"))
        hasher.update(b"\n")
        hasher.update(content)
        hasher.update(b"\n")
    return hasher.hexdigest()


def _relevant_stage_files() -> list[Path]:
    """Deterministically ordered list of files the content-manifest hash
    covers, matched from ``_RELEVANT_STAGE_GLOB_PATTERNS`` -- both tracked
    and untracked, since Stage 1 + capture infrastructure are currently
    uncommitted and a hash that only covered tracked files would miss the
    actual code being run."""
    matched: set[Path] = set()
    for pattern in _RELEVANT_STAGE_GLOB_PATTERNS:
        matched.update(p for p in BACKEND_ROOT.glob(pattern) if p.is_file())
    return sorted(matched, key=lambda p: p.relative_to(BACKEND_ROOT).as_posix())


def _content_manifest_hash() -> tuple[str | None, str | None]:
    """SHA-256 manifest hash over the real, on-disk relevant stage files."""
    try:
        contents = {
            path.relative_to(BACKEND_ROOT).as_posix(): path.read_bytes()
            for path in _relevant_stage_files()
        }
    except OSError as exc:
        return None, f"{type(exc).__name__}: {exc}"
    return _manifest_hash_for_contents(contents), None


def _tracked_diff_hash() -> tuple[str | None, str | None]:
    """SHA-256 of the tracked working-tree diff against HEAD -- records a
    hash only, never the diff text itself, per the instruction not to
    persist the entire diff in every capture record.

    ``_run_git`` runs with ``cwd=BACKEND_ROOT`` (see below), which IS
    ``backend/`` already -- a pathspec of ``backend`` relative to that cwd
    would look for a nonexistent ``backend/backend/`` and match nothing
    (a real, previously-shipped bug: it silently hashed the empty diff on
    every run, tracked changes or not). The pathspec must be ``.``,
    meaning "everything under the current directory" relative to the cwd
    ``git diff`` is actually invoked from.
    """
    diff_text, diff_error = _run_git("diff", "HEAD", "--", ".")
    if diff_error:
        return None, diff_error
    return hashlib.sha256(diff_text.encode("utf-8")).hexdigest(), None


def build_run_context() -> dict[str, Any]:
    """Reproducibility metadata for this capture run (Stage 3 §F, Stage 4 §6).

    Every field either has a real, honestly-obtained value, or is ``None``
    with an explicit sibling ``*_error`` key recording why -- this function
    never invents a plausible-looking identity for a field it could not
    actually obtain. ``git_head_sha`` + ``git_dirty`` alone are not enough
    while Stage 1/capture files are uncommitted (a dirty tree could mean
    anything); ``tracked_diff_sha256`` and ``stage_files_content_sha256``
    add deterministic working-tree identity on top of that, as hashes only
    -- never the diff/file contents themselves.
    """
    context: dict[str, Any] = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "capture_script": CAPTURE_SCRIPT_IDENTIFIER,
        "capture_script_version": CAPTURE_SCRIPT_VERSION,
    }

    sha, sha_error = _run_git("rev-parse", "HEAD")
    context["git_head_sha"] = sha
    if sha_error:
        context["git_head_sha_error"] = sha_error

    porcelain, status_error = _run_git("status", "--porcelain")
    if status_error:
        context["git_dirty"] = None
        context["git_dirty_error"] = status_error
    else:
        context["git_dirty"] = bool(porcelain)

    diff_hash, diff_hash_error = _tracked_diff_hash()
    context["tracked_diff_sha256"] = diff_hash
    if diff_hash_error:
        context["tracked_diff_sha256_error"] = diff_hash_error

    manifest_hash, manifest_hash_error = _content_manifest_hash()
    context["stage_files_content_sha256"] = manifest_hash
    if manifest_hash_error:
        context["stage_files_content_sha256_error"] = manifest_hash_error

    try:
        context["groq_model"] = settings.groq_model
    except Exception as exc:  # pragma: no cover - defensive, mirrors git handling
        context["groq_model"] = None
        context["groq_model_error"] = f"{type(exc).__name__}: {exc}"

    try:
        context["chroma_collection_name"] = settings.chroma_collection_name
    except Exception as exc:  # pragma: no cover - defensive
        context["chroma_collection_name"] = None
        context["chroma_collection_name_error"] = f"{type(exc).__name__}: {exc}"

    try:
        store = get_knowledge_base_store()
        context["chroma_chunk_count"] = store.chunk_count
    except Exception as exc:
        context["chroma_chunk_count"] = None
        context["chroma_chunk_count_error"] = f"{type(exc).__name__}: {exc}"

    return context


# --- Capture ------------------------------------------------------------------


def _candidate_pool_from_retrieved_chunks(
    retrieved_chunks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """The role-filtered candidate pool (layer A), WITHOUT any excerpt/
    preview text.

    This is deliberately narrower than ``result.retrieved_chunks``: it never
    copies ``content_preview`` (or any other text field) into the returned
    dicts, so this candidate-pool structure can never itself be the source
    of an unauthorized-text leak -- excerpt text is added, separately and
    only for authorized chunks, in ``evidence_text`` by ``capture_case``.

    ``selected_for_context``/``context_filter_reasons`` are kept here as
    diagnostic flags from an EARLIER selection stage (before
    ``_restore_missing_facet_context`` and ``_prefer_active_topic_context``
    can still mutate the context). They are NOT authoritative for what was
    actually sent to generation -- that authority is
    ``retrieval.final_generation_context`` (layer B), built separately from
    ``generation_context_sink`` in ``capture_case``, never from these flags.
    """
    pool: list[dict[str, Any]] = []
    for row in retrieved_chunks:
        pool.append(
            {
                "citation_id": row.get("citation_id"),
                "citation_id_stamped": row.get("citation_id_stamped"),
                "title": row.get("title"),
                "document_id": row.get("document_id"),
                "source_filename": row.get("source_filename"),
                "path_or_section": row.get("path"),
                "page": row.get("page"),
                "chunk_index": row.get("chunk_index"),
                "audience": row.get("audience"),
                "original_score": row.get("original_score"),
                "reranked_score": row.get("reranked_score"),
                "boost_reasons": row.get("boost_reasons"),
                # Diagnostic only -- an earlier selection stage, predates
                # the context mutations layer B accounts for. See docstring.
                "selected_for_context": row.get("selected_for_context"),
                "context_filter_reasons": row.get("context_filter_reasons"),
            }
        )
    return pool


def _identity_integrity_check(
    candidate_pool: list[dict[str, Any]],
    v1_displayed_citations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Capture-time-only qualification check for quantitative gold use.

    Two independent checks, either of which is enough to fail:

    1. Every candidate must carry a STAMPED ``citation_id`` (i.e.
       ``metadata["chunk_id"]`` was actually present on the chunk) --
       an id that fell back to ``document_id::chunk_index`` is not
       guaranteed stable/unique across re-ingests, and collides silently
       when a real ``chunk_index == 0`` meets that same formula's own
       ``chunk_index or index`` substitution (see
       ``question_answering._raw_citation_id``'s own documented caveat).
    2. Every displayed citation_id must be reconcilable against the
       captured candidate pool's own citation_id space -- if a displayed
       id cannot be found there, the candidate-pool identity (computed
       without DB/PDF resolution, per design) has diverged from the
       resolved identity actually shown (e.g. a Postgres document remap).

    This NEVER fails the user-facing QA request and never rewrites any id
    to force a match -- it only annotates the CAPTURE record so a labeler
    or a future scoring script knows not to trust this case's identifiers
    for quantitative Precision/Recall without first fixing the underlying
    source data (stamping chunk_id) or investigating the mismatch. The
    capture may still be fully useful diagnostically even when this check
    fails.
    """
    unstamped_candidates = [
        {
            "citation_id": c.get("citation_id"),
            "title": c.get("title"),
            "document_id": c.get("document_id"),
            "chunk_index": c.get("chunk_index"),
        }
        for c in candidate_pool
        if not c.get("citation_id_stamped")
    ]

    candidate_id_space = {c.get("citation_id") for c in candidate_pool if c.get("citation_id")}
    displayed_ids = {c.get("citation_id") for c in v1_displayed_citations if c.get("citation_id")}
    unreconciled_displayed_ids = sorted(displayed_ids - candidate_id_space)

    issues: list[str] = []
    if unstamped_candidates:
        issues.append(
            f"{len(unstamped_candidates)} candidate(s) lack a stamped "
            "metadata chunk_id -- citation_id fell back to "
            "document_id::chunk_index, not gold-quality identity."
        )
    if unreconciled_displayed_ids:
        issues.append(
            f"{len(unreconciled_displayed_ids)} displayed citation_id(s) do "
            "not appear in the captured role_filtered_candidate_pool: "
            f"{unreconciled_displayed_ids}."
        )

    return {
        "status": "failed" if issues else "ok",
        "ineligible_for_gold": bool(issues),
        "issues": issues,
        "unstamped_candidates": unstamped_candidates,
        "unreconciled_displayed_citation_ids": unreconciled_displayed_ids,
    }


def capture_case(case: CaptureCase, run_context: dict[str, Any]) -> dict[str, Any]:
    """Run one case through the REAL pipeline exactly once and capture it.

    Never issues a second Chroma query: the only retrieval this function
    ever sees is whatever ``answer_qa_question`` itself performed for this
    one call, surfaced through ``result.retrieved_chunks``.
    """
    history = list(case.conversation_history or [])
    if case.is_followup and not history:
        return {
            "capture_id": str(uuid.uuid4()),
            "run": run_context,
            "case_id": case.case_id,
            "category": case.category,
            "captured": False,
            "capture_error": (
                "is_followup=True but conversation_history is empty or "
                "absent -- refusing to invoke answer_qa_question with "
                "fabricated/reconstructed history. Supply the real "
                "conversation history for this case, or mark it "
                "is_followup=False if it is genuinely standalone."
            ),
        }

    debug_sink: list[dict[str, Any]] = []
    usage_sink: dict[str, Any] = {}
    rewrite_sink: dict[str, Any] = {}
    generation_context_sink: dict[str, Any] = {}

    started = time.perf_counter()
    try:
        result = answer_qa_question(
            case.question,
            user_role=case.user_role,
            history=history,
            client_active_service=case.active_service,
            citation_debug_sink=debug_sink,
            generation_usage_sink=usage_sink,
            answer_rewrite_sink=rewrite_sink,
            generation_context_sink=generation_context_sink,
        )
    except Exception as exc:  # noqa: BLE001 -- one bad case must not kill the run
        return {
            "capture_id": str(uuid.uuid4()),
            "run": run_context,
            "case_id": case.case_id,
            "category": case.category,
            "captured": False,
            "capture_error": f"{type(exc).__name__}: {exc}",
            "latency_ms": (time.perf_counter() - started) * 1000.0,
        }
    elapsed_ms = (time.perf_counter() - started) * 1000.0

    retrieved_chunks = list(result.retrieved_chunks or [])
    displayed_sources = list(result.sources or [])

    candidate_pool = _candidate_pool_from_retrieved_chunks(retrieved_chunks)
    v1_displayed_citations = [
        {"citation_id": source.get("citation_id"), "title": source.get("title")}
        for source in displayed_sources
    ]

    # Layer B (authoritative): the exact final chunks generation actually
    # received, captured AFTER _restore_missing_facet_context and
    # _prefer_active_topic_context by answer_qa_question itself (see
    # question_answering._record_generation_context) -- never derived from
    # retrieved_chunks' selected_for_context flags, which reflect an
    # earlier, pre-mutation selection stage (see _candidate_pool_from_
    # retrieved_chunks' own docstring on that distinction).
    final_generation_context = list(generation_context_sink.get("final_context_chunks") or [])
    # Convenience projection of layer B ONLY -- never a re-derivation from
    # layer A's diagnostic flags.
    selected_context_citation_ids = [
        c.get("citation_id") for c in final_generation_context if c.get("citation_id")
    ]

    # Security gate: evaluated per candidate, BEFORE any excerpt text is
    # added to the record being built -- never "build the full record then
    # sanitize." A chunk that fails this check contributes nothing to
    # evidence_text at all, not even a placeholder.
    included_chunk_ids: list[str] = []
    excerpts: dict[str, str] = {}
    for row in retrieved_chunks:
        citation_id = row.get("citation_id")
        if not citation_id:
            continue
        if not is_excerpt_authorized(row.get("audience"), case.user_role):
            continue
        preview = row.get("content_preview")
        if not preview:
            continue
        included_chunk_ids.append(citation_id)
        excerpts[citation_id] = preview

    # rewrite_sink stays {} (empty) whenever the branch this request took
    # never reached _record_answer_rewrite at all (greeting, out-of-scope,
    # typed-answer, etc.) -- that is a DIFFERENT fact from "the rewrite
    # stage ran and every flag came out False", so the two must never be
    # conflated: an empty sink reports rewrite_applied as the literal
    # string "not_observed", never a dict of (possibly misleading) False
    # values.
    rewrite_stage_observed = bool(rewrite_sink)

    return {
        "capture_id": str(uuid.uuid4()),
        "run": run_context,
        "case_id": case.case_id,
        "category": case.category,
        "captured": True,
        "latency_ms": elapsed_ms,
        "question": {
            "text": case.question,
            "is_followup": case.is_followup,
            "client_active_service": case.active_service,
        },
        "user_role": case.user_role,
        "conversation_history": history,
        "answer": {
            "final_displayed": result.answer,
            "rewrite_stage_observed": rewrite_stage_observed,
            "raw_pre_rewrite": (
                rewrite_sink.get("evidence_bearing_answer") if rewrite_stage_observed else None
            ),
            "rewrite_applied": (
                {
                    "table_inversion_corrected": rewrite_sink.get("table_inversion_corrected", False),
                    "classification_template_applied": rewrite_sink.get(
                        "classification_template_applied", False
                    ),
                    "used_recovered_factual": rewrite_sink.get("used_recovered", False),
                }
                if rewrite_stage_observed
                else "not_observed"
            ),
            "confidence": result.confidence,
            "fallback_used": result.fallback_used,
            "fallback_reason": result.fallback_reason,
        },
        "retrieval": {
            "role_filtered_candidate_pool": candidate_pool,
            "final_generation_context": final_generation_context,
            "selected_context_citation_ids": selected_context_citation_ids,
            "generation_invoked": generation_context_sink.get("generation_invoked"),
            "generation_succeeded": generation_context_sink.get("generation_succeeded"),
            "generation_context_status": generation_context_sink.get("status"),
            "normalized_query": result.normalized_query,
            "expanded_query": result.expanded_query,
            "broad_query": result.broad_query,
            "detected_intent": result.detected_intent,
        },
        "citation_selector_debug": debug_sink,
        "v1_displayed_citations": v1_displayed_citations,
        "generation_usage": usage_sink or None,
        "evidence_text": {
            "policy": "withheld_by_default",
            "included_chunk_ids": included_chunk_ids,
            "excerpts": excerpts,
        },
        "identity_integrity": _identity_integrity_check(candidate_pool, v1_displayed_citations),
    }


def run_capture(cases: list[CaptureCase]) -> dict[str, Any]:
    run_context = build_run_context()
    rows = [capture_case(case, run_context) for case in cases]
    captured = [r for r in rows if r.get("captured")]
    failed = [r for r in rows if not r.get("captured")]
    return {
        "run": run_context,
        "case_count": len(cases),
        "captured_count": len(captured),
        "failed_count": len(failed),
        "cases": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    cases = load_cases(args.cases)
    report = run_capture(cases)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"cases={args.cases}")
    print(
        f"case_count={report['case_count']} captured={report['captured_count']} "
        f"failed={report['failed_count']}"
    )
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
