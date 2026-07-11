"""Bounded advisory flow: collect one preference before recommending."""

from __future__ import annotations

from typing import Any

from data.accessor import safe_get
from response.builder import build_response
from response.cards import entity_fee, entity_label, entity_university, parse_money
from schemas import ResponsePayload

from .category_handler import (
    available_categories,
    category_summary,
    display_category,
    entities_for_category,
)


def _preference(message: str) -> str | None:
    text = message.casefold()
    if any(marker in text for marker in ("lower fee", "low fee", "budget", "affordable", "cost")):
        return "fees"
    if any(marker in text for marker in ("placement", "career support", "hiring")):
        return "placements"
    if any(marker in text for marker in ("specialization", "specialisation")):
        return "specialization"
    if any(marker in text for marker in ("business", "management", "leadership")):
        return "business"
    if any(marker in text for marker in ("technology", "tech", "software", "computer")):
        return "technology"
    return None


def _lowest_fee_options(category: str, category_index: Any, catalog: Any) -> list[str]:
    ranked: list[tuple[float, str]] = []
    seen: set[str] = set()
    for entity in entities_for_category(category, category_index, catalog):
        fee = entity_fee(entity)
        amount = parse_money(fee)
        university = entity_university(entity) or entity_label(entity)
        if amount is None or not university or university.casefold() in seen:
            continue
        seen.add(university.casefold())
        ranked.append((amount, f"{university} ({fee})"))
    return [label for _, label in sorted(ranked)[:3]]


def _placement_options(category: str, category_index: Any, catalog: Any) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()
    for entity in entities_for_category(category, category_index, catalog):
        has_published_support = bool(
            safe_get(entity, "placement_content") or safe_get(entity, "job_profiles")
        )
        university = entity_university(entity) or entity_label(entity)
        if has_published_support and university and university.casefold() not in seen:
            seen.add(university.casefold())
            labels.append(university)
    return labels[:4]


async def handle_advisory(
    state: Any = None,
    message: str = "",
    catalog: Any = None,
    category_index: Any = None,
    *,
    llm: Any = None,
    **_: Any,
) -> ResponsePayload:
    """Ask exactly one bounded preference question; do not invent a ranking."""

    del llm
    focus = getattr(state, "focus", None)
    category = getattr(focus, "category", None)
    preference = _preference(message)
    if category:
        label = display_category(category)
        if preference == "fees":
            options = _lowest_fee_options(category, category_index, catalog)
            if options:
                return build_response(
                    f"Based only on the currently published fees, the lower-cost {label} "
                    f"options I found are {', '.join(options)}. Please compare the full fee "
                    "schedule before applying.",
                    suggested_chips=[f"Compare {label} options", f"{label} eligibility"],
                )
        if preference == "placements":
            options = _placement_options(category, category_index, catalog)
            if options:
                return build_response(
                    f"For {label}, these universities publish placement or career-support "
                    f"details: {', '.join(options)}. This is not a ranking or placement guarantee.",
                    suggested_chips=[f"{label} fees", f"Compare {label} options"],
                )
        if preference == "specialization":
            mapping = getattr(category_index, "specialization_to_entities", {})
            names = [display_category(name) for name in list(mapping)[:6]]
            return build_response(
                f"Which {label} specialization fits your goal?",
                suggested_chips=names or ["Marketing", "Business Analytics", "Finance", "HR"],
            )
        text = (
            f"I can narrow the published {label} options for you. "
            "What matters most: lower fees, a preferred specialization, or placement support?"
        )
        chips = ["Lower fees", "Preferred specialization", "Placement support"]
    else:
        if preference in {"business", "technology"}:
            selected = "mba" if preference == "business" else "mca"
            summary = category_summary(selected, category_index, catalog)
            universities = summary["universities"]
            label = selected.upper()
            if universities:
                return build_response(
                    f"Based on that direction, {label} is the closest catalog category. "
                    f"It currently has published options from {', '.join(universities[:5])}. "
                    "This is a category fit, not a university ranking.",
                    suggested_chips=[f"Explore {label}", f"Compare {label} options"],
                )
        if preference == "fees":
            ranked_categories: list[tuple[float, str]] = []
            for item in available_categories(category_index, catalog):
                summary = category_summary(item, category_index, catalog)
                if summary["fee_min"] is not None:
                    ranked_categories.append((summary["fee_min"], display_category(item)))
            if ranked_categories:
                _, label = min(ranked_categories)
                return build_response(
                    f"From comparable published starting totals, {label} currently has the "
                    "lowest entry point among the catalog categories. Fee schedules differ, "
                    "so treat this as a shortlist signal rather than a final price.",
                    suggested_chips=[f"Explore {label}", "Compare MBA and MCA"],
                )
        text = (
            "I can narrow the catalog with one preference. Which direction is closer to "
            "your goal: business and management, or technology and software?"
        )
        chips = ["Business and management", "Technology and software", "Lower fees"]
    return build_response(text, suggested_chips=chips)


handle = handle_advisory

__all__ = ["handle", "handle_advisory"]
