"""Tests for the 2026-10-21 export_document()/restore_document_export() fix.

Root cause (two separate bugs, same incident class as the 2026-10-04
Get-quota incident already covered by test_chroma_pagination_fix.py):

  - export_document() used a bare collection.get(where=...) with no
    pagination -- for a document over CHROMA_GET_PAGE_SIZE (300) chunks
    (e.g. the 492-chunk LSPU Student Handbook), this would silently
    return only the first ~300 records with no error, producing a
    snapshot that LOOKS complete but is missing ~40% of the document.

  - restore_document_export() issued a single, unbatched collection.add()
    for the whole snapshot -- for the same 492-record document, this
    would almost certainly be rejected outright by Chroma Cloud's
    per-request Add-action quota (same quota CHROMA_ADD_MAX_BATCH_SIZE
    in digital_ingestion.py already exists to respect on the ingestion-
    publish path), failing to restore anything.

FakeCappedChromaCollection (copied from test_chroma_pagination_fix.py's
own fixture, extended with add-call tracking already present there and a
delete-call failure hook) models both the real Get-quota cap and the
real Add-quota cap, so these tests prove the fix against the actual
confirmed Chroma Cloud behavior, not an idealized fake.

Nothing here touches real Chroma Cloud or the production collection.
"""

from __future__ import annotations

import pytest

from app.services.chroma_store import (
    CHROMA_GET_PAGE_SIZE,
    CHROMA_RESTORE_MAX_BATCH_SIZE,
    KnowledgeBaseStore,
)

assert CHROMA_GET_PAGE_SIZE == 300, (
    "This test file's fake hard-codes Chroma Cloud's documented 300 "
    "Get-action quota; update both together if that constant ever changes."
)


class ChromaQuotaError(RuntimeError):
    """Stand-in for chromadb.errors.ChromaError's quota-exceeded error."""


class FakeCappedChromaCollection:
    """Models Chroma Cloud's real, confirmed Get- and Add-action quotas.

    fail_on_add_call lets a test make the Nth add() call (1-indexed, across
    the whole test, including any add_document_chunks seeding) raise, to
    exercise restore's own partial-batch-failure cleanup path.
    fail_on_delete_document_id / fail_all_deletes mirror
    test_chroma_pagination_fix.py's fixture for the rollback scenarios.
    """

    def __init__(
        self,
        *,
        fail_on_add_call: int | None = None,
        fail_on_delete_document_id: str | None = None,
        fail_all_deletes: bool = False,
    ):
        self._records: dict[str, dict] = {}
        self._documents: dict[str, str] = {}
        self.fail_on_add_call = fail_on_add_call
        self.fail_on_delete_document_id = fail_on_delete_document_id
        self.fail_all_deletes = fail_all_deletes
        self.add_call_count = 0
        self.add_batch_sizes: list[int] = []
        self.get_calls: list[dict] = []
        self.delete_calls: list[int] = []

    def add(self, *, ids, documents, metadatas):
        self.add_call_count += 1
        self.add_batch_sizes.append(len(ids))
        if len(ids) > CHROMA_RESTORE_MAX_BATCH_SIZE and len(ids) > 300:
            # Mirrors the real Add-action quota directly, not just via the
            # fail_on_add_call hook, so a test can't accidentally pass by
            # relying on injected failure alone.
            raise ChromaQuotaError(
                f"Quota exceeded: current usage of {len(ids)} exceeds limit of 300."
            )
        if self.fail_on_add_call == self.add_call_count:
            raise RuntimeError(
                f"Simulated Chroma Cloud quota exceeded: current usage of {len(ids)} "
                "exceeds limit of 300"
            )
        for _id, doc, meta in zip(ids, documents, metadatas):
            self._records[_id] = meta
            self._documents[_id] = doc

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

        include = include or []
        result: dict = {"ids": page}
        if "metadatas" in include:
            result["metadatas"] = [self._records[i] for i in page]
        if "documents" in include:
            result["documents"] = [self._documents[i] for i in page]
        return result

    def delete(self, *, ids):
        self.delete_calls.append(len(ids))
        if self.fail_all_deletes:
            raise RuntimeError("Simulated Chroma delete failure")
        touched_doc_ids = {self._records[i]["document_id"] for i in ids if i in self._records}
        if self.fail_on_delete_document_id in touched_doc_ids:
            raise RuntimeError("Simulated Chroma delete failure")
        for i in ids:
            self._records.pop(i, None)
            self._documents.pop(i, None)

    def count(self):
        return len(self._records)


