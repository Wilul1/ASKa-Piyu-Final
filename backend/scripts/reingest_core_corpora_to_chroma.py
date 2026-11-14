"""Re-embed core handbook/charter PDFs into Chroma from durable Postgres pdf_data.

Use after an embedding-model switch (e.g. e5-small -> Gemini) when
ASKA_KB_REBUILD_DOCUMENT_PATHS is empty on the dyno but source_documents
still hold the PDFs.

  heroku run -a aska-piyu -- python scripts/reingest_core_corpora_to_chroma.py
"""

from __future__ import annotations

import sys
import time

CORE_FILENAMES = (
    "Laguna State Polytechnic University-CC_2026-1st Edition.pdf",
    "LSPU Student Handbook.pdf",
    "LSPU Faculty Manual 2020.pdf",
)


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


def main() -> int:
    from app.db.session import get_session_factory
    from app.services.admin.digital_ingestion import (
        DigitalIngestionError,
        build_lightweight_publish,
    )

    session = get_session_factory()()
    failures = 0
    try:
        for index, filename in enumerate(CORE_FILENAMES):
            if index > 0:
                # Pause between documents so Gemini free-tier quota can recover.
                time.sleep(15)
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
                result = build_lightweight_publish(
                    pdf_bytes,
                    filename=filename,
                    content_type=row.content_type or "application/pdf",
                    title=row.source_label or filename.rsplit(".", 1)[0],
                )
            except DigitalIngestionError as exc:
                print(f"FAIL ingestion filename={filename} error={exc}")
                failures += 1
                continue
            except Exception as exc:
                print(f"FAIL unexpected filename={filename} error={type(exc).__name__}: {exc}")
                failures += 1
                continue
            print(
                f"OK filename={filename} document_id={result.get('document_id')} "
                f"chunks={result.get('chunks_indexed')} pages={result.get('page_count')} "
                f"method={result.get('extraction_method')}"
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
