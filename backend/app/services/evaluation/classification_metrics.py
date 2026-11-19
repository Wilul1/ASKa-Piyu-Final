"""Pure classification metrics: accuracy/precision/recall/F1, binary and
multiclass, computed one-vs-rest per class. No I/O -- takes plain label
lists in, returns plain dataclasses out, so this is fully unit-testable
without a database, Chroma, or a Groq key.
"""

from __future__ import annotations

from dataclasses import dataclass


class EmptyDatasetError(ValueError):
    """Raised when classification metrics are requested for zero cases."""


@dataclass(frozen=True)
class ClassMetrics:
    label: str
    true_positives: int
    true_negatives: int
    false_positives: int
    false_negatives: int
    support: int
    precision: float
    recall: float
    f1: float


@dataclass(frozen=True)
class ClassificationMetrics:
    case_count: int
    labels: tuple[str, ...]
    accuracy: float
    macro_precision: float
    macro_recall: float
    macro_f1: float
    weighted_precision: float
    weighted_recall: float
    weighted_f1: float
    per_class: tuple[ClassMetrics, ...]


def _safe_divide(numerator: float, denominator: float) -> float:
    """0.0 by convention when the denominator is zero (e.g. a label never
    predicted, or never actually present) -- never raises, never fabricates
    a value other than the documented zero."""
    if denominator == 0:
        return 0.0
    return numerator / denominator


def evaluate_classification(
    y_true: list[str],
    y_pred: list[str],
    *,
    labels: list[str] | None = None,
) -> ClassificationMetrics:
    """Multiclass-capable classification metrics via one-vs-rest per class.

    ``labels`` optionally fixes the label universe (and its order) --
    otherwise it is the sorted union of every label seen in ``y_true`` or
    ``y_pred``, so a label predicted but never true (or vice versa) still
    gets its own row rather than being silently dropped.
    """
    if len(y_true) != len(y_pred):
        raise ValueError(
            f"y_true and y_pred must be the same length (got {len(y_true)} and {len(y_pred)})."
        )
    if not y_true:
        raise EmptyDatasetError("Cannot compute classification metrics on an empty dataset.")

    label_universe = labels if labels is not None else sorted(set(y_true) | set(y_pred))
    case_count = len(y_true)
    correct = sum(1 for t, p in zip(y_true, y_pred) if t == p)
    accuracy = _safe_divide(correct, case_count)

    per_class: list[ClassMetrics] = []
    for label in label_universe:
        tp = sum(1 for t, p in zip(y_true, y_pred) if t == label and p == label)
        fp = sum(1 for t, p in zip(y_true, y_pred) if t != label and p == label)
        fn = sum(1 for t, p in zip(y_true, y_pred) if t == label and p != label)
        tn = case_count - tp - fp - fn
        support = tp + fn
        precision = _safe_divide(tp, tp + fp)
        recall = _safe_divide(tp, tp + fn)
        f1 = _safe_divide(2 * precision * recall, precision + recall)
        per_class.append(
            ClassMetrics(
                label=label,
                true_positives=tp,
                true_negatives=tn,
                false_positives=fp,
                false_negatives=fn,
                support=support,
                precision=round(precision, 4),
                recall=round(recall, 4),
                f1=round(f1, 4),
            )
        )

    class_count = len(per_class) or 1
    macro_precision = sum(c.precision for c in per_class) / class_count
    macro_recall = sum(c.recall for c in per_class) / class_count
    macro_f1 = sum(c.f1 for c in per_class) / class_count

    total_support = sum(c.support for c in per_class)
    weighted_precision = _safe_divide(
        sum(c.precision * c.support for c in per_class), total_support
    )
    weighted_recall = _safe_divide(sum(c.recall * c.support for c in per_class), total_support)
    weighted_f1 = _safe_divide(sum(c.f1 * c.support for c in per_class), total_support)

    return ClassificationMetrics(
        case_count=case_count,
        labels=tuple(label_universe),
        accuracy=round(accuracy, 4),
        macro_precision=round(macro_precision, 4),
        macro_recall=round(macro_recall, 4),
        macro_f1=round(macro_f1, 4),
        weighted_precision=round(weighted_precision, 4),
        weighted_recall=round(weighted_recall, 4),
        weighted_f1=round(weighted_f1, 4),
        per_class=tuple(per_class),
    )
