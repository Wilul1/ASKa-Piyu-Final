"""Phase 2A: retrieval-only expansion-rule benchmark with ablations.

Measures Hit@k / MRR for expected document sections. Does not call the LLM.

Usage (from backend/, against the configured Chroma store):

    python -m scripts.retrieval_expansion_benchmark
    python -m scripts.retrieval_expansion_benchmark --out /tmp/phase2a_results.json

Ablation modes (benchmark-only; production defaults unchanged):
  A. full pipeline
  B. query expansion disabled
  C. each QUERY_EXPANSION_RULE disabled individually
  D. named service/title boosts disabled
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import settings
from app.services.chroma_store import RetrievedChunk, get_knowledge_base_store
from app.services.retrieval_reranker import (
    QUERY_EXPANSION_RULES,
    RetrievalAblation,
    prepare_retrieval_query,
)

DATASET_PATH = Path(__file__).resolve().parents[1] / "benchmarks" / "retrieval_expansion_benchmark.json"
DEFAULT_OUT = Path(__file__).resolve().parents[1] / "benchmarks" / "results" / "phase2a_retrieval_expansion.json"


def _normalize(text: str) -> str:
    return " ".join((text or "").casefold().split())


def _chunk_labels(chunk: RetrievedChunk) -> dict[str, Any]:
    metadata = chunk.metadata or {}
    return {
        "title": metadata.get("title") or chunk.title,
        "article": metadata.get("article"),
        "section": metadata.get("section") or metadata.get("source_section"),
        "path": " > ".join(
            str(metadata.get(key))
            for key in ("chapter", "article", "section", "source_section", "title")
            if metadata.get(key)
        ),
        "category": metadata.get("category"),
        "subcategory": metadata.get("subcategory"),
        "original_score": chunk.original_score,
        "reranked_score": chunk.reranked_score,
        "rerank_reasons": list(chunk.rerank_reasons or [])[:16],
    }


def _haystack(chunk: RetrievedChunk) -> str:
    metadata = chunk.metadata or {}
    parts = [
        str(chunk.title or ""),
        str(metadata.get("title") or ""),
        str(metadata.get("article") or ""),
        str(metadata.get("section") or ""),
        str(metadata.get("source_section") or ""),
        str(metadata.get("canonical_topic") or ""),
        str(metadata.get("procedure_title") or ""),
        str(chunk.text or "")[:400],
    ]
    return _normalize(" ".join(parts))


def _matches_expected(chunk: RetrievedChunk, titles: list[str], article_substrings: list[str]) -> bool:
    hay = _haystack(chunk)
    for title in titles:
        needle = _normalize(title)
        if needle and needle in hay:
            return True
    for article in article_substrings:
        needle = _normalize(article)
        if needle and needle in hay:
            return True
    return False


def _expected_rank(
    chunks: list[RetrievedChunk],
    *,
    expected_titles: list[str],
    acceptable_titles: list[str],
    article_substrings: list[str],
) -> tuple[int | None, str]:
    """Return (1-based rank, match_kind) for the first expected/acceptable hit."""
    for index, chunk in enumerate(chunks, start=1):
        if _matches_expected(chunk, expected_titles, article_substrings):
            return index, "expected"
        if _matches_expected(chunk, acceptable_titles, []):
            return index, "acceptable"
    return None, "miss"


def _metrics_from_ranks(ranks: list[int | None]) -> dict[str, float]:
    n = len(ranks) or 1
    hit1 = sum(1 for rank in ranks if rank is not None and rank <= 1) / n
    hit3 = sum(1 for rank in ranks if rank is not None and rank <= 3) / n
    hit5 = sum(1 for rank in ranks if rank is not None and rank <= 5) / n
    mrr = sum((1.0 / rank) if rank else 0.0 for rank in ranks) / n
    return {
        "n": float(len(ranks)),
        "hit_at_1": round(hit1, 4),
        "hit_at_3": round(hit3, 4),
        "hit_at_5": round(hit5, 4),
        "mrr": round(mrr, 4),
    }


def _evaluate_case(
    store: Any,
    case: dict[str, Any],
    *,
    ablation: RetrievalAblation | None,
    top_k: int,
) -> dict[str, Any]:
    query = case["query"]
    prepared = prepare_retrieval_query(query, ablation=ablation)
    chunks = store.search(query, top_k=top_k, raw_k=max(top_k, 12), ablation=ablation)
    expected = list(case.get("expected_titles") or [])
    acceptable = list(case.get("acceptable_titles") or [])
    articles = list(case.get("expected_article_substrings") or [])
    out_of_scope = bool(case.get("out_of_scope"))

    if out_of_scope:
        # For OOS cases, a "hit" means no campus section is forced into Top-1 by expansion.
        # We still record ranks against expected (empty) and flag whether expansion fired.
        rank, match_kind = None, "out_of_scope"
        success_rank = None
    else:
        rank, match_kind = _expected_rank(
            chunks,
            expected_titles=expected,
            acceptable_titles=acceptable,
            article_substrings=articles,
        )
        success_rank = rank

    top = [_chunk_labels(chunk) for chunk in chunks[:5]]
    return {
        "id": case["id"],
        "query": query,
        "out_of_scope": out_of_scope,
        "depends_on_expansion_rule": bool(case.get("depends_on_expansion_rule")),
        "related_rules": list(case.get("related_rules") or []),
        "notes": case.get("notes") or "",
        "expanded_query": prepared.expanded_query,
        "matched_expansion_rules": list(prepared.matched_expansion_rules),
        "expected_rank": success_rank,
        "match_kind": match_kind,
        "hit_at_1": bool(success_rank is not None and success_rank <= 1),
        "hit_at_3": bool(success_rank is not None and success_rank <= 3),
        "hit_at_5": bool(success_rank is not None and success_rank <= 5),
        "reciprocal_rank": (1.0 / success_rank) if success_rank else 0.0,
        "top_sections": top,
        "top1_title": top[0]["title"] if top else None,
        "top1_reasons": top[0]["rerank_reasons"] if top else [],
    }


def _summarize(cases: list[dict[str, Any]], *, include_oos: bool = False) -> dict[str, Any]:
    scoped = [case for case in cases if include_oos or not case.get("out_of_scope")]
    ranks = [case.get("expected_rank") for case in scoped]
    metrics = _metrics_from_ranks(ranks)
    metrics["case_ids"] = [case["id"] for case in scoped]
    return metrics


def _classify_rule(
    *,
    full_rank: int | None,
    ablated_rank: int | None,
    case_ids_exercising: list[str],
) -> str:
    if not case_ids_exercising:
        return "not_exercised"
    # Lower rank number is better; None is worst.
    def score(rank: int | None) -> float:
        return float(rank) if rank is not None else math.inf

    if score(ablated_rank) > score(full_rank):
        # Removing the rule made the expected section worse / missing.
        if full_rank is not None and full_rank <= 3 and (ablated_rank is None or ablated_rank > 5):
            return "clearly_load_bearing"
        if full_rank is not None and (ablated_rank is None or ablated_rank > full_rank):
            return "helpful_but_not_required" if (ablated_rank is not None and ablated_rank <= 5) else "clearly_load_bearing"
    if score(ablated_rank) < score(full_rank):
        return "harmful"
    return "no_measurable_effect"


def run_benchmark(top_k: int = 5) -> dict[str, Any]:
    dataset = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    cases = list(dataset["cases"])
    store = get_knowledge_base_store()
    if store.chunk_count == 0:
        raise SystemExit(
            f"Knowledge base empty (chroma_persist_dir={settings.chroma_persist_dir!r})."
        )

    modes: dict[str, RetrievalAblation | None] = {
        "full": None,
        "no_expansion": RetrievalAblation(disable_query_expansion=True),
        "no_named_service_boosts": RetrievalAblation(disable_named_service_boosts=True),
    }

    mode_results: dict[str, list[dict[str, Any]]] = {}
    for mode_name, ablation in modes.items():
        mode_results[mode_name] = [
            _evaluate_case(store, case, ablation=ablation, top_k=top_k) for case in cases
        ]

    # Per-rule ablation only for rules that fire on at least one in-scope case
    # under the full pipeline, plus every named related_rule from the dataset.
    full_by_id = {row["id"]: row for row in mode_results["full"]}
    exercised: set[str] = set()
    for row in mode_results["full"]:
        exercised.update(row.get("matched_expansion_rules") or [])
    for case in cases:
        exercised.update(case.get("related_rules") or [])

    per_rule: dict[str, Any] = {}
    for rule in QUERY_EXPANSION_RULES:
        rule_name = rule.name
        if rule_name not in exercised:
            per_rule[rule_name] = {
                "classification": "not_exercised",
                "exercised_by_cases": [],
                "case_deltas": [],
            }
            continue
        ablated_rows = [
            _evaluate_case(
                store,
                case,
                ablation=RetrievalAblation(disable_expansion_rules=frozenset({rule_name})),
                top_k=top_k,
            )
            for case in cases
            if rule_name in (case.get("related_rules") or [])
            or rule_name in (full_by_id[case["id"]].get("matched_expansion_rules") or [])
        ]
        deltas = []
        classifications = []
        for row in ablated_rows:
            before = full_by_id[row["id"]]
            delta = {
                "case_id": row["id"],
                "query": row["query"],
                "full_rank": before.get("expected_rank"),
                "ablated_rank": row.get("expected_rank"),
                "full_hit_at_1": before.get("hit_at_1"),
                "ablated_hit_at_1": row.get("hit_at_1"),
                "full_hit_at_3": before.get("hit_at_3"),
                "ablated_hit_at_3": row.get("hit_at_3"),
                "full_hit_at_5": before.get("hit_at_5"),
                "ablated_hit_at_5": row.get("hit_at_5"),
                "full_top1": before.get("top1_title"),
                "ablated_top1": row.get("top1_title"),
                "matched_rules_full": before.get("matched_expansion_rules"),
            }
            deltas.append(delta)
            classifications.append(
                _classify_rule(
                    full_rank=before.get("expected_rank"),
                    ablated_rank=row.get("expected_rank"),
                    case_ids_exercising=[row["id"]],
                )
            )
        # Aggregate classification: worst signal wins (harmful > load-bearing > helpful > none)
        priority = {
            "harmful": 4,
            "clearly_load_bearing": 3,
            "helpful_but_not_required": 2,
            "no_measurable_effect": 1,
            "not_exercised": 0,
        }
        overall = max(classifications, key=lambda item: priority[item]) if classifications else "not_exercised"
        per_rule[rule_name] = {
            "classification": overall,
            "exercised_by_cases": [delta["case_id"] for delta in deltas],
            "case_deltas": deltas,
        }

    # False-positive / harm examples under full pipeline
    false_positives = []
    case_by_id = {case["id"]: case for case in cases}
    for row in mode_results["full"]:
        case = case_by_id[row["id"]]
        if row.get("out_of_scope") and row.get("matched_expansion_rules"):
            false_positives.append(
                {
                    "case_id": row["id"],
                    "query": row["query"],
                    "matched_expansion_rules": row["matched_expansion_rules"],
                    "top1_title": row.get("top1_title"),
                    "top_sections": [item["title"] for item in row.get("top_sections") or []],
                    "note": "Out-of-scope query still triggered campus expansion rules.",
                }
            )
            continue
        if row.get("out_of_scope"):
            continue
        expected_titles = list(case.get("expected_titles") or [])
        acceptable_titles = list(case.get("acceptable_titles") or [])
        top1_title = _normalize(str(row.get("top1_title") or ""))
        expected_hit = any(_normalize(title) in top1_title or top1_title in _normalize(title) for title in expected_titles + acceptable_titles if title)
        if row.get("expected_rank") not in (None, 1) and not expected_hit:
            false_positives.append(
                {
                    "case_id": row["id"],
                    "query": row["query"],
                    "matched_expansion_rules": row["matched_expansion_rules"],
                    "expected_rank": row["expected_rank"],
                    "top1_title": row.get("top1_title"),
                    "note": "A non-expected section outranked the expected section.",
                }
            )

    no_exp = {row["id"]: row for row in mode_results["no_expansion"]}
    semantic_equal_or_better = []
    expansion_regressions = []
    for row in mode_results["full"]:
        if row.get("out_of_scope"):
            continue
        other = no_exp[row["id"]]
        full_rank = row.get("expected_rank")
        bare_rank = other.get("expected_rank")
        if bare_rank is not None and (full_rank is None or bare_rank <= full_rank):
            semantic_equal_or_better.append(
                {
                    "case_id": row["id"],
                    "query": row["query"],
                    "full_rank": full_rank,
                    "no_expansion_rank": bare_rank,
                }
            )
        if full_rank is not None and (bare_rank is None or bare_rank > full_rank):
            expansion_regressions.append(
                {
                    "case_id": row["id"],
                    "query": row["query"],
                    "full_rank": full_rank,
                    "no_expansion_rank": bare_rank,
                    "matched_expansion_rules": row.get("matched_expansion_rules"),
                }
            )

    summary = {
        "full": _summarize(mode_results["full"]),
        "no_expansion": _summarize(mode_results["no_expansion"]),
        "no_named_service_boosts": _summarize(mode_results["no_named_service_boosts"]),
        "full_including_oos_count": len(mode_results["full"]),
    }

    load_bearing = sorted(
        name for name, payload in per_rule.items() if payload["classification"] == "clearly_load_bearing"
    )
    helpful = sorted(
        name for name, payload in per_rule.items() if payload["classification"] == "helpful_but_not_required"
    )
    redundant = sorted(
        name for name, payload in per_rule.items() if payload["classification"] == "no_measurable_effect"
    )
    harmful = sorted(name for name, payload in per_rule.items() if payload["classification"] == "harmful")
    not_exercised = sorted(
        name for name, payload in per_rule.items() if payload["classification"] == "not_exercised"
    )

    return {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "dataset": str(DATASET_PATH),
            "dataset_version": dataset.get("version"),
            "chroma_persist_dir": settings.chroma_persist_dir,
            "chroma_collection_name": settings.chroma_collection_name,
            "embedding_model_name": settings.embedding_model_name,
            "chunk_count": store.chunk_count,
            "case_count": len(cases),
            "rule_count": len(QUERY_EXPANSION_RULES),
            "top_k": top_k,
        },
        "summary_metrics": summary,
        "mode_results": mode_results,
        "per_rule_ablation": per_rule,
        "classifications": {
            "clearly_load_bearing": load_bearing,
            "helpful_but_not_required": helpful,
            "no_measurable_effect": redundant,
            "harmful": harmful,
            "not_exercised": not_exercised,
        },
        "false_positive_examples": false_positives,
        "semantic_equal_or_better": semantic_equal_or_better,
        "expansion_needed_regressions": expansion_regressions,
        "phase2b_candidates": {
            "must_preserve_until_replacement": load_bearing,
            "safe_to_consider_removing_if_redundant": redundant,
            "harmful_investigate_first": harmful,
            "needs_more_benchmark_coverage": not_exercised,
            "helpful_keep_for_now": helpful,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()

    results = run_benchmark(top_k=args.top_k)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=2), encoding="utf-8")

    summary = results["summary_metrics"]
    classifications = results["classifications"]
    print(f"cases={results['meta']['case_count']} rules={results['meta']['rule_count']}")
    print(
        "full:     "
        f"Hit@1={summary['full']['hit_at_1']} "
        f"Hit@3={summary['full']['hit_at_3']} "
        f"Hit@5={summary['full']['hit_at_5']} "
        f"MRR={summary['full']['mrr']}"
    )
    print(
        "no_exp:   "
        f"Hit@1={summary['no_expansion']['hit_at_1']} "
        f"Hit@3={summary['no_expansion']['hit_at_3']} "
        f"Hit@5={summary['no_expansion']['hit_at_5']} "
        f"MRR={summary['no_expansion']['mrr']}"
    )
    print(
        "no_boost: "
        f"Hit@1={summary['no_named_service_boosts']['hit_at_1']} "
        f"Hit@3={summary['no_named_service_boosts']['hit_at_3']} "
        f"Hit@5={summary['no_named_service_boosts']['hit_at_5']} "
        f"MRR={summary['no_named_service_boosts']['mrr']}"
    )
    print("load-bearing:", ", ".join(classifications["clearly_load_bearing"]) or "(none)")
    print("helpful:", ", ".join(classifications["helpful_but_not_required"]) or "(none)")
    print("redundant:", ", ".join(classifications["no_measurable_effect"]) or "(none)")
    print("harmful:", ", ".join(classifications["harmful"]) or "(none)")
    print("not exercised:", len(classifications["not_exercised"]))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
