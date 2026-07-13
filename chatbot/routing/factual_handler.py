"""Deterministic entity-level factual lookup."""

from __future__ import annotations

from typing import Any

from data.accessor import safe_get
from response.builder import build_response
from response.cards import (
    catalog_get_entity,
    clean_text,
    entity_label,
    entity_university,
    find_catalog_entity,
    first_value,
)
from response.templates import render_topic, suggested_chips, topic_from_message
from schemas import ResponsePayload
from taxonomy.alias_tables import normalize_text


def _focus(state: Any) -> Any:
    return getattr(state, "focus", None)


def _cached_entity(state: Any, entity_id: str | None) -> Any:
    if state is None or not entity_id:
        return None
    cache = getattr(state, "entity_cache", None)
    return safe_get(cache, [entity_id], None)


def _concept(focus: Any, primary: str, legacy: str) -> str | None:
    value = getattr(focus, primary, None) or getattr(focus, legacy, None)
    return str(value) if value else None


def _cache_resolved(state: Any, catalog: Any, entity_id: str) -> Any:
    cache_method = getattr(catalog, "cache_in_state", None)
    if callable(cache_method) and state is not None:
        try:
            entity = cache_method(entity_id, state)
        except (KeyError, TypeError, ValueError):
            entity = None
        if entity is not None:
            focus = _focus(state)
            if focus is not None and hasattr(focus, "entity_id"):
                focus.entity_id = entity_id
            return entity
    return find_catalog_entity(catalog, entity_id)


def _university_entity_id(catalog: Any, concept: str) -> str | None:
    list_metadata = getattr(catalog, "list_metadata", None)
    if not callable(list_metadata):
        return None
    query = set(normalize_text(concept).split())
    matches: list[str] = []
    for item in list_metadata("university"):
        names = (
            getattr(item, "canonical_name", None),
            getattr(item, "university_name", None),
        )
        if any(
            query
            and (tokens := set(normalize_text(name).split()))
            and (query <= tokens or tokens <= query)
            for name in names
            if name
        ):
            matches.append(str(item.id))
    unique = list(dict.fromkeys(matches))
    return unique[0] if len(unique) == 1 else None


def _load_focused_entity(
    state: Any,
    catalog: Any,
    category_index: Any,
    explicit: Any = None,
    *,
    multiple_matches: list[str] | None = None,
) -> Any:
    if explicit is not None:
        return explicit
    focus = _focus(state)

    # Canonical concepts are the authoritative focus. Resolve the concrete
    # publisher record here, at the handler boundary, and only then populate the
    # legacy entity_id cache used by older sessions and synthesis code.
    university = _concept(focus, "university_concept", "university")
    category = _concept(focus, "course_concept", "category")
    specialization = _concept(focus, "specialization_concept", "specialization")
    if category_index is not None and (category or specialization):
        university_keys = [university] if university else [None]
        legacy_university = getattr(focus, "university", None)
        metadata = (
            getattr(catalog, "get_metadata", lambda _value: None)(legacy_university)
            if legacy_university
            else None
        )
        if metadata is not None:
            university_keys.extend(
                value
                for value in (
                    getattr(metadata, "university_name", None),
                    getattr(metadata, "canonical_name", None),
                )
                if value
            )
        matches: set[str] = set()
        for university_key in university_keys:
            matches.update(
                category_index.intersect(
                    category=category,
                    specialization=specialization,
                    university=university_key,
                )
            )
        desired_type = "specialization" if specialization else "course"
        matches = {
            entity_id
            for entity_id in matches
            if getattr(catalog.get_metadata(entity_id), "page_type", None) == desired_type
        }
        if len(matches) == 1:
            return _cache_resolved(state, catalog, next(iter(matches)))
        if len(matches) > 1:
            # A provider-less specialization is one concept backed by multiple
            # publisher records. Never fall through to ``find_catalog_entity``:
            # its exact-name lookup would silently select the first provider.
            if multiple_matches is not None:
                multiple_matches.extend(sorted(matches))
            return None
    elif university:
        university_id = _university_entity_id(catalog, university)
        if university_id:
            return _cache_resolved(state, catalog, university_id)

    # Backward-compatible fallback for focus JSON written before concept fields
    # existed. New turns take the concept-first path above.
    entity_id = getattr(focus, "entity_id", None)
    cached = _cached_entity(state, entity_id)
    if cached is not None:
        return cached

    if entity_id and catalog is not None:
        entity = _cache_resolved(state, catalog, entity_id)
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

    multiple_matches: list[str] = []
    focused_entity = _load_focused_entity(
        state,
        catalog,
        category_index,
        explicit=entity,
        multiple_matches=multiple_matches,
    )
    if focused_entity is None and multiple_matches:
        focus = _focus(state)
        specialization = _concept(focus, "specialization_concept", "specialization")
        category = _concept(focus, "course_concept", "category")
        subject = specialization or category or "that program"
        providers = sorted(
            {
                provider
                for entity_id in multiple_matches
                if (candidate := catalog_get_entity(catalog, entity_id)) is not None
                if (provider := entity_university(candidate))
            },
            key=str.casefold,
        )
        selected_topic = topic or topic_from_message(message)
        detail = "published information" if selected_topic == "about" else selected_topic
        return build_response(
            f"{subject} has published records from multiple universities. "
            f"Which university should I use for the {detail} answer?",
            suggested_chips=[f"{provider} {subject}" for provider in providers],
        )
    if focused_entity is None:
        return build_response(
            "I couldn't load a single published record for that request. "
            "Which university or course should I check?",
            suggested_chips=["Browse course categories", "Browse universities", "Compare courses"],
        )

    selected_topic = topic or topic_from_message(message)
    text: str | None = None
    if selected_topic == "about" and llm is not None and use_llm:
        text = await _synthesized_overview(focused_entity, llm)
    if not text:
        text = render_topic(selected_topic, focused_entity, catalog=catalog)

    chips = suggested_chips(
        focused_entity,
        selected_topic,
        catalog=catalog,
    )
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
