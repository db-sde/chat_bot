"""Persisted, opt-in advisor questionnaire and catalog recommendation ranking."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from data.accessor import safe_get
from response.builder import build_response
from response.cards import (
    catalog_get_entity,
    clean_text,
    entity_label,
    entity_page_type,
    entity_university,
    first_value,
    format_inr,
    iter_catalog_entities,
    parse_money,
)
from schemas import ResponsePayload
from session.state import AdvisorField
from taxonomy.alias_tables import normalize_text
from taxonomy.index_builder import normalize_category

_LAKH_AMOUNT_RE = re.compile(
    r"(?<![\w.])(?:₹\s*|rs\.?\s*|inr\s*)?(\d+(?:\.\d+)?)\s*"
    r"(?:lakhs?|lacs?|l)(?!\w)",
    re.IGNORECASE,
)
_CURRENCY_AMOUNT_RE = re.compile(
    r"(?:₹\s*|\brs\.?\s*|\binr\s*)(\d[\d,]*(?:\.\d+)?)",
    re.IGNORECASE,
)
_GROUPED_OR_LARGE_AMOUNT_RE = re.compile(
    r"(?<![\d.])(\d{5,}(?:\.\d+)?|\d{1,3}(?:,\d{2})*,\d{3})(?![\d.])"
)
_CONTEXT_BUDGET_RE = re.compile(
    r"\b(?:budget|max(?:imum)?|under|below|within|up\s*to|upto)\b"
    r"[^\d₹]{0,24}(?:₹\s*)?(\d[\d,]*(?:\.\d+)?)",
    re.IGNORECASE,
)

_PERSONAL_ADVISOR_RE = re.compile(
    r"\b(?:(?:the\s+)?best\b[^?]{0,50}\bfor\s+me|which\b[^?]{0,50}\b(?:is|are)\s+(?:the\s+)?best\b|"
    r"recommend(?:\s+me)?\s+(?:a\s+)?"
    r"(?:universit(?:y|ies)|programs?|courses?)|recommend\b[^?]{0,60}\bfor\s+me|"
    r"help\s+me\s+(?:choose|decide)|which\b[^?]{0,80}\bshould\s+i\s+choose)\b",
    re.IGNORECASE,
)
_CANCEL_RE = re.compile(
    r"^\s*(?:cancel|stop|exit|quit|never\s*mind|leave\s+advisor(?:\s+mode)?)\s*[.!]?\s*$",
    re.IGNORECASE,
)
_RESTART_RE = re.compile(
    r"^\s*(?:restart|start\s+over|reset)(?:\s+(?:the\s+)?advisor)?\s*[.!]?\s*$",
    re.IGNORECASE,
)
_QUERY_PREFIX_RE = re.compile(
    r"^\s*(?:tell|show|browse|explore|compare|what|which|who|where|when|why|how|"
    r"is|are|do|does|can|could|would|give|list)\b",
    re.IGNORECASE,
)
_EDUCATION_PREFIX_RE = re.compile(
    r"^\s*(?:my\s+(?:current\s+)?education\s+is|i\s+(?:have\s+)?(?:completed|studied)|"
    r"i\s+(?:have|hold)\s+(?:an?\s+)?|i\s+am\s+(?:an?\s+)?|currently\s+)\s*",
    re.IGNORECASE,
)
_EXPERIENCE_RE = re.compile(
    r"\b(?:fresher|no\s+(?:work\s+)?experience|"
    r"(?:(?:less|more)\s+than\s+|under\s+|over\s+)?"
    r"\d+(?:\.\d+)?(?:\s*[-\u2013]\s*\d+(?:\.\d+)?)?\s*(?:\+\s*)?"
    r"(?:years?|yrs?|months?|mos?)"
    r"(?:\s+(?:of\s+)?(?:work\s+)?experience)?)\b",
    re.IGNORECASE,
)
_GOAL_PREFIX_RE = re.compile(
    r"^\s*(?:my\s+(?:career\s+)?goal\s+is|career\s+goal\s*[:=-]?|"
    r"i\s+want\s+to\s+(?:become|work\s+in|build\s+a\s+career\s+in)|"
    r"i(?:'d|\s+would)\s+like\s+to\s+(?:become|work\s+in))\s*",
    re.IGNORECASE,
)
_NO_PREFERENCE_RE = re.compile(
    r"^\s*(?:no\s+preference|none|not\s+sure|open\s+to\s+any|any)\s*[.!]?\s*$",
    re.IGNORECASE,
)

_FIELD_ORDER: tuple[AdvisorField, ...] = (
    "current_education",
    "work_experience",
    "career_goal",
    "budget",
    "preferred_specialization",
)

_QUESTIONS: Mapping[AdvisorField, tuple[str, tuple[str, ...]]] = {
    "current_education": (
        "## Advisor profile\n\n### Current education\n"
        "What is your current or highest completed education?",
        ("Completed graduation", "Currently in final year", "Completed Class 12"),
    ),
    "work_experience": (
        "## Advisor profile\n\n### Work experience\nHow much work experience do you have?",
        ("Fresher", "Less than 2 years", "2-5 years", "More than 5 years"),
    ),
    "career_goal": (
        "## Advisor profile\n\n### Career goal\n"
        "What role, industry, or career outcome are you aiming for?",
        (),
    ),
    "budget": (
        "## Advisor profile\n\n### Budget\nWhat is your maximum total program budget in INR?",
        (),
    ),
    "preferred_specialization": (
        "## Advisor profile\n\n### Preferred specialization\n"
        'Which specialization would you prefer? You can also say "no preference."',
        (),
    ),
}


def parse_budget(message: str) -> float | None:
    """Parse a user-stated INR ceiling without treating years as a budget."""

    text = str(message or "").replace("\u00a0", " ")
    match = _LAKH_AMOUNT_RE.search(text)
    if match:
        try:
            return float(match.group(1)) * 100_000
        except ValueError:
            return None
    for pattern in (
        _CURRENCY_AMOUNT_RE,
        _CONTEXT_BUDGET_RE,
        _GROUPED_OR_LARGE_AMOUNT_RE,
    ):
        match = pattern.search(text)
        if not match:
            continue
        try:
            amount = float(match.group(1).replace(",", ""))
        except ValueError:
            continue
        if amount >= 0:
            return amount
    return None


def is_personal_advisor_request(message: str) -> bool:
    """Distinguish guided personal advice from direct analytical shortlists."""

    return bool(_PERSONAL_ADVISOR_RE.search(str(message or "")))


def _clean_reply(message: str) -> str:
    return " ".join(str(message or "").strip(" \t\r\n.!?").split())


def _short_non_query(message: str, *, max_words: int = 14) -> str | None:
    value = _clean_reply(message)
    if (
        not value
        or "?" in message
        or _QUERY_PREFIX_RE.search(value)
        or len(value.split()) > max_words
    ):
        return None
    return value


def _specialization_from_mentions(mentions: Any) -> str | None:
    candidates = [
        candidate
        for candidate in getattr(mentions, "specializations", ()) or ()
        if str(getattr(candidate, "confidence", "")).upper() == "HIGH"
    ]
    if not candidates:
        return None
    spans = [_clean_reply(str(getattr(candidate, "matched_span", ""))) for candidate in candidates]
    spans = [value for value in spans if value]
    if spans:
        return max(spans, key=len).title()
    labels = [
        _clean_reply(str(getattr(candidate, "canonical_name", ""))) for candidate in candidates
    ]
    labels = [value for value in labels if value]
    return labels[0] if labels else None


def _extract_expected(field: AdvisorField, message: str, mentions: Any = None) -> Any:
    value = _clean_reply(message)
    if not value:
        return None
    if field == "current_education":
        direct = _short_non_query(message, max_words=12)
        if direct is None:
            return None
        stripped = _EDUCATION_PREFIX_RE.sub("", direct).strip()
        return stripped or None
    if field == "work_experience":
        match = _EXPERIENCE_RE.search(value)
        return _clean_reply(match.group(0)) if match else None
    if field == "career_goal":
        direct = _short_non_query(message, max_words=16)
        if direct is None:
            return None
        stripped = _GOAL_PREFIX_RE.sub("", direct).strip()
        return stripped or None
    if field == "budget":
        return parse_budget(message)
    if field == "preferred_specialization":
        if _NO_PREFERENCE_RE.fullmatch(value):
            return "No preference"
        mentioned = _specialization_from_mentions(mentions)
        if mentioned:
            return mentioned
        return _short_non_query(message, max_words=8)
    return None


def advisor_can_consume(state: Any, message: str, mentions: Any = None) -> bool:
    """Accept only a valid answer to the active advisor's expected field."""

    advisor = getattr(state, "advisor", None)
    if advisor is None or not getattr(advisor, "active", False):
        return False
    if _CANCEL_RE.fullmatch(message) or _RESTART_RE.fullmatch(message):
        return True
    field = getattr(advisor, "last_asked_field", None)
    return bool(field and _extract_expected(field, message, mentions) is not None)


