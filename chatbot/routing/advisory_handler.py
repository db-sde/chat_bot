"""Bounded advisory flow: collect one preference before recommending."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from advisor.flow import handle_advisor_turn, is_personal_advisor_request
from data.accessor import safe_get
from response.builder import build_response
from response.cards import (
    catalog_get_entity,
    clean_text,
    entity_fee,
    entity_label,
    entity_page_type,
    entity_university,
    first_value,
    format_inr,
    iter_catalog_entities,
    parse_money,
)
from schemas import ResponsePayload

from .category_handler import (
    available_categories,
    category_summary,
    display_category,
    entities_for_category,
)

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
_SALARY_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def parse_budget(message: str) -> float | None:
    """Parse a user-stated INR ceiling without treating years as a budget."""

    text = str(message or "").replace("\u00a0", " ")
    lakh_match = _LAKH_AMOUNT_RE.search(text)
    if lakh_match:
        try:
            return float(lakh_match.group(1)) * 100_000
        except ValueError:
            return None

    for pattern in (_CURRENCY_AMOUNT_RE, _CONTEXT_BUDGET_RE, _GROUPED_OR_LARGE_AMOUNT_RE):
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


def advisory_preference(message: str) -> str | None:
    """Return a bounded, response-level preference already stated by the user."""

    text = message.casefold()
    if any(marker in text for marker in ("accredit", "naac", "recognition")) and any(
        marker in text for marker in ("fee", "cost", "affordable", "reasonable")
    ):
        return "accreditation_fees"
    if any(
        marker in text
        for marker in (
            "fee",
            "budget",
            "affordable",
            "reasonable cost",
            "lower cost",
            "lowest cost",
            "lowest fee",
            "cheapest",
            "under ",
            "below ",
            "within ",
            "up to ",
        )
    ):
        return "fees"
    if any(marker in text for marker in ("ranking", "ranked", "top ")):
        return "rankings"
    if any(marker in text for marker in ("placement", "career support", "hiring", "recruit")):
        return "placements"
    if any(
        marker in text
        for marker in (
            "career opportunity",
            "career opportunities",
            "career outcome",
            "career data",
            "salary",
            "job",
            "role",
            "package",
            "earning",
        )
    ):
        return "careers"
    if any(marker in text for marker in ("specialization", "specialisation")):
        return "specialization"
    if any(marker in text for marker in ("business", "management", "leadership")):
        return "business"
    if any(marker in text for marker in ("technology", "tech", "software", "computer")):
        return "technology"
    return None


def _published_total_fee(entity: Any) -> str:
    total = clean_text(safe_get(entity, "total_fee", None))
    if total:
        return total
    plans = safe_get(entity, "fee_plans", []) or []
    for plan in plans if isinstance(plans, (list, tuple)) else []:
        total = clean_text(safe_get(plan, "plan_total", None))
        if total:
            return total
    return ""


def _fee_options(
    entities: Sequence[Any],
    *,
    max_budget: float | None = None,
    limit: int = 3,
) -> list[str]:
    best_by_provider: dict[str, tuple[float, str, str]] = {}
    for entity in entities:
        # A ceiling must be compared with a published total, never a per-term
        # starting amount. For an unbounded fee shortlist, the existing comparable
        # fee helper can still use the best available publisher field.
        fee = _published_total_fee(entity) if max_budget is not None else entity_fee(entity)
        amount = parse_money(fee)
        university = entity_university(entity) or entity_label(entity)
        if amount is None or not university:
            continue
        if max_budget is not None and amount > max_budget:
            continue
        key = university.casefold()
        current = best_by_provider.get(key)
        if current is None or amount < current[0]:
            best_by_provider[key] = (amount, university, fee)
    ranked = sorted(best_by_provider.values(), key=lambda item: (item[0], item[1].casefold()))
    return [f"{university} ({fee})" for _, university, fee in ranked[:limit]]


def _lowest_fee_options(
    category: str,
    category_index: Any,
    catalog: Any,
    *,
    max_budget: float | None = None,
    limit: int = 3,
) -> list[str]:
    return _fee_options(
        entities_for_category(category, category_index, catalog),
        max_budget=max_budget,
        limit=limit,
    )


def _placement_options(category: str, category_index: Any, catalog: Any) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()
    for entity in entities_for_category(category, category_index, catalog):
        has_published_support = bool(
            safe_get(entity, "placement_content") or safe_get(entity, "job_profiles")
        )
        university = entity_university(entity) or entity_label(entity)
        if has_published_support and university and university.casefold() not in seen:
            seen.add(university.casefold())
            labels.append(university)
    return labels[:4]


def _category_from_message(message: str, category_index: Any, catalog: Any) -> str | None:
    text = str(message or "").casefold()
    for category in sorted(
        available_categories(category_index, catalog), key=lambda item: len(str(item)), reverse=True
    ):
        value = str(category).strip().casefold()
        if value and re.search(rf"(?<!\w){re.escape(value)}(?!\w)", text):
            return str(category)
    return None


def _candidate_entities(catalog: Any, references: Sequence[Any] | None) -> list[Any]:
    if not references or isinstance(references, (str, bytes)):
        return []
    entities: list[Any] = []
    seen: set[str] = set()
    for item in references:
        reference = first_value(item, "entity_id", "id", "slug", default=item)
        entity = catalog_get_entity(catalog, reference)
        if entity is None and not isinstance(item, (str, int)):
            entity = item
        if entity is None:
            continue
        identity = str(
            first_value(entity, "id", "entity_id", "slug", default=entity_label(entity))
        ).casefold()
        if identity in seen:
            continue
        seen.add(identity)
        entities.append(entity)
    return entities


def _same_specialization(entities: Sequence[Any]) -> str | None:
    if len(entities) < 2:
        return None
    if any(entity_page_type(entity) != "specialization" for entity in entities):
        return None
    names = {
        clean_text(
            first_value(entity, "specialization_name", "spec_name", default=None)
        ).casefold()
        for entity in entities
    }
    if len(names) != 1:
        return None
    name = next(iter(names), "")
    if not name:
        return None
    return clean_text(
        first_value(entities[0], "specialization_name", "spec_name", default=None)
    )


def _salary_amount(value: Any) -> float | None:
    text = clean_text(value).casefold()
    match = _SALARY_NUMBER_RE.search(text)
    if not match:
        return None
    try:
        amount = float(match.group(0).replace(",", ""))
    except ValueError:
        return None
    if "lpa" in text or "lakh" in text or "lac" in text:
        return amount * 100_000
    if re.search(r"\b(?:k|thousand)\b", text):
        return amount * 1_000
    return amount


def _career_rows(entities: Sequence[Any]) -> list[tuple[float, str]]:
    rows: list[tuple[float, str]] = []
    for entity in entities:
        if entity_page_type(entity) != "specialization":
            continue
        profiles = safe_get(entity, "job_profiles", []) or []
        if not isinstance(profiles, (list, tuple)):
            continue
        best: tuple[float, str, str] | None = None
        for profile in profiles:
            salary = clean_text(safe_get(profile, "avg_salary", None))
            amount = _salary_amount(salary)
            if amount is None:
                continue
            title = clean_text(safe_get(profile, "job_title", None)) or "published role"
            if best is None or amount > best[0]:
                best = (amount, title, salary)
        if best is None:
            continue
        specialization = clean_text(
            first_value(entity, "specialization_name", "spec_name", default=entity_label(entity))
        )
        university = entity_university(entity)
        label = f"{specialization} at {university}" if university else specialization
        rows.append((best[0], f"{label} — {best[1]} ({best[2]})"))
    return sorted(rows, key=lambda item: (-item[0], item[1].casefold()))


def _career_response(entities: Sequence[Any], *, category: str | None = None) -> ResponsePayload:
    rows = _career_rows(entities)
    label = display_category(category) if category else "specialization"
    if not rows:
        return build_response(
            f"I couldn't produce a grounded {label} career ranking because the current "
            "catalog does not publish comparable average-salary figures for these options.",
            suggested_chips=["Compare fees", "Explore specializations"],
        )
    lines = [f"{index}. {text}" for index, (_, text) in enumerate(rows[:6], start=1)]
    return build_response(
        "Using only published average-salary figures in the catalog, the available "
        f"{label} data ranks as:\n" + "\n".join(lines) + "\n"
        "This compares only records with published figures; it is not a placement "
        "guarantee, and missing data is not treated as a lower result.",
        suggested_chips=["Compare fees", "Placement support", "Explore specializations"],
    )


_NAAC_RANK = {
    "A++": 8,
    "A+": 7,
    "A": 6,
    "B++": 5,
    "B+": 4,
    "B": 3,
    "C": 2,
    "D": 1,
}


def _accreditation_fee_response(catalog: Any) -> ResponsePayload:
    rows: list[tuple[int, float, str, str, str]] = []
    for entity in iter_catalog_entities(catalog):
        if entity_page_type(entity) != "university":
            continue
        grade = clean_text(safe_get(entity, "naac_grade", None)).upper()
        rank = _NAAC_RANK.get(grade)
        fee = clean_text(safe_get(entity, "starting_fee", None))
        amount = parse_money(fee)
        university = entity_label(entity)
        if rank is None or amount is None or not university:
            continue
        rows.append((rank, amount, university, grade, fee))

    if not rows:
        return build_response(
            "I couldn't find universities with both a published NAAC grade and "
            "comparable fee data in the current catalog.",
            suggested_chips=["Explore universities", "Compare course fees"],
        )

    highest = max(row[0] for row in rows)
    selected = sorted(
        (row for row in rows if row[0] == highest),
        key=lambda row: (row[1], row[2].casefold()),
    )
    grade = selected[0][3]
    options = ", ".join(f"{row[2]} ({row[4]})" for row in selected[:5])
    return build_response(
        f"The highest published NAAC grade in the current catalog is {grade}. "
        f"Universities with that grade, ordered by published starting fee, are: {options}. "
        "Starting fees may use different per-semester schedules, so compare the total "
        "program fee before deciding.",
        suggested_chips=["Compare course fees", "Check accreditations"],
    )


def _ranking_response(
    category: str | None,
    category_index: Any,
    catalog: Any,
) -> ResponsePayload:
    """Use publisher rankings when present and never manufacture a 'top' list."""

    entities = (
        entities_for_category(category, category_index, catalog)
        if category
        else iter_catalog_entities(catalog)
    )
    rows: list[str] = []
    seen: set[str] = set()
    for entity in entities:
        university = entity_university(entity) or entity_label(entity)
        ranking = first_value(
            entity,
            "ranking",
            "rank",
            "nirf_rank",
            "ranking_content",
            default=None,
        )
        rankings = safe_get(entity, "rankings", None)
        if ranking is None and rankings:
            ranking = rankings
        rendered = clean_text(ranking, max_chars=180)
        key = university.casefold()
        if university and rendered and key not in seen:
            seen.add(key)
            rows.append(f"• **{university}:** {rendered}")
    label = display_category(category) if category else "program"
    if not rows:
        return build_response(
            f"## Top {label} programs\n\n"
            "The current catalog does not publish comparable ranking data, so I won't "
            "invent a top order. I can compare the published fees, accreditations, or "
            "placement support instead.",
            suggested_chips=[
                f"Cheapest {label}",
                f"Compare {label} accreditations",
                f"{label} placement support",
            ],
        )
    return build_response(
        f"## Published {label} rankings\n\n" + "\n".join(rows[:6]),
        suggested_chips=[f"Compare {label} fees", f"{label} eligibility"],
    )


def _fee_response(
    label: str,
    entities: Sequence[Any],
    *,
    budget: float | None,
) -> ResponsePayload:
    options = _fee_options(entities, max_budget=budget, limit=5 if budget is not None else 3)
    if budget is not None:
        formatted_budget = format_inr(budget)
        if not options:
            return build_response(
                f"I couldn't find any published {label} option with a total fee at or below "
                f"{formatted_budget} in the current catalog.",
                suggested_chips=[f"Show lowest-fee {label}", "Try another budget"],
            )
        return build_response(
            f"Within a published total-fee budget of {formatted_budget}, the {label} "
            f"options I found are {', '.join(options)}. I filtered out options above "
            "that ceiling; please confirm the final fee schedule before applying.",
            suggested_chips=[f"Compare {label} options", f"{label} eligibility"],
        )
    if options:
        return build_response(
            f"Based only on the currently published fees, the lower-cost {label} "
            f"options I found are {', '.join(options)}. Please compare the full fee "
            "schedule before applying.",
            suggested_chips=[f"Compare {label} options", f"{label} eligibility"],
        )
    return build_response(
        f"I couldn't find comparable published fee data for the {label} options.",
        suggested_chips=["Try another priority", "Explore programs"],
    )


def _specialization_shortlist(
    specialization: str,
    entities: Sequence[Any],
) -> ResponsePayload:
    fee_labels = _fee_options(entities, limit=6)
    if fee_labels:
        rendered = ", ".join(fee_labels)
    else:
        providers = [entity_university(entity) for entity in entities]
        rendered = ", ".join(dict.fromkeys(provider for provider in providers if provider))
    return build_response(
        f"I found {len(entities)} published {specialization} options: {rendered}. "
        "I can't identify one as best without a priority. What matters most: lower fees, "
        "published career data, or accreditation?",
        suggested_chips=["Lower fees", "Published career data", "Accreditation"],
    )


async def handle_advisory(
    state: Any = None,
    message: str = "",
    catalog: Any = None,
    category_index: Any = None,
    *,
    llm: Any = None,
    candidate_ids: Sequence[Any] | None = None,
    advisory_candidate_ids: Sequence[Any] | None = None,
    candidates: Sequence[Any] | None = None,
    mentions: Any = None,
    **_: Any,
) -> ResponsePayload:
    """Ask exactly one bounded preference question; do not invent a ranking."""

    del llm
    focus = getattr(state, "focus", None)
    category = getattr(focus, "category", None) or _category_from_message(
        message, category_index, catalog
    )
    category = str(category) if category else None
    preference = advisory_preference(message)

    # Guided mode is opt-in and persisted separately from academic focus. Direct
    # analytical queries (fee/ranking/NAAC) still use the established shortlist
    # path when lightweight handler tests provide a state without AdvisorState.
    if hasattr(state, "advisor") and is_personal_advisor_request(message):
        return handle_advisor_turn(
            state,
            message,
            catalog,
            mentions=mentions,
            category=category,
            start=True,
        )

    budget = parse_budget(message) if preference == "fees" else None
    references = advisory_candidate_ids or candidate_ids or candidates
    shortlisted = _candidate_entities(catalog, references)

    if preference == "accreditation_fees":
        return _accreditation_fee_response(catalog)

    if preference == "rankings":
        return _ranking_response(category, category_index, catalog)

    if preference == "careers":
        if shortlisted:
            career_entities = shortlisted
        elif category:
            career_entities = entities_for_category(category, category_index, catalog)
        else:
            career_entities = iter_catalog_entities(catalog)
        return _career_response(career_entities, category=category)

    specialization = _same_specialization(shortlisted)
    if specialization:
        if preference == "fees":
            return _fee_response(specialization, shortlisted, budget=budget)
        return _specialization_shortlist(specialization, shortlisted)

    if category:
        label = display_category(category)
        if preference == "fees":
            return _fee_response(
                label,
                entities_for_category(category, category_index, catalog),
                budget=budget,
            )
        if preference == "placements":
            options = _placement_options(category, category_index, catalog)
            if options:
                return build_response(
                    f"For {label}, these universities publish placement or career-support "
                    f"details: {', '.join(options)}. This is not a ranking or placement guarantee.",
                    suggested_chips=[f"{label} fees", f"Compare {label} options"],
                )
        if preference == "specialization":
            names: list[str] = []
            seen: set[str] = set()
            for entity in entities_for_category(category, category_index, catalog):
                if entity_page_type(entity) != "specialization":
                    continue
                name = clean_text(
                    first_value(
                        entity,
                        "specialization_name",
                        "spec_name",
                        default="",
                    )
                )
                key = name.casefold()
                if name and key not in seen:
                    seen.add(key)
                    names.append(name)
            names.sort(key=str.casefold)
            return build_response(
                f"Which {label} specialization fits your goal?",
                suggested_chips=names[:6] or ["Browse specializations"],
            )
        text = (
            f"I can narrow the published {label} options for you. "
            "What matters most: lower fees, a preferred specialization, or placement support?"
        )
        chips = ["Lower fees", "Preferred specialization", "Placement support"]
    else:
        if preference in {"business", "technology"}:
            labels = [
                display_category(item)
                for item in available_categories(category_index, catalog)[:6]
            ]
            if labels:
                return build_response(
                    "I can use that direction to compare published options, but the catalog "
                    "doesn't define a universal business-or-technology mapping. Which course "
                    f"category should I evaluate: {', '.join(labels)}?",
                    suggested_chips=labels,
                )
        if preference == "fees":
            ranked_categories: list[tuple[float, str]] = []
            for item in available_categories(category_index, catalog):
                summary = category_summary(item, category_index, catalog)
                if summary["fee_min"] is not None:
                    ranked_categories.append((summary["fee_min"], display_category(item)))
            if ranked_categories:
                _, label = min(ranked_categories)
                known_labels = [
                    display_category(item)
                    for item in available_categories(category_index, catalog)[:2]
                ]
                compare_chip = (
                    f"Compare {known_labels[0]} and {known_labels[1]}"
                    if len(known_labels) == 2
                    else "Compare course categories"
                )
                return build_response(
                    f"From comparable published starting totals, {label} currently has the "
                    "lowest entry point among the catalog categories. Fee schedules differ, "
                    "so treat this as a shortlist signal rather than a final price.",
                    suggested_chips=[f"Explore {label}", compare_chip],
                )
        text = (
            "I can narrow the catalog with one preference. Which direction is closer to "
            "your goal: business and management, or technology and software?"
        )
        chips = ["Business and management", "Technology and software", "Lower fees"]
    return build_response(text, suggested_chips=chips)


handle = handle_advisory

__all__ = ["advisory_preference", "handle", "handle_advisory", "parse_budget"]
