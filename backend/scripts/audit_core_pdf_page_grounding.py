"""Audit handbook/charter chunk page_start vs real PDF headings (read-only).

Pulls durable pdf_data from source_documents, runs the same digital
extraction + chunking path used for lightweight publish, then checks whether
each chunk's title/section heading appears on the cited page (or nearby).

  heroku run -a aska-piyu -- python scripts/audit_core_pdf_page_grounding.py

No Chroma writes. No reingest.
"""

from __future__ import annotations

import re
import sys
from collections import Counter

CORE = (
    "LSPU Student Handbook.pdf",
    "Laguna State Polytechnic University-CC_2026-1st Edition.pdf",
)

# Probe titles that previously misfired in production screenshots.
PROBE_SUBSTRINGS = (
    "Mental Health",
    "Honorable Dismissal",
    "Client-initiated",
    "Publication (Editor-in-Chief)",
    "Good Moral",
    "ID Validation",
    "Dropping",
    "Leave of Absence",
)


def _best_row(session, filename: str):
    from app.models.db_models import SourceDocument

    rows = (
        session.query(SourceDocument)
        .filter(SourceDocument.original_filename == filename)
        .all()
    )
    rows = [r for r in rows if r.pdf_data]
    if not rows:
        return None
    return max(rows, key=lambda r: len(r.pdf_data or b""))


def _heading_variants(title: str) -> list[str]:
    raw = re.sub(r"\s+", " ", (title or "").strip())
    if not raw:
        return []
    variants = [raw]
    # Handbook structure labels are "1.1 > New Student" / "Article 18 > Leave..."
    if " > " in raw:
        leaf = raw.rsplit(" > ", 1)[-1].strip()
        if leaf:
            variants.append(leaf)
        left = raw.split(" > ", 1)[0].strip()
        if left:
            variants.append(left)
    for candidate in list(variants):
        # Drop leading "Article 9." / "4.2." / "Sec. 3." / "1.1"
        stripped = re.sub(
            r"^(?:article|sec(?:tion)?|chapter)\s+[\w.-]+\s*[.:\-–—]?\s*",
            "",
            candidate,
            flags=re.I,
        ).strip()
        if stripped and stripped.casefold() != candidate.casefold():
            variants.append(stripped)
        numbered = re.sub(r"^[\d.]+(?:\s*[.:\-–—]\s*|\s+)", "", candidate).strip()
        if numbered and numbered.casefold() != candidate.casefold():
            variants.append(numbered)
        # Drop trailing parenthetical
        no_paren = re.sub(r"\s*\([^)]*\)\s*$", "", stripped or candidate).strip()
        if no_paren and no_paren not in variants:
            variants.append(no_paren)
    # Prefer longer first; dedupe
    seen: set[str] = set()
    ordered: list[str] = []
    for variant in sorted(variants, key=len, reverse=True):
        key = variant.casefold()
        if key in seen or len(variant) < 4:
            continue
        seen.add(key)
        ordered.append(variant)
    return ordered


def _page_has_heading(page_text: str, title: str) -> bool:
    hay = re.sub(r"\s+", " ", page_text or "").casefold()
    for variant in _heading_variants(title):
        needle = re.sub(r"\s+", " ", variant).casefold()
        if needle and needle in hay:
            return True
        # Prefix match for truncated titles
        if len(needle) >= 24 and needle[:24] in hay:
            return True
    return False


def _find_heading_pages(page_texts: list[str], title: str) -> list[int]:
    hits: list[int] = []
    for idx, text in enumerate(page_texts, start=1):
        if _page_has_heading(text, title):
            hits.append(idx)
    return hits


def _chunk_label(meta: dict) -> str:
    for key in (
        "source_section",
        "section_heading",
        "section",
        "article",
        "title",
        "procedure_title",
        "canonical_topic",
    ):
        value = str(meta.get(key) or "").strip()
        if value:
            return value
    return ""


def _page_of(meta: dict) -> int | None:
    for key in ("page_number", "page_start", "page"):
        raw = meta.get(key)
        try:
            page = int(raw)
        except (TypeError, ValueError):
            continue
        if page > 0:
            return page
    return None


