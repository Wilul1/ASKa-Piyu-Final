"""Attach office ids to tickets whose taxonomy label now resolves.

Dry-run is the default. Pass --apply to write.

Never uses the OSA default fallback: tickets whose label still has no
seeded office stay in Needs Routing.
"""

from __future__ import annotations

import argparse

from app.db.session import get_session_factory, initialize_database
from app.services.ticket_office_resolver import backfill_unresolved_ticket_offices


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill unresolved ticket office ids.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write resolved office ids. Without this flag, only print what would change.",
    )
    args = parser.parse_args()

    initialize_database()
    session = get_session_factory()()
    try:
        updated = backfill_unresolved_ticket_offices(session)
        if not updated:
            print("No unresolved tickets could be attached to a seeded office.")
            session.rollback()
            return
        for ticket_id, previous, office_name in updated:
            print(f"{ticket_id}: {previous!r} -> {office_name}")
        if args.apply:
            session.commit()
            print(f"Applied {len(updated)} ticket office assignment(s).")
        else:
            session.rollback()
            print(f"Dry-run: {len(updated)} ticket(s) would be updated. Re-run with --apply to write.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
