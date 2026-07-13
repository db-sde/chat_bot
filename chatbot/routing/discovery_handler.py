"""Top-level program discovery."""

from __future__ import annotations

from typing import Any

from response.builder import build_response
from schemas import ResponsePayload

from .category_handler import available_categories, display_category, handle_category
from .list_handler import handle_list_providers


async def handle_discovery(
    state: Any = None,
    message: str = "",
    catalog: Any = None,
    category_index: Any = None,
    *,
    llm: Any = None,
    **_: Any,
) -> ResponsePayload:
    """Show category choices rather than guessing a university or course."""

    focus = getattr(state, "focus", None)
    specialization = getattr(focus, "specialization_concept", None) or getattr(
        focus, "specialization", None
    )
    category = getattr(focus, "course_concept", None) or getattr(focus, "category", None)
    university = getattr(focus, "university_concept", None) or getattr(
        focus, "university", None
    )
    if specialization and not university:
        return await handle_list_providers(
            state=state,
            message=message,
            catalog=catalog,
            category_index=category_index,
            specialization=str(specialization),
        )
    if category and not university:
        return await handle_category(
            state=state,
            message=message,
            catalog=catalog,
            category_index=category_index,
        )

    del llm
    categories = available_categories(category_index, catalog)
    labels = [display_category(category) for category in categories[:6]]

    greeting = str(message or "").strip().casefold()
    prefix = "Hi! " if greeting in {"hi", "hello", "hey", "good morning", "good evening"} else ""
    text = (
        f"{prefix}I can help you explore online programs, compare course categories, "
        "or check fees, eligibility, and duration for a university. Which category "
        "would you like to start with?"
    )
    return build_response(text, suggested_chips=labels)


handle = handle_discovery

__all__ = ["handle", "handle_discovery"]
