"""Tests for the Strategy B Chroma recovery tool
(``scripts/chroma_sqlite_recovery.py``).

CRITICAL: every test in this file builds and destroys its own SYNTHETIC
SQLite/Chroma data under ``tmp_path``. No test in this file may open, read,
or reference ``backend/data/chroma`` (the real, currently-broken store) --
there is no fixture, constant, or code path here that points at it. Real
chromadb IS exercised in several tests (writing to/reading from temp
directories only), which is safe and necessary to prove the tool's
subprocess-isolated count()/query() checks and the destination-write path
actually work against the real library, not just against mocks.
"""

from __future__ import annotations

import json
import math
import sqlite3
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.chroma_sqlite_recovery import (
    EmbeddingBatchError,
    ExclusionReason,
    ExtractedRecord,
    ExtractionError,
    RecoverySafetyError,
    best_effort_source_filename_resolution,
    compute_identity_digest,
    compute_records_digest,
    discover_metadata_segment_id,
    extract_records,
    main,
    open_source_readonly,
    regenerate_embeddings,
    run_recovery,
    validate_destination_safety,
    validate_recovered_store,
)

EXPECTED_DIM = 384


# ---------------------------------------------------------------------------
# Synthetic source-store builder -- the only way any test in this file
# produces sqlite data; never reads a real chroma.sqlite3.
# ---------------------------------------------------------------------------


def build_synthetic_source(
    db_path: Path,
    *,
    collection_name: str = "test_kb",
    dimension: int = EXPECTED_DIM,
    records: list[dict] | None = None,
    include_array_metadata_row: bool = False,
    two_metadata_segments: bool = False,
) -> None:
    """Builds a minimal, schema-faithful synthetic ``chroma.sqlite3``.

    ``records`` is a list of dicts, each optionally overriding:
    ``chunk_id`` (defaults to ``f"doc-A::{index}"``), ``embedding_id``
    (defaults to the same value as chunk_id -- pass a different value to
    exercise the identity-mismatch fail-closed path), ``document_id``,
    ``chunk_index``, ``text``, ``fts_text`` (defaults to ``text`` -- pass a
    different value to exercise the text-mismatch fail-closed path),
    ``extra_metadata`` (dict of additional string/int/float/bool metadata),
    ``omit_keys`` (list of required-identity keys to leave out).
    """
    records = records if records is not None else [{}]
    con = sqlite3.connect(str(db_path))
    cur = con.cursor()
    cur.executescript(
        """
        CREATE TABLE collections (id TEXT PRIMARY KEY, name TEXT, dimension INTEGER, database_id TEXT);
        CREATE TABLE segments (id TEXT PRIMARY KEY, type TEXT, scope TEXT, collection TEXT);
        CREATE TABLE embeddings (
            id INTEGER PRIMARY KEY, segment_id TEXT NOT NULL, embedding_id TEXT NOT NULL,
            seq_id BLOB, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE embedding_metadata (
            id INTEGER, key TEXT NOT NULL, string_value TEXT, int_value INTEGER,
            float_value REAL, bool_value INTEGER
        );
        CREATE TABLE embedding_metadata_array (
            id INTEGER, key TEXT, string_value TEXT, int_value INTEGER, float_value REAL, bool_value INTEGER
        );
        CREATE TABLE embedding_fulltext_search_content (id INTEGER PRIMARY KEY, c0 TEXT);
        """
    )
    coll_id = "coll-1"
    seg_id = "seg-meta-1"
    cur.execute("INSERT INTO collections VALUES (?,?,?,?)", (coll_id, collection_name, dimension, "db-1"))
    cur.execute(
        "INSERT INTO segments VALUES (?,?,?,?)",
        (seg_id, "urn:chroma:segment/metadata/sqlite", "METADATA", coll_id),
    )
    if two_metadata_segments:
        cur.execute(
            "INSERT INTO segments VALUES (?,?,?,?)",
            ("seg-meta-2", "urn:chroma:segment/metadata/sqlite", "METADATA", coll_id),
        )

    for index, spec in enumerate(records):
        row_id = index + 1
        document_id = spec.get("document_id", "doc-A")
        chunk_index = spec.get("chunk_index", index)
        chunk_id = spec.get("chunk_id", f"{document_id}::{chunk_index}")
        embedding_id = spec.get("embedding_id", chunk_id)
        text = spec.get("text", f"This is chunk number {index} of the synthetic document.")
        fts_text = spec.get("fts_text", text)
        omit_keys = set(spec.get("omit_keys", []))

        cur.execute(
            "INSERT INTO embeddings (id, segment_id, embedding_id) VALUES (?,?,?)",
            (row_id, seg_id, embedding_id),
        )
        cur.execute(
            "INSERT INTO embedding_fulltext_search_content (id, c0) VALUES (?,?)", (row_id, fts_text)
        )

        meta: dict = {"chroma:document": text}
        if "document_id" not in omit_keys:
            meta["document_id"] = document_id
        if "chunk_id" not in omit_keys:
            meta["chunk_id"] = chunk_id
        if "chunk_index" not in omit_keys:
            meta["chunk_index"] = chunk_index
        meta.update(spec.get("extra_metadata", {}))

        for key, value in meta.items():
            if isinstance(value, bool):
                cur.execute(
                    "INSERT INTO embedding_metadata (id,key,bool_value) VALUES (?,?,?)",
                    (row_id, key, int(value)),
                )
            elif isinstance(value, int):
                cur.execute(
                    "INSERT INTO embedding_metadata (id,key,int_value) VALUES (?,?,?)", (row_id, key, value)
                )
            elif isinstance(value, float):
                cur.execute(
                    "INSERT INTO embedding_metadata (id,key,float_value) VALUES (?,?,?)",
                    (row_id, key, value),
                )
            else:
                cur.execute(
                    "INSERT INTO embedding_metadata (id,key,string_value) VALUES (?,?,?)",
                    (row_id, key, value),
                )

    if include_array_metadata_row:
        cur.execute(
            "INSERT INTO embedding_metadata_array (id,key,string_value) VALUES (?,?,?)",
            (1, "campuses", "main"),
        )

    con.commit()
    con.close()


