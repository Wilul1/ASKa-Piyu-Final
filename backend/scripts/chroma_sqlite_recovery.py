"""Strategy B Chroma recovery tool -- DIAGNOSTIC/RECOVERY UTILITY ONLY.

Not part of the runtime application; never imported by any route or
app-startup path. Implements the approved Strategy B design: read the
existing (broken) Chroma SQLite metadata store directly (never through
chromadb, never via the crashing HNSW vector segment), preserve every
record's exact identity/text/metadata, regenerate vectors through the
REAL, unmodified production embedding implementation, and write the
result into a completely NEW Chroma store at an explicit destination.
The broken source is never written to, never opened via chromadb's own
API, and `index_metadata.pickle` (or any other HNSW binary file) is never
read or deserialized by this tool.

Three modes:

    python scripts/chroma_sqlite_recovery.py
        Dry run (the default): extracts and validates records from the
        source SQLite metadata store, reports counts/exclusions/identity
        and text-validation results, and checks destination safety if
        --dest was also given. Never regenerates vectors, never writes
        anything, never loads the embedding model.

    python scripts/chroma_sqlite_recovery.py --execute --dest <new-path>
        Full recovery: extraction + validation (as above) PLUS vector
        regeneration through the real production embedding function and
        a write into a brand-new Chroma store at --dest. Requires BOTH
        --execute and an explicit --dest; there is no implicit
        destination.

    python scripts/chroma_sqlite_recovery.py --validate <recovered-path> --validate-collection <name>
        Validates an already-recovered destination store: reconciles ids/
        metadata/text digests against the manifest, and proves count()/
        query() succeed by running them in FRESH, ISOLATED SUBPROCESSES
        (never in this process) -- mirroring exactly the isolation
        technique used to originally diagnose the source store's native
        crash, so a validation run can never itself risk taking down the
        calling process. Never points at the broken source store.

Identity contract: a record is write-eligible only if its Chroma
``embedding_id`` and its ``chunk_id`` metadata are BOTH present and
EQUAL, and its ``document_id``/``chunk_index`` metadata are present. Any
violation excludes that record (never synthesizes a replacement id) and
marks the whole run ``incomplete``.

Text contract: the authoritative text for re-embedding is
``embedding_metadata`` where ``key='chroma:document'``, cross-checked for
exact equality against ``embedding_fulltext_search_content.c0`` for the
same row. A mismatch excludes the record; no normalization/trimming/
re-extraction/re-chunking/OCR is ever performed.

Metadata contract: every other ``(id, key)`` pair found in
``embedding_metadata`` is carried over verbatim, with its native SQLite
type (str/int/float/bool) preserved -- ``chroma:document`` itself is
pulled out as the record's text (Chroma's own internal document-text
key, not real ASKa-Piyu content metadata) and is the only key ever
excluded from the written metadata payload; this exclusion is recorded
explicitly in the manifest, never silent.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

BACKEND_ROOT = Path(__file__).resolve().parents[1]

# Bootstrap only: every project script here (see citation_grounding_
# baseline.py / citation_grounding_capture.py) is documented and normally
# run as `python -m scripts.<name>` FROM backend/, which already puts
# backend/ on sys.path so `app.*` imports resolve. This tool's own module
# docstring additionally documents direct invocation
# (`python scripts/chroma_sqlite_recovery.py ...`), which Python runs with
# sys.path[0] set to backend/scripts/ instead -- backend/ itself is never
# added, so every local `from app...` import inside this module's
# functions would fail with ModuleNotFoundError. This insert makes both
# documented invocation forms resolve identically; it touches only
# sys.path, never any recovery/extraction/embedding/validation logic, and
# is a no-op (guarded) when `-m` invocation (or a normal test import) has
# already put backend/ on the path.
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

TEXT_METADATA_KEY = "chroma:document"
EXCLUDED_METADATA_KEYS = frozenset({TEXT_METADATA_KEY})
REQUIRED_IDENTITY_KEYS = ("document_id", "chunk_id", "chunk_index")
EXPECTED_DIMENSIONALITY = 384
RECOVERY_TOOL_IDENTIFIER = "backend/scripts/chroma_sqlite_recovery.py"
RECOVERY_TOOL_VERSION = "chroma_sqlite_recovery/1.0.0"


# --- Exceptions --------------------------------------------------------------


class RecoverySafetyError(Exception):
    """A destination-safety invariant was violated. Never caught silently."""


class ExtractionError(Exception):
    """A structural extraction precondition failed (aborts the whole run)."""


class EmbeddingBatchError(Exception):
    """An entire embedding batch failed (aborts the whole run, per design)."""


# --- Data structures -----------------------------------------------------


@dataclass
class ExtractedRecord:
    embedding_id: str
    text: str
    metadata: dict[str, Any]
    row_id: int


@dataclass
class EmbeddedRecord:
    embedding_id: str
    text: str
    metadata: dict[str, Any]
    vector: list[float]


@dataclass
class ExclusionReason:
    row_id: int | None
    embedding_id: str | None
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {"row_id": self.row_id, "embedding_id": self.embedding_id, "reason": self.reason}


# --- Destination / source safety ---------------------------------------------


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def validate_destination_safety(source_chroma_dir: Path, destination: Path) -> None:
    """Raises RecoverySafetyError on any violation. Never mutates anything."""
    try:
        source = source_chroma_dir.resolve()
    except OSError as exc:
        raise RecoverySafetyError(f"could not resolve source path {source_chroma_dir}: {exc}") from exc
    try:
        dest = destination.resolve()
    except OSError as exc:
        raise RecoverySafetyError(f"could not resolve destination path {destination}: {exc}") from exc

    if dest == source:
        raise RecoverySafetyError(f"destination equals source Chroma path: {dest}")
    if _is_within(dest, source):
        raise RecoverySafetyError(f"destination is inside the source Chroma path: {dest} within {source}")
    if _is_within(source, dest):
        raise RecoverySafetyError(f"source Chroma path is inside the destination: {source} within {dest}")
    if dest.exists():
        if dest.is_file():
            raise RecoverySafetyError(f"destination already exists as a file: {dest}")
        if any(dest.iterdir()):
            raise RecoverySafetyError(f"destination already exists and is non-empty: {dest}")


# --- Source SQLite access (read-only; never through chromadb) ----------------


def open_source_readonly(sqlite_path: Path) -> sqlite3.Connection:
    """Open the source chroma.sqlite3 in SQLite's own read-only URI mode.

    This connection can never write, at the driver level -- independent of
    whether any code here attempts to. chromadb's own API is never
    imported or invoked against the source path anywhere in this module;
    only Python's stdlib ``sqlite3`` touches it.
    """
    uri = f"file:{sqlite_path.resolve().as_posix()}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def sha256_of_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def discover_metadata_segment_id(conn: sqlite3.Connection, collection_name: str) -> str:
    """Dynamically discover the METADATA segment id -- never hardcoded."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT s.id FROM segments s
        JOIN collections c ON s.collection = c.id
        WHERE c.name = ? AND s.scope = 'METADATA'
        """,
        (collection_name,),
    )
    rows = cur.fetchall()
    if not rows:
        raise ExtractionError(f"no METADATA segment found for collection {collection_name!r}")
    if len(rows) > 1:
        raise ExtractionError(
            f"multiple METADATA segments found for collection {collection_name!r}: {rows}"
        )
    return rows[0][0]


def _typed_value(row: tuple) -> Any:
    """One row of (id, key, string_value, int_value, float_value, bool_value)
    -> the single non-None typed value. Uses ``is not None`` throughout, never
    truthiness, so a legitimate 0/0.0/False value is never mistaken for
    "absent" (the exact chunk_index==0 pitfall this tool must not repeat)."""
    _row_id, _key, string_value, int_value, float_value, bool_value = row
    if string_value is not None:
        return string_value
    if int_value is not None:
        return int_value
    if float_value is not None:
        return float_value
    if bool_value is not None:
        return bool(bool_value)
    return None


def _group_metadata(rows: list[tuple]) -> dict[int, dict[str, Any]]:
    grouped: dict[int, dict[str, Any]] = {}
    for row in rows:
        row_id = row[0]
        key = row[1]
        grouped.setdefault(row_id, {})[key] = _typed_value(row)
    return grouped


def extract_records(
    conn: sqlite3.Connection,
    *,
    segment_id: str,
) -> tuple[list[ExtractedRecord], list[ExclusionReason]]:
    """Read-only extraction with identity/text validation applied inline.

    Never deserializes index_metadata.pickle or any HNSW binary file --
    this function only ever issues SELECTs against the sqlite tables
    (embeddings, embedding_metadata, embedding_metadata_array,
    embedding_fulltext_search_content), never touches the vector segment.
    """
    cur = conn.cursor()

    # Structural fail-closed check: this extractor has no support for
    # array-valued metadata (embedding_metadata_array). If any exists,
    # abort before extracting a single record, rather than silently
    # dropping or mis-encoding it.
    cur.execute("SELECT COUNT(*) FROM embedding_metadata_array")
    array_row_count = cur.fetchone()[0]
    if array_row_count:
        raise ExtractionError(
            f"embedding_metadata_array has {array_row_count} row(s); this "
            "extractor has no support for array-valued metadata and must "
            "not silently drop or mis-encode it. Aborting before any "
            "record is extracted -- this requires a separate, explicitly "
            "designed extension, not a guess."
        )

    cur.execute(
        "SELECT id, embedding_id FROM embeddings WHERE segment_id = ? ORDER BY id",
        (segment_id,),
    )
    embeddings_rows = cur.fetchall()

    cur.execute(
        """
        SELECT em.id, em.key, em.string_value, em.int_value, em.float_value, em.bool_value
        FROM embedding_metadata em
        JOIN embeddings e ON e.id = em.id
        WHERE e.segment_id = ?
        ORDER BY em.id, em.key
        """,
        (segment_id,),
    )
    metadata_by_id = _group_metadata(cur.fetchall())

    cur.execute("SELECT id, c0 FROM embedding_fulltext_search_content")
    fts_by_id = {row[0]: row[1] for row in cur.fetchall()}

    records: list[ExtractedRecord] = []
    exclusions: list[ExclusionReason] = []

    for row_id, embedding_id in embeddings_rows:
        raw_metadata = metadata_by_id.get(row_id, {})

        # --- text contract (Stage 6) ---
        text = raw_metadata.get(TEXT_METADATA_KEY)
        if text is None:
            exclusions.append(
                ExclusionReason(row_id, embedding_id, "missing chroma:document metadata (no text)")
            )
            continue
        fts_text = fts_by_id.get(row_id)
        if fts_text != text:
            exclusions.append(
                ExclusionReason(
                    row_id,
                    embedding_id,
                    "chroma:document does not exactly match "
                    "embedding_fulltext_search_content.c0 for this row",
                )
            )
            continue

        # --- identity contract (Stage 5) ---
        missing = [k for k in REQUIRED_IDENTITY_KEYS if k not in raw_metadata]
        if missing:
            exclusions.append(
                ExclusionReason(row_id, embedding_id, f"missing required identity metadata: {missing}")
            )
            continue
        chunk_id = raw_metadata["chunk_id"]
        if embedding_id != chunk_id:
            exclusions.append(
                ExclusionReason(
                    row_id,
                    embedding_id,
                    f"embedding_id != chunk_id metadata ({embedding_id!r} != {chunk_id!r})",
                )
            )
            continue

        metadata = {k: v for k, v in raw_metadata.items() if k not in EXCLUDED_METADATA_KEYS}
        records.append(
            ExtractedRecord(embedding_id=embedding_id, text=text, metadata=metadata, row_id=row_id)
        )

    return records, exclusions


def best_effort_source_filename_resolution(records: list[ExtractedRecord]) -> dict[str, Any]:
    """Informational-only check of which distinct source_filename values
    resolve to a current Postgres source_documents row, via the same
    resolver citation display already uses. Never affects extraction/write
    eligibility. Any failure to check is reported honestly, never silently
    skipped or treated as a hard error."""
    distinct_filenames = sorted(
        {r.metadata.get("source_filename") for r in records if r.metadata.get("source_filename")}
    )
    try:
        from app.services.document_storage import find_source_document_by_filename
    except Exception as exc:  # pragma: no cover - defensive import guard
        return {"checked": False, "reason": f"could not import resolver: {type(exc).__name__}: {exc}"}

    unresolved: list[str] = []
    try:
        for filename in distinct_filenames:
            row = find_source_document_by_filename(filename)
            if row is None:
                unresolved.append(filename)
    except Exception as exc:  # pragma: no cover - defensive
        return {"checked": False, "reason": f"resolution query failed: {type(exc).__name__}: {exc}"}

    return {
        "checked": True,
        "distinct_source_filenames": distinct_filenames,
        "unresolved_source_filenames": unresolved,
    }


# --- Deterministic digests ----------------------------------------------


def compute_records_digest(records: list[ExtractedRecord]) -> str:
    """Deterministic regardless of source row/dict iteration order: always
    sorted by embedding_id, then by metadata key, before hashing."""
    hasher = hashlib.sha256()
    for record in sorted(records, key=lambda r: r.embedding_id):
        hasher.update(record.embedding_id.encode("utf-8"))
        hasher.update(b"\x00")
        hasher.update(record.text.encode("utf-8"))
        hasher.update(b"\x00")
        for key in sorted(record.metadata):
            hasher.update(key.encode("utf-8"))
            hasher.update(b"=")
            hasher.update(repr(record.metadata[key]).encode("utf-8"))
            hasher.update(b"\x00")
        hasher.update(b"\x01")
    return hasher.hexdigest()


def compute_identity_digest(records: list[ExtractedRecord]) -> str:
    hasher = hashlib.sha256()
    for record in sorted(records, key=lambda r: r.embedding_id):
        tup = (
            record.embedding_id,
            record.metadata.get("document_id"),
            record.metadata.get("chunk_id"),
            record.metadata.get("chunk_index"),
        )
        hasher.update(repr(tup).encode("utf-8"))
        hasher.update(b"\x00")
    return hasher.hexdigest()


# --- Vector regeneration (production embedding function, document path) -----


def regenerate_embeddings(
    records: list[ExtractedRecord],
    *,
    embed_documents: Callable[[list[str]], list[list[float]]],
    batch_size: int = 32,
    expected_dimensionality: int = EXPECTED_DIMENSIONALITY,
) -> tuple[list[EmbeddedRecord], list[ExclusionReason]]:
    """Regenerates vectors via ``embed_documents`` -- the production
    embedding function's document/passage path (``__call__``), never
    ``embed_query``. This function never adds a "passage: " prefix itself;
    the real embedding function is responsible for its own prefixing, so
    reusing it here (rather than reimplementing it) is what guarantees the
    same prefixing/normalization/model actually runs.

    A whole-batch exception is fatal (stops the run, per design). A single
    record's invalid vector (wrong dimension, non-finite values) excludes
    only that record and lets the rest of the batch continue.
    """
    embedded: list[EmbeddedRecord] = []
    exclusions: list[ExclusionReason] = []

    for start in range(0, len(records), batch_size):
        batch = records[start : start + batch_size]
        texts = [r.text for r in batch]
        try:
            vectors = embed_documents(texts)
        except Exception as exc:
            raise EmbeddingBatchError(
                f"embedding batch starting at record index {start} (size {len(batch)}) "
                f"failed: {type(exc).__name__}: {exc}"
            ) from exc

        if len(vectors) != len(batch):
            raise EmbeddingBatchError(
                f"embedding function returned {len(vectors)} vector(s) for a batch of "
                f"{len(batch)} text(s) (starting at record index {start})"
            )

        for record, vector in zip(batch, vectors):
            vector = list(vector)
            if len(vector) != expected_dimensionality:
                exclusions.append(
                    ExclusionReason(
                        record.row_id,
                        record.embedding_id,
                        f"vector dimension {len(vector)} != expected {expected_dimensionality}",
                    )
                )
                continue
            if not all(math.isfinite(v) for v in vector):
                exclusions.append(
                    ExclusionReason(
                        record.row_id,
                        record.embedding_id,
                        "vector contains non-finite value(s) (NaN/Inf)",
                    )
                )
                continue
            embedded.append(
                EmbeddedRecord(
                    embedding_id=record.embedding_id,
                    text=record.text,
                    metadata=record.metadata,
                    vector=vector,
                )
            )

    return embedded, exclusions


# --- Destination write --------------------------------------------------


def create_destination_client_and_collection(
    dest_path: Path,
    collection_name: str,
    embedding_function: Any,
) -> tuple[Any, Any]:
    """Creates a brand-new PersistentClient/collection at ``dest_path``.

    Uses ``create_collection`` (never ``get_or_create_collection``) so
    recovery can never silently attach to a pre-existing collection.
    Mirrors production's own collection-creation parameters exactly (see
    app.services.chroma_store.KnowledgeBaseStore.__init__).
    """
    import chromadb
    from chromadb.config import Settings as ChromaSettings

    dest_path.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(
        path=str(dest_path),
        settings=ChromaSettings(anonymized_telemetry=False),
    )
    collection = client.create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
        embedding_function=embedding_function,
    )
    return client, collection


def write_records(collection: Any, embedded_records: list[EmbeddedRecord], *, batch_size: int = 100) -> None:
    """Writes with explicit precomputed ``embeddings=`` so Chroma never
    invokes the embedding function a second time for this insert -- the
    vectors already computed by ``regenerate_embeddings`` are the only
    ones that ever reach the new store."""
    for start in range(0, len(embedded_records), batch_size):
        batch = embedded_records[start : start + batch_size]
        if not batch:
            continue
        collection.add(
            ids=[r.embedding_id for r in batch],
            documents=[r.text for r in batch],
            metadatas=[r.metadata for r in batch],
            embeddings=[r.vector for r in batch],
        )


# --- git / reproducibility helpers -------------------------------------------


def _run_git(*args: str) -> tuple[str | None, str | None]:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=BACKEND_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"git command failed to run: {type(exc).__name__}: {exc}"
    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        return None, f"git exited {completed.returncode}: {stderr or 'no stderr output'}"
    return completed.stdout.strip(), None


def _git_info() -> dict[str, Any]:
    info: dict[str, Any] = {}
    sha, sha_error = _run_git("rev-parse", "HEAD")
    info["git_head_sha"] = sha
    if sha_error:
        info["git_head_sha_error"] = sha_error
    porcelain, status_error = _run_git("status", "--porcelain")
    if status_error:
        info["git_dirty"] = None
        info["git_dirty_error"] = status_error
    else:
        info["git_dirty"] = bool(porcelain)
    return info


# --- Orchestration: recovery run ---------------------------------------------


def run_recovery(
    *,
    source_dir: Path,
    source_collection: str,
    dest_dir: Path,
    dest_collection: str,
    execute: bool,
    embed_documents: Callable[[list[str]], list[list[float]]] | None = None,
    embedding_function_for_write: Any = None,
    embedding_model_name: str = "",
    embedding_function_name: str = "",
    embedding_function_config: dict[str, Any] | None = None,
    dimensionality: int = EXPECTED_DIMENSIONALITY,
    batch_size: int = 32,
) -> dict[str, Any]:
    """Runs extraction + validation, and (only when ``execute=True``)
    vector regeneration + write into a brand-new store at ``dest_dir``.

    In dry-run mode (``execute=False``), the embedding model is never
    loaded and nothing is written -- only the cheap, local SQLite-only
    extraction/validation steps run, plus a destination-safety pre-check.
    """
    validate_destination_safety(source_dir, dest_dir)

    sqlite_path = source_dir / "chroma.sqlite3"
    if not sqlite_path.exists():
        raise ExtractionError(f"source sqlite file not found: {sqlite_path}")

    source_sha_before = sha256_of_file(sqlite_path)

    conn = open_source_readonly(sqlite_path)
    try:
        segment_id = discover_metadata_segment_id(conn, source_collection)
        records, extraction_exclusions = extract_records(conn, segment_id=segment_id)
    finally:
        conn.close()

    orphan_faq_ids = sorted(r.embedding_id for r in records if r.embedding_id.startswith("faq:"))
    source_filename_check = best_effort_source_filename_resolution(records)
    records_digest = compute_records_digest(records)
    identity_digest = compute_identity_digest(records)

    embed_exclusions: list[ExclusionReason] = []
    embedded_records: list[EmbeddedRecord] = []
    embedding_regeneration_status = "skipped_dry_run"

    if execute:
        if embed_documents is None or embedding_function_for_write is None:
            raise ExtractionError(
                "execute=True requires both embed_documents and "
                "embedding_function_for_write to be supplied"
            )
        embedded_records, embed_exclusions = regenerate_embeddings(
            records,
            embed_documents=embed_documents,
            batch_size=batch_size,
            expected_dimensionality=dimensionality,
        )
        embedding_regeneration_status = "completed"

    all_exclusions = extraction_exclusions + embed_exclusions
    excluded_ids = {e.embedding_id for e in all_exclusions if e.embedding_id}
    embedded_records = [r for r in embedded_records if r.embedding_id not in excluded_ids]

    wrote_count = 0
    if execute:
        client, collection = create_destination_client_and_collection(
            dest_dir, dest_collection, embedding_function_for_write
        )
        write_records(collection, embedded_records)
        wrote_count = len(embedded_records)

    # Diagnostic only, never used to gate any logic below: a direct
    # filesystem check (not merely "execute was True") of whether a
    # destination was actually created, so a dry-run manifest reader never
    # has to infer "nothing was created" from regeneration_status alone.
    destination_created = (dest_dir / "chroma.sqlite3").exists()

    source_sha_after = sha256_of_file(sqlite_path)
    source_immutable = source_sha_after == source_sha_before

    status = "complete" if execute and not all_exclusions and wrote_count == len(records) else (
        "dry_run_ok" if not execute and not extraction_exclusions else "incomplete"
    )
    if not source_immutable:
        status = "invalid_source_mutated"

    manifest: dict[str, Any] = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "recovery_tool": RECOVERY_TOOL_IDENTIFIER,
        "recovery_tool_version": RECOVERY_TOOL_VERSION,
        "mode": "execute" if execute else "dry_run",
        **_git_info(),
        "source": {
            "path": str(source_dir),
            "collection_name": source_collection,
            "sqlite_sha256_before": source_sha_before,
            "sqlite_sha256_after": source_sha_after,
            "sqlite_immutable": source_immutable,
            "record_count_found": len(records) + len(extraction_exclusions),
            "record_count_passed_extraction": len(records),
            "metadata_text_digest": records_digest,
            "identity_digest": identity_digest,
            "excluded_metadata_keys": sorted(EXCLUDED_METADATA_KEYS),
            "excluded_metadata_keys_reason": (
                "chroma:document is Chroma's own internal document-text "
                "bookkeeping key, not real ASKa-Piyu content metadata; it is "
                "pulled out as record text (documents=) and never written "
                "back as a literal metadata key."
            ),
        },
        "destination": {
            "path": str(dest_dir),
            "collection_name": dest_collection,
            # Diagnostic only (see destination_created's own computation
            # above) -- never read back by this tool to decide anything;
            # exists purely so a manifest reader does not have to infer
            # "nothing was created" from regeneration_status alone.
            "destination_created": destination_created,
        },
        "embedding": {
            "model_name": embedding_model_name,
            "function_name": embedding_function_name,
            "function_config": embedding_function_config or {},
            "dimensionality": dimensionality,
            "regeneration_status": embedding_regeneration_status,
        },
        "results": {
            "recovered_record_count": wrote_count,
            "excluded_record_count": len(all_exclusions),
            "excluded_records": [e.as_dict() for e in all_exclusions],
            "identity_digest": identity_digest,
            "metadata_text_digest": records_digest,
            "status": status,
        },
        "informational": {
            "orphan_faq_record_ids": orphan_faq_ids,
            "orphan_faq_record_count": len(orphan_faq_ids),
            "source_filename_resolution": source_filename_check,
        },
    }
    return manifest


# --- Validation mode (subprocess-isolated count/query checks) ---------------


_ISOLATED_COUNT_SCRIPT = """
import sys, json
import chromadb
from chromadb.config import Settings as ChromaSettings

