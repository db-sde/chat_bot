"""Canonical response-payload construction."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from schemas import ResponsePayload


def normalize_chips(chips: Iterable[Any] | None, *, limit: int = 6) -> list[str]:
    """Trim, deduplicate, and cap suggested chips while preserving order."""

    result: list[str] = []
    seen: set[str] = set()
    for chip in chips or ():
        value = str(chip).strip()
        key = value.casefold()
        if not value or key in seen:
            continue
        seen.add(key)
        result.append(value)
        if len(result) >= limit:
            break
    return result


def build_response(
    text: Any,
    *,
    suggested_chips: Iterable[Any] | None = None,
    cta: Any = None,
) -> ResponsePayload:
    """Build the one response shape accepted by every route."""

    rendered = str(text or "").strip()
    if not rendered:
        rendered = "What would you like to know about online universities or programs?"
    return ResponsePayload(
        text=rendered,
        suggested_chips=normalize_chips(suggested_chips),
        cta=cta,
    )


__all__ = ["build_response", "normalize_chips"]
