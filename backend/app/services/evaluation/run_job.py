"""Subprocess entry for one evaluation run.

The API worker must not run ``run_evaluation`` in-process: loading
sentence-transformers / Chroma on the same Python interpreter freezes
login and every other request for tens of seconds (GIL + CPU).
"""

from __future__ import annotations

import logging
import os
import sys

# Must be set before importing torch/sentence-transformers. Two processes
# loading Intel OpenMP (the API worker already warmed embeddings) otherwise
# abort with Windows STATUS_ACCESS_VIOLATION (0xC0000005).
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

from app.services.evaluation.persistence import process_evaluation_run_job  # noqa: E402

logger = logging.getLogger(__name__)


def main(argv: list[str]) -> int:
    if len(argv) != 2 or not argv[1].strip():
        print("usage: python -m app.services.evaluation.run_job <run_id>", file=sys.stderr)
        return 2
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    run_id = argv[1].strip()
    logger.info("evaluation subprocess starting run_id=%s", run_id)
    process_evaluation_run_job(run_id)
    logger.info("evaluation subprocess finished run_id=%s", run_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