def make_store(collection: FakeCappedChromaCollection) -> KnowledgeBaseStore:
    store = KnowledgeBaseStore.__new__(KnowledgeBaseStore)
    store._collection = collection
    return store


def seed_real_records(
    store: KnowledgeBaseStore,
    collection: FakeCappedChromaCollection,
    *,
    document_id: str,
    n_chunks: int,
    filename: str = "f.pdf",
) -> None:
    """Seeds via collection.add() directly in CHROMA_RESTORE_MAX_BATCH_SIZE
    batches -- not store.add_document_chunks(), to keep this file
    independent of the ingestion module's own batching constant and
    behavior (already covered by test_chroma_pagination_fix.py)."""
    ids = [f"{document_id}::{i}" for i in range(n_chunks)]
    documents = [f"chunk text {i} for {document_id}" for i in range(n_chunks)]
    metadatas = [{"document_id": document_id, "source_filename": filename, "chunk_index": i} for i in range(n_chunks)]
    for start in range(0, n_chunks, CHROMA_RESTORE_MAX_BATCH_SIZE):
        end = start + CHROMA_RESTORE_MAX_BATCH_SIZE
        collection.add(ids=ids[start:end], documents=documents[start:end], metadatas=metadatas[start:end])


# --- export_document(): exhaustive retrieval, every size ------------------


@pytest.mark.parametrize("n", [1, 299, 300, 301, 492, 600])
def test_export_document_retrieves_every_record_at_every_size(n):
    collection = FakeCappedChromaCollection()
    store = make_store(collection)
    seed_real_records(store, collection, document_id="doc", n_chunks=n)

    export = store.export_document("doc")

    assert export is not None
    assert len(export["ids"]) == n
    assert len(export["documents"]) == n
    assert len(export["metadatas"]) == n
    assert len(set(export["ids"])) == n


def test_export_document_492_records_pages_across_multiple_gets():
    """The exact scenario this fix targets: the real production baseline."""
    collection = FakeCappedChromaCollection()
    store = make_store(collection)
    seed_real_records(store, collection, document_id="8dff347a-...", n_chunks=492)
    collection.get_calls.clear()

    export = store.export_document("8dff347a-...")

    assert export is not None
    assert len(export["ids"]) == 492
    # Multiple paginated Get calls were actually issued -- not one bare call.
    assert len(collection.get_calls) >= 2
    assert all((c["limit"] or 0) <= CHROMA_GET_PAGE_SIZE for c in collection.get_calls)


def test_export_document_not_found_returns_none_unchanged_contract():
    """article_rag_indexer.index_published_article treats None as
    "nothing to restore, first-time index" -- this contract must not change."""
    collection = FakeCappedChromaCollection()
    store = make_store(collection)

    assert store.export_document("never-existed") is None


# --- export_document(): fails closed, never returns inconsistent data -----


def test_export_document_fails_closed_on_misaligned_arrays():
    collection = FakeCappedChromaCollection()
    store = make_store(collection)
    seed_real_records(store, collection, document_id="doc", n_chunks=5)

    # Simulate a backend that returns misaligned ids/documents/metadatas --
    # export_document must detect this itself, not trust the read blindly.
    original_get = collection.get

    def _misaligned_get(*args, **kwargs):
        result = original_get(*args, **kwargs)
        if "documents" in (kwargs.get("include") or []):
            result["documents"] = result["documents"][:-1]  # drop one
        return result

    collection.get = _misaligned_get

    with pytest.raises(ValueError, match="misaligned"):
        store.export_document("doc")


