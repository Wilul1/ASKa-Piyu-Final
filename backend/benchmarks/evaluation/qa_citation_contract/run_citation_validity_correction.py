"""Stage 3.6: post-run citation-validity metric correction.

NOT a new judging run. Makes zero LLM/HTTP calls. Reuses the already-
recorded claim data from the Stage 3.5 citation-claim judging run
(qacj_citation_judging_20261110T082650Z/judgments.jsonl) exactly as
captured, and recomputes ONLY the citation_validity FractionMetric for
each already-judged (case, judge-slot) data point, using the Stage 3.6-
fixed resolve_citation_validity() in place of the original, confirmed-
defective one. The other four citation metrics (precision, completeness,
claim_support_rate, unsupported_claim_rate) are taken AS-IS from the
original run's own recorded per-judge CitationMetrics and asserted to be
byte-identical to what a fresh compute_citation_metrics() call produces
from the same recorded claims -- proving this script changes nothing
about them, only citation_validity.

Reads, never writes to: the Stage 3.4 capture, the Stage 3.5 judging run,
the dataset, or the locked corpus extract. Writes only a new, separate
correction artifact.
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.evaluation.qa_citation_capture import DEFAULT_RUNS_DIR  # noqa: E402
from app.services.evaluation.qa_citation_claim_judging import resolve_citation_validity  # noqa: E402
from app.services.evaluation.qa_citation_eligibility import load_captures_jsonl  # noqa: E402
from app.services.evaluation.qa_citation_metrics import (  # noqa: E402
    ClaimMetricInput,
    FractionMetric,
    compute_citation_metrics,
)

CAPTURE_RUN_DIR = (
    BACKEND_ROOT / "benchmarks" / "evaluation" / "qa_citation_runs" / "qac_capture_20261110T063448Z_f2dfa9d3"
)
ORIGINAL_JUDGING_RUN_DIR = (
    BACKEND_ROOT / "benchmarks" / "evaluation" / "qa_citation_runs" / "qacj_citation_judging_20261110T082650Z"
)
ORIGINAL_JUDGING_RUN_ID = "qacj_citation_judging_20261110T082650Z"


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _claim_inputs_from_recorded(parsed: dict[str, Any] | None) -> tuple[ClaimMetricInput, ...]:
    if not parsed:
        return ()
    claims = parsed.get("claims") or []
    return tuple(
        ClaimMetricInput(
            claim_id=c["claim_id"],
            requires_citation=c["requires_citation"],
            claim_support=c.get("claim_support"),
            supporting_displayed_ids=tuple(c.get("supporting_displayed_ids") or ()),
        )
        for c in claims
    )


def main() -> int:
    capture_path = CAPTURE_RUN_DIR / "captures.jsonl"
    capture_file_sha256 = hashlib.sha256(capture_path.read_bytes()).hexdigest()
    capture_records = {r["case_id"]: r for r in load_captures_jsonl(capture_path)}

    judging_summary_path = ORIGINAL_JUDGING_RUN_DIR / "judging_summary.json"
    judgments_path = ORIGINAL_JUDGING_RUN_DIR / "judgments.jsonl"
    original_summary = json.loads(judging_summary_path.read_text(encoding="utf-8"))
    original_citation_validity = original_summary["citation_aggregation"]["citation_validity"]
    judgment_rows = _load_jsonl(judgments_path)

    capture_summary = json.loads((CAPTURE_RUN_DIR / "summary.json").read_text(encoding="utf-8"))
    corpus_identity = capture_summary.get("corpus") or {}

    original_numerator_sum = 0
    original_denominator_sum = 0
    corrected_numerator_sum = 0
    corrected_denominator_sum = 0

    other_metrics_names = (
        "citation_precision",
        "citation_completeness",
        "claim_support_rate",
        "unsupported_claim_rate",
    )
    other_metrics_mismatches: list[dict[str, Any]] = []
    per_case_corrections: list[dict[str, Any]] = []
    cases_recomputed = 0
    citation_ids_recomputed = 0

    for row in judgment_rows:
        citation_block = row.get("citation")
        if not citation_block or citation_block.get("final_status") != "judged":
            continue
        case_id = row["case_id"]
        capture_record = capture_records.get(case_id)
        if capture_record is None:
            raise RuntimeError(f"Capture record not found for judged case {case_id!r}; stopping.")
        displayed_citation_ids = list(capture_record.get("displayed_citation_ids") or [])

        # The ONLY thing this script computes fresh: the corrected validity
        # mapping, using the Stage 3.6-fixed resolver. Everything else below
        # reuses already-recorded data.
        corrected_validity_by_id = resolve_citation_validity(
            displayed_citation_ids=displayed_citation_ids
        )
        original_validity_by_id = citation_block.get("citation_validity_by_id") or {}

        case_entry = {
            "case_id": case_id,
            "displayed_citation_ids": displayed_citation_ids,
            "original_citation_validity_by_id": original_validity_by_id,
            "corrected_citation_validity_by_id": corrected_validity_by_id,
        }
        per_case_corrections.append(case_entry)
        cases_recomputed += 1

        for slot_key in ("primary_judge", "secondary_judge"):
            slot = citation_block.get(slot_key)
            if not slot or slot.get("judge_execution_status") != "evaluated":
                continue
            claims = _claim_inputs_from_recorded(slot.get("parsed"))

            original_metrics = slot.get("citation_metrics") or {}
            original_validity_fraction = original_metrics.get("citation_validity") or {}
            original_numerator_sum += int(original_validity_fraction.get("numerator") or 0)
            original_denominator_sum += int(original_validity_fraction.get("denominator") or 0)

            corrected = compute_citation_metrics(
                displayed_citation_ids=displayed_citation_ids,
                claims=claims,
                citation_validity_by_id=corrected_validity_by_id,
            )
            corrected_numerator_sum += corrected.citation_validity.numerator
            corrected_denominator_sum += corrected.citation_validity.denominator
            citation_ids_recomputed += corrected.citation_validity.denominator

            # Validation: the other four metrics must be UNCHANGED -- same
            # claims, same displayed_citation_ids, only citation_validity_by_id
            # differs, and none of the other four metrics read that mapping.
            for name in other_metrics_names:
                orig = original_metrics.get(name) or {}
                new_fraction: FractionMetric = getattr(corrected, name)
                if (
                    orig.get("numerator") != new_fraction.numerator
                    or orig.get("denominator") != new_fraction.denominator
                ):
                    other_metrics_mismatches.append(
                        {
                            "case_id": case_id,
                            "slot": slot_key,
                            "metric": name,
                            "original": orig,
                            "recomputed": {
                                "numerator": new_fraction.numerator,
                                "denominator": new_fraction.denominator,
                            },
                        }
                    )

    denominator_matches_original = (
        corrected_denominator_sum == original_denominator_sum == int(original_citation_validity["denominator"])
    )

    corrected_value = (
        (corrected_numerator_sum / corrected_denominator_sum) if corrected_denominator_sum else None
    )

    judged_dt = datetime.now(timezone.utc)
    correction_run_id = f"qacj_citation_validity_correction_{judged_dt.strftime('%Y%m%dT%H%M%SZ')}"
    run_dir = DEFAULT_RUNS_DIR / correction_run_id
    if run_dir.exists():
        print(f"CORRECTION RUN DIRECTORY ALREADY EXISTS: {run_dir}", file=sys.stderr)
        return 2
    run_dir.mkdir(parents=True, exist_ok=False)

    report = {
        "correction_run_id": correction_run_id,
        "corrected_at": judged_dt.isoformat(),
        "note": (
            "This is a post-run metric correction, NOT a new citation-claim "
            "judging run. No chatbot generation, no citation verification, "
            "and no judge (LLM) calls occurred while producing this "
            "artifact -- it recomputes ONLY the citation_validity fraction "
            "from already-recorded claim data, using the Stage 3.6-fixed "
            "resolve_citation_validity() in place of the original, "
            "confirmed-defective one (which cross-checked an unrelated "
            "UUID namespace -- see qa_citation_claim_judging.py's updated "
            "docstring for the full explanation)."
        ),
        "original_judging_run_id": ORIGINAL_JUDGING_RUN_ID,
        "original_judging_run_untouched": True,
        "source_capture_run_id": "qac_capture_20261110T063448Z_f2dfa9d3",
        "source_capture_file_sha256": capture_file_sha256,
        "dataset_version": original_summary["dataset_version"],
        "dataset_json_sha256": original_summary["dataset_json_sha256"],
        "corpus": corpus_identity,
        "validity_rule": (
            "valid: the displayed citation id's exact document_id::chunk_index "
            "compound key exists in the locked 691-chunk extract "
            "(qa_citation_dataset.load_locked_extract_index). "
            "unresolved: the id is malformed, or well-formed but does not "
            "exist in the locked extract (covers nonexistent document, "
            "nonexistent chunk index, and malformed strings uniformly, via "
            "a plain dict lookup)."
        ),
        "cases_recomputed": cases_recomputed,
        "citation_observations_recomputed": citation_ids_recomputed,
        "original_citation_validity": original_citation_validity,
        "corrected_citation_validity": {
            "numerator": corrected_numerator_sum,
            "denominator": corrected_denominator_sum,
            "value": corrected_value,
        },
        "denominator_unchanged_from_original": denominator_matches_original,
        "other_four_metrics_verified_unchanged": len(other_metrics_mismatches) == 0,
        "other_four_metrics_mismatches": other_metrics_mismatches,
        "implementation_fix_location": "app/services/evaluation/qa_citation_claim_judging.py::resolve_citation_validity",
        "regression_tests_file": "backend/tests/test_qa_citation_claim_judging.py",
    }

    (run_dir / "citation_validity_correction.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8"
    )
    (run_dir / "per_case_corrections.jsonl").write_text(
        "".join(json.dumps(e, ensure_ascii=False, default=str) + "\n" for e in per_case_corrections),
        encoding="utf-8",
    )

    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
