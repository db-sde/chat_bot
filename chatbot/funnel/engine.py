"""Pure journey selection and funnel progression over a validated chip map."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .chip_config import (
    ChipDefinition,
    ChipMapConfig,
    ChipMapStore,
    FunnelStage,
)

logger = logging.getLogger(__name__)

_STAGE_RANK = {
    FunnelStage.TOP: 0,
    FunnelStage.MID: 1,
    FunnelStage.BOTTOM: 2,
}
_PAGE_SURFACES = {
    "home": "page:home",
    "homepage": "page:home",
    "blog": "page:home",
    "pillar": "page:pillar",
    "discipline": "page:pillar",
    "discipline_hub": "page:pillar",
    "university": "page:university",
    "course": "page:course",
    "specialization": "page:specialization",
}


def _normalise_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().casefold()).strip("_")


def _page_surface(page_type: Any) -> str:
    normalized = _normalise_key(page_type)
    return _PAGE_SURFACES.get(normalized, f"page:{normalized or 'unknown'}")


@dataclass(frozen=True, slots=True)
class ResolvedChip:
    id: str
    label: str
    handler: str
    funnel_stage: FunnelStage
    tool: str | None = None

    def as_action(self) -> dict[str, str]:
        """Return a transport-neutral action dictionary for a future adapter."""

        result = {
            "chip_id": self.id,
            "label": self.label,
            "handler": self.handler,
        }
        if self.tool:
            result["tool"] = self.tool
        return result


@dataclass(frozen=True, slots=True)
class OpeningChipSet:
    surface: str
    top: tuple[ResolvedChip, ...]
    more: tuple[ResolvedChip, ...]
    config_version: str
    missing_surface: bool = False


@dataclass(frozen=True, slots=True)
class FollowupChipSet:
    surface: str
    chips: tuple[ResolvedChip, ...]
    funnel_stage: FunnelStage
    interaction_count: int
    config_version: str
    missing_surface: bool = False


@dataclass(frozen=True, slots=True)
class ChipJourneyState:
    """Small integration boundary; persistence can be added to ConversationState later."""

    completed_actions: frozenset[str] = field(default_factory=frozenset)


def _resolved(chip_id: str, definition: ChipDefinition) -> ResolvedChip:
    # Referenced definitions are guaranteed to have a base label by config validation.
    assert definition.label is not None
    return ResolvedChip(
        id=chip_id,
        label=definition.label,
        handler=definition.handler,
        funnel_stage=definition.funnel_stage,
        tool=definition.tool,
    )


def _resolve_many(config: ChipMapConfig, chip_ids: Sequence[str]) -> tuple[ResolvedChip, ...]:
    return tuple(_resolved(chip_id, config.chips[chip_id]) for chip_id in chip_ids)


def _available_chips(
    chips: Sequence[ResolvedChip],
    *,
    config: ChipMapConfig,
    entity_context: Mapping[str, Any] | None,
) -> tuple[ResolvedChip, ...]:
    """Filter declared catalog capabilities when an entity context is available."""

    if entity_context is None:
        return tuple(chips)
    return tuple(
        chip
        for chip in chips
        if all(
            bool(entity_context.get(requirement))
            for requirement in config.chips[chip.id].requires
        )
    )


def _state_value(state: Any, name: str) -> Any:
    if state is None:
        return None
    if isinstance(state, Mapping):
        return state.get(name)
    return getattr(state, name, None)


def _completed_actions(state: Any) -> frozenset[str]:
    if isinstance(state, ChipJourneyState):
        return state.completed_actions
    for name in ("completed_actions", "completed_chip_actions"):
        values = _state_value(state, name)
        if values:
            return frozenset(str(value) for value in values)
    for container_name in ("funnel", "navigation"):
        nested = _state_value(state, container_name)
        for name in ("completed_actions", "completed_chip_actions"):
            values = _state_value(nested, name)
            if values:
                return frozenset(str(value) for value in values)
    return frozenset()


def _is_completed(
    chip: ResolvedChip,
    completed: frozenset[str],
    *,
    config: ChipMapConfig,
) -> bool:
    """Treat label variants sharing one handler as the same completed action."""

    completed_handlers = {
        config.chips[value].handler
        for value in completed
        if value in config.chips
    }
    return (
        chip.id in completed
        or chip.handler in completed
        or chip.handler in completed_handlers
    )


def _deduplicate(chips: Sequence[ResolvedChip]) -> list[ResolvedChip]:
    result: list[ResolvedChip] = []
    seen: set[str] = set()
    for chip in chips:
        if chip.id in seen:
            continue
        seen.add(chip.id)
        result.append(chip)
    return result


def apply_progression(
    chips: Sequence[ResolvedChip],
    *,
    config: ChipMapConfig,
    source_stage: FunnelStage,
    interaction_count: int,
    completed_actions: frozenset[str] = frozenset(),
    tool_reveal: bool = False,
) -> tuple[ResolvedChip, ...]:
    """Apply the stable funnel rules without mutating state or configuration.

    Completed actions are never reintroduced. If every configured conversion has
    already completed, the function does not violate that rule merely to manufacture
    another CTA; integration should end or reset the journey at that point.
    """

    count = max(0, int(interaction_count))
    source_rank = _STAGE_RANK[source_stage]

    def allowed(chip: ResolvedChip) -> bool:
        return (
            not _is_completed(chip, completed_actions, config=config)
            and _STAGE_RANK[chip.funnel_stage] >= source_rank
        )

    selected = [chip for chip in _deduplicate(chips) if allowed(chip)]
    conversion_ids = tuple(config.progression.conversion_chips)

    if tool_reveal:
        priorities = [
            _resolved(chip_id, config.chips[chip_id])
            for chip_id in config.progression.tool_reveal_priority
        ]
        selected = _deduplicate([*filter(allowed, priorities), *selected])

    if not any(chip.id in conversion_ids for chip in selected):
        conversion = next(
            (
                _resolved(chip_id, config.chips[chip_id])
                for chip_id in conversion_ids
                if allowed(_resolved(chip_id, config.chips[chip_id]))
            ),
            None,
        )
        if conversion is not None:
            selected.append(conversion)

    if tool_reveal:
        priority_index = {
            chip_id: index
            for index, chip_id in enumerate(config.progression.tool_reveal_priority)
        }
        selected.sort(key=lambda chip: priority_index.get(chip.id, len(priority_index)))
    elif count >= config.progression.escalate_after:
        conversion_index = next(
            (index for index, chip in enumerate(selected) if chip.id in conversion_ids),
            None,
        )
        if conversion_index is not None and conversion_index > 0:
            selected.insert(0, selected.pop(conversion_index))

    return tuple(selected)


class JourneyEngine:
    """Resolve only the opening top/more chip set for one page type."""

    def __init__(self, store: ChipMapStore) -> None:
        self.store = store

    def opening(
        self,
        page_type: str,
        *,
        entity_context: Mapping[str, Any] | None = None,
    ) -> OpeningChipSet:
        config = self.store.snapshot()
        surface_key = _page_surface(page_type)
        surface = config.surfaces.get(surface_key)
        if surface is None or not (surface.top or surface.more):
            logger.warning("Missing chip surface: %s; using safe defaults", surface_key)
            safe = _resolve_many(config, config.progression.conversion_chips)
            return OpeningChipSet(
                surface=surface_key,
                top=safe,
                more=(),
                config_version=config.version,
                missing_surface=True,
            )
        return OpeningChipSet(
            surface=surface_key,
            top=_available_chips(
                _resolve_many(config, surface.top),
                config=config,
                entity_context=entity_context,
            ),
            more=_available_chips(
                _resolve_many(config, surface.more),
                config=config,
                entity_context=entity_context,
            ),
            config_version=config.version,
        )


class ChipEngine:
    """Resolve post-card/post-answer chips and apply deterministic progression."""

    def __init__(self, store: ChipMapStore) -> None:
        self.store = store

    @staticmethod
    def _surface_key(
        *,
        page_type: str | None,
        card_type: str | None,
        answer_state: str | None,
    ) -> str:
        answer = _normalise_key(answer_state)
        if answer in {"tool_reveal", "reveal"}:
            return "tool:reveal"
        if answer:
            return f"answer:{answer}"
        card = _normalise_key(card_type)
        if card:
            return f"card:{card}"
        # Page-only resolution intentionally has no follow set: opening chips belong
        # exclusively to JourneyEngine. The resulting safe fallback is explicit.
        return _page_surface(page_type)

    def lookup(
        self,
        page_type: str | None = None,
        card_type: str | None = None,
        answer_state: str | None = None,
        interaction_count: int = 0,
        *,
        state: Any = None,
        entity_context: Mapping[str, Any] | None = None,
    ) -> FollowupChipSet:
        """Look up one follow surface and remove unavailable catalog actions."""
        config = self.store.snapshot()
        surface_key = self._surface_key(
            page_type=page_type,
            card_type=card_type,
            answer_state=answer_state,
        )
        surface = config.surfaces.get(surface_key)
        missing = surface is None or not surface.follow
        if missing:
            logger.warning("Missing chip surface: %s; using safe defaults", surface_key)
            stage = (
                config.surfaces.get(_page_surface(page_type)).funnel_stage
                if config.surfaces.get(_page_surface(page_type)) is not None
                else FunnelStage.BOTTOM
            )
            base = _resolve_many(config, config.progression.conversion_chips)
        else:
            assert surface is not None
            stage = surface.funnel_stage
            base = _available_chips(
                _resolve_many(config, surface.follow),
                config=config,
                entity_context=entity_context,
            )

        page_surface = config.surfaces.get(_page_surface(page_type))
        state_navigation = _state_value(state, "navigation")
        state_surface_key = _state_value(state_navigation, "surface")
        state_surface = config.surfaces.get(str(state_surface_key or ""))
        stage = max(
            (
                stage,
                page_surface.funnel_stage if page_surface is not None else stage,
                state_surface.funnel_stage if state_surface is not None else stage,
            ),
            key=lambda candidate: _STAGE_RANK[candidate],
        )

        selected = apply_progression(
            base,
            config=config,
            source_stage=stage,
            interaction_count=interaction_count,
            completed_actions=_completed_actions(state),
            tool_reveal=surface_key == "tool:reveal",
        )
        return FollowupChipSet(
            surface=surface_key,
            chips=selected,
            funnel_stage=stage,
            interaction_count=max(0, int(interaction_count)),
            config_version=config.version,
            missing_surface=missing,
        )


__all__ = [
    "ChipEngine",
    "ChipJourneyState",
    "FollowupChipSet",
    "JourneyEngine",
    "OpeningChipSet",
    "ResolvedChip",
    "apply_progression",
]
