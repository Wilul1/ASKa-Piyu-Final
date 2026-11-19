"""Stage 4B.4 -- regression tests for add_document_chunks()'s authoritative
document-identity fix.

Context: app.services.common_representation.chunker labels every chunk it
produces with a "document_id" key (the source DocumentRecord's id --
typically the source filename, a different concept from Chroma's own
per-publish UUID). Before this fix, add_document_chunks()'s per-chunk
metadata merge let that chunk-level value silently overwrite the
function's own document_id argument -- the real, freshly-generated UUID
every identity-based Chroma lookup (export_document, delete_document,
delete_by_document_id, document_chunk_count) queries by. Uses a mocked
collection throughout; never touches real ChromaDB.
"""
from __future__ import annotations

from app.services.chroma_store import KnowledgeBaseStore
from app.services.chunking import DocumentChunk


class _FakeCollection:
    """Minimal collection stub: records exactly what add() was called
    with, and supports get(where=...) well enough for a verification-style
    round trip (count/export-shaped lookup by document_id)."""

    def __init__(self):
        self.added = None
        self._records: dict[str, dict] = {}

    def add(self, *, ids, documents, metadatas):
        self.added = (list(ids), list(documents), [dict(m) for m in metadatas])
        for _id, doc, meta in zip(ids, documents, metadatas):
            self._records[_id] = {"document": doc, "metadata": dict(meta)}

    def get(self, where=None, include=None, limit=None, offset=0, ids=None):
        if ids is not None:
            matched = [i for i in ids if i in self._records]
        elif where and "document_id" in where:
            wanted = where["document_id"]
            matched = [i for i, r in self._records.items() if r["metadata"].get("document_id") == wanted]
        else:
            matched = list(self._records.keys())
        page = matched[offset:] if limit is None else matched[offset : offset + limit]
        return {
            "ids": page,
            "documents": [self._records[i]["document"] for i in page],
            "metadatas": [self._records[i]["metadata"] for i in page],
        }

    def count(self):
        return len(self._records)


def _make_store() -> tuple[KnowledgeBaseStore, _FakeCollection]:
    collection = _FakeCollection()
    store = KnowledgeBaseStore.__new__(KnowledgeBaseStore)
    store._collection = collection
    return store, collection


def test_chunk_level_document_id_cannot_overwrite_the_authoritative_uuid():
    store, collection = _make_store()
    chunk = DocumentChunk(
        text="Service details.", chunk_index=0, char_start=0,
        metadata={"document_id": "source-file.pdf", "title": "Service"},
    )
    store.add_document_chunks(
        document_id="REAL-UUID-1234", title="Service", source_filename="source-file.pdf",
        document_type="information", chunks=[chunk],
    )
    stored = collection.added[2][0]
    assert stored["document_id"] == "REAL-UUID-1234"


def test_source_filename_and_source_document_remain_correct():
    store, collection = _make_store()
    chunk = DocumentChunk(
        text="Service details.", chunk_index=0, char_start=0,
        metadata={"document_id": "source-file.pdf", "source_document": "source-file.pdf"},
    )
    store.add_document_chunks(
        document_id="REAL-UUID-1234", title="Service", source_filename="source-file.pdf",
        document_type="information", chunks=[chunk],
    )
    stored = collection.added[2][0]
    assert stored["source_filename"] == "source-file.pdf"
    assert stored["source_document"] == "source-file.pdf"


def test_unrelated_metadata_survives_the_fix():
    store, collection = _make_store()
    chunk = DocumentChunk(
        text="Enrollment procedure.", chunk_index=0, char_start=0,
        metadata={
            "document_id": "charter.pdf", "office": "Registrar", "page_start": 7, "page_end": 8,
            "chapter": "Chapter 1", "hierarchy_path": ["Chapter 1", "Enrollment"],
        },
    )
    store.add_document_chunks(
        document_id="REAL-UUID-9999", title="Charter", source_filename="charter.pdf",
        document_type="citizen_charter", chunks=[chunk],
    )
    stored = collection.added[2][0]
    assert stored["document_id"] == "REAL-UUID-9999"
    assert stored["office"] == "Registrar"
    assert stored["page_start"] == 7
    assert stored["page_end"] == 8
    assert stored["chapter"] == "Chapter 1"
    # list values are JSON-encoded by this same merge loop -- unaffected by this fix.
    import json
    assert json.loads(stored["hierarchy_path"]) == ["Chapter 1", "Enrollment"]