class FakeEmbeddingFunction:
    """Chroma-compatible fake: no model loading, deterministic small vectors."""

    def __init__(self, dimension: int = EXPECTED_DIM) -> None:
        self.dimension = dimension
        self.calls: list[list[str]] = []

    def __call__(self, input: list[str]) -> list[list[float]]:
        self.calls.append(list(input))
        return [[0.1] * self.dimension for _ in input]

    def name(self) -> str:
        return "fake_test_embedding"

    def get_config(self) -> dict:
        return {"model_name": "fake-model", "device": "cpu"}

    def is_legacy(self) -> bool:
        return False


# ---------------------------------------------------------------------------
# Identity preservation / text preservation / metadata preservation
# ---------------------------------------------------------------------------


def test_identity_preserved_exactly(tmp_path: Path):
    db_path = tmp_path / "chroma.sqlite3"
    build_synthetic_source(
        db_path,
        records=[{"document_id": "doc-X", "chunk_index": 7, "chunk_id": "doc-X::7"}],
    )
    conn = open_source_readonly(db_path)
    try:
        seg = discover_metadata_segment_id(conn, "test_kb")
        records, exclusions = extract_records(conn, segment_id=seg)
    finally:
        conn.close()

    assert exclusions == []
    assert len(records) == 1
    record = records[0]
    assert record.embedding_id == "doc-X::7"
    assert record.metadata["document_id"] == "doc-X"
    assert record.metadata["chunk_id"] == "doc-X::7"
    assert record.metadata["chunk_index"] == 7


def test_exact_text_preserved_verbatim(tmp_path: Path):
    db_path = tmp_path / "chroma.sqlite3"
    exact_text = "Exact text with\nnewlines, trailing spaces   , and \"quotes\"."
    build_synthetic_source(db_path, records=[{"text": exact_text, "fts_text": exact_text}])
    conn = open_source_readonly(db_path)
    try:
        seg = discover_metadata_segment_id(conn, "test_kb")
        records, exclusions = extract_records(conn, segment_id=seg)
    finally:
        conn.close()

    assert exclusions == []
    assert records[0].text == exact_text
    # chroma:document must never appear as a literal metadata key.
    assert "chroma:document" not in records[0].metadata


def test_fts_mismatch_fails_closed(tmp_path: Path):
    db_path = tmp_path / "chroma.sqlite3"
    build_synthetic_source(
        db_path,
        records=[
            {"chunk_index": 0, "text": "same text", "fts_text": "same text"},
            {"chunk_index": 1, "text": "original", "fts_text": "CORRUPTED / DIFFERENT"},
        ],
    )
    conn = open_source_readonly(db_path)
    try:
        seg = discover_metadata_segment_id(conn, "test_kb")
        records, exclusions = extract_records(conn, segment_id=seg)
    finally:
        conn.close()

    assert len(records) == 1
    assert records[0].metadata["chunk_index"] == 0
    assert len(exclusions) == 1
    assert "does not exactly match" in exclusions[0].reason


