"""Restore public KB articles after RAG fail-close or Chroma drift.

Examples (from backend/ with venv active):

  python scripts/restore_public_kb_articles.py
  python scripts/restore_public_kb_articles.py --apply
  python scripts/restore_public_kb_articles.py --apply --drafts-only
  python scripts/restore_public_kb_articles.py --apply --stale-only

Default is dry-run (no writes).
"""

from __future__ import annotations

import argparse
import json
import sys

from app.db.session import get_session_factory
from app.services.kb_public_restore import restore_public_kb_articles


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write changes (default is dry-run).",
    )
    parser.add_argument(
        "--drafts-only",
        action="store_true",
        help="Only attempt to republish unpublished drafts.",
    )
    parser.add_argument(
        "--stale-only",
        action="store_true",
        help="Only re-index published articles with rag_indexed=false.",
    )
    args = parser.parse_args()
    if args.drafts_only and args.stale_only:
        print("Choose at most one of --drafts-only / --stale-only.", file=sys.stderr)
        return 2

    republish_drafts = not args.stale_only
    reindex_stale = not args.drafts_only
    session = get_session_factory()()
    try:
        report = restore_public_kb_articles(
            session,
            republish_drafts=republish_drafts,
            reindex_stale=reindex_stale,
            dry_run=not args.apply,
        )
    finally:
        session.close()

    print(json.dumps(report, indent=2, ensure_ascii=False))
    if not args.apply:
        print(
            "\nDry-run only. Re-run with --apply to restore public KB / Ask indexing.",
            file=sys.stderr,
        )
    failed = len(report.get("stale_failed") or []) + len(report.get("draft_failed") or [])
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
