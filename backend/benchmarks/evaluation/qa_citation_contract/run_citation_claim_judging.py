"""Stage 3.5: full citation-claim judging run over the Stage 3.4 capture.

Judges ONLY citation-claim behavior (Phase 5 Part A,
qa_citation_claim_judging.py) over the 32 answerable records from the
accepted Stage 3.4 full citation capture (qac_capture_20261110T063448Z_
f2dfa9d3). Does NOT re-run QA or insufficient-evidence judging -- the
accepted QA reference run (qacj_judging_20261110T060752Z_e9d55993) stays
exactly as-is and is not touched or redone.

Reuses the exact same dual-judge pair already qualified for QA judging
(dots-studio/dots-3-note-preview:free / nvidia/nemotron-3-ultra-550b-a55b
:free) and the exact same envelope-capturing response_fn builder already
built and proven in run_qa_citation_judging_qa_ie_only.py (imported, not
duplicated). No change to any Phase 1-5 module, no change to the citation
prompt/rubric/parsing logic, no change to the capture.

Routing/eligibility is handled entirely by the existing, unmodified
judge_citation_claims_cases()/classify_eligibility() -- this driver does
not special-case qac_008, qac_020, or qac_025 in any way; their outcomes
are observed and reported, not manufactured.

Known, unavoidable limitation (explicitly documented in the run's own
output, not silently omitted): the production citation_verification.py
module does not capture resolved provider/model, response id, or call
timestamp for the ORIGINAL citation-verification calls made during Stage
3.4 capture. This driver's OWN judge calls (for citation-CLAIM judging,
a separate step from citation VERIFICATION) do capture a full envelope,
same as the QA judging runs -- that traceability gap is specific to the
production verifier module from Stage 3.4, not to this judging run.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.services.evaluation.qa_citation_capture import DEFAULT_RUNS_DIR  # noqa: E402
from app.services.evaluation.qa_citation_claim_judging import (  # noqa: E402
    CitationClaimJudgeAdapter,
    build_citation_claim_judge_pair,
    judge_citation_claims_cases,
)
from app.services.evaluation.qa_citation_dataset import load_qa_citation_dataset  # noqa: E402
from app.services.evaluation.qa_citation_eligibility import (  # noqa: E402
    load_captures_jsonl,
    summarize_eligibility,
)
from app.services.evaluation.qa_citation_run_report import (  # noqa: E402
    QaCitationRunReportError,
    _build_citation_aggregation,
    _build_judgment_row,
    _case_lookup,
    _partition_records_by_case_type,
)

from run_qa_citation_judging_qa_ie_only import (  # noqa: E402
    PRIMARY_MODEL,
    PRIMARY_PROVIDER,
    SECONDARY_MODEL,
    SECONDARY_PROVIDER,
    _make_response_fn,
)

CAPTURE_RUN_DIR = (
    BACKEND_ROOT / "benchmarks" / "evaluation" / "qa_citation_runs" / "qac_capture_20261110T063448Z_f2dfa9d3"
)
DATASET_PATH = BACKEND_ROOT / "benchmarks" / "evaluation" / "qa_citation_eval_dataset.json"
EXPECTED_DATASET_SHA256 = "81f66f25d007f373512936880edca530c4f2137377ee5601fbb155fe81455972"

ACCEPTED_QA_REFERENCE_RUN_ID = "qacj_judging_20261110T060752Z_e9d55993"

CITATION_VERIFIER_METADATA_LIMITATION_NOTE = (
    "The Stage 3.4 production citation_verification.py module (unmodified) "
    "did not record resolved model/provider identity, a response id, or a "
    "call timestamp for the original citation-VERIFICATION calls that "
    "produced this capture's displayed_citation_ids -- only usage/content "
    "were captured. This is distinct from citation-CLAIM JUDGING (this "
    "run), whose own judge calls DO have full envelope traceability "
    "(raw_response_envelopes.jsonl), since those calls were made directly "
    "by this evaluation driver, not through the production verifier "
    "module."
)


class TracingCitationClaimJudgeAdapter(CitationClaimJudgeAdapter):
    """Driver-local subclass, identical pattern to
    run_qa_citation_judging_qa_ie_only.TracingJudgeAdapter: tags the
    envelope-capturing response_fn with the current case_id before
    delegating to the unmodified CitationClaimJudgeAdapter.__call__."""

    def __init__(self, *, context: dict, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._context = context

    def __call__(self, record: Mapping[str, Any]) -> Mapping[str, Any]:
        self._context["case_id"] = str(record.get("case_id") or "")
        return super().__call__(record)


def main() -> int:
    dataset_bytes = DATASET_PATH.read_bytes()
    actual_hash = hashlib.sha256(dataset_bytes).hexdigest()
    if actual_hash != EXPECTED_DATASET_SHA256:
        print(f"DATASET HASH MISMATCH: expected {EXPECTED_DATASET_SHA256}, got {actual_hash}", file=sys.stderr)
        return 2

    captures_path = CAPTURE_RUN_DIR / "captures.jsonl"
    summary_path = CAPTURE_RUN_DIR / "summary.json"
    if not captures_path.is_file() or not summary_path.is_file():
        print(f"STAGE 3.4 CAPTURE NOT FOUND: {CAPTURE_RUN_DIR}", file=sys.stderr)
        return 2

    capture_summary = json.loads(summary_path.read_text(encoding="utf-8"))
    capture_run_id = str(capture_summary.get("run_id") or "")
    if capture_run_id != "qac_capture_20261110T063448Z_f2dfa9d3":
        print(f"UNEXPECTED CAPTURE RUN ID: {capture_run_id}", file=sys.stderr)
        return 2

    dataset = load_qa_citation_dataset(DATASET_PATH)
    capture_records = load_captures_jsonl(captures_path)
    capture_file_sha256 = hashlib.sha256(captures_path.read_bytes()).hexdigest()

    answerable_records, insufficient_evidence_records = _partition_records_by_case_type(
        capture_records, dataset
    )
    print(
        f"{len(answerable_records)} answerable record(s) routed to citation-claim judging; "
        f"{len(insufficient_evidence_records)} insufficient-evidence record(s) NOT routed here "
        "(citation claims are not judged for that population).",
        file=sys.stderr,
    )

    envelope_sink: list[dict[str, Any]] = []
    primary_ctx: dict = {}
    secondary_ctx: dict = {}
    primary = TracingCitationClaimJudgeAdapter(
        context=primary_ctx,
        model=PRIMARY_MODEL,
        provider=PRIMARY_PROVIDER,
        dataset=dataset,
        response_fn=_make_response_fn(
            model=PRIMARY_MODEL, provider=PRIMARY_PROVIDER, slot_name="citation_primary",
            envelope_sink=envelope_sink, context=primary_ctx,
        ),
        slot_name="citation_primary",
    )
    secondary = TracingCitationClaimJudgeAdapter(
        context=secondary_ctx,
        model=SECONDARY_MODEL,
        provider=SECONDARY_PROVIDER,
        dataset=dataset,
        response_fn=_make_response_fn(
            model=SECONDARY_MODEL, provider=SECONDARY_PROVIDER, slot_name="citation_secondary",
            envelope_sink=envelope_sink, context=secondary_ctx,
        ),
        slot_name="citation_secondary",
    )
    primary, secondary = build_citation_claim_judge_pair(primary=primary, secondary=secondary)

    print(f"Judging {len(answerable_records)} case(s) for citation claims...", file=sys.stderr)
    citation_outcomes = judge_citation_claims_cases(
        answerable_records, primary_judge=primary, secondary_judge=secondary
    )

    if len(citation_outcomes) != len(answerable_records):
        raise QaCitationRunReportError(
            f"Citation-claim judging dropped or duplicated cases: "
            f"answerable_records={len(answerable_records)}, citation_outcomes={len(citation_outcomes)}."
        )

    cases_by_id = _case_lookup(dataset)
    eligibility = summarize_eligibility(answerable_records)
    citation_aggregation = _build_citation_aggregation(citation_outcomes, eligibility=eligibility)

    outcomes_by_id = {o.case_id: o for o in citation_outcomes}
    judgment_rows = tuple(
        _build_judgment_row(
            case_id=cid, case_type=cases_by_id[cid].case_type,
            qa_outcome=None, citation_outcome=outcomes_by_id.get(cid), ie_outcome=None,
        )
        for cid in (r["case_id"] for r in answerable_records)
    )

    special_cases = {}
    for cid in ("qac_008_latin_cum_laude", "qac_020_transferee_documents", "qac_025_four_point_zero_and_inc"):
        outcome = outcomes_by_id.get(cid)
        if outcome is not None:
            special_cases[cid] = {
                "final_status": outcome.final_status,
                "eligibility": outcome.eligibility_verdict.as_dict(),
                "primary_claims_found": (
                    len(outcome.primary_judge.parsed.claims)
                    if outcome.primary_judge and outcome.primary_judge.parsed
                    else None
                ),
                "secondary_claims_found": (
                    len(outcome.secondary_judge.parsed.claims)
                    if outcome.secondary_judge and outcome.secondary_judge.parsed
                    else None
                ),
            }
        else:
            # Not in answerable_records at all (e.g. qac_025 may have been
            # routed here as answerable but excluded, or may not appear if
            # case_type differs) -- report explicitly, never silently.
            cap_record = next((r for r in capture_records if r.get("case_id") == cid), None)
            special_cases[cid] = {
                "final_status": "not_routed_to_citation_judging",
                "case_type": cases_by_id[cid].case_type if cid in cases_by_id else None,
                "is_genuine_model_output": cap_record.get("is_genuine_model_output") if cap_record else None,
                "fallback_reason": cap_record.get("fallback_reason") if cap_record else None,
            }

    judged_dt = datetime.now(timezone.utc)
    run_id = f"qacj_citation_judging_{judged_dt.strftime('%Y%m%dT%H%M%SZ')}"
    run_dir = DEFAULT_RUNS_DIR / run_id
    if run_dir.exists():
        print(f"JUDGING RUN DIRECTORY ALREADY EXISTS: {run_dir}", file=sys.stderr)
        return 2
    run_dir.mkdir(parents=True, exist_ok=False)

    summary = {
        "judging_run_id": run_id,
        "judged_at": judged_dt.isoformat(),
        "capture_run_id": capture_run_id,
        "capture_file_sha256": capture_file_sha256,
        "dataset_version": dataset.dataset_version,
        "dataset_json_sha256": dataset.dataset_json_sha256,
        "accepted_qa_reference_run_id_not_modified": ACCEPTED_QA_REFERENCE_RUN_ID,
        "judges": {
            "citation_claim_rubric": {
                "primary_model": primary.identity.model,
                "primary_provider": primary.identity.provider,
                "secondary_model": secondary.identity.model,
                "secondary_provider": secondary.identity.provider,
                "prompt_version": primary.prompt_version,
                "prompt_sha256": primary.prompt_sha256,
            }
        },
        "scope_note": (
            "This run judges ONLY citation-claim behavior. QA and "
            "insufficient-evidence judging were NOT re-run; the accepted "
            "QA reference run above is untouched."
        ),
        "answerable_total": len(answerable_records),
        "citation_aggregation": citation_aggregation,
        "special_case_outcomes": special_cases,
        "citation_verifier_metadata_limitation": CITATION_VERIFIER_METADATA_LIMITATION_NOTE,
        "coverage_vs_correctness_note": (
            "Stage 3.4's '34/36 cases produced a displayed citation' is "
            "CAPTURE COVERAGE -- whether any citation was shown at all. "
            "This run's citation_aggregation (precision/completeness/claim_"
            "support_rate/unsupported_claim_rate/citation_validity) is "
            "CLAIM-LEVEL JUDGING -- whether what was shown (or not shown) "
            "was actually correct. The two are not the same measurement "
            "and are reported separately here, not conflated."
        ),
    }

    (run_dir / "judgments.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False, default=str) + "\n" for row in judgment_rows),
        encoding="utf-8",
    )
    (run_dir / "judging_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8"
    )
    (run_dir / "raw_response_envelopes.jsonl").write_text(
        "".join(json.dumps(e, ensure_ascii=False, default=str) + "\n" for e in envelope_sink),
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "judging_run_id": run_id,
                "output_dir": str(run_dir),
                "answerable_total": len(answerable_records),
                "citation_aggregation": citation_aggregation,
                "envelope_count": len(envelope_sink),
            },
            indent=2,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