dest = sys.argv[1]
collection_name = sys.argv[2]
try:
    client = chromadb.PersistentClient(path=dest, settings=ChromaSettings(anonymized_telemetry=False))
    col = client.get_collection(name=collection_name)
    n = col.count()
    print(json.dumps({"ok": True, "count": n}))
except Exception as exc:
    print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}))
    raise
"""

_ISOLATED_QUERY_SCRIPT = """
import sys, json
import chromadb
from chromadb.config import Settings as ChromaSettings

dest = sys.argv[1]
collection_name = sys.argv[2]
dim = int(sys.argv[3])
try:
    client = chromadb.PersistentClient(path=dest, settings=ChromaSettings(anonymized_telemetry=False))
    col = client.get_collection(name=collection_name)
    # A fixed dummy query_embeddings vector is used deliberately: this
    # checks the native query() path's stability, not embedding-function
    # correctness (already covered separately at regeneration time), and
    # avoids loading the sentence-transformer model in this subprocess.
    res = col.query(query_embeddings=[[0.0] * dim], n_results=1)
    returned = len(res.get("ids", [[]])[0]) if res.get("ids") else 0
    print(json.dumps({"ok": True, "returned": returned}))
except Exception as exc:
    print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}))
    raise
"""


def _run_isolated_python(script: str, args: list[str], *, timeout: float = 120.0) -> dict[str, Any]:
    """Runs ``script`` in a brand-new ``python -c`` subprocess -- never in
    this process. A native crash in the subprocess (segfault) is reported
    via its exit code, never propagated into this process."""
    try:
        completed = subprocess.run(
            [sys.executable, "-c", script, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.SubprocessError as exc:
        return {"ok": False, "exit_code": None, "error": f"{type(exc).__name__}: {exc}"}

    result: dict[str, Any] = {
        "exit_code": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }
    if completed.returncode == 0 and completed.stdout.strip():
        try:
            parsed = json.loads(completed.stdout.strip().splitlines()[-1])
            result.update(parsed)
        except (json.JSONDecodeError, IndexError):
            result["ok"] = False
            result["error"] = "isolated subprocess did not print valid JSON"
    else:
        result.setdefault("ok", False)
        if "error" not in result:
            result["error"] = f"isolated subprocess exited {completed.returncode}"
    return result


def validate_recovered_store(
    dest_dir: Path,
    dest_collection: str,
    *,
    expected_manifest: dict[str, Any] | None = None,
    dimensionality: int = EXPECTED_DIMENSIONALITY,
) -> dict[str, Any]:
    """Validates an already-recovered destination store.

    Never points at the broken source store -- callers must never pass
    the configured production ``chroma_persist_dir`` here; this function
    does not itself know or check what that path is (the CLI layer's
    --validate flag is a distinct, separate code path from --execute's
    destination-safety checks, by design, so validation can be re-run
    later against a recovered store on its own).
    """
    checks: dict[str, Any] = {}

    sqlite_path = dest_dir / "chroma.sqlite3"
    if not sqlite_path.exists():
        return {"status": "failed", "reason": f"destination sqlite file not found: {sqlite_path}"}

    # 1) Isolated count() check, TWICE, in independent fresh subprocesses.
    count_run_1 = _run_isolated_python(
        _ISOLATED_COUNT_SCRIPT, [str(dest_dir), dest_collection]
    )
    count_run_2 = _run_isolated_python(
        _ISOLATED_COUNT_SCRIPT, [str(dest_dir), dest_collection]
    )
    checks["count_run_1"] = count_run_1
    checks["count_run_2"] = count_run_2
    counts_ok = (
        count_run_1.get("ok") is True
        and count_run_2.get("ok") is True
        and count_run_1.get("count") == count_run_2.get("count")
    )
    checks["count_stable_across_isolated_runs"] = counts_ok

    # 2) Isolated query() check.
    query_run = _run_isolated_python(
        _ISOLATED_QUERY_SCRIPT, [str(dest_dir), dest_collection, str(dimensionality)]
    )
    checks["query_run"] = query_run
    checks["query_ok"] = query_run.get("ok") is True

    # 3) Raw-SQLite self-consistency checks (never via chromadb) -- these
    # run regardless of whether a manifest was supplied: duplicate/missing
    # id detection is a property of the destination alone, not something
    # that requires a prior manifest to compare against.
    conn = open_source_readonly(sqlite_path)
    try:
        segment_id = discover_metadata_segment_id(conn, dest_collection)
        records, exclusions = extract_records(conn, segment_id=segment_id)
    finally:
        conn.close()

    actual_ids = {r.embedding_id for r in records}
    duplicate_ids = len(actual_ids) != len(records)
    reconciliation: dict[str, Any] = {
        "checked": True,
        "destination_record_count": len(records),
        "destination_exclusion_count": len(exclusions),
        "no_duplicate_ids": not duplicate_ids,
        "no_unexpected_exclusions_in_destination": len(exclusions) == 0,
        "compared_against_manifest": False,
    }

    # 4) Manifest-comparison fields -- only added when a manifest was
    # actually supplied to compare against.
    if expected_manifest is not None:
        reconciliation.update(
            {
                "compared_against_manifest": True,
                "expected_recovered_record_count": expected_manifest.get("results", {}).get(
                    "recovered_record_count"
                ),
                "record_count_matches": len(records)
                == expected_manifest.get("results", {}).get("recovered_record_count"),
                "identity_digest_matches": compute_identity_digest(records)
                == expected_manifest.get("results", {}).get("identity_digest"),
                "metadata_text_digest_matches": compute_records_digest(records)
                == expected_manifest.get("results", {}).get("metadata_text_digest"),
            }
        )
    checks["reconciliation"] = reconciliation

    self_consistency_ok = reconciliation["no_duplicate_ids"] and reconciliation[
        "no_unexpected_exclusions_in_destination"
    ]
    manifest_comparison_ok = not expected_manifest or all(
        reconciliation[k]
        for k in ("record_count_matches", "identity_digest_matches", "metadata_text_digest_matches")
    )

    overall_ok = counts_ok and checks["query_ok"] and self_consistency_ok and manifest_comparison_ok

    return {
        "status": "ok" if overall_ok else "failed",
        "validated_at": datetime.now(timezone.utc).isoformat(),
        "destination": {"path": str(dest_dir), "collection_name": dest_collection},
        "checks": checks,
    }


# --- CLI ----------------------------------------------------------------


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


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--execute", action="store_true",
        help="Actually regenerate vectors and write the recovered store (requires --dest).",
    )
    parser.add_argument(
        "--dest", type=Path, default=None,
        help="Explicit NEW destination directory for the recovered store. Required with --execute.",
    )
    parser.add_argument(
        "--dest-collection", type=str, default=None,
        help="Destination collection name (default: <source-collection>_recovered_<UTC timestamp>).",
    )
    parser.add_argument(
        "--validate", type=Path, default=None,
        help="Validate an already-recovered destination instead of running extraction/recovery.",
    )
    parser.add_argument(
        "--validate-collection", type=str, default=None,
        help="Collection name to validate. Required with --validate.",
    )
    parser.add_argument(
        "--validate-manifest", type=Path, default=None,
        help="Optional manifest JSON (from a prior --execute run) to reconcile --validate against.",
    )
    parser.add_argument(
        "--source-dir", type=Path, default=None,
        help="Override source Chroma persistence directory (default: settings.chroma_persist_dir).",
    )
    parser.add_argument(
        "--source-collection", type=str, default=None,
        help="Override source collection name (default: settings.chroma_collection_name).",
    )
    parser.add_argument("--out", type=Path, default=None, help="Where to write the manifest/validation JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)

    if args.validate is not None:
        if not args.validate_collection:
            print("ERROR: --validate requires --validate-collection", file=sys.stderr)
            return 2
        expected_manifest = None
        if args.validate_manifest is not None:
            expected_manifest = json.loads(args.validate_manifest.read_text(encoding="utf-8"))
        result = validate_recovered_store(
            args.validate, args.validate_collection, expected_manifest=expected_manifest
        )
        out_path = args.out or (args.validate.parent / "chroma_recovery_validation.json")
        _write_json(out_path, result)
        print(json.dumps(result, indent=2, default=str))
        print(f"Wrote {out_path}")
        return 0 if result.get("status") == "ok" else 1

    if args.execute and not args.dest:
        print("ERROR: --execute requires --dest", file=sys.stderr)
        return 2

    source_dir = args.source_dir or _default_source_persist_dir()
    source_collection = args.source_collection or _default_source_collection_name()

    embed_documents = None
    embedding_function_for_write = None
    embedding_model_name = ""
    embedding_function_name = ""
    embedding_function_config: dict[str, Any] = {}
    dest_dir = args.dest
    dest_collection = args.dest_collection

    if args.execute:
        from app.services.embeddings import get_embedding_function

        real_embed_fn = get_embedding_function()
        embed_documents = real_embed_fn  # __call__ == document/passage path
        embedding_function_for_write = real_embed_fn
        embedding_function_config = real_embed_fn.get_config()
        embedding_model_name = embedding_function_config.get("model_name", "")
        embedding_function_name = real_embed_fn.name()
        dest_collection = dest_collection or f"{source_collection}_recovered_{_timestamp_slug()}"
    else:
        # Deliberately NOT under backend/data/ (where the real Chroma store
        # lives) -- dry-run never writes here (execute=False), but the
        # default preview path is still kept well away from the real
        # persistence directory as an extra margin of safety, not just a
        # reliance on the destination-safety sibling-directory check.
        dest_dir = dest_dir or (
            BACKEND_ROOT / "benchmarks" / "results" / f"chroma_recovery_dryrun_preview_{_timestamp_slug()}"
        )
        dest_collection = dest_collection or f"{source_collection}_recovered_preview"

    manifest = run_recovery(
        source_dir=source_dir,
        source_collection=source_collection,
        dest_dir=dest_dir,
        dest_collection=dest_collection,
        execute=args.execute,
        embed_documents=embed_documents,
        embedding_function_for_write=embedding_function_for_write,
        embedding_model_name=embedding_model_name,
        embedding_function_name=embedding_function_name,
        embedding_function_config=embedding_function_config,
    )

    out_path = args.out or (
        BACKEND_ROOT / "benchmarks" / "results" / f"chroma_recovery_manifest_{_timestamp_slug()}.json"
    )
    _write_json(out_path, manifest)
    print(json.dumps(manifest, indent=2, default=str))
    print(f"Wrote {out_path}")
    return 0 if manifest["results"]["status"] in ("complete", "dry_run_ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