def test_legacy_chunk_without_a_chunk_level_document_id_is_unaffected():
    store, collection = _make_store()
    legacy_chunk = DocumentChunk(
        text="Legacy procedure chunk.", chunk_index=0, char_start=0,
        metadata={"title": "Procedure", "office": "Treasury"},
    )
    store.add_document_chunks(
        document_id="REAL-UUID-5678", title="Procedure", source_filename="legacy.pdf",
        document_type="procedure", chunks=[legacy_chunk],
    )
    stored = collection.added[2][0]
    assert stored["document_id"] == "REAL-UUID-5678"
    assert stored["office"] == "Treasury"


def test_generic_and_handbook_shaped_stage4a_chunks_are_both_covered():
    store, collection = _make_store()
    generic_chunk = DocumentChunk(
        text="Generic info text.", chunk_index=0, char_start=0,
        metadata={"document_id": "doc.pdf", "unit_id": "generic:0", "content_type": "information"},
    )
    handbook_chunk = DocumentChunk(
        text="Policy text.", chunk_index=0, char_start=0,
        metadata={"document_id": "handbook.pdf", "unit_id": "handbook:0", "chapter": "Chapter 2", "page_start": 10, "page_end": 10},
    )

    store.add_document_chunks(
        document_id="UUID-GENERIC", title="Doc", source_filename="doc.pdf",
        document_type="information", chunks=[generic_chunk],
    )
    store.add_document_chunks(
        document_id="UUID-HANDBOOK", title="Handbook", source_filename="handbook.pdf",
        document_type="information", chunks=[handbook_chunk],
    )
    all_records = collection._records
    doc_ids = {r["metadata"]["document_id"] for r in all_records.values()}
    assert doc_ids == {"UUID-GENERIC", "UUID-HANDBOOK"}


def test_storage_to_verification_round_trip_now_finds_the_published_chunk():
    """Exercises the real failure mode from Stage 4B.2 end to end: write
    through the real add_document_chunks(), then verify through the real
    document_chunk_count() AND export_document() -- the actual methods
    publish_new_version/export tooling call, not just a direct query
    against the fake collection -- using the SAME authoritative UUID for
    both the write and the verification. Pre-fix, the chunk's own
    "document_id": "handbook.pdf" metadata silently overwrote the stored
    record's document_id, so a document_chunk_count/export_document
    lookup by the real UUID found 0 records even though the write itself
    "succeeded" -- exactly Stage 4B.2's "expected 1 chunks, found 0"
    symptom."""
    store, collection = _make_store()
    chunk = DocumentChunk(
        text="Enrollment procedures for new students.", chunk_index=0, char_start=0,
        metadata={"document_id": "handbook.pdf", "office": "Registrar", "chapter": "Chapter 1"},
    )
    store.add_document_chunks(
        document_id="REAL-UUID-ROUNDTRIP", title="Handbook", source_filename="handbook.pdf",
        document_type="information", chunks=[chunk],
    )

    # document_chunk_count() -- the real method publish_new_version itself
    # calls to verify a new version before deleting the old one.
    count = store.document_chunk_count(document_id="REAL-UUID-ROUNDTRIP")
    assert count == 1

    # export_document() -- the real method, independently re-confirms the
    # count internally and returns the actual stored documents/metadatas.
    export = store.export_document("REAL-UUID-ROUNDTRIP")
    assert export is not None
    assert export["document_id"] == "REAL-UUID-ROUNDTRIP"
    assert export["documents"] == ["Enrollment procedures for new students."]
    stored_metadata = export["metadatas"][0]
    assert stored_metadata["document_id"] == "REAL-UUID-ROUNDTRIP"
    assert stored_metadata["source_filename"] == "handbook.pdf"
    assert stored_metadata["office"] == "Registrar"
    assert stored_metadata["chapter"] == "Chapter 1"
