"""Re-embed core handbook/charter PDFs into Chroma from durable Postgres pdf_data.

Use after an embedding-model switch (e.g. e5-small -> Gemini) when
ASKA_KB_REBUILD_DOCUMENT_PATHS is empty on the dyno but source_documents
still hold the PDFs.

  heroku run -a aska-piyu -- bash -lc 'cd /app && PYTHONPATH=/app python scripts/reingest_core_corpora_to_chroma.py'

Optional:
  ASKA_REINGEST_ONLY=handbook|charter|faculty  — single corpus
  ASKA_REINGEST_SLEEP_SECONDS=90               — pause between documents
"""

from __future__ import annotations

import os
import sys
import time

CORE_FILENAMES = (
    "Laguna State Polytechnic University-CC_2026-1st Edition.pdf",
    "LSPU Student Handbook.pdf",
    "LSPU Faculty Manual 2020.pdf",
)

_ONLY_ALIASES = {
    "charter": "Laguna State Polytechnic University-CC_2026-1st Edition.pdf",
    "handbook": "LSPU Student Handbook.pdf",
    "faculty": "LSPU Faculty Manual 2020.pdf",
}


def _selected_filenames() -> tuple[str, ...]:
    only = (os.environ.get("ASKA_REINGEST_ONLY") or "").strip().casefold()
    if not only:
        return CORE_FILENAMES
    if only in _ONLY_ALIASES:
        return (_ONLY_ALIASES[only],)
    for name in CORE_FILENAMES:
        if only in name.casefold():
            return (name,)
    raise SystemExit(f"Unknown ASKA_REINGEST_ONLY={only!r}")


def _best_source_row(session, filename: str):
    from app.models.db_models import SourceDocument

    rows = (
        session.query(SourceDocument)
        .filter(SourceDocument.original_filename == filename)
        .all()
    )
    if not rows:
        return None
    return max(rows, key=lambda row: len(row.pdf_data or b""))


def _publish_with_retries(pdf_bytes: bytes, *, filename: str, content_type: str, title: str):
    from app.services.admin.digital_ingestion import (
        DigitalIngestionError,
        build_lightweight_publish,
    )

    attempts = 4
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return build_lightweight_publish(
                pdf_bytes,
                filename=filename,
                content_type=content_type,
                title=title,
            )
        except DigitalIngestionError as exc:
            last_exc = exc
            message = str(exc)
            if "429" not in message and "rate" not in message.casefold():
                raise
            wait_s = min(180, 30 * attempt)
            print(
                f"RETRY filename={filename} attempt={attempt}/{attempts} "
                f"wait_s={wait_s} error={message}"
            )
            time.sleep(wait_s)
        except Exception as exc:
            last_exc = exc
            message = f"{type(exc).__name__}: {exc}"
            if "429" not in message:
                raise
            wait_s = min(180, 30 * attempt)
            print(
                f"RETRY filename={filename} attempt={attempt}/{attempts} "
                f"wait_s={wait_s} error={message}"
            )
            time.sleep(wait_s)
    assert last_exc is not None
    raise last_exc


def main() -> int:
    from app.db.session import get_session_factory

    filenames = _selected_filenames()
    sleep_s = int(os.environ.get("ASKA_REINGEST_SLEEP_SECONDS") or "90")
    session = get_session_factory()()
    failures = 0
    try:
        for index, filename in enumerate(filenames):
            if index > 0:
                print(f"SLEEP between_docs_s={sleep_s}")
                time.sleep(sleep_s)
            row = _best_source_row(session, filename)
            if row is None or not row.pdf_data:
                print(f"FAIL missing_pdf filename={filename}")
                failures += 1
                continue
            pdf_bytes = bytes(row.pdf_data)
            print(
                f"START filename={filename} source_id={row.id} "
                f"pdf_bytes={len(pdf_bytes)} type={row.document_type}"
            )
            try:
                result = _publish_with_retries(
                    pdf_bytes,
                    filename=filename,
                    content_type=row.content_type or "application/pdf",
                    title=row.source_label or filename.rsplit(".", 1)[0],
                )
            except Exception as exc:
                print(f"FAIL ingestion filename={filename} error={exc}")
                failures += 1
                continue
            print(
                f"OK filename={filename} document_id={result.get('document_id')} "
                f"chunks={result.get('chunks_indexed')} pages={result.get('page_count')} "
                f"method={result.get('extraction_method')} "
                f"structuring={result.get('structuring_method')}"
            )
    finally:
        session.close()

    if failures:
        print(f"DONE with_failures={failures}")
        return 1
    print("DONE ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
