from __future__ import annotations

import pytest

from app.services.evaluation.classification_metrics import EmptyDatasetError
from app.services.evaluation.performance_metrics import CallRecord, evaluate_performance


def test_basic_success_failure_and_latency_stats():
    records = [
        CallRecord(success=True, latency_ms=100.0),
        CallRecord(success=True, latency_ms=200.0),
        CallRecord(success=False, latency_ms=50.0),
    ]
    metrics = evaluate_performance(records)
    assert metrics.call_count == 3
    assert metrics.success_count == 2
    assert metrics.failure_count == 1
    assert metrics.success_rate == pytest.approx(2 / 3, abs=1e-4)
    assert metrics.failure_rate == pytest.approx(1 / 3, abs=1e-4)
    assert metrics.avg_latency_ms == pytest.approx((100 + 200 + 50) / 3, abs=1e-2)
    assert metrics.median_latency_ms == 100.0


def test_first_call_in_run_and_warm_latency_reported_separately():
    records = [
        CallRecord(success=True, latency_ms=900.0, is_first_call_in_run=True),
        CallRecord(success=True, latency_ms=100.0, is_first_call_in_run=False),
        CallRecord(success=True, latency_ms=120.0, is_first_call_in_run=False),
    ]
    metrics = evaluate_performance(records)
    assert metrics.first_call_in_run_count == 1
    assert metrics.first_call_in_run_avg_latency_ms == pytest.approx(900.0, abs=1e-2)
    assert metrics.warm_call_count == 2
    assert metrics.warm_avg_latency_ms == pytest.approx(110.0, abs=1e-2)
    # Blended average must not be mistaken for either the first call or the warm calls alone.
    assert metrics.avg_latency_ms != metrics.warm_avg_latency_ms


def test_no_first_call_in_run_flagged_reports_none_not_zero():
    records = [CallRecord(success=True, latency_ms=100.0)]
    metrics = evaluate_performance(records)
    assert metrics.first_call_in_run_count == 0
    assert metrics.first_call_in_run_avg_latency_ms is None
    assert metrics.warm_avg_latency_ms == pytest.approx(100.0, abs=1e-2)


def test_token_usage_aggregation_ignores_missing_values():
    records = [
        CallRecord(success=True, latency_ms=10.0, prompt_tokens=100, completion_tokens=20),
        CallRecord(success=True, latency_ms=10.0, prompt_tokens=None, completion_tokens=None),
    ]
    metrics = evaluate_performance(records)
    assert metrics.total_prompt_tokens == 100
    assert metrics.total_completion_tokens == 20
    assert metrics.avg_prompt_tokens == pytest.approx(100.0, abs=1e-2)


def test_no_token_data_reports_none_averages_but_zero_totals():
    records = [CallRecord(success=True, latency_ms=10.0)]
    metrics = evaluate_performance(records)
    assert metrics.total_prompt_tokens == 0
    assert metrics.avg_prompt_tokens is None


def test_p95_latency_uses_numpy_percentile_semantics():
    records = [CallRecord(success=True, latency_ms=float(v)) for v in range(1, 101)]
    metrics = evaluate_performance(records)
    assert metrics.p95_latency_ms == pytest.approx(95.05, abs=0.5)


def test_empty_record_list_raises():
    with pytest.raises(EmptyDatasetError):
        evaluate_performance([])