def test_string_int_float_bool_metadata_preserved_with_native_types(tmp_path: Path):
    db_path = tmp_path / "chroma.sqlite3"
    build_synthetic_source(
        db_path,
        records=[
            {
                "extra_metadata": {
                    "title": "A String Title",
                    "page": 42,
                    "classification_confidence": 0.875,
                    "toc_origin": True,
                    "another_bool_false": False,
                    "chunk_index_like_zero_field": 0,
                }
            }
        ],
    )
    conn = open_source_readonly(db_path)
    try:
        seg = discover_metadata_segment_id(conn, "test_kb")
        records, exclusions = extract_records(conn, segment_id=seg)
    finally:
        conn.close()

    assert exclusions == []
    metadata = records[0].metadata
    assert metadata["title"] == "A String Title" and isinstance(metadata["title"], str)
    assert metadata["page"] == 42 and isinstance(metadata["page"], int)
    assert metadata["classification_confidence"] == pytest.approx(0.875) and isinstance(
        metadata["classification_confidence"], float
    )
    assert metadata["toc_origin"] is True
    assert metadata["another_bool_false"] is False
    # A legitimate 0 value must survive -- never treated as "missing".
    assert metadata["chunk_index_like_zero_field"] == 0


def test_audience_preserved_including_missing(tmp_path: Path):
    db_path = tmp_path / "chroma.sqlite3"
    build_synthetic_source(
        db_path,
        records=[
            {"chunk_index": 0, "extra_metadata": {"audience": "faculty"}},
            {"chunk_index": 1, "extra_metadata": {}},  # no audience key at all
        ],
    )
    conn = open_source_readonly(db_path)
    try:
        seg = discover_metadata_segment_id(conn, "test_kb")
        records, exclusions = extract_records(conn, segment_id=seg)
    finally:
        conn.close()

    assert exclusions == []
    by_index = {r.metadata["chunk_index"]: r for r in records}
    assert by_index[0].metadata["audience"] == "faculty"
    assert "audience" not in by_index[1].metadata  # never defaulted/synthesized


# ---------------------------------------------------------------------------
# Identity fail-closed cases
# ---------------------------------------------------------------------------


def test_missing_identity_fails_closed_never_synthesizes(tmp_path: Path):
    db_path = tmp_path / "chroma.sqlite3"
    build_synthetic_source(
        db_path,
        records=[
            {"chunk_index": 0},
            {"chunk_index": 1, "omit_keys": ["chunk_id"]},
            {"chunk_index": 2, "omit_keys": ["document_id"]},
        ],
    )
    conn = open_source_readonly(db_path)
    try:
        seg = discover_metadata_segment_id(conn, "test_kb")
        records, exclusions = extract_records(conn, segment_id=seg)
    finally:
        conn.close()

    assert len(records) == 1
    assert records[0].metadata["chunk_index"] == 0
    assert len(exclusions) == 2
    reasons = {e.reason for e in exclusions}
    assert any("chunk_id" in r for r in reasons)
    assert any("document_id" in r for r in reasons)
    # No excluded record's id was ever fabricated into the passing set.
    passing_ids = {r.embedding_id for r in records}
    assert "doc-A::1" not in passing_ids
    assert "doc-A::2" not in passing_ids


def test_embedding_id_chunk_id_mismatch_fails_closed(tmp_path: Path):
    db_path = tmp_path / "chroma.sqlite3"
    build_synthetic_source(
        db_path,
        records=[
            {"chunk_index": 0, "chunk_id": "doc-A::0", "embedding_id": "SOMETHING-ELSE"},
            {"chunk_index": 1},
        ],
    )
    conn = open_source_readonly(db_path)
    try:
        seg = discover_metadata_segment_id(conn, "test_kb")
        records, exclusions = extract_records(conn, segment_id=seg)
    finally:
        conn.close()

    assert len(records) == 1
    assert records[0].metadata["chunk_index"] == 1
    assert len(exclusions) == 1
    assert "embedding_id != chunk_id" in exclusions[0].reason


def test_array_metadata_present_fails_closed_whole_run(tmp_path: Path):
    db_path = tmp_path / "chroma.sqlite3"
    build_synthetic_source(
        db_path,
        records=[{"chunk_index": 0}, {"chunk_index": 1}],
        include_array_metadata_row=True,
    )
    conn = open_source_readonly(db_path)
    try:
        seg = discover_metadata_segment_id(conn, "test_kb")
        with pytest.raises(ExtractionError, match="embedding_metadata_array"):
            extract_records(conn, segment_id=seg)
    finally:
        conn.close()


def test_multiple_metadata_segments_is_a_structural_error(tmp_path: Path):
    db_path = tmp_path / "chroma.sqlite3"
    build_synthetic_source(db_path, records=[{}], two_metadata_segments=True)
    conn = open_source_readonly(db_path)
    try:
        with pytest.raises(ExtractionError, match="multiple METADATA segments"):
            discover_metadata_segment_id(conn, "test_kb")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Destination safety
# ---------------------------------------------------------------------------


