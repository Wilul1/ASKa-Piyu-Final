"""Dump global layout structure and chunks for a PDF. No Chroma writes.

Usage (from backend/):

    python scripts/inspect_pdf_layout.py path/to/file.pdf --out layout.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.services.common_representation.pipeline import inspect_pdf_bytes  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect global PDF layout extraction.")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--document-id", default=None)
    args = parser.parse_args()
    pdf_path = args.pdf
    if not pdf_path.is_file():
        print(f"PDF not found: {pdf_path}", file=sys.stderr)
        return 1
    document_id = args.document_id or pdf_path.stem
    report = inspect_pdf_bytes(
        pdf_path.read_bytes(),
        document_id=document_id,
        source_filename=pdf_path.name,
    )
    encoded = json.dumps(report, indent=2, ensure_ascii=False)
    if args.out is None:
        print(encoded)
    else:
        args.out.write_text(encoded, encoding="utf-8")
        print(
            f"Wrote {args.out} ({report['page_count']} pages, "
            f"{len(report['units'])} units, {len(report['chunks'])} chunks)",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