def _category_specializations(
    category: str | None,
    catalog: Any,
    *,
    limit: int = 6,
) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    target = normalize_category(category or "")
    for entity in iter_catalog_entities(catalog):
        if entity_page_type(entity) != "specialization":
            continue
        entity_category = normalize_category(
            first_value(entity, "program_name", "parent_course", "category", default="")
        )
        if target and entity_category != target:
            continue
        name = clean_text(first_value(entity, "specialization_name", "spec_name", default=""))
        key = normalize_text(name)
        if name and key not in seen:
            seen.add(key)
            names.append(name)
    names.sort(key=str.casefold)
    return names[:limit]


def _next_missing(advisor: Any) -> AdvisorField | None:
    for field in _FIELD_ORDER:
        if getattr(advisor, field, None) in (None, ""):
            return field
    return None


def _question(advisor: Any, catalog: Any) -> ResponsePayload:
    field = _next_missing(advisor)
    if field is None:
        raise ValueError("advisor profile is complete")
    advisor.active = True
    advisor.last_asked_field = field
    text, chips = _QUESTIONS[field]
    if field == "preferred_specialization":
        chips = (*_category_specializations(advisor.category, catalog), "No preference")
    return build_response(text, suggested_chips=chips)


def _entity_text(entity: Any) -> str:
    pieces = [
        entity_label(entity),
        entity_university(entity),
        clean_text(safe_get(entity, "hero_description", None)),
        clean_text(safe_get(entity, "about_content", None)),
        clean_text(safe_get(entity, "placement_content", None)),
    ]
    for item in safe_get(entity, "highlights", []) or []:
        pieces.extend(
            (
                clean_text(safe_get(item, "highlight_title", None)),
                clean_text(safe_get(item, "highlight_description", None)),
            )
        )
    for item in safe_get(entity, "job_profiles", []) or []:
        pieces.append(clean_text(safe_get(item, "job_title", None)))
    for path in (
        "career_outcomes",
        "discovery_tags",
        "finder_tags",
        "career_tracks",
        "roi_tags",
        "search_keywords",
    ):
        pieces.extend(clean_text(value) for value in (safe_get(entity, path, []) or []))
    profile = safe_get(entity, "recommendation_profile", None)
    if isinstance(profile, Mapping):
        pieces.extend(clean_text(value) for value in profile.values())
    attributes = safe_get(entity, "recommendation_attributes", None)
    if isinstance(attributes, Mapping):
        pieces.extend(clean_text(key) for key, value in attributes.items() if value is True)
    return normalize_text(" ".join(pieces))