def test_export_document_fails_closed_on_duplicate_ids():
    collection = FakeCappedChromaCollection()
    store = make_store(collection)
    seed_real_records(store, collection, document_id="doc", n_chunks=3)

    original_get = collection.get

    def _duplicated_get(*args, **kwargs):
        result = original_get(*args, **kwargs)
        result["ids"] = result["ids"] + [result["ids"][0]]
        if "documents" in result:
            result["documents"] = result["documents"] + [result["documents"][0]]
        if "metadatas" in result:
            result["metadatas"] = result["metadatas"] + [result["metadatas"][0]]
        return result

    collection.get = _duplicated_get

    with pytest.raises(ValueError, match="duplicate"):
        store.export_document("doc")


def test_export_document_fails_closed_on_mismatched_document_id():
    collection = FakeCappedChromaCollection()
    store = make_store(collection)
    seed_real_records(store, collection, document_id="doc-a", n_chunks=3)

    original_get = collection.get

    def _wrong_owner_get(*args, **kwargs):
        result = original_get(*args, **kwargs)
        if "metadatas" in result and result["metadatas"]:
            result["metadatas"][0] = dict(result["metadatas"][0])
            result["metadatas"][0]["document_id"] = "doc-b"  # tampered
        return result

    collection.get = _wrong_owner_get

    with pytest.raises(ValueError, match="document_id"):
        store.export_document("doc-a")


def test_export_document_fails_closed_when_independent_count_disagrees():
    """The reconciliation cross-check: a single, independently-issued
    document_chunk_count() call (taken immediately after the paginated
    read) must agree with the just-read ids, or the export is refused.

    2026-10-21 note: a stricter two-count (before-and-after) version of
    this check was tried first. While testing it, this project's own
    test_chroma_rebuild.py integration test crashed with a real "Windows
    fatal exception: access violation" inside chromadb's embedded Rust
    backend -- but reverting to this single-count version did NOT make
    that crash go away (the same test crashes identically against fully
    original, unmodified store code, with no count() call involved at
    all). So that crash is pre-existing, environment-specific chromadb/
    test-harness flakiness unrelated to this check, not something this
    check causes -- see export_document's own CONCURRENCY LIMITATION
    docstring section for the full explanation. The single-count design
    below is kept for simplicity, not because it was proven to avoid a
    crash that neither version actually causes."""
    collection = FakeCappedChromaCollection()
    store = make_store(collection)
    seed_real_records(store, collection, document_id="doc", n_chunks=5)

    original_count = store.document_chunk_count

    def _lying_count(document_id):
        return original_count(document_id) + 1  # disagrees on purpose

    store.document_chunk_count = _lying_count

    with pytest.raises(ValueError, match="independent count"):
        store.export_document("doc")


# --- restore_document_export(): batched, preserves ids/documents/metadata -


def test_restore_batches_492_records_never_a_single_oversized_add():
    collection = FakeCappedChromaCollection()
    store = make_store(collection)
    export = {
        "document_id": "doc",
        "ids": [f"doc::{i}" for i in range(492)],
        "documents": [f"text {i}" for i in range(492)],
        "metadatas": [{"document_id": "doc", "chunk_index": i} for i in range(492)],
    }

    store.restore_document_export(export)

    assert collection.count() == 492
    assert all(size <= CHROMA_RESTORE_MAX_BATCH_SIZE for size in collection.add_batch_sizes)
    assert len(collection.add_batch_sizes) >= 2  # 492 / 250 -> at least 2 batches


