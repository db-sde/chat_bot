from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest

from analytics import (
    CHIP_TAPPED,
    EVENT_NAMES,
    KEY_BLOCK_FIELDS,
    AnalyticsEmitter,
    build_chip_shown,
    build_event,
)


def _event(event: str = CHIP_TAPPED, **updates: object) -> dict[str, object]:
    values = {
        "session_id": "session-1",
        "correlation_id": "sess_on-1:turn_2",
        "surface": "answer:fees",
        "funnel_stage": "bottom",
        "interaction_count": 2,
        "entity": {"type": "course", "id": "course-nmims-mba"},
        "config_version": "2026-07-16",
        "content_version": "2026-07-16",
        "ts": datetime(2026, 7, 16, 10, 30, tzinfo=UTC),
        "chip_id": "roi_tool",
        "chip_handler": "tool_entry",
    }
    values.update(updates)
    return build_event(event, **values)  # type: ignore[arg-type]


def test_stable_taxonomy_and_full_key_block() -> None:
    event = _event()

    assert {
        "chip_shown",
        "chip_tapped",
        "card_shown",
        "cascade_step",
        "tool_started",
        "tool_step",
        "tool_partial_reveal",
        "tool_lead_gate",
        "tool_completed",
        "lead_captured",
        "apply_clicked",
        "counsellor_clicked",
        "session_start",
        "flow_abandoned",
    } == EVENT_NAMES
    assert set(KEY_BLOCK_FIELDS) <= event.keys()
    assert event["entity"] == {"type": "course", "id": "course-nmims-mba"}
    assert event["ts"] == "2026-07-16T10:30:00Z"


def test_chip_shown_batches_ids_handlers_and_ab_assignments() -> None:
    event = build_chip_shown(
        [
            {"chip_id": "eligibility", "handler": "get_eligibility"},
            {
                "chip_id": "roi_tool_ab",
                "handler": "tool_entry",
                "ab": {"slot": "roi_tool_ab", "variant": "b"},
            },
            "counsellor",
            "counsellor",
        ],
        session_id="session-1",
        correlation_id="sess_on-1:turn_2",
        surface="answer:fees",
        funnel_stage="bottom",
        interaction_count=2,
        entity={"type": "course", "id": "course-nmims-mba"},
        config_version="2026-07-16",
        content_version="2026-07-16",
    )

    assert event["event"] == "chip_shown"
    assert event["chips"] == [
        {"chip_id": "eligibility", "chip_handler": "get_eligibility"},
        {
            "chip_id": "roi_tool_ab",
            "chip_handler": "tool_entry",
            "ab": {"slot": "roi_tool_ab", "variant": "b"},
        },
        {"chip_id": "counsellor"},
    ]

    with pytest.raises(ValueError, match="chips array"):
        build_event(
            "chip_shown",
            session_id="session-1",
            correlation_id="sess_on-1:turn_2",
            surface="answer:fees",
            funnel_stage="bottom",
            interaction_count=2,
            entity={"type": "course", "id": "course-nmims-mba"},
            config_version="2026-07-16",
            content_version="2026-07-16",
        )


def test_optional_sink_configuration_is_read_additively_from_settings(tmp_path) -> None:
    path = tmp_path / "configured.jsonl"
    emitter = AnalyticsEmitter(
        SimpleNamespace(
            analytics_webhook_url="https://analytics.example/events",
            analytics_webhook_secret="secret",
            analytics_timeout_seconds=0.75,
            analytics_dead_letter_path=path,
            analytics_queue_size=7,
        )
    )

    assert emitter.url == "https://analytics.example/events"
    assert emitter.secret == "secret"
    assert emitter.timeout == 0.75
    assert emitter.dead_letter_path == path
    assert emitter.snapshot()["queue_capacity"] == 7


@pytest.mark.asyncio
async def test_unconfigured_sink_is_non_blocking_and_snapshot_is_resettable(tmp_path) -> None:
    emitter = AnalyticsEmitter(dead_letter_path=tmp_path / "unused.jsonl")

    assert emitter.emit(_event()) is True
    snapshot = emitter.snapshot()

    assert snapshot["accepted"] == 1
    assert snapshot["disabled"] == 1
    assert snapshot["queue_depth"] == 0
    assert snapshot["events"][0]["chip_id"] == "roi_tool"
    assert not (tmp_path / "unused.jsonl").exists()

    emitter.reset_snapshot()
    assert emitter.snapshot()["accepted"] == 0
    await emitter.close()