def _published_total_fee(entity: Any) -> tuple[float | None, str]:
    value = clean_text(safe_get(entity, "total_fee", None))
    if not value:
        for plan in safe_get(entity, "fee_plans", []) or []:
            value = clean_text(safe_get(plan, "plan_total", None))
            if value:
                break
    if not value:
        numeric = first_value(
            entity,
            "total_fee_numeric",
            "starting_fee_numeric",
            "fee_numeric",
            default=None,
        )
        if isinstance(numeric, (int, float)) and not isinstance(numeric, bool):
            value = format_inr(float(numeric))
    return parse_money(value), value


def _matches_specialization(entity: Any, preference: str | None) -> bool:
    if not preference or preference.casefold() == "no preference":
        return True
    target = set(normalize_text(preference).split())
    values = [
        clean_text(first_value(entity, "specialization_name", "spec_name", default="")),
        *[clean_text(value) for value in (safe_get(entity, "aliases", []) or [])],
    ]
    return any(
        target
        and (tokens := set(normalize_text(value).split()))
        and (target <= tokens or tokens <= target)
        for value in values
        if value
    )


def _candidate_pool(advisor: Any, catalog: Any) -> list[Any]:
    category = normalize_category(getattr(advisor, "category", None) or "")
    preference = getattr(advisor, "preferred_specialization", None)
    all_entities = iter_catalog_entities(catalog)
    page_type = "specialization" if preference and preference != "No preference" else "course"
    pool = [
        entity
        for entity in all_entities
        if entity_page_type(entity) == page_type
        and (
            not category
            or normalize_category(
                first_value(
                    entity,
                    "program_name",
                    "parent_course",
                    "category",
                    default="",
                )
            )
            == category
        )
        and _matches_specialization(entity, preference)
    ]
    # Sparse catalogs may publish a course without dedicated specialization pages.
    if not pool and page_type == "specialization":
        pool = [
            entity
            for entity in all_entities
            if entity_page_type(entity) == "course"
            and (
                not category
                or normalize_category(
                    first_value(entity, "program_name", "category", default="")
                )
                == category
            )
        ]
    return pool