def test_destination_equals_source_refused(tmp_path: Path):
    source = tmp_path / "data" / "chroma"
    source.mkdir(parents=True)
    with pytest.raises(RecoverySafetyError, match="equals source"):
        validate_destination_safety(source, source)


def test_destination_inside_source_refused(tmp_path: Path):
    source = tmp_path / "data" / "chroma"
    source.mkdir(parents=True)
    with pytest.raises(RecoverySafetyError, match="inside the source"):
        validate_destination_safety(source, source / "nested")


def test_source_inside_destination_refused(tmp_path: Path):
    source = tmp_path / "data" / "chroma"
    source.mkdir(parents=True)
    with pytest.raises(RecoverySafetyError, match="inside the destination"):
        validate_destination_safety(source, tmp_path)


def test_nonempty_destination_refused(tmp_path: Path):
    source = tmp_path / "data" / "chroma"
    source.mkdir(parents=True)
    dest = tmp_path / "occupied"
    dest.mkdir()
    (dest / "file.txt").write_text("existing content")
    with pytest.raises(RecoverySafetyError, match="non-empty"):
        validate_destination_safety(source, dest)


def test_destination_as_existing_file_refused(tmp_path: Path):
    source = tmp_path / "data" / "chroma"
    source.mkdir(parents=True)
    dest = tmp_path / "occupied_file"
    dest.write_text("I am a file, not a directory")
    with pytest.raises(RecoverySafetyError, match="already exists as a file"):
        validate_destination_safety(source, dest)


def test_new_and_empty_destinations_allowed(tmp_path: Path):
    source = tmp_path / "data" / "chroma"
    source.mkdir(parents=True)
    empty_existing = tmp_path / "empty_dest"
    empty_existing.mkdir()
    validate_destination_safety(source, empty_existing)  # must not raise
    validate_destination_safety(source, tmp_path / "brand_new_path")  # must not raise


# ---------------------------------------------------------------------------
# Vector validation
# ---------------------------------------------------------------------------


def _records_for_vector_tests() -> list[ExtractedRecord]:
    return [
        ExtractedRecord(
            embedding_id="a::0", text="hello",
            metadata={"document_id": "a", "chunk_id": "a::0", "chunk_index": 0}, row_id=1,
        ),
        ExtractedRecord(
            embedding_id="a::1", text="world",
            metadata={"document_id": "a", "chunk_id": "a::1", "chunk_index": 1}, row_id=2,
        ),
    ]


def test_vector_wrong_dimension_rejected():
    records = _records_for_vector_tests()

    def embed(texts):
        return [[0.1] * 383 if t == "world" else [0.1] * 384 for t in texts]

    embedded, exclusions = regenerate_embeddings(records, embed_documents=embed, batch_size=10)
    assert [r.embedding_id for r in embedded] == ["a::0"]
    assert len(exclusions) == 1
    assert exclusions[0].embedding_id == "a::1"
    assert "dimension" in exclusions[0].reason


def test_vector_nan_rejected():
    records = _records_for_vector_tests()

    def embed(texts):
        return [[float("nan")] * 384 if t == "hello" else [0.1] * 384 for t in texts]

    embedded, exclusions = regenerate_embeddings(records, embed_documents=embed, batch_size=10)
    assert [r.embedding_id for r in embedded] == ["a::1"]
    assert len(exclusions) == 1
    assert "non-finite" in exclusions[0].reason


def test_vector_inf_rejected():
    records = _records_for_vector_tests()

    def embed(texts):
        return [[float("inf")] + [0.1] * 383 if t == "hello" else [0.1] * 384 for t in texts]

    embedded, exclusions = regenerate_embeddings(records, embed_documents=embed, batch_size=10)
    assert [r.embedding_id for r in embedded] == ["a::1"]
    assert len(exclusions) == 1
    assert "non-finite" in exclusions[0].reason


def test_batch_level_exception_stops_execution_safely():
    records = _records_for_vector_tests()

    def crashing_embed(texts):
        raise RuntimeError("simulated embedding model crash")

    with pytest.raises(EmbeddingBatchError, match="simulated embedding model crash"):
        regenerate_embeddings(records, embed_documents=crashing_embed, batch_size=10)


def test_embed_documents_path_used_not_embed_query():
    """Stage 6 item 15: proves the recovery code calls the document
    embedding interface (a plain call, i.e. __call__) and never touches
    embed_query. Uses a mock -- no model download/load."""
    records = [
        ExtractedRecord(
            embedding_id="a::0", text="hi",
            metadata={"document_id": "a", "chunk_id": "a::0", "chunk_index": 0}, row_id=1,
        )
    ]
    mock_embed_fn = MagicMock(side_effect=lambda texts: [[0.1] * 384 for _ in texts])
    mock_embed_fn.embed_query = MagicMock(
        side_effect=AssertionError("embed_query must never be called by recovery")
    )

    embedded, exclusions = regenerate_embeddings(records, embed_documents=mock_embed_fn, batch_size=10)

    assert exclusions == []
    assert len(embedded) == 1
    assert mock_embed_fn.called
    assert not mock_embed_fn.embed_query.called


