from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

import resilience.intent_metrics as metrics_module
from resilience.intent_metrics import IntentMetrics


def test_empty_snapshot_has_zero_rate_and_no_percentiles() -> None:
    metrics = IntentMetrics()

    assert metrics.snapshot() == {
        "total_messages": 0,
        "llm_intent_calls": 0,
        "llm_intent_call_rate": 0.0,
        "llm_intent_failures": 0,
        "action_from_deterministic_rule": 0,
        "action_from_heuristic_regex": 0,
        "action_from_gemini": 0,
        "llm_intent_latency_ms": {
            "sample_count": 0,
            "p50": None,
            "p95": None,
        },
    }


def test_snapshot_computes_rate_and_nearest_rank_percentiles(monkeypatch) -> None:
    metrics = IntentMetrics()
    clock_ns = iter(
        [
            0,
            10_000_000,
            100_000_000,
            120_000_000,
            200_000_000,
            230_000_000,
            300_000_000,
            400_000_000,
        ]
    )
    monkeypatch.setattr(metrics_module.time, "perf_counter_ns", lambda: next(clock_ns))

    for index in range(10):
        message_token = metrics.begin_message()
        source = (
            "deterministic_rule"
            if index < 6
            else "heuristic_regex" if index < 8 else "gemini"
        )
        metrics.record_action_source(message_token, source)  # type: ignore[arg-type]
        if index < 4:
            call_token = metrics.begin_llm_intent(message_token)
            metrics.finish(call_token, failed=index == 3)

    snapshot = metrics.snapshot()

    assert snapshot["total_messages"] == 10
    assert snapshot["llm_intent_calls"] == 4
    assert snapshot["llm_intent_call_rate"] == pytest.approx(0.4)
    assert snapshot["llm_intent_failures"] == 1
    assert snapshot["action_from_deterministic_rule"] == 6
    assert snapshot["action_from_heuristic_regex"] == 2
    assert snapshot["action_from_gemini"] == 2
    assert snapshot["llm_intent_latency_ms"] == {
        "sample_count": 4,
        "p50": 20.0,
        "p95": 100.0,
    }


def test_reset_rejects_stale_message_and_in_flight_call() -> None:
    metrics = IntentMetrics()
    stale_message = metrics.begin_message()
    stale_call = metrics.begin_llm_intent(stale_message)

    metrics.reset()
    metrics.finish(stale_call, failed=True)

    assert metrics.begin_llm_intent(stale_message) is None
    assert metrics.snapshot() == {
        "total_messages": 0,
        "llm_intent_calls": 0,
        "llm_intent_call_rate": 0.0,
        "llm_intent_failures": 0,
        "action_from_deterministic_rule": 0,
        "action_from_heuristic_regex": 0,
        "action_from_gemini": 0,
        "llm_intent_latency_ms": {
            "sample_count": 0,
            "p50": None,
            "p95": None,
        },
    }


def test_duplicate_finish_is_ignored() -> None:
    metrics = IntentMetrics()
    call = metrics.begin_llm_intent(metrics.begin_message())

    metrics.finish(call, failed=True)
    metrics.finish(call, failed=True)

    snapshot = metrics.snapshot()
    assert snapshot["llm_intent_failures"] == 1
    assert snapshot["llm_intent_latency_ms"]["sample_count"] == 1


def test_action_source_is_recorded_once_and_stale_tokens_are_ignored() -> None:
    metrics = IntentMetrics()
    message = metrics.begin_message()

    metrics.record_action_source(message, "deterministic_rule")
    metrics.record_action_source(message, "gemini")
    metrics.reset()
    metrics.record_action_source(message, "heuristic_regex")

    snapshot = metrics.snapshot()
    assert snapshot["action_from_deterministic_rule"] == 0
    assert snapshot["action_from_heuristic_regex"] == 0
    assert snapshot["action_from_gemini"] == 0


def test_concurrent_updates_are_exact_and_latency_sample_is_bounded() -> None:
    metrics = IntentMetrics(latency_sample_size=128)

    def record(index: int) -> None:
        message = metrics.begin_message()
        source = ("deterministic_rule", "heuristic_regex", "gemini")[index % 3]
        metrics.record_action_source(message, source)  # type: ignore[arg-type]
        call = metrics.begin_llm_intent(message)
        metrics.finish(call, failed=index % 7 == 0)

    with ThreadPoolExecutor(max_workers=16) as executor:
        list(executor.map(record, range(2_000)))

    snapshot = metrics.snapshot()
    assert snapshot["total_messages"] == 2_000
    assert snapshot["llm_intent_calls"] == 2_000
    assert snapshot["llm_intent_call_rate"] == 1.0
    assert snapshot["llm_intent_failures"] == 286
    assert snapshot["action_from_deterministic_rule"] == 667
    assert snapshot["action_from_heuristic_regex"] == 667
    assert snapshot["action_from_gemini"] == 666
    assert snapshot["llm_intent_latency_ms"]["sample_count"] == 128
    assert snapshot["llm_intent_latency_ms"]["p50"] >= 0
    assert snapshot["llm_intent_latency_ms"]["p95"] >= 0
