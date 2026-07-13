"""Honest responses for named concepts absent from the published catalog."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from response.builder import build_response
from response.templates import entity_not_found_answer
from schemas import ResponsePayload

from .category_handler import available_categories, category_summary, display_category


def _display_unknowns(values: Sequence[str]) -> str:
    cleaned = [" ".join(str(value).strip().split()) for value in values if str(value).strip()]
    if not cleaned:
        return "that name"
    if len(cleaned) == 1:
        return cleaned[0]
    return ", ".join(cleaned[:-1]) + f" and {cleaned[-1]}"


async def handle_unsupported_entity(
    state: Any = None,
    message: str = "",
    catalog: Any = None,
    category_index: Any = None,
    *,
    unknown_entities: Sequence[str] | None = None,
    llm: Any = None,
    **_: Any,
) -> ResponsePayload:
    """Acknowledge unknown names and retain useful catalog-backed scope."""

    del message, llm
    focus = getattr(state, "focus", None)
    unknowns = list(unknown_entities or getattr(focus, "unknown_entities", ()) or ())
    missing = _display_unknowns(unknowns)
    category = getattr(focus, "course_concept", None) or getattr(focus, "category", None)
    if category:
        summary = category_summary(str(category), category_index, catalog)
        providers = list(summary.get("universities") or ())
        if providers:
            label = display_category(str(category))
            return build_response(
                f"I couldn't find {missing} in the DegreeBaba catalog.\n\n"
                f"Available {label} providers include: {', '.join(providers)}.",
                suggested_chips=[f"Tell me about {provider}" for provider in providers[:6]],
            )
    categories = [
        display_category(item)
        for item in available_categories(category_index, catalog)[:2]
    ]
    return build_response(
        entity_not_found_answer(missing, None),
        suggested_chips=[
            *[f"Explore {item}" for item in categories],
            "Browse universities",
            "Talk to a counsellor",
        ],
    )


handle = handle_unsupported_entity

__all__ = ["handle", "handle_unsupported_entity"]
