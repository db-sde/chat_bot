"""Small catalog formatting primitives shared by guided card builders."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from response.cards import clean_text, first_value, has_value
from schemas import CardFact


def optional_text(value: Any, *, max_chars: int | None = None) -> str | None:
    rendered = clean_text(value, max_chars=max_chars)
    return rendered or None


def catalog_strings(
    value: Any,
    *,
    fields: Sequence[str] = ("name", "title"),
    limit: int = 8,
) -> list[str]:
    if not has_value(value):
        return []
    items = (
        value
        if isinstance(value, Iterable) and not isinstance(value, (str, bytes, Mapping))
        else (value,)
    )
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        rendered = (
            clean_text(item)
            if isinstance(item, (str, int, float))
            else clean_text(first_value(item, *fields, default=None))
        )
        key = rendered.casefold()
        if not rendered or key in seen:
            continue
        seen.add(key)
        result.append(rendered)
        if len(result) >= limit:
            break
    return result


def card_fact(label: str, value: Any, *, max_chars: int = 300) -> CardFact | None:
    rendered_label = clean_text(label)
    rendered_value = clean_text(value, max_chars=max_chars)
    if not rendered_label or not rendered_value:
        return None
    return CardFact(label=rendered_label, value=rendered_value)


def unique_facts(facts: Iterable[CardFact | None], *, limit: int = 8) -> list[CardFact]:
    result: list[CardFact] = []
    seen: set[tuple[str, str]] = set()
    for fact in facts:
        if fact is None:
            continue
        key = (fact.label.casefold(), fact.value.casefold())
        if key in seen:
            continue
        seen.add(key)
        result.append(fact)
        if len(result) >= limit:
            break
    return result


__all__ = [
    "card_fact",
    "catalog_strings",
    "optional_text",
    "unique_facts",
]