def test_restore_preserves_original_ids_documents_and_metadata():
    collection = FakeCappedChromaCollection()
    store = make_store(collection)
    export = {
        "document_id": "doc",
        "ids": ["doc::0", "doc::1", "doc::2"],
        "documents": ["Cyberbullying text", "Gambling text", "Indecency text"],
        "metadatas": [
            {"document_id": "doc", "title": "Cyber bullying or bullying"},
            {"document_id": "doc", "title": "Gambling"},
            {"document_id": "doc", "title": "Indecency and Obsceni"},
        ],
    }

    store.restore_document_export(export)

    assert collection._documents["doc::1"] == "Gambling text"
    assert collection._records["doc::1"]["title"] == "Gambling"
    assert set(collection._records.keys()) == {"doc::0", "doc::1", "doc::2"}


def test_restore_does_not_touch_unrelated_document_ids():
    collection = FakeCappedChromaCollection()
    store = make_store(collection)
    seed_real_records(store, collection, document_id="unrelated", n_chunks=10, filename="Other.pdf")

    export = {
        "document_id": "doc",
        "ids": [f"doc::{i}" for i in range(5)],
        "documents": [f"text {i}" for i in range(5)],
        "metadatas": [{"document_id": "doc", "chunk_index": i} for i in range(5)],
    }
    store.restore_document_export(export)

    assert store.document_chunk_count("unrelated") == 10
    assert store.document_chunk_count("doc") == 5


# --- restore_document_export(): fails closed on bad input -----------------


def test_restore_rejects_misaligned_export():
    collection = FakeCappedChromaCollection()
    store = make_store(collection)
    export = {
        "document_id": "doc",
        "ids": ["doc::0", "doc::1"],
        "documents": ["only one"],
        "metadatas": [{"document_id": "doc"}, {"document_id": "doc"}],
    }

    with pytest.raises(ValueError, match="mismatch"):
        store.restore_document_export(export)
    assert collection.count() == 0  # never attempted to write anything


def test_restore_rejects_duplicate_ids():
    collection = FakeCappedChromaCollection()
    store = make_store(collection)
    export = {
        "document_id": "doc",
        "ids": ["doc::0", "doc::0"],
        "documents": ["a", "b"],
        "metadatas": [{"document_id": "doc"}, {"document_id": "doc"}],
    }

    with pytest.raises(ValueError, match="duplicate"):
        store.restore_document_export(export)
    assert collection.count() == 0


# --- restore_document_export(): pre-restore precondition (2026-10-21) -----


def test_restore_aborts_before_adding_when_predelete_leaves_records_behind():
    """The upfront delete_document(document_id) must be independently
    verified empty before any add() happens. Simulate a delete that
    "succeeds" (raises nothing) but a record is still visible afterward
    -- restore must abort with zero records added, not proceed on top of
    an unverified pre-restore state."""
    collection = FakeCappedChromaCollection()
    store = make_store(collection)
    seed_real_records(store, collection, document_id="doc", n_chunks=3)

    real_delete_document = store.delete_document

    def _delete_that_leaves_one_behind(document_id):
        real_delete_document(document_id)
        # Put one record back, simulating a delete that silently failed
        # to remove everything (e.g. an undiscovered partial-delete bug).
        collection.add(ids=["doc::leftover"], documents=["leftover"], metadatas=[{"document_id": document_id}])

    store.delete_document = _delete_that_leaves_one_behind

    export = {
        "document_id": "doc",
        "ids": [f"new::{i}" for i in range(3)],
        "documents": [f"text {i}" for i in range(3)],
        "metadatas": [{"document_id": "doc", "chunk_index": i} for i in range(3)],
    }

    with pytest.raises(RuntimeError, match="could not be verified clean"):
        store.restore_document_export(export)

    # No new records were added -- only the simulated leftover remains.
    assert collection.count() == 1
    assert "doc::leftover" in collection._records
    assert not any(i.startswith("new::") for i in collection._records)


