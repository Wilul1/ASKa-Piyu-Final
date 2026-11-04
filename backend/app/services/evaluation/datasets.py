"""Labeled evaluation dataset loading and validation.

Every dataset file is a JSON object::

    {"dataset_version": "...", "cases": [{"labeling_status": "labeled"|"unlabeled", ...}, ...]}

Evaluation runs operate ONLY on cases with ``labeling_status == "labeled"``.
Unlabeled cases are counted and reported as excluded -- never silently
treated as wrong, never silently skipped without being counted. This
mirrors the honesty pattern already established in
``backend/scripts/citation_grounding_baseline.py`` (every case there is
still ``excluded_unlabeled``), per the Phase 1 audit finding that this
system must surface, not hide.

This module never invents a label: a case missing required fields for its
kind is rejected (raised as ``DatasetValidationError`` naming the case),
never defaulted or guessed.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LABELED = "labeled"
UNLABELED = "unlabeled"
_VALID_LABELING_STATUSES = {LABELED, UNLABELED}


class DatasetValidationError(ValueError):
    """A dataset file is malformed, or a case is missing a required field."""


@dataclass(frozen=True)
class DatasetLoadResult:
    dataset_version: str
    kind: str
    labeled_cases: tuple[dict[str, Any], ...]
    unlabeled_count: int
    total_count: int
    # sha256 of the dataset file's raw bytes -- byte-level reproducibility
    # evidence for a persisted run's config, independent of dataset_version
    # (a human-assigned label that could be bumped without the file
    # actually changing, or left stale after an edit). Defaults to "" only
    # for DatasetLoadResult instances built directly in tests, never for a
    # real file load below.
    sha256: str = ""


def _read_dataset_file(path: Path) -> tuple[dict[str, Any], str]:
    if not path.exists():
        raise DatasetValidationError(f"Dataset file not found: {path}")
    raw_bytes = path.read_bytes()
    try:
        payload = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DatasetValidationError(f"Dataset file {path} is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise DatasetValidationError(f"Dataset file {path} must contain a JSON object at the top level.")
    return payload, hashlib.sha256(raw_bytes).hexdigest()


def _split_labeled(
    *, path: Path, kind: str, payload: dict[str, Any], sha256: str,
    cases: list[Any], required_fields: tuple[str, ...],
) -> DatasetLoadResult:
    labeled: list[dict[str, Any]] = []
    unlabeled_count = 0

    dataset_version = str(payload.get("dataset_version") or "").strip()
    if not dataset_version:
        raise DatasetValidationError(f"Dataset file {path} is missing a non-empty dataset_version.")

    for index, raw_case in enumerate(cases):
        if not isinstance(raw_case, dict):
            raise DatasetValidationError(f"Dataset file {path}, case index {index}: must be a JSON object.")
        status = str(raw_case.get("labeling_status") or "").strip().lower()
        if status not in _VALID_LABELING_STATUSES:
            raise DatasetValidationError(
                f"Dataset file {path}, case index {index}: labeling_status must be "
                f"one of {sorted(_VALID_LABELING_STATUSES)!r}, got {status!r}."
            )
        if status == UNLABELED:
            unlabeled_count += 1
            continue
        missing = [field for field in required_fields if not raw_case.get(field)]
        if missing:
            raise DatasetValidationError(
                f"Dataset file {path}, case index {index} (labeled): missing required "
                f"field(s) {missing} for kind={kind!r}."
            )
        labeled.append(raw_case)

    return DatasetLoadResult(
        dataset_version=dataset_version,
        kind=kind,
        labeled_cases=tuple(labeled),
        unlabeled_count=unlabeled_count,
        total_count=len(cases),
        sha256=sha256,
    )


def load_classification_dataset(path: str | Path) -> DatasetLoadResult:
    """Cases: case_id, text, true_label, component (classify_chunk|classify_question)."""
    path = Path(path)
    payload, sha256 = _read_dataset_file(path)
    cases = payload.get("cases")
    if not isinstance(cases, list):
        raise DatasetValidationError(f"Dataset file {path} must have a top-level 'cases' list.")
    return _split_labeled(
        path=path,
        kind="classification",
        payload=payload,
        sha256=sha256,
        cases=cases,
        required_fields=("case_id", "text", "true_label", "component"),
    )


def load_retrieval_dataset(path: str | Path) -> DatasetLoadResult:
    """Cases: query_id, query, relevant_ids (non-empty list)."""
    path = Path(path)
    payload, sha256 = _read_dataset_file(path)
    cases = payload.get("cases")
    if not isinstance(cases, list):
        raise DatasetValidationError(f"Dataset file {path} must have a top-level 'cases' list.")
    result = _split_labeled(
        path=path,
        kind="retrieval",
        payload=payload,
        sha256=sha256,
        cases=cases,
        required_fields=("query_id", "query", "relevant_ids"),
    )
    for case in result.labeled_cases:
        if not isinstance(case.get("relevant_ids"), list) or not case["relevant_ids"]:
            raise DatasetValidationError(
                f"Dataset file {path}, query_id={case.get('query_id')!r}: relevant_ids "
                "must be a non-empty list for a labeled retrieval case."
            )
    return result


def load_rag_dataset(path: str | Path) -> DatasetLoadResult:
    """Cases: case_id, question. reference_answer/gold_citation_ids are
    optional per-case (answer correctness / citation-set metrics are
    simply not computed for a case missing them -- see rag_metrics.py)."""
    path = Path(path)
    payload, sha256 = _read_dataset_file(path)
    cases = payload.get("cases")
    if not isinstance(cases, list):
        raise DatasetValidationError(f"Dataset file {path} must have a top-level 'cases' list.")
    return _split_labeled(
        path=path,
        kind="rag",
        payload=payload,
        sha256=sha256,
        cases=cases,
        required_fields=("case_id", "question"),
    )
