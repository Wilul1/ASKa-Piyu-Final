"""Unit tests for app.services.evaluation.classification_metrics.

Pure functions only -- no database, no Chroma, no Groq key required.
"""
from __future__ import annotations

import pytest

from app.services.evaluation.classification_metrics import (
    EmptyDatasetError,
    evaluate_classification,
)


def test_perfect_binary_predictions_score_1_0_everywhere():
    y_true = ["spam", "ham", "spam", "ham"]
    y_pred = ["spam", "ham", "spam", "ham"]
    metrics = evaluate_classification(y_true, y_pred)
    assert metrics.accuracy == 1.0
    assert metrics.macro_precision == 1.0
    assert metrics.macro_recall == 1.0
    assert metrics.macro_f1 == 1.0
    assert metrics.case_count == 4


def test_multiclass_metrics_match_hand_computed_values():
    # 3 classes, 6 cases, one confusion: a true "b" predicted as "c".
    y_true = ["a", "a", "b", "b", "c", "c"]
    y_pred = ["a", "a", "b", "c", "c", "c"]
    metrics = evaluate_classification(y_true, y_pred)
    assert metrics.accuracy == pytest.approx(5 / 6, abs=1e-4)

    by_label = {c.label: c for c in metrics.per_class}
    assert by_label["a"].precision == 1.0
    assert by_label["a"].recall == 1.0
    assert by_label["b"].true_positives == 1
    assert by_label["b"].false_negatives == 1
    assert by_label["b"].recall == pytest.approx(0.5, abs=1e-4)
    # c: both true "c" cases are correctly predicted "c" (tp=2), plus one
    # false positive from the misclassified true "b" (predicted "c").
    assert by_label["c"].true_positives == 2
    assert by_label["c"].false_positives == 1
    assert by_label["c"].precision == pytest.approx(2 / 3, abs=1e-4)
    assert by_label["c"].recall == pytest.approx(1.0, abs=1e-4)


def test_label_never_predicted_gets_zero_precision_not_a_crash():
    y_true = ["a", "a", "b"]
    y_pred = ["a", "a", "a"]  # "b" never predicted
    metrics = evaluate_classification(y_true, y_pred)
    by_label = {c.label: c for c in metrics.per_class}
    assert by_label["b"].true_positives == 0
    assert by_label["b"].false_negatives == 1
    assert by_label["b"].precision == 0.0
    assert by_label["b"].recall == 0.0
    assert by_label["b"].f1 == 0.0


def test_label_only_in_predictions_still_gets_its_own_row():
    y_true = ["a", "a"]
    y_pred = ["a", "b"]  # "b" predicted but never true
    metrics = evaluate_classification(y_true, y_pred)
    assert "b" in metrics.labels
    by_label = {c.label: c for c in metrics.per_class}
    assert by_label["b"].false_positives == 1
    assert by_label["b"].support == 0


def test_empty_dataset_raises_rather_than_returning_fabricated_metrics():
    with pytest.raises(EmptyDatasetError):
        evaluate_classification([], [])


def test_mismatched_lengths_raise_value_error():
    with pytest.raises(ValueError):
        evaluate_classification(["a", "b"], ["a"])


def test_weighted_average_accounts_for_class_support_imbalance():
    # 9 "a" (all correct) + 1 "b" (wrong) -- weighted F1 should be dominated by "a".
    y_true = ["a"] * 9 + ["b"]
    y_pred = ["a"] * 9 + ["a"]
    metrics = evaluate_classification(y_true, y_pred)
    assert metrics.weighted_f1 > metrics.macro_f1