def test_restore_aborts_before_adding_when_predelete_verification_raises():
    """If the post-delete document_chunk_count() call itself raises
    (not just disagrees), restore must abort the same way -- a clear,
    actionable exception, zero records added."""
    collection = FakeCappedChromaCollection()
    store = make_store(collection)
    seed_real_records(store, collection, document_id="doc", n_chunks=3)

    def _raising_count(document_id):
        raise RuntimeError("simulated verification query failure")

    store.document_chunk_count = _raising_count

    export = {
        "document_id": "doc",
        "ids": [f"new::{i}" for i in range(3)],
        "documents": [f"text {i}" for i in range(3)],
        "metadatas": [{"document_id": "doc", "chunk_index": i} for i in range(3)],
    }

    with pytest.raises(RuntimeError, match="clearing document_id"):
        store.restore_document_export(export)

    # delete_document() itself still ran (real one, unpatched) and
    # succeeded -- only the verification query was simulated as failing --
    # so no new records were added either way.
    assert not any(i.startswith("new::") for i in collection._records)


def test_restore_proceeds_normally_when_predelete_precondition_is_clean():
    """Sanity check: the new precondition check must not break the
    ordinary, already-covered success path (seeded under the SAME
    document_id this time, so the precondition check has something real
    to verify against zero)."""
    collection = FakeCappedChromaCollection()
    store = make_store(collection)
    seed_real_records(store, collection, document_id="doc", n_chunks=3, filename="old.pdf")

    export = {
        "document_id": "doc",
        "ids": [f"new::{i}" for i in range(5)],
        "documents": [f"text {i}" for i in range(5)],
        "metadatas": [{"document_id": "doc", "chunk_index": i} for i in range(5)],
    }

    store.restore_document_export(export)

    assert store.document_chunk_count("doc") == 5
    assert all(i.startswith("new::") for i in collection._records)


# --- restore_document_export(): a later batch fails -- recovery state -----


def test_restore_failure_in_a_later_batch_cleans_up_and_reports_safe_to_retry():
    """600 records -> 3 batches of 250,250,100. The 2nd batch fails after
    the 1st already landed 250 records. Cleanup must remove those 250 and
    verify zero remain, then raise an error that says it's safe to retry."""
    collection = FakeCappedChromaCollection(fail_on_add_call=2)
    store = make_store(collection)
    export = {
        "document_id": "doc",
        "ids": [f"doc::{i}" for i in range(600)],
        "documents": [f"text {i}" for i in range(600)],
        "metadatas": [{"document_id": "doc", "chunk_index": i} for i in range(600)],
    }

    with pytest.raises(RuntimeError, match="safe to retry"):
        store.restore_document_export(export)

    assert collection.count() == 0  # no partial 250 left behind
    assert store.document_chunk_count("doc") == 0


def test_restore_failure_cleanup_itself_failing_is_reported_not_hidden():
    """If the cleanup delete after a failed batch ALSO fails, the error
    must say manual verification is required -- never claim a clean
    "safe to retry" state that was not actually confirmed."""
    collection = FakeCappedChromaCollection(fail_on_add_call=2, fail_all_deletes=True)
    store = make_store(collection)
    export = {
        "document_id": "doc",
        "ids": [f"doc::{i}" for i in range(600)],
        "documents": [f"text {i}" for i in range(600)],
        "metadatas": [{"document_id": "doc", "chunk_index": i} for i in range(600)],
    }

    with pytest.raises(RuntimeError, match="manual verification is required"):
        store.restore_document_export(export)


def test_restore_round_trips_through_export_for_492_records():
    """End-to-end: export a real 492-chunk document, then restore it from
    that exact export, and confirm the result is identical."""
    collection = FakeCappedChromaCollection()
    store = make_store(collection)
    seed_real_records(store, collection, document_id="8dff347a-...", n_chunks=492, filename="LSPU Student Handbook.pdf")

    export = store.export_document("8dff347a-...")
    assert export is not None

    store.delete_document("8dff347a-...")
    assert collection.count() == 0

    store.restore_document_export(export)

    assert collection.count() == 492
    assert store.document_chunk_count("8dff347a-...") == 492
