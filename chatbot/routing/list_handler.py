"""Deterministic list-shaped responses for resolved category/specialization requests."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from data.accessor import safe_get
from response.builder import build_response
from response.cards import (
    catalog_get_entity,
    entity_label,
    entity_page_type,
    entity_university,
)
from schemas import ResponsePayload

from .category_handler import display_category, entities_for_category


def _focus_category(state: Any) -> str | None:
    focus = getattr(state, "focus", None)
    category = getattr(focus, "category", None)
    return str(category) if category else None


async def handle_list_specializations(
    state: Any = None,
    message: str = "",
    catalog: Any = None,
    category_index: Any = None,
    *,
    category: str | None = None,
    llm: Any = None,
    **_: Any,
) -> ResponsePayload:
    """List every published specialization family for one resolved category."""

    del message, llm
    selected = category or _focus_category(state)
    label = display_category(selected)
    names: list[str] = []
    seen: set[str] = set()
    if selected:
        for entity in entities_for_category(selected, category_index, catalog):
            if entity_page_type(entity) != "specialization":
                continue
            name = str(
                safe_get(entity, "specialization_name", None)
                or safe_get(entity, "spec_name", None)
                or entity_label(entity)
            ).strip()
            if name and name.casefold() not in seen:
                seen.add(name.casefold())
                names.append(name)
    names.sort(key=str.casefold)
    if not names:
        return build_response(
            f"I couldn't find published {label} specializations in the current catalog.",
            suggested_chips=["Explore MBA", "Explore MCA"],
        )
    return build_response(
        f"Published {label} specializations include: {', '.join(names)}.",
        suggested_chips=names[:6],
    )


async def handle_list_providers(
    state: Any = None,
    message: str = "",
    catalog: Any = None,
    category_index: Any = None,
    *,
    specialization_candidates: Sequence[Any] | None = None,
    llm: Any = None,
    **_: Any,
) -> ResponsePayload:
    """List all universities represented by one resolved specialization family."""

    del state, message, category_index, llm
    entities: list[Any] = []
    for candidate in specialization_candidates or ():
        entity_id = getattr(candidate, "entity_id", candidate)
        entity = catalog_get_entity(catalog, entity_id)
        if entity is not None and entity_page_type(entity) == "specialization":
            entities.append(entity)

    specialization = "this specialization"
    if entities:
        specialization = str(
            safe_get(entities[0], "specialization_name", None)
            or safe_get(entities[0], "spec_name", None)
            or entity_label(entities[0])
        ).strip()
    providers = sorted(
        {
            university.strip()
            for entity in entities
            if (university := entity_university(entity)) and university.strip()
        },
        key=str.casefold,
    )
    if not providers:
        return build_response(
            f"I couldn't find published university providers for {specialization}.",
            suggested_chips=["Explore specializations", "Browse universities"],
        )
    count = len(providers)
    return build_response(
        f"{specialization} is offered by {count} published "
        f"universit{'y' if count == 1 else 'ies'}: {', '.join(providers)}.",
        suggested_chips=[f"Tell me about {provider}" for provider in providers[:6]],
    )


__all__ = ["handle_list_providers", "handle_list_specializations"]
