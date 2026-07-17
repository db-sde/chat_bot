"""Stable analytics event contracts for the DegreeBaba funnel.

The builders in this module are deliberately transport-agnostic.  They create
plain JSON-compatible dictionaries so the same event can be sent to an HTTP
sink, written to a dead-letter file, or asserted directly in a unit test.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any, Final

CHIP_SHOWN: Final = "chip_shown"
CHIP_TAPPED: Final = "chip_tapped"
CARD_SHOWN: Final = "card_shown"
CASCADE_STEP: Final = "cascade_step"
TOOL_STARTED: Final = "tool_started"
TOOL_STEP: Final = "tool_step"
TOOL_PARTIAL_REVEAL: Final = "tool_partial_reveal"
TOOL_LEAD_GATE: Final = "tool_lead_gate"
TOOL_COMPLETED: Final = "tool_completed"
LEAD_CAPTURED: Final = "lead_captured"
APPLY_CLICKED: Final = "apply_clicked"
COUNSELLOR_CLICKED: Final = "counsellor_clicked"
SESSION_START: Final = "session_start"
FLOW_ABANDONED: Final = "flow_abandoned"

EVENT_NAMES: Final = frozenset(
    {
        CHIP_SHOWN,
        CHIP_TAPPED,
        CARD_SHOWN,
        CASCADE_STEP,
        TOOL_STARTED,
        TOOL_STEP,
        TOOL_PARTIAL_REVEAL,
        TOOL_LEAD_GATE,
        TOOL_COMPLETED,
        LEAD_CAPTURED,
        APPLY_CLICKED,
        COUNSELLOR_CLICKED,
        SESSION_START,
        FLOW_ABANDONED,
    }
)
FUNNEL_STAGES: Final = frozenset({"top", "mid", "bottom"})
KEY_BLOCK_FIELDS: Final = (
    "session_id",
    "correlation_id",
    "ts",
    "event",
    "surface",
    "funnel_stage",
    "interaction_count",
    "entity",
    "config_version",
    "content_version",
)


def _required_text(name: str, value: object) -> str:
    rendered = str(value or "").strip()
    if not rendered:
        raise ValueError(f"{name} must be a non-empty string")
    return rendered


def _timestamp(value: datetime | str | None) -> str:
    if value is None:
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, datetime):
        moment = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return _required_text("ts", value)


def _entity(value: Mapping[str, Any] | None) -> dict[str, str | None]:
    """Normalize the always-present entity key without inventing an identity."""

    source = value or {}
    entity_type = str(source.get("type") or "").strip() or None
    entity_id = str(source.get("id") or "").strip() or None
    return {"type": entity_type, "id": entity_id}


def _ab(value: Mapping[str, Any] | None) -> dict[str, str] | None:
    if value is None:
        return None
    slot = _required_text("ab.slot", value.get("slot"))
    variant = _required_text("ab.variant", value.get("variant"))
    return {"slot": slot, "variant": variant}


def validate_event(event: Mapping[str, Any]) -> None:
    """Validate the stable key block of an already-built event."""

    missing = [field for field in KEY_BLOCK_FIELDS if field not in event]
    if missing:
        raise ValueError(f"analytics event is missing required fields: {', '.join(missing)}")
    if event["event"] not in EVENT_NAMES:
        raise ValueError(f"unknown analytics event: {event['event']!r}")
    for field in (
        "session_id",
        "correlation_id",
        "ts",
        "surface",
        "config_version",
        "content_version",
    ):
        _required_text(field, event[field])
    if event["funnel_stage"] not in FUNNEL_STAGES:
        raise ValueError("funnel_stage must be one of: top, mid, bottom")
    interaction_count = event["interaction_count"]
    if isinstance(interaction_count, bool) or not isinstance(interaction_count, int):
        raise ValueError("interaction_count must be an integer")
    if interaction_count < 0:
        raise ValueError("interaction_count must be non-negative")
    entity = event["entity"]
    if not isinstance(entity, Mapping) or not {"type", "id"}.issubset(entity):
        raise ValueError("entity must contain type and id keys")
    if event["event"] == CHIP_SHOWN:
        chips = event.get("chips")
        if not isinstance(chips, list) or not chips:
            raise ValueError("chip_shown must contain a non-empty chips array")
        if any(not isinstance(chip, Mapping) or not chip.get("chip_id") for chip in chips):
            raise ValueError("each chip_shown entry must contain chip_id")
    if event["event"] == CHIP_TAPPED:
        _required_text("chip_id", event.get("chip_id"))
        _required_text("chip_handler", event.get("chip_handler"))


def build_event(
    event: str,
    *,
    session_id: str,
    correlation_id: str,
    surface: str,
    funnel_stage: str,
    interaction_count: int,
    entity: Mapping[str, Any] | None,
    config_version: str,
    content_version: str,
    ts: datetime | str | None = None,
    chip_id: str | None = None,
    chip_handler: str | None = None,
    ab: Mapping[str, Any] | None = None,
    attributes: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one event with the complete, joinable analytics key block."""

    payload: dict[str, Any] = {
        "session_id": _required_text("session_id", session_id),
        "correlation_id": _required_text("correlation_id", correlation_id),
        "ts": _timestamp(ts),
        "event": _required_text("event", event),
        "surface": _required_text("surface", surface),
        "funnel_stage": _required_text("funnel_stage", funnel_stage),
        "interaction_count": interaction_count,
        "entity": _entity(entity),
        "config_version": _required_text("config_version", config_version),
        "content_version": _required_text("content_version", content_version),
    }
    if chip_id is not None:
        payload["chip_id"] = _required_text("chip_id", chip_id)
    if chip_handler is not None:
        payload["chip_handler"] = _required_text("chip_handler", chip_handler)
    normalized_ab = _ab(ab)
    if normalized_ab is not None:
        payload["ab"] = normalized_ab
    if attributes:
        reserved = set(KEY_BLOCK_FIELDS) | {"chip_id", "chip_handler", "ab"}
        collisions = reserved.intersection(attributes)
        if collisions:
            raise ValueError(
                "attributes cannot replace reserved fields: " + ", ".join(sorted(collisions))
            )
        payload.update(attributes)
    validate_event(payload)
    return payload


