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
    render_sections,
)
from schemas import ResponsePayload

from .category_handler import available_categories, display_category, entities_for_category


def _focus_category(state: Any) -> str | None:
    focus = getattr(state, "focus", None)
    category = getattr(focus, "course_concept", None) or getattr(focus, "category", None)
    return str(category) if category else None


def _focus_specialization(state: Any) -> str | None:
    focus = getattr(state, "focus", None)
    specialization = getattr(focus, "specialization_concept", None) or getattr(
        focus, "specialization", None
    )
    return str(specialization) if specialization else None


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
        categories = [
            display_category(item) for item in available_categories(category_index, catalog)[:3]
        ]
        return build_response(
            f"I couldn't find published {label} specializations in the current catalog.",
            suggested_chips=[f"Explore {item}" for item in categories],
        )
    return build_response(
        render_sections(
            f"{label} Specializations",
            [("Published Options", names)],
        ),
        suggested_chips=[f"{label} {name}" for name in names[:6]],
    )


async def handle_list_providers(
    state: Any = None,
    message: str = "",
    catalog: Any = None,
    category_index: Any = None,
    *,
    specialization_candidates: Sequence[Any] | None = None,
    specialization: str | None = None,
    llm: Any = None,
    **_: Any,
) -> ResponsePayload:
    """List all universities represented by one resolved specialization family."""

    del message, llm
    entities: list[Any] = []
    selected = specialization or _focus_specialization(state)
    if selected and category_index is not None:
        for entity_id in category_index.entities_for_specialization(selected):
            entity = catalog_get_entity(catalog, entity_id)
            if entity is not None and entity_page_type(entity) == "specialization":
                entities.append(entity)
    for candidate in specialization_candidates or ():
        entity_id = getattr(candidate, "entity_id", candidate)
        entity = catalog_get_entity(catalog, entity_id)
        if entity is not None and entity_page_type(entity) == "specialization":
            entities.append(entity)

    # A concept may be backed by the same record through both the taxonomy
    # candidate and the reverse index. Preserve all providers without duplicates.
    deduped: dict[str, Any] = {}
    for entity in entities:
        identity = str(
            safe_get(entity, "id", None)
            or safe_get(entity, "slug", None)
            or (entity_university(entity), entity_label(entity))
        )
        deduped.setdefault(identity, entity)
    entities = list(deduped.values())

    specialization_label = selected or "this specialization"
    if entities:
        specialization_label = str(
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
            f"I couldn't find published university providers for {specialization_label}.",
            suggested_chips=["Explore specializations", "Browse universities"],
        )
    count = len(providers)
    return build_response(
        render_sections(
            f"{specialization_label} Programs",
            [("Published Universities", providers)],
            intro=(
                f"{specialization_label} is offered by {count} published "
                f"universit{'y' if count == 1 else 'ies'}."
            ),
        ),
        suggested_chips=[
            f"Tell me about {provider} {specialization_label}" for provider in providers[:6]
        ],
    )


__all__ = ["handle_list_providers", "handle_list_specializations"]
