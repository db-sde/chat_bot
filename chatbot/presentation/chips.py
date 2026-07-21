"""Transport adapters for config-owned funnel chips."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from data.accessor import safe_get
from funnel import FollowupChipSet, OpeningChipSet, ResolvedChip
from response.cards import catalog_get_entity, entity_page_type, iter_catalog_entities
from schemas import QuickAction


def _published(value: Any) -> bool:
    if value is None or value is False:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (Mapping, list, tuple, set)):
        return bool(value)
    return True


def _linked(entity: Any, field: str, catalog: Any) -> Any:
    reference = safe_get(entity, field, None)
    if reference is None:
        return None
    if entity_page_type(reference):
        return reference
    nested_id = safe_get(reference, "id", None)
    return catalog_get_entity(catalog, nested_id or reference)


def _catalog_sources(entity: Any, catalog: Any) -> tuple[Any, ...]:
    sources: list[Any] = [entity]
    if entity_page_type(entity) == "specialization":
        course = _linked(entity, "linked_course", catalog)
        if course is not None:
            sources.append(course)
    university = _linked(entity, "linked_university", catalog)
    if university is None and len(sources) > 1:
        university = _linked(sources[1], "linked_university", catalog)
    if university is not None:
        sources.append(university)
    return tuple(sources)


def _any_published(sources: Iterable[Any], *fields: str) -> bool:
    return any(_published(safe_get(source, field, None)) for source in sources for field in fields)


def _has_comparison_option(entity: Any, catalog: Any) -> bool:
    page_type = entity_page_type(entity)
    entity_id = safe_get(entity, "id", None)
    category = str(
        safe_get(entity, "category", None)
        or safe_get(entity, "program_name", None)
        or ""
    ).casefold()
    specialization = str(
        safe_get(entity, "specialization_name", None)
        or safe_get(entity, "spec_name", None)
        or ""
    ).casefold()
    for candidate in iter_catalog_entities(catalog):
        if safe_get(candidate, "id", None) == entity_id or entity_page_type(candidate) != page_type:
            continue
        if page_type == "course":
            candidate_category = str(
                safe_get(candidate, "category", None)
                or safe_get(candidate, "program_name", None)
                or ""
            ).casefold()
            if category and candidate_category == category:
                return True
        elif page_type == "specialization":
            candidate_specialization = str(
                safe_get(candidate, "specialization_name", None)
                or safe_get(candidate, "spec_name", None)
                or ""
            ).casefold()
            if specialization and candidate_specialization == specialization:
                return True
        else:
            return True
    return False


def catalog_chip_context(entity: Any, catalog: Any) -> dict[str, bool] | None:
    """Project Catalog V3 fields into stable chip capabilities."""

    if entity is None:
        return None
    page_type = entity_page_type(entity)
    sources = _catalog_sources(entity, catalog)
    review_count = safe_get(entity, "review_count", None)
    reviews = safe_get(entity, "reviews", None)
    average_rating = safe_get(entity, "average_rating", None)
    has_reviews = (
        bool(review_count > 0)
        if isinstance(review_count, (int, float)) and not isinstance(review_count, bool)
        else _published(reviews)
    )
    if not has_reviews and page_type == "university":
        uni_id = safe_get(entity, "id", None)
        linked_courses = [
            c
            for c in iter_catalog_entities(catalog)
            if entity_page_type(c) == "course"
            and safe_get(c, "linked_university", None) == uni_id
        ]
        has_reviews = any(_published(safe_get(c, "reviews", None)) for c in linked_courses)

    direct_careers = _any_published(
        (entity,),
        "career_outcomes",
        "career_tracks",
        "salary_outcomes",
        "job_profiles",
    )
    return {
        "programs": _any_published((entity,), "program_ids", "programs_table"),
        "reviews": has_reviews,
        "average_rating": (
            isinstance(average_rating, (int, float))
            and not isinstance(average_rating, bool)
        ) or (page_type == "university" and has_reviews),
        "accreditations": _any_published(
            sources,
            "accreditations",
            "ugc_approved",
            "ugc_status",
            "naac_grade",
        ),
        "placement_support": any(
            safe_get(source, "placement_support", None) is True for source in sources
        ),
        "fees": _any_published(
            sources,
            "fee_metadata",
            "fee_plans",
            "starting_fee",
            "starting_fee_numeric",
            "total_fee",
            "total_fee_numeric",
            "fee_numeric",
            "emi_amount",
            "emi_content",
        ),
        "why_choose": _any_published(
            (entity,), "why_choose_content", "hero_description", "about_content"
        ),
        "admissions": _any_published(sources, "admission_steps"),
        "eligibility": _any_published(
            sources,
            "eligibility_summary",
            "eligibility_content",
            "eligibility_requirements",
        ),
        "specializations": page_type == "course"
        and _any_published((entity,), "specialization_ids"),
        "other_specializations": page_type == "specialization"
        and _any_published((entity,), "other_specs"),
        "careers": direct_careers,
        "syllabus": _any_published(
            (entity,), "syllabus", "semesters", "syllabus_semesters", "syllabus_content"
        ),
        "scholarship": _any_published(sources, "scholarship_available", "scholarship_types"),
        "roi": _any_published(
            sources,
            "starting_fee_numeric",
            "total_fee_numeric",
            "fee_numeric",
        ),
        "validity": _any_published(
            sources,
            "validity",
            "certificate_description",
            "accreditations",
            "ugc_approved",
            "ugc_status",
        ),
        "comparison": _has_comparison_option(entity, catalog),
        "faqs": _any_published((entity,), "faqs"),
    }


def chip_message(chip: ResolvedChip) -> str:
    if chip.handler == "tool_entry" and chip.tool:
        return f"tool:{chip.tool}"
    if chip.handler == "cta_apply":
        return "Apply now"
    if chip.handler == "cta_callback":
        return "Talk to a counsellor"
    # Labels are deterministic config content and every non-tool handler already
    # has a matching guided-widget adapter or ordinary NLU phrase.
    return chip.label


def resolved_chip_action(
    chip: ResolvedChip,
    *,
    surface: str,
    config_version: str,
    content_version: str = "not_applicable",
    interaction_count: int = 0,
    correlation_id: str | None = None,
    lead_tags: dict[str, object] | None = None,
) -> QuickAction:
    return QuickAction(
        label=chip.label,
        message=chip_message(chip),
        chip_id=chip.id,
        chip_handler=chip.handler,
        tool=chip.tool,  # type: ignore[arg-type]
        surface=surface,
        funnel_stage=chip.funnel_stage.value,
        config_version=config_version,
        content_version=content_version,
        interaction_count=max(0, int(interaction_count)),
        correlation_id=correlation_id,
        lead_tags=lead_tags,
    )


def chip_actions(
    chips: Iterable[ResolvedChip],
    *,
    surface: str,
    config_version: str,
    content_version: str = "not_applicable",
    interaction_count: int = 0,
    correlation_id: str | None = None,
    lead_tags: dict[str, object] | None = None,
) -> list[QuickAction]:
    return [
        resolved_chip_action(
            chip,
            surface=surface,
            config_version=config_version,
            content_version=content_version,
            interaction_count=interaction_count,
            correlation_id=correlation_id,
            lead_tags=lead_tags,
        )
        for chip in chips
    ]


def opening_payload(
    opening: OpeningChipSet,
    *,
    correlation_id: str | None = None,
) -> dict[str, object]:
    return {
        "surface": opening.surface,
        "funnel_stage": (
            opening.top[0].funnel_stage.value
            if opening.top
            else opening.more[0].funnel_stage.value if opening.more else "top"
        ),
        "config_version": opening.config_version,
        "content_version": "not_applicable",
        "interaction_count": 0,
        "correlation_id": correlation_id,
        "missing_surface": opening.missing_surface,
        "top": [
            action.model_dump(mode="json", exclude_none=True)
            for action in chip_actions(
                opening.top,
                surface=opening.surface,
                config_version=opening.config_version,
                correlation_id=correlation_id,
            )
        ],
        "more": [
            action.model_dump(mode="json", exclude_none=True)
            for action in chip_actions(
                opening.more,
                surface=opening.surface,
                config_version=opening.config_version,
                correlation_id=correlation_id,
            )
        ],
    }


def followup_payload(
    followup: FollowupChipSet,
    *,
    correlation_id: str | None = None,
    content_version: str = "not_applicable",
) -> dict[str, object]:
    return {
        "surface": followup.surface,
        "funnel_stage": followup.funnel_stage.value,
        "interaction_count": followup.interaction_count,
        "config_version": followup.config_version,
        "content_version": content_version,
        "correlation_id": correlation_id,
        "missing_surface": followup.missing_surface,
        "actions": [
            action.model_dump(mode="json", exclude_none=True)
            for action in chip_actions(
                followup.chips,
                surface=followup.surface,
                config_version=followup.config_version,
                content_version=content_version,
                interaction_count=followup.interaction_count,
                correlation_id=correlation_id,
            )
        ],
    }


__all__ = [
    "catalog_chip_context",
    "chip_actions",
    "chip_message",
    "followup_payload",
    "opening_payload",
    "resolved_chip_action",
]
