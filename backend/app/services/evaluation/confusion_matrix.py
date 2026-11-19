"""Pure confusion matrix construction for genuine classification tasks only
(classify_chunk / classify_question). Never used for retrieval (Hit@K) or
RAG (faithfulness/relevancy) metrics -- those are not classification and
never produce a confusion matrix anywhere in this evaluation system.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.evaluation.classification_metrics import EmptyDatasetError


@dataclass(frozen=True)
class ConfusionMatrix:
    labels: tuple[str, ...]
    # matrix[i][j] = count of cases with true label labels[i] predicted as labels[j]
    matrix: tuple[tuple[int, ...], ...]
    case_count: int

    def as_dict(self) -> dict:
        return {
            "labels": list(self.labels),
            "matrix": [list(row) for row in self.matrix],
            "case_count": self.case_count,
        }


def build_confusion_matrix(
    y_true: list[str],
    y_pred: list[str],
    *,
    labels: list[str] | None = None,
) -> ConfusionMatrix:
    if len(y_true) != len(y_pred):
        raise ValueError(
            f"y_true and y_pred must be the same length (got {len(y_true)} and {len(y_pred)})."
        )
    if not y_true:
        raise EmptyDatasetError("Cannot build a confusion matrix from an empty dataset.")

    label_universe = labels if labels is not None else sorted(set(y_true) | set(y_pred))
    index_of = {label: i for i, label in enumerate(label_universe)}
    size = len(label_universe)
    rows = [[0] * size for _ in range(size)]
    for true_label, pred_label in zip(y_true, y_pred):
        rows[index_of[true_label]][index_of[pred_label]] += 1

    return ConfusionMatrix(
        labels=tuple(label_universe),
        matrix=tuple(tuple(row) for row in rows),
        case_count=len(y_true),
    )
