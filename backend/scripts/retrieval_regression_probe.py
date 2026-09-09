"""Retrieval regression probe for Phase 1 hardcoding cleanup.

Records retrieval/context/answer diagnostics for a fixed question set.
Run inside the API container with PYTHONPATH=/app.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from app.services.qa.question_answering import answer_qa_question

QUESTIONS = [
    ("excuse_slip", "How do I get an excuse slip if I missed class because I was sick?"),
    ("copy_of_grades", "How do I request a copy of grades?"),
    (
        "ojt_compound",
        "I want to deploy for OJT next term, but I still have an incomplete subject and unpaid fees. What do I need to settle first?",
    ),
    ("honorable_dismissal", "Where do I file a petition for honorable dismissal?"),
    ("incomplete_inc", "What happens if I get an incomplete (INC) grade?"),
    ("fees", "How much are the fees for a transcript of records?"),
    ("out_of_scope", "What is the weather in Manila today?"),
]


def main() -> int:
    label = sys.argv[1] if len(sys.argv) > 1 else "baseline"
    rows: list[dict[str, Any]] = []
    for key, question in QUESTIONS:
        result = answer_qa_question(question)
        retrieved = list(result.retrieved_chunks or [])
        selected = [row for row in retrieved if row.get("selected_for_context")]
        rows.append(
            {
                "key": key,
                "question": question,
                "confidence": result.confidence,
                "detected_intent": result.detected_intent,
                "normalized_query": result.normalized_query,
                "expanded_query": result.expanded_query,
                "matched_expansion_rules": list(result.matched_expansion_rules or []),
                "out_of_scope_detected": result.out_of_scope_detected,
                "answer": (result.answer or "")[:900],
                "source_titles": [s.get("title") for s in (result.sources or [])][:6],
                "selected_titles": [row.get("title") for row in selected][:6],
                "retrieved_top": [
                    {
                        "rank": row.get("rank"),
                        "title": row.get("title"),
                        "path": row.get("path"),
                        "original_score": row.get("original_score"),
                        "reranked_score": row.get("reranked_score"),
                        "selected_for_context": row.get("selected_for_context"),
                        "filter_reasons": row.get("filter_reasons"),
                        "rerank_reasons": (row.get("rerank_reasons") or [])[:12],
                    }
                    for row in retrieved[:8]
                ],
                "rerank_reasons_summary": result.rerank_reasons,
            }
        )
        print(
            f"[{label}] {key}: conf={result.confidence} "
            f"selected={rows[-1]['selected_titles'][:3]} "
            f"oos={result.out_of_scope_detected}"
        )

    out_path = f"/tmp/retrieval_regression_{label}.json"
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(rows, handle, indent=2)
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
