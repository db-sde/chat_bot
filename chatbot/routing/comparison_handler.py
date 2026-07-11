"""Grounded category-to-category comparison."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from response.builder import build_response
from response.cards import format_inr
from schemas import ResponsePayload

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
    candidates = list(dict.fromkeys([*known, "mba", "mca", "bba", "bca", "mcom", "bcom"]))
    for category in candidates:
        normalized = str(category).strip().casefold()
        if not normalized:
            continue
        match = re.search(rf"(?<!\w){re.escape(normalized)}(?!\w)", text)
        if match:
            matches.append((match.start(), category))
    return [category for _, category in sorted(matches)]


async def handle_comparison(
    state: Any = None,
    message: str = "",
    catalog: Any = None,
    category_index: Any = None,
    *,
    categories: Sequence[str] | None = None,
    llm: Any = None,
    **_: Any,
) -> ResponsePayload:
    """Compare aggregate category data without choosing a university record."""

    del llm
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
        suggestions = [display_category(item) for item in known[:4]] or ["MBA", "MCA", "BBA"]
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
