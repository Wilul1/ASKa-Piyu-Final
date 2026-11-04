from __future__ import annotations

import json

import pytest

from app.services.evaluation.datasets import (
    DatasetValidationError,
    load_classification_dataset,
    load_rag_dataset,
    load_retrieval_dataset,
)
from app.services.evaluation.evaluation_service import DEFAULT_RETRIEVAL_DATASET_PATH


def _write(tmp_path, name: str, payload: dict) -> str:
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def test_classification_dataset_splits_labeled_and_unlabeled(tmp_path):
    path = _write(
        tmp_path,
        "classification.json",
        {
            "dataset_version": "v1",
            "cases": [
                {
                    "case_id": "c1",
                    "text": "where do I enroll",
                    "true_label": "Enrollment",
                    "component": "classify_question",
                    "labeling_status": "labeled",
                },
                {
                    "case_id": "c2",
                    "text": "unlabeled example",
                    "labeling_status": "unlabeled",
                },
            ],
        },
    )
    result = load_classification_dataset(path)
    assert result.dataset_version == "v1"
    assert len(result.labeled_cases) == 1
    assert result.unlabeled_count == 1
    assert result.total_count == 2


def test_missing_required_field_on_labeled_case_raises(tmp_path):
    path = _write(
        tmp_path,
        "classification.json",
        {
            "dataset_version": "v1",
            "cases": [{"case_id": "c1", "labeling_status": "labeled"}],  # missing text/true_label/component
        },
    )
    with pytest.raises(DatasetValidationError):
        load_classification_dataset(path)


def test_missing_required_field_on_unlabeled_case_does_not_raise(tmp_path):
    path = _write(
        tmp_path,
        "classification.json",
        {"dataset_version": "v1", "cases": [{"labeling_status": "unlabeled"}]},
    )
    result = load_classification_dataset(path)
    assert result.unlabeled_count == 1
    assert result.labeled_cases == ()


def test_missing_dataset_version_raises(tmp_path):
    path = _write(tmp_path, "classification.json", {"cases": []})
    with pytest.raises(DatasetValidationError):
        load_classification_dataset(path)


def test_invalid_labeling_status_raises(tmp_path):
    path = _write(
        tmp_path,
        "classification.json",
        {"dataset_version": "v1", "cases": [{"labeling_status": "maybe"}]},
    )
    with pytest.raises(DatasetValidationError):
        load_classification_dataset(path)


def test_malformed_json_raises(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(DatasetValidationError):
        load_classification_dataset(str(path))


def test_missing_file_raises(tmp_path):
    with pytest.raises(DatasetValidationError):
        load_classification_dataset(str(tmp_path / "does_not_exist.json"))


def test_retrieval_dataset_requires_non_empty_relevant_ids_when_labeled(tmp_path):
    path = _write(
        tmp_path,
        "retrieval.json",
        {
            "dataset_version": "v1",
            "cases": [
                {
                    "query_id": "q1",
                    "query": "how do I enroll",
                    "relevant_ids": [],
                    "labeling_status": "labeled",
                }
            ],
        },
    )
    with pytest.raises(DatasetValidationError):
        load_retrieval_dataset(path)


def test_default_retrieval_dataset_is_12_question_v2():
    result = load_retrieval_dataset(DEFAULT_RETRIEVAL_DATASET_PATH)
    assert result.dataset_version == "2026-11-04-v2-human-reviewed-rag-benchmark-q1-q12"
    assert len(result.labeled_cases) == 12
    assert result.unlabeled_count == 0


def test_retrieval_dataset_accepts_valid_labeled_case(tmp_path):
    path = _write(
        tmp_path,
        "retrieval.json",
        {
            "dataset_version": "v1",
            "cases": [
                {
                    "query_id": "q1",
                    "query": "how do I enroll",
                    "relevant_ids": ["chunk-1"],
                    "labeling_status": "labeled",
                }
            ],
        },
    )
    result = load_retrieval_dataset(path)
    assert len(result.labeled_cases) == 1


def test_rag_dataset_allows_optional_reference_answer(tmp_path):
    path = _write(
        tmp_path,
        "rag.json",
        {
            "dataset_version": "v1",
            "cases": [
                {"case_id": "r1", "question": "What is the gambling penalty?", "labeling_status": "labeled"}
            ],
        },
    )
    result = load_rag_dataset(path)
    assert len(result.labeled_cases) == 1
    assert "reference_answer" not in result.labeled_cases[0]
