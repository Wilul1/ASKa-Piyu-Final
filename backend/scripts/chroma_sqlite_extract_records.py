"""Read-only extraction of current Chroma records into a reviewable JSON
artifact, for retrieval-evaluation dataset preparation.

DIAGNOSTIC UTILITY ONLY -- not part of the runtime application, never
imported by any route or app-startup path.

This script issues NO SQL of its own and never opens its own database
connection in anything other than read-only mode: every database access
is delegated to scripts/chroma_sqlite_recovery.py's already-reviewed,
already-safe functions (``open_source_readonly`` -- stdlib ``sqlite3``,
URI ``mode=ro``, which cannot write at the SQLite driver level --
``discover_metadata_segment_id``, ``extract_records``, ``sha256_of_file``,
``compute_records_digest``, ``compute_identity_digest``). That module is
imported, never modified, never duplicated. chromadb's own API is never
imported or invoked anywhere in this file.

Every metadata value is written out exactly as extracted -- never
normalized, rewritten, summarized, or invented. The source
``chroma.sqlite3`` is hashed immediately before and after the read; the
run is reported as failed (not silently "ok") if the two hashes differ.

Run from backend/:
    python -m scripts.chroma_sqlite_extract_records
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from scripts.chroma_sqlite_recovery import (  # noqa: E402
    compute_identity_digest,
    compute_records_digest,
    discover_metadata_segment_id,
    extract_records,
    open_source_readonly,
    sha256_of_file,
)


def _default_source_persist_dir() -> Path:
    from app.config import settings

    raw = settings.chroma_persist_dir
    path = Path(raw)
    if not path.is_absolute():
        path = BACKEND_ROOT / path
    return path.resolve()


def _default_source_collection_name() -> str:
    from app.config import settings

    return settings.chroma_collection_name


def _timestamp_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def main() -> int:
    source_dir = _default_source_persist_dir()
    source_collection = _default_source_collection_name()
    sqlite_path = source_dir / "chroma.sqlite3"

    if not sqlite_path.exists():
        print(f"ERROR: source sqlite file not found: {sqlite_path}", file=sys.stderr)
        return 2

    print(f"Source: {sqlite_path}")
    print(f"Collection: {source_collection}")

    hash_before = sha256_of_file(sqlite_path)
    print(f"SHA256 before: {hash_before}")

    # Read-only at the SQLite driver level (mode=ro) -- reused, not
    # reimplemented. No other connection to this file is ever opened.
    conn = open_source_readonly(sqlite_path)
    try:
        segment_id = discover_metadata_segment_id(conn, source_collection)
        records, exclusions = extract_records(conn, segment_id=segment_id)
    finally:
        conn.close()

    hash_after = sha256_of_file(sqlite_path)
    print(f"SHA256 after:  {hash_after}")
    hash_match = hash_before == hash_after
    if not hash_match:
        print("STOP: source hash changed during extraction. Aborting without writing an artifact.", file=sys.stderr)
        return 1

    identity_digest = compute_identity_digest(records)
    metadata_text_digest = compute_records_digest(records)

    chunk_ids = [r.embedding_id for r in records]
    duplicate_ids = len(set(chunk_ids)) != len(chunk_ids)
    missing_text = [r.embedding_id for r in records if not (r.text or "").strip()]

    # Compare against the known-good Nov 4 dry-run manifest, if present --
    # informational only, never fabricated if the file is absent.
    manifest_path = (
        BACKEND_ROOT / "benchmarks" / "results" / "chroma_recovery_manifest_20261104T103724Z.json"
    )
    manifest_comparison: dict = {"checked": False}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected_identity = manifest.get("source", {}).get("identity_digest")
        expected_metadata_text = manifest.get("source", {}).get("metadata_text_digest")
        expected_count = manifest.get("source", {}).get("record_count_passed_extraction")
        manifest_comparison = {
            "checked": True,
            "manifest_path": str(manifest_path),
            "expected_record_count": expected_count,
            "record_count_matches": expected_count == len(records),
            "expected_identity_digest": expected_identity,
            "identity_digest_matches": expected_identity == identity_digest,
            "expected_metadata_text_digest": expected_metadata_text,
            "metadata_text_digest_matches": expected_metadata_text == metadata_text_digest,
        }

    extracted_records = [
        {
            "chunk_id": r.embedding_id,
            "text": r.text,
            "metadata": dict(r.metadata),
        }
        for r in records
    ]

    out_path = BACKEND_ROOT / "benchmarks" / "results" / f"chroma_record_extraction_{_timestamp_slug()}.json"
    artifact = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "extraction_tool": "backend/scripts/chroma_sqlite_extract_records.py",
        "reused_functions_from": "backend/scripts/chroma_sqlite_recovery.py",
        "source": {
            "path": str(sqlite_path),
            "collection_name": source_collection,
            "sha256_before": hash_before,
            "sha256_after": hash_after,
            "sqlite_immutable": hash_match,
        },
        "validation": {
            "record_count": len(records),
            "exclusion_count": len(exclusions),
            "exclusions": [e.as_dict() for e in exclusions],
            "no_duplicate_chunk_ids": not duplicate_ids,
            "no_missing_text": len(missing_text) == 0,
            "missing_text_chunk_ids": missing_text,
            "identity_digest": identity_digest,
            "metadata_text_digest": metadata_text_digest,
        },
        "manifest_comparison": manifest_comparison,
        "records": extracted_records,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(artifact, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    print()
    print(f"Record count: {len(records)}")
    print(f"Exclusions: {len(exclusions)}")
    print(f"No duplicate chunk ids: {not duplicate_ids}")
    print(f"No missing text: {len(missing_text) == 0}")
    print(f"Identity digest: {identity_digest}")
    print(f"Metadata+text digest: {metadata_text_digest}")
    if manifest_comparison.get("checked"):
        print(f"Matches Nov 4 manifest -- count: {manifest_comparison['record_count_matches']}, "
              f"identity: {manifest_comparison['identity_digest_matches']}, "
              f"metadata+text: {manifest_comparison['metadata_text_digest_matches']}")
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
