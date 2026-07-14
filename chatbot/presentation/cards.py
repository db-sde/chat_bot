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
)
from response.templates import (
    accreditation_items,
    career_items,
    ranking_items,
    specialization_items,
)
from schemas import (
    CTA,
    CardFact,
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
    highlights = unique_facts(
        (
            card_fact("Established", safe_get(entity, "established_year", None)),
            card_fact(
                "Learning mode",
                first_value(entity, "mode_of_learning", "mode", default=None),
            ),
            card_fact("Starting fee", first_value(entity, "starting_fee", default=None)),
            card_fact("NAAC grade", safe_get(entity, "naac_grade", None)),
            card_fact(
                "UGC status",
                first_value(entity, "ugc_approved", "ugc_status", default=None),
            ),
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
        highlights=highlights,
        programs=programs,
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
        eligibility=optional_text(
            first_value(
                entity,
                "eligibility_summary",
                "eligibility_content",
                default=None,
            ),
            max_chars=320,
        ),
        mode=optional_text(first_value(entity, "mode", "mode_of_learning", default=None)),
        specializations=specialization_items(entity, catalog),
        career_outcomes=career_items(entity),
        highlights=highlights,
        details_url=_details_url(entity),
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
    program_count = len(
        catalog_strings(
            safe_get(entity, "programs_table", None),
            fields=("program_name", "name", "title"),
            limit=8,
        )
    )
    specializations = specialization_items(entity, catalog)
    approvals = accreditation_items(entity)
    rankings = ranking_items(entity)
    careers = career_items(entity)
    placement = optional_text(
        first_value(
            entity,
            "placement_content",
            "placement_support",
            "placements_content",
            default=None,
        ),
        max_chars=240,
    )
    facts = unique_facts(
        (
            card_fact("Fee", entity_fee(entity)),
            card_fact("Duration", safe_get(entity, "duration", None)),
            card_fact("Mode", first_value(entity, "mode", "mode_of_learning", default=None)),
            card_fact(
                "Eligibility",
                first_value(
                    entity,
                    "eligibility_summary",
                    "eligibility_content",
                    default=None,
                ),
            ),
            card_fact("Programs", str(program_count) if program_count else None),
            card_fact("Specializations", ", ".join(specializations[:5])),
            card_fact("Approvals", "; ".join(approvals[:3])),
            card_fact("Rankings", "; ".join(rankings[:2])),
            card_fact("Placement support", placement),
            card_fact("Career outcomes", ", ".join(careers[:4])),
        ),
        limit=8,
    )
    return ComparisonItem(
        id=_identifier(entity),
        name=_card_name(entity, "Catalog option"),
        subtitle=provider if page_type != "university" and provider else None,
        facts=facts,
    )


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
    return ComparisonCard(title=clean_text(title) or "Comparison", items=items)


def build_comparison_card_from_text(
    text: str,
    *,
    title: str = "Comparison",
) -> ComparisonCard | None:
    """Build a fallback card from deterministic text (only with no operands)."""

    items = comparison_items_from_text(text)
    if len(items) < 2:
        return None
    return ComparisonCard(title=clean_text(title) or "Comparison", items=items)


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
