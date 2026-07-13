"""Responses for catalog concepts that cannot form a published combination."""

from __future__ import annotations

from typing import Any

from response.builder import build_response
from schemas import ResponsePayload

from .category_handler import category_summary, display_category


async def handle_invalid_combination(
    state: Any = None,
    message: str = "",
    catalog: Any = None,
    category_index: Any = None,
    *,
    llm: Any = None,
    **_: Any,
) -> ResponsePayload:
    """Explain an explicit university/course conflict without guessing a record."""

    del message, llm
    focus = getattr(state, "focus", None)
    university = getattr(focus, "university_concept", None) or getattr(
        focus, "university", None
    )
    category = getattr(focus, "course_concept", None) or getattr(focus, "category", None)
    specialization = getattr(focus, "specialization_concept", None) or getattr(
        focus, "specialization", None
    )
    requested = specialization or (display_category(str(category)) if category else "that program")
    text = (
        f"{university or 'That university'} does not currently offer {requested} "
        "in the published DegreeBaba catalog."
    )
    chips: list[str] = []
    if category:
        providers = category_summary(str(category), category_index, catalog).get(
            "universities", ()
        )
        chips = [f"Tell me about {provider}" for provider in list(providers)[:6]]
        if providers:
            text += f" Available providers include: {', '.join(providers)}."
    return build_response(text, suggested_chips=chips)


handle = handle_invalid_combination

__all__ = ["handle", "handle_invalid_combination"]
