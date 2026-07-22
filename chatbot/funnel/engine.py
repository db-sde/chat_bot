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
    ChipType,
    FunnelStage,
)
from .flow_config import SPLIT, TERMINAL, FlowMapStore

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
    # §2 taxonomy, resolved against the active entity (§4.3).
    type: ChipType = ChipType.NAV_SET
    rows_visible: int | None = None
    # §10 a demoted chip renders dimmed with a check, never disappears.
    seen: bool = False

    def as_action(self) -> dict[str, str]:
        """Return a transport-neutral action dictionary for a future adapter."""

        result = {
            "chip_id": self.id,
            "label": self.label,
            "handler": self.handler,
            "type": self.type.value,
        }
        if self.tool:
            result["tool"] = self.tool
        if self.rows_visible is not None:
            result["rows_visible"] = self.rows_visible
        if self.seen:
            result["seen"] = True
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
    # §8 the conversion slot is always present and always separate from the
    # info slots; §10 demoted chips live in `more`, never deleted.
    more: tuple[ResolvedChip, ...] = ()
    conversion: ResolvedChip | None = None
    # §7 backfill tier reached; 4+ means the entity is thin on content.
    pool_tier: int = 1


@dataclass(frozen=True, slots=True)
class ChipJourneyState:
    """Small integration boundary; persistence can be added to ConversationState later."""

    completed_actions: frozenset[str] = field(default_factory=frozenset)
    current_node: str = ""


