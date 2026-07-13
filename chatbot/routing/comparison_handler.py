"""Grounded category-to-category comparison."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from data.accessor import safe_get
from response.builder import build_response
from response.cards import (
    catalog_get_entity,
    clean_text,
    entity_fee,
    entity_label,
    entity_page_type,
    entity_university,
    first_value,
    format_inr,
    parse_money,
)
from schemas import ResponsePayload

from .advisory_handler import advisory_preference, handle_advisory
from .category_handler import (
    available_categories,
    category_summary,
    display_category,
)


def _explicit_categories(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Sequence):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)]


def _categories_from_message(message: str, known: list[str]) -> list[str]:
    text = str(message or "").casefold()
    matches: list[tuple[int, str]] = []
    for category in dict.fromkeys(known):
        normalized = str(category).strip().casefold()
        if not normalized:
            continue
        match = re.search(rf"(?<!\w){re.escape(normalized)}(?!\w)", text)
        if match:
            matches.append((match.start(), category))
    return [category for _, category in sorted(matches)]


def _value(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(name, default)
    return getattr(item, name, default)


def _operand_id(item: Any) -> str:
    if isinstance(item, (str, int)):
        return str(item)
    return str(_value(item, "entity_id", _value(item, "id", "")) or "")


def _unique_ids(items: Iterable[Any] | None) -> list[str]:
    return list(dict.fromkeys(value for item in items or () if (value := _operand_id(item))))


def _course_ids_for_universities(
    universities: Sequence[Any] | None,
    category: str | None,
    category_index: Any,
    catalog: Any,
) -> list[str]:
    if not universities or not category or category_index is None:
        return []
    result: list[str] = []
    for university in universities:
        university_id = _operand_id(university)
        if not university_id:
            continue
        try:
            matches = category_index.intersect(
                category=str(category),
                university=university_id,
            )
        except (AttributeError, TypeError, ValueError):
            matches = ()
        course_ids = [
            entity_id
            for entity_id in matches
            if entity_page_type(catalog_get_entity(catalog, entity_id)) == "course"
        ]
        if len(course_ids) == 1:
            result.append(course_ids[0])
    return list(dict.fromkeys(result))


def _course_comparison(
    entity_ids: Sequence[str],
    catalog: Any,
    category: str | None,
) -> ResponsePayload | None:
    entities = [catalog_get_entity(catalog, entity_id) for entity_id in entity_ids]
    entities = [entity for entity in entities if entity is not None]
    if len(entities) < 2:
        return None

    lines: list[str] = []
    chips: list[str] = []
    for entity in entities[:3]:
        university = entity_university(entity) or "University not listed"
        program = entity_label(entity, default=display_category(category or "program"))
        fee = entity_fee(entity)
        duration = clean_text(first_value(entity, "duration", default=""))
        mode = clean_text(first_value(entity, "mode", "mode_of_learning", default=""))
        details = [f"published total fee {fee}" if fee else "published fee unavailable"]
        if duration:
            details.append(f"duration {duration}")
        if mode:
            details.append(f"mode {mode}")
        lines.append(f"- {university} — {program}: {'; '.join(details)}.")
        chips.append(f"Tell me about {university}")

    label = display_category(category) if category else "program"
    return build_response(
        f"Here is the {label} comparison based on the current catalog:\n"
        + "\n".join(lines)
        + "\nFees can use different schedules, so confirm the final fee plan before applying.",
        suggested_chips=chips,
    )


def _university_comparison(
    universities: Sequence[Any] | None,
    catalog: Any,
    *,
    allow_single: bool = False,
) -> ResponsePayload | None:
    entities = [catalog_get_entity(catalog, item) for item in _unique_ids(universities)]
    entities = [entity for entity in entities if entity is not None]
    if not entities:
        return None
    if len(entities) == 1 and not allow_single:
        return None

    lines: list[str] = []
    chips: list[str] = []
    for entity in entities[:3]:
        label = entity_label(entity, default="University")
        naac = clean_text(first_value(entity, "naac_grade", default=""))
        approval = clean_text(
            first_value(entity, "ugc_approved", "ugc_status", default="")
        )
        starting_fee = entity_fee(entity)
        programs = safe_get(entity, "programs_table", []) or []
        program_count = (
            len(programs)
            if isinstance(programs, Iterable) and not isinstance(programs, (str, bytes, Mapping))
            else 0
        )
        details: list[str] = []
        if naac:
            details.append(f"NAAC {naac}")
        if approval:
            details.append(approval)
        if starting_fee:
            details.append(f"published starting fee {starting_fee}")
        if program_count:
            details.append(f"{program_count} listed program{'s' if program_count != 1 else ''}")
        lines.append(
            f"- {label}: {'; '.join(details) if details else 'published details are limited'}."
        )
        chips.append(f"Programs at {label}")

    if len(entities) == 1:
        return build_response(
            "Here is the published information I can provide for the university I matched:\n"
            + "\n".join(lines),
            suggested_chips=chips,
        )
    return build_response(
        "Here is a university-level comparison based on the current catalog:\n"
        + "\n".join(lines)
        + "\nFor a like-for-like decision, compare the same program at each university.",
        suggested_chips=chips,
    )


def _specialization_comparison(
    groups: Sequence[Sequence[Any]] | None,
    catalog: Any,
) -> ResponsePayload | None:
    if not groups or len(groups) < 2:
        return None
    lines: list[str] = []
    chips: list[str] = []
    for group in groups[:3]:
        entities = [catalog_get_entity(catalog, entity_id) for entity_id in _unique_ids(group)]
        entities = [entity for entity in entities if entity is not None]
        if not entities:
            continue
        label = clean_text(
            first_value(
                entities[0],
                "specialization_name",
                "spec_name",
                default=entity_label(entities[0], default="Specialization"),
            )
        )
        providers = list(
            dict.fromkeys(
                entity_university(entity)
                for entity in entities
                if entity_university(entity)
            )
        )
        fees = [
            amount
            for entity in entities
            if (amount := parse_money(entity_fee(entity))) is not None
        ]
        if fees:
            minimum, maximum = min(fees), max(fees)
            fee = (
                f"published fee {format_inr(minimum)}"
                if minimum == maximum
                else f"published fee range {format_inr(minimum)}-{format_inr(maximum)}"
            )
        else:
            fee = "published fee unavailable"
        count = len(providers)
        lines.append(
            f"- {label}: {count} provider option{'s' if count != 1 else ''}; {fee}."
        )
        chips.append(f"Explore {label}")
    if len(lines) < 2:
        return None
    return build_response(
        "Here is a specialization-family comparison based on the current catalog:\n"
        + "\n".join(lines)
        + "\nProvider availability and outcomes vary, so compare the concrete "
        "program records next.",
        suggested_chips=chips,
    )


async def handle_comparison(
    state: Any = None,
    message: str = "",
    catalog: Any = None,
    category_index: Any = None,
    *,
    categories: Sequence[str] | None = None,
    universities: Sequence[Any] | None = None,
    entity_ids: Sequence[str] | None = None,
    common_category: str | None = None,
    specializations: Sequence[Sequence[Any]] | None = None,
    allow_single_university: bool = False,
    llm: Any = None,
    **_: Any,
) -> ResponsePayload:
    """Compare concrete operands, falling back to aggregate course categories."""

    del llm
    selected_entity_ids = _unique_ids(entity_ids)
    if not selected_entity_ids:
        selected_entity_ids = _course_ids_for_universities(
            universities,
            common_category,
            category_index,
            catalog,
        )
    course_payload = _course_comparison(
        selected_entity_ids,
        catalog,
        common_category,
    )
    if course_payload is not None:
        return course_payload

    university_payload = _university_comparison(
        universities,
        catalog,
        allow_single=allow_single_university,
    )
    if university_payload is not None:
        return university_payload

    specialization_payload = _specialization_comparison(specializations, catalog)
    if specialization_payload is not None:
        return specialization_payload

    university_ids = _unique_ids(universities)
    if not any(
        (
            selected_entity_ids,
            university_ids,
            categories,
            specializations,
        )
    ) and advisory_preference(message):
        # Gemini can reasonably label a superlative shortlist request as
        # comparison. With no concrete operands, honor the stated ranking
        # preference instead of asking for two unrelated course categories.
        return await handle_advisory(
            state=state,
            message=message,
            catalog=catalog,
            category_index=category_index,
        )

    if len(university_ids) == 1:
        entity = catalog_get_entity(catalog, university_ids[0])
        university = entity_label(entity, default="that university")
        scope = f" for {display_category(common_category)}" if common_category else ""
        return build_response(
            f"I matched {university}{scope}. Which other university would you like "
            "to compare it with?",
            suggested_chips=["Browse universities"],
        )

    selected = _explicit_categories(categories)
    known = available_categories(category_index, catalog)
    if not selected:
        selected = _categories_from_message(message, known)

    focus = getattr(state, "focus", None)
    focused_category = getattr(focus, "category", None)
    if focused_category and str(focused_category).casefold() not in {
        item.casefold() for item in selected
    }:
        selected.append(str(focused_category))

    selected = list(dict.fromkeys(item.strip().casefold() for item in selected if item.strip()))
    if len(selected) < 2:
        suggestions = [display_category(item) for item in known[:4]]
        return build_response(
            "Which two course categories would you like me to compare?",
            suggested_chips=suggestions,
        )

    selected = selected[:3]
    lines: list[str] = []
    for category in selected:
        summary = category_summary(category, category_index, catalog)
        label = display_category(category)
        provider_count = len(summary["universities"])
        minimum = summary["fee_min"]
        maximum = summary["fee_max"]
        if minimum is None:
            fee = "published fee range unavailable"
        elif maximum is None or minimum == maximum:
            fee = f"published fee data from {format_inr(minimum)}"
        else:
            fee = f"published fee range {format_inr(minimum)}-{format_inr(maximum)}"
        provider = f"{provider_count} university option{'s' if provider_count != 1 else ''}"
        lines.append(f"- {label}: {provider}; {fee}.")

    text = (
        "Here is a category-level comparison based on the current catalog:\n"
        + "\n".join(lines)
        + "\nFees can use different schedules, so check the final program record before applying."
    )
    return build_response(
        text,
        suggested_chips=[f"Explore {display_category(item)}" for item in selected],
    )


handle = handle_comparison

__all__ = ["handle", "handle_comparison"]
