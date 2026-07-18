"""Deterministic experience helpers built on the existing catalog and focus state."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from data.accessor import safe_get
from response.cards import (
    catalog_get_entity,
    clean_text,
    entity_fee,
    entity_heading,
    entity_label,
    entity_page_type,
    entity_university,
    first_value,
    iter_catalog_entities,
    parse_money,
)
from response.templates import accreditation_items, topic_from_message
from schemas import CatalogOption, ProgramCard, QuickAction, ResponseContext
from taxonomy.index_builder import normalize_category

from .cards import build_program_card

_NEUTRAL = {"", "none", "no preference", "not sure", "not sure yet", "any"}


def _value(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(name, default)
    return getattr(item, name, default)


def _concept(value: Any) -> str | None:
    rendered = clean_text(value)
    return rendered or None


def _display_course(value: str | None) -> str | None:
    if not value:
        return None
    return value.upper() if len(value) <= 6 and value.replace("-", "").isalnum() else value


def context_from_state(
    state: Any,
    catalog: Any = None,
    *,
    entity: Any = None,
) -> ResponseContext:
    """Project the existing Focus; this never creates or mutates conversational state."""

    focus = _value(state, "focus")
    entity_id = _concept(_value(focus, "entity_id"))
    resolved = entity or catalog_get_entity(catalog, entity_id)
    university = _concept(
        _value(focus, "university_concept") or _value(focus, "university")
    )
    course = _concept(_value(focus, "course_concept") or _value(focus, "category"))
    specialization = _concept(
        _value(focus, "specialization_concept") or _value(focus, "specialization")
    )

    if resolved is not None:
        page_type = entity_page_type(resolved)
        university = university or _concept(entity_university(resolved))
        if page_type == "university":
            university = university or _concept(entity_label(resolved))
        elif page_type == "course":
            course = _concept(
                first_value(resolved, "program_name", "category", default=None)
            ) or course
        elif page_type == "specialization":
            linked_course = catalog_get_entity(catalog, safe_get(resolved, "linked_course", None))
            course = _concept(safe_get(linked_course, "program_name", None)) or course or _concept(
                first_value(resolved, "program_name", "parent_course", default=None)
            )
            specialization = specialization or _concept(
                first_value(
                    resolved,
                    "specialization_name",
                    "spec_name",
                    default=None,
                )
            )
        entity_id = entity_id or _concept(first_value(resolved, "id", "entity_id", default=None))

    course = _display_course(course)
    parts = [value for value in (university, course, specialization) if value]
    return ResponseContext(
        university=university,
        course=course,
        specialization=specialization,
        entity_id=entity_id,
        label=" · ".join(dict.fromkeys(parts)) or None,
    )


def context_from_entity(entity: Any, catalog: Any = None) -> ResponseContext:
    """Build page context from one entity and its published relationships."""

    page_type = entity_page_type(entity)
    university = _concept(entity_university(entity))
    course = None
    specialization = None
    if page_type == "university":
        university = _concept(entity_label(entity))
    elif page_type == "course":
        course = _display_course(
            _concept(first_value(entity, "program_name", "category", default=None))
        )
    elif page_type == "specialization":
        linked_course = catalog_get_entity(catalog, safe_get(entity, "linked_course", None))
        course = _display_course(
            _concept(safe_get(linked_course, "program_name", None))
            or _concept(first_value(entity, "program_name", "parent_course", default=None))
        )
        specialization = _concept(
            first_value(entity, "specialization_name", "spec_name", default=None)
        )
    parts = [value for value in (university, course, specialization) if value]
    return ResponseContext(
        university=university,
        course=course,
        specialization=specialization,
        entity_id=_concept(first_value(entity, "id", "entity_id", default=None)),
        label=" · ".join(dict.fromkeys(parts)) or None,
    )


def resolve_page_entity(catalog: Any, reference: str, page_type: str | None = None) -> Any:
    """Resolve an exact id, slug, or unique publisher alias for page context."""

    entity = catalog_get_entity(catalog, reference)
    if entity is None:
        normalized = clean_text(reference).casefold()
        metadata = _value(catalog, "metadata", {})
        matches = [
            item
            for item in metadata.values()
            if normalized == clean_text(_value(item, "slug")).casefold()
            or normalized
            in {clean_text(alias).casefold() for alias in (_value(item, "aliases", ()) or ())}
        ]
        if len(matches) == 1:
            entity = catalog_get_entity(catalog, _value(matches[0], "id"))
    if entity is not None and page_type and entity_page_type(entity) != page_type:
        return None
    return entity


def _compact_action_label(value: str, *, limit: int = 24) -> str:
    """Visually shorten a label without changing the message sent on selection."""

    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip(" .,:;!?-") + "…"


def _faq_actions(entity: Any) -> list[tuple[str, str, frozenset[str]]]:
    result: list[tuple[str, str, frozenset[str]]] = []
    for faq in safe_get(entity, "faqs", []) or []:
        question = clean_text(safe_get(faq, "question", None))
        if question:
            result.append(
                (_compact_action_label(question), question, frozenset({"faq"}))
            )
        if len(result) >= 3:
            break
    return result


def quick_actions_for_response(
    *,
    entity: Any = None,
    message: str = "",
    route: str = "",
) -> list[QuickAction]:
    """Return exactly three compact actions, ending with the counsellor escape hatch."""

    page_type = entity_page_type(entity) if entity is not None else ""
    subject = entity_heading(entity) if entity is not None else ""
    answered = "comparison" if route == "comparison" else topic_from_message(message)
    banks: dict[str, list[tuple[str, str, frozenset[str]]]] = {
        "university": [
            ("Show me programs", f"{subject} programs", frozenset({"programs"})),
            ("See accreditations", f"{subject} accreditations", frozenset({"accreditation"})),
            ("Read student reviews", f"{subject} student reviews", frozenset({"reviews"})),
            ("Compare my options", f"Compare {subject}", frozenset({"comparison"})),
        ],
        "course": [
            ("Show fees & EMI", f"{subject} fees and EMI", frozenset({"fee", "emi"})),
            ("Am I eligible?", f"{subject} eligibility", frozenset({"eligibility"})),
            ("Show specializations", f"{subject} specializations", frozenset({"specializations"})),
            ("Compare my options", f"Compare {subject}", frozenset({"comparison"})),
        ],
        "specialization": [
            ("Show career & salary", f"{subject} career and salary", frozenset({"jobs"})),
            ("Show me the syllabus", f"{subject} syllabus", frozenset({"syllabus"})),
            (
                "Show other specialties",
                f"{subject} other specializations",
                frozenset({"specializations"}),
            ),
            ("Compare my options", f"Compare {subject}", frozenset({"comparison"})),
        ],
        "": [
            ("Show me universities", "Browse universities", frozenset({"universities"})),
            ("Show me programs", "Browse course categories", frozenset({"programs"})),
            ("Compare my options", "Compare universities", frozenset({"comparison"})),
        ],
    }
    bank = banks.get(page_type, banks[""])
    faq_actions = _faq_actions(entity) if entity else []
    # An overview has no more-specific answered topic, so page FAQs are the most
    # grounded next questions. Topic-specific answers retain their curated bank.
    candidates = (
        [*faq_actions, *bank]
        if faq_actions and answered == "about"
        else [*bank, *faq_actions]
    )
    actions: list[QuickAction] = []
    seen: set[str] = set()
    answered_message = clean_text(message).casefold()
    for label, action_message, topics in candidates:
        key = label.casefold()
        if (
            answered in topics
            or action_message.casefold() == answered_message
            or len(label) > 24
            or key in seen
        ):
            continue
        actions.append(QuickAction(label=label, message=action_message))
        seen.add(key)
        if len(actions) == 2:
            break
    for label, action_message in (
        ("Show me programs", "Browse course categories"),
        ("Compare my options", "Compare universities"),
        ("Show me universities", "Browse universities"),
    ):
        if len(actions) == 2:
            break
        if label.casefold() not in seen and not (
            answered == "comparison" and label == "Compare my options"
        ):
            actions.append(QuickAction(label=label, message=action_message))
            seen.add(label.casefold())
    actions.append(QuickAction(label="Talk to a counsellor", message="Talk to a counsellor"))
    return actions[:3]


def _option_meta(entity: Any) -> str | None:
    page_type = entity_page_type(entity)
    details: list[str] = []
    naac = clean_text(safe_get(entity, "naac_grade", None))
    ugc = next(
        (
            value
            for value in accreditation_items(entity)
            if value.casefold().startswith("ugc")
        ),
        clean_text(first_value(entity, "ugc_status", default=None)),
    )
    if naac:
        details.append(f"NAAC {naac}")
    if ugc:
        details.append(ugc)
    if page_type == "university":
        programs = safe_get(entity, "program_ids", None) or safe_get(
            entity, "programs_table", []
        ) or []
        if programs:
            details.append(f"{len(programs)} programs")
    elif page_type == "course":
        duration = clean_text(safe_get(entity, "duration", None))
        if duration:
            details.append(duration)
    else:
        fee = entity_fee(entity)
        if fee:
            details.append(fee)
    return " · ".join(details) or None


def _catalog_option(entity: Any) -> CatalogOption | None:
    entity_id = clean_text(first_value(entity, "id", "entity_id", default=None))
    if not entity_id:
        return None
    return CatalogOption(
        id=entity_id,
        slug=clean_text(safe_get(entity, "slug", None)) or entity_id,
        page_type=entity_page_type(entity),
        name=entity_label(entity),
        university_name=_concept(entity_university(entity)),
        category=_concept(
            first_value(entity, "program_name", "parent_course", "category", default=None)
        ),
        meta=_option_meta(entity),
    )


def _same_reference(entity: Any, reference: str, catalog: Any) -> bool:
    linked = first_value(entity, "linked_university.id", "linked_university", default=None)
    candidate_values = {
        clean_text(linked).casefold(),
        entity_university(entity).casefold(),
    }
    resolved = catalog_get_entity(catalog, reference)
    target_values = {clean_text(reference).casefold()}
    if resolved is not None:
        target_values.update(
            {
                clean_text(safe_get(resolved, "id", None)).casefold(),
                clean_text(safe_get(resolved, "slug", None)).casefold(),
                entity_label(resolved).casefold(),
                entity_university(resolved).casefold(),
            }
        )
    return bool(candidate_values.intersection(target_values))


def catalog_options(
    catalog: Any,
    kind: str,
    *,
    university: str | None = None,
    program: str | None = None,
    query: str | None = None,
) -> tuple[list[CatalogOption], list[CatalogOption]]:
    page_type_by_kind = {
        "university": "university",
        "program": "course",
        "specialization": "specialization",
    }
    if kind not in page_type_by_kind:
        raise ValueError("kind must be university, program, or specialization")
    page_type = page_type_by_kind[kind]
    normalized_program = clean_text(program).casefold()
    normalized_query = clean_text(query).casefold()
    entities: list[Any] = []
    for entity in iter_catalog_entities(catalog):
        if entity_page_type(entity) != page_type:
            continue
        if university and page_type != "university" and not _same_reference(
            entity, university, catalog
        ):
            continue
        if normalized_program:
            category = clean_text(
                first_value(entity, "program_name", "parent_course", "category", default=None)
            ).casefold()
            linked_course = clean_text(
                first_value(entity, "linked_course.id", "linked_course", default=None)
            ).casefold()
            if normalized_program not in {
                category,
                linked_course,
                entity_label(entity).casefold(),
            } and normalized_program not in entity_label(entity).casefold():
                continue
        haystack = " ".join(
            (
                entity_label(entity),
                entity_university(entity),
                clean_text(
                    first_value(
                        entity,
                        "program_name",
                        "parent_course",
                        "discipline",
                        "category",
                        default=None,
                    )
                ),
            )
        ).casefold()
        if normalized_query and normalized_query not in haystack:
            continue
        entities.append(entity)

    deduplicated: list[Any] = []
    seen: set[str] = set()
    for entity in entities:
        if page_type == "course":
            key = normalize_category(
                first_value(entity, "program_name", "category", default=None)
            ) or entity_label(entity).casefold()
        elif page_type == "specialization":
            key = entity_label(entity).casefold()
        else:
            key = clean_text(first_value(entity, "id", "slug", default=None)).casefold()
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(entity)

    def popularity_rank(entity: Any) -> int | None:
        for field in ("traffic_rank", "popularity_rank", "popular_rank"):
            raw = safe_get(entity, field, None)
            try:
                rank = int(str(raw).strip())
            except (TypeError, ValueError):
                continue
            if rank > 0:
                return rank
        return None

    def explicitly_popular(entity: Any) -> bool:
        if popularity_rank(entity) is not None:
            return True
        for field in ("is_popular", "popular"):
            raw = safe_get(entity, field, None)
            if raw is True or str(raw).strip().casefold() in {"1", "true", "yes"}:
                return True
        return False

    popular_entities = sorted(
        (entity for entity in deduplicated if explicitly_popular(entity)),
        key=lambda value: (
            popularity_rank(value) is None,
            popularity_rank(value) or 0,
            entity_label(value).casefold(),
            entity_university(value).casefold(),
        ),
    )
    popular = [
        option for entity in popular_entities[:8] if (option := _catalog_option(entity)) is not None
    ]
    deduplicated.sort(
        key=lambda value: (entity_label(value).casefold(), entity_university(value).casefold())
    )
    options = [
        option for entity in deduplicated if (option := _catalog_option(entity)) is not None
    ]
    return options, popular


def _neutral(value: Any) -> bool:
    return clean_text(value).casefold() in _NEUTRAL


def _matches_program(entity: Any, program: str) -> bool:
    def key(value: Any) -> str:
        normalized = " ".join(clean_text(value).casefold().replace("-", " ").split())
        return normalized.removeprefix("online ").strip()

    requested = key(program)
    if not requested:
        return False
    published = {
        key(safe_get(entity, "category", None)),
        key(safe_get(entity, "program_name", None)),
    }
    published.discard("")
    return requested in published


def _budget_bounds(value: Any) -> tuple[float | None, float | None] | None:
    if value is None or _neutral(value):
        return None
    if isinstance(value, (int, float)):
        return None, float(value)
    normalized = clean_text(value).casefold().replace("₹", "inr ").replace("\u2013", "-")
    if "under" in normalized and "1l" in normalized:
        return None, 100_000
    if "1-2" in normalized:
        return 100_000, 200_000
    if "2-3" in normalized:
        return 200_000, 300_000
    if "3l+" in normalized or "3 lakh+" in normalized:
        return 300_000, None
    amount = parse_money(value)
    return (None, amount) if amount is not None else None


def _approval_value(entity: Any, catalog: Any, *paths: str) -> str:
    direct = clean_text(first_value(entity, *paths, default=None))
    if direct:
        return direct
    linked = catalog_get_entity(catalog, safe_get(entity, "linked_university", None))
    return clean_text(first_value(linked, *paths, default=None)) if linked is not None else ""


def _approval_values(entity: Any, catalog: Any, *paths: str) -> list[str]:
    values = [clean_text(first_value(entity, *paths, default=None))]
    linked = catalog_get_entity(catalog, safe_get(entity, "linked_university", None))
    if linked is not None:
        values.append(clean_text(first_value(linked, *paths, default=None)))
    return [value for value in values if value]


def _structured_accreditation_values(
    entity: Any,
    catalog: Any,
    accreditation_type: str,
) -> list[str]:
    """Read V3 accreditation objects before consulting legacy display strings."""

    candidates = [entity]
    linked = catalog_get_entity(catalog, safe_get(entity, "linked_university", None))
    if linked is not None:
        candidates.append(linked)
    values: list[str] = []
    for candidate in candidates:
        for accreditation in safe_get(candidate, "accreditations", []) or []:
            item_type = clean_text(safe_get(accreditation, "type", None))
            if item_type.casefold() != accreditation_type.casefold():
                continue
            values.append(clean_text(safe_get(accreditation, "value", None)))
    return [value for value in values if value]


def _matches_approval(entity: Any, approval: str, catalog: Any) -> bool:
    normalized = clean_text(approval).casefold()
    if normalized in _NEUTRAL:
        return True
    if "ugc-deb" in normalized or "ugc deb" in normalized:
        structured = _structured_accreditation_values(entity, catalog, "UGC")
        if structured:
            return any(
                value.casefold() in {"entitled", "recognized", "approved"}
                for value in structured
            )
        return any(
            "deb" in value.casefold() or "ugc entitled" in value.casefold()
            for value in _approval_values(entity, catalog, "ugc_status", "ugc_approved")
        )
    if "ugc" in normalized:
        if _structured_accreditation_values(entity, catalog, "UGC"):
            return True
        return "ugc" in _approval_value(
            entity, catalog, "ugc_status", "ugc_approved"
        ).casefold()
    if "naac" in normalized and "a+" in normalized:
        return _approval_value(entity, catalog, "naac_grade").upper() in {"A+", "A++"}
    return False


def _representative_three(entities: list[Any]) -> list[Any]:
    priced = [entity for entity in entities if parse_money(entity_fee(entity)) is not None]
    pool = priced if len(priced) >= 3 else entities
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
    indexes = (0, (len(ordered) - 1) // 2, len(ordered) - 1)
    return [ordered[index] for index in indexes]


def finder_results(
    catalog: Any,
    *,
    program: str | None = None,
    area: str | None = None,
    approval: str | None = None,
    budget: Any = None,
) -> tuple[list[ProgramCard], int]:
    courses = [
        entity for entity in iter_catalog_entities(catalog) if entity_page_type(entity) == "course"
    ]
    if program and not _neutral(program):
        courses = [entity for entity in courses if _matches_program(entity, program)]

    if area and not _neutral(area):
        target = clean_text(area).casefold()
        course_ids = {
            clean_text(
                first_value(entity, "linked_course.id", "linked_course", default=None)
            )
            for entity in iter_catalog_entities(catalog)
            if entity_page_type(entity) == "specialization"
            and target
            in clean_text(
                first_value(entity, "specialization_name", "spec_name", default=None)
            ).casefold()
        }
        courses = [
            entity
            for entity in courses
            if clean_text(first_value(entity, "id", "entity_id", default=None)) in course_ids
        ]

    if approval and not _neutral(approval):
        courses = [
            entity for entity in courses if _matches_approval(entity, approval, catalog)
        ]

    bounds = _budget_bounds(budget)
    if bounds is not None:
        minimum, maximum = bounds
        courses = [
            entity
            for entity in courses
            if (fee := parse_money(entity_fee(entity))) is not None
            and (minimum is None or fee >= minimum)
            and (maximum is None or fee <= maximum)
        ]

    matched_count = len(courses)
    results = [build_program_card(entity, catalog) for entity in _representative_three(courses)]
    return results, matched_count


__all__ = [
    "catalog_options",
    "context_from_entity",
    "context_from_state",
    "finder_results",
    "quick_actions_for_response",
    "resolve_page_entity",
]
