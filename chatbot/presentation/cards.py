"""Catalog-grounded builders for rich response components."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from data.accessor import safe_get
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
from response.templates import (
    accreditation_items,
    career_items,
    ranking_items,
    specialization_items,
)
from schemas import (
    CTA,
    CardDetails,
    CardFact,
    CardFAQ,
    CardReview,
    ComparisonCard,
    ComparisonItem,
    LeadCTAComponent,
    ProgramCard,
    QuickAction,
    QuickActionsComponent,
    UniversityCard,
)

from .formatter import (
    card_fact,
    catalog_strings,
    comparison_items_from_text,
    optional_text,
    unique_facts,
)


def _identifier(entity: Any) -> str | None:
    return optional_text(first_value(entity, "id", "entity_id", default=None))


def _card_name(entity: Any, default: str) -> str:
    page_type = entity_page_type(entity)
    paths = {
        "university": ("university_full_name", "university_name", "name"),
        "course": ("program_name", "name", "category"),
        "specialization": ("specialization_name", "spec_name", "name"),
    }.get(page_type, ("name", "title"))
    return optional_text(first_value(entity, *paths, default=None)) or entity_label(entity, default)


def _summary(entity: Any) -> str | None:
    return optional_text(
        first_value(
            entity,
            "hero_description",
            "about_content",
            "why_choose_content",
            default=None,
        ),
        max_chars=360,
    )


def _details_url(entity: Any) -> str | None:
    return optional_text(
        first_value(
            entity,
            "details_url",
            "page_url",
            "canonical_url",
            "url",
            default=None,
        )
    )


def _linked_entity(entity: Any, path: str, catalog: Any) -> Any:
    reference = safe_get(entity, path, None)
    if isinstance(reference, Mapping):
        embedded_type = entity_page_type(reference)
        if embedded_type:
            return reference
        reference = first_value(reference, "id", "entity_id", "slug", default=None)
    return catalog_get_entity(catalog, reference) if reference is not None else None


def _first_catalog_value(entity: Any, catalog: Any, *paths: str) -> Any:
    value = first_value(entity, *paths, default=None)
    if value is not None and clean_text(value):
        return value
    for relation in ("linked_course", "linked_university"):
        linked = _linked_entity(entity, relation, catalog)
        if linked is not None:
            value = first_value(linked, *paths, default=None)
            if value is not None and clean_text(value):
                return value
    return None


def _integer_value(value: Any) -> int | None:
    if isinstance(value, int):
        return max(value, 0)
    rendered = clean_text(value)
    if not rendered:
        return None
    digits = "".join(character for character in rendered if character.isdigit())
    return int(digits) if digits else None


def _card_details(entity: Any, catalog: Any = None) -> CardDetails | None:
    description = optional_text(
        first_value(
            entity,
            "hero_description",
            "about_content",
            "why_choose_content",
            default=None,
        ),
        max_chars=2400,
    )
    accreditations = accreditation_items(entity)
    if not accreditations:
        for relation in ("linked_course", "linked_university"):
            linked = _linked_entity(entity, relation, catalog)
            if linked is not None and (accreditations := accreditation_items(linked)):
                break
    admission_steps = optional_text(
        first_value(entity, "admission_steps", "admission_fee_note", default=None),
        max_chars=2400,
    )

    reviews: list[CardReview] = []
    for review in safe_get(entity, "reviews", []) or []:
        text = optional_text(safe_get(review, "review_text", None), max_chars=900)
        if not text:
            continue
        reviews.append(
            CardReview(
                text=text,
                reviewer_name=optional_text(safe_get(review, "reviewer_name", None)),
                reviewer_label=optional_text(safe_get(review, "reviewer_label", None)),
            )
        )
        if len(reviews) >= 6:
            break

    faqs: list[CardFAQ] = []
    for faq in safe_get(entity, "faqs", []) or []:
        question = optional_text(safe_get(faq, "question", None), max_chars=300)
        answer = optional_text(safe_get(faq, "answer", None), max_chars=1600)
        if question and answer:
            faqs.append(CardFAQ(question=question, answer=answer))
        if len(faqs) >= 8:
            break

    details = CardDetails(
        description=description,
        accreditations=accreditations[:8],
        admission_steps=admission_steps,
        reviews=reviews,
        faqs=faqs,
    )
    return details if any(details.model_dump().values()) else None


def _specialization_count(entity: Any, catalog: Any) -> int | None:
    published = _integer_value(safe_get(entity, "num_specializations", None))
    if published is not None:
        return published
    entity_id = _identifier(entity)
    if entity_page_type(entity) == "course" and entity_id:
        count = sum(
            1
            for candidate in iter_catalog_entities(catalog)
            if entity_page_type(candidate) == "specialization"
            and clean_text(
                first_value(candidate, "linked_course.id", "linked_course", default=None)
            )
            == entity_id
        )
        return count or None
    other_specs = safe_get(entity, "other_specs", []) or []
    return len(other_specs) or None


def _career_pair(entity: Any) -> tuple[str | None, str | None]:
    for profile in safe_get(entity, "job_profiles", []) or []:
        career = optional_text(first_value(profile, "job_title", "role", "name", default=None))
        salary = optional_text(first_value(profile, "avg_salary", "salary", default=None))
        if career or salary:
            return career, salary
    return None, None


def _approval_fact(entity: Any) -> CardFact | None:
    values = accreditation_items(entity)
    return card_fact("Approvals & accreditations", "; ".join(values[:4])) if values else None


def _ranking_fact(entity: Any) -> CardFact | None:
    values = ranking_items(entity)
    return card_fact("Published rankings", "; ".join(values[:3])) if values else None


def build_university_card(entity: Any) -> UniversityCard:
    """Build a university card without filling absent publisher facts."""

    programs = catalog_strings(
        safe_get(entity, "programs_table", None),
        fields=("program_name", "name", "title"),
        limit=8,
    )
    program_rows = safe_get(entity, "programs_table", None) or []
    program_count = _integer_value(safe_get(entity, "num_programs", None))
    if program_count is None and isinstance(program_rows, Iterable) and not isinstance(
        program_rows, (str, bytes, Mapping)
    ):
        program_count = len(list(program_rows))
    established_year = optional_text(safe_get(entity, "established_year", None))
    learning_mode = optional_text(
        first_value(entity, "mode_of_learning", "mode", default=None)
    )
    starting_fee = optional_text(first_value(entity, "starting_fee", default=None))
    naac_grade = optional_text(safe_get(entity, "naac_grade", None))
    ugc_status = optional_text(
        first_value(entity, "ugc_approved", "ugc_status", default=None)
    )
    highlights = unique_facts(
        (
            card_fact("Established", established_year),
            card_fact("Learning mode", learning_mode),
            card_fact("Starting fee", starting_fee),
            card_fact("NAAC grade", naac_grade),
            card_fact("UGC status", ugc_status),
            _approval_fact(entity),
            _ranking_fact(entity),
            card_fact(
                "Why students consider it",
                safe_get(entity, "why_choose_content", None),
                max_chars=300,
            ),
        )
    )
    return UniversityCard(
        id=_identifier(entity),
        slug=optional_text(safe_get(entity, "slug", None)),
        name=_card_name(entity, "University"),
        summary=_summary(entity),
        logo_url=optional_text(
            first_value(
                entity,
                "logo_url",
                "university_logo",
                "brand_logo",
                "logo",
                default=None,
            )
        ),
        details_url=_details_url(entity),
        established_year=established_year,
        starting_fee=starting_fee,
        program_count=program_count,
        learning_mode=learning_mode,
        naac_grade=naac_grade,
        ugc_status=ugc_status,
        highlights=highlights,
        programs=programs,
        details=_card_details(entity),
    )


def build_program_card(entity: Any, catalog: Any = None) -> ProgramCard:
    """Build a course/specialization card from publisher fields only."""

    placement = optional_text(
        first_value(
            entity,
            "placement_content",
            "placement_support",
            "placements_content",
            default=None,
        ),
        max_chars=300,
    )
    naac_grade = optional_text(_first_catalog_value(entity, catalog, "naac_grade"))
    ugc_status = optional_text(
        _first_catalog_value(entity, catalog, "ugc_status", "ugc_approved")
    )
    eligibility = optional_text(
        _first_catalog_value(
            entity,
            catalog,
            "eligibility_summary",
            "eligibility_content",
        ),
        max_chars=320,
    )
    emi = optional_text(_first_catalog_value(entity, catalog, "emi_amount", "emi_content"))
    career_outcome, average_salary = _career_pair(entity)
    highlights = unique_facts(
        (
            _approval_fact(entity),
            _ranking_fact(entity),
            card_fact("Placement support", placement),
        )
    )
    page_type = entity_page_type(entity)
    return ProgramCard(
        kind="specialization" if page_type == "specialization" else "course",
        id=_identifier(entity),
        slug=optional_text(safe_get(entity, "slug", None)),
        name=_card_name(entity, "Program"),
        university_name=optional_text(entity_university(entity)),
        category=optional_text(safe_get(entity, "category", None)),
        summary=_summary(entity),
        duration=optional_text(safe_get(entity, "duration", None)),
        fee=optional_text(entity_fee(entity)),
        eligibility=eligibility,
        mode=optional_text(first_value(entity, "mode", "mode_of_learning", default=None)),
        naac_grade=naac_grade,
        ugc_status=ugc_status,
        specialization_count=_specialization_count(entity, catalog),
        emi=emi,
        career_outcome=career_outcome,
        average_salary=average_salary,
        specializations=specialization_items(entity, catalog),
        career_outcomes=career_items(entity),
        highlights=highlights,
        details_url=_details_url(entity),
        details=_card_details(entity, catalog),
    )


def build_entity_card(entity: Any, catalog: Any = None) -> UniversityCard | ProgramCard:
    if entity_page_type(entity) == "university":
        return build_university_card(entity)
    return build_program_card(entity, catalog)


def _resolve_operand(operand: Any, catalog: Any) -> Any:
    if isinstance(operand, (str, int)):
        return catalog_get_entity(catalog, operand)
    if entity_page_type(operand):
        return operand
    reference = first_value(operand, "entity_id", "id", "slug", default=None)
    if reference is not None:
        resolved = catalog_get_entity(catalog, reference)
        if resolved is not None:
            return resolved
    return None


def _comparison_item(entity: Any, catalog: Any = None) -> ComparisonItem:
    page_type = entity_page_type(entity)
    provider = entity_university(entity)
    specializations = specialization_items(entity, catalog)
    specialization_count = _specialization_count(entity, catalog)
    specialization_value = (
        str(specialization_count)
        if specialization_count is not None
        else ", ".join(specializations[:5])
    )
    facts = unique_facts(
        (
            card_fact("Fees", entity_fee(entity)),
            card_fact("Duration", safe_get(entity, "duration", None)),
            card_fact("Mode", first_value(entity, "mode", "mode_of_learning", default=None)),
            card_fact("NAAC grade", _first_catalog_value(entity, catalog, "naac_grade")),
            card_fact(
                "UGC status",
                _first_catalog_value(entity, catalog, "ugc_status", "ugc_approved"),
            ),
            card_fact("Specializations", specialization_value),
            card_fact(
                "EMI",
                _first_catalog_value(entity, catalog, "emi_amount", "emi_content"),
            ),
            card_fact(
                "Eligibility",
                _first_catalog_value(
                    entity,
                    catalog,
                    "eligibility_summary",
                    "eligibility_content",
                ),
            ),
        ),
        limit=8,
    )
    return ComparisonItem(
        id=_identifier(entity),
        name=_card_name(entity, "Catalog option"),
        subtitle=provider if page_type != "university" and provider else None,
        facts=facts,
    )


def _comparison_verdict(items: Iterable[ComparisonItem]) -> str | None:
    priced: list[tuple[float, str]] = []
    for item in items:
        fee = next(
            (
                fact.value
                for fact in item.facts
                if fact.label in {"Fees", "Fee", "Starting fee", "Fee range"}
            ),
            None,
        )
        amount = parse_money(fee)
        if amount is not None:
            label = f"{item.subtitle} — {item.name}" if item.subtitle else item.name
            priced.append((amount, label))
    if len(priced) < 2:
        return "There isn't enough comparable published fee data for a fee-based verdict."
    lowest = min(amount for amount, _ in priced)
    winners = [name for amount, name in priced if amount == lowest]
    if len(winners) == 1:
        return f"{winners[0]} has the lowest published fee among these options."
    return "The lowest published fee is tied between " + " and ".join(winners) + "."


def build_comparison_card(
    operands: Iterable[Any],
    catalog: Any = None,
    *,
    title: str = "Comparison",
) -> ComparisonCard | None:
    """Resolve concrete operands and build a side-by-side catalog card."""

    items: list[ComparisonItem] = []
    seen: set[str] = set()
    for operand in operands:
        entity = _resolve_operand(operand, catalog)
        if entity is None:
            continue
        item = _comparison_item(entity, catalog)
        key = (item.id or f"{item.name}\0{item.subtitle or ''}").casefold()
        if key in seen:
            continue
        seen.add(key)
        items.append(item)
        if len(items) >= 3:
            break
    if len(items) < 2:
        return None
    return ComparisonCard(
        title=clean_text(title) or "Comparison",
        items=items,
        verdict=_comparison_verdict(items),
    )


def build_comparison_card_from_text(
    text: str,
    *,
    title: str = "Comparison",
) -> ComparisonCard | None:
    """Build a fallback card from deterministic text (only with no operands)."""

    items = comparison_items_from_text(text)
    if len(items) < 2:
        return None
    return ComparisonCard(
        title=clean_text(title) or "Comparison",
        items=items,
        verdict=_comparison_verdict(items),
    )


def build_lead_cta(cta: CTA | Mapping[str, Any]) -> LeadCTAComponent:
    typed = cta if isinstance(cta, CTA) else CTA.model_validate(cta)
    return LeadCTAComponent(
        label=typed.label,
        action=typed.action,
        url=typed.url,
        payload=typed.payload,
    )


def build_quick_actions(actions: Iterable[Any]) -> QuickActionsComponent | None:
    values: list[QuickAction] = []
    seen: set[str] = set()
    for action in actions:
        rendered = clean_text(action)
        key = rendered.casefold()
        if not rendered or key in seen:
            continue
        seen.add(key)
        values.append(QuickAction(label=rendered, message=rendered))
        if len(values) >= 6:
            break
    return QuickActionsComponent(actions=values) if values else None


__all__ = [
    "build_comparison_card",
    "build_comparison_card_from_text",
    "build_entity_card",
    "build_lead_cta",
    "build_program_card",
    "build_quick_actions",
    "build_university_card",
]
