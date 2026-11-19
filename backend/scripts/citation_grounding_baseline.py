"""Citation Grounding V2 -- Stage 1 baseline measurement (lexical V1 only).

Runs the REAL, unmodified V1 production pipeline (``answer_qa_question``) for
every case in ``backend/benchmarks/citation_grounding_benchmark.json``, using
the ``citation_debug_sink`` / ``generation_usage_sink`` instrumentation (see
``app/services/qa/question_answering.py`` and
``app/services/qa/groq_answer_service.py``) purely as an observer. That
instrumentation is inert by construction (see the referenced modules and
their tests): with the sinks omitted, ``answer_qa_question`` reproduces
production commit 54975af's citation selection exactly, so running this
script cannot itself change what V1 selects or returns.

This script does NOT implement, call, or simulate the Citation Grounding V2
LLM verifier. It measures the CURRENT lexical selector
(``_select_supporting_context``) only, in lexical mode, as the "before"
baseline that a future verifier will be compared against.

Honesty rules this script follows (see the benchmark file's own
``labeling_methodology`` for the full definitions):

* Layer A (answer-level Citation Set Precision/Recall) distinguishes an
  UNLABELED case (``gold_supporting_chunk_ids`` is ``null`` -- not yet
  adjudicated, excluded from measured evaluation) from an ADJUDICATED
  empty-gold case (``gold_supporting_chunk_ids == []`` -- a labeler
  determined no supporting source exists). These are never merged: a plain
  ``if not gold`` check would treat "unknown" and "adjudicated: nothing
  supports this" as the same case, which they are not. See
  ``_layer_a_for_case`` below for the four resulting statuses
  (``excluded_unlabeled``, ``correct_abstention``,
  ``false_positive_citations``, ``scored``). Every case in the current
  benchmark file is ``excluded_unlabeled`` today (no case has been through
  the two-labeler-plus-adjudication process yet); this script never
  substitutes V1's own displayed citations as a stand-in gold set -- that
  would be circular.
* Layer B (claim-level entailment) is always ``"not_applicable_v1_lexical_
  baseline"`` -- V1 has no notion of per-claim entailment.
* "Unsupported Claim Rate" is NOT computed in this Stage 1 baseline. It
  depended on the production claim splitter (``_answer_claims`` /
  ``_CLAIM_SPLIT_RE``) and an experimental coverage-floor concept that were
  never part of the reviewed, committed production pipeline (54975af) --
  see the module docstring history for details. Fixing or extending the
  production claim splitter is out of scope for Stage 1, whose job is
  answer-level citation-set measurement (Layer A), not claim-level
  statistics. This metric is deferred until Citation Grounding V2 defines
  an explicit, separately reviewed claim-extraction contract; it is not
  fabricated or approximated here.
* Citation Redundancy Rate is computed ONLY when a case's
  ``evidence_equivalence_groups`` is non-null; otherwise
  ``"not_computed: no_gold_labels"``.
* A case whose answer cannot be reproduced standalone -- e.g. a follow-up
  question that depends on conversation history this benchmark file does
  not store and replay -- is EXCLUDED from executable evaluation rather
  than being replayed without that history and silently scored as if it
  were a fresh question. See ``reproducible_standalone`` below.

Usage (from backend/, against whatever Chroma store your .env points at --
this calls the real retrieval + rerank + generation pipeline, so it is NOT
free/instant like rag_benchmark.py; expect real LLM latency per case):

    python -m scripts.citation_grounding_baseline
    python -m scripts.citation_grounding_baseline --out /tmp/stage1_baseline.json
    python -m scripts.citation_grounding_baseline --dataset benchmarks/my_cases.json
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.qa.question_answering import answer_qa_question

DATASET_PATH = (
    Path(__file__).resolve().parents[1] / "benchmarks" / "citation_grounding_benchmark.json"
)
DEFAULT_OUT = (
    Path(__file__).resolve().parents[1]
    / "benchmarks"
    / "results"
    / "citation_grounding_baseline.json"
)

NOT_COMPUTED_NO_GOLD = "not_computed: no_gold_labels"
NOT_APPLICABLE_V1 = "not_applicable_v1_lexical_baseline"


def _layer_a_for_case(case: dict[str, Any], displayed_ids: list[str]) -> dict[str, Any]:
    """Answer-level Citation Set Precision/Recall for one case.

    Distinguishes ``gold_supporting_chunk_ids is None`` (this case has not
    been adjudicated -- its ground truth is simply unknown, and it must be
    excluded from any measured Precision/Recall average) from
    ``gold_supporting_chunk_ids == []`` (a labeler adjudicated this
    question and determined that no supporting source exists -- a valid,
    scorable outcome in its own right). ``if not gold:`` would incorrectly
    treat both as the same "no gold" bucket; this function never does that.
    """
    gold = case.get("labeling", {}).get("gold_supporting_chunk_ids")

    if gold is None:
        return {
            "status": "excluded_unlabeled",
            "precision": NOT_COMPUTED_NO_GOLD,
            "recall": NOT_COMPUTED_NO_GOLD,
            "reason": (
                "case['labeling']['gold_supporting_chunk_ids'] is null -- "
                "this case has not been through the two-labeler+adjudication "
                "process yet, so its ground truth is unknown. Excluded from "
                "measured Layer A evaluation, not scored as zero."
            ),
        }

    gold_set = set(gold)
    shown_set = set(displayed_ids)
    true_positive = len(gold_set & shown_set)

    if not gold_set:
        # Adjudicated: a labeler determined no supporting source exists for
        # this question. This is NOT the same as "unlabeled" above.
        if not shown_set:
            return {
                "status": "correct_abstention",
                "precision": None,
                "recall": None,
                "true_positive": 0,
                "gold_count": 0,
                "shown_count": 0,
                "reason": (
                    "Adjudicated gold_supporting_chunk_ids == [] (no "
                    "supporting source exists) and V1 displayed zero "
                    "citations -- correct abstention. Precision/recall are "
                    "not computed (both denominators are zero); this case "
                    "should be counted as a correct abstention, not omitted."
                ),
            }
        return {
            "status": "false_positive_citations",
            "precision": 0.0,
            "recall": None,
            "true_positive": 0,
            "gold_count": 0,
            "shown_count": len(shown_set),
            "reason": (
                "Adjudicated gold_supporting_chunk_ids == [] (no "
                "supporting source exists) but V1 displayed "
                f"{len(shown_set)} citation(s) -- every displayed citation "
                "is a false positive by definition. Recall is not computed "
                "(zero gold items to recall)."
            ),
        }

    precision = (true_positive / len(shown_set)) if shown_set else None
    recall = true_positive / len(gold_set)
    return {
        "status": "scored",
        "precision": precision,
        "recall": recall,
        "true_positive": true_positive,
        "gold_count": len(gold_set),
        "shown_count": len(shown_set),
    }


def _redundancy_for_case(case: dict[str, Any], displayed_ids: list[str]) -> dict[str, Any]:
    groups = case.get("labeling", {}).get("evidence_equivalence_groups")
    if not groups:
        return {
            "redundancy_rate": NOT_COMPUTED_NO_GOLD,
            "reason": (
                "case['labeling']['evidence_equivalence_groups'] is null -- "
                "not labeled yet."
            ),
        }
    id_to_group: dict[str, int] = {}
    for group_index, group in enumerate(groups):
        for chunk_id in group:
            id_to_group[chunk_id] = group_index
    group_counts: dict[int, int] = {}
    for chunk_id in displayed_ids:
        group_index = id_to_group.get(chunk_id)
        if group_index is not None:
            group_counts[group_index] = group_counts.get(group_index, 0) + 1
    redundant = sum(count - 1 for count in group_counts.values() if count > 1)
    return {
        "redundancy_rate": (redundant / len(displayed_ids)) if displayed_ids else None,
        "redundant_extra_citations": redundant,
    }


def run_case(case: dict[str, Any]) -> dict[str, Any]:
    """Run one benchmark case through the real V1 pipeline, or, when the
    case is marked non-reproducible standalone (e.g. a follow-up question
    whose required conversation history this benchmark does not store and
    replay), skip execution entirely rather than answering it out of
    context and scoring a result that was never actually reproduced."""
    if not case.get("reproducible_standalone", True):
        return {
            "id": case["id"],
            "question": case["question"],
            "excluded": True,
            "exclusion_reason": case.get(
                "reproducible_standalone_note",
                "Case marked reproducible_standalone: false -- required "
                "conversation history is not captured in this benchmark "
                "file, so it cannot be replayed as a standalone question.",
            ),
        }

    debug_sink: list[dict[str, Any]] = []
    usage_sink: dict[str, Any] = {}
    started = time.perf_counter()
    error: str | None = None
    result = None
    try:
        result = answer_qa_question(
            case["question"],
            user_role=case.get("user_role"),
            citation_debug_sink=debug_sink,
            generation_usage_sink=usage_sink,
        )
    except Exception as exc:  # noqa: BLE001 -- one bad case must not kill the run
        error = f"{type(exc).__name__}: {exc}"
    elapsed_ms = (time.perf_counter() - started) * 1000.0

    if error is not None:
        return {
            "id": case["id"],
            "question": case["question"],
            "error": error,
            "latency_ms": elapsed_ms,
        }

    # Identity fix (Stage 1 cleanup): record the exact identity
    # `result.sources` actually exposes -- `citation_id` -- not the coarser
    # `document_id`, which is shared across multiple distinct chunks of the
    # same source document and would silently collapse them.
    displayed_ids = [source.get("citation_id") for source in (result.sources or [])]
    displayed_ids = [d for d in displayed_ids if d]
    displayed_titles = [source.get("title") for source in (result.sources or [])]

    row = {
        "id": case["id"],
        "question": case["question"],
        "user_role": case.get("user_role"),
        "latency_ms": elapsed_ms,
        "confidence": result.confidence,
        "displayed_citation_count": len(result.sources or []),
        "displayed_citation_titles": displayed_titles,
        "displayed_citation_ids": displayed_ids,
        "retrieved_chunk_count": len(result.retrieved_chunks or []),
        "generation_usage": usage_sink or None,
        "generation_usage_note": (
            None
            if usage_sink
            else (
                "empty -- either Groq was not called for this turn (typed/"
                "fallback/out-of-scope answer path) or the provider's "
                "response omitted a usage object; not an error."
            )
        ),
        "layer_a": _layer_a_for_case(case, displayed_ids),
        "layer_b": {
            "status": NOT_APPLICABLE_V1,
            "reason": case.get("layer_b_note"),
        },
        "citation_redundancy": _redundancy_for_case(case, displayed_ids),
        "citation_debug_row_count": len(debug_sink),
    }
    return row


def run_benchmark(dataset_path: Path) -> dict[str, Any]:
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    cases = dataset.get("cases", [])
    rows = [run_case(case) for case in cases]

    excluded_rows = [r for r in rows if r.get("excluded")]
    ok_rows = [r for r in rows if "error" not in r and not r.get("excluded")]
    error_rows = [r for r in rows if "error" in r]

    layer_a_by_status: dict[str, int] = {}
    for r in ok_rows:
        status = r["layer_a"].get("status", "unknown")
        layer_a_by_status[status] = layer_a_by_status.get(status, 0) + 1
    layer_a_computed = [
        r for r in ok_rows if isinstance(r["layer_a"].get("precision"), (int, float))
    ]

    summary = {
        "dataset_version": dataset.get("version"),
        "case_count": len(cases),
        "ok_count": len(ok_rows),
        "error_count": len(error_rows),
        "excluded_count": len(excluded_rows),
        "excluded_note": (
            "Cases excluded from executable evaluation because they are "
            "not reproducible standalone (e.g. follow-up questions whose "
            "required conversation history is not captured in this "
            "benchmark file) -- see each row's exclusion_reason."
        ),
        "mean_latency_ms": (
            sum(r["latency_ms"] for r in ok_rows) / len(ok_rows) if ok_rows else None
        ),
        "mean_displayed_citation_count": (
            sum(r["displayed_citation_count"] for r in ok_rows) / len(ok_rows)
            if ok_rows
            else None
        ),
        "layer_a_status_counts": layer_a_by_status,
        "layer_a_cases_with_gold_labels": len(layer_a_computed),
        "layer_a_note": (
            f"{len(layer_a_computed)}/{len(ok_rows)} cases had adjudicated "
            "non-empty gold labels to score numeric Precision/Recall "
            "against (status 'scored'). 0 is expected until the two-"
            "labeler+adjudication process actually runs on this benchmark "
            "file. 'excluded_unlabeled' cases are never averaged into any "
            "reported metric; 'correct_abstention' and "
            "'false_positive_citations' are adjudicated outcomes without a "
            "numeric precision/recall pair (see layer_a_status_counts)."
        ),
        "layer_b_note": (
            "not_applicable_v1_lexical_baseline for all cases -- V1 has no "
            "per-claim entailment notion."
        ),
        "unsupported_claim_rate_note": (
            "Not computed in this Stage 1 baseline -- deferred pending an "
            "explicit, separately reviewed claim-extraction contract for "
            "Citation Grounding V2. See module docstring."
        ),
    }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "lexical_v1_baseline_only",
        "summary": summary,
        "cases": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DATASET_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    report = run_benchmark(args.dataset)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    summary = report["summary"]
    print(f"dataset={args.dataset}")
    print(
        f"cases={summary['case_count']} ok={summary['ok_count']} "
        f"errors={summary['error_count']} excluded={summary['excluded_count']}"
    )
    print(f"mean_latency_ms={summary['mean_latency_ms']}")
    print(f"mean_displayed_citation_count={summary['mean_displayed_citation_count']}")
    print(f"layer_a_status_counts={summary['layer_a_status_counts']}")
    print(f"layer_a_cases_with_gold_labels={summary['layer_a_cases_with_gold_labels']}/{summary['ok_count']}")
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
