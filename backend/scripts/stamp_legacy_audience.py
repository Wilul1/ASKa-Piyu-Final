"""Stamp missing Chroma ``audience`` metadata without wiping the collection.

Infers audience from source_filename / title / document_type using the same
rules as ingest. Run from the backend directory:

    python scripts/stamp_legacy_audience.py
    python scripts/stamp_legacy_audience.py --dry-run
"""

from __future__ import annotations

import argparse
import sys

from app.services.article_rag_indexer import infer_rag_audience_from_document
from app.services.chroma_store import get_knowledge_base_store


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill missing Chroma audience tags.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without writing.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=200,
        help="Chroma get/update batch size (default 200).",
    )
    args = parser.parse_args()

    store = get_knowledge_base_store()
    collection = store._collection
    total = int(collection.count() or 0)
    if total == 0:
        print("Chroma collection is empty — nothing to stamp.")
        return

    stamped = 0
    skipped = 0
    offset = 0
    while offset < total:
        batch = collection.get(
            include=["metadatas"],
            limit=args.batch_size,
            offset=offset,
        )
        ids = batch.get("ids") or []
        metadatas = batch.get("metadatas") or []
        if not ids:
            break

        update_ids: list[str] = []
        update_metas: list[dict] = []
        for chunk_id, meta in zip(ids, metadatas):
            meta = dict(meta or {})
            existing = str(meta.get("audience") or meta.get("doc_audience") or "").strip().lower()
            if existing in {"student", "faculty", "both"}:
                skipped += 1
                continue
            inferred = infer_rag_audience_from_document(
                filename=str(meta.get("source_filename") or meta.get("filename") or ""),
                title=str(meta.get("title") or meta.get("doc_display_title") or ""),
                document_type=str(meta.get("document_type") or ""),
            )
            meta["audience"] = inferred
            update_ids.append(chunk_id)
            update_metas.append(meta)
            stamped += 1

        if update_ids and not args.dry_run:
            collection.update(ids=update_ids, metadatas=update_metas)

        offset += len(ids)

    mode = "DRY-RUN" if args.dry_run else "DONE"
    print(f"[{mode}] total={total} stamped={stamped} already_tagged={skipped}")
    if args.dry_run and stamped:
        print("Re-run without --dry-run to write audience tags.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
