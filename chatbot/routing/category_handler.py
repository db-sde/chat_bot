"""Category-level factual answers that never select an arbitrary provider."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from data.accessor import safe_get
from response.builder import build_response
from response.cards import (
    catalog_get_entity,
    entity_fee,
    entity_label,
    entity_university,
    format_inr,
    iter_catalog_entities,
    parse_money,
)
from schemas import ResponsePayload


def display_category(category: Any) -> str:
    value = str(category or "").strip()
    if not value:
        return "this program"
    if value.replace("-", "").isalnum() and len(value) <= 6:
        return value.upper()
    return value.replace("-", " ").title()


def category_entity_ids(category_index: Any, category: str) -> tuple[Any, ...]:
    """Read a category from the index without assuming a concrete implementation."""

    if category_index is None or not category:
        return ()
    for method_name in ("entities_for_category", "get_entities", "for_category"):
        method = getattr(category_index, method_name, None)
        if callable(method):
            try:
                values = method(category)
            except (KeyError, TypeError, ValueError):
                continue
            if values is not None and not isinstance(values, (str, bytes)):
                return tuple(values)

    if isinstance(category_index, Mapping):
        values = category_index.get(category) or category_index.get(category.casefold()) or ()
        return tuple(values) if not isinstance(values, (str, bytes)) else (values,)

    for attr_name in ("category_to_entities", "categories", "by_category"):
        mapping = getattr(category_index, attr_name, None)
        if isinstance(mapping, Mapping):
            values = mapping.get(category) or mapping.get(category.casefold()) or ()
            return tuple(values) if not isinstance(values, (str, bytes)) else (values,)
    return ()


def available_categories(category_index: Any, catalog: Any = None) -> list[str]:
    """List known categories, most represented first."""

    counts: dict[str, int] = {}
    mapping = getattr(category_index, "category_to_entities", None)
    if not isinstance(mapping, Mapping) and isinstance(category_index, Mapping):
        mapping = category_index
    if isinstance(mapping, Mapping):
        for category, values in mapping.items():
            if not category:
                continue
            try:
                count = len(values)
            except TypeError:
                count = 1
            counts[str(category)] = count

    if not counts:
        for entity in iter_catalog_entities(catalog):
            category = safe_get(entity, "category", None)
            if category:
                key = str(category).strip().casefold()
                counts[key] = counts.get(key, 0) + 1
    return [item[0] for item in sorted(counts.items(), key=lambda item: (-item[1], item[0]))]


def entities_for_category(category: str, category_index: Any, catalog: Any) -> list[Any]:
    """Return all matching records; never collapse the result to its first member."""

    records: list[Any] = []
    seen: set[str] = set()
    for reference in category_entity_ids(category_index, category):
        entity = catalog_get_entity(catalog, reference)
        if entity is None and not isinstance(reference, (str, int)):
            entity = reference
        if entity is None:
            continue
        identity = str(
            safe_get(entity, "id", None)
            or safe_get(entity, "slug", None)
            or entity_label(entity)
        ).casefold()
        if identity in seen:
            continue
        seen.add(identity)
        records.append(entity)

    if records:
        return records

    target = str(category or "").strip().casefold()
    for entity in iter_catalog_entities(catalog):
        value = str(safe_get(entity, "category", "") or "").strip().casefold()
        if value == target:
            records.append(entity)
    return records


def category_summary(category: str, category_index: Any, catalog: Any) -> dict[str, Any]:
    entities = entities_for_category(category, category_index, catalog)
    universities: list[str] = []
    seen_universities: set[str] = set()
    fee_values: list[float] = []
    for entity in entities:
        university = entity_university(entity)
        if not university and str(safe_get(entity, "_meta.page_type", "")) == "university":
            university = entity_label(entity)
        if university and university.casefold() not in seen_universities:
            seen_universities.add(university.casefold())
            universities.append(university)
        fee = parse_money(entity_fee(entity))
        if fee is not None:
            fee_values.append(fee)
    return {
        "category": category,
        "entities": entities,
        "universities": universities,
        "fee_min": min(fee_values) if fee_values else None,
        "fee_max": max(fee_values) if fee_values else None,
    }


def _focus_category(state: Any) -> str | None:
    focus = getattr(state, "focus", None)
    value = getattr(focus, "category", None)
    return str(value) if value else None


async def handle_category(
    state: Any = None,
    message: str = "",
    catalog: Any = None,
    category_index: Any = None,
    *,
    category: str | None = None,
    llm: Any = None,
    **_: Any,
) -> ResponsePayload:
    """List every matching university and the aggregate published fee range."""

    del llm  # category answers are deterministic by design
    selected = category or _focus_category(state)
    label = display_category(selected)
    if not selected:
        return build_response(
            "Which course category would you like to explore?",
            suggested_chips=["MBA", "MCA", "BBA"],
        )

    summary = category_summary(selected, category_index, catalog)
    universities: list[str] = summary["universities"]
    if not universities:
        return build_response(
            f"I couldn't find published university options for {label} yet. "
            "Would you like to try another course category?",
            suggested_chips=[
                display_category(item)
                for item in available_categories(category_index, catalog)
                if str(item).casefold() != str(selected).casefold()
            ][:3],
        )

    if "eligib" in message.casefold() or "requirement" in message.casefold():
        requirements: list[str] = []
        seen: set[str] = set()
        for entity in summary["entities"]:
            university = entity_university(entity) or entity_label(entity)
            # Dedup by university name — not the full rendered string — so the
            # same university with slightly different phrasing isn't listed twice.
            university_key = university.casefold()
            if university_key in seen:
                continue
            eligibility = safe_get(entity, "eligibility_summary", None) or safe_get(
                entity, "eligibility_content", None
            )
            if not eligibility:
                continue
            seen.add(university_key)
            requirements.append(f"{university}: {eligibility}")
        if requirements:
            return build_response(
                f"Published {label} eligibility varies by university: "
                + "; ".join(requirements[:6])
                + ". Check the final university record before applying.",
                suggested_chips=[f"{label} fees", f"Universities offering {label}"],
            )

    shown = universities[:8]
    provider_text = ", ".join(shown)
    if len(universities) > len(shown):
        provider_text += f", and {len(universities) - len(shown)} more"

    minimum = summary["fee_min"]
    maximum = summary["fee_max"]
    if minimum is None:
        fee_text = "A comparable published fee range is not available for every option."
    elif maximum is None or minimum == maximum:
        fee_text = f"The published fee data currently starts at about {format_inr(minimum)}."
    else:
        fee_text = (
            f"Across records with comparable fee data, the published range is about "
            f"{format_inr(minimum)} to {format_inr(maximum)}."
        )

    text = (
        f"{label} is available from {provider_text}. {fee_text} "
        "I haven't selected one university for you."
    )
    return build_response(
        text,
        suggested_chips=[f"{label} eligibility", f"{label} fees"],
    )


handle = handle_category


__all__ = [
    "available_categories",
    "category_entity_ids",
    "category_summary",
    "display_category",
    "entities_for_category",
    "handle",
    "handle_category",
]
