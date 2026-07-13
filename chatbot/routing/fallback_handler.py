"""Useful, non-dead-end fallback response."""

from __future__ import annotations

from typing import Any

from response.builder import build_response
from response.cta import lead_capture_cta
from schemas import ResponsePayload

from .category_handler import available_categories, display_category


async def handle_fallback(
    state: Any = None,
    message: str = "",
    catalog: Any = None,
    category_index: Any = None,
    *,
    llm: Any = None,
    **_: Any,
) -> ResponsePayload:
    """Recover with a bounded question and an optional human-help path."""

    del state, message, llm
    categories = [
        display_category(item)
        for item in available_categories(category_index, catalog)[:3]
    ]
    return build_response(
        "I couldn't confidently match that to the published catalog. Could you share a "
        "university name, a course category, or a specialization?",
        suggested_chips=[*[f"Explore {item}" for item in categories], "Browse universities"],
        cta=lead_capture_cta(),
    )


handle = handle_fallback

__all__ = ["handle", "handle_fallback"]
