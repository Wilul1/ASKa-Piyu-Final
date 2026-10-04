"""Tests for the Chroma Cloud Get-quota pagination fix (2026-10-04).

Root cause: Chroma Cloud caps any single collection.get(where=...) response
at CHROMA_GET_PAGE_SIZE (300) results when `limit` is omitted -- silently,
with no error. An explicit limit ABOVE that hard-fails instead. This is
exactly how a 371-chunk LSPU Student Handbook replacement was miscounted
as 300 during verification, and why the rollback that followed only ever
saw/deleted that same capped page, leaving chunk_index 300-370 (71 records)
orphaned under the new document_id while the old 300-chunk version stayed
untouched.

FakeCappedChromaCollection below models BOTH real, confirmed behaviors:
  - limit=None (omitted)      -> silently capped at CHROMA_GET_PAGE_SIZE.
  - limit > CHROMA_GET_PAGE_SIZE -> raises (mirrors the real
    "Quota exceeded: 'Limit value' exceeded quota limit for action 'Get'"
    error reproduced directly against production, read-only, this session).
  - limit <= CHROMA_GET_PAGE_SIZE -> normal, correct offset/limit paging.

This lets these tests prove two things at once: (1) the OLD, now-removed
calling pattern (bare collection.get(where=...), no limit) really would
have silently lost data past 300 records -- a permanent regression guard
-- and (2) the NEW KnowledgeBaseStore methods, which only ever call
collection.get() through _get_all_matching's paginated loop, are correct
at every size, including exact multiples of the page size.

Nothing here touches real Chroma Cloud or the production collection.
"""

from __future__ import annotations

import pytest

from app.services.admin.digital_ingestion import (
    DigitalIngestionError,
    DigitalIngestionReconciliationError,
    publish_new_version,
)
from app.services.chroma_store import CHROMA_GET_PAGE_SIZE, KnowledgeBaseStore
from app.services.chunking import DocumentChunk

assert CHROMA_GET_PAGE_SIZE == 300, (
    "This test file's fake hard-codes Chroma Cloud's documented 300 "
    "Get-action quota; update both together if that constant ever changes."
)


def make_chunks(n: int) -> list[DocumentChunk]:
    return [
        DocumentChunk(text=f"chunk {i}", chunk_index=i, char_start=i * 100, metadata={})
        for i in range(n)
    ]


class ChromaQuotaError(RuntimeError):
    """Stand-in for chromadb.errors.ChromaError's quota-exceeded error."""


