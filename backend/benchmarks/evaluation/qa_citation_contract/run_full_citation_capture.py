"""Stage 3.4: full 36-case citation-enabled capture.

Thin wrapper around the existing, fully-audited Stage 3.1
run_answer_capture() -- which already internally forces synchronous
("llm") citation verification via _force_synchronous_citation_verification
-- adding only one further evaluation-only override on top: pointing
settings.citation_verifier_model at the Stage 3.3-qualified replacement,
dots-studio/dots-3-note-preview:free. No other code changes anywhere, no
new capture logic, no new retrieval/generation logic -- 100% reuse of
run_answer_capture()/capture_one_case() exactly as already written and
audited.

Does not run citation judging. Writes a brand-new, separate run directory
(Stage 3.1's own "never overwrite" guard applies); never modifies any
historical capture, qualification, or judging artifact.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.evaluation.qa_citation_capture import (  # noqa: E402
    DEFAULT_LIVE_DATASET_PATH,
    QaCitationCaptureError,
    run_answer_capture,
)
from app.services.evaluation.qa_citation_corpus import CorpusIdentityError  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_citation_verifier_qualification import (  # noqa: E402
    REPLACEMENT_VERIFIER_MODEL,
    REPLACEMENT_VERIFIER_PROVIDER,
    _force_citation_verifier_model,
)

EXPECTED_DATASET_SHA256 = "81f66f25d007f373512936880edca530c4f2137377ee5601fbb155fe81455972"
EXPECTED_CORPUS_IDENTITY_DIGEST = "fcb324dad73c41684e771defec0a36937ddde014df858c3f020aaf914774c85b"
EXPECTED_CORPUS_METADATA_TEXT_DIGEST = (
    "7cec45b38d017d17f4f7b39abf3dc2d52a4f6f832b179ea2b70c37c6086262d7"
)

MODEL_MANIFEST_NOTE = (
    "KNOWN LIMITATION: the production citation_verification.py module "
    "(unmodified by this capture) does not record resolved model/provider "
    "identity, a response id, or a call timestamp for verifier calls -- "
    "only `usage` and parsed `content` are captured in "
    "citation_v2_sink/VerificationOutcome. Full verifier-response-envelope "
    "traceability is NOT claimed for this capture. Resolved-provider "
    "confirmation for dots-studio/dots-3-note-preview:free exists only "
    "from the separate Stage 3.3 qualification test "
    "(qacv_citation_qual_20261110T061915Z), which called the OpenRouter "
    "API directly outside the production module."
)


def main() -> int:
    import hashlib

    dataset_bytes = DEFAULT_LIVE_DATASET_PATH.read_bytes()
    actual_dataset_sha256 = hashlib.sha256(dataset_bytes).hexdigest()
    if actual_dataset_sha256 != EXPECTED_DATASET_SHA256:
        print(
            f"DATASET HASH MISMATCH: expected {EXPECTED_DATASET_SHA256}, "
            f"got {actual_dataset_sha256}. Stopping.",
            file=sys.stderr,
        )
        return 2

    with _force_citation_verifier_model(REPLACEMENT_VERIFIER_MODEL):
        try:
            result = run_answer_capture(dataset_path=DEFAULT_LIVE_DATASET_PATH)
        except (QaCitationCaptureError, CorpusIdentityError) as exc:
            print(f"CAPTURE NOT EXECUTED: {exc}", file=sys.stderr)
            return 2

    corpus_report = result.corpus or {}
    if corpus_report.get("identity_digest") != EXPECTED_CORPUS_IDENTITY_DIGEST:
        print(
            "CORPUS IDENTITY DIGEST MISMATCH after capture completed -- "
            "reporting, not rolling back (run is already written and immutable).",
            file=sys.stderr,
        )
    if corpus_report.get("metadata_text_digest") != EXPECTED_CORPUS_METADATA_TEXT_DIGEST:
        print(
            "CORPUS METADATA-TEXT DIGEST MISMATCH after capture completed -- "
            "reporting, not rolling back.",
            file=sys.stderr,
        )

    model_manifest = {
        "verifier_model": REPLACEMENT_VERIFIER_MODEL,
        "verifier_configured_provider_label": REPLACEMENT_VERIFIER_PROVIDER,
        "verifier_expected_resolved_provider": "AtlasCloud",
        "note": MODEL_MANIFEST_NOTE,
    }
    (result.output_dir / "model_manifest.json").write_text(
        json.dumps(model_manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print(
        json.dumps(
            {
                "run_id": result.run_id,
                "output_dir": str(result.output_dir),
                "dataset_version": result.dataset_version,
                "status_counts": result.status_counts,
                "record_count": len(result.records),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
