"""Isolated tests for the Chroma Cloud Add-quota batching fix (2026-10-03).

Root cause this fix addresses: Chroma Cloud enforces a per-request "Number
of records" quota on the ``Add`` action (observed limit: 300), independent
of total collection size (production already held 728 records when a
single 371-record add() was rejected). These tests exercise the REAL
production code -- KnowledgeBaseStore.add_document_chunks's batching
and app.services.admin.digital_ingestion.publish_new_version's staged
replacement/rollback orchestration -- against a FakeChromaCollection test
double. Nothing here ever touches real Chroma Cloud or the production
728-record collection.
"""

from __future__ import annotations

import re

import pytest

from app.services.admin.digital_ingestion import (
    CHROMA_ADD_MAX_BATCH_SIZE,
    DigitalIngestionError,
    DigitalIngestionReconciliationError,
    publish_new_version,
)
from app.services.chroma_store import KnowledgeBaseStore
from app.services.chunking import DocumentChunk

_DOCUMENT_ID_RE = re.compile(r"document_id=([0-9a-fA-F-]{36})")


def make_chunks(n: int) -> list[DocumentChunk]:
    return [
        DocumentChunk(text=f"chunk {i}", chunk_index=i, char_start=i * 100, metadata={})
        for i in range(n)
    ]


class FakeChromaCollection:
    """Minimal stand-in for chromadb.Collection: add()/get()/delete()/count().

    fail_on_add_call: 1-indexed .add() call number (across the whole test)
    that should raise instead of writing -- simulates a quota error on a
    specific batch.
    fail_on_delete_document_id: a document_id whose delete() should raise.
    fail_all_deletes: if True, every delete() raises regardless of id --
    used to simulate "rollback itself fails" without needing to know the
    freshly-generated new_document_id in advance.
    """

    def __init__(
        self,
        *,
        fail_on_add_call: int | None = None,
        fail_on_delete_document_id: str | None = None,
        fail_all_deletes: bool = False,
    ):
        self._records: dict[str, dict] = {}
        self.fail_on_add_call = fail_on_add_call
        self.fail_on_delete_document_id = fail_on_delete_document_id
        self.fail_all_deletes = fail_all_deletes
        self.add_call_count = 0
        self.add_batch_sizes: list[int] = []

    def add(self, *, ids, documents, metadatas):
        self.add_call_count += 1
        self.add_batch_sizes.append(len(ids))
        if self.fail_on_add_call == self.add_call_count:
            raise RuntimeError(
                f"Simulated Chroma Cloud quota exceeded: current usage of {len(ids)} "
                "exceeds limit of 300"
            )
        for _id, meta in zip(ids, metadatas):
            self._records[_id] = meta

    def get(self, where=None, include=None):
        if where and "document_id" in where:
            wanted = where["document_id"]
            ids = [i for i, m in self._records.items() if m.get("document_id") == wanted]
        else:
            ids = list(self._records.keys())
        return {"ids": ids, "metadatas": [self._records[i] for i in ids]}

    def delete(self, *, ids):
        if self.fail_all_deletes:
            raise RuntimeError("Simulated Chroma delete failure")
        touched_doc_ids = {self._records[i]["document_id"] for i in ids if i in self._records}
        if self.fail_on_delete_document_id in touched_doc_ids:
            raise RuntimeError("Simulated Chroma delete failure")
        for i in ids:
            self._records.pop(i, None)

    def count(self):
        return len(self._records)


def make_store(collection: FakeChromaCollection) -> KnowledgeBaseStore:
    store = KnowledgeBaseStore.__new__(KnowledgeBaseStore)
    store._collection = collection  # bypass __init__ -- no real Chroma connection
    return store