@pytest.mark.asyncio
async def test_http_failure_is_dead_lettered_without_raising(tmp_path) -> None:
    async def fail(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("hub unavailable")

    client = httpx.AsyncClient(transport=httpx.MockTransport(fail))
    path = tmp_path / "analytics.jsonl"
    emitter = AnalyticsEmitter(
        url="https://analytics.example/events",
        dead_letter_path=path,
        client=client,
    )

    assert emitter.emit(_event()) is True
    await emitter.close()

    row = json.loads(path.read_text(encoding="utf-8").strip())
    assert row["event"] == "chip_tapped"
    assert row["delivery_failure"]["type"] == "ConnectError"
    assert emitter.snapshot()["dead_lettered"] == 1
    await client.aclose()


@pytest.mark.asyncio
async def test_queue_overflow_uses_bounded_background_dead_letter(tmp_path) -> None:
    release = asyncio.Event()

    async def slow(_request: httpx.Request) -> httpx.Response:
        await release.wait()
        return httpx.Response(204)

    client = httpx.AsyncClient(transport=httpx.MockTransport(slow))
    path = tmp_path / "overflow.jsonl"
    emitter = AnalyticsEmitter(
        url="https://analytics.example/events",
        dead_letter_path=path,
        queue_size=1,
        client=client,
    )

    assert emitter.emit(_event(chip_id="first")) is True
    assert emitter.emit(_event(chip_id="overflow")) is False
    release.set()
    await emitter.close()

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [row["chip_id"] for row in rows] == ["overflow"]
    assert rows[0]["delivery_failure"]["message"] == "analytics delivery queue is full"
    assert emitter.snapshot()["delivered"] == 1
    await client.aclose()


@pytest.mark.asyncio
async def test_flush_waits_for_inflight_delivery_without_resetting_snapshot(tmp_path) -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow(_request: httpx.Request) -> httpx.Response:
        started.set()
        await release.wait()
        return httpx.Response(204)

    client = httpx.AsyncClient(transport=httpx.MockTransport(slow))
    emitter = AnalyticsEmitter(
        url="https://analytics.example/events",
        dead_letter_path=tmp_path / "unused.jsonl",
        client=client,
    )

    try:
        assert emitter.emit(_event()) is True
        await asyncio.wait_for(started.wait(), timeout=0.5)
        flush_task = asyncio.create_task(emitter.flush(timeout=0.5))
        await asyncio.sleep(0)
        assert flush_task.done() is False

        release.set()
        await flush_task

        snapshot = emitter.snapshot()
        assert snapshot["accepted"] == 1
        assert snapshot["delivered"] == 1
        assert snapshot["queue_depth"] == 0
    finally:
        release.set()
        await emitter.close()
        await client.aclose()


@pytest.mark.asyncio
async def test_async_reset_drains_delivery_before_clearing_snapshot(tmp_path) -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow(_request: httpx.Request) -> httpx.Response:
        started.set()
        await release.wait()
        return httpx.Response(204)

    client = httpx.AsyncClient(transport=httpx.MockTransport(slow))
    emitter = AnalyticsEmitter(
        url="https://analytics.example/events",
        dead_letter_path=tmp_path / "unused.jsonl",
        client=client,
    )

    try:
        assert emitter.emit(_event(chip_id="before-reset")) is True
        await asyncio.wait_for(started.wait(), timeout=0.5)
        reset_task = asyncio.create_task(emitter.reset(timeout=0.5))
        await asyncio.sleep(0)
        assert reset_task.done() is False

        release.set()
        await reset_task
        assert emitter.snapshot() == {
            "accepted": 0,
            "delivered": 0,
            "disabled": 0,
            "dead_lettered": 0,
            "dropped": 0,
            "queue_capacity": 1024,
            "queue_depth": 0,
            "event_counts": {},
            "events": [],
        }

        assert emitter.emit(_event(chip_id="after-reset")) is True
        await emitter.flush(timeout=0.5)
        snapshot = emitter.snapshot()
        assert snapshot["accepted"] == 1
        assert snapshot["delivered"] == 1
        assert snapshot["events"][0]["chip_id"] == "after-reset"
    finally:
        release.set()
        await emitter.close()
        await client.aclose()


@pytest.mark.asyncio
async def test_async_reset_timeout_preserves_pre_reset_counters(tmp_path) -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def blocked(_request: httpx.Request) -> httpx.Response:
        started.set()
        await release.wait()
        return httpx.Response(204)

    client = httpx.AsyncClient(transport=httpx.MockTransport(blocked))
    emitter = AnalyticsEmitter(
        url="https://analytics.example/events",
        dead_letter_path=tmp_path / "unused.jsonl",
        client=client,
    )

    try:
        assert emitter.emit(_event()) is True
        await asyncio.wait_for(started.wait(), timeout=0.5)

        with pytest.raises(TimeoutError):
            await emitter.reset(timeout=0.01)

        snapshot = emitter.snapshot()
        assert snapshot["accepted"] == 1
        assert snapshot["delivered"] == 0
        assert snapshot["event_counts"] == {"chip_tapped": 1}

        release.set()
        await emitter.flush(timeout=0.5)
        assert emitter.snapshot()["delivered"] == 1
    finally:
        release.set()
        await emitter.close()
        await client.aclose()


@pytest.mark.asyncio
async def test_async_reset_drains_overflow_dead_letter_before_clearing(tmp_path) -> None:
    release = asyncio.Event()

    async def slow(_request: httpx.Request) -> httpx.Response:
        await release.wait()
        return httpx.Response(204)

    client = httpx.AsyncClient(transport=httpx.MockTransport(slow))
    path = tmp_path / "overflow-reset.jsonl"
    emitter = AnalyticsEmitter(
        url="https://analytics.example/events",
        dead_letter_path=path,
        queue_size=1,
        client=client,
    )

    try:
        assert emitter.emit(_event(chip_id="queued")) is True
        assert emitter.emit(_event(chip_id="overflow")) is False
        reset_task = asyncio.create_task(emitter.reset(timeout=0.5))
        await asyncio.sleep(0)
        assert reset_task.done() is False

        release.set()
        await reset_task

        assert emitter.snapshot()["accepted"] == 0
        assert emitter.snapshot()["dead_lettered"] == 0
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        assert [row["chip_id"] for row in rows] == ["overflow"]
    finally:
        release.set()
        await emitter.close()
        await client.aclose()
