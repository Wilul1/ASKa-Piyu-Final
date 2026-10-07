"""One-off backfill: recover SourceDocument.pdf_data from ingestion_jobs.

Root cause this recovers from: the web dyno's local filesystem is
ephemeral, so every PDF written there is lost on the next restart/deploy.
The ``source_documents`` row survives (in durable Postgres) but its file
does not. The original bytes often still exist, durably, in a historical
``ingestion_jobs.pdf_bytes`` row for the same filename -- this script finds
an UNAMBIGUOUS such match and copies the bytes into
``SourceDocument.pdf_data``.

Safety, by construction:
  - Read-mostly. Dry-run is the DEFAULT -- pass --apply to actually write.
  - NEVER touches Chroma (no import of chroma_store/get_knowledge_base_store
    anywhere in this file).
  - NEVER deletes an ingestion_jobs or source_documents row.
  - NEVER creates a new Chroma vector or changes any Chroma document_id.
  - NEVER matches "only by latest job": candidates are filtered by
    normalized filename (and byte_size, when known), and are accepted only
    when every surviving candidate's pdf_bytes is BYTE-IDENTICAL (same
    sha256). If more than one distinct content is found, the row is
    skipped and reported -- never guessed.
  - Only ever writes the ``pdf_data`` column of an existing
    ``source_documents`` row; never touches ``stored_file_path`` or any
    other column.

This script is intended for local/manual review before ever being pointed
at production. It must NEVER be run directly against the production
database as part of an automated workflow -- see the project's production
deployment runbook for the explicit, reviewed procedure.
"""

from __future__ import annotations

import argparse
import hashlib
import re
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.db_models import IngestionJob, SourceDocument
from app.services.document_storage import is_source_pdf_resolvable


def _normalize_filename(name: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", (name or "").casefold())


@dataclass
class BackfillResult:
    source_document_id: str
    original_filename: str
    status: str  # "already_ok" | "matched" | "skipped_ambiguous" | "skipped_no_candidate"
    detail: str
    matched_job_id: str | None = None
    bytes_available: int | None = None


def find_backfill_candidates(session: Session) -> list[BackfillResult]:
    """Read-only: compute what the backfill WOULD do. Zero writes."""
    results: list[BackfillResult] = []
    rows = session.query(SourceDocument).all()
    all_jobs = session.query(IngestionJob).filter(IngestionJob.pdf_bytes.isnot(None)).all()

    for row in rows:
        if is_source_pdf_resolvable(row):
            results.append(
                BackfillResult(
                    source_document_id=row.id,
                    original_filename=row.original_filename,
                    status="already_ok",
                    detail="Local file or pdf_data already available; nothing to do.",
                )
            )
            continue

        target_name = _normalize_filename(row.original_filename)
        candidates = [
            job for job in all_jobs if _normalize_filename(job.source_filename) == target_name
        ]
        if row.byte_size:
            byte_matched = [job for job in candidates if job.byte_size == row.byte_size]
            if byte_matched:
                candidates = byte_matched

        if not candidates:
            results.append(
                BackfillResult(
                    source_document_id=row.id,
                    original_filename=row.original_filename,
                    status="skipped_no_candidate",
                    detail=(
                        "No ingestion_jobs row with a matching filename "
                        "(and byte_size, when known) carries pdf_bytes."
                    ),
                )
            )
            continue

        hashes = {hashlib.sha256(job.pdf_bytes).hexdigest() for job in candidates}
        if len(hashes) > 1:
            results.append(
                BackfillResult(
                    source_document_id=row.id,
                    original_filename=row.original_filename,
                    status="skipped_ambiguous",
                    detail=(
                        f"{len(candidates)} candidate ingestion_jobs rows match by filename"
                        f"/byte_size but carry {len(hashes)} distinct byte contents -- "
                        "never guessing; skipped."
                    ),
                )
            )
            continue

        # Every surviving candidate is byte-identical: which one is picked
        # cannot change the result, so this is a safe, unambiguous match --
        # never "latest job" as a tiebreaker when content could differ.
        chosen = candidates[0]
        results.append(
            BackfillResult(
                source_document_id=row.id,
                original_filename=row.original_filename,
                status="matched",
                detail=f"Unique byte-identical match across {len(candidates)} candidate job(s).",
                matched_job_id=chosen.id,
                bytes_available=len(chosen.pdf_bytes),
            )
        )

    return results


def apply_backfill(session: Session, results: list[BackfillResult]) -> int:
    """Write pdf_data for every 'matched' result only. Returns rows written.

    Never touches Chroma. Never deletes ingestion_jobs or source_documents.
    Only ever sets SourceDocument.pdf_data on an existing row.
    """
    written = 0
    for result in results:
        if result.status != "matched" or not result.matched_job_id:
            continue
        row = session.get(SourceDocument, result.source_document_id)
        job = session.get(IngestionJob, result.matched_job_id)
        if row is None or job is None or not job.pdf_bytes:
            continue
        row.pdf_data = job.pdf_bytes
        written += 1
    if written:
        session.commit()
    return written


def _print_report(results: list[BackfillResult]) -> None:
    for result in results:
        print(
            f"[{result.status}] source_documents.id={result.source_document_id} "
            f"filename={result.original_filename!r}: {result.detail}"
        )
    print("")
    print(f"Total rows inspected: {len(results)}")
    print(f"Already OK: {sum(1 for r in results if r.status == 'already_ok')}")
    print(f"Matched (recoverable): {sum(1 for r in results if r.status == 'matched')}")
    print(f"Skipped (ambiguous): {sum(1 for r in results if r.status == 'skipped_ambiguous')}")
    print(
        f"Skipped (no candidate): {sum(1 for r in results if r.status == 'skipped_no_candidate')}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write pdf_data for unambiguously matched rows. "
        "Default is dry-run: report only, zero writes.",
    )
    args = parser.parse_args()

    from app.db.session import get_session_factory

    session = get_session_factory()()
    try:
        results = find_backfill_candidates(session)
        _print_report(results)

        if not args.apply:
            print("")
            print(
                "DRY RUN (default) -- zero writes performed. "
                "Pass --apply to write pdf_data for matched rows."
            )
            return

        written = apply_backfill(session, results)
        print("")
        print(f"APPLIED -- wrote pdf_data for {written} row(s).")
    finally:
        session.close()


if __name__ == "__main__":
    main()
