"""Stage 3.2C: small, paired qualification test for a third candidate judge
model against the existing reference Nvidia judge.

NOT a full QA/citation evaluation run. Uses 8 hand-selected cases from the
existing capture run qac_capture_20261110T014318Z_80d7ddd1 (read-only;
never recaptures or modifies anything) and calls each of the candidate and
Nvidia once per case, using the exact same existing, unmodified prompts and
rubrics (qa_citation_judge_prompt.py for the 7 answerable cases,
qa_citation_insufficient_evidence.py for the 1 insufficient-evidence case).

Case selection (8 total, documented rationale):
  - qac_008_latin_cum_laude, qac_009_counseling_office,
    qac_019_free_higher_education, qac_020_transferee_documents: the four
    cases explicitly named in the authorization as having previously
    exposed judge weaknesses (large score gaps / vaguer-vs-specific
    evidence grounding between judges in prior runs).
  - qac_001_tor_undergrad_fee, qac_013_shifting_conditions,
    qac_030_library_reference_who: three further answerable cases from
    different categories, with different prior agreement patterns (clean
    full-agreement, no-disagreement, and a mild 1-point disagreement
    respectively), for category/characteristic diversity.
  - qac_033_wifi_password: the one insufficient-evidence case with full
    judge agreement in the first live run, used here for the IE rubric
    pairing.
None is the excluded fallback case (qac_025).

No modification to any Phase 1-5 module, the dataset, the capture run, or
any historical judging run. Writes a new, separate qualification-run
directory only. Max 16 real judge calls (8 cases x 2 judges), no retries.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import httpx  # noqa: E402

from app.config import settings  # noqa: E402
from app.services.evaluation.qa_citation_capture import DEFAULT_RUNS_DIR  # noqa: E402
from app.services.evaluation.qa_citation_dataset import load_qa_citation_dataset  # noqa: E402
from app.services.evaluation.qa_citation_eligibility import load_captures_jsonl  # noqa: E402
from app.services.evaluation.qa_citation_insufficient_evidence import (  # noqa: E402
    build_insufficient_evidence_judge_call_payload,
    build_insufficient_evidence_prompt,
    insufficient_evidence_prompt_sha256,
)
from app.services.evaluation.qa_citation_judge_prompt import (  # noqa: E402
    build_judge_call_payload,
    build_judge_prompt,
    judge_prompt_sha256,
)

CANDIDATE_MODEL = "dots-studio/dots-3-note-preview:free"
CANDIDATE_PROVIDER = "atlascloud"  # configured label; resolved_provider captured from the API separately
REFERENCE_MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"
REFERENCE_PROVIDER = "nvidia"

ANSWERABLE_CASE_IDS = [
    "qac_008_latin_cum_laude",
    "qac_009_counseling_office",
    "qac_019_free_higher_education",
    "qac_020_transferee_documents",
    "qac_001_tor_undergrad_fee",
    "qac_013_shifting_conditions",
    "qac_030_library_reference_who",
]
INSUFFICIENT_EVIDENCE_CASE_ID = "qac_033_wifi_password"

CAPTURE_RUN_DIR = (
    BACKEND_ROOT / "benchmarks" / "evaluation" / "qa_citation_runs" / "qac_capture_20261110T014318Z_80d7ddd1"
)
DATASET_PATH = BACKEND_ROOT / "benchmarks" / "evaluation" / "qa_citation_eval_dataset.json"


def _call_model(*, model: str, configured_provider: str, prompt: str, case_id: str, slot: str, envelope_sink: list) -> tuple[str | None, dict[str, Any]]:
    key = settings.groq_api_key or ""
    called_at = datetime.now(timezone.utc).isoformat()
    envelope: dict[str, Any] = {
        "case_id": case_id,
        "slot": slot,
        "configured_model": model,
        "configured_provider": configured_provider,
        "called_at": called_at,
    }
    try:
        with httpx.Client(timeout=180.0) as client:
            resp = client.post(
                settings.llm_base_url,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "temperature": 0,
                    "max_tokens": 10000,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
    except httpx.TimeoutException as exc:
        envelope["error_category"] = "timeout"
        envelope["error_detail"] = str(exc)
        envelope_sink.append(envelope)
        return None, envelope
    except httpx.HTTPError as exc:
        envelope["error_category"] = "request_error"
        envelope["error_detail"] = str(exc)
        envelope_sink.append(envelope)
        return None, envelope

    envelope["http_status"] = resp.status_code
    if resp.status_code != 200:
        envelope["error_category"] = "http_error"
        envelope["error_detail"] = resp.text[:1000]
        envelope_sink.append(envelope)
        return None, envelope

    body: dict[str, Any] = {}
    content: str | None = None
    try:
        body = resp.json()
        choice = body.get("choices", [{}])[0]
        content = choice.get("message", {}).get("content")
        envelope["finish_reason"] = choice.get("finish_reason")
    except (KeyError, IndexError, ValueError, TypeError) as exc:
        envelope["error_category"] = "malformed_envelope"
        envelope["error_detail"] = str(exc)
        envelope_sink.append(envelope)
        return None, envelope

    envelope["response_id"] = body.get("id")
    envelope["resolved_model"] = body.get("model")
    envelope["resolved_provider"] = body.get("provider")
    envelope["created"] = body.get("created")
    envelope["usage"] = body.get("usage")
    envelope["parsed_content"] = content
    envelope["error_category"] = None if content and str(content).strip() else "empty_content"
    envelope_sink.append(envelope)
    return content, envelope


def main() -> int:
    dataset = load_qa_citation_dataset(DATASET_PATH)
    captures_path = CAPTURE_RUN_DIR / "captures.jsonl"
    capture_file_sha256 = hashlib.sha256(captures_path.read_bytes()).hexdigest()
    records = load_captures_jsonl(captures_path)
    records_by_id = {r.get("case_id"): r for r in records}
    cases_by_id = {c.case_id: c for c in dataset.cases}

    selected_case_ids = ANSWERABLE_CASE_IDS + [INSUFFICIENT_EVIDENCE_CASE_ID]
    for cid in selected_case_ids:
        if cid not in records_by_id or cid not in cases_by_id:
            print(f"SELECTED CASE NOT FOUND IN CAPTURE/DATASET: {cid}", file=sys.stderr)
            return 2
        rec = records_by_id[cid]
        if rec.get("is_genuine_model_output") is not True:
            print(f"SELECTED CASE IS NOT A GENUINE CAPTURED ANSWER: {cid}", file=sys.stderr)
            return 2

    envelope_sink: list[dict[str, Any]] = []
    qualification_rows: list[dict[str, Any]] = []

    for case_id in ANSWERABLE_CASE_IDS:
        case = cases_by_id[case_id]
        rec = records_by_id[case_id]
        prompt = build_judge_prompt(
            question=case.question,
            generated_answer=rec.get("generated_answer"),
            retrieved_context=rec.get("retrieved_context"),
            reference_answer=case.reference_answer,
        )
        print(f"QA pair for {case_id}...", file=sys.stderr)
        cand_content, _ = _call_model(
            model=CANDIDATE_MODEL, configured_provider=CANDIDATE_PROVIDER, prompt=prompt,
            case_id=case_id, slot="candidate", envelope_sink=envelope_sink,
        )
        ref_content, _ = _call_model(
            model=REFERENCE_MODEL, configured_provider=REFERENCE_PROVIDER, prompt=prompt,
            case_id=case_id, slot="reference", envelope_sink=envelope_sink,
        )
        cand_payload = (
            build_judge_call_payload(cand_content, slot="candidate")
            if cand_content
            else {"evaluation_status": "no_content"}
        )
        ref_payload = (
            build_judge_call_payload(ref_content, slot="reference")
            if ref_content
            else {"evaluation_status": "no_content"}
        )
        qualification_rows.append(
            {
                "case_id": case_id,
                "case_type": "labeled_student_support",
                "rubric": "qa",
                "candidate": cand_payload,
                "reference": ref_payload,
                "prompt_version": "qa_citation_judge_v1",
                "prompt_sha256": judge_prompt_sha256(),
            }
        )

    case = cases_by_id[INSUFFICIENT_EVIDENCE_CASE_ID]
    rec = records_by_id[INSUFFICIENT_EVIDENCE_CASE_ID]
    ie_prompt = build_insufficient_evidence_prompt(
        question=case.question,
        generated_answer=rec.get("generated_answer"),
        retrieved_context=rec.get("retrieved_context"),
        displayed_citation_ids=rec.get("displayed_citation_ids"),
    )
    print(f"IE pair for {INSUFFICIENT_EVIDENCE_CASE_ID}...", file=sys.stderr)
    cand_content, _ = _call_model(
        model=CANDIDATE_MODEL, configured_provider=CANDIDATE_PROVIDER, prompt=ie_prompt,
        case_id=INSUFFICIENT_EVIDENCE_CASE_ID, slot="candidate", envelope_sink=envelope_sink,
    )
    ref_content, _ = _call_model(
        model=REFERENCE_MODEL, configured_provider=REFERENCE_PROVIDER, prompt=ie_prompt,
        case_id=INSUFFICIENT_EVIDENCE_CASE_ID, slot="reference", envelope_sink=envelope_sink,
    )
    cand_payload = (
        build_insufficient_evidence_judge_call_payload(cand_content, slot="candidate")
        if cand_content
        else {"evaluation_status": "no_content"}
    )
    ref_payload = (
        build_insufficient_evidence_judge_call_payload(ref_content, slot="reference")
        if ref_content
        else {"evaluation_status": "no_content"}
    )
    qualification_rows.append(
        {
            "case_id": INSUFFICIENT_EVIDENCE_CASE_ID,
            "case_type": "insufficient_evidence",
            "rubric": "insufficient_evidence",
            "candidate": cand_payload,
            "reference": ref_payload,
            "prompt_version": "qa_citation_insufficient_evidence_judge_v1",
            "prompt_sha256": insufficient_evidence_prompt_sha256(),
        }
    )

    # --- Structured-output reliability summary ---
    def _is_valid(payload: dict[str, Any], rubric: str) -> bool:
        if rubric == "qa":
            return payload.get("evaluation_status") == "evaluated" and all(
                isinstance(payload.get(d), int) and 0 <= payload.get(d) <= 4
                for d in ("correctness", "completeness", "relevance", "faithfulness")
            )
        return payload.get("evaluation_status") == "evaluated" and isinstance(
            payload.get("correctly_declined", {}).get("result"), bool
        ) and isinstance(payload.get("unsupported_claim_detected", {}).get("result"), bool)

    candidate_valid = sum(1 for r in qualification_rows if _is_valid(r["candidate"], r["rubric"]))
    reference_valid = sum(1 for r in qualification_rows if _is_valid(r["reference"], r["rubric"]))

    candidate_errors = [
        {"case_id": r["case_id"], "evaluation_status": r["candidate"].get("evaluation_status"),
         "validation_error": r["candidate"].get("validation_error")}
        for r in qualification_rows if not _is_valid(r["candidate"], r["rubric"])
    ]
    reference_errors = [
        {"case_id": r["case_id"], "evaluation_status": r["reference"].get("evaluation_status"),
         "validation_error": r["reference"].get("validation_error")}
        for r in qualification_rows if not _is_valid(r["reference"], r["rubric"])
    ]

    judged_dt = datetime.now(timezone.utc)
    run_id = f"qacq_qualification_{judged_dt.strftime('%Y%m%dT%H%M%SZ')}"
    run_dir = DEFAULT_RUNS_DIR / run_id
    if run_dir.exists():
        print(f"QUALIFICATION RUN DIRECTORY ALREADY EXISTS: {run_dir}", file=sys.stderr)
        return 2
    run_dir.mkdir(parents=True, exist_ok=False)

    model_manifest = {
        "candidate_model": CANDIDATE_MODEL,
        "candidate_configured_provider_label": CANDIDATE_PROVIDER,
        "reference_model": REFERENCE_MODEL,
        "reference_configured_provider_label": REFERENCE_PROVIDER,
        "candidate_resolved_providers_seen": sorted(
            {e.get("resolved_provider") for e in envelope_sink if e.get("slot") == "candidate" and e.get("resolved_provider")}
        ),
        "reference_resolved_providers_seen": sorted(
            {e.get("resolved_provider") for e in envelope_sink if e.get("slot") == "reference" and e.get("resolved_provider")}
        ),
    }

    summary = {
        "qualification_run_id": run_id,
        "qualified_at": judged_dt.isoformat(),
        "capture_run_id": "qac_capture_20261110T014318Z_80d7ddd1",
        "capture_file_sha256": capture_file_sha256,
        "dataset_version": dataset.dataset_version,
        "dataset_json_sha256": dataset.dataset_json_sha256,
        "case_count": len(qualification_rows),
        "candidate_valid_schema_count": candidate_valid,
        "reference_valid_schema_count": reference_valid,
        "candidate_valid_schema_rate": candidate_valid / len(qualification_rows),
        "reference_valid_schema_rate": reference_valid / len(qualification_rows),
        "candidate_errors": candidate_errors,
        "reference_errors": reference_errors,
        "note": (
            "This is a small (n=8), hand-selected qualification test, NOT a "
            "statistically reliable full model validation. It uses the "
            "existing, unmodified qa_citation_judge_v1 and "
            "qa_citation_insufficient_evidence_judge_v1 prompts/rubrics "
            "against already-captured chatbot answers; no chatbot "
            "regeneration occurred."
        ),
    }

    (run_dir / "qualification_results.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in qualification_rows),
        encoding="utf-8",
    )
    (run_dir / "raw_response_envelopes.jsonl").write_text(
        "".join(json.dumps(e, ensure_ascii=False, default=str) + "\n" for e in envelope_sink),
        encoding="utf-8",
    )
    (run_dir / "qualification_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8"
    )
    (run_dir / "model_manifest.json").write_text(
        json.dumps(model_manifest, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8"
    )

    print(json.dumps({"qualification_run_id": run_id, "output_dir": str(run_dir), "summary": summary}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