def seed_old_version(store: KnowledgeBaseStore, *, document_id: str, n_chunks: int, filename: str) -> None:
    """Writes the pre-existing "old version" directly (bypassing
    max_batch_size), then resets the fake collection's call-count
    bookkeeping so a test's fail_on_add_call counts only the batches of
    the NEW version under test, not this setup write."""
    collection = store._collection
    store.add_document_chunks(
        document_id=document_id,
        title="Old Version",
        source_filename=filename,
        document_type="information",
        chunks=make_chunks(n_chunks),
    )
    if isinstance(collection, FakeChromaCollection):
        collection.add_call_count = 0
        collection.add_batch_sizes = []


# --- A-G: successful batching at the required sizes -------------------

@pytest.mark.parametrize(
    "n_chunks,expected_batches,expected_sizes",
    [
        (1, 1, [1]),  # A
        (250, 1, [250]),  # B
        (251, 2, [250, 1]),  # C
        (300, 2, [250, 50]),  # D
        (371, 2, [250, 121]),  # E -- the exact Student Handbook case
        (500, 2, [250, 250]),  # F
        (501, 3, [250, 250, 1]),  # G
    ],
)
def test_batched_add_success_scenarios(n_chunks, expected_batches, expected_sizes):
    collection = FakeChromaCollection()
    store = make_store(collection)
    chunks = make_chunks(n_chunks)

    new_document_id, indexed = publish_new_version(
        store,
        chunks=chunks,
        title="Test Doc",
        source_filename="test.pdf",
        replaced_document_id=None,
    )

    assert indexed == n_chunks
    assert store.document_chunk_count(new_document_id) == n_chunks
    assert collection.add_call_count == expected_batches
    assert collection.add_batch_sizes == expected_sizes
    assert all(size <= CHROMA_ADD_MAX_BATCH_SIZE for size in collection.add_batch_sizes)


def test_add_document_chunks_default_behavior_unchanged_for_other_callers():
    """Every other existing caller of add_document_chunks (full extract/
    ingest pipeline, etc.) does not pass max_batch_size, so it must keep
    getting exactly one add() call regardless of chunk count -- this fix
    must not change their behavior at all."""
    collection = FakeChromaCollection()
    store = make_store(collection)
    chunks = make_chunks(400)

    count = store.add_document_chunks(
        document_id="doc-x",
        title="t",
        source_filename="f.pdf",
        document_type="information",
        chunks=chunks,
    )

    assert count == 400
    assert collection.add_call_count == 1
    assert collection.add_batch_sizes == [400]


def test_progress_callback_fires_once_per_batch_with_running_totals():
    collection = FakeChromaCollection()
    store = make_store(collection)
    chunks = make_chunks(371)
    progress: list[tuple[int, int]] = []

    publish_new_version(
        store,
        chunks=chunks,
        title="t",
        source_filename="f.pdf",
        replaced_document_id=None,
        progress_callback=lambda added, total: progress.append((added, total)),
    )

    assert progress == [(250, 371), (371, 371)]


# --- H-K: partial-batch failure and rollback ---------------------------

def test_scenario_H_first_batch_fails_old_intact_zero_new_chunks():
    collection = FakeChromaCollection()
    store = make_store(collection)
    seed_old_version(store, document_id="old-id", n_chunks=300, filename="handbook.pdf")
    # Arm the failure injection only AFTER seeding, so it targets the NEW
    # document's first batch rather than this setup write.
    collection.fail_on_add_call = 1

    with pytest.raises(DigitalIngestionError):
        publish_new_version(
            store,
            chunks=make_chunks(371),
            title="t",
            source_filename="handbook.pdf",
            replaced_document_id="old-id",
        )

    assert store.document_chunk_count("old-id") == 300  # old untouched
    assert collection.count() == 300  # zero new chunks landed anywhere


def test_scenario_I_second_batch_fails_after_first_succeeds_rolls_back():
    collection = FakeChromaCollection(fail_on_add_call=2)
    store = make_store(collection)
    seed_old_version(store, document_id="old-id", n_chunks=300, filename="handbook.pdf")
    assert collection.count() == 300

    with pytest.raises(DigitalIngestionError):
        publish_new_version(
            store,
            chunks=make_chunks(371),  # batch 1 (250) succeeds, batch 2 (121) fails
            title="t",
            source_filename="handbook.pdf",
            replaced_document_id="old-id",
        )

    assert store.document_chunk_count("old-id") == 300  # old untouched
    assert collection.count() == 300  # batch 1's 250 chunks were rolled back


