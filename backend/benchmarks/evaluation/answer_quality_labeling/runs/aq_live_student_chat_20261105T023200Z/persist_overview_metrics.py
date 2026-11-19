"""Attach durable human RAG overview metrics to the latest local evaluation run."""

from __future__ import annotations

from app.db.session import get_session_factory
from app.services.evaluation.human_rag_overview import apply_human_rag_overview_to_run
from app.services.evaluation.persistence import get_latest_run


def main() -> None:
    session = get_session_factory()()
    try:
        run = get_latest_run(session)
        if run is None or run.status != "completed":
            raise SystemExit(f"No completed evaluation run to attach metrics to (got {run}).")
        if not apply_human_rag_overview_to_run(session, run):
            raise SystemExit("Human overview metrics file is missing or incomplete.")
        session.commit()
        print(f"Attached durable human RAG overview metrics to run {run.id}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
