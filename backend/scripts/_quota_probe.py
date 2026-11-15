"""One-shot Gemini embed quota probe."""
from __future__ import annotations

import time


def main() -> int:
    from app.services.embeddings import get_embedding_function

    ef = get_embedding_function()
    t0 = time.time()
    try:
        vectors = ef(["quota probe: citizen charter fitness facility"])
        print("OK dim=", len(vectors[0]), "elapsed_s=", round(time.time() - t0, 2))
        return 0
    except Exception as exc:
        print("FAIL", type(exc).__name__, str(exc)[:240])
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