# ---------------------------------------------------------------------------
# Deterministic digests
# ---------------------------------------------------------------------------


def test_digest_deterministic_under_row_reordering():
    records = [
        ExtractedRecord(embedding_id="a::0", text="alpha", metadata={"k1": "v1", "k2": 2}, row_id=1),
        ExtractedRecord(embedding_id="a::1", text="beta", metadata={"k1": "v1", "k2": 3}, row_id=2),
        ExtractedRecord(embedding_id="a::2", text="gamma", metadata={"k1": "v1", "k2": 4}, row_id=3),
    ]
    forward = compute_records_digest(records)
    reversed_order = compute_records_digest(list(reversed(records)))
    shuffled = compute_records_digest([records[1], records[2], records[0]])
    assert forward == reversed_order == shuffled

    identity_forward = compute_identity_digest(records)
    identity_reversed = compute_identity_digest(list(reversed(records)))
    assert identity_forward == identity_reversed


def test_digest_changes_when_content_changes():
    base = [ExtractedRecord(embedding_id="a::0", text="alpha", metadata={"k": "v"}, row_id=1)]
    changed_text = [ExtractedRecord(embedding_id="a::0", text="ALPHA-CHANGED", metadata={"k": "v"}, row_id=1)]
    changed_meta = [ExtractedRecord(embedding_id="a::0", text="alpha", metadata={"k": "different"}, row_id=1)]
    assert compute_records_digest(base) != compute_records_digest(changed_text)
    assert compute_records_digest(base) != compute_records_digest(changed_meta)


def test_digest_key_order_within_metadata_does_not_matter():
    a = [ExtractedRecord(embedding_id="x::0", text="t", metadata={"z": 1, "a": 2}, row_id=1)]
    b = [ExtractedRecord(embedding_id="x::0", text="t", metadata={"a": 2, "z": 1}, row_id=1)]
    assert compute_records_digest(a) == compute_records_digest(b)


# ---------------------------------------------------------------------------
# Source immutability
# ---------------------------------------------------------------------------


def test_source_sqlite_hash_unchanged_by_dry_run(tmp_path: Path):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    build_synthetic_source(source_dir / "chroma.sqlite3", records=[{"chunk_index": 0}])

    before = (source_dir / "chroma.sqlite3").read_bytes()
    manifest = run_recovery(
        source_dir=source_dir,
        source_collection="test_kb",
        dest_dir=tmp_path / "dest_preview_only",
        dest_collection="preview",
        execute=False,
    )
    after = (source_dir / "chroma.sqlite3").read_bytes()

    assert before == after
    assert manifest["source"]["sqlite_immutable"] is True
    assert manifest["source"]["sqlite_sha256_before"] == manifest["source"]["sqlite_sha256_after"]


def test_source_sqlite_hash_unchanged_by_execute(tmp_path: Path):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    build_synthetic_source(source_dir / "chroma.sqlite3", records=[{"chunk_index": 0}, {"chunk_index": 1}])

    before = (source_dir / "chroma.sqlite3").read_bytes()
    fake_ef = FakeEmbeddingFunction()
    manifest = run_recovery(
        source_dir=source_dir,
        source_collection="test_kb",
        dest_dir=tmp_path / "dest",
        dest_collection="recovered",
        execute=True,
        embed_documents=fake_ef,
        embedding_function_for_write=fake_ef,
        embedding_model_name="fake-model",
        embedding_function_name="fake_test_embedding",
        embedding_function_config={},
    )
    after = (source_dir / "chroma.sqlite3").read_bytes()

    assert before == after
    assert manifest["source"]["sqlite_immutable"] is True
    assert manifest["results"]["status"] == "complete"


# ---------------------------------------------------------------------------
# Manifest completeness / status semantics / end-to-end (real chromadb,
# synthetic temp data only)
# ---------------------------------------------------------------------------


_REQUIRED_MANIFEST_TOP_KEYS = {
    "captured_at", "recovery_tool", "recovery_tool_version", "mode",
    "git_head_sha", "git_dirty", "source", "destination", "embedding",
    "results", "informational",
}
_REQUIRED_RESULTS_KEYS = {
    "recovered_record_count", "excluded_record_count", "excluded_records",
    "identity_digest", "metadata_text_digest", "status",
}


