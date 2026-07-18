#!/usr/bin/env python3
"""Validate chip and node maps together before deployment."""

from __future__ import annotations

import sys
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from funnel import (  # noqa: E402
    DEFAULT_CHIP_MAP_PATH,
    DEFAULT_FLOW_MAP_PATH,
    SPLIT,
    TERMINAL,
    ChipMapStore,
    FlowMapLoadError,
    FlowMapStore,
)

MAX_HOPS = 5


def _surface_chips(surface: object) -> tuple[str, ...]:
    return (*surface.top, *surface.more, *surface.follow)  # type: ignore[attr-defined]


def _distance_to_exit(
    start: str,
    transitions: dict[str, dict[str, str]],
) -> int | None:
    """Return the shortest bounded route to conversion or a runtime picker split."""

    queue: deque[tuple[str, int]] = deque([(start, 0)])
    visited: set[str] = set()
    while queue:
        node, depth = queue.popleft()
        if node in visited or depth >= MAX_HOPS:
            continue
        visited.add(node)
        for destination in transitions[node].values():
            if destination in {TERMINAL, SPLIT}:
                return depth + 1
            queue.append((destination, depth + 1))
    return None


def validate() -> list[str]:
    chip_store = ChipMapStore(DEFAULT_CHIP_MAP_PATH, auto_reload=False)
    flow_store = FlowMapStore(
        chip_store,
        DEFAULT_FLOW_MAP_PATH,
        auto_reload=False,
    )
    chips = chip_store.snapshot()
    flow = flow_store.snapshot()
    assert flow is not None
    errors: list[str] = []
    conversion_ids = set(chips.progression.conversion_chips)

    for node, mapping in flow.surfaces.items():
        declared = set(_surface_chips(chips.surfaces[node]))
        has_conversion = bool(declared.intersection(conversion_ids))
        has_forward_route = any(destination != TERMINAL for destination in mapping.values())
        if not has_forward_route and not has_conversion:
            errors.append(
                f"{node}: no forward transition and no conversion chip"
            )

    reachable: set[str] = set()
    queue = deque(key for key in flow.surfaces if key.startswith("page:"))
    while queue:
        node = queue.popleft()
        if node in reachable:
            continue
        reachable.add(node)
        for destination in flow.surfaces[node].values():
            if destination not in {TERMINAL, SPLIT}:
                queue.append(destination)

    for node in sorted(reachable):
        distance = _distance_to_exit(node, flow.surfaces)
        if distance is None:
            errors.append(f"{node}: no terminal or picker transition within {MAX_HOPS} hops")

    return errors


def main() -> int:
    try:
        errors = validate()
    except FlowMapLoadError as error:
        print(f"Flow validation failed: {error}", file=sys.stderr)
        return 1
    if errors:
        for error in errors:
            print(f"Flow validation failed: {error}", file=sys.stderr)
        return 1
    print("Flow validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
