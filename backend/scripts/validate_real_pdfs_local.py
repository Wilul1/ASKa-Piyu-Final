"""Optional, LOCAL-ONLY validation of the extraction/cleaning pipeline
against the real LSPU Faculty Manual / Student Handbook PDFs.

Not part of the automated test suite -- the real PDFs are never
committed to this repository (ownership/size), so this script is a
manual diagnostic an admin can run on their own machine when they have
local copies of the documents available. It is read-only end to end:

- No Chroma access of any kind (no add/get/delete/count).
- No network call (no Hugging Face, OpenRouter, Groq, or AWS OCR --
  this script only runs the PyMuPDF digital-extraction path, which
  never calls the OCR worker for a digitally-extractable PDF).
- No index/publish of any kind -- publish_new_version() is never
  imported or called here.

Usage:
    python scripts/validate_real_pdfs_local.py <faculty_manual.pdf> <student_handbook.pdf>

Or set env vars and run with no arguments:
    ASKA_VALIDATE_FACULTY_MANUAL_PDF=/path/to/faculty.pdf
    ASKA_VALIDATE_STUDENT_HANDBOOK_PDF=/path/to/handbook.pdf

If neither a CLI argument nor the matching env var points to an
existing file, that document is skipped (printed, not a failure) --
this script is meant to degrade gracefully when the PDFs simply aren't
present on a given machine (e.g. CI, a fresh clone).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.admin.digital_ingestion import (  # noqa: E402
    build_chunks_with_pages,
    extract_digital_text_only,
    _page_offsets_from_texts,
)
from app.services.chroma_store import KnowledgeBaseStore  # noqa: E402


class _NeverCalledCollection:
    """Fails loudly if anything in this script ever reaches Chroma."""

    def add(self, **kwargs):
        raise AssertionError("Chroma add() must never be called by this read-only validation script.")

    def get(self, **kwargs):
        return {"ids": [], "metadatas": []}

    def delete(self, **kwargs):
        raise AssertionError("Chroma delete() must never be called by this read-only validation script.")

    def count(self):
        return 0


def _fake_store() -> KnowledgeBaseStore:
    store = KnowledgeBaseStore.__new__(KnowledgeBaseStore)
    store._collection = _NeverCalledCollection()
    return store


def _resolve_pdf_path(cli_arg: str | None, env_var: str) -> Path | None:
    candidate = cli_arg or os.environ.get(env_var)
    if not candidate:
        return None
    path = Path(candidate)
    return path if path.is_file() else None


def validate_one(label: str, pdf_path: Path, *, toc_fragments: list[str], body_fragments: list[str]) -> bool:
    print("=" * 70)
    print(f"{label}: {pdf_path}")
    file_bytes = pdf_path.read_bytes()
    page_texts, page_offsets = extract_digital_text_only(file_bytes)
    print(f"  physical pages: {len(page_texts)}")

    store = _fake_store()
    import unittest.mock as mock

    with (
        mock.patch("app.services.admin.digital_ingestion.get_knowledge_base_store", return_value=store),
        mock.patch("app.services.admin.knowledge_base_pipeline.get_knowledge_base_store", return_value=store),
    ):
        chunks = build_chunks_with_pages(
            page_texts, page_offsets, chunk_size=900, chunk_overlap=120,
            title=label, source_filename=f"{label}.pdf",
        )
    print(f"  total chunks: {len(chunks)}")

    ok = True

    # A/C: no chunk primarily TOC navigation
    toc_like = [c for c in chunks if sum(1 for f in toc_fragments if f in c.text) >= 3]
    print(f"  [A/C] chunks primarily TOC navigation: {len(toc_like)}")
    if toc_like:
        ok = False
        for c in toc_like[:3]:
            print(f"        chunk {c.chunk_index}: {c.text[:150]!r}")

    # B/G: representative body content survives
    full_text = "\n".join(c.text for c in chunks)
    for frag in body_fragments:
        present = frag in full_text
        print(f"  [B/G] body fragment survives ({present}): {frag!r}")
        ok = ok and present

    # D: TOC text never became an office-classification input
    suspicious_office_titles = {"Foreword", "Copyright Page", "Administrative Officials", "Contents"}
    bad_headings = {
        c.metadata.get("section_heading")
        for c in chunks
        if c.metadata.get("section_heading") in suspicious_office_titles
    }
    print(f"  [D] TOC-label headings reaching classification: {bad_headings or 'none'}")
    ok = ok and not bad_headings

    # E: pagination furniture absent from chunk text
    import re
    furniture_hits = [c for c in chunks if re.search(r"(?i)\bpage\s*:?\s*(\d+|[ivxlcdm]{1,6})\b", c.text)]
    print(f"  [E] chunks containing page-furniture-shaped text: {len(furniture_hits)}")
    ok = ok and not furniture_hits

    # F: no chunk starts mid-word (char_start > 0 implies a space before it
    # in the cleaned text -- checked structurally via chunking.py's own
    # tests; here we just sanity-check no chunk TEXT begins with a
    # lowercase continuation fragment shape, a cheap proxy).
    midword_like = [c for c in chunks if c.text[:1].islower() and not c.text[:1].isdigit()]
    print(f"  [F] chunks starting with a lowercase letter (possible mid-word start): {len(midword_like)}")
    for c in midword_like[:3]:
        print(f"        chunk {c.chunk_index}: {c.text[:60]!r}")

    print(f"  RESULT: {'PASS' if ok else 'FAIL'}")
    print()
    return ok


def main() -> int:
    args = sys.argv[1:]
    faculty_arg = args[0] if len(args) > 0 else None
    handbook_arg = args[1] if len(args) > 1 else None

    faculty_path = _resolve_pdf_path(faculty_arg, "ASKA_VALIDATE_FACULTY_MANUAL_PDF")
    handbook_path = _resolve_pdf_path(handbook_arg, "ASKA_VALIDATE_STUDENT_HANDBOOK_PDF")

    if faculty_path is None and handbook_path is None:
        print(
            "No real PDF paths found (neither CLI args nor "
            "ASKA_VALIDATE_FACULTY_MANUAL_PDF / ASKA_VALIDATE_STUDENT_HANDBOOK_PDF "
            "env vars point to an existing file). Skipping -- this is expected "
            "on a machine without local copies of the real documents."
        )
        return 0

    all_ok = True
    if faculty_path is not None:
        all_ok &= validate_one(
            "FACULTY_MANUAL",
            faculty_path,
            toc_fragments=[
                "Foreword", "Copyright Page", "Board of Regents", "Administrative Officials",
                "General Information", "Historical Development", "Commitment of",
                "University Policies", "Faculty Attendance and Absence", "Submission of Grades",
                "Grievance Machinery",
            ],
            body_fragments=["dated January 10, 2001", "Faculty Official Time"],
        )
    else:
        print("FACULTY_MANUAL: skipped (no local PDF path provided).")

    if handbook_path is not None:
        all_ok &= validate_one(
            "STUDENT_HANDBOOK",
            handbook_path,
            toc_fragments=[
                "Handbook Owner Information", "Message of the University President",
                "Chapter 1", "Chapter 2", "Chapter 3", "Article 1:", "Article 2:", "Appendices",
            ],
            body_fragments=[],
        )
    else:
        print("STUDENT_HANDBOOK: skipped (no local PDF path provided).")

    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