def test_manifest_contains_all_required_fields_dry_run(tmp_path: Path):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    build_synthetic_source(source_dir / "chroma.sqlite3", records=[{"chunk_index": 0}])

    manifest = run_recovery(
        source_dir=source_dir,
        source_collection="test_kb",
        dest_dir=tmp_path / "dest_preview",
        dest_collection="preview",
        execute=False,
    )
    assert _REQUIRED_MANIFEST_TOP_KEYS <= set(manifest.keys())
    assert _REQUIRED_RESULTS_KEYS <= set(manifest["results"].keys())
    assert manifest["embedding"]["regeneration_status"] == "skipped_dry_run"
    assert manifest["results"]["recovered_record_count"] == 0  # nothing written in dry run


def test_complete_status_only_when_zero_exclusions_and_full_write(tmp_path: Path):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    build_synthetic_source(
        source_dir / "chroma.sqlite3",
        records=[{"chunk_index": 0}, {"chunk_index": 1}, {"chunk_index": 2}],
    )
    fake_ef = FakeEmbeddingFunction()
    manifest = run_recovery(
        source_dir=source_dir,
        source_collection="test_kb",
        dest_dir=tmp_path / "dest",
        dest_collection="recovered",
        execute=True,
        embed_documents=fake_ef,
        embedding_function_for_write=fake_ef,
        embedding_model_name="fake-model",
        embedding_function_name="fake_test_embedding",
        embedding_function_config={},
    )
    assert manifest["results"]["status"] == "complete"
    assert manifest["results"]["recovered_record_count"] == 3
    assert manifest["results"]["excluded_record_count"] == 0


def test_incomplete_status_when_any_record_excluded(tmp_path: Path):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    build_synthetic_source(
        source_dir / "chroma.sqlite3",
        records=[
            {"chunk_index": 0},
            {"chunk_index": 1, "omit_keys": ["chunk_id"]},  # will be excluded
        ],
    )
    fake_ef = FakeEmbeddingFunction()
    manifest = run_recovery(
        source_dir=source_dir,
        source_collection="test_kb",
        dest_dir=tmp_path / "dest",
        dest_collection="recovered",
        execute=True,
        embed_documents=fake_ef,
        embedding_function_for_write=fake_ef,
        embedding_model_name="fake-model",
        embedding_function_name="fake_test_embedding",
        embedding_function_config={},
    )
    assert manifest["results"]["status"] == "incomplete"
    assert manifest["results"]["recovered_record_count"] == 1
    assert manifest["results"]["excluded_record_count"] == 1
    # Excluded record must never have been silently patched/retried into
    # the write set.
    assert manifest["results"]["excluded_records"][0]["reason"]


def test_orphan_faq_and_source_filename_informational_fields(tmp_path: Path):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    build_synthetic_source(
        source_dir / "chroma.sqlite3",
        records=[
            {
                "chunk_index": 0,
                "document_id": "faq:1111-2222",
                "chunk_id": "faq:1111-2222::0",
                "extra_metadata": {"source_filename": "unresolvable_file.pdf"},
            },
        ],
    )
    manifest = run_recovery(
        source_dir=source_dir,
        source_collection="test_kb",
        dest_dir=tmp_path / "dest_preview",
        dest_collection="preview",
        execute=False,
    )
    assert manifest["informational"]["orphan_faq_record_ids"] == ["faq:1111-2222::0"]
    assert manifest["informational"]["orphan_faq_record_count"] == 1
    # source_filename_resolution is best-effort/informational; either it
    # successfully checked (and correctly found this fake filename
    # unresolved) or it honestly reported that it could not check --
    # either is acceptable, silent success is not.
    resolution = manifest["informational"]["source_filename_resolution"]
    assert "checked" in resolution
    if resolution["checked"]:
        assert "unresolvable_file.pdf" in resolution["unresolved_source_filenames"]


# --- End-to-end with real chromadb against temp/synthetic data only --------


def test_end_to_end_execute_then_validate_real_chromadb(tmp_path: Path):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    build_synthetic_source(
        source_dir / "chroma.sqlite3",
        records=[{"chunk_index": 0}, {"chunk_index": 1}, {"chunk_index": 2}],
    )
    fake_ef = FakeEmbeddingFunction()
    dest_dir = tmp_path / "dest"

    manifest = run_recovery(
        source_dir=source_dir,
        source_collection="test_kb",
        dest_dir=dest_dir,
        dest_collection="recovered",
        execute=True,
        embed_documents=fake_ef,
        embedding_function_for_write=fake_ef,
        embedding_model_name="fake-model",
        embedding_function_name="fake_test_embedding",
        embedding_function_config={},
    )
    assert manifest["results"]["status"] == "complete"

    result = validate_recovered_store(dest_dir, "recovered", expected_manifest=manifest)
    assert result["status"] == "ok"
    checks = result["checks"]
    assert checks["count_run_1"]["count"] == 3
    assert checks["count_run_2"]["count"] == 3
    assert checks["count_stable_across_isolated_runs"] is True
    assert checks["query_ok"] is True
    reconciliation = checks["reconciliation"]
    assert reconciliation["record_count_matches"] is True
    assert reconciliation["identity_digest_matches"] is True
    assert reconciliation["metadata_text_digest_matches"] is True
    assert reconciliation["no_duplicate_ids"] is True


