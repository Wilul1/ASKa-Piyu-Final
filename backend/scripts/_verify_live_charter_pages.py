"""Read-only: verify live Chroma charter chunks vs PDF page text (no embeds)."""
from __future__ import annotations

import re
import sys

FILENAME = "Laguna State Polytechnic University-CC_2026-1st Edition.pdf"
PROBES = (
    "ID Validation",
    "Good Moral Certificate (Undergraduate)",
    "Dropping of Subjects",
    "Fitness",
    "Gymnasium",
)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).casefold()


def main() -> int:
    from app.db.session import get_session_factory
    from app.models.db_models import SourceDocument
    from app.services.admin.digital_ingestion import extract_digital_text_only
    from app.services.chroma_store import get_knowledge_base_store

    session = get_session_factory()()
    try:
        rows = (
            session.query(SourceDocument)
            .filter(SourceDocument.original_filename == FILENAME)
            .all()
        )
        rows = [r for r in rows if r.pdf_data]
        if not rows:
            print("FAIL missing_pdf")
            return 1
        row = max(rows, key=lambda r: len(r.pdf_data or b""))
        page_texts, _ = extract_digital_text_only(bytes(row.pdf_data))
    finally:
        session.close()

    store = get_knowledge_base_store()
    doc_id = store.document_id_for_source_filename(FILENAME)
    print(f"live_document_id={doc_id}")
    if not doc_id:
        print("FAIL no_chroma_document")
        return 1

    data = store._collection.get(
        where={"source_filename": FILENAME},
        include=["metadatas", "documents"],
    )
    metadatas = data.get("metadatas") or []
    documents = data.get("documents") or []
    # Prefer chunks for the current document_id if present
    pairs = []
    for meta, doc in zip(metadatas, documents):
        meta = dict(meta or {})
        if str(meta.get("document_id") or "") == str(doc_id):
            pairs.append((meta, doc))
    if not pairs:
        pairs = [(dict(m or {}), d) for m, d in zip(metadatas, documents)]

    print(f"chunks_for_doc={len(pairs)} pages_pdf={len(page_texts)}")

    checked = on = near = else_ = miss = 0
    for meta, _doc in pairs:
        label = (
            str(meta.get("source_section") or "")
            or str(meta.get("section_heading") or "")
            or str(meta.get("title") or "")
            or str(meta.get("procedure_title") or "")
        ).strip()
        page = meta.get("page_number") or meta.get("page_start") or meta.get("page")
        try:
            page = int(page)
        except (TypeError, ValueError):
            continue
        if len(label) < 8:
            continue
        checked += 1
        needle = _norm(label)
        if 1 <= page <= len(page_texts) and needle[: min(40, len(needle))] in _norm(
            page_texts[page - 1]
        ):
            on += 1
            continue
        found = [
            i
            for i, text in enumerate(page_texts, start=1)
            if needle[: min(40, len(needle))] in _norm(text)
        ]
        if not found:
            miss += 1
        elif any(abs(p - page) <= 2 for p in found):
            near += 1
        else:
            else_ += 1

    checked_safe = checked or 1
    print(
        f"labeled={checked} on_page={on} ({100 * on / checked_safe:.1f}%) "
        f"nearby={near} elsewhere={else_} missing={miss}"
    )

    print("probes:")
    for needle in PROBES:
        hits = []
        for meta, doc in pairs:
            blob = f"{meta.get('source_section','')} {meta.get('title','')} {doc or ''}"
            if needle.casefold() not in blob.casefold():
                continue
            page = meta.get("page_number") or meta.get("page_start")
            label = str(meta.get("source_section") or meta.get("title") or "")[:80]
            body = [
                i
                for i, text in enumerate(page_texts, start=1)
                if needle.casefold() in (text or "").casefold()
            ][:6]
            ok = bool(page and body and any(abs(int(page) - b) <= 2 for b in body))
            hits.append((ok, page, label, body))
            if len(hits) >= 2:
                break
        if not hits:
            print(f"  [{needle}] no_chunk_hit")
        for ok, page, label, body in hits:
            print(f"  [{needle}] ok={ok} cited_p={page} body={body} label={label!r}")

    if on / checked_safe >= 0.9 and else_ / checked_safe <= 0.1:
        print("VERDICT: LIVE_CHARTER_GOOD")
        return 0
    print("VERDICT: LIVE_CHARTER_NEEDS_REVIEW")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
