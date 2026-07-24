"""Catalog-only projections for the guided-navigation prototype.

The helpers in this module intentionally stop at the presentation boundary.  They
read the already-loaded :class:`~data.loader.CatalogStore`, build the same cards
used by chat responses, and never invoke NLU, resolution, routing, or an LLM.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from contextlib import suppress
from typing import Any

from data.accessor import safe_get
from response.cards import (
    catalog_get_entity,
    clean_text,
    entity_page_type,
    first_value,
    iter_catalog_entities,
)
from response.catalog_facts import accreditation_items

from .cards import build_comparison_card, build_entity_card

_PAGE_TYPES = {"homepage", "pillar", "university", "course", "specialization"}
_PROGRAM_NAMES = {
    "mba": "MBA",
    "mca": "MCA",
    "bba": "BBA",
    "bca": "BCA",
    "bcom": "BCom",
    "mcom": "MCom",
    "msc": "MSc",
}
_PROGRAM_ORDER = {"mba": 0, "mca": 1, "bba": 2, "msc": 3}


def _normalise(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", clean_text(value).casefold()).strip()


def _distinct(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        rendered = clean_text(value)
        key = rendered.casefold()
        if not rendered or key in seen:
            continue
        seen.add(key)
        result.append(rendered)
    return result


def _entity_id(entity: Any) -> str:
    return clean_text(safe_get(entity, "id", None))


def _university_name(entity: Any) -> str:
    return clean_text(
        first_value(entity, "university_name", "university_full_name", default=None)
    )


def _course_name(entity: Any) -> str:
    return clean_text(first_value(entity, "program_name", "category", default=None))


def _specialization_name(entity: Any) -> str:
    return clean_text(
        first_value(entity, "specialization_name", "spec_name", default=None)
    )


def _entity_terms(entity: Any, catalog: Any) -> set[str]:
    values: list[Any] = [
        safe_get(entity, "id", None),
        safe_get(entity, "slug", None),
        _university_name(entity),
        safe_get(entity, "university_full_name", None),
        _course_name(entity),
        safe_get(entity, "category", None),
        _specialization_name(entity),
    ]
    values.extend(safe_get(entity, "aliases", None) or [])
    metadata_getter = getattr(catalog, "get_metadata", None)
    metadata = metadata_getter(_entity_id(entity)) if callable(metadata_getter) else None
    if metadata is not None:
        values.extend(
            (
                getattr(metadata, "canonical_name", None),
                getattr(metadata, "university_name", None),
                getattr(metadata, "program_name", None),
                getattr(metadata, "spec_name", None),
                getattr(metadata, "category", None),
                getattr(metadata, "specialization_name", None),
            )
        )
        values.extend(getattr(metadata, "aliases", ()) or ())

    terms: set[str] = set()
    for value in values:
        term = _normalise(value)
        if not term:
            continue
        terms.add(term)
        terms.add(term.replace(" ", ""))
        if term.startswith("online "):
            shorter = term.removeprefix("online ").strip()
            terms.add(shorter)
            terms.add(shorter.replace(" ", ""))
        if term.endswith(" online"):
            shorter = term.removesuffix(" online").strip()
            terms.add(shorter)
            terms.add(shorter.replace(" ", ""))
    return terms


def _matches(entity: Any, value: str | None, catalog: Any) -> bool:
    if not value:
        return True
    term = _normalise(value)
    return term in _entity_terms(entity, catalog) or term.replace(" ", "") in _entity_terms(
        entity, catalog
    )


def _entities(catalog: Any, page_type: str | None = None) -> list[Any]:
    entities = iter_catalog_entities(catalog)
    if page_type:
        entities = [entity for entity in entities if entity_page_type(entity) == page_type]
    return sorted(entities, key=lambda entity: (_entity_id(entity).casefold(),))


def _linked(entity: Any, path: str, catalog: Any) -> Any:
    reference = safe_get(entity, path, None)
    if isinstance(reference, Mapping):
        if entity_page_type(reference):
            return reference
        reference = first_value(reference, "id", "entity_id", "slug", default=None)
    return catalog_get_entity(catalog, reference) if reference is not None else None


def _same_university(entity: Any, university: Any, catalog: Any) -> bool:
    linked = _linked(entity, "linked_university", catalog)
    if linked is not None and _entity_id(linked) == _entity_id(university):
        return True
    candidate = _normalise(_university_name(entity))
    return bool(candidate) and candidate in {
        _normalise(_university_name(university)),
        _normalise(safe_get(university, "university_full_name", None)),
    }


def _same_category(entity: Any, course: Any) -> bool:
    entity_program = _normalise(
        first_value(entity, "program_name", "parent_course", default=None)
    )
    course_program = _normalise(safe_get(course, "program_name", None))
    return bool(entity_program and entity_program == course_program)


def _same_course(entity: Any, course: Any, catalog: Any) -> bool:
    linked_reference = clean_text(safe_get(entity, "linked_course", None))
    if linked_reference:
        return _entity_id(_linked(entity, "linked_course", catalog)) == _entity_id(course)
    return _same_category(entity, course)


def _resolve_university(catalog: Any, value: str | None) -> Any:
    if not value:
        return None
    return next(
        (entity for entity in _entities(catalog, "university") if _matches(entity, value, catalog)),
        None,
    )


def _resolve_course(catalog: Any, value: str | None, university: Any = None) -> Any:
    if not value:
        return None
    return next(
        (
            entity
            for entity in _entities(catalog, "course")
            if _matches(entity, value, catalog)
            and (university is None or _same_university(entity, university, catalog))
        ),
        None,
    )


def _resolve_specialization(
    catalog: Any,
    value: str | None,
    *,
    university: Any = None,
    course: Any = None,
) -> Any:
    if not value:
        return None
    return next(
        (
            entity
            for entity in _entities(catalog, "specialization")
            if _matches(entity, value, catalog)
            and (university is None or _same_university(entity, university, catalog))
            and (course is None or _same_course(entity, course, catalog))
        ),
        None,
    )


def _parent_university(entity: Any, catalog: Any) -> Any:
    if entity_page_type(entity) == "university":
        return entity
    linked = _linked(entity, "linked_university", catalog)
    if linked is not None:
        return linked
    name = _university_name(entity)
    return _resolve_university(catalog, name)


def _parent_course(entity: Any, catalog: Any) -> Any:
    if entity_page_type(entity) == "course":
        return entity
    if entity_page_type(entity) != "specialization":
        return None
    linked = _linked(entity, "linked_course", catalog)
    if linked is not None:
        return linked
    return _resolve_course(
        catalog,
        clean_text(first_value(entity, "program_name", "parent_course", default=None)),
        _parent_university(entity, catalog),
    )


def _resolve_context_entity(
    catalog: Any,
    *,
    page_type: str,
    university: str | None,
    course: str | None,
    specialization: str | None,
    entity_id: str | None,
) -> Any:
    if entity_id:
        entity = catalog_get_entity(catalog, entity_id)
        if entity is None:
            return None
        return entity
    if page_type in {"homepage", "pillar"}:
        return None
    university_entity = _resolve_university(catalog, university)
    if university and university_entity is None:
        return None
    if page_type == "university":
        return university_entity
    course_entity = _resolve_course(catalog, course, university_entity)
    if course and course_entity is None:
        return None
    if page_type == "course":
        return course_entity
    return _resolve_specialization(
        catalog,
        specialization,
        university=university_entity,
        course=course_entity,
    )


def _card(entity: Any, catalog: Any) -> dict[str, Any]:
    return build_entity_card(entity, catalog).model_dump(mode="json")


def _entity_sort_name(entity: Any) -> str:
    page_type = entity_page_type(entity)
    if page_type == "university":
        return _university_name(entity)
    if page_type == "specialization":
        return _specialization_name(entity)
    return _course_name(entity)


def _card_list(entities: Iterable[Any], catalog: Any, *, limit: int = 8) -> list[dict[str, Any]]:
    ordered = sorted(
        entities,
        key=lambda entity: (_entity_sort_name(entity).casefold(), _entity_id(entity).casefold()),
    )[:limit]
    return [_card(entity, catalog) for entity in ordered]


def _courses_for_university(catalog: Any, university: Any) -> list[Any]:
    return [
        entity
        for entity in _entities(catalog, "course")
        if _same_university(entity, university, catalog)
    ]


def _specializations_for_course(catalog: Any, course: Any) -> list[Any]:
    result: list[Any] = []
    for entity in _entities(catalog, "specialization"):
        linked_reference = clean_text(safe_get(entity, "linked_course", None))
        if linked_reference:
            if _entity_id(_linked(entity, "linked_course", catalog)) == _entity_id(course):
                result.append(entity)
            continue
        if _same_category(entity, course) and _same_university(
            entity, _parent_university(course, catalog), catalog
        ):
            result.append(entity)
    return result


def _relation_chain(entity: Any, catalog: Any) -> list[Any]:
    values = [entity, _parent_course(entity, catalog), _parent_university(entity, catalog)]
    result: list[Any] = []
    seen: set[str] = set()
    for value in values:
        if value is None:
            continue
        key = _entity_id(value) or str(id(value))
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _first_text(sources: Iterable[Any], *paths: str) -> str | None:
    for source in sources:
        rendered = clean_text(first_value(source, *paths, default=None))
        if rendered:
            return rendered
    return None


def _fee_info(entity: Any, catalog: Any) -> dict[str, Any]:
    sources = _relation_chain(entity, catalog)
    plans: list[dict[str, str | None]] = []
    primary = sources[0] if sources else None
    primary_has_own_fee = bool(
        primary is not None
        and (
            _first_text((primary,), "total_fee", "starting_fee")
            or any(
                isinstance(safe_get(primary, path, None), (int, float))
                and not isinstance(safe_get(primary, path, None), bool)
                for path in ("total_fee_numeric", "starting_fee_numeric", "fee_numeric")
            )
        )
    )
    plan_sources = sources[:1] if primary_has_own_fee else sources
    for source in plan_sources:
        rows = safe_get(source, "fee_plans", None) or []
        if not isinstance(rows, Iterable) or isinstance(rows, (str, bytes, Mapping)):
            continue
        for row in rows:
            plan = {
                "name": _first_text((row,), "plan_name", "name"),
                "amount": _first_text((row,), "plan_amount", "amount"),
                "total": _first_text((row,), "plan_total", "total"),
                "note": _first_text((row,), "plan_note", "note"),
            }
            if any(plan.values()):
                plans.append(plan)
        if plans:
            break

    total_fee = _first_text(sources, "total_fee")
    if total_fee is None:
        total_fee = next((str(plan["total"]) for plan in plans if plan["total"]), None)
    semester_fee = _first_text(sources, "starting_fee")
    if semester_fee is None:
        semester_fee = next(
            (
                str(plan["amount"])
                for plan in plans
                if plan["amount"] and "semester" in str(plan["name"] or "").casefold()
            ),
            None,
        )
    emi = _first_text(sources, "emi_amount", "emi_content")
    numeric = next(
        (
            value
            for source in sources
            for path in ("total_fee_numeric", "starting_fee_numeric", "fee_numeric")
            if isinstance((value := safe_get(source, path, None)), (int, float))
            and not isinstance(value, bool)
        ),
        None,
    )
    metadata = next(
        (
            dict(value)
            for source in sources
            if isinstance((value := safe_get(source, "fee_metadata", None)), Mapping)
        ),
        None,
    )
    return {
        "available": bool(total_fee or semester_fee or emi or plans),
        "total_fee": total_fee,
        "semester_fee": semester_fee,
        "emi": emi,
        "plans": plans,
        "fee_numeric": numeric,
        "fee_metadata": metadata,
    }


def _string_values(value: Any, *paths: str) -> list[str]:
    if value is None:
        return []
    values = value if isinstance(value, (list, tuple, set)) else [value]
    result: list[str] = []
    for item in values:
        if isinstance(item, (str, int, float)):
            rendered = clean_text(item)
        else:
            rendered = clean_text(first_value(item, *paths, default=None))
        if rendered:
            result.append(rendered)
    return _distinct(result)


def _eligibility_info(entity: Any, catalog: Any) -> dict[str, Any]:
    sources = _relation_chain(entity, catalog)
    summary = _first_text(sources, "eligibility_summary", "eligibility_content")
    requirements: list[str] = []
    for source in sources:
        for path in ("eligibility_requirements", "requirements", "qualification_checklist"):
            requirements.extend(
                _string_values(
                    safe_get(source, path, None),
                    "requirement",
                    "qualification",
                    "label",
                    "text",
                    "name",
                )
            )
        if requirements:
            break
    requirements = _distinct(requirements)
    return {
        "available": bool(summary or requirements),
        "summary": summary,
        "requirements": requirements,
    }


def _career_info(entity: Any) -> dict[str, Any]:
    profiles = safe_get(entity, "job_profiles", None) or []
    roles: list[str] = []
    salaries: list[str] = []
    if isinstance(profiles, Iterable) and not isinstance(profiles, (str, bytes, Mapping)):
        for profile in profiles:
            role = clean_text(first_value(profile, "job_title", "role", "name", default=None))
            salary = clean_text(first_value(profile, "avg_salary", "salary", default=None))
            if role:
                roles.append(role)
            if salary:
                salaries.append(salary)
    roles.extend(
        _string_values(
            safe_get(entity, "career_outcomes", None),
            "job_title",
            "role",
            "name",
            "title",
        )
    )
    for outcome in safe_get(entity, "salary_outcomes", None) or []:
        role = clean_text(safe_get(outcome, "job_title", None))
        salary = clean_text(safe_get(outcome, "salary_display", None))
        if role:
            roles.append(role)
        if salary:
            salaries.append(salary)
    recruiters: list[str] = []
    for path in ("recruiters", "top_recruiters", "hiring_partners"):
        recruiters.extend(
            _string_values(safe_get(entity, path, None), "name", "company", "title")
        )
    average_salary = salaries[0] if salaries else clean_text(
        first_value(entity, "average_salary", "avg_salary", default=None)
    ) or None
    roles = _distinct(roles)
    recruiters = _distinct(recruiters)
    return {
        "available": bool(average_salary or roles or recruiters),
        "average_salary": average_salary,
        "job_roles": roles,
        "recruiters": recruiters,
    }


def _syllabus_sections(entity: Any) -> list[dict[str, Any]]:
    value = first_value(entity, "syllabus", "semesters", "syllabus_semesters", default=None)
    sections: list[dict[str, Any]] = []
    if isinstance(value, Mapping):
        for title, subjects in value.items():
            items = _string_values(subjects, "subject", "name", "title")
            if items:
                sections.append({"title": clean_text(title), "items": items})
    elif isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
        for index, semester in enumerate(value, start=1):
            title = clean_text(
                first_value(
                    semester,
                    "semester_name",
                    "semester",
                    "title",
                    "name",
                    default=f"Semester {index}",
                )
            )
            items: list[str] = []
            for path in ("subjects", "courses", "modules", "items"):
                items.extend(
                    _string_values(
                        safe_get(semester, path, None), "subject", "name", "title", "module"
                    )
                )
            if items:
                sections.append({"title": title, "items": _distinct(items)})
    content = clean_text(safe_get(entity, "syllabus_content", None), max_chars=2400)
    if not sections and content:
        sections.append({"title": "Published syllabus", "items": [content]})
    return sections


def _syllabus_info(entity: Any) -> dict[str, Any]:
    semesters = _syllabus_sections(entity)
    return {"available": bool(semesters), "semesters": semesters}


def _review_info(entity: Any, catalog: Any) -> dict[str, Any]:
    review_sources: list[tuple[Any, str | None]] = [(entity, None)]
    scope_label: str | None = None
    direct_reviews = safe_get(entity, "reviews", None) or []
    if entity_page_type(entity) == "university" and not direct_reviews:
        linked_courses = [
            course
            for course in _courses_for_university(catalog, entity)
            if safe_get(course, "reviews", None)
        ]
        if linked_courses:
            review_sources = [(course, _course_name(course)) for course in linked_courses]
            scope_label = (
                f"Published reviews across {len(linked_courses)} "
                f"{_university_name(entity)} programs"
            )

    rating = clean_text(
        first_value(entity, "rating", "average_rating", "overall_rating", default=None)
    ) or None
    breakdown: list[dict[str, str]] = []
    value = first_value(entity, "rating_breakdown", "reviews_breakdown", default=None)
    if isinstance(value, Mapping):
        breakdown = [
            {"label": clean_text(label), "value": clean_text(score)}
            for label, score in value.items()
            if clean_text(label) and clean_text(score)
        ]
    elif isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
        for item in value:
            label = clean_text(first_value(item, "label", "name", "stars", default=None))
            score = clean_text(first_value(item, "value", "count", "percentage", default=None))
            if label and score:
                breakdown.append({"label": label, "value": score})

    testimonials: list[dict[str, str | None]] = []
    ratings: list[float] = []
    theme_counts: dict[str, int] = {}
    published_review_count = 0
    for source, source_label in review_sources:
        reviews = safe_get(source, "reviews", None) or []
        if not isinstance(reviews, Iterable) or isinstance(reviews, (str, bytes, Mapping)):
            continue
        for review in reviews:
            text = clean_text(first_value(review, "review_text", "text", default=None))
            if not text:
                continue
            published_review_count += 1
            review_rating = safe_get(review, "rating", None)
            with suppress(TypeError, ValueError):
                ratings.append(float(review_rating))
            theme = clean_text(safe_get(review, "theme", None)) or None
            if theme:
                normalized_theme = theme.title()
                theme_counts[normalized_theme] = theme_counts.get(normalized_theme, 0) + 1
            testimonials.append(
                {
                    "text": text,
                    "reviewer_name": clean_text(safe_get(review, "reviewer_name", None))
                    or None,
                    "reviewer_label": (
                        clean_text(safe_get(review, "reviewer_label", None))
                        or source_label
                    ),
                    "rating": review_rating,
                    "theme": theme,
                }
            )

    if scope_label and ratings:
        rating = clean_text(round(sum(ratings) / len(ratings), 2)) or None
    if not breakdown and testimonials:
        total = sum(theme_counts.values())
        breakdown = [
            {"label": theme, "value": f"{round(count / total * 100)}%"}
            for theme, count in sorted(theme_counts.items())
        ] if total else []
    result = {
        "available": bool(rating or breakdown or testimonials),
        "rating": rating,
        "breakdown": breakdown,
        "testimonials": testimonials,
        "review_count": (
            published_review_count
            if scope_label
            else safe_get(entity, "review_count", None)
        ),
    }
    if scope_label:
        result["scope_label"] = scope_label
    return result


def _accreditation_info(entity: Any, catalog: Any) -> dict[str, Any]:
    values: list[str] = []
    for source in _relation_chain(entity, catalog):
        values.extend(accreditation_items(source))
    items = _distinct(values)
    return {"available": bool(items), "items": items}


def _admission_info(entity: Any, catalog: Any) -> dict[str, Any]:
    sources = _relation_chain(entity, catalog)
    steps: list[str] = []
    for source in sources:
        steps = _string_values(
            safe_get(source, "admission_steps", None),
            "step",
            "label",
            "title",
            "text",
        )
        if steps:
            break
    fee_note = _first_text(sources, "admission_fee_note")
    return {
        "available": bool(steps or fee_note),
        "steps": steps,
        "fee_note": fee_note,
    }


def _placement_info(entity: Any, catalog: Any) -> dict[str, Any]:
    sources = _relation_chain(entity, catalog)
    supported = any(safe_get(source, "placement_support", None) is True for source in sources)
    industry_projects = any(
        safe_get(source, "industry_projects", None) is True for source in sources
    )
    content = _first_text(sources, "placement_content")
    return {
        "available": bool(supported or industry_projects or content),
        "supported": supported,
        "industry_projects": industry_projects,
        "content": content,
    }


def _overview_info(entity: Any) -> dict[str, Any]:
    why_choose = clean_text(safe_get(entity, "why_choose_content", None)) or None
    description = clean_text(
        first_value(entity, "hero_description", "about_content", default=None)
    ) or None
    return {
        "available": bool(why_choose or description),
        "why_choose": why_choose,
        "description": description,
    }


def _validity_info(entity: Any, catalog: Any) -> dict[str, Any]:
    candidates = [entity] if entity is not None else _entities(catalog)
    values = _distinct(
        clean_text(safe_get(candidate, "validity", None))
        for candidate in candidates
        if candidate is not None
    )
    return {
        "available": bool(values),
        "content": values[0] if values else None,
    }


def _info(entity: Any, catalog: Any) -> dict[str, Any]:
    return {
        "fees": _fee_info(entity, catalog),
        "eligibility": _eligibility_info(entity, catalog),
        "career": _career_info(entity),
        "syllabus": _syllabus_info(entity),
        "reviews": _review_info(entity, catalog),
        "accreditations": _accreditation_info(entity, catalog),
        "admissions": _admission_info(entity, catalog),
        "placement": _placement_info(entity, catalog),
        "overview": _overview_info(entity),
        "validity": _validity_info(entity, catalog),
    }


def _related(entity: Any, catalog: Any) -> dict[str, list[dict[str, Any]]]:
    page_type = entity_page_type(entity)
    university = _parent_university(entity, catalog)
    course = _parent_course(entity, catalog)
    universities: list[Any] = []
    courses: list[Any] = []
    specializations: list[Any] = []
    alternatives: list[Any] = []

    if page_type == "university":
        courses = _courses_for_university(catalog, entity)
        alternatives = [
            candidate
            for candidate in _entities(catalog, "university")
            if _entity_id(candidate) != _entity_id(entity)
        ]
    elif page_type == "course":
        universities = [university] if university is not None else []
        specializations = _specializations_for_course(catalog, entity)
        alternatives = [
            candidate
            for candidate in _entities(catalog, "course")
            if _entity_id(candidate) != _entity_id(entity) and _same_category(candidate, entity)
        ]
    elif page_type == "specialization":
        universities = [university] if university is not None else []
        courses = [course] if course is not None else []
        if course is not None:
            specializations = [
                candidate
                for candidate in _specializations_for_course(catalog, course)
                if _entity_id(candidate) != _entity_id(entity)
            ]
        name = _normalise(_specialization_name(entity))
        alternatives = [
            candidate
            for candidate in _entities(catalog, "specialization")
            if _entity_id(candidate) != _entity_id(entity)
            and _normalise(_specialization_name(candidate)) == name
        ]

    return {
        "universities": _card_list(universities, catalog),
        "courses": _card_list(courses, catalog),
        "specializations": _card_list(specializations, catalog),
        "alternatives": _card_list(alternatives, catalog),
    }


def guide_context(
    catalog: Any,
    *,
    page_type: str = "homepage",
    university: str | None = None,
    course: str | None = None,
    specialization: str | None = None,
    entity_id: str | None = None,
) -> dict[str, Any] | None:
    """Build one grounded guided-navigation state, or ``None`` when unresolved."""

    normalized_page_type = clean_text(page_type).casefold() or "homepage"
    if normalized_page_type in {"discipline", "discipline_hub", "pillar_page"}:
        normalized_page_type = "pillar"
    if normalized_page_type not in _PAGE_TYPES:
        raise ValueError("Invalid page_type")
    entity = _resolve_context_entity(
        catalog,
        page_type=normalized_page_type,
        university=university,
        course=course,
        specialization=specialization,
        entity_id=entity_id,
    )
    if entity is None and normalized_page_type not in {"homepage", "pillar"}:
        return None
    if entity is not None:
        normalized_page_type = entity_page_type(entity)

    if entity is None:
        pillar_course = clean_text(course) if normalized_page_type == "pillar" else None
        context = {
            "page_type": normalized_page_type,
            "university": None,
            "course": pillar_course or None,
            "specialization": None,
            "entity_id": None,
            "label": pillar_course or None,
        }
        return {
            "context": context,
            "entity": None,
            "related": {
                "universities": [],
                "courses": [],
                "specializations": [],
                "alternatives": [],
            },
            "info": {
                "fees": {
                    "available": False,
                    "total_fee": None,
                    "semester_fee": None,
                    "emi": None,
                    "plans": [],
                },
                "eligibility": {"available": False, "summary": None, "requirements": []},
                "career": {
                    "available": False,
                    "average_salary": None,
                    "job_roles": [],
                    "recruiters": [],
                },
                "syllabus": {"available": False, "semesters": []},
                "reviews": {
                    "available": False,
                    "rating": None,
                    "breakdown": [],
                    "testimonials": [],
                },
                "accreditations": {"available": False, "items": []},
                "admissions": {"available": False, "steps": None, "fee_note": None},
                "placement": {
                    "available": False,
                    "supported": False,
                    "industry_projects": False,
                    "content": None,
                },
                "overview": {
                    "available": False,
                    "why_choose": None,
                    "description": None,
                },
                "validity": _validity_info(None, catalog),
            },
        }

    university_entity = _parent_university(entity, catalog)
    course_entity = _parent_course(entity, catalog)
    university_label = _university_name(university_entity) if university_entity else None
    course_label = _course_name(course_entity) if course_entity else None
    specialization_label = (
        _specialization_name(entity) if normalized_page_type == "specialization" else None
    )
    context = {
        "page_type": normalized_page_type,
        "university": university_label,
        "course": course_label,
        "specialization": specialization_label,
        "entity_id": _entity_id(entity) or None,
        "label": " • ".join(
            value for value in (university_label, course_label, specialization_label) if value
        ),
    }
    return {
        "context": context,
        "entity": _card(entity, catalog),
        "related": _related(entity, catalog),
        "info": _info(entity, catalog),
    }


def guide_catalog(
    catalog: Any,
    kind: str,
    *,
    query: str | None = None,
    university: str | None = None,
    course: str | None = None,
) -> list[dict[str, Any]]:
    """Return deterministic picker options projected from the in-memory catalog."""

    normalized_kind = clean_text(kind).casefold()
    term = _normalise(query)
    if normalized_kind == "universities":
        matching_provider_ids: set[str] | None = None
        if course:
            matching_provider_ids = {
                _entity_id(provider)
                for candidate in _entities(catalog, "course")
                if _matches(candidate, course, catalog)
                and (provider := _parent_university(candidate, catalog)) is not None
            }
        entities = [
            entity
            for entity in _entities(catalog, "university")
            if (
                matching_provider_ids is None
                or _entity_id(entity) in matching_provider_ids
            )
            and (not term or any(term in value for value in _entity_terms(entity, catalog)))
        ]
        return _card_list(entities, catalog, limit=100)

    if normalized_kind == "programs":
        providers: dict[str, set[str]] = {}
        program_labels: dict[str, str] = {}
        for entity in _entities(catalog, "course"):
            category = _normalise(
                first_value(entity, "program_name", "category", default=None)
            )
            if category:
                program_labels.setdefault(category, _course_name(entity))
                university_entity = _parent_university(entity, catalog)
                provider_key = _entity_id(university_entity) or _normalise(_university_name(entity))
                if provider_key:
                    providers.setdefault(category, set()).add(provider_key)
        items = [
            {
                "type": "program_option",
                "id": category,
                "slug": category,
                "page_type": "course",
                "name": program_labels.get(category) or _PROGRAM_NAMES.get(
                    category, category.upper()
                ),
                "provider_count": len(provider_ids),
            }
            for category, provider_ids in providers.items()
            if not term
            or term in category
            or term in _normalise(_PROGRAM_NAMES.get(category, category.upper()))
        ]
        items.sort(
            key=lambda item: (
                _PROGRAM_ORDER.get(str(item["id"]), 100),
                str(item["name"]).casefold(),
            )
        )
        return items

    if normalized_kind == "courses":
        university_entity = _resolve_university(catalog, university) if university else None
        if university and university_entity is None:
            return []
        entities = [
            entity
            for entity in _entities(catalog, "course")
            if (university_entity is None or _same_university(entity, university_entity, catalog))
            and (not course or _matches(entity, course, catalog))
            and (not term or any(term in value for value in _entity_terms(entity, catalog)))
        ]
        return _card_list(entities, catalog, limit=24)

    if normalized_kind != "specializations":
        raise ValueError("Unknown guided catalog kind")

    university_entity = _resolve_university(catalog, university) if university else None
    if university and university_entity is None:
        return []
    course_entity = _resolve_course(catalog, course, university_entity) if course else None
    if course and course_entity is None:
        return []
    entities = [
        entity
        for entity in _entities(catalog, "specialization")
        if (university_entity is None or _same_university(entity, university_entity, catalog))
        and (course_entity is None or _same_course(entity, course_entity, catalog))
        and (not term or any(term in value for value in _entity_terms(entity, catalog)))
    ]
    return _card_list(entities, catalog, limit=250)



_NAAC_RANK = {"a++": 0, "a+": 1, "a": 2, "b++": 3, "b+": 4, "b": 5}


def _naac_rank(entity: Any) -> int:
    grade = str(safe_get(entity, "naac_grade", "") or "").strip().casefold()
    return _NAAC_RANK.get(grade, 99)


def _fee_key(entity: Any) -> float:
    for path in ("total_fee_numeric", "fee_numeric", "starting_fee_numeric"):
        value = safe_get(entity, path, None)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return float("inf")


def _program_term(entity: Any) -> str:
    return _normalise(first_value(entity, "program_name", "category", default=None))


def _specialization_term(entity: Any) -> str:
    return _normalise(first_value(entity, "specialization_name", "spec_name", default=None))


def resolve_opponents(catalog: Any, entity_id: str) -> dict[str, Any] | None:
    """Delta §1.2 — valid comparison opponents for one entity, or None if unknown.

    Validity (§1.1) is enforced at generation time: only same-type, same-term
    partners that pass the per-type constraint are ever returned, so an invalid
    pair cannot be selected.
    """

    active = catalog.get_entity(entity_id) if hasattr(catalog, "get_entity") else None
    if active is None:
        active = getattr(catalog, "entities", {}).get(entity_id)
    if active is None:
        return None
    page_type = entity_page_type(active)
    active_id = _entity_id(active)

    if page_type == "university":
        opponents = [
            e for e in _entities(catalog, "university") if _entity_id(e) != active_id
        ]
        opponents.sort(key=lambda e: (_naac_rank(e), _entity_sort_name(e).casefold()))
    elif page_type == "course":
        term = _program_term(active)
        active_uni = _entity_id(_parent_university(active, catalog))
        opponents = [
            e
            for e in _entities(catalog, "course")
            if _entity_id(e) != active_id
            and term
            and _program_term(e) == term
            and _entity_id(_parent_university(e, catalog)) != active_uni
        ]
        opponents.sort(key=lambda e: (_fee_key(e), _entity_sort_name(e).casefold()))
    elif page_type == "specialization":
        term = _specialization_term(active)
        active_course = _entity_id(_parent_course(active, catalog))
        opponents = [
            e
            for e in _entities(catalog, "specialization")
            if _entity_id(e) != active_id
            and term
            and _specialization_term(e) == term
            and _entity_id(_parent_course(e, catalog)) != active_course
        ]
        opponents.sort(key=lambda e: (_fee_key(e), _entity_sort_name(e).casefold()))
    else:
        return None

    return {
        "active": {"type": page_type, "id": active_id},
        "items": [_card(e, catalog) for e in opponents[:100]],
    }


def guide_comparison(catalog: Any, entity_ids: Iterable[str]) -> dict[str, Any] | None:
    card = build_comparison_card(entity_ids, catalog, title="Compare catalog options")
    return card.model_dump(mode="json") if card is not None else None


__all__ = ["guide_catalog", "guide_comparison", "guide_context", "resolve_opponents"]