def test_validate_recovered_count_matches_manifest(tmp_path: Path):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    build_synthetic_source(source_dir / "chroma.sqlite3", records=[{"chunk_index": i} for i in range(5)])
    fake_ef = FakeEmbeddingFunction()
    dest_dir = tmp_path / "dest"

    manifest = run_recovery(
        source_dir=source_dir, source_collection="test_kb",
        dest_dir=dest_dir, dest_collection="recovered", execute=True,
        embed_documents=fake_ef, embedding_function_for_write=fake_ef,
        embedding_model_name="fake-model", embedding_function_name="fake_test_embedding",
        embedding_function_config={},
    )
    result = validate_recovered_store(dest_dir, "recovered", expected_manifest=manifest)
    assert result["checks"]["reconciliation"]["expected_recovered_record_count"] == 5
    assert result["checks"]["reconciliation"]["destination_record_count"] == 5


def test_validate_detects_duplicate_ids_in_destination_sqlite(tmp_path: Path):
    """Directly crafts a destination-shaped sqlite with a real duplicate
    embedding_id (chromadb's own add() would not allow this -- it is
    tested at the reconciliation-logic level, which must still catch it
    if it were ever encountered)."""
    dest_dir = tmp_path / "dest_with_dupes"
    dest_dir.mkdir()
    build_synthetic_source(
        dest_dir / "chroma.sqlite3",
        collection_name="dupe_test",
        records=[
            {"chunk_index": 0, "chunk_id": "doc-A::0", "embedding_id": "doc-A::0"},
            {"chunk_index": 1, "chunk_id": "doc-A::0", "embedding_id": "doc-A::0"},  # literal duplicate
        ],
    )
    result = validate_recovered_store(dest_dir, "dupe_test", expected_manifest=None)
    reconciliation = result["checks"]["reconciliation"]
    assert reconciliation["checked"] is True
    assert reconciliation["no_duplicate_ids"] is False


def test_validate_nonexistent_destination_reports_failed_not_exception(tmp_path: Path):
    result = validate_recovered_store(tmp_path / "does_not_exist", "whatever")
    assert result["status"] == "failed"
    assert "not found" in result["reason"]


def test_validate_never_reports_ok_without_manifest_reconciliation_when_given(tmp_path: Path):
    """If an expected_manifest IS supplied but digests don't match (e.g. a
    caller accidentally points --validate-manifest at the wrong run),
    status must be failed, not silently ok."""
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    build_synthetic_source(source_dir / "chroma.sqlite3", records=[{"chunk_index": 0}])
    fake_ef = FakeEmbeddingFunction()
    dest_dir = tmp_path / "dest"

    manifest = run_recovery(
        source_dir=source_dir, source_collection="test_kb",
        dest_dir=dest_dir, dest_collection="recovered", execute=True,
        embed_documents=fake_ef, embedding_function_for_write=fake_ef,
        embedding_model_name="fake-model", embedding_function_name="fake_test_embedding",
        embedding_function_config={},
    )
    tampered_manifest = json.loads(json.dumps(manifest))
    tampered_manifest["results"]["identity_digest"] = "0" * 64

    result = validate_recovered_store(dest_dir, "recovered", expected_manifest=tampered_manifest)
    assert result["status"] == "failed"
    assert result["checks"]["reconciliation"]["identity_digest_matches"] is False


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------


def test_cli_execute_without_dest_is_rejected(capsys):
    rc = main(["--execute"])
    assert rc == 2
    captured = capsys.readouterr()
    assert "--dest" in captured.err


def test_cli_validate_without_collection_is_rejected(tmp_path: Path, capsys):
    rc = main(["--validate", str(tmp_path)])
    assert rc == 2
    captured = capsys.readouterr()
    assert "--validate-collection" in captured.err


def test_cli_dry_run_default_writes_manifest_and_never_touches_embedding_model(tmp_path: Path):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    build_synthetic_source(source_dir / "chroma.sqlite3", records=[{"chunk_index": 0}])
    out_path = tmp_path / "manifest.json"

    with patch("app.services.embeddings.get_embedding_function") as mock_get_ef:
        rc = main(
            [
                "--source-dir", str(source_dir),
                "--source-collection", "test_kb",
                "--out", str(out_path),
            ]
        )
    assert rc == 0
    assert not mock_get_ef.called  # dry run must never load the real embedding function
    manifest = json.loads(out_path.read_text())
    assert manifest["mode"] == "dry_run"
    assert manifest["results"]["status"] == "dry_run_ok"


