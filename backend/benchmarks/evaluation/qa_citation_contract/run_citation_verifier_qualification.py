"""Stage 3.3: citation-verifier qualification -- a SMALL real chatbot
capture test (at most 3 cases) through the actual answer_qa_question()
pipeline, with citation verification forced synchronous and pointed at a
replacement verifier model, to confirm displayed citation IDs are now
produced correctly.

Root cause of the original HTTP 404
------------------------------------
The previously configured citation_verifier_model,
"nvidia/nemotron-3-super-120b-a12b:free", does not exist on OpenRouter.
The base model "nvidia/nemotron-3-super-120b-a12b" exists WITHOUT a
":free" variant (confirmed via a fresh GET to OpenRouter's public
/api/v1/models catalog) -- an invalid/stale model ID, not a provider-
routing issue or a request-construction bug. Separately and importantly:
_call_verifier() (citation_verification.py) sends a strict
response_format=json_schema request -- the verifier model must support
OpenRouter's "structured_outputs" capability. Of the current free-tier
catalog, only 5 models advertise this; the QA secondary judge
(nvidia/nemotron-3-ultra-550b-a55b:free) is NOT one of them, so it could
not have served as the citation verifier even if its name had been
correct.

Replacement verifier: dots-studio/dots-3-note-preview:free (provider
AtlasCloud) -- already the QA primary judge, chosen here primarily for
proven reliability (100% success across 39 prior real calls across the
QA judging and qualification runs) and confirmed structured_outputs
support, over an untested-at-scale alternative
(nvidia/nemotron-3.5-super-vl:free, which also supports structured
outputs and also passed a one-off preflight test but has no track record
in this project).

Evaluation-only overrides, both via try/finally context managers, both
restored unconditionally: citation_verification_mode -> "llm" (reusing
qa_citation_capture.py's existing _force_synchronous_citation_verification,
unmodified) and citation_verifier_model -> the replacement candidate
(new, local to this script only). Neither writes to backend/.env or
changes app/config.py's defaults; neither affects any other process.

Reuses capture_one_case() (Stage 3.1, unmodified) directly for the actual
chatbot call per selected case -- no reimplementation of retrieval,
generation, or citation-verification orchestration. Selects 3 real,
already-dataset-defined answerable cases (never the fallback case
qac_025) by filtering the loaded dataset client-side; writes no new
dataset file and does not modify qa_citation_eval_dataset.json.
"""

from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import settings  # noqa: E402
from app.services.evaluation.qa_citation_capture import (  # noqa: E402
    DEFAULT_RUNS_DIR,
    EXPECTED_LABELED_RETRIEVAL_CHUNK_COUNT,
    LABELED_RETRIEVAL_COLLECTION,
    LABELED_RETRIEVAL_INDEX_PATH,
    EvaluationStudentStore,
    QaCitationCaptureError,
    _force_synchronous_citation_verification,
    capture_one_case,
    model_config_snapshot,
)
from app.services.evaluation.qa_citation_corpus import CorpusIdentityError, verify_evaluation_corpus  # noqa: E402
from app.services.evaluation.qa_citation_dataset import load_qa_citation_dataset  # noqa: E402
from app.services.evaluation.labeled_retrieval_store import LabeledRetrievalStore  # noqa: E402

REPLACEMENT_VERIFIER_MODEL = "dots-studio/dots-3-note-preview:free"
REPLACEMENT_VERIFIER_PROVIDER = "atlascloud"

SELECTED_CASE_IDS = [
    "qac_001_tor_undergrad_fee",
    "qac_008_latin_cum_laude",
    "qac_013_shifting_conditions",
]
DATASET_PATH = BACKEND_ROOT / "benchmarks" / "evaluation" / "qa_citation_eval_dataset.json"


@contextmanager
def _force_citation_verifier_model(model: str):
    """Evaluation-only, process-local override, mirroring
    qa_citation_capture.py's _force_synchronous_citation_verification
    exactly in shape: try/finally, original value always restored
    (including on exception), never writes to .env or changes
    app/config.py's default."""
    original = settings.citation_verifier_model
    settings.citation_verifier_model = model
    try:
        yield
    finally:
        settings.citation_verifier_model = original