def build_chip_shown(
    chips: Iterable[str | Mapping[str, Any]],
    **key_block: Any,
) -> dict[str, Any]:
    """Build one batched impression event for a rendered chip set.

    Each entry preserves the chip id and, when present, its handler and stable
    A/B assignment. Duplicate chip ids are ignored after their first appearance.
    """

    rendered: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in chips:
        if isinstance(value, str):
            chip_id = _required_text("chips[].chip_id", value)
            handler = None
            assignment = None
        elif isinstance(value, Mapping):
            chip_id = _required_text("chips[].chip_id", value.get("chip_id") or value.get("id"))
            handler = str(value.get("chip_handler") or value.get("handler") or "").strip() or None
            raw_ab = value.get("ab")
            assignment = _ab(raw_ab if isinstance(raw_ab, Mapping) else None)
        else:
            raise ValueError("each chip impression must be a chip id or mapping")
        if chip_id in seen:
            continue
        seen.add(chip_id)
        item: dict[str, Any] = {"chip_id": chip_id}
        if handler is not None:
            item["chip_handler"] = handler
        if assignment is not None:
            item["ab"] = assignment
        rendered.append(item)
    if not rendered:
        raise ValueError("chip_shown requires at least one chip")
    attributes = dict(key_block.pop("attributes", {}) or {})
    attributes["chips"] = rendered
    return build_event(CHIP_SHOWN, attributes=attributes, **key_block)


__all__ = [
    "APPLY_CLICKED",
    "CARD_SHOWN",
    "CASCADE_STEP",
    "CHIP_SHOWN",
    "CHIP_TAPPED",
    "COUNSELLOR_CLICKED",
    "EVENT_NAMES",
    "FLOW_ABANDONED",
    "FUNNEL_STAGES",
    "KEY_BLOCK_FIELDS",
    "LEAD_CAPTURED",
    "SESSION_START",
    "TOOL_COMPLETED",
    "TOOL_LEAD_GATE",
    "TOOL_PARTIAL_REVEAL",
    "TOOL_STARTED",
    "TOOL_STEP",
    "build_chip_shown",
    "build_event",
    "validate_event",
]
