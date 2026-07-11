"""Useful, non-dead-end fallback response."""

from __future__ import annotations

from typing import Any

from response.builder import build_response
from response.cta import lead_capture_cta
from schemas import ResponsePayload


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

    del state, message, catalog, category_index, llm
    return build_response(
        "I couldn't confidently match that to the published catalog. Could you share a "
        "university name, a course such as MBA or MCA, or a specialization?",
        suggested_chips=["Explore MBA", "Browse universities", "Compare MBA and MCA"],
        cta=lead_capture_cta(),
    )


handle = handle_fallback

__all__ = ["handle", "handle_fallback"]