def _ranked_recommendations(advisor: Any, catalog: Any, *, limit: int = 3) -> list[Any]:
    goal_terms = {
        token
        for token in normalize_text(getattr(advisor, "career_goal", None) or "").split()
        if len(token) > 2
    }
    budget = getattr(advisor, "budget", None)
    ranked: list[tuple[float, float, str, Any]] = []
    for entity in _candidate_pool(advisor, catalog):
        amount, _ = _published_total_fee(entity)
        if budget is not None and (amount is None or amount > budget):
            continue
        linked_university = catalog_get_entity(
            catalog,
            safe_get(entity, "linked_university", None),
        )
        searchable = " ".join(
            value
            for value in (
                _entity_text(entity),
                _entity_text(linked_university) if linked_university is not None else "",
            )
            if value
        )
        haystack = set(searchable.split())
        score = float(len(goal_terms & haystack))
        if _matches_specialization(entity, advisor.preferred_specialization):
            score += 5
        if safe_get(entity, "placement_content", None) or safe_get(entity, "job_profiles", None):
            score += 1
        if first_value(entity, "ugc_status", "ugc_approved", "naac_grade", default=None):
            score += 1
        attributes = safe_get(entity, "recommendation_attributes", None)
        if isinstance(attributes, Mapping):
            experience = normalize_text(getattr(advisor, "work_experience", None) or "")
            if (
                "fresher" in experience and attributes.get("freshers") is True
            ) or (
                experience
                and "fresher" not in experience
                and attributes.get("working_professional") is True
            ):
                score += 1
        if budget is not None and amount is not None:
            score += 2
        university = entity_university(entity) or entity_label(entity)
        ranked.append((score, -(amount or float("inf")), university.casefold(), entity))
    ranked.sort(key=lambda item: (-item[0], -item[1], item[2]))

    # Return one record per provider, preserving the strongest catalog match.
    selected: list[Any] = []
    seen: set[str] = set()
    for _, _, _, entity in ranked:
        provider = normalize_text(entity_university(entity) or entity_label(entity))
        if not provider or provider in seen:
            continue
        seen.add(provider)
        selected.append(entity)
        if len(selected) == limit:
            break
    return selected


def _recommendation_label(entity: Any, category: str | None) -> str:
    university = entity_university(entity)
    specialization = clean_text(first_value(entity, "specialization_name", "spec_name", default=""))
    program = clean_text(safe_get(entity, "program_name", None))
    course = program or (str(category or "").upper() if category else "Program")
    parts = [university, course]
    if specialization and normalize_text(specialization) not in normalize_text(course):
        parts.append(specialization)
    return " — ".join(value for value in parts if value) or entity_label(entity)


def _reasons(entity: Any, advisor: Any) -> list[str]:
    reasons: list[str] = []
    specialization = clean_text(first_value(entity, "specialization_name", "spec_name", default=""))
    if specialization:
        reasons.append(f"Published specialization: {specialization}.")
    amount, fee = _published_total_fee(entity)
    if fee:
        if advisor.budget is not None and amount is not None:
            reasons.append(
                f"Published total fee {fee}, within your {format_inr(advisor.budget)} budget."
            )
        else:
            reasons.append(f"Published total fee: {fee}.")
    jobs = [
        clean_text(safe_get(item, "job_title", None))
        for item in (safe_get(entity, "job_profiles", []) or [])
    ]
    jobs = [item for item in jobs if item]
    if jobs:
        reasons.append(f"Published career roles include {', '.join(jobs[:2])}.")
    elif safe_get(entity, "career_outcomes", None):
        outcomes = [clean_text(value) for value in safe_get(entity, "career_outcomes", [])]
        outcomes = [value for value in outcomes if value]
        if outcomes:
            reasons.append(f"Published career outcomes include {', '.join(outcomes[:2])}.")
    placement = clean_text(safe_get(entity, "placement_content", None), max_chars=150)
    if placement:
        reasons.append(f"Published placement support: {placement}")
    eligibility = clean_text(
        first_value(entity, "eligibility_summary", "eligibility_content", default=""),
        max_chars=150,
    )
    if eligibility and len(reasons) < 3:
        reasons.append(f"Published eligibility: {eligibility}.")
    approval = clean_text(first_value(entity, "ugc_status", "ugc_approved", default=""))
    grade = clean_text(safe_get(entity, "naac_grade", None))
    if (approval or grade) and len(reasons) < 3:
        details = ", ".join(
            value for value in (approval, f"NAAC {grade}" if grade else "") if value
        )
        reasons.append(f"Published recognition: {details}.")
    return reasons[:3] or ["This is a published catalog option matching the selected course."]