def main() -> int:
    dataset = load_qa_citation_dataset(DATASET_PATH)
    cases_by_id = {c.case_id: c for c in dataset.cases}
    for cid in SELECTED_CASE_IDS:
        case = cases_by_id.get(cid)
        if case is None:
            print(f"SELECTED CASE NOT IN DATASET: {cid}", file=sys.stderr)
            return 2
        if case.case_type != "labeled_student_support":
            print(f"SELECTED CASE IS NOT ANSWERABLE: {cid} ({case.case_type})", file=sys.stderr)
            return 2

    try:
        corpus_identity = verify_evaluation_corpus(persist_report_path=None)
    except CorpusIdentityError as exc:
        print(f"CORPUS IDENTITY FAILED: {exc}", file=sys.stderr)
        return 2
    if not corpus_identity.corresponds:
        print("CORPUS DOES NOT CORRESPOND TO LOCKED EXTRACT. Stopping.", file=sys.stderr)
        return 2

    labeled = LabeledRetrievalStore(
        index_path=LABELED_RETRIEVAL_INDEX_PATH, collection_name=LABELED_RETRIEVAL_COLLECTION
    )
    if labeled.chunk_count != EXPECTED_LABELED_RETRIEVAL_CHUNK_COUNT:
        print(
            f"LabeledRetrievalStore chunk_count={labeled.chunk_count}, "
            f"expected {EXPECTED_LABELED_RETRIEVAL_CHUNK_COUNT}. Stopping.",
            file=sys.stderr,
        )
        return 2
    store = EvaluationStudentStore(labeled)

    captured_dt = datetime.now(timezone.utc)
    run_id = f"qacv_citation_qual_{captured_dt.strftime('%Y%m%dT%H%M%SZ')}"
    run_dir = DEFAULT_RUNS_DIR / run_id
    if run_dir.exists():
        print(f"QUALIFICATION RUN DIRECTORY ALREADY EXISTS: {run_dir}", file=sys.stderr)
        return 2

    records: list[dict[str, Any]] = []
    with _force_synchronous_citation_verification(), _force_citation_verifier_model(
        REPLACEMENT_VERIFIER_MODEL
    ):
        model_snapshot = model_config_snapshot()
        for case_id in SELECTED_CASE_IDS:
            print(f"Capturing {case_id} with synchronous citation verification...", file=sys.stderr)
            case = cases_by_id[case_id]
            try:
                record = capture_one_case(
                    case,
                    run_id=run_id,
                    dataset=dataset,
                    corpus_identity=corpus_identity,
                    store=store,
                    captured_at=datetime.now(timezone.utc).isoformat(),
                    model_snapshot=model_snapshot,
                )
            except QaCitationCaptureError as exc:
                print(f"CAPTURE FAILED for {case_id}: {exc}", file=sys.stderr)
                return 2
            records.append(record)

    # --- Build the qualification artifact: per-case citation-ID validity checks ---
    results = []
    for record in records:
        displayed_ids = record.get("displayed_citation_ids") or []
        retrieved_ids = set(record.get("retrieved_chunk_ids") or [])
        gen_context_ids = set(record.get("generation_context_chunk_ids") or [])
        # Every displayed ID must correspond to an actually-retrieved source
        # (never invented) -- confirmed directly from this record's own
        # retrieved_chunk_ids, not assumed.
        all_displayed_correspond_to_retrieved = all(
            cid in retrieved_ids or cid in gen_context_ids for cid in displayed_ids
        )
        raw = record.get("raw_qa_result_json") or {}
        citation_v2 = raw.get("citation_v2_sink") or {}
        results.append(
            {
                "case_id": record["case_id"],
                "execution_status": record["execution_status"],
                "is_genuine_model_output": record.get("is_genuine_model_output"),
                "fallback_used": record.get("fallback_used"),
                "fallback_reason": record.get("fallback_reason"),
                "generated_answer": record.get("generated_answer"),
                "displayed_citation_ids": displayed_ids,
                "displayed_citation_count": len(displayed_ids),
                "all_displayed_ids_correspond_to_retrieved_sources": all_displayed_correspond_to_retrieved,
                "retrieved_chunk_ids_count": len(retrieved_ids),
                "citation_v2_sink": citation_v2,
            }
        )

    produced_citations_count = sum(1 for r in results if r["displayed_citation_count"] > 0)

    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "capture_results.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in records),
        encoding="utf-8",
    )

    model_manifest = {
        "replacement_verifier_model": REPLACEMENT_VERIFIER_MODEL,
        "replacement_verifier_configured_provider_label": REPLACEMENT_VERIFIER_PROVIDER,
        "resolved_providers_seen": sorted(
            {
                r["citation_v2_sink"].get("resolved_provider")
                for r in results
                if isinstance(r["citation_v2_sink"], dict) and r["citation_v2_sink"].get("resolved_provider")
            }
        ),
        "original_failing_model": "nvidia/nemotron-3-super-120b-a12b:free",
        "original_failure_root_cause": (
            "Model ID does not exist on OpenRouter -- the base model "
            "nvidia/nemotron-3-super-120b-a12b exists without a ':free' "
            "variant, confirmed via GET /api/v1/models. Separately, the "
            "citation verifier requires structured_outputs support, which "
            "the QA secondary judge (nvidia/nemotron-3-ultra-550b-a55b:free) "
            "does not have."
        ),
    }

    summary = {
        "qualification_run_id": run_id,
        "qualified_at": captured_dt.isoformat(),
        "dataset_version": dataset.dataset_version,
        "dataset_json_sha256": dataset.dataset_json_sha256,
        "corpus": {
            "identity_digest": corpus_identity.evaluation_identity_digest,
            "metadata_text_digest": corpus_identity.evaluation_metadata_text_digest,
            "corresponds": corpus_identity.corresponds,
        },
        "selected_case_ids": SELECTED_CASE_IDS,
        "case_count": len(records),
        "cases_with_displayed_citations": produced_citations_count,
        "all_displayed_ids_correspond_to_retrieved_sources_overall": all(
            r["all_displayed_ids_correspond_to_retrieved_sources"] for r in results
        ),
        "per_case_results": results,
        "note": (
            "This is a small (n=3) real-capture qualification test, NOT a "
            "full citation capture or full citation judging run. Uses the "
            "unmodified Stage 2/3.1 prompts, rubric, and capture_one_case() "
            "orchestration; only citation_verification_mode and "
            "citation_verifier_model were overridden, both evaluation-only "
            "and restored after this run."
        ),
    }
    (run_dir / "citation_verifier_qualification.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8"
    )
    (run_dir / "model_manifest.json").write_text(
        json.dumps(model_manifest, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8"
    )

    print(
        json.dumps(
            {
                "run_id": run_id,
                "output_dir": str(run_dir),
                "cases_with_displayed_citations": produced_citations_count,
                "case_count": len(records),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
