"""Stage 3.1 CLI: capture chatbot answers for qa_citation_v1.

Does not judge, migrate, or call generate_groq_answer() as a substitute.
Refuses to run when the live dataset is missing or the evaluation corpus
does not correspond to the locked extract.
"""

from __future__ import annotations

import argparse
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
from app.services.evaluation.qa_citation_corpus import (  # noqa: E402
    CorpusIdentityError,
    verify_evaluation_corpus,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT_LIVE_DATASET_PATH,
        help="Live qa_citation_eval_dataset.json (Stage 2 loader). Not an example file.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Parent directory for a new run folder. Existing run ids are refused.",
    )
    parser.add_argument(
        "--verify-corpus-only",
        action="store_true",
        help="Verify evaluation Chroma against the locked extract and exit.",
    )
    args = parser.parse_args(argv)

    if args.verify_corpus_only:
        try:
            identity = verify_evaluation_corpus()
        except CorpusIdentityError as exc:
            print(f"CORPUS IDENTITY FAILED: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(identity.as_dict(), indent=2, ensure_ascii=False))
        return 0

    try:
        result = run_answer_capture(dataset_path=args.dataset, output_dir=args.output_dir)
    except (QaCitationCaptureError, CorpusIdentityError) as exc:
        print(f"CAPTURE NOT EXECUTED: {exc}", file=sys.stderr)
        return 2

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
