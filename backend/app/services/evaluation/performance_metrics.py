"""Pure performance metrics: latency (avg/median/P95, first-call-in-run vs
later calls), success/failure rate, token usage. No I/O -- takes a list of
already-recorded call outcomes in, returns a plain dataclass out.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.services.evaluation.classification_metrics import EmptyDatasetError


@dataclass(frozen=True)
class CallRecord:
    """One recorded model/API call's outcome.

    ``is_first_call_in_run`` marks the first call to a given model observed
    within one evaluation run -- real evidence from that run's own call
    sequence, never a claim about genuine infrastructure cold-boot state
    (the provider endpoint may already have been warm from unrelated
    traffic before the run started). Named deliberately NOT "cold_start"
    for that reason -- see ``evaluation_service.CallTracker``, which is
    the only thing that decides this value.
    """

    success: bool
    latency_ms: float
    is_first_call_in_run: bool = False
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


@dataclass(frozen=True)
class PerformanceMetrics:
    call_count: int
    success_count: int
    failure_count: int
    success_rate: float
    failure_rate: float
    avg_latency_ms: float
    median_latency_ms: float
    p95_latency_ms: float
    first_call_in_run_count: int
    first_call_in_run_avg_latency_ms: float | None
    warm_call_count: int
    warm_avg_latency_ms: float | None
    total_prompt_tokens: int
    total_completion_tokens: int
    avg_prompt_tokens: float | None
    avg_completion_tokens: float | None


def evaluate_performance(records: list[CallRecord]) -> PerformanceMetrics:
    if not records:
        raise EmptyDatasetError("Cannot compute performance metrics on an empty call set.")

    call_count = len(records)
    successes = [r for r in records if r.success]
    failures = [r for r in records if not r.success]
    latencies = [r.latency_ms for r in records]

    first_call_in_run = [r for r in records if r.is_first_call_in_run]
    warm = [r for r in records if not r.is_first_call_in_run]

    prompt_token_values = [r.prompt_tokens for r in records if r.prompt_tokens is not None]
    completion_token_values = [r.completion_tokens for r in records if r.completion_tokens is not None]

    return PerformanceMetrics(
        call_count=call_count,
        success_count=len(successes),
        failure_count=len(failures),
        success_rate=round(len(successes) / call_count, 4),
        failure_rate=round(len(failures) / call_count, 4),
        avg_latency_ms=round(float(np.mean(latencies)), 2),
        median_latency_ms=round(float(np.median(latencies)), 2),
        p95_latency_ms=round(float(np.percentile(latencies, 95)), 2),
        first_call_in_run_count=len(first_call_in_run),
        first_call_in_run_avg_latency_ms=(
            round(float(np.mean([r.latency_ms for r in first_call_in_run])), 2) if first_call_in_run else None
        ),
        warm_call_count=len(warm),
        warm_avg_latency_ms=(
            round(float(np.mean([r.latency_ms for r in warm])), 2) if warm else None
        ),
        total_prompt_tokens=sum(prompt_token_values),
        total_completion_tokens=sum(completion_token_values),
        avg_prompt_tokens=(
            round(sum(prompt_token_values) / len(prompt_token_values), 2) if prompt_token_values else None
        ),
        avg_completion_tokens=(
            round(sum(completion_token_values) / len(completion_token_values), 2)
            if completion_token_values
            else None
        ),
    )