def test_scenario_J_final_batch_fails_rolls_back_every_earlier_batch():
    collection = FakeChromaCollection(fail_on_add_call=3)
    store = make_store(collection)
    seed_old_version(store, document_id="old-id", n_chunks=300, filename="handbook.pdf")

    with pytest.raises(DigitalIngestionError):
        publish_new_version(
            store,
            chunks=make_chunks(501),  # batches 250, 250, 1 -- fail on the 3rd (final)
            title="t",
            source_filename="handbook.pdf",
            replaced_document_id="old-id",
        )

    assert store.document_chunk_count("old-id") == 300  # old untouched
    assert collection.count() == 300  # both earlier successful batches rolled back


def test_scenario_K_rollback_failure_raises_reconciliation_and_preserves_document_id():
    collection = FakeChromaCollection(fail_on_add_call=2, fail_all_deletes=True)
    store = make_store(collection)
    seed_old_version(store, document_id="old-id", n_chunks=300, filename="handbook.pdf")

    with pytest.raises(DigitalIngestionReconciliationError) as excinfo:
        publish_new_version(
            store,
            chunks=make_chunks(371),  # batch 1 (250) succeeds, batch 2 fails, rollback also fails
            title="t",
            source_filename="handbook.pdf",
            replaced_document_id="old-id",
        )

    message = str(excinfo.value)
    assert "manual cleanup is required" in message.lower()

    match = _DOCUMENT_ID_RE.search(message)
    assert match is not None, "orphan document_id must be preserved in the message for manual cleanup"
    orphan_id = match.group(1)

    # Old version was NEVER touched (requirement K).
    assert store.document_chunk_count("old-id") == 300
    # The orphaned batch-1 chunks are still sitting there, precisely findable.
    assert store.document_chunk_count(orphan_id) == 250
    assert collection.count() == 300 + 250


# --- L: full success with replacement -----------------------------------

def test_scenario_L_full_success_verifies_new_then_deletes_old_then_publishes():
    collection = FakeChromaCollection()
    store = make_store(collection)
    seed_old_version(store, document_id="old-id", n_chunks=300, filename="handbook.pdf")

    new_id, indexed = publish_new_version(
        store,
        chunks=make_chunks(371),
        title="New Version",
        source_filename="handbook.pdf",
        replaced_document_id="old-id",
    )

    assert indexed == 371
    assert new_id != "old-id"
    assert store.document_chunk_count(new_id) == 371
    assert store.document_chunk_count("old-id") == 0
    assert collection.count() == 371


def test_old_version_cleanup_failure_after_new_version_confirmed_is_reconciliation_not_failed():
    """If the new version is fully verified but deleting the OLD version
    fails, the job must be needs_reconciliation (new version is already
    live) -- never 'failed', which would wrongly suggest nothing happened."""
    collection = FakeChromaCollection(fail_on_delete_document_id="old-id")
    store = make_store(collection)
    seed_old_version(store, document_id="old-id", n_chunks=300, filename="handbook.pdf")

    with pytest.raises(DigitalIngestionReconciliationError) as excinfo:
        publish_new_version(
            store,
            chunks=make_chunks(371),
            title="t",
            source_filename="handbook.pdf",
            replaced_document_id="old-id",
        )

    # New version is fully present and correct -- it must not be re-added or deleted.
    assert store.document_chunk_count("old-id") == 300  # old cleanup failed, left in place
    message = str(excinfo.value)
    match = _DOCUMENT_ID_RE.search(message)
    assert match is not None
    new_id = match.group(1)
    assert store.document_chunk_count(new_id) == 371