def audit_one(filename: str, pdf_bytes: bytes) -> dict:
    from app.services.admin.digital_ingestion import (
        build_structure_aware_chunks,
        extract_digital_text_only,
    )

    page_texts, _page_offsets = extract_digital_text_only(pdf_bytes)
    chunks = build_structure_aware_chunks(
        page_texts,
        title=filename.rsplit(".", 1)[0],
        source_filename=filename,
        pdf_bytes=pdf_bytes,
    )

    checked = 0
    on_page = 0
    nearby = 0  # within +/- 2 pages
    elsewhere = 0
    missing_heading = 0
    no_page = 0
    mismatches: list[dict] = []

    for chunk in chunks:
        meta = dict(chunk.metadata or {})
        label = _chunk_label(meta)
        page = _page_of(meta)
        if not label or len(label) < 8:
            continue
        checked += 1
        if page is None:
            no_page += 1
            continue
        if page < 1 or page > len(page_texts):
            elsewhere += 1
            mismatches.append(
                {
                    "label": label[:80],
                    "cited_page": page,
                    "found_pages": [],
                    "reason": "cited_page_out_of_range",
                }
            )
            continue
        if _page_has_heading(page_texts[page - 1], label):
            on_page += 1
            continue
        found = _find_heading_pages(page_texts, label)
        if not found:
            missing_heading += 1
            mismatches.append(
                {
                    "label": label[:80],
                    "cited_page": page,
                    "found_pages": [],
                    "reason": "heading_not_in_pdf_text",
                }
            )
            continue
        if any(abs(p - page) <= 2 for p in found):
            nearby += 1
        else:
            elsewhere += 1
            mismatches.append(
                {
                    "label": label[:80],
                    "cited_page": page,
                    "found_pages": found[:5],
                    "reason": "heading_on_other_pages",
                }
            )

    probes: list[dict] = []
    for needle in PROBE_SUBSTRINGS:
        hits = []
        for chunk in chunks:
            meta = dict(chunk.metadata or {})
            label = _chunk_label(meta)
            if needle.casefold() not in label.casefold() and needle.casefold() not in (
                chunk.text or ""
            ).casefold():
                continue
            page = _page_of(meta)
            found = _find_heading_pages(page_texts, label) if label else []
            body_pages = [
                idx
                for idx, text in enumerate(page_texts, start=1)
                if needle.casefold() in (text or "").casefold()
            ][:8]
            hits.append(
                {
                    "label": label[:90],
                    "cited_page": page,
                    "heading_pages": found[:5],
                    "body_pages_with_needle": body_pages,
                    "ok": bool(
                        page
                        and (
                            (found and page in found)
                            or any(abs(bp - page) <= 2 for bp in body_pages)
                        )
                    ),
                }
            )
            if len(hits) >= 3:
                break
        if hits:
            probes.append({"needle": needle, "hits": hits})

    return {
        "filename": filename,
        "pdf_bytes": len(pdf_bytes),
        "pages": len(page_texts),
        "chunks": len(chunks),
        "checked_labeled": checked,
        "on_cited_page": on_page,
        "nearby_pm2": nearby,
        "elsewhere": elsewhere,
        "heading_missing": missing_heading,
        "no_page_meta": no_page,
        "mismatch_examples": mismatches[:12],
        "probes": probes,
    }


def _print_report(report: dict) -> None:
    print("=" * 72)
    print(report["filename"])
    print(
        f"  pdf_bytes={report['pdf_bytes']} pages={report['pages']} "
        f"chunks={report['chunks']}"
    )
    checked = report["checked_labeled"] or 1
    on = report["on_cited_page"]
    near = report["nearby_pm2"]
    else_ = report["elsewhere"]
    missing = report["heading_missing"]
    print(
        f"  labeled_chunks={report['checked_labeled']} "
        f"on_page={on} ({100 * on / checked:.1f}%) "
        f"nearby±2={near} ({100 * near / checked:.1f}%) "
        f"elsewhere={else_} heading_missing={missing} "
        f"no_page={report['no_page_meta']}"
    )
    if report["mismatch_examples"]:
        print("  mismatch examples:")
        for item in report["mismatch_examples"][:8]:
            print(
                f"    - {item['reason']}: cited_p={item['cited_page']} "
                f"found={item['found_pages']} label={item['label']!r}"
            )
    if report["probes"]:
        print("  production probes:")
        for probe in report["probes"]:
            print(f"    [{probe['needle']}]")
            for hit in probe["hits"]:
                print(
                    f"      ok={hit['ok']} cited_p={hit['cited_page']} "
                    f"heading_pages={hit['heading_pages']} "
                    f"body_pages={hit['body_pages_with_needle']} "
                    f"label={hit['label']!r}"
                )


def _local_pdf_bytes(filename: str) -> bytes | None:
    """Optional local fallback under backend/data/audit_pdfs (gitignored)."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "data" / "audit_pdfs"
    if not root.is_dir():
        return None
    candidates = [
        root / filename,
        root / filename.replace(" ", "_"),
        root / "LSPU_Student_Handbook.pdf" if "Handbook" in filename else None,
        root / "Laguna_State_Polytechnic_University-CC_2026-1st_Edition.pdf"
        if "CC_2026" in filename or "Charter" in filename
        else None,
    ]
    for path in candidates:
        if path is not None and path.is_file():
            return path.read_bytes()
    return None


def main() -> int:
    failures = 0
    session = None
    try:
        try:
            from app.db.session import get_session_factory

            session = get_session_factory()()
        except Exception as exc:
            print(f"NOTE db_unavailable ({type(exc).__name__}); trying local audit_pdfs")
            session = None

        for filename in CORE:
            pdf_bytes = None
            source_note = "local"
            if session is not None:
                row = _best_row(session, filename)
                if row is not None and row.pdf_data:
                    pdf_bytes = bytes(row.pdf_data)
                    source_note = f"db source_id={row.id}"
            if pdf_bytes is None:
                pdf_bytes = _local_pdf_bytes(filename)
            if pdf_bytes is None:
                print(f"FAIL missing_pdf filename={filename}")
                failures += 1
                continue
            print(f"START filename={filename} ({source_note})")
            report = audit_one(filename, pdf_bytes)
            _print_report(report)
            # Fail closed recommendation threshold: >25% elsewhere or key probes fail
            checked = report["checked_labeled"] or 1
            elsewhere_rate = report["elsewhere"] / checked
            probe_fail = any(
                (not hit["ok"])
                for probe in report["probes"]
                for hit in probe["hits"]
                if probe["needle"]
                in {"Mental Health", "Honorable Dismissal", "Client-initiated"}
            )
            if elsewhere_rate > 0.25 or probe_fail:
                print("  VERDICT: NEEDS_FIXING_BEFORE_REINGEST")
                failures += 1
            elif elsewhere_rate > 0.10:
                print("  VERDICT: REINGEST_OK_WITH_SECTION_SEARCH_SAFETY_NET")
            else:
                print("  VERDICT: GOOD_TO_REINGEST")
    finally:
        if session is not None:
            session.close()
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