def _resolved(
    chip_id: str,
    definition: ChipDefinition,
    *,
    entity_type: str | None = None,
    seen: bool = False,
) -> ResolvedChip:
    # Referenced definitions are guaranteed to have a base label by config validation.
    assert definition.label is not None
    return ResolvedChip(
        id=chip_id,
        label=definition.label,
        handler=definition.handler,
        funnel_stage=definition.funnel_stage,
        tool=definition.tool,
        type=definition.resolve_type(entity_type),
        rows_visible=definition.resolve_rows_visible(entity_type),
        seen=seen,
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
            # Generated chips (e.g. per-entity FAQ chips) have no config entry
            # and therefore declare no catalog requirements.
            for requirement in getattr(config.chips.get(chip.id), "requires", ())
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


def _current_node(state: Any) -> str:
    direct = _state_value(state, "current_node")
    if direct:
        return str(direct)
    navigation = _state_value(state, "navigation")
    nested = _state_value(navigation, "current_node")
    return str(nested or "")


def _set_current_node(state: Any, value: str) -> None:
    if state is None or not value:
        return
    navigation = _state_value(state, "navigation")
    target = navigation if navigation is not None else state
    if isinstance(target, dict):
        target["current_node"] = value
        return
    try:
        target.current_node = value
    except (AttributeError, TypeError):
        # Frozen test-state adapters remain valid read-only integration boundaries.
        return


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


# §7 the never-empty guarantee: 3 info + 1 reserved conversion.
NAV_INFO_SLOTS = 3
# §10 More is capped so demoted chips cannot grow without bound.
MORE_CAP = 8


def _pool_key(entity_type: str | None) -> str:
    return f"entity:{_normalise_key(entity_type)}"


def resolve_nav_pool(
    config: ChipMapConfig,
    *,
    entity_type: str | None,
    consumed: frozenset[str],
    entity_context: Mapping[str, Any] | None = None,
    faq_chips: Sequence[ResolvedChip] = (),
) -> tuple[tuple[ResolvedChip, ...], int]:
    """Fill one nav_set from the entity pool (§5) via the backfill ladder (§7).

    Returns the ordered pool and the ladder tier reached, so integration can
    emit `chip_pool_exhausted` at tier 4+ — a content-roadmap signal, not just
    a bug signal.

    Chips are never deleted for having been used: a consumed chip is demoted to
    a strictly lower tier (§10) and climbs back only within that tier, so the
    pool is always full and self-replenishing.
    """

    pool = config.pools.get(_pool_key(entity_type))
    conversion_ids = set(config.progression.conversion_chips)

    def build(chip_ids: Sequence[str]) -> list[ResolvedChip]:
        resolved: list[ResolvedChip] = []
        for chip_id in chip_ids:
            if chip_id == "faq_chips":
                resolved.extend(faq_chips)
                continue
            definition = config.chips.get(chip_id)
            if definition is None:
                continue
            # Conversion chips own a reserved slot (§8); they never occupy an
            # info slot, and are exempt from consumption (§10).
            if chip_id in conversion_ids:
                continue
            resolved.append(
                _resolved(
                    chip_id,
                    definition,
                    entity_type=entity_type,
                    seen=chip_id in consumed,
                )
            )
        return _available_chips(
            _deduplicate(resolved), config=config, entity_context=entity_context
        )

    priority = build(pool.priority) if pool is not None else []
    unseen = [chip for chip in priority if not chip.seen]

    tier = 1
    if len(unseen) < NAV_INFO_SLOTS:
        # Tier 2+: FAQ chips, then siblings/level-up/tools from the backfill list.
        backfill = build(pool.backfill) if pool is not None else []
        extra = [
            chip
            for chip in backfill
            if not chip.seen and chip.id not in {c.id for c in priority}
        ]
        if extra:
            tier = 2
        unseen = unseen + extra
        if len(unseen) < NAV_INFO_SLOTS:
            # Tier 6: fall back on demoted chips, still rendered in seen state.
            tier = 6

    # Guard 1 (§10): never-seen strictly outranks seen. Sorting by the flag
    # alone keeps configured priority order stable inside each tier.
    combined = _deduplicate([*priority, *(build(pool.backfill) if pool is not None else [])])
    ordered = sorted(combined, key=lambda chip: chip.seen)
    return tuple(ordered), tier


def split_nav_set(
    pool: Sequence[ResolvedChip],
) -> tuple[tuple[ResolvedChip, ...], tuple[ResolvedChip, ...]]:
    """Split a resolved pool into the visible info slots and the More list (§8, §10)."""

    visible = tuple(pool[:NAV_INFO_SLOTS])
    # Guard 2 (§10): More is capped; the overflow stays reachable via Main menu.
    more = tuple(pool[NAV_INFO_SLOTS:][:MORE_CAP])
    return visible, more


def reserved_conversion(
    config: ChipMapConfig,
    *,
    interaction_count: int,
    tool_reveal: bool = False,
    entity_type: str | None = None,
) -> ResolvedChip | None:
    """§8 pick the chip occupying the always-present conversion slot.

    Escalation changes only *which* conversion chip occupies the slot, never
    how many info chips exist beside it.
    """

    escalate = tool_reveal or interaction_count >= config.progression.escalate_after
    preferred = "apply_now" if escalate else "counsellor"
    order = [preferred] + [
        chip_id
        for chip_id in config.progression.conversion_chips
        if chip_id != preferred
    ]
    for chip_id in order:
        definition = config.chips.get(chip_id)
        if definition is not None:
            return _resolved(chip_id, definition, entity_type=entity_type)
    return None


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

    def __init__(
        self,
        store: ChipMapStore,
        flow_store: FlowMapStore | None = None,
    ) -> None:
        self.store = store
        sibling_flow_map = store.path.with_name("flow_map.json")
        self.flow_store = flow_store or (
            FlowMapStore(store, sibling_flow_map, auto_reload=store.auto_reload)
            if sibling_flow_map.exists()
            else None
        )

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
        completed_chip_id: str | None = None,
        entity_type: str | None = None,
        consumed: frozenset[str] | None = None,
        faq_chips: Sequence[ResolvedChip] = (),
    ) -> FollowupChipSet:
        """Look up one follow surface and remove unavailable catalog actions."""
        config = self.store.snapshot()
        requested_surface = self._surface_key(
            page_type=page_type,
            card_type=card_type,
            answer_state=answer_state,
        )
        surface_key = requested_surface
        terminal = False
        flow = (
            self.flow_store.snapshot(version=config.version)
            if self.flow_store is not None
            else None
        )
        current_node = _current_node(state) or requested_surface
        if flow is not None and completed_chip_id:
            destination = flow.surfaces.get(current_node, {}).get(completed_chip_id)
            if destination == TERMINAL:
                terminal = True
            elif destination == SPLIT:
                # Picker resolution synchronises the concrete page/card node later.
                pass
            elif destination:
                definition = config.chips.get(completed_chip_id)
                conditional_eligibility = bool(
                    definition is not None
                    and definition.handler == "get_eligibility"
                    and requested_surface.startswith("answer:eligibility_")
                )
                surface_key = requested_surface if conditional_eligibility else destination

        if flow is not None and surface_key in flow.surfaces:
            current_node = surface_key
            _set_current_node(state, current_node)
            transitions = flow.surfaces[current_node]
            terminal = terminal or bool(
                transitions and all(destination == TERMINAL for destination in transitions.values())
            )

        surface = config.surfaces.get(surface_key)
        missing = surface is None or not surface.follow
        if terminal:
            missing = False
            stage = FunnelStage.BOTTOM
            base = _resolve_many(config, config.progression.conversion_chips)
        elif missing:
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

        # §5 the configured `follow` list is a seed; the rendered set comes from
        # the entity pool so it always knows what is still unexplored. Without a
        # resolvable entity the surface list is all we have.
        more: tuple[ResolvedChip, ...] = ()
        tier = 1
        pool_key = _pool_key(entity_type)
        if entity_type and pool_key in config.pools:
            pool, tier = resolve_nav_pool(
                config,
                entity_type=entity_type,
                consumed=consumed if consumed is not None else _completed_actions(state),
                entity_context=entity_context,
                faq_chips=faq_chips,
            )
            visible, more = split_nav_set(pool)
            selected = visible
            if tier >= 4:
                # A content-roadmap signal, not merely a bug signal (§13).
                logger.info(
                    "chip_pool_exhausted: entity_type=%s tier=%s", entity_type, tier
                )

        conversion = reserved_conversion(
            config,
            interaction_count=interaction_count,
            tool_reveal=surface_key == "tool:reveal",
            entity_type=entity_type,
        )
        # §7 hard invariant: a nav_set renders 3 info + 1 conversion. Fewer is a
        # bug state, not a valid one — but only for nav_set (§2.2).
        if len(selected) < NAV_INFO_SLOTS and entity_type:
            logger.error(
                "nav_set underfilled: surface=%s entity_type=%s rendered=%s",
                surface_key,
                entity_type,
                len(selected),
            )

        return FollowupChipSet(
            surface=surface_key,
            chips=selected,
            funnel_stage=stage,
            interaction_count=max(0, int(interaction_count)),
            config_version=config.version,
            missing_surface=missing,
            more=more,
            conversion=conversion,
            pool_tier=tier,
        )


__all__ = [
    "MORE_CAP",
    "NAV_INFO_SLOTS",
    "ChipEngine",
    "ChipJourneyState",
    "FollowupChipSet",
    "JourneyEngine",
    "OpeningChipSet",
    "ResolvedChip",
    "apply_progression",
    "reserved_conversion",
    "resolve_nav_pool",
    "split_nav_set",
]
