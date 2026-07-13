"""Render pending candidate choices without silently selecting one."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from data.accessor import safe_get
from response.builder import build_response
from response.cards import (
    catalog_get_entity,
    entity_label,
    entity_page_type,
    entity_university,
    numbered_lines,
)
from schemas import ResponsePayload


def _pending_candidates(state: Any) -> list[Any]:
    pending = getattr(state, "pending_clarification", None)
    values = getattr(pending, "candidates", None)
    return list(values or [])


def _candidate_identity(candidate: Any) -> Any:
    if isinstance(candidate, (str, int)):
        return candidate
    return safe_get(candidate, "entity_id", None) or safe_get(candidate, "id", None)


def _candidate_label(candidate: Any, catalog: Any) -> str:
    identity = _candidate_identity(candidate)
    entity = catalog_get_entity(catalog, identity)
    if entity is not None:
        label = entity_label(entity, default=str(identity or ""))
        university = entity_university(entity)
        if (
            university
            and entity_page_type(entity) in {"course", "specialization"}
            and university.casefold() != label.casefold()
        ):
            return f"{label} — {university}"
        return label

    get_metadata = getattr(catalog, "get_metadata", None)
    if callable(get_metadata) and identity is not None:
        try:
            metadata = get_metadata(str(identity))
        except (KeyError, TypeError, ValueError):
            metadata = None
        if metadata is not None:
            label = safe_get(metadata, "canonical_name", None)
            university = safe_get(metadata, "university_name", None)
            if label and university and str(label).casefold() != str(university).casefold():
                return f"{label} — {university}"
            if label:
                return str(label)

    direct = safe_get(candidate, "canonical_name", None) or safe_get(candidate, "name", None)
    if direct:
        return str(direct)
    if isinstance(identity, str) and ":" in identity:
        slot_type, value = identity.split(":", 1)
        if slot_type.casefold() == "category" and value.strip():
            return value.strip().upper()
        if value.strip():
            return value.strip().replace("-", " ").title()
    return str(identity or "Unknown option")


async def handle_clarification(
    state: Any = None,
    message: str = "",
    catalog: Any = None,
    category_index: Any = None,
    *,
    candidates: Sequence[Any] | None = None,
    slot_type: str | None = None,
    llm: Any = None,
    **_: Any,
) -> ResponsePayload:
    """List every candidate and let the user disambiguate by name or ordinal."""

    del message, category_index, llm
    values = list(candidates) if candidates is not None else _pending_candidates(state)
    labels: list[str] = []
    seen: set[str] = set()
    for candidate in values:
        label = _candidate_label(candidate, catalog).strip()
        if label and label.casefold() not in seen:
            seen.add(label.casefold())
            labels.append(label)

    if not labels:
        noun = slot_type or "option"
        return build_response(
            f"I need one more detail to identify the {noun}. Which university, course, "
            "or specialization did you mean?",
            suggested_chips=[
                "Search universities",
                "Browse course categories",
                "Browse specializations",
            ],
        )

    if len(labels) == 1:
        return build_response(
            f"Did you mean {labels[0]}?",
            suggested_chips=[labels[0], "None of these"],
        )

    noun = slot_type or "match"
    text = f"I found more than one {noun}. Which one did you mean?\n{numbered_lines(labels)}"
    return build_response(text, suggested_chips=labels[:6])


handle = handle_clarification

__all__ = ["handle", "handle_clarification"]
