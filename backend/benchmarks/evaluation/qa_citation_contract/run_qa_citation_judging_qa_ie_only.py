"""Stage 3.2B live judging CLI: QA rubric + insufficient-evidence rubric ONLY.

Citation-claim judging is deliberately never invoked by this script. The
configured citation_verifier_model ("nvidia/nemotron-3-super-120b-a12b:free")
returned HTTP 404 from OpenRouter during the 2026-11-10 capture run -- a
separate, pre-existing configuration problem unrelated to this script. Per
explicit authorization, this run must not call the citation-claim judge at
all; the output records citation evaluation as "pending" with that reason,
rather than running judge_citation_claims_cases() (which would report
judging_failed_total for every case and misrepresent a deliberate skip as a
judging failure).

Judge models (v3, this run): both are EXPLICIT, FIXED model IDs, never a
dynamic routing alias. Per Stage 3.2C's n=8 qualification test
(qacq_qualification_20261110T050229Z), the primary was replaced again:
  - primary:   dots-studio/dots-3-note-preview:free (provider: AtlasCloud)
  - secondary: nvidia/nemotron-3-ultra-550b-a55b:free (provider: Nvidia)
Distinct models, distinct providers. The secondary is unchanged from the
prior fixed-model run. The new primary replaces cohere/north-mini-code:free,
which had a 10/35 malformed-JSON rate as primary in the prior run
(qacj_judging_20261110T043108Z_04139416); in qualification testing,
dots-studio/dots-3-note-preview:free achieved 8/8 valid schema compliance
against the same existing prompts, including succeeding on the one
insufficient-evidence case where the Nvidia secondary itself failed.

Full raw response envelope: each judge call's complete OpenRouter response
envelope (resolved model/provider if returned, response id, created
timestamp, finish_reason, usage/token metadata) is captured via a small,
driver-local subclass of JudgeAdapter/InsufficientEvidenceJudgeAdapter
(TracingJudgeAdapter/TracingInsufficientEvidenceJudgeAdapter below) that
tags each call with its case_id before delegating to the real adapter's
unmodified __call__. No change to qa_citation_judge_prompt.py or
qa_citation_insufficient_evidence.py. Envelopes are written to a separate
sibling JSONL artifact (raw_response_envelopes.jsonl), never mixed into
judgments.jsonl's existing, audited schema. Credentials/authorization
headers are never included in any captured envelope.

This script does not modify any Phase 1-5 module. It reuses
judge_eligible_cases/judge_insufficient_evidence_cases (Phase 2/4),
JudgeAdapter/InsufficientEvidenceJudgeAdapter/build_judge_pair (Phase 3/4),
and the QA/insufficient-evidence aggregation helpers already built and
independently audited in qa_citation_run_report.py (Phase 5) -- it only
skips that module's top-level run_qa_citation_judging(), which mandatorily
calls the citation-claim judge with no opt-out.

Writes a new, uniquely-identified run directory under the same
qa_citation_runs/ root Stage 3.1 capture runs use (distinguished by the
qacj_judging_ run_id prefix vs. capture's qac_capture_ prefix). Never
overwrites an existing run directory. Never modifies any existing capture
run or prior judging run -- read-only access only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import httpx  # noqa: E402

from app.config import settings  # noqa: E402
from app.services.evaluation.qa_citation_capture import DEFAULT_RUNS_DIR  # noqa: E402
from app.services.evaluation.qa_citation_dataset import load_qa_citation_dataset  # noqa: E402
from app.services.evaluation.qa_citation_eligibility import (  # noqa: E402
    load_captures_jsonl,
    summarize_eligibility,
)
from app.services.evaluation.qa_citation_insufficient_evidence import (  # noqa: E402
    InsufficientEvidenceJudgeAdapter,
    build_insufficient_evidence_judge_pair,
    judge_insufficient_evidence_cases,
    summarize_insufficient_evidence_outcomes,
)
from app.services.evaluation.qa_citation_judge_prompt import (  # noqa: E402
    JudgeAdapter,
    build_judge_pair,
)
from app.services.evaluation.qa_citation_judging import (  # noqa: E402
    JudgeCallError,
    JudgeTimeoutError,
    judge_eligible_cases,
)
from app.services.evaluation.qa_citation_run_report import (  # noqa: E402
    QaCitationRunReportError,
    _build_judgment_row,
    _build_qa_aggregation,
    _case_lookup,
    _partition_records_by_case_type,
    new_judging_run_id,
)

JUDGING_REPORT_VERSION_QA_IE_ONLY = "stage_3_2d_qa_ie_only_v3_qualified_models"

PRIMARY_MODEL = "dots-studio/dots-3-note-preview:free"
PRIMARY_PROVIDER = "atlascloud"
SECONDARY_MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"
SECONDARY_PROVIDER = "nvidia"

CITATION_PENDING_REASON = (
    "Citation-claim judging was not invoked this run. The configured "
    "citation_verifier_model ('nvidia/nemotron-3-super-120b-a12b:free') "
    "returned HTTP 404 Not Found from OpenRouter during the 2026-11-10 "
    "capture run (verifier_invoked=true, verifier_succeeded=false for all "
    "36 cases) -- a separate, pre-existing configuration issue. Citation "
    "evaluation is recorded as pending rather than attempted or inferred."
)


def _make_response_fn(*, model: str, provider: str, slot_name: str, envelope_sink: list, context: dict):
    """Returns a ResponseFn that also appends a full, credential-free raw
    response envelope to ``envelope_sink`` for every call, tagged with the
    case_id currently held in ``context`` (set by the TracingJudgeAdapter
    subclasses below immediately before delegating to JudgeAdapter.__call__,
    since ResponseFn's own signature -- str -> str|Mapping -- doesn't carry
    case_id)."""
    key = settings.groq_api_key or ""

    def response_fn(prompt: str) -> str:
        case_id = context.get("case_id", "")
        started_at = datetime.now(timezone.utc).isoformat()
        try:
            with httpx.Client(timeout=180.0) as client:
                resp = client.post(
                    settings.llm_base_url,
                    headers={
                        "Authorization": f"Bearer {key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model,
                        "temperature": 0,
                        "max_tokens": 10000,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                )
        except httpx.TimeoutException as exc:
            envelope_sink.append(
                {
                    "case_id": case_id,
                    "slot": slot_name,
                    "configured_model": model,
                    "configured_provider": provider,
                    "called_at": started_at,
                    "error_category": "timeout",
                    "error_detail": str(exc),
                }
            )
            raise JudgeTimeoutError(f"timeout calling {model}: {exc}") from exc
        except httpx.HTTPError as exc:
            envelope_sink.append(
                {
                    "case_id": case_id,
                    "slot": slot_name,
                    "configured_model": model,
                    "configured_provider": provider,
                    "called_at": started_at,
                    "error_category": "request_error",
                    "error_detail": str(exc),
                }
            )
            raise JudgeCallError(f"request_error calling {model}: {exc}") from exc

        if resp.status_code in (401, 403):
            envelope_sink.append(
                {
                    "case_id": case_id,
                    "slot": slot_name,
                    "configured_model": model,
                    "configured_provider": provider,
                    "called_at": started_at,
                    "http_status": resp.status_code,
                    "error_category": "auth_error",
                }
            )
            raise JudgeCallError(f"auth_error calling {model}: HTTP {resp.status_code}")
        if resp.status_code == 429:
            envelope_sink.append(
                {
                    "case_id": case_id,
                    "slot": slot_name,
                    "configured_model": model,
                    "configured_provider": provider,
                    "called_at": started_at,
                    "http_status": resp.status_code,
                    "error_category": "rate_limited",
                }
            )
            raise JudgeCallError(f"rate_limited calling {model}: HTTP {resp.status_code}")
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            envelope_sink.append(
                {
                    "case_id": case_id,
                    "slot": slot_name,
                    "configured_model": model,
                    "configured_provider": provider,
                    "called_at": started_at,
                    "http_status": resp.status_code,
                    "error_category": "provider_error",
                    "error_detail": str(exc),
                }
            )
            raise JudgeCallError(f"provider_error calling {model}: {exc}") from exc

        body: dict[str, Any] = {}
        content: str | None = None
        finish_reason = None
        try:
            body = resp.json()
            choice = body.get("choices", [{}])[0]
            content = choice.get("message", {}).get("content")
            finish_reason = choice.get("finish_reason")
        except (KeyError, IndexError, ValueError, TypeError) as exc:
            envelope_sink.append(
                {
                    "case_id": case_id,
                    "slot": slot_name,
                    "configured_model": model,
                    "configured_provider": provider,
                    "called_at": started_at,
                    "http_status": resp.status_code,
                    "error_category": "malformed_envelope",
                    "error_detail": str(exc),
                }
            )
            raise JudgeCallError(f"malformed_response calling {model}: {exc}") from exc

        # Full envelope, recorded regardless of whether content ended up usable.
        envelope_sink.append(
            {
                "case_id": case_id,
                "slot": slot_name,
                "configured_model": model,
                "configured_provider": provider,
                "called_at": started_at,
                "http_status": resp.status_code,
                "response_id": body.get("id"),
                "resolved_model": body.get("model"),
                "resolved_provider": body.get("provider"),
                "created": body.get("created"),
                "finish_reason": finish_reason,
                "usage": body.get("usage"),
                "parsed_content": content,
                "error_category": None if content and str(content).strip() else "empty_content",
            }
        )

        if not content or not str(content).strip():
            raise JudgeCallError(
                f"empty_response_content calling {model} (finish_reason={finish_reason!r})"
            )
        return content

    return response_fn


class TracingJudgeAdapter(JudgeAdapter):
    """Driver-local subclass: tags the envelope-capturing response_fn with
    the current case_id before delegating to JudgeAdapter's unmodified
    __call__. No change to qa_citation_judge_prompt.py."""

    def __init__(self, *, context: dict, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._context = context

    def __call__(self, record: Mapping[str, Any]) -> Mapping[str, Any]:
        self._context["case_id"] = str(record.get("case_id") or "")
        return super().__call__(record)


class TracingInsufficientEvidenceJudgeAdapter(InsufficientEvidenceJudgeAdapter):
    def __init__(self, *, context: dict, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._context = context

    def __call__(self, record: Mapping[str, Any]) -> Mapping[str, Any]:
        self._context["case_id"] = str(record.get("case_id") or "")
        return super().__call__(record)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-run-dir", type=Path, required=True)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=BACKEND_ROOT / "benchmarks" / "evaluation" / "qa_citation_eval_dataset.json",
    )
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args(argv)

    captures_path = args.capture_run_dir / "captures.jsonl"
    capture_summary_path = args.capture_run_dir / "summary.json"
    if not captures_path.is_file() or not capture_summary_path.is_file():
        print(f"CAPTURE RUN NOT FOUND: {args.capture_run_dir}", file=sys.stderr)
        return 2

    dataset = load_qa_citation_dataset(args.dataset)
    capture_records = load_captures_jsonl(captures_path)
    capture_file_sha256 = hashlib.sha256(captures_path.read_bytes()).hexdigest()
    capture_summary = json.loads(capture_summary_path.read_text(encoding="utf-8"))
    capture_run_id = str(capture_summary.get("run_id") or "")
    if not capture_run_id:
        print(f"CAPTURE SUMMARY MISSING run_id: {capture_summary_path}", file=sys.stderr)
        return 2

    answerable_records, insufficient_evidence_records = _partition_records_by_case_type(
        capture_records, dataset
    )

    envelope_sink: list[dict[str, Any]] = []

    qa_primary_context: dict = {}
    qa_secondary_context: dict = {}
    qa_primary = TracingJudgeAdapter(
        context=qa_primary_context,
        model=PRIMARY_MODEL,
        provider=PRIMARY_PROVIDER,
        dataset=dataset,
        response_fn=_make_response_fn(
            model=PRIMARY_MODEL,
            provider=PRIMARY_PROVIDER,
            slot_name="qa_primary",
            envelope_sink=envelope_sink,
            context=qa_primary_context,
        ),
        slot_name="qa_primary",
    )
    qa_secondary = TracingJudgeAdapter(
        context=qa_secondary_context,
        model=SECONDARY_MODEL,
        provider=SECONDARY_PROVIDER,
        dataset=dataset,
        response_fn=_make_response_fn(
            model=SECONDARY_MODEL,
            provider=SECONDARY_PROVIDER,
            slot_name="qa_secondary",
            envelope_sink=envelope_sink,
            context=qa_secondary_context,
        ),
        slot_name="qa_secondary",
    )
    qa_primary, qa_secondary = build_judge_pair(primary=qa_primary, secondary=qa_secondary)

    ie_primary_context: dict = {}
    ie_secondary_context: dict = {}
    ie_primary = TracingInsufficientEvidenceJudgeAdapter(
        context=ie_primary_context,
        model=PRIMARY_MODEL,
        provider=PRIMARY_PROVIDER,
        dataset=dataset,
        response_fn=_make_response_fn(
            model=PRIMARY_MODEL,
            provider=PRIMARY_PROVIDER,
            slot_name="ie_primary",
            envelope_sink=envelope_sink,
            context=ie_primary_context,
        ),
        slot_name="ie_primary",
    )
    ie_secondary = TracingInsufficientEvidenceJudgeAdapter(
        context=ie_secondary_context,
        model=SECONDARY_MODEL,
        provider=SECONDARY_PROVIDER,
        dataset=dataset,
        response_fn=_make_response_fn(
            model=SECONDARY_MODEL,
            provider=SECONDARY_PROVIDER,
            slot_name="ie_secondary",
            envelope_sink=envelope_sink,
            context=ie_secondary_context,
        ),
        slot_name="ie_secondary",
    )
    ie_primary, ie_secondary = build_insufficient_evidence_judge_pair(
        primary=ie_primary, secondary=ie_secondary
    )

    print(f"Judging {len(answerable_records)} answerable case(s) under the QA rubric...", file=sys.stderr)
    qa_outcomes = judge_eligible_cases(
        answerable_records, primary_judge=qa_primary, secondary_judge=qa_secondary
    )
    print(
        f"Judging {len(insufficient_evidence_records)} insufficient-evidence case(s)...",
        file=sys.stderr,
    )
    ie_outcomes = judge_insufficient_evidence_cases(
        insufficient_evidence_records, primary_judge=ie_primary, secondary_judge=ie_secondary
    )

    total_routed = len(qa_outcomes) + len(ie_outcomes)
    if total_routed != len(capture_records):
        raise QaCitationRunReportError(
            "Judging dropped or duplicated cases: "
            f"capture_records={len(capture_records)}, qa_outcomes={len(qa_outcomes)}, "
            f"ie_outcomes={len(ie_outcomes)}."
        )

    cases_by_id = _case_lookup(dataset)
    category_by_case_id = {case_id: case.category for case_id, case in cases_by_id.items()}

    qa_eligibility = summarize_eligibility(answerable_records)
    ie_eligibility = summarize_eligibility(insufficient_evidence_records)

    qa_aggregation = _build_qa_aggregation(
        qa_outcomes, eligibility=qa_eligibility, category_by_case_id=category_by_case_id
    )
    ie_aggregation = summarize_insufficient_evidence_outcomes(ie_outcomes)

    fallback_counts = {"genuine": 0, "fallback": 0, "no_result": 0, "fields_missing": 0}
    for record in capture_records:
        if "is_genuine_model_output" not in record or "fallback_used" not in record:
            fallback_counts["fields_missing"] += 1
        elif record["is_genuine_model_output"] is None:
            fallback_counts["no_result"] += 1
        elif record["is_genuine_model_output"] is True:
            fallback_counts["genuine"] += 1
        else:
            fallback_counts["fallback"] += 1

    population_summary = {
        "answerable_total": len(answerable_records),
        "answerable_qa_judged": qa_aggregation["judged_count"],
        "answerable_qa_judging_failed_partial": qa_aggregation["judging_failed_partial_count"],
        "answerable_qa_judging_failed_total": qa_aggregation["judging_failed_total_count"],
        "answerable_excluded": qa_eligibility.excluded_count,
        "answerable_citation_judging": "not_invoked_this_run",
        "insufficient_evidence_total": len(insufficient_evidence_records),
        "insufficient_evidence_judged": ie_aggregation.judged_count,
        "insufficient_evidence_judging_failed_partial": (
            ie_aggregation.judging_failed_partial_count
        ),
        "insufficient_evidence_judging_failed_total": ie_aggregation.judging_failed_total_count,
        "insufficient_evidence_excluded": ie_aggregation.excluded_count,
        "ineligible_excluded_by_reason": {
            **qa_eligibility.exclusion_counts_by_reason,
            **ie_eligibility.exclusion_counts_by_reason,
        },
        "fallback_vs_genuine_counts": fallback_counts,
    }

    qa_outcomes_by_id = {o.case_id: o for o in qa_outcomes}
    ie_outcomes_by_id = {o.case_id: o for o in ie_outcomes}
    judgment_rows = tuple(
        _build_judgment_row(
            case_id=record_case_id,
            case_type=cases_by_id[record_case_id].case_type,
            qa_outcome=qa_outcomes_by_id.get(record_case_id),
            citation_outcome=None,
            ie_outcome=ie_outcomes_by_id.get(record_case_id),
        )
        for record_case_id in (str(r.get("case_id") or "") for r in capture_records)
    )

    corpus_dicts = [dict(r.get("corpus") or {}) for r in capture_records]
    corpus = corpus_dicts[0] if corpus_dicts else {}
    if any(c != corpus for c in corpus_dicts):
        raise QaCitationRunReportError(
            "Capture records in this run disagree on corpus identity; "
            "a judging run must be built from one capture run's records."
        )

    judged_dt = datetime.now(timezone.utc)
    resolved_run_id = new_judging_run_id(judged_at=judged_dt)
    runs_root = args.output_dir if args.output_dir is not None else DEFAULT_RUNS_DIR
    run_dir = runs_root / resolved_run_id
    if run_dir.exists():
        print(f"JUDGING RUN DIRECTORY ALREADY EXISTS: {run_dir}", file=sys.stderr)
        return 2

    summary: dict[str, Any] = {
        "judging_run_id": resolved_run_id,
        "report_version": JUDGING_REPORT_VERSION_QA_IE_ONLY,
        "judged_at": judged_dt.isoformat(),
        "capture_run_id": capture_run_id,
        "capture_file_sha256": capture_file_sha256,
        "dataset_version": dataset.dataset_version,
        "dataset_json_sha256": dataset.dataset_json_sha256,
        "corpus": corpus,
        "judges": {
            "qa_rubric": {
                "primary_model": qa_primary.identity.model,
                "primary_provider": qa_primary.identity.provider,
                "secondary_model": qa_secondary.identity.model,
                "secondary_provider": qa_secondary.identity.provider,
                "prompt_version": qa_primary.prompt_version,
                "prompt_sha256": qa_primary.prompt_sha256,
            },
            "insufficient_evidence_rubric": {
                "primary_model": ie_primary.identity.model,
                "primary_provider": ie_primary.identity.provider,
                "secondary_model": ie_secondary.identity.model,
                "secondary_provider": ie_secondary.identity.provider,
                "prompt_version": ie_primary.prompt_version,
                "prompt_sha256": ie_primary.prompt_sha256,
            },
            "citation_claim_rubric": {
                "status": "pending",
                "reason": CITATION_PENDING_REASON,
            },
        },
        "population_summary": population_summary,
        "qa_aggregation": qa_aggregation,
        "citation_aggregation": {"status": "pending", "reason": CITATION_PENDING_REASON},
        "insufficient_evidence_aggregation": ie_aggregation.as_dict(),
        "note_on_empty_citations": (
            "Citation evaluation was not performed this run (see "
            "judges.citation_claim_rubric). Missing/empty displayed citations "
            "in the underlying capture must NOT be interpreted as evidence "
            "that any answer is unsupported -- that determination requires "
            "citation-claim judging, which did not run."
        ),
        "raw_response_envelope_file": "raw_response_envelopes.jsonl",
        "raw_response_envelope_note": (
            "One row per judge call (including failed calls), credential-"
            "free. Each row includes case_id, slot, configured_model/"
            "provider, and -- when the HTTP call succeeded -- the response "
            "id, resolved model/provider fields (if OpenRouter returned "
            "them), created timestamp, finish_reason, usage/token metadata, "
            "and parsed content. OpenRouter's response envelope for these "
            "calls did not include a distinct 'resolved backend' identity "
            "field beyond echoing the requested model string; resolved_"
            "model/resolved_provider are recorded as returned (possibly "
            "null) rather than fabricated."
        ),
    }

    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "judgments.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False, default=str) + "\n" for row in judgment_rows),
        encoding="utf-8",
    )
    (run_dir / "judging_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    (run_dir / "raw_response_envelopes.jsonl").write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, default=str) + "\n" for row in envelope_sink
        ),
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "judging_run_id": resolved_run_id,
                "output_dir": str(run_dir),
                "population_summary": population_summary,
                "envelope_count": len(envelope_sink),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
