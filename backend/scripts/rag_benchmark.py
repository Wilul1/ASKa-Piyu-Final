"""Retrieval-quality benchmark for the live/configured Chroma knowledge base.

Runs a fixed set of known-answer questions (derived from the Citizen's
Charter, Student Handbook, and Faculty Manual extraction dumps reviewed
during the RAG accuracy rework) through the real retrieval + rerank pipeline
(``KnowledgeBaseStore.search``) and reports whether the expected chunk shows
up, and at what rank. No Groq/LLM call is made — this only measures
retrieval/rerank quality, so it is safe to run repeatedly and cheaply.

Usage (run from the backend/ directory, against whatever
``ASKA_CHROMA_PERSIST_DIR`` your .env points at):

    python -m scripts.rag_benchmark

Compare a "before" run (old embedding model) against an "after" run (new
embedding model, once re-indexed via POST /admin/kb/rebuild) to confirm the
embedding swap actually improved ranking rather than just changing it.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import settings
from app.services.chroma_store import RetrievedChunk, get_knowledge_base_store


@dataclass(frozen=True)
class BenchmarkCase:
    question: str
    # Any one of these substrings appearing in the top chunk's title/path/text
    # (case-insensitive) counts as a hit. Provide a few phrasings since exact
    # source wording varies.
    expect_any: tuple[str, ...]
    note: str = ""


# Facts verified against the source PDFs during manual article review earlier
# in this project. Keep this list small and high-confidence; add cases here
# whenever a real wrong-answer report comes in.
BENCHMARK_CASES: tuple[BenchmarkCase, ...] = (
    BenchmarkCase(
        "How much does it cost to get a copy of my Transcript of Records?",
        ("transcript of records", "tor"),
        note="Charter TOR fee card",
    ),
    BenchmarkCase(
        "How much is the fee for a second copy of my diploma?",
        ("diploma",),
        note="Charter diploma fee card, not Assessment of Fees",
    ),
    BenchmarkCase(
        "Which office handles student enrollment?",
        ("enrollment", "registrar"),
        note="Primary Enrollment service, not Assessment of Fees",
    ),
    BenchmarkCase(
        "How much does it cost to drop a subject?",
        ("dropping", "per unit"),
        note="Charter dropping-of-subjects fee should win over the older Handbook figure",
    ),
    BenchmarkCase(
        "What is the fee for library circulation service if my book is overdue?",
        ("library circulation", "overdue"),
    ),
    BenchmarkCase(
        "How long does the LSPU entrance examination take, including orientation?",
        ("entrance examination", "orientation"),
    ),
    BenchmarkCase(
        "What is the process for validating my student ID?",
        ("id validation", "student id", "identification card"),
    ),
    BenchmarkCase(
        "What happens if I fail more than 75% of my units?",
        ("scholastic delinquency", "dismissal", "probation"),
    ),
    BenchmarkCase(
        "How is faculty teaching load determined?",
        ("teaching load", "faculty manual", "time allotment"),
        note="Should prefer Faculty Manual over student academic-load sections",
    ),
    BenchmarkCase(
        "What are the responsibilities of an LSPU faculty member?",
        ("faculty responsibilit", "code of ethics", "commitment"),
        note="Faculty Manual, not narrow role-designation sections",
    ),
    BenchmarkCase(
        "What is honorable dismissal for a student?",
        ("honorable dismissal",),
    ),
    BenchmarkCase(
        "Who is the current LSPU president?",
        ("university president", "administrative officials"),
    ),
)


def _chunk_haystack(chunk: RetrievedChunk) -> str:
    metadata = chunk.metadata or {}
    parts = [
        chunk.title or "",
        str(metadata.get("source_section") or ""),
        str(metadata.get("canonical_topic") or ""),
        str(metadata.get("office") or ""),
        chunk.text or "",
    ]
    return " ".join(parts).lower()


def run_benchmark(top_k: int = 5) -> list[dict]:
    store = get_knowledge_base_store()
    if store.chunk_count == 0:
        raise SystemExit(
            "Knowledge base is empty (chroma_persist_dir="
            f"{settings.chroma_persist_dir!r}). Ingest documents first."
        )

    results: list[dict] = []
    for case in BENCHMARK_CASES:
        chunks = store.search(case.question, top_k=top_k)
        rank = None
        for index, chunk in enumerate(chunks, start=1):
            haystack = _chunk_haystack(chunk)
            if any(term.lower() in haystack for term in case.expect_any):
                rank = index
                break
        results.append(
            {
                "question": case.question,
                "note": case.note,
                "hit": rank is not None,
                "rank": rank,
                "top_title": chunks[0].title if chunks else None,
                "top_score": chunks[0].relevance_score if chunks else None,
            }
        )
    return results


def main() -> None:
    print(f"chroma_persist_dir={settings.chroma_persist_dir}")
    print(f"chroma_collection_name={settings.chroma_collection_name}")
    print(f"embedding_model_name={settings.embedding_model_name} (env={settings.env})")
    print()

    results = run_benchmark()
    hits = sum(1 for r in results if r["hit"])
    for r in results:
        status = f"HIT (rank {r['rank']})" if r["hit"] else "MISS"
        print(f"[{status}] {r['question']}")
        if r["note"]:
            print(f"    note: {r['note']}")
        print(f"    top result: {r['top_title']!r} (score={r['top_score']})")
    print()
    print(f"Score: {hits}/{len(results)} hits")


if __name__ == "__main__":
    main()
