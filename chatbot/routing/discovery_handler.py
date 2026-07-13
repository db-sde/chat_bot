"""Top-level program discovery."""

from __future__ import annotations

import re
from typing import Any

from response.builder import build_response
from response.cards import (
    entity_label,
    entity_page_type,
    iter_catalog_entities,
    render_sections,
)
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

    if re.search(
        r"\b(?:browse|explore|show|list)(?:\s+me)?\s+universit(?:y|ies)\b",
        message,
        flags=re.IGNORECASE,
    ):
        universities = sorted(
            {
                entity_label(entity)
                for entity in iter_catalog_entities(catalog)
                if entity_page_type(entity) == "university"
            },
            key=str.casefold,
        )
        shown = universities[:8]
        return build_response(
            render_sections(
                "Browse Online Universities",
                [("Published Universities", shown)],
                intro=(
                    f"The catalog currently contains {len(universities)} published "
                    "university profiles. Choose one to explore its programs."
                ),
            ),
            suggested_chips=[f"Tell me about {name}" for name in shown[:6]],
        )

    focus = getattr(state, "focus", None)
    specialization = getattr(focus, "specialization_concept", None) or getattr(
        focus, "specialization", None
    )
    category = getattr(focus, "course_concept", None) or getattr(focus, "category", None)
    university = getattr(focus, "university_concept", None) or getattr(focus, "university", None)
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
    text = render_sections(
        "Explore Online Programs",
        [("Course Categories", labels)],
        intro=(
            f"{prefix}I can help you explore programs, compare categories, or check "
            "published fees, eligibility, and duration. Which category would you "
            "like to start with?"
        ),
    )
    return build_response(text, suggested_chips=labels)


handle = handle_discovery

__all__ = ["handle", "handle_discovery"]
