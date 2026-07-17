"""Non-blocking analytics delivery with a durable local dead letter."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections import deque
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from .events import validate_event

LOGGER = logging.getLogger(__name__)


class AnalyticsEmitter:
    """Accept events synchronously and deliver them outside the request path.

    ``emit`` only validates, snapshots, and performs ``Queue.put_nowait``. Network
    delivery and dead-letter writes run in owned background tasks. A configured
    sink uses one persistent ``httpx.AsyncClient`` for the emitter lifetime.
    """

    def __init__(
        self,
        settings: Any | None = None,
        *,
        url: str | None = None,
        secret: str | None = None,
        timeout_seconds: float | None = None,
        dead_letter_path: str | Path | None = None,
        queue_size: int | None = None,
        snapshot_size: int = 512,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        configured_url = (
            url if url is not None else getattr(settings, "analytics_webhook_url", None)
        )
        configured_secret = (
            secret if secret is not None else getattr(settings, "analytics_webhook_secret", None)
        )
        configured_timeout = (
            timeout_seconds
            if timeout_seconds is not None
            else getattr(settings, "analytics_timeout_seconds", 2.0)
        )
        configured_dead_letter = dead_letter_path or getattr(
            settings,
            "analytics_dead_letter_path",
            "var/analytics_dead_letters.jsonl",
        )
        configured_queue_size = (
            queue_size
            if queue_size is not None
            else getattr(settings, "analytics_queue_size", 1_024)
        )
        if configured_queue_size < 1:
            raise ValueError("analytics queue_size must be positive")
        if snapshot_size < 1:
            raise ValueError("analytics snapshot_size must be positive")
        if float(configured_timeout) <= 0:
            raise ValueError("analytics timeout_seconds must be positive")

        self.url = str(configured_url or "").strip() or None
        self.secret = str(configured_secret or "").strip() or None
        self.timeout = float(configured_timeout)
        self.dead_letter_path = Path(configured_dead_letter)
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(
            maxsize=int(configured_queue_size)
        )
        self._overflow: deque[tuple[dict[str, Any], Exception]] = deque(
            maxlen=int(configured_queue_size)
        )
        self._worker_task: asyncio.Task[None] | None = None
        self._overflow_task: asyncio.Task[None] | None = None
        self._delivery_inflight = 0
        self._overflow_inflight = 0
        self._maintenance_lock = asyncio.Lock()
        self._client = client
        self._owns_client = client is None
        self._write_lock = asyncio.Lock()
        self._snapshot_lock = threading.Lock()
        self._events: deque[dict[str, Any]] = deque(maxlen=snapshot_size)
        self._event_counts: dict[str, int] = {}
        self._accepted = 0
        self._delivered = 0
        self._disabled = 0
        self._dead_lettered = 0
        self._dropped = 0
        self._closing = False

    @staticmethod
    def _copy_event(event: Mapping[str, Any]) -> dict[str, Any]:
        """Take an immutable-by-convention JSON snapshot of caller-owned data."""

        return json.loads(json.dumps(dict(event), ensure_ascii=False))

    def _record(self, event: dict[str, Any], outcome: str) -> None:
        with self._snapshot_lock:
            if outcome == "accepted":
                self._accepted += 1
                self._events.append(self._copy_event(event))
                name = str(event.get("event") or "unknown")
                self._event_counts[name] = self._event_counts.get(name, 0) + 1
            elif outcome == "delivered":
                self._delivered += 1
            elif outcome == "disabled":
                self._disabled += 1
            elif outcome == "dead_lettered":
                self._dead_lettered += 1
            elif outcome == "dropped":
                self._dropped += 1

    def _ensure_worker(self, loop: asyncio.AbstractEventLoop) -> None:
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = loop.create_task(
                self._run(),
                name="degreebaba-analytics-emitter",
            )

    def _ensure_overflow_drain(self, loop: asyncio.AbstractEventLoop) -> None:
        if self._overflow_task is None or self._overflow_task.done():
            self._overflow_task = loop.create_task(
                self._drain_overflow(),
                name="degreebaba-analytics-overflow",
            )

    def emit(self, event: Mapping[str, Any]) -> bool:
        """Queue one event without awaiting network or filesystem I/O.

        The boolean reports whether the event entered the normal queue. ``False``
        means it was rejected or routed to the local dead-letter overflow path.
        No validation or delivery error is allowed to escape into a chat request.
        """

        try:
            payload = self._copy_event(event)
            validate_event(payload)
        except Exception as exc:
            LOGGER.warning("Rejected malformed analytics event: %s", exc)
            return False

        self._record(payload, "accepted")
        if not self.url:
            self._record(payload, "disabled")
            return True
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            LOGGER.warning("Analytics emit called without a running event loop")
            self._record(payload, "dropped")
            return False
        if self._closing:
            self._record(payload, "dropped")
            return False

        self._ensure_worker(loop)
        try:
            self._queue.put_nowait(payload)
        except asyncio.QueueFull:
            error = RuntimeError("analytics delivery queue is full")
            if len(self._overflow) == self._overflow.maxlen:
                self._record(payload, "dropped")
                LOGGER.error("Analytics queue and dead-letter overflow are full; event dropped")
                return False
            self._overflow.append((payload, error))
            self._ensure_overflow_drain(loop)
            return False
        return True

    def emit_many(self, events: Iterable[Mapping[str, Any]]) -> int:
        """Queue several events and return the number accepted by the normal path."""

        return sum(1 for event in events if self.emit(event))

    async def _http_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def _deliver(self, event: dict[str, Any]) -> None:
        headers = {"content-type": "application/json"}
        if self.secret:
            headers["authorization"] = f"Bearer {self.secret}"
        try:
            client = await self._http_client()
            response = await client.post(self.url or "", json=event, headers=headers)
            response.raise_for_status()
        except asyncio.CancelledError:
            await self._dead_letter(event, RuntimeError("analytics emitter closed during delivery"))
            raise
        except Exception as exc:
            LOGGER.error("Analytics sink delivery failed: %s", exc)
            await self._dead_letter(event, exc)
        else:
            self._record(event, "delivered")

    async def _run(self) -> None:
        while True:
            event = await self._queue.get()
            self._delivery_inflight += 1
            try:
                await self._deliver(event)
            finally:
                self._delivery_inflight -= 1
                self._queue.task_done()

    async def _drain_overflow(self) -> None:
        while self._overflow:
            event, error = self._overflow.popleft()
            self._overflow_inflight += 1
            try:
                await self._dead_letter(event, error)
            finally:
                self._overflow_inflight -= 1

    async def _dead_letter(self, event: dict[str, Any], exc: Exception) -> None:
        row = self._copy_event(event)
        row["delivery_failure"] = {
            "type": type(exc).__name__,
            "message": str(exc)[:500],
            "failed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }
        line = json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
        try:
            async with self._write_lock:
                await asyncio.to_thread(self._append_line, line)
        except Exception:
            self._record(event, "dropped")
            LOGGER.exception("Analytics dead-letter write failed")
        else:
            self._record(event, "dead_lettered")

    def _append_line(self, line: str) -> None:
        self.dead_letter_path.parent.mkdir(parents=True, exist_ok=True)
        with self.dead_letter_path.open("a", encoding="utf-8") as handle:
            handle.write(line)

    def snapshot(self) -> dict[str, Any]:
        """Return a deterministic in-memory diagnostic snapshot for tests/metrics."""

        with self._snapshot_lock:
            events = [self._copy_event(event) for event in self._events]
            accepted = self._accepted
            delivered = self._delivered
            disabled = self._disabled
            dead_lettered = self._dead_lettered
            dropped = self._dropped
            event_counts = dict(self._event_counts)
        return {
            "accepted": accepted,
            "delivered": delivered,
            "disabled": disabled,
            "dead_lettered": dead_lettered,
            "dropped": dropped,
            "queue_capacity": self._queue.maxsize,
            "queue_depth": self._queue.qsize(),
            "event_counts": event_counts,
            "events": events,
        }

    def reset_snapshot(self) -> None:
        """Reset process-local diagnostics without affecting queued delivery."""

        with self._snapshot_lock:
            self._events.clear()
            self._event_counts.clear()
            self._accepted = 0
            self._delivered = 0
            self._disabled = 0
            self._dead_lettered = 0
            self._dropped = 0

    async def _drain_pending(self) -> None:
        """Reach one event-loop-atomic point with no queued or in-flight work."""

        while True:
            loop = asyncio.get_running_loop()
            if self._overflow and (
                self._overflow_task is None or self._overflow_task.done()
            ):
                self._ensure_overflow_drain(loop)

            overflow_task = self._overflow_task
            if overflow_task is not None and not overflow_task.done():
                await asyncio.shield(overflow_task)

            await self._queue.join()

            # ``Queue.join`` can wake just before another task performs a
            # put-nowait.  The explicit in-flight counters close that race when
            # the worker has already taken the new item and qsize is zero.
            overflow_task = self._overflow_task
            if (
                self._queue.empty()
                and self._delivery_inflight == 0
                and not self._overflow
                and self._overflow_inflight == 0
                and (overflow_task is None or overflow_task.done())
            ):
                return

    @staticmethod
    def _validated_maintenance_timeout(timeout: float) -> float:
        value = float(timeout)
        if value <= 0:
            raise ValueError("analytics maintenance timeout must be positive")
        return value

    async def flush(self, *, timeout: float = 5.0) -> None:
        """Drain delivery and dead-letter work within a bounded maintenance call.

        This method is intended for shutdown, administration, and deterministic
        tests. Normal request handling continues to use non-blocking ``emit``.
        A timeout leaves the queued work and diagnostic counters intact.
        """

        bounded_timeout = self._validated_maintenance_timeout(timeout)

        async def flush_serialized() -> None:
            async with self._maintenance_lock:
                await self._drain_pending()

        await asyncio.wait_for(flush_serialized(), timeout=bounded_timeout)

    async def reset(self, *, timeout: float = 5.0) -> None:
        """Flush pre-reset work, then atomically clear process diagnostics.

        The clear happens synchronously at the first quiescent event-loop point,
        so a delivery from before this call cannot later appear in the new
        snapshot. If the bounded flush times out, no counters are cleared.
        """

        bounded_timeout = self._validated_maintenance_timeout(timeout)

        async def reset_serialized() -> None:
            async with self._maintenance_lock:
                await self._drain_pending()
                self.reset_snapshot()

        await asyncio.wait_for(reset_serialized(), timeout=bounded_timeout)

    async def close(self, *, timeout: float = 5.0) -> None:
        """Drain owned tasks and close the pooled HTTP client."""

        self._closing = True
        if self._overflow_task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(self._overflow_task), timeout=timeout)
            except TimeoutError:
                self._overflow_task.cancel()
                await asyncio.gather(self._overflow_task, return_exceptions=True)

        if self._worker_task is not None:
            try:
                await asyncio.wait_for(self._queue.join(), timeout=timeout)
            except TimeoutError:
                self._worker_task.cancel()
                await asyncio.gather(self._worker_task, return_exceptions=True)
                while True:
                    try:
                        event = self._queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    try:
                        await self._dead_letter(
                            event,
                            RuntimeError("analytics emitter close timeout"),
                        )
                    finally:
                        self._queue.task_done()
            else:
                self._worker_task.cancel()
                await asyncio.gather(self._worker_task, return_exceptions=True)

        if self._client is not None and self._owns_client:
            await self._client.aclose()


__all__ = ["AnalyticsEmitter"]