def _recommendation_response(advisor: Any, catalog: Any) -> ResponsePayload:
    recommendations = _ranked_recommendations(advisor, catalog)
    if not recommendations:
        advisor.active = False
        advisor.last_asked_field = None
        return build_response(
            "## Recommended programs\n\n"
            "I couldn't verify a catalog option against all of those preferences. "
            "Try a higher budget or say “restart advisor” to change the profile.",
            suggested_chips=["Restart advisor", "Browse programs"],
        )

    sections = ["## Recommended programs"]
    quick_actions: list[str] = []
    for index, entity in enumerate(recommendations, start=1):
        label = _recommendation_label(entity, advisor.category)
        sections.extend(
            (
                f"### {index}. {label}",
                "**Why it matches**",
                *[f"• {reason}" for reason in _reasons(entity, advisor)],
            )
        )
        university = entity_university(entity)
        if university:
            quick_actions.append(f"{university} fees")
    if len(recommendations) >= 2:
        providers = [entity_university(entity) for entity in recommendations[:2]]
        if all(providers):
            quick_actions.append(f"Compare {providers[0]} and {providers[1]}")
    advisor.active = False
    advisor.last_asked_field = None
    return build_response("\n\n".join(sections), suggested_chips=quick_actions)


def _capture_initial_values(advisor: Any, message: str, mentions: Any) -> None:
    # Only explicit, self-describing phrases are accepted on the trigger turn.
    education = None
    if re.search(r"\b(?:education|completed|degree|graduate|graduation)\b", message, re.I):
        education = _extract_expected("current_education", message, mentions)
    experience = _EXPERIENCE_RE.search(message)
    goal = None
    if _GOAL_PREFIX_RE.search(message):
        goal = _extract_expected("career_goal", message, mentions)
    budget = parse_budget(message)
    specialization = _specialization_from_mentions(mentions)
    if education:
        advisor.current_education = education
    if experience:
        advisor.work_experience = _clean_reply(experience.group(0))
    if goal:
        advisor.career_goal = goal
    if budget is not None:
        advisor.budget = budget
    if specialization:
        advisor.preferred_specialization = specialization


def handle_advisor_turn(
    state: Any,
    message: str,
    catalog: Any,
    *,
    mentions: Any = None,
    category: str | None = None,
    start: bool = False,
) -> ResponsePayload:
    """Start or advance the advisor, asking exactly the next missing field."""

    advisor = state.advisor
    if _CANCEL_RE.fullmatch(message):
        advisor.clear()
        return build_response(
            "Advisor mode cancelled. You can continue browsing the catalog.",
            suggested_chips=["Browse programs", "Compare universities"],
        )
    if _RESTART_RE.fullmatch(message):
        remembered_category = category or advisor.category
        advisor.clear()
        advisor.active = True
        advisor.category = remembered_category
        return _question(advisor, catalog)

    if start and not advisor.active:
        # Re-enter a suspended advisor with the profile already collected. This
        # keeps the flow genuinely stateful and ensures we ask only for fields
        # that are still missing after an informational detour.
        advisor.active = True
        if category:
            advisor.category = category
        _capture_initial_values(advisor, message, mentions)
    elif category and not advisor.category:
        advisor.category = category

    expected = advisor.last_asked_field
    if advisor.active and expected:
        value = _extract_expected(expected, message, mentions)
        if value is not None:
            setattr(advisor, expected, value)
            advisor.last_asked_field = None

    missing = _next_missing(advisor)
    if missing is not None:
        return _question(advisor, catalog)
    return _recommendation_response(advisor, catalog)


__all__ = [
    "advisor_can_consume",
    "handle_advisor_turn",
    "is_personal_advisor_request",
    "parse_budget",
]
