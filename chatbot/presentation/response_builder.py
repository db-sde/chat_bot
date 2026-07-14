"""Add rich presentation data to a canonical :class:`ResponsePayload`."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from enum import Enum
from typing import Any

from response.builder import build_transport_components
from response.cards import catalog_get_entity, clean_text, entity_page_type
from schemas import (
    ComparisonCard,
    ProgramCard,
    ResponseComponent,
    ResponsePayload,
    UniversityCard,
)

from .cards import (
    build_comparison_card,
    build_comparison_card_from_text,
    build_entity_card,
)
from .formatter import advisor_message


def _value(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(name, default)
    return getattr(item, name, default)


def _route_name(route: Any) -> str:
    candidate = route
    if isinstance(route, Mapping):
        candidate = next(
            (
                route[key]
                for key in ("route", "name", "intent", "action")
                if route.get(key) is not None
            ),
            "",
        )
    elif route is not None and not isinstance(route, (str, Enum)):
        candidate = next(
            (
                value
                for key in ("route", "name", "intent", "action")
                if (value := getattr(route, key, None)) is not None
            ),
            route,
        )
    if isinstance(candidate, Enum):
        candidate = candidate.value
    return str(candidate or "").strip().casefold()


def _component_type(component: Any) -> str:
    return str(_value(component, "type", ""))


def _as_operands(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (str, bytes, Mapping)):
        return [value]
    if isinstance(value, Iterable):
        return list(value)
    return [value]


def _structured_operands(
    explicit: Iterable[Any] | None,
    route: Any,
    state: Any,
) -> list[Any]:
    if explicit is not None:
        return _as_operands(explicit)
    for source in (route, state):
        for field in (
            "comparison_operands",
            "comparison_entity_ids",
            "entity_ids",
            "comparison_universities",
            "universities",
        ):
            value = _value(source, field)
            if value:
                return _as_operands(value)
    return []


def _resolve_entity(entity: Any, state: Any, route: Any, catalog: Any) -> Any:
    candidate = entity if entity is not None else _value(route, "entity")
    if candidate is not None:
        if isinstance(candidate, (str, int)):
            return catalog_get_entity(catalog, candidate)
        if entity_page_type(candidate):
            return candidate
        reference = _value(candidate, "entity_id") or _value(candidate, "id")
        if reference:
            resolved = catalog_get_entity(catalog, reference)
            if resolved is not None:
                return resolved

    focus = _value(state, "focus")
    entity_id = _value(focus, "entity_id") or _value(route, "entity_id")
    resolved = catalog_get_entity(catalog, entity_id)
    if resolved is not None:
        return resolved

    cache = _value(state, "entity_cache", {})
    if entity_id and isinstance(cache, Mapping):
        cached = cache.get(str(entity_id))
        if cached is not None:
            return cached
    return None


def _comparison_title(text: str) -> str:
    for line in str(text or "").splitlines():
        candidate = clean_text(line)
        if candidate and not candidate.startswith(("•", "-", "*")):
            return candidate[:100]
    return "Comparison"


def enrich_response(
    payload: ResponsePayload | Mapping[str, Any],
    *,
    state: Any = None,
    route: Any = None,
    catalog: Any = None,
    entity: Any = None,
    operands: Iterable[Any] | None = None,
) -> ResponsePayload:
    """Return an additive rich response without mutating routing or focus state.

    Structured comparison operands are authoritative. Existing comparison text is
    parsed only when no such operands are available to the presentation layer.
    """

    current = (
        payload
        if isinstance(payload, ResponsePayload)
        else ResponsePayload.model_validate(payload)
    )
    route_name = _route_name(route)
    resolved_entity = _resolve_entity(entity, state, route, catalog)
    existing: list[ResponseComponent | dict[str, Any]] = list(current.components)
    component_types = {_component_type(component) for component in existing}

    card: ResponseComponent | None = None
    if route_name == "comparison" and "comparison_card" not in component_types:
        structured = _structured_operands(operands, route, state)
        if structured:
            card = build_comparison_card(
                structured,
                catalog,
                title=_comparison_title(current.text),
            )
        else:
            card = build_comparison_card_from_text(
                current.text,
                title=_comparison_title(current.text),
            )
    elif (
        resolved_entity is not None
        and "university_card" not in component_types
        and "program_card" not in component_types
        and (
            route_name in {"factual", "university", "program", "specialization"}
            or entity is not None
        )
    ):
        card = build_entity_card(resolved_entity, catalog)

    if card is not None:
        existing.insert(0, card)

    # Legacy actions remain authoritative. Rebuild their mirrors so payloads made
    # through ``model_copy(update=...)`` cannot retain stale rich actions.
    existing = [
        component
        for component in existing
        if not (
            current.suggested_chips and _component_type(component) == "quick_actions"
        )
        and not (current.cta is not None and _component_type(component) == "lead_cta")
    ]
    components = build_transport_components(
        suggested_chips=current.suggested_chips,
        cta=current.cta,
        components=existing,
    )

    presentation_card = next(
        (
            component
            for component in components
            if isinstance(component, (UniversityCard, ProgramCard, ComparisonCard))
        ),
        None,
    )
    message = advisor_message(
        current.text,
        card=presentation_card,
        next_actions=current.suggested_chips,
    )
    return current.model_copy(update={"message": message, "components": components})


__all__ = ["enrich_response"]
