"""Process-local counters for outcome-driven intent classification.

The collector deliberately stores no message text or session identifiers.  Its
epoch tokens make resets safe even when a request is already in flight: work
started before a reset cannot add calls or latency samples to the new epoch.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Literal

ActionSource = Literal[
    "deterministic_rule",
    "heuristic_regex",
    "gemini",
]


@dataclass(frozen=True, slots=True)
class MessageMetricToken:
    """Identify the metrics epoch in which a message began."""

    epoch: int
    message_id: int


@dataclass(frozen=True, slots=True)
class IntentCallMetricToken:
    """Track one classifier attempt until its outcome is known."""

    epoch: int
    call_id: int
    started_ns: int


class IntentMetrics:
    """Thread-safe, resettable intent-path metrics for one process."""

    def __init__(self, *, latency_sample_size: int = 2_048) -> None:
        if latency_sample_size < 1:
            raise ValueError("latency_sample_size must be positive")
        self._lock = threading.Lock()
        self._epoch = 0
        self._next_call_id = 0
        self._next_message_id = 0
        self._total_messages = 0
        self._llm_intent_calls = 0
        self._llm_intent_failures = 0
        self._active_calls: set[int] = set()
        self._action_recorded_messages: set[int] = set()
        self._action_sources = {
            "deterministic_rule": 0,
            "heuristic_regex": 0,
            "gemini": 0,
        }
        self._latencies_ms: deque[float] = deque(maxlen=latency_sample_size)

    def begin_message(self) -> MessageMetricToken:
        """Count a valid incoming chat message and return its epoch token."""

        with self._lock:
            self._total_messages += 1
            self._next_message_id += 1
            return MessageMetricToken(self._epoch, self._next_message_id)

    def record_action_source(
        self,
        message_token: MessageMetricToken,
        source: ActionSource,
    ) -> None:
        """Attribute a routed message to exactly one decision source."""

        with self._lock:
            if (
                message_token.epoch != self._epoch
                or message_token.message_id in self._action_recorded_messages
            ):
                return
            self._action_recorded_messages.add(message_token.message_id)
            self._action_sources[source] += 1

    def begin_llm_intent(
        self,
        message_token: MessageMetricToken,
    ) -> IntentCallMetricToken | None:
        """Count entry to the Gemini path unless the message predates a reset."""

        started_ns = time.perf_counter_ns()
        with self._lock:
            if message_token.epoch != self._epoch:
                return None
            self._llm_intent_calls += 1
            self._next_call_id += 1
            call_id = self._next_call_id
            self._active_calls.add(call_id)
            return IntentCallMetricToken(self._epoch, call_id, started_ns)

    def finish(
        self,
        call_token: IntentCallMetricToken | None,
        *,
        failed: bool,
    ) -> None:
        """Record one classifier outcome; stale or duplicate finishes are ignored."""

        if call_token is None:
            return
        elapsed_ms = (time.perf_counter_ns() - call_token.started_ns) / 1_000_000
        with self._lock:
            if (
                call_token.epoch != self._epoch
                or call_token.call_id not in self._active_calls
            ):
                return
            self._active_calls.remove(call_token.call_id)
            self._latencies_ms.append(max(elapsed_ms, 0.0))
            if failed:
                self._llm_intent_failures += 1

    def reset(self) -> None:
        """Start a clean epoch without accepting late results from the old one."""

        with self._lock:
            self._epoch += 1
            self._total_messages = 0
            self._llm_intent_calls = 0
            self._llm_intent_failures = 0
            self._active_calls.clear()
            self._action_recorded_messages.clear()
            for source in self._action_sources:
                self._action_sources[source] = 0
            self._latencies_ms.clear()

    def snapshot(self) -> dict[str, Any]:
        """Return an atomic counter/sample snapshot with computed rate and tails."""

        with self._lock:
            total_messages = self._total_messages
            llm_intent_calls = self._llm_intent_calls
            llm_intent_failures = self._llm_intent_failures
            action_sources = dict(self._action_sources)
            latencies_ms = sorted(self._latencies_ms)

        rate = llm_intent_calls / total_messages if total_messages else 0.0
        return {
            "total_messages": total_messages,
            "llm_intent_calls": llm_intent_calls,
            "llm_intent_call_rate": rate,
            "llm_intent_failures": llm_intent_failures,
            "action_from_deterministic_rule": action_sources["deterministic_rule"],
            "action_from_heuristic_regex": action_sources["heuristic_regex"],
            "action_from_gemini": action_sources["gemini"],
            "llm_intent_latency_ms": {
                "sample_count": len(latencies_ms),
                "p50": _nearest_rank(latencies_ms, 0.50),
                "p95": _nearest_rank(latencies_ms, 0.95),
            },
        }


def _nearest_rank(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    index = max(0, math.ceil(quantile * len(values)) - 1)
    return round(values[index], 3)


# The FastAPI application uses one collector for the life of each worker process.
intent_metrics = IntentMetrics()


__all__ = [
    "ActionSource",
    "IntentCallMetricToken",
    "IntentMetrics",
    "MessageMetricToken",
    "intent_metrics",
]
