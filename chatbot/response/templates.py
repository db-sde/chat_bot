"""Zero-LLM response templates for catalog-backed questions."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any

from data.accessor import safe_get

from .cards import (
    catalog_get_entity,
    clean_text,
    entity_fee,
    entity_heading,
    entity_label,
    entity_page_type,
    entity_university,
    first_value,
    has_value,
    related_specialization_names,
    render_sections,
)


def unavailable_answer(entity: Any, topic: str) -> str:
    subject = entity_label(entity)
    return (
        f"I don't have published {topic} information for {subject} yet. "
        "Would you like to check another detail or speak with a counsellor?"
    )


def entity_not_found_answer(name: str, suggestion: str | None = None) -> str:
    """Response when entity_matcher returned no match — the name is unresolved."""

    base = f'I couldn\'t find a match for "{name}" in the published catalog.'
    if suggestion:
        base += f" Did you mean {suggestion}?"
    else:
        base += " Could you check the spelling, or try a different university or course name?"
    return base


def fee_answer(entity: Any) -> str:
    subject = entity_label(entity)
    total = clean_text(safe_get(entity, "total_fee", None))
    starting = clean_text(safe_get(entity, "starting_fee", None))

    if total and starting and total.casefold() != starting.casefold():
        return (
            f"The published total fee for {subject} is {total}; "
            f"the listed starting fee is {starting}."
        )
    if total:
        return f"The published total fee for {subject} is {total}."
    if starting:
        return f"The published starting fee for {subject} is {starting}."

    plans = safe_get(entity, "fee_plans", []) or []
    for plan in plans if isinstance(plans, (list, tuple)) else []:
        name = clean_text(safe_get(plan, "plan_name", None))
        amount = clean_text(first_value(plan, "plan_total", "plan_amount", default=None))
        if amount:
            qualifier = f" under the {name} plan" if name else ""
            return f"The published fee for {subject}{qualifier} is {amount}."
    return unavailable_answer(entity, "fee")


def duration_answer(entity: Any) -> str:
    subject = entity_label(entity)
    duration = clean_text(safe_get(entity, "duration", None))
    if not duration:
        return unavailable_answer(entity, "duration")
    return f"The published duration for {subject} is {duration}."


def eligibility_answer(entity: Any) -> str:
    subject = entity_label(entity)
    summary = clean_text(safe_get(entity, "eligibility_summary", None))
    detail = clean_text(safe_get(entity, "eligibility_content", None), max_chars=480)
    if summary and detail and summary.casefold() not in detail.casefold():
        return f"For {subject}, the eligibility summary is: {summary}. {detail}"
    if detail:
        return f"For {subject}, {detail}"
    if summary:
        return f"For {subject}, the published eligibility is: {summary}."
    programs = safe_get(entity, "programs_table", []) or []
    rendered: list[str] = []
    for program in programs if isinstance(programs, (list, tuple)) else []:
        name = clean_text(safe_get(program, "program_name", None))
        eligibility = clean_text(safe_get(program, "program_eligibility", None))
        if eligibility:
            rendered.append(f"{name}: {eligibility}" if name else eligibility)
    if rendered:
        return f"Published program eligibility at {subject}: {'; '.join(rendered[:6])}."
    return unavailable_answer(entity, "eligibility")


def mode_answer(entity: Any) -> str:
    subject = entity_label(entity)
    mode = clean_text(first_value(entity, "mode", "mode_of_learning", default=None))
    if not mode:
        return unavailable_answer(entity, "learning-mode")
    return f"{subject} is offered in {mode} mode."


def placements_answer(entity: Any) -> str:
    subject = entity_label(entity)
    content = clean_text(
        first_value(
            entity,
            "placement_content",
            "placement_support",
            "placements_content",
            default=None,
        ),
        max_chars=520,
    )
    if not content:
        return unavailable_answer(entity, "placement")
    return render_sections(
        entity_heading(entity),
        [("Placement Support", [content])],
        intro=f"Published placement information for {subject}.",
    )


def emi_answer(entity: Any) -> str:
    subject = entity_label(entity)
    amount = clean_text(safe_get(entity, "emi_amount", None))
    content = clean_text(safe_get(entity, "emi_content", None), max_chars=420)
    if amount and content:
        return f"The listed EMI for {subject} is {amount}. {content}"
    if amount:
        return f"The listed EMI for {subject} is {amount}."
    if content:
        return f"For {subject}, {content}"
    return unavailable_answer(entity, "EMI")


def syllabus_answer(entity: Any) -> str:
    subject = entity_label(entity)
    content = clean_text(safe_get(entity, "syllabus_content", None), max_chars=560)
    if not content:
        return unavailable_answer(entity, "syllabus")
    return f"The published curriculum for {subject} includes: {content}"


def admission_answer(entity: Any) -> str:
    subject = entity_label(entity)
    steps = clean_text(safe_get(entity, "admission_steps", None), max_chars=500)
    fee_note = clean_text(safe_get(entity, "admission_fee_note", None), max_chars=180)
    if steps and fee_note:
        return f"For {subject}, {steps} {fee_note}"
    if steps:
        return f"For {subject}, {steps}"
    if fee_note:
        return f"For {subject}, the published admission note is: {fee_note}"
    return unavailable_answer(entity, "admission-process")


def exam_answer(entity: Any) -> str:
    subject = entity_label(entity)
    content = clean_text(safe_get(entity, "exam_content", None), max_chars=480)
    if not content:
        return unavailable_answer(entity, "examination")
    return f"For {subject}, {content}"


def _nested_lines(
    value: Any,
    *,
    field_groups: tuple[tuple[str, ...], ...],
    limit: int = 6,
) -> list[str]:
    """Render publisher strings/objects without assuming one feed-specific shape."""

    if not has_value(value):
        return []
    values = (
        value
        if isinstance(value, Iterable) and not isinstance(value, (str, bytes, Mapping))
        else [value]
    )
    result: list[str] = []
    for item in values:
        if isinstance(item, (str, int, float)):
            rendered = clean_text(item)
        else:
            parts = [
                clean_text(first_value(item, *fields, default=None)) for fields in field_groups
            ]
            rendered = " — ".join(part for part in parts if part)
        if rendered and rendered.casefold() not in {line.casefold() for line in result}:
            result.append(rendered)
        if len(result) >= limit:
            break
    return result


def accreditation_items(entity: Any) -> list[str]:
    """Collect approvals and accreditation bodies from all documented shapes."""

    details: list[str] = []
    naac = clean_text(safe_get(entity, "naac_grade", None))
    ugc = clean_text(first_value(entity, "ugc_status", "ugc_approved", default=None))
    if naac:
        details.append(f"NAAC grade {naac}")
    if ugc:
        details.append(ugc)
    details.extend(
        _nested_lines(
            safe_get(entity, "accreditations", None),
            field_groups=(
                ("body_name", "name", "title"),
                ("body_descriptor", "descriptor", "status"),
                ("body_detail", "detail", "description"),
            ),
        )
    )
    for path in ("approvals", "approval"):
        details.extend(
            _nested_lines(
                safe_get(entity, path, None),
                field_groups=(
                    ("body_name", "authority", "name", "title"),
                    ("status", "descriptor", "detail", "description"),
                ),
            )
        )
    return list(dict.fromkeys(details))


def ranking_items(entity: Any) -> list[str]:
    """Collect explicit publisher rankings; never infer a ranking from NAAC or fees."""

    result: list[str] = []
    for path in ("rankings", "ranking", "ranking_content"):
        result.extend(
            _nested_lines(
                safe_get(entity, path, None),
                field_groups=(
                    ("ranking_body", "organization", "agency", "name", "title"),
                    ("rank", "position", "value"),
                    ("ranking_year", "year"),
                    ("description", "detail"),
                ),
            )
        )
    facts = safe_get(entity, "facts", []) or []
    if isinstance(facts, Iterable) and not isinstance(facts, (str, bytes, Mapping)):
        for fact in facts:
            title = clean_text(first_value(fact, "fact_title", "title", default=None))
            if "rank" not in title.casefold():
                continue
            description = clean_text(
                first_value(fact, "fact_description", "description", default=None)
            )
            result.append(" — ".join(value for value in (title, description) if value))
    return list(dict.fromkeys(value for value in result if value))[:6]


def accreditation_answer(entity: Any) -> str:
    subject = entity_label(entity)
    details = accreditation_items(entity)
    if not details:
        return unavailable_answer(entity, "accreditation")
    return render_sections(
        entity_heading(entity),
        [("Approvals & Accreditations", details)],
        intro=f"Published accreditation details for {subject}.",
    )


def ranking_answer(entity: Any) -> str:
    details = ranking_items(entity)
    if not details:
        return unavailable_answer(entity, "ranking")
    return render_sections(entity_heading(entity), [("Published Rankings", details)])


def certificate_answer(entity: Any) -> str:
    subject = entity_label(entity)
    description = clean_text(safe_get(entity, "certificate_description", None), max_chars=420)
    validity = clean_text(safe_get(entity, "validity", None), max_chars=220)
    if description and validity:
        return f"For {subject}, {description} {validity}"
    if description:
        return f"For {subject}, {description}"
    if validity:
        return f"For {subject}, {validity}"
    return unavailable_answer(entity, "certificate")


def jobs_answer(entity: Any) -> str:
    subject = entity_label(entity)
    profiles = safe_get(entity, "job_profiles", []) or []
    rendered: list[str] = []
    for profile in profiles if isinstance(profiles, (list, tuple)) else []:
        title = clean_text(safe_get(profile, "job_title", None))
        salary = clean_text(safe_get(profile, "avg_salary", None))
        if title:
            rendered.append(f"{title} ({salary})" if salary else title)
    rendered.extend(
        _nested_lines(
            safe_get(entity, "career_outcomes", None),
            field_groups=(
                ("job_title", "role", "name", "title"),
                ("avg_salary", "salary", "outcome", "description"),
            ),
        )
    )
    if not rendered:
        return unavailable_answer(entity, "career-outcome")
    return render_sections(
        entity_heading(entity),
        [("Career Outcomes", rendered[:6])],
        intro=f"Published career options for {subject}.",
    )


def _provider_name(entity: Any, catalog: Any = None) -> str:
    """Resolve a provider name without exposing a linked catalog identifier."""

    direct = clean_text(
        first_value(entity, "university_name", "university_full_name", default=None)
    )
    if direct:
        return direct

    linked = safe_get(entity, "linked_university", None)
    if not has_value(linked):
        return ""

    embedded = clean_text(
        first_value(
            linked,
            "university_full_name",
            "university_name",
            "canonical_name",
            "name",
            default=None,
        )
    )
    if embedded:
        return embedded

    reference = first_value(linked, "id", "entity_id", "slug", default=linked)
    provider = catalog_get_entity(catalog, reference)
    if provider is None:
        return ""
    return clean_text(
        first_value(
            provider,
            "university_full_name",
            "university_name",
            "canonical_name",
            "name",
            default=None,
        )
    ) or entity_label(provider, default="")


def provider_answer(entity: Any, catalog: Any = None) -> str:
    """Name the published university provider, resolving linked ids when needed."""

    subject = entity_label(entity)
    provider = _provider_name(entity, catalog)
    if not provider:
        return unavailable_answer(entity, "provider")
    if provider.casefold() == subject.casefold():
        return f"The published catalog record is for {provider}."
    return f"{subject} is offered by {provider}."


def programs_answer(entity: Any) -> str:
    subject = entity_label(entity)
    programs = safe_get(entity, "programs_table", []) or []
    rendered: list[str] = []
    for program in programs if isinstance(programs, (list, tuple)) else []:
        name = clean_text(safe_get(program, "program_name", None))
        fee = clean_text(safe_get(program, "program_fee", None))
        if name:
            rendered.append(f"{name} ({fee})" if fee else name)
    if not rendered:
        return unavailable_answer(entity, "program")
    return render_sections(
        entity_heading(entity),
        [("Published Programs", rendered[:8])],
        intro=f"Programs currently listed for {subject}.",
    )


def reviews_answer(entity: Any) -> str:
    subject = entity_label(entity)
    reviews = safe_get(entity, "reviews", []) or []
    rendered: list[str] = []
    for review in reviews if isinstance(reviews, (list, tuple)) else []:
        text = clean_text(safe_get(review, "review_text", None), max_chars=180)
        reviewer = clean_text(safe_get(review, "reviewer_name", None))
        if text:
            rendered.append(f'"{text}" — {reviewer}' if reviewer else f'"{text}"')
    if not rendered:
        return unavailable_answer(entity, "review")
    return render_sections(
        entity_heading(entity),
        [("Student Feedback", rendered[:3])],
        intro=f"Published student feedback for {subject}.",
    )


def specialization_items(entity: Any, catalog: Any = None) -> list[str]:
    """Return concrete catalog specialization labels related to this record."""

    result = related_specialization_names(entity, catalog, limit=8)
    for path in ("specializations", "popular_specializations"):
        result.extend(
            _nested_lines(
                safe_get(entity, path, None),
                field_groups=(("specialization_name", "spec_name", "name", "title"),),
                limit=8,
            )
        )
    return list(dict.fromkeys(result))[:8]


def specializations_answer(entity: Any, catalog: Any = None) -> str:
    details = specialization_items(entity, catalog)
    intro = clean_text(safe_get(entity, "specializations_intro", None), max_chars=320)
    if not details and not intro:
        return unavailable_answer(entity, "specialization")
    sections = [("Popular Specializations", details)] if details else []
    return render_sections(entity_heading(entity), sections, intro=intro)


def career_items(entity: Any) -> list[str]:
    profiles = safe_get(entity, "job_profiles", []) or []
    result: list[str] = []
    for profile in profiles if isinstance(profiles, (list, tuple)) else []:
        title = clean_text(safe_get(profile, "job_title", None))
        salary = clean_text(safe_get(profile, "avg_salary", None))
        if title:
            result.append(f"{title} ({salary})" if salary else title)
    result.extend(
        _nested_lines(
            safe_get(entity, "career_outcomes", None),
            field_groups=(
                ("job_title", "role", "name", "title"),
                ("avg_salary", "salary", "outcome", "description"),
            ),
            limit=4,
        )
    )
    return list(dict.fromkeys(result))[:4]


def about_answer(entity: Any, catalog: Any = None) -> str:
    subject = entity_label(entity)
    hero = clean_text(safe_get(entity, "hero_description", None), max_chars=260)
    about = clean_text(safe_get(entity, "about_content", None), max_chars=520)
    provider = _provider_name(entity, catalog)
    duration = clean_text(safe_get(entity, "duration", None))
    mode = clean_text(first_value(entity, "mode", "mode_of_learning", default=None))
    fee = entity_fee(entity)
    eligibility = clean_text(
        first_value(entity, "eligibility_summary", "eligibility_content", default=None),
        max_chars=260,
    )
    starting_fee = clean_text(safe_get(entity, "starting_fee", None))
    details: list[str] = []
    if duration:
        details.append(f"duration: {duration}")
    if mode:
        details.append(f"mode: {mode}")
    if fee:
        details.append(f"fee: {fee}")
    if starting_fee and starting_fee.casefold() != fee.casefold():
        details.append(f"starting fee: {starting_fee}")
    if eligibility:
        details.append(f"eligibility: {eligibility}")

    overview: list[str] = []
    if hero:
        overview.append(hero)
    if about and (not hero or hero.casefold() not in about.casefold()):
        overview.append(about)

    intro = None
    if provider and provider.casefold() != subject.casefold():
        intro = f"{subject} is offered by {provider}."

    sections: list[tuple[str, Iterable[Any]]] = []
    if overview:
        sections.append(("Overview", overview))
    if details:
        sections.append(("Published Details", details))
    approvals = accreditation_items(entity)
    if approvals:
        sections.append(("Approvals & Accreditations", approvals))
    specializations = specialization_items(entity, catalog)
    if specializations:
        sections.append(("Popular Specializations", specializations[:6]))
    placement = clean_text(
        first_value(
            entity,
            "placement_content",
            "placement_support",
            "placements_content",
            default=None,
        ),
        max_chars=320,
    )
    if placement:
        sections.append(("Placement Support", [placement]))
    careers = career_items(entity)
    if careers:
        sections.append(("Career Outcomes", careers))
    rankings = ranking_items(entity)
    if rankings:
        sections.append(("Published Rankings", rankings))
    if sections or intro:
        return render_sections(entity_heading(entity), sections, intro=intro)
    return unavailable_answer(entity, "overview")


TEMPLATE_BY_TOPIC: dict[str, Callable[[Any], str]] = {
    "fee": fee_answer,
    "duration": duration_answer,
    "eligibility": eligibility_answer,
    "mode": mode_answer,
    "placements": placements_answer,
    "emi": emi_answer,
    "syllabus": syllabus_answer,
    "admission": admission_answer,
    "exam": exam_answer,
    "accreditation": accreditation_answer,
    "ranking": ranking_answer,
    "certificate": certificate_answer,
    "jobs": jobs_answer,
    "programs": programs_answer,
    "reviews": reviews_answer,
    "provider": provider_answer,
    "about": about_answer,
}


def render_topic(topic: str, entity: Any, *, catalog: Any = None) -> str:
    if topic == "provider":
        return provider_answer(entity, catalog)
    if topic == "about":
        return about_answer(entity, catalog)
    if topic == "specializations":
        return specializations_answer(entity, catalog)
    template = TEMPLATE_BY_TOPIC.get(topic, about_answer)
    return template(entity)


def topic_from_message(message: str) -> str:
    """Classify common factual slots without an LLM call."""

    normalized = f" {str(message or '').casefold()} "
    checks: tuple[tuple[str, tuple[str, ...]], ...] = (
        (
            "provider",
            (
                "which university",
                "what university",
                "university offers",
                "university offer",
                "offered by",
                "who offers",
                "program provider",
            ),
        ),
        ("emi", (" emi ", "installment", "instalment", "monthly payment")),
        ("fee", (" fee", "fees", "cost", "tuition", "price")),
        ("duration", ("duration", "how long", " years", " semesters")),
        ("eligibility", ("eligib", "qualif", "requirement", "who can apply")),
        ("mode", (" mode", "online or offline", "distance mode", "learning mode")),
        ("placements", ("placement", "hiring", "recruit", "career support")),
        (
            "jobs",
            (
                "job profile",
                " job ",
                " jobs",
                " role",
                "career option",
                "career opportunit",
                "career outcome",
                "career scope",
                "salary",
                "package",
                "earning",
            ),
        ),
        ("syllabus", ("syllabus", "curriculum", "subjects", "semester-wise")),
        ("admission", ("admission", "how to apply", "application process", "enrol")),
        ("exam", ("exam", "proctor", "assessment")),
        ("ranking", ("ranking", "ranked", " rank ", "position in")),
        ("accreditation", ("naac", "ugc", "accredit", "approval", "recognition")),
        ("certificate", ("certificate", "degree valid", "validity")),
        ("specializations", ("specializations", "specialisations")),
        ("programs", ("programs", "courses offered", "degrees offered")),
        ("reviews", ("reviews", "student feedback", "testimonials")),
    )
    for topic, needles in checks:
        if any(needle in normalized for needle in needles):
            return topic
    return "about"


_TOPIC_FIELDS: dict[str, tuple[str, ...]] = {
    "fee": ("total_fee", "starting_fee", "fee_plans", "programs_table"),
    "duration": ("duration",),
    "eligibility": ("eligibility_summary", "eligibility_content", "programs_table"),
    "mode": ("mode", "mode_of_learning"),
    "emi": ("emi_amount", "emi_content", "fee_plans"),
    "placements": ("placement_content", "placement_support", "placements_content"),
    "syllabus": ("syllabus_content",),
    "jobs": ("job_profiles", "career_outcomes"),
    "admission": ("admission_steps", "admission_fee_note"),
    "accreditation": ("naac_grade", "ugc_status", "ugc_approved", "accreditations"),
    "programs": ("programs_table",),
    "reviews": ("reviews",),
    "exam": ("exam_content",),
}

_TOPIC_LABELS = {
    "fee": "Fees",
    "duration": "Duration",
    "eligibility": "Eligibility",
    "mode": "Learning Mode",
    "emi": "EMI Options",
    "placements": "Placement Support",
    "jobs": "Career Scope",
    "specializations": "Specializations",
    "accreditation": "Approvals",
    "ranking": "Rankings",
    "programs": "Programs",
    "admission": "Admission Process",
    "syllabus": "Syllabus",
    "reviews": "Reviews",
}

_TOPIC_ACTION_ORDER: dict[str, tuple[str, ...]] = {
    "fee": ("eligibility", "specializations", "placements", "emi", "duration"),
    "eligibility": ("fee", "specializations", "admission", "duration"),
    "placements": ("jobs", "fee", "specializations", "eligibility"),
    "jobs": ("placements", "specializations", "fee", "syllabus"),
    "specializations": ("fee", "eligibility", "jobs", "placements"),
    "accreditation": ("ranking", "programs", "fee", "reviews"),
    "ranking": ("accreditation", "programs", "fee", "placements"),
    "programs": ("fee", "eligibility", "accreditation", "specializations"),
    "about": (
        "fee",
        "eligibility",
        "specializations",
        "placements",
        "jobs",
        "accreditation",
        "ranking",
        "duration",
        "programs",
    ),
}


def has_topic_data(entity: Any, topic: str, *, catalog: Any = None) -> bool:
    """Return whether selecting a quick action can produce a grounded answer."""

    if topic == "specializations":
        return bool(specialization_items(entity, catalog)) or has_value(
            safe_get(entity, "specializations_intro", None)
        )
    if topic == "ranking":
        return bool(ranking_items(entity))
    if topic == "accreditation":
        return bool(accreditation_items(entity))
    return any(has_value(safe_get(entity, path, None)) for path in _TOPIC_FIELDS.get(topic, ()))


def _action_subject(entity: Any) -> str:
    heading = entity_heading(entity)
    return heading if len(heading) <= 48 else entity_university(entity) or entity_label(entity)


def suggested_chips(
    entity: Any,
    topic: str,
    *,
    catalog: Any = None,
    limit: int = 4,
) -> list[str]:
    """Build executable, subject-qualified actions only for published data."""

    result: list[str] = []
    subject = _action_subject(entity)
    order = _TOPIC_ACTION_ORDER.get(topic, _TOPIC_ACTION_ORDER["about"])
    supports_compare = entity_page_type(entity) in {
        "university",
        "course",
        "specialization",
    }
    topic_limit = max(limit - 1, 0) if supports_compare else limit
    for candidate_topic in order:
        if len(result) >= topic_limit:
            break
        if candidate_topic == topic or not has_topic_data(entity, candidate_topic, catalog=catalog):
            continue
        label = _TOPIC_LABELS[candidate_topic]
        result.append(f"{subject} {label}")
    if len(result) < limit and supports_compare:
        result.append(f"Compare {subject} with another university")
    return result


__all__ = [
    "TEMPLATE_BY_TOPIC",
    "about_answer",
    "accreditation_answer",
    "accreditation_items",
    "admission_answer",
    "career_items",
    "certificate_answer",
    "duration_answer",
    "eligibility_answer",
    "emi_answer",
    "entity_not_found_answer",
    "exam_answer",
    "fee_answer",
    "has_topic_data",
    "jobs_answer",
    "mode_answer",
    "placements_answer",
    "programs_answer",
    "provider_answer",
    "ranking_answer",
    "ranking_items",
    "render_topic",
    "reviews_answer",
    "specialization_items",
    "specializations_answer",
    "suggested_chips",
    "syllabus_answer",
    "topic_from_message",
    "unavailable_answer",
]
