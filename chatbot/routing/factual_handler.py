"""Deterministic entity-level factual lookup."""

from __future__ import annotations

from typing import Any

from data.accessor import safe_get
from response.builder import build_response
from response.cards import (
    clean_text,
    entity_label,
    find_catalog_entity,
    first_value,
)
from response.templates import render_topic, suggested_chips, topic_from_message
from schemas import ResponsePayload


def _focus(state: Any) -> Any:
    return getattr(state, "focus", None)


def _cached_entity(state: Any, entity_id: str | None) -> Any:
    if state is None or not entity_id:
        return None
    cache = getattr(state, "entity_cache", None)
    return safe_get(cache, [entity_id], None)


def _load_focused_entity(state: Any, catalog: Any, explicit: Any = None) -> Any:
    if explicit is not None:
        return explicit
    focus = _focus(state)
    entity_id = getattr(focus, "entity_id", None)
    cached = _cached_entity(state, entity_id)
    if cached is not None:
        return cached

    if entity_id and catalog is not None:
        cache_method = getattr(catalog, "cache_in_state", None)
        if callable(cache_method) and state is not None:
            try:
                entity = cache_method(entity_id, state)
            except (KeyError, TypeError, ValueError):
                entity = None
            if entity is not None:
                return entity
        entity = find_catalog_entity(catalog, entity_id)
        if entity is not None:
            return entity

    for reference in (
        getattr(focus, "specialization", None),
        getattr(focus, "university", None),
    ):
        entity = find_catalog_entity(catalog, reference)
        if entity is not None:
            return entity
    return None


async def _synthesized_overview(entity: Any, llm: Any) -> str | None:
    """Make at most one short, grounded synthesis call for broad overviews."""

    synthesize = getattr(llm, "synthesize", None)
    if not callable(synthesize):
        return None
    configured = getattr(llm, "synthesis_configured", True)
    if not configured:
        return None

    subject = entity_label(entity)
    fields = [
        clean_text(safe_get(entity, "hero_description", None), max_chars=300),
        clean_text(safe_get(entity, "about_content", None), max_chars=900),
        clean_text(safe_get(entity, "why_choose_content", None), max_chars=500),
    ]
    context = "\n".join(value for value in fields if value)
    if not context:
        return None
    prompt = (
        f"Answer in 2-3 concise sentences using only this published data about {subject}. "
        "Do not infer rankings, outcomes, or missing facts.\n\n"
        f"{context}"
    )
    try:
        result = await synthesize(prompt)
    except Exception:
        return None
    text = str(result or "").strip()
    return text or None


async def handle_factual(
    state: Any = None,
    message: str = "",
    catalog: Any = None,
    category_index: Any = None,
    *,
    entity: Any = None,
    topic: str | None = None,
    llm: Any = None,
    use_llm: bool = True,
    **_: Any,
) -> ResponsePayload:
    """Answer from cached publisher data, degrading cleanly on absent fields."""

    del category_index
    focused_entity = _load_focused_entity(state, catalog, explicit=entity)
    if focused_entity is None:
        return build_response(
            "I couldn't load a single published record for that request. "
            "Which university or course should I check?",
            suggested_chips=["Explore MBA", "Browse universities", "Compare courses"],
        )

    selected_topic = topic or topic_from_message(message)
    text: str | None = None
    if selected_topic == "about" and llm is not None and use_llm:
        text = await _synthesized_overview(focused_entity, llm)
    if not text:
        text = render_topic(selected_topic, focused_entity)

    chips = suggested_chips(focused_entity, selected_topic)
    if not chips:
        page_type = str(first_value(focused_entity, "_meta.page_type", "page_type", default=""))
        if page_type == "university":
            chips = [
                label
                for label, paths in (
                    ("Programs", ("programs_table",)),
                    ("Accreditations", ("accreditations", "naac_grade", "ugc_approved")),
                    ("Reviews", ("reviews",)),
                )
                if any(safe_get(focused_entity, path, None) for path in paths)
            ][:3]
    return build_response(text, suggested_chips=chips)


handle = handle_factual

__all__ = ["handle", "handle_factual"]
