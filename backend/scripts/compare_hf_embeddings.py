"""Manual, OPTIONAL compatibility check: local sentence-transformers output
vs. Hugging Face's hosted inference router, for intfloat/multilingual-e5-small.

Not run automatically by anything (not a test, not part of startup). Uses
only synthetic, non-institutional strings and never touches Chroma or any
real document/ticket/KB data.

Usage (from backend/ with venv active):

    set ASKA_HF_TOKEN=hf_your_token_here
    python scripts/compare_hf_embeddings.py

Reads ASKA_HF_TOKEN (or HF_TOKEN as a fallback) from the environment. Never
prints the token, in any form — not even partially.
"""

from __future__ import annotations

import math
import os
import sys

SYNTHETIC_PAIRS = [
    (
        "query: What are the requirements for graduation?",
        "passage: Students must complete all academic requirements before graduation.",
    ),
    (
        "query: How do I enroll for the semester?",
        "passage: Enrollment requires a signed registration form submitted to the registrar.",
    ),
]


def _get_token() -> str | None:
    return (os.environ.get("ASKA_HF_TOKEN") or os.environ.get("HF_TOKEN") or "").strip() or None


def _local_vectors(texts: list[str]) -> list[list[float]]:
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer("intfloat/multilingual-e5-small", device="cpu")
    return model.encode(texts, normalize_embeddings=True, show_progress_bar=False).tolist()


def _remote_vectors(texts: list[str], token: str) -> list[list[float]]:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from app.services.embeddings import HFRemoteEmbeddingFunction

    ef = HFRemoteEmbeddingFunction(token=token)
    # _encode expects already-prefixed text (same as what __call__/embed_query
    # produce internally) -- passing already-prefixed synthetic strings here
    # mirrors exactly what the app sends, with no double-prefixing.
    return ef._encode(texts)


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def main() -> int:
    token = _get_token()
    if not token:
        print(
            "ASKA_HF_TOKEN (or HF_TOKEN) is not set in the environment. "
            "Set it and re-run this script."
        )
        return 1

    texts = [t for pair in SYNTHETIC_PAIRS for t in pair]
    print(f"Comparing {len(texts)} synthetic strings (no institutional data)...")

    local_vectors = _local_vectors(texts)
    remote_vectors = _remote_vectors(texts, token)

    if len(local_vectors) != len(remote_vectors):
        print(
            f"MISMATCH: local returned {len(local_vectors)} vectors, "
            f"remote returned {len(remote_vectors)}."
        )
        return 2

    print()
    print(f"{'label':<40} {'dim(local==remote)':<20} {'cosine':<14} {'max|diff|':<14} {'mean|diff|'}")
    for text, local_vec, remote_vec in zip(texts, local_vectors, remote_vectors):
        dims_match = len(local_vec) == len(remote_vec)
        cosine = _cosine(local_vec, remote_vec) if dims_match else float("nan")
        if dims_match:
            diffs = [abs(a - b) for a, b in zip(local_vec, remote_vec)]
            max_abs_diff = max(diffs)
            mean_abs_diff = sum(diffs) / len(diffs)
        else:
            max_abs_diff = mean_abs_diff = float("nan")
        label = text[:37] + "..." if len(text) > 40 else text
        dims_label = f"{len(local_vec)}=={len(remote_vec)}" if dims_match else "MISMATCH"
        print(f"{label:<40} {dims_label:<20} {cosine:<14.10f} {max_abs_diff:<14.2e} {mean_abs_diff:.2e}")

    print()
    print("Reminder: this is a point-in-time manual check against whatever model")
    print("revision HF's hosted router currently serves -- HF does not let us pin")
    print("an exact revision, so re-run this periodically rather than trusting a")
    print("single past result indefinitely.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