def test_cli_execute_and_validate_round_trip(tmp_path: Path):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    build_synthetic_source(source_dir / "chroma.sqlite3", records=[{"chunk_index": 0}, {"chunk_index": 1}])
    dest_dir = tmp_path / "dest"
    manifest_out = tmp_path / "manifest.json"
    validate_out = tmp_path / "validation.json"

    with patch("app.services.embeddings.get_embedding_function", return_value=FakeEmbeddingFunction()):
        rc_execute = main(
            [
                "--execute", "--dest", str(dest_dir), "--dest-collection", "recovered_cli",
                "--source-dir", str(source_dir), "--source-collection", "test_kb",
                "--out", str(manifest_out),
            ]
        )
    assert rc_execute == 0
    manifest = json.loads(manifest_out.read_text())
    assert manifest["results"]["status"] == "complete"

    rc_validate = main(
        [
            "--validate", str(dest_dir), "--validate-collection", "recovered_cli",
            "--validate-manifest", str(manifest_out), "--out", str(validate_out),
        ]
    )
    assert rc_validate == 0
    validation = json.loads(validate_out.read_text())
    assert validation["status"] == "ok"


# ---------------------------------------------------------------------------
# Direct-invocation regression guard: calling main() in-process (as every
# test above does) can NEVER catch a sys.path[0] bug, because pytest has
# already put backend/ on sys.path by the time it imports this test module
# -- that is exactly the condition `python -m scripts...` also produces,
# and exactly the condition `python scripts/chroma_sqlite_recovery.py`
# does NOT produce. These two tests shell out to a real subprocess from
# backend/ to genuinely exercise both documented invocation forms.
# `--execute` with no `--dest` is used deliberately: it reaches the CLI's
# own argument validation (proving app.* imports resolved) and exits
# before touching any file, real or synthetic.
# ---------------------------------------------------------------------------


def _script_path() -> Path:
    return Path(__file__).resolve().parents[1] / "scripts" / "chroma_sqlite_recovery.py"


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_direct_invocation_resolves_app_imports_without_module_not_found():
    completed = subprocess.run(
        [sys.executable, str(_script_path()), "--execute"],
        cwd=str(_backend_root()),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert "ModuleNotFoundError" not in completed.stderr
    assert "No module named 'app'" not in completed.stderr
    assert completed.returncode == 2
    assert "--dest" in completed.stderr


def test_module_invocation_still_resolves_app_imports():
    completed = subprocess.run(
        [sys.executable, "-m", "scripts.chroma_sqlite_recovery", "--execute"],
        cwd=str(_backend_root()),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert "ModuleNotFoundError" not in completed.stderr
    assert completed.returncode == 2
    assert "--dest" in completed.stderr


def test_direct_and_module_invocation_behave_identically():
    """Both documented invocation forms must reach the same CLI outcome,
    not merely both "work" in isolation."""
    direct = subprocess.run(
        [sys.executable, str(_script_path()), "--execute"],
        cwd=str(_backend_root()), capture_output=True, text=True, timeout=30,
    )
    module = subprocess.run(
        [sys.executable, "-m", "scripts.chroma_sqlite_recovery", "--execute"],
        cwd=str(_backend_root()), capture_output=True, text=True, timeout=30,
    )
    assert direct.returncode == module.returncode == 2
    assert direct.stderr.strip() == module.stderr.strip()


# ---------------------------------------------------------------------------
# destination_created manifest clarity field (diagnostic only)
# ---------------------------------------------------------------------------


def test_destination_created_false_in_dry_run(tmp_path: Path):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    build_synthetic_source(source_dir / "chroma.sqlite3", records=[{"chunk_index": 0}])

    manifest = run_recovery(
        source_dir=source_dir,
        source_collection="test_kb",
        dest_dir=tmp_path / "dest_preview",
        dest_collection="preview",
        execute=False,
    )
    assert manifest["destination"]["destination_created"] is False
    assert not (tmp_path / "dest_preview").exists()


def test_destination_created_true_after_execute(tmp_path: Path):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    build_synthetic_source(source_dir / "chroma.sqlite3", records=[{"chunk_index": 0}])
    fake_ef = FakeEmbeddingFunction()
    dest_dir = tmp_path / "dest"

    manifest = run_recovery(
        source_dir=source_dir, source_collection="test_kb",
        dest_dir=dest_dir, dest_collection="recovered", execute=True,
        embed_documents=fake_ef, embedding_function_for_write=fake_ef,
        embedding_model_name="fake-model", embedding_function_name="fake_test_embedding",
        embedding_function_config={},
    )
    assert manifest["destination"]["destination_created"] is True
    assert (dest_dir / "chroma.sqlite3").exists()
