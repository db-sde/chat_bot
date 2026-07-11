"""Zero-LLM response templates for catalog-backed questions."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from data.accessor import safe_get

from .cards import (
    catalog_get_entity,
    clean_text,
    entity_fee,
    entity_label,
    first_value,
    has_value,
)


def unavailable_answer(entity: Any, topic: str) -> str:
    subject = entity_label(entity)
    return (
        f"I don't have published {topic} information for {subject} yet. "
        "Would you like to check another detail or speak with a counsellor?"
    )


def entity_not_found_answer(name: str, suggestion: str | None = None) -> str:
    """Response when entity_matcher returned no match — the name is unresolved."""

    base = f"I couldn't find a match for \"{name}\" in the published catalog."
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
    content = clean_text(safe_get(entity, "placement_content", None), max_chars=520)
    if not content:
        return unavailable_answer(entity, "placement")
    return f"For {subject}, the published placement information says: {content}"


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


def accreditation_answer(entity: Any) -> str:
    subject = entity_label(entity)
    naac = clean_text(safe_get(entity, "naac_grade", None))
    ugc = clean_text(first_value(entity, "ugc_status", "ugc_approved", default=None))
    details = [value for value in (f"NAAC grade {naac}" if naac else "", ugc) if value]
    if not details:
        return unavailable_answer(entity, "accreditation")
    return f"The published accreditation details for {subject} are: {'; '.join(details)}."


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
    if not rendered:
        return unavailable_answer(entity, "career-outcome")
    return f"Published career options for {subject} include {', '.join(rendered[:6])}."


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
    return f"Published programs at {subject} include {', '.join(rendered[:8])}."


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
    return f"The published student feedback for {subject} includes: {'; '.join(rendered[:3])}."


def about_answer(entity: Any, catalog: Any = None) -> str:
    subject = entity_label(entity)
    hero = clean_text(safe_get(entity, "hero_description", None), max_chars=260)
    about = clean_text(safe_get(entity, "about_content", None), max_chars=520)
    if hero and about and hero.casefold() not in about.casefold():
        return f"{subject}: {hero} {about}"
    if about:
        return f"{subject}: {about}"
    if hero:
        return f"{subject}: {hero}"

    provider = _provider_name(entity, catalog)
    duration = clean_text(safe_get(entity, "duration", None))
    mode = clean_text(first_value(entity, "mode", "mode_of_learning", default=None))
    fee = entity_fee(entity)
    eligibility = clean_text(
        first_value(entity, "eligibility_summary", "eligibility_content", default=None),
        max_chars=260,
    )

    sentences: list[str] = []
    if provider and provider.casefold() != subject.casefold():
        sentences.append(f"{subject} is offered by {provider}.")

    published: list[str] = []
    if duration:
        published.append(f"duration: {duration}")
    if mode:
        published.append(f"mode: {mode}")
    if fee:
        published.append(f"fee: {fee}")
    if eligibility:
        published.append(f"eligibility: {eligibility}")
    if published:
        sentences.append(f"Published details — {'; '.join(published)}.")
    if sentences:
        return " ".join(sentences)
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
                "salary",
                "package",
                "earning",
            ),
        ),
        ("syllabus", ("syllabus", "curriculum", "subjects", "semester-wise")),
        ("admission", ("admission", "how to apply", "application process", "enrol")),
        ("exam", ("exam", "proctor", "assessment")),
        ("accreditation", ("naac", "ugc", "accredit", "approval", "recognition")),
        ("certificate", ("certificate", "degree valid", "validity")),
        ("programs", ("programs", "courses offered", "degrees offered")),
        ("reviews", ("reviews", "student feedback", "testimonials")),
    )
    for topic, needles in checks:
        if any(needle in normalized for needle in needles):
            return topic
    return "about"


_CHIP_FIELDS: dict[str, tuple[str, ...]] = {
    "Fees": ("total_fee", "starting_fee", "fee_plans"),
    "Duration": ("duration",),
    "Eligibility": ("eligibility_summary", "eligibility_content", "programs_table"),
    "Mode": ("mode", "mode_of_learning"),
    "EMI options": ("emi_amount", "emi_content", "fee_plans"),
    "Placements": ("placement_content",),
    "Syllabus": ("syllabus_content",),
    "Job profiles": ("job_profiles",),
    "Admission process": ("admission_steps", "admission_fee_note"),
    "Accreditations": ("naac_grade", "ugc_status", "ugc_approved", "accreditations"),
    "Programs": ("programs_table",),
    "Reviews": ("reviews",),
}

_TOPIC_CHIPS: dict[str, tuple[str, ...]] = {
    "fee": ("Eligibility", "EMI options", "Placements"),
    "duration": ("Fees", "Eligibility", "Mode"),
    "eligibility": ("Fees", "Admission process", "Duration"),
    "mode": ("Duration", "Fees", "Exams"),
    "placements": ("Job profiles", "Fees", "Eligibility"),
    "emi": ("Fees", "Eligibility", "Admission process"),
    "syllabus": ("Duration", "Job profiles", "Fees"),
    "admission": ("Eligibility", "Fees", "EMI options"),
    "exam": ("Mode", "Syllabus", "Duration"),
    "accreditation": ("Programs", "Fees", "Reviews"),
    "certificate": ("Accreditations", "Mode", "Placements"),
    "jobs": ("Placements", "Fees", "Syllabus"),
    "programs": ("Fees", "Eligibility", "Accreditations"),
    "reviews": ("Programs", "Accreditations", "Fees"),
    "provider": ("Fees", "Eligibility", "Duration"),
    "about": ("Fees", "Eligibility", "Placements", "Programs", "Accreditations"),
}


def suggested_chips(entity: Any, topic: str, *, limit: int = 3) -> list[str]:
    """Return static chips only when the corresponding entity data exists."""

    result: list[str] = []
    for label in _TOPIC_CHIPS.get(topic, _TOPIC_CHIPS["about"]):
        paths = ("exam_content",) if label == "Exams" else _CHIP_FIELDS.get(label, ())
        if any(has_value(safe_get(entity, path, None)) for path in paths):
            result.append(label)
        if len(result) >= limit:
            break
    return result


__all__ = [
    "TEMPLATE_BY_TOPIC",
    "about_answer",
    "accreditation_answer",
    "admission_answer",
    "certificate_answer",
    "duration_answer",
    "eligibility_answer",
    "emi_answer",
    "entity_not_found_answer",
    "exam_answer",
    "fee_answer",
    "jobs_answer",
    "mode_answer",
    "placements_answer",
    "programs_answer",
    "provider_answer",
    "render_topic",
    "reviews_answer",
    "suggested_chips",
    "syllabus_answer",
    "topic_from_message",
    "unavailable_answer",
]