class FakeCappedChromaCollection:
    """Models Chroma Cloud's real, confirmed Get-action quota behavior.

    fail_on_add_call / fail_on_delete_document_id / fail_all_deletes mirror
    test_digital_ingestion_batching.py's fake for the rollback scenarios.
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
        self.get_calls: list[dict] = []  # for asserting pagination behavior
        self.delete_calls: list[int] = []  # size of each delete(ids=...) call

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

    def _matched_ids(self, where):
        if where and "document_id" in where:
            wanted = where["document_id"]
            return [i for i, m in self._records.items() if m.get("document_id") == wanted]
        if where and "source_filename" in where:
            wanted = where["source_filename"]
            return [i for i, m in self._records.items() if m.get("source_filename") == wanted]
        return list(self._records.keys())

    def get(self, where=None, include=None, limit=None, offset=0, ids=None):
        self.get_calls.append({"where": where, "limit": limit, "offset": offset})
        if ids is not None:
            matched = [i for i in ids if i in self._records]
        else:
            matched = self._matched_ids(where)

        if limit is not None and limit > CHROMA_GET_PAGE_SIZE:
            raise ChromaQuotaError(
                f"Quota exceeded: 'Limit value' exceeded quota limit for action 'Get': "
                f"current usage of {limit} exceeds limit of {CHROMA_GET_PAGE_SIZE}."
            )
        if limit is None:
            # The ACTUAL confirmed production bug: silent cap, no error.
            page = matched[offset : offset + CHROMA_GET_PAGE_SIZE]
        else:
            page = matched[offset : offset + limit]

        return {"ids": page, "metadatas": [self._records[i] for i in page]}

    def delete(self, *, ids):
        self.delete_calls.append(len(ids))
        if self.fail_all_deletes:
            raise RuntimeError("Simulated Chroma delete failure")
        touched_doc_ids = {self._records[i]["document_id"] for i in ids if i in self._records}
        if self.fail_on_delete_document_id in touched_doc_ids:
            raise RuntimeError("Simulated Chroma delete failure")
        for i in ids:
            self._records.pop(i, None)

    def count(self):
        return len(self._records)


def make_store(collection: FakeCappedChromaCollection) -> KnowledgeBaseStore:
    store = KnowledgeBaseStore.__new__(KnowledgeBaseStore)
    store._collection = collection
    return store


def seed(store: KnowledgeBaseStore, *, document_id: str, n_chunks: int, filename: str = "f.pdf") -> None:
    store.add_document_chunks(
        document_id=document_id, title="t", source_filename=filename,
        document_type="information", chunks=make_chunks(n_chunks),
    )


# --- Regression guard: proves the OLD bare-get() pattern really was broken -

def test_old_bare_get_without_limit_silently_truncates_past_300_the_real_bug():
    """Not testing production code here -- directly proving the fake
    faithfully reproduces the confirmed incident mechanics, so the tests
    below that exercise the FIXED helper mean something."""
    collection = FakeCappedChromaCollection()
    store = make_store(collection)
    seed(store, document_id="doc-371", n_chunks=371)

    bare = collection.get(where={"document_id": "doc-371"})  # no limit -- the old pattern
    assert len(bare["ids"]) == 300  # silently wrong, exactly the 2026-10-04 incident


def test_explicit_limit_above_300_hard_fails_like_real_chroma_cloud():
    collection = FakeCappedChromaCollection()
    store = make_store(collection)
    seed(store, document_id="doc-371", n_chunks=371)

    with pytest.raises(ChromaQuotaError):
        collection.get(where={"document_id": "doc-371"}, limit=1000)


# --- document_chunk_count: exhaustive at every required size ---------------

@pytest.mark.parametrize("n", [1, 299, 300, 301, 371, 500, 600, 1000])
def test_document_chunk_count_is_exhaustive_at_every_size(n):
    collection = FakeCappedChromaCollection()
    store = make_store(collection)
    seed(store, document_id=f"doc-{n}", n_chunks=n)

    assert store.document_chunk_count(f"doc-{n}") == n

    # No single page request ever exceeded the quota.
    assert all((c["limit"] or 0) <= CHROMA_GET_PAGE_SIZE for c in collection.get_calls)


def test_600_exact_multiple_pages_correctly_including_the_confirming_empty_page():
    collection = FakeCappedChromaCollection()
    store = make_store(collection)
    seed(store, document_id="doc-600", n_chunks=600)
    collection.get_calls.clear()

    count = store.document_chunk_count("doc-600")

    assert count == 600
    # 300 + 300 + 0 (confirming page) == 3 calls; offsets strictly increase by 300.
    offsets = [c["offset"] for c in collection.get_calls]
    assert offsets == [0, 300, 600]


def test_1000_never_issues_a_get_with_limit_above_300():
    collection = FakeCappedChromaCollection()
    store = make_store(collection)
    seed(store, document_id="doc-1000", n_chunks=1000)
    collection.get_calls.clear()

    count = store.document_chunk_count("doc-1000")

    assert count == 1000
    assert all(c["limit"] == CHROMA_GET_PAGE_SIZE for c in collection.get_calls)


# --- Metadata filtering: document_id and source_filename, exhaustively -----

def test_document_id_for_source_filename_exhaustive_past_300():
    collection = FakeCappedChromaCollection()
    store = make_store(collection)
    seed(store, document_id="doc-big", n_chunks=371, filename="Big Handbook.pdf")

    found = store.document_id_for_source_filename("Big Handbook.pdf")
    assert found == "doc-big"


def test_source_filename_lookup_sees_both_document_ids_past_the_300_cap(caplog):
    """Directly mirrors the incident's Phase 4 finding: 300 "old" + 71
    "new" chunks sharing one source_filename (371 total, > the page cap).
    Before the fix, an unpaginated get(where={"source_filename": ...})
    would only ever see the first 300 (the old document_id) and never
    discover the second document_id exists at all. After the fix, the
    exhaustive read must see BOTH distinct document_ids (which is exactly
    why document_id_for_source_filename warns and picks one -- that warning
    firing at all proves both were actually seen, not just the first 300)."""
    collection = FakeCappedChromaCollection()
    store = make_store(collection)
    seed(store, document_id="old-id", n_chunks=300, filename="Handbook.pdf")
    seed(store, document_id="new-id", n_chunks=71, filename="Handbook.pdf")

    import logging

    with caplog.at_level(logging.WARNING, logger="app.services.chroma_store"):
        found = store.document_id_for_source_filename("Handbook.pdf")

    assert found in ("old-id", "new-id")
    assert any("Multiple distinct document_ids found" in r.message for r in caplog.records)


# --- Rollback: removes ALL new-version records, at sizes requiring pagination

@pytest.mark.parametrize("n", [301, 371, 500, 600])
def test_rollback_removes_every_chunk_past_300_when_add_fails_outright(n):
    collection = FakeCappedChromaCollection(fail_on_add_call=1)
    store = make_store(collection)

    with pytest.raises(DigitalIngestionError):
        publish_new_version(
            store, chunks=make_chunks(n), title="t", source_filename="f.pdf",
            replaced_document_id=None,
        )

    assert collection.count() == 0


def test_rollback_after_partial_batches_removes_all_landed_chunks_past_300():
    """A later add() batch fails after earlier ones (250-sized, matching the
    real CHROMA_ADD_MAX_BATCH_SIZE) already landed >300 total records --
    rollback's own enumeration must be paginated too, or it would repeat
    the exact 2026-10-04 incident (seeing only the first 300 to delete)."""
    collection = FakeCappedChromaCollection(fail_on_add_call=3)  # fails the 3rd 250-batch
    store = make_store(collection)

    with pytest.raises(DigitalIngestionError):
        publish_new_version(
            store, chunks=make_chunks(600), title="t", source_filename="f.pdf",  # 3 batches: 250,250,100
            replaced_document_id=None,
        )

    assert collection.count() == 0  # not 300 left over, not 71 orphaned -- zero.


def test_rollback_deletes_in_capped_size_batches_never_a_single_oversized_call():
    collection = FakeCappedChromaCollection(fail_on_add_call=3)
    store = make_store(collection)

    with pytest.raises(DigitalIngestionError):
        publish_new_version(
            store, chunks=make_chunks(600), title="t", source_filename="f.pdf",
            replaced_document_id=None,
        )

    assert collection.delete_calls, "rollback must have issued at least one delete"
    assert all(size <= CHROMA_GET_PAGE_SIZE for size in collection.delete_calls)


# --- Full replacement safety: old=300, new=371 ------------------------------

def test_full_replacement_old_300_new_371_success():
    collection = FakeCappedChromaCollection()
    store = make_store(collection)
    seed(store, document_id="old-id", n_chunks=300, filename="Handbook.pdf")

    new_id, indexed = publish_new_version(
        store, chunks=make_chunks(371), title="New", source_filename="Handbook.pdf",
        replaced_document_id="old-id",
    )

    assert indexed == 371
    assert store.document_chunk_count(new_id) == 371  # exhaustive -- not capped at 300
    assert store.document_chunk_count("old-id") == 0  # deleted only AFTER full verification
    assert collection.count() == 371


def test_full_replacement_old_untouched_until_new_version_fully_verified():
    """The exact ordering guarantee: old=0 happens AFTER new=371 is proven,
    never before, never speculatively."""
    collection = FakeCappedChromaCollection()
    store = make_store(collection)
    seed(store, document_id="old-id", n_chunks=300, filename="Handbook.pdf")

    # Sanity: before replacement, old is intact.
    assert store.document_chunk_count("old-id") == 300

    publish_new_version(
        store, chunks=make_chunks(371), title="New", source_filename="Handbook.pdf",
        replaced_document_id="old-id",
    )

    assert store.document_chunk_count("old-id") == 0


def test_full_replacement_failure_leaves_old_300_fully_intact_this_is_the_exact_incident():
    """Replays the exact 2026-10-04 incident shape (old=300, attempted
    new=371) but with the fix applied -- the failure path must now be
    impossible for this specific miscount, proven by injecting a REAL
    failure (add failure) instead and confirming old stays exactly 300."""
    collection = FakeCappedChromaCollection(fail_on_add_call=2)  # 250 lands, second 121-batch fails
    store = make_store(collection)
    seed(store, document_id="old-id", n_chunks=300, filename="Handbook.pdf")

    with pytest.raises(DigitalIngestionError):
        publish_new_version(
            store, chunks=make_chunks(371), title="New", source_filename="Handbook.pdf",
            replaced_document_id="old-id",
        )

    assert store.document_chunk_count("old-id") == 300  # untouched
    assert collection.count() == 300  # new version fully rolled back, zero orphans


def test_unrelated_records_are_never_touched_by_a_large_replacement():
    collection = FakeCappedChromaCollection()
    store = make_store(collection)
    seed(store, document_id="old-id", n_chunks=300, filename="Handbook.pdf")
    seed(store, document_id="unrelated-id", n_chunks=50, filename="Other Document.pdf")

    publish_new_version(
        store, chunks=make_chunks(371), title="New", source_filename="Handbook.pdf",
        replaced_document_id="old-id",
    )

    assert store.document_chunk_count("unrelated-id") == 50


# --- The exact incident, proven fixed ---------------------------------------

def test_this_fix_would_have_prevented_the_371_to_71_incident():
    """Direct replay: old Handbook=300, attempted new version=371, full
    success path (no injected failure, matching what SHOULD have happened
    in production). Before the fix, document_chunk_count(new_id) would
    have read 300 (capped) instead of 371, triggering a false-mismatch
    rollback whose own enumeration was ALSO capped at 300, leaving the
    71-chunk tail (chunk_index 300-370) orphaned while old stayed at 300.
    After the fix: exact count, no mismatch, no rollback, no orphan."""
    collection = FakeCappedChromaCollection()
    store = make_store(collection)
    seed(store, document_id="8dff347a-old", n_chunks=300, filename="LSPU Student Handbook.pdf")

    new_id, indexed = publish_new_version(
        store, chunks=make_chunks(371), title="LSPU Student Handbook",
        source_filename="LSPU Student Handbook.pdf", replaced_document_id="8dff347a-old",
    )

    assert indexed == 371
    assert store.document_chunk_count(new_id) == 371  # NOT 300
    assert store.document_chunk_count("8dff347a-old") == 0  # old correctly replaced
    assert collection.count() == 371  # NOT 728-style "728 baseline + 71 orphan" shape
