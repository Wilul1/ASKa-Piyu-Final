import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from app.services.evaluation.datasets import load_retrieval_dataset
from app.services.evaluation.evaluation_service import evaluate_retrieval
from app.services.evaluation.labeled_retrieval_store import (
    EXPECTED_LABELED_RETRIEVAL_CHUNK_COUNT,
    LABELED_RETRIEVAL_COLLECTION,
    LABELED_RETRIEVAL_INDEX_PATH,
    LabeledRetrievalStore,
)


ROOT = Path(__file__).resolve().parent
INDEX_PATH = LABELED_RETRIEVAL_INDEX_PATH
DATASET_PATH = ROOT / "benchmarks" / "evaluation" / "retrieval_relevance_dataset.json"
OUTPUT_DIR = ROOT / "benchmarks" / "results"
COLLECTION_NAME = LABELED_RETRIEVAL_COLLECTION
K = 5
CANDIDATE_POOL_SIZE = 20


def main():
    if not INDEX_PATH.exists():
        raise FileNotFoundError(f"Evaluation index not found: {INDEX_PATH}")
    if not DATASET_PATH.exists():
        raise FileNotFoundError(f"Retrieval dataset not found: {DATASET_PATH}")

    dataset = load_retrieval_dataset(DATASET_PATH)
    print(f"DATASET_LABELED_CASES={len(dataset.labeled_cases)}")
    print(f"DATASET_UNLABELED_CASES={dataset.unlabeled_count}")

    if not dataset.labeled_cases:
        raise RuntimeError("No labeled retrieval cases were loaded.")

    store = LabeledRetrievalStore()
    count = store.chunk_count
    print(f"EVALUATION_COLLECTION_COUNT={count}")

    if count != 691:
        raise RuntimeError(
            f"Expected 691 evaluation chunks, found {count}. "
            "Stopping rather than benchmarking an unexpected corpus."
        )

    embedding_result, reranker_result = evaluate_retrieval(
        dataset,
        store=store,
        k=K,
        candidate_pool_size=CANDIDATE_POOL_SIZE,
    )

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / f"retrieval_benchmark_{timestamp}.json"

    report = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset": str(DATASET_PATH),
        "index": str(INDEX_PATH),
        "collection": COLLECTION_NAME,
        "collection_count": count,
        "labeled_case_count": len(dataset.labeled_cases),
        "unlabeled_case_count": dataset.unlabeled_count,
        "k": K,
        "candidate_pool_size": CANDIDATE_POOL_SIZE,
        "embedding_only": asdict(embedding_result),
        "reranker": asdict(reranker_result),
    }

    output_path.write_text(
        json.dumps(report, indent=2, default=str),
        encoding="utf-8",
    )

    print("RETRIEVAL_BENCHMARK=COMPLETED")
    print(f"EMBEDDING_RESULT={json.dumps(asdict(embedding_result), default=str)}")
    print(f"RERANKER_RESULT={json.dumps(asdict(reranker_result), default=str)}")
    print(f"REPORT_PATH={output_path}")


if __name__ == "__main__":
    main()
