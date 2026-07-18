"""Add rich presentation data to a canonical :class:`ResponsePayload`."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from enum import Enum
from typing import Any

import logging_setup
from response.builder import build_transport_components
from response.cards import (
    catalog_get_entity,
    clean_text,
    entity_fee,
    entity_label,
    entity_page_type,
    entity_university,
    first_value,
    iter_catalog_entities,
    parse_money,
)
from response.templates import topic_from_message
from schemas import (
    CardListComponent,
    ComparisonCard,
    LeadCTAComponent,
    ProgramCard,
    QuickAction,
    QuickActionsComponent,
    ResponseComponent,
    ResponsePayload,
    UniversityCard,
)
from taxonomy.index_builder import normalize_category

from .cards import (
    build_comparison_card,
    build_comparison_card_from_text,
    build_entity_card,
)
from .chips import chip_actions
from .experience import context_from_state, quick_actions_for_response
from .formatter import advisor_message


def _value(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(name, default)
    return getattr(item, name, default)


def _route_name(route: Any) -> str:
    candidate = route
    if isinstance(route, Mapping):
        candidate = next(
            (
                route[key]
                for key in ("route", "name", "intent", "action")
                if route.get(key) is not None
            ),
            "",
        )
    elif route is not None and not isinstance(route, (str, Enum)):
        candidate = next(
            (
                value
                for key in ("route", "name", "intent", "action")
                if (value := getattr(route, key, None)) is not None
            ),
            route,
        )
    if isinstance(candidate, Enum):
        candidate = candidate.value
    return str(candidate or "").strip().casefold()


def _component_type(component: Any) -> str:
    return str(_value(component, "type", ""))


def _as_operands(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (str, bytes, Mapping)):
        return [value]
    if isinstance(value, Iterable):
        return list(value)
    return [value]


def _structured_operands(
    explicit: Iterable[Any] | None,
    route: Any,
    state: Any,
) -> list[Any]:
    if explicit is not None:
        return _as_operands(explicit)
    for source in (route, state):
        for field in (
            "comparison_operands",
            "comparison_entity_ids",
            "entity_ids",
            "comparison_universities",
            "universities",
        ):
            value = _value(source, field)
            if value:
                return _as_operands(value)
    return []


def _resolve_entity(entity: Any, state: Any, route: Any, catalog: Any) -> Any:
    candidate = entity if entity is not None else _value(route, "entity")
    if candidate is not None:
        if isinstance(candidate, (str, int)):
            return catalog_get_entity(catalog, candidate)
        if entity_page_type(candidate):
            return candidate
        reference = _value(candidate, "entity_id") or _value(candidate, "id")
        if reference:
            resolved = catalog_get_entity(catalog, reference)
            if resolved is not None:
                return resolved

    focus = _value(state, "focus")
    entity_id = _value(focus, "entity_id") or _value(route, "entity_id")
    resolved = catalog_get_entity(catalog, entity_id)
    if resolved is not None:
        return resolved

    cache = _value(state, "entity_cache", {})
    if entity_id and isinstance(cache, Mapping):
        cached = cache.get(str(entity_id))
        if cached is not None:
            return cached
    return None


def _comparison_title(text: str) -> str:
    for line in str(text or "").splitlines():
        candidate = clean_text(line)
        if candidate and not candidate.startswith(("•", "-", "*")):
            return candidate[:100]
    return "Comparison"


def _data_comparison_title(card: ComparisonCard) -> str:
    labels = [item.subtitle or item.name for item in card.items]
    labels = list(dict.fromkeys(clean_text(label) for label in labels if clean_text(label)))
    return " vs ".join(labels[:3]) or "Comparison"


def _compact_choice_label(value: Any) -> str:
    rendered = clean_text(value)
    if len(rendered) <= 24:
        return rendered
    compact = re.sub(r"\bUniversity\b", "Uni", rendered, flags=re.IGNORECASE)
    compact = re.sub(r"\s+Online$", "", compact, flags=re.IGNORECASE)
    if len(compact) <= 24:
        return compact
    return f"{compact[:23].rstrip()}…"


def _clarification_actions(chips: Iterable[Any]) -> list[QuickAction]:
    actions: list[QuickAction] = []
    seen: set[str] = set()
    for chip in chips:
        message = clean_text(chip)
        key = message.casefold()
        if not message or key in seen:
            continue
        seen.add(key)
        actions.append(QuickAction(label=_compact_choice_label(message), message=message))
        if len(actions) == 3:
            return actions
    if len(actions) == 1:
        actions.append(
            QuickAction(
                label="Browse programs",
                message="Browse programs",
            )
        )
    if len(actions) < 3 and "talk to a counsellor" not in seen:
        actions.append(
            QuickAction(
                label="Talk to a counsellor",
                message="Talk to a counsellor",
            )
        )
    return actions


def _representative_entities(entities: Iterable[Any]) -> list[Any]:
    values = list(entities)
    priced = [entity for entity in values if parse_money(entity_fee(entity)) is not None]
    pool = priced if len(priced) >= 3 else values
    ordered = sorted(
        pool,
        key=lambda entity: (
            parse_money(entity_fee(entity)) is None,
            parse_money(entity_fee(entity)) or 0,
            entity_university(entity).casefold(),
            entity_label(entity).casefold(),
        ),
    )
    if len(ordered) <= 3:
        return ordered
    return [ordered[0], ordered[(len(ordered) - 1) // 2], ordered[-1]]


def _list_card_entities(route_name: str, state: Any, catalog: Any) -> list[Any]:
    focus = _value(state, "focus")
    if route_name == "category":
        category = _value(focus, "course_concept") or _value(focus, "category")
        normalized = normalize_category(category)
        if not normalized:
            return []
        matches = [
            entity
            for entity in iter_catalog_entities(catalog)
            if entity_page_type(entity) == "course"
            and normalize_category(first_value(entity, "program_name", "category", default=None))
            == normalized
        ]
        return _representative_entities(matches)

    if route_name != "list_providers":
        return []
    specialization = clean_text(
        _value(focus, "specialization_concept") or _value(focus, "specialization")
    )
    if not specialization:
        return []
    universities: dict[str, Any] = {}
    for entity in iter_catalog_entities(catalog):
        if entity_page_type(entity) != "specialization":
            continue
        label = clean_text(first_value(entity, "specialization_name", "spec_name", default=None))
        if label.casefold() != specialization.casefold():
            continue
        linked = first_value(entity, "linked_university.id", "linked_university", default=None)
        university = catalog_get_entity(catalog, linked)
        if university is None or entity_page_type(university) != "university":
            continue
        identity = clean_text(first_value(university, "id", "slug", default=None))
        if identity:
            universities.setdefault(identity, university)
    return sorted(universities.values(), key=lambda value: entity_label(value).casefold())[:3]


def _card_list(route_name: str, state: Any, catalog: Any, text: str) -> CardListComponent | None:
    entities = _list_card_entities(route_name, state, catalog)
    if not entities:
        return None
    title = _comparison_title(text)
    return CardListComponent(
        title=title,
        items=[build_entity_card(entity, catalog) for entity in entities],
    )


def _requests_university_programs(message: str) -> bool:
    return bool(
        re.search(
            r"\b(?:show|list)\b.*\bprograms?\b.*\b(?:at|by|from)\b",
            clean_text(message),
            flags=re.IGNORECASE,
        )
    )


def _university_program_card_list(
    university: Any,
    catalog: Any,
) -> CardListComponent | None:
    if entity_page_type(university) != "university":
        return None
    university_id = clean_text(first_value(university, "id", "entity_id", default=None))
    university_names = {
        name.casefold()
        for name in (entity_university(university), entity_label(university))
        if name
    }
    courses = []
    for entity in iter_catalog_entities(catalog):
        if entity_page_type(entity) != "course":
            continue
        linked_id = clean_text(
            first_value(entity, "linked_university.id", "linked_university", default=None)
        )
        same_university = bool(university_id and linked_id == university_id) or (
            entity_university(entity).casefold() in university_names
        )
        if same_university:
            courses.append(entity)
    courses.sort(key=lambda entity: entity_label(entity).casefold())
    if not courses:
        return None
    return CardListComponent(
        title=f"{entity_label(university)} Programs",
        items=[build_entity_card(entity, catalog) for entity in courses[:3]],
    )


def _tool_program_card_list(
    tool_flow: Mapping[str, Any] | None,
    catalog: Any,
) -> CardListComponent | None:
    if tool_flow is None or tool_flow.get("step") != "reveal":
        return None
    identifiers = tool_flow.get("cta_program_ids")
    if not isinstance(identifiers, Iterable) or isinstance(identifiers, (str, bytes, Mapping)):
        return None

    cards: list[ProgramCard] = []
    seen: set[str] = set()
    for identifier in identifiers:
        key = clean_text(identifier)
        if not key or key in seen:
            continue
        seen.add(key)
        resolved = catalog_get_entity(catalog, key)
        if resolved is None:
            continue
        candidate = build_entity_card(resolved, catalog)
        if isinstance(candidate, ProgramCard):
            cards.append(candidate)
        if len(cards) == 3:
            break
    if not cards:
        return None
    return CardListComponent(title="Recommended programs", items=cards)


def _chip_delivery_context(state: Any) -> tuple[int, str | None]:
    navigation = _value(state, "navigation")
    interaction_count = max(0, int(_value(navigation, "interaction_count", 0) or 0))
    session_id = clean_text(_value(state, "session_id"))
    if not session_id:
        return interaction_count, None
    turn_count = max(0, int(_value(state, "turn_count", 0) or 0))
    correlation_id = logging_setup.correlation_id(
        session_id,
        max(turn_count, interaction_count, 1),
    )
    return interaction_count, correlation_id


def _positive_eligibility(text: str) -> bool:
    normalized = clean_text(text).casefold()
    return bool(
        re.search(
            r"(?:^|[.!?]\s+)(?:yes\b|you(?:'re| are) eligible\b|you qualify\b)",
            normalized,
        )
    )


def _delivers_value(text: str, value: str | None) -> bool:
    rendered = clean_text(value).casefold()
    return bool(rendered and rendered in clean_text(text).casefold())


def _card_list_message(card_list: CardListComponent) -> str:
    count = len(card_list.items)
    subject = re.sub(r"\s+Programs$", "", clean_text(card_list.title), flags=re.IGNORECASE)
    item_kind = (
        "universities"
        if card_list.items and isinstance(card_list.items[0], UniversityCard)
        else "program options"
    )
    quantity = "three representative" if count == 3 else str(count)
    suffix = f" for {subject}" if subject else ""
    return f"Here are {quantity} published {item_kind}{suffix}."


def enrich_response(
    payload: ResponsePayload | Mapping[str, Any],
    *,
    state: Any = None,
    route: Any = None,
    catalog: Any = None,
    entity: Any = None,
    operands: Iterable[Any] | None = None,
    message: str = "",
    chip_engine: Any = None,
) -> ResponsePayload:
    """Return an additive rich response without mutating routing or focus state.

    Structured comparison operands are authoritative. Existing comparison text is
    parsed only when no such operands are available to the presentation layer.
    """

    current = (
        payload if isinstance(payload, ResponsePayload) else ResponsePayload.model_validate(payload)
    )
    route_name = _route_name(route)
    resolved_entity = _resolve_entity(entity, state, route, catalog)
    existing: list[ResponseComponent | dict[str, Any]] = list(current.components)
    component_types = {_component_type(component) for component in existing}
    raw_tool_flow = current.metadata.get("tool_flow")
    tool_flow = raw_tool_flow if isinstance(raw_tool_flow, Mapping) else None

    card: ResponseComponent | None = None
    if route_name == "comparison" and "comparison_card" not in component_types:
        structured = _structured_operands(operands, route, state)
        if structured:
            card = build_comparison_card(
                structured,
                catalog,
                title="Comparison",
            )
            if isinstance(card, ComparisonCard):
                card = card.model_copy(update={"title": _data_comparison_title(card)})
        else:
            card = build_comparison_card_from_text(
                current.text,
                title=_comparison_title(current.text),
            )
    elif (
        resolved_entity is not None
        and "university_card" not in component_types
        and "program_card" not in component_types
        and (
            route_name in {"factual", "university", "program", "specialization"}
            or entity is not None
        )
    ):
        if _requests_university_programs(message):
            card = _university_program_card_list(resolved_entity, catalog)
        if card is None:
            card = build_entity_card(resolved_entity, catalog)

    if card is None and "card_list" not in component_types:
        card = _tool_program_card_list(tool_flow, catalog)
    if card is None and "card_list" not in component_types:
        card = _card_list(route_name, state, catalog, current.text)

    if card is not None:
        existing.insert(0, card)

    # Keep legacy chip strings untouched, but make the modern action contract compact
    # and deterministic for a one-card mobile viewport.
    existing = [
        component
        for component in existing
        if _component_type(component) != "quick_actions"
        and not (current.cta is not None and _component_type(component) == "lead_cta")
    ]
    components = build_transport_components(
        suggested_chips=None,
        cta=current.cta,
        components=existing,
    )

    presentation_card = next(
        (
            component
            for component in components
            if isinstance(component, (UniversityCard, ProgramCard, ComparisonCard))
        ),
        None,
    )
    presentation_list = next(
        (component for component in components if isinstance(component, CardListComponent)),
        None,
    )
    interaction_count, correlation_id = _chip_delivery_context(state)
    if tool_flow is not None and current.quick_actions:
        if chip_engine is not None and tool_flow.get("step") == "reveal":
            navigation = _value(state, "navigation")
            followup = chip_engine.lookup(
                page_type=str(_value(navigation, "page_type", "homepage") or "homepage"),
                answer_state="tool_reveal",
                interaction_count=interaction_count,
                state=state,
            )
            quick_actions = chip_actions(
                followup.chips,
                surface=followup.surface,
                config_version=followup.config_version,
                content_version=str(tool_flow.get("version") or "not_applicable"),
                interaction_count=interaction_count,
                correlation_id=correlation_id,
                lead_tags=(
                    dict(tool_flow.get("lead_tags", {}))
                    if isinstance(tool_flow.get("lead_tags"), Mapping)
                    else None
                ),
            )
        else:
            quick_actions = list(current.quick_actions)
    elif route_name == "clarification" and current.suggested_chips:
        quick_actions = _clarification_actions(current.suggested_chips)
    elif chip_engine is not None:
        topic = topic_from_message(message)
        answer_state = {
            "fee": "fees",
            "emi": "fees",
            "jobs": "careers",
            "placements": "careers",
            "syllabus": "syllabus",
            "certificate": "validity",
            "accreditation": "approvals",
            "reviews": "reviews",
        }.get(topic)
        if route_name == "comparison":
            answer_state = "comparison"
        elif topic == "eligibility":
            answer_state = (
                "eligibility_yes"
                if _positive_eligibility(current.text)
                else "eligibility_borderline"
            )
        elif topic == "specializations" and any(
            marker in current.text.casefold()
            for marker in ("not been published", "no specialization", "no specialisation")
        ):
            answer_state = "no_specializations"

        card_type: str | None = None
        if answer_state is None:
            if isinstance(presentation_card, UniversityCard):
                card_type = "university"
            elif isinstance(presentation_card, ProgramCard):
                card_type = presentation_card.kind
            elif resolved_entity is not None:
                card_type = entity_page_type(resolved_entity) or None

        navigation = _value(state, "navigation")
        page_type = str(_value(navigation, "page_type", "homepage") or "homepage")
        followup = chip_engine.lookup(
            page_type=page_type,
            card_type=card_type,
            answer_state=answer_state,
            interaction_count=interaction_count,
            state=state,
        )
        quick_actions = chip_actions(
            followup.chips,
            surface=followup.surface,
            config_version=followup.config_version,
            interaction_count=interaction_count,
            correlation_id=correlation_id,
        )
    else:
        quick_actions = quick_actions_for_response(
            entity=resolved_entity,
            message=message,
            route=route_name,
        )
    if quick_actions:
        components.append(QuickActionsComponent(actions=quick_actions))

    topic = topic_from_message(message)
    lead_trigger: str | None = None
    if isinstance(presentation_card, ComparisonCard) and presentation_card.verdict:
        lead_trigger = "comparison_verdict"
    elif topic == "eligibility" and isinstance(presentation_card, ProgramCard):
        if presentation_card.eligibility and _positive_eligibility(current.text):
            lead_trigger = "published_eligibility"
    elif (
        topic == "fee"
        and isinstance(presentation_card, ProgramCard)
        and _delivers_value(current.text, presentation_card.fee)
    ):
        lead_trigger = "published_fee"
    elif (
        topic == "emi"
        and isinstance(presentation_card, ProgramCard)
        and _delivers_value(current.text, presentation_card.emi)
    ):
        lead_trigger = "published_emi"
    if lead_trigger and not any(
        _component_type(component) == "lead_cta" for component in components
    ):
        components.append(
            LeadCTAComponent(
                label="Check today's fee offer and seats",
                action="lead_capture",
                payload={"phone_only": True, "trigger": lead_trigger},
            )
        )

    presentation_message = advisor_message(
        current.text,
        card=presentation_card,
        next_actions=(action.message for action in quick_actions),
    )
    if presentation_list is not None and not (
        tool_flow is not None and tool_flow.get("step") == "reveal"
    ):
        presentation_message = _card_list_message(presentation_list)
    phone_only_lead = bool(
        route_name == "lead"
        and current.cta is not None
        and current.cta.action in {"lead_capture", "start_lead_capture"}
    )
    if phone_only_lead:
        presentation_message = (
            "Want me to check today's fee offer and seat availability? Share your number — no spam."
        )
    context = context_from_state(state, catalog, entity=resolved_entity)
    metadata = dict(current.metadata)
    metadata.update(
        {
            "route": route_name or None,
            "page_type": entity_page_type(resolved_entity) or None,
            "entity_id": context.entity_id,
        }
    )
    if phone_only_lead:
        metadata["lead_capture_mode"] = "phone_only"
    return current.model_copy(
        update={
            "message": presentation_message,
            "components": components,
            "quick_actions": quick_actions,
            "context": context,
            "metadata": metadata,
        }
    )


__all__ = ["enrich_response"]
