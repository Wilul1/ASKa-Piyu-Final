from __future__ import annotations

import pytest

from app.services.evaluation.classification_metrics import EmptyDatasetError
from app.services.evaluation.confusion_matrix import build_confusion_matrix


def test_binary_confusion_matrix_cell_values():
    y_true = ["pos", "pos", "neg", "neg"]
    y_pred = ["pos", "neg", "neg", "neg"]
    cm = build_confusion_matrix(y_true, y_pred)
    assert cm.labels == ("neg", "pos")
    index = {label: i for i, label in enumerate(cm.labels)}
    # true=pos,pred=pos -> 1 ; true=pos,pred=neg -> 1 ; true=neg,pred=neg -> 2
    assert cm.matrix[index["pos"]][index["pos"]] == 1
    assert cm.matrix[index["pos"]][index["neg"]] == 1
    assert cm.matrix[index["neg"]][index["neg"]] == 2
    assert cm.matrix[index["neg"]][index["pos"]] == 0
    assert cm.case_count == 4


def test_multiclass_confusion_matrix_diagonal_counts_correct_predictions():
    y_true = ["a", "b", "c", "a", "b", "c"]
    y_pred = ["a", "b", "c", "a", "b", "c"]
    cm = build_confusion_matrix(y_true, y_pred)
    index = {label: i for i, label in enumerate(cm.labels)}
    for label in ("a", "b", "c"):
        assert cm.matrix[index[label]][index[label]] == 2
    total_off_diagonal = sum(
        cm.matrix[i][j] for i in range(len(cm.labels)) for j in range(len(cm.labels)) if i != j
    )
    assert total_off_diagonal == 0


def test_explicit_label_order_is_respected():
    cm = build_confusion_matrix(["a", "b"], ["a", "b"], labels=["b", "a"])
    assert cm.labels == ("b", "a")


def test_as_dict_round_trips_plain_json_safe_types():
    cm = build_confusion_matrix(["a", "b"], ["a", "a"])
    payload = cm.as_dict()
    assert payload["labels"] == list(cm.labels)
    assert payload["matrix"] == [list(row) for row in cm.matrix]
    assert payload["case_count"] == 2


def test_empty_dataset_raises():
    with pytest.raises(EmptyDatasetError):
        build_confusion_matrix([], [])


def test_mismatched_lengths_raise_value_error():
    with pytest.raises(ValueError):
        build_confusion_matrix(["a", "b"], ["a"])
