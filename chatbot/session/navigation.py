"""Deterministic navigation-state transitions for the guided widget."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .state import ConversationState, NavigationState, NavigationStep

PAGE_SURFACES: dict[str, str] = {
    "homepage": "page:home",
    "pillar": "page:pillar",
    "university": "page:university",
    "course": "page:course",
    "specialization": "page:specialization",
}

PAGE_STEPS: dict[str, NavigationStep] = {
    "homepage": NavigationStep.HOMEPAGE,
    "pillar": NavigationStep.HOMEPAGE,
    "university": NavigationStep.UNIVERSITY_CARD,
    "course": NavigationStep.COURSE_CARD,
    "specialization": NavigationStep.SPECIALIZATION_CARD,
}

CHIP_STEPS: dict[str, NavigationStep] = {
    "browse_universities": NavigationStep.UNIVERSITY_PICKER,
    "list_providers": NavigationStep.UNIVERSITY_PICKER,
    "browse_programs": NavigationStep.COURSE_PICKER,
    "programs_here": NavigationStep.COURSE_PICKER,
    "eligible_programs": NavigationStep.COURSE_PICKER,
    "specializations": NavigationStep.SPECIALIZATION_PICKER,
    "other_specs": NavigationStep.SPECIALIZATION_PICKER,
    "fees_emi": NavigationStep.FEES,
    "starting_fees": NavigationStep.FEES,
    "fees_across": NavigationStep.FEES,
    "see_fees": NavigationStep.FEES,
    "eligibility": NavigationStep.ELIGIBILITY,
    "check_eligibility": NavigationStep.ELIGIBILITY,
    "careers": NavigationStep.CAREERS,
    "careers_from_syllabus": NavigationStep.CAREERS,
    "approvals": NavigationStep.APPROVALS,
    "reviews": NavigationStep.REVIEWS,
    "average_rating": NavigationStep.REVIEWS,
    "placement_support": NavigationStep.CAREERS,
    "why_choose": NavigationStep.UNIVERSITY_CARD,
    "syllabus": NavigationStep.SYLLABUS,
    "admission_process": NavigationStep.ADMISSIONS,
    "admission_steps": NavigationStep.ADMISSIONS,
    "admissions": NavigationStep.ADMISSIONS,
    "validity": NavigationStep.VALIDITY,
    "validity_course": NavigationStep.VALIDITY,
    "compare": NavigationStep.COMPARISON,
    "compare_rival": NavigationStep.COMPARISON,
    "compare_top": NavigationStep.COMPARISON,
    "compare_universities": NavigationStep.COMPARISON,
    "compare_others": NavigationStep.COMPARISON,
    "compare_program": NavigationStep.COMPARISON,
    "compare_specializations": NavigationStep.COMPARISON,
    "roi_tool": NavigationStep.TOOL,
    "career_quiz_tool": NavigationStep.TOOL,
    "specialization_quiz_tool": NavigationStep.TOOL,
    "scholarship_tool": NavigationStep.TOOL,
    "apply_now": NavigationStep.LEAD_CAPTURE,
    "counsellor": NavigationStep.LEAD_CAPTURE,
}

ANSWER_STEPS: dict[str, NavigationStep] = {
    "fees": NavigationStep.FEES,
    "eligibility_yes": NavigationStep.ELIGIBILITY,
    "eligibility_no": NavigationStep.ELIGIBILITY,
    "eligibility_borderline": NavigationStep.ELIGIBILITY,
    "careers": NavigationStep.CAREERS,
    "approvals": NavigationStep.APPROVALS,
    "reviews": NavigationStep.REVIEWS,
    "average_rating": NavigationStep.REVIEWS,
    "placement": NavigationStep.CAREERS,
    "overview": NavigationStep.UNIVERSITY_CARD,
    "syllabus": NavigationStep.SYLLABUS,
    "validity": NavigationStep.VALIDITY,
    "comparison": NavigationStep.COMPARISON,
    # An empty specialization result is information about the selected course,
    # not a new navigation destination. Keep the course card authoritative.
    "no_specializations": NavigationStep.COURSE_CARD,
}


def _value(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(name, default)
    return getattr(item, name, default)


def sync_page_navigation(
    state: ConversationState,
    *,
    page_type: str,
    entity_id: str | None = None,
    config_version: str = "",
) -> NavigationState:
    """Synchronise context and visible-chip origin in one atomic state update."""

    normalized = str(page_type or "homepage").strip().casefold()
    if normalized not in PAGE_SURFACES:
        normalized = "homepage"
    navigation = state.navigation
    next_entity_id = entity_id or None
    journey_changed = (
        navigation.page_type != normalized
        or navigation.entity_id != next_entity_id
    )
    if journey_changed:
        navigation.interaction_count = 0
        navigation.completed_actions.clear()
        navigation.step = PAGE_STEPS[normalized]
        navigation.surface = PAGE_SURFACES[normalized]
    navigation.page_type = normalized
    navigation.entity_id = next_entity_id
    if normalized in {"homepage", "pillar"}:
        navigation.university_id = None
        navigation.course_id = None
        navigation.specialization_id = None
    elif normalized == "university":
        navigation.university_id = entity_id or navigation.university_id
        navigation.course_id = None
        navigation.specialization_id = None
    elif normalized == "course":
        navigation.course_id = entity_id or navigation.course_id
        navigation.specialization_id = None
    elif normalized == "specialization":
        navigation.specialization_id = entity_id or navigation.specialization_id
    if config_version:
        navigation.config_version = config_version
    return navigation


def advance_navigation(
    state: ConversationState,
    *,
    chip_id: str | None,
    surface: str | None = None,
) -> NavigationState:
    """Record one guided action and advance through the central transition table."""

    navigation = state.navigation
    if surface:
        navigation.surface = str(surface)
    if chip_id and navigation.mark_completed(chip_id):
        navigation.interaction_count += 1
        navigation.step = CHIP_STEPS.get(chip_id, navigation.step)
    return navigation


def advance_answer_navigation(
    state: ConversationState,
    *,
    answer_state: str | None,
) -> NavigationState:
    """Apply an answer-state transition without changing interaction depth."""

    normalized = str(answer_state or "").strip().casefold()
    step = ANSWER_STEPS.get(normalized)
    if step is not None:
        state.navigation.step = step
    return state.navigation


def navigation_payload(state: ConversationState) -> dict[str, Any]:
    return state.navigation.model_dump(mode="json")


__all__ = [
    "ANSWER_STEPS",
    "CHIP_STEPS",
    "PAGE_STEPS",
    "PAGE_SURFACES",
    "advance_answer_navigation",
    "advance_navigation",
    "navigation_payload",
    "sync_page_navigation",
]
