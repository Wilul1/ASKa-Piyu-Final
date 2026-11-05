"""The human QA overlay headline numbers must stay unchanged, and the
per-question rows must be the same judgments that produced those averages.
"""

from __future__ import annotations

from app.services.evaluation.human_rag_overview import (
    load_human_rag_overview,
    overlay_case_breakdown,
)


def test_overlay_headline_metrics_are_unchanged():
    payload = load_human_rag_overview()
    assert payload is not None
    metrics = payload["metrics"]
    assert metrics["answer_correctness"]["value"] == 0.5833
    assert metrics["faithfulness"]["value"] == 0.5417
    assert metrics["answer_relevancy"]["value"] == 0.9167
    assert metrics["citation_set_precision"]["value"] == 0.9000


def test_overlay_case_rows_recompute_to_headline_metrics():
    cases = overlay_case_breakdown()
    assert cases is not None
    assert len(cases) == 14
    included = [case for case in cases if case.get("included")]
    excluded = [case for case in cases if not case.get("included")]
    assert len(included) == 12
    assert {case["case_id"] for case in excluded} == {
        "aq_09_faculty_teaching_load",
        "aq_10_faculty_responsibilities",
    }

    def _mean(name: str) -> float:
        scores = [float(case[name]["score"]) for case in included]
        return sum(scores) / len(scores)

    def _citation_mean() -> float:
        scores = [
            float(case["citation"]["score"])
            for case in included
            if case["citation"].get("score") is not None
        ]
        return sum(scores) / len(scores)

    assert round(_mean("correctness"), 4) == 0.5833
    assert round(_mean("faithfulness"), 4) == 0.5417
    assert round(_mean("relevance"), 4) == 0.9167
    assert round(_citation_mean(), 4) == 0.9
    assert all("question" in case and case["question"] for case in cases)
