"""Deterministic ROI scoring using normalized numeric catalog fields only."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from data.accessor import safe_get

from .base import ToolResult, unavailable_result
from .content import ToolDefinition


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    rendered = float(value)
    return rendered if math.isfinite(rendered) else None


def _catalog_entity(catalog: Any, identifier: str) -> Any:
    if catalog is None:
        return None
    for method_name in ("get_entity", "get", "by_id"):
        method = getattr(catalog, method_name, None)
        if callable(method):
            try:
                entity = method(identifier)
            except (KeyError, TypeError, ValueError):
                continue
            if entity is not None:
                return entity
    if isinstance(catalog, Mapping):
        return catalog.get(identifier)
    return None


def _catalog_entities(catalog: Any) -> list[Any]:
    if catalog is None:
        return []
    for method_name in ("list_entities", "all_entities", "values"):
        method = getattr(catalog, method_name, None)
        if callable(method):
            try:
                values = method()
            except TypeError:
                continue
            if values is not None:
                return list(values.values() if isinstance(values, Mapping) else values)
    if isinstance(catalog, Mapping):
        return list(catalog.values())
    values = getattr(catalog, "entities", None)
    if isinstance(values, Mapping):
        return list(values.values())
    return []


def _entity_id(entity: Any) -> str | None:
    value = safe_get(entity, "id", None) or safe_get(entity, "entity_id", None)
    rendered = " ".join(str(value or "").split())
    return rendered or None


def _salary_numeric(entity: Any) -> float | None:
    direct = _number(safe_get(entity, "salary_numeric", None))
    if direct is not None:
        return direct
    salaries = [
        salary
        for profile in (safe_get(entity, "job_profiles", []) or [])
        if (salary := _number(safe_get(profile, "salary_numeric", None))) is not None
    ]
    # Spec: expected salary comes from job_profiles[].avg_salary. A program that
    # lists several roles gets their mean — the honest central estimate.
    return sum(salaries) / len(salaries) if salaries else None


def _current_annual_salary(payload: Mapping[str, Any]) -> float | None:
    values = payload.get("answer_values")
    periods = payload.get("answer_periods")
    if not isinstance(values, Mapping) or not isinstance(periods, Mapping):
        return None
    key = next((name for name in values if str(name).startswith("current_salary")), None)
    if key is None:
        return None
    amount = _number(values.get(key))
    period = periods.get(key)
    if amount is None or amount < 0 or period not in {"monthly", "annual"}:
        return None
    return amount * 12 if period == "monthly" else amount


def _payback_months(fee: float, post_salary: float, current_salary: float) -> int | None:
    delta_salary = post_salary - current_salary
    monthly_delta = delta_salary / 12
    if fee <= 0 or monthly_delta <= 0:
        return None
    return math.ceil(fee / monthly_delta)


def _rank_same_discipline(
    catalog: Any,
    discipline: str,
    current_salary: float,
) -> list[str]:
    ranked: list[tuple[int, str]] = []
    for entity in _catalog_entities(catalog):
        if str(safe_get(entity, "discipline", "")).casefold() != discipline.casefold():
            continue
        entity_id = _entity_id(entity)
        fee = _number(safe_get(entity, "fee_numeric", None))
        salary = _salary_numeric(entity)
        if not entity_id or fee is None or salary is None:
            continue
        payback = _payback_months(fee, salary, current_salary)
        if payback is not None:
            ranked.append((payback, entity_id))
    ranked.sort(key=lambda item: (item[0], item[1]))
    return [entity_id for _, entity_id in ranked[:3]]


def _normalized(value: Any) -> str:
    return "".join(character for character in str(value or "").casefold() if character.isalnum())


def _configured_program(
    answers: Mapping[str, str],
    payload: Mapping[str, Any],
    catalog: Any,
) -> tuple[str | None, Any]:
    contextual_id = str(payload.get("program_id") or "").strip()
    contextual = _catalog_entity(catalog, contextual_id) if contextual_id else None
    if contextual is not None and (
        str(safe_get(contextual, "_meta.page_type", "") or "")
        in {"course", "specialization"}
        or contextual_id.startswith(("course-", "spec-"))
    ):
        return contextual_id, contextual

    values = payload.get("answer_values")
    selected = values.get("program") if isinstance(values, Mapping) else None
    answered = str(answers.get("program") or "").strip()
    # Q1 is an entity step: when the answer already is a catalog id, use it.
    # (Only the prefixed-id branch above is context-derived; this is the user's
    # own selection and must not be dropped for lacking a known id prefix.)
    if answered:
        direct = _catalog_entity(catalog, answered)
        if direct is not None:
            return answered, direct
    target = _normalized(selected or answered)
    candidates: list[tuple[float, str, Any]] = []
    for entity in _catalog_entities(catalog):
        entity_id = _entity_id(entity)
        if not entity_id or not entity_id.startswith("course-"):
            continue
        names = (
            safe_get(entity, "program_name", None),
            safe_get(entity, "course_name", None),
        )
        if target and target not in {_normalized(name) for name in names}:
            continue
        fee = _number(safe_get(entity, "fee_numeric", None))
        candidates.append((fee if fee is not None else math.inf, entity_id, entity))
    if not candidates:
        return None, None
    _, entity_id, entity = min(candidates, key=lambda item: (item[0], item[1]))
    return entity_id, entity


def _rank_same_discipline_by_fee(catalog: Any, discipline: str) -> list[str]:
    ranked: list[tuple[float, str]] = []
    for entity in _catalog_entities(catalog):
        if str(safe_get(entity, "discipline", "")).casefold() != discipline.casefold():
            continue
        entity_id = _entity_id(entity)
        fee = _number(safe_get(entity, "fee_numeric", None))
        if entity_id and fee is not None:
            ranked.append((fee, entity_id))
    ranked.sort(key=lambda item: (item[0], item[1]))
    return [entity_id for _, entity_id in ranked[:3]]


def _answer_value(payload: Mapping[str, Any], step_id: str) -> Any:
    values = payload.get("answer_values")
    return values.get(step_id) if isinstance(values, Mapping) else None


def _current_monthly_salary(payload: Mapping[str, Any]) -> float | None:
    """Q2 bucket midpoint, normalised to a monthly figure."""

    values = payload.get("answer_values")
    periods = payload.get("answer_periods")
    if not isinstance(values, Mapping):
        return None
    key = next((name for name in values if str(name).startswith("current_salary")), None)
    if key is None:
        return None
    amount = _number(values.get(key))
    if amount is None or amount < 0:
        return None
    period = periods.get(key) if isinstance(periods, Mapping) else None
    return amount / 12 if period == "annual" else amount


def _rank_by_roi(catalog: Any, discipline: str, exclude: str | None = None) -> list[str]:
    """Best-ROI programs in the same discipline: lowest fee per rupee of salary."""

    ranked: list[tuple[float, str]] = []
    for entity in _catalog_entities(catalog):
        if str(safe_get(entity, "discipline", "")).casefold() != discipline.casefold():
            continue
        entity_id = _entity_id(entity)
        fee = _number(safe_get(entity, "fee_numeric", None))
        salary = _salary_numeric(entity)
        if not entity_id or entity_id == exclude or fee is None or not salary:
            continue
        ranked.append((fee / salary, entity_id))
    ranked.sort(key=lambda item: (item[0], item[1]))
    return [entity_id for _, entity_id in ranked[:3]]


def _payback_band(months: int) -> str:
    if months <= 12:
        return "excellent — under a year"
    if months <= 18:
        return "strong — around 18 months"
    if months <= 36:
        return f"solid — about {round(months / 12)} years"
    return "longer-term — 3 years+"


def _friendly_payback(months: int) -> str:
    """Spec: round to a friendly figure, cap the display at a sane ceiling."""

    if months > 36:
        return "~3 years+"
    if months <= 12:
        return f"{months} months"
    if months % 12 == 0:
        years = months // 12
        return f"{years} year" if years == 1 else f"{years} years"
    return f"{months} months"


def score_roi(
    answers: Mapping[str, str],
    payload: Mapping[str, Any],
    catalog: Any,
    *,
    definition: ToolDefinition | None = None,
) -> ToolResult:
    """Salary-delta payback using the catalog's own numeric fields.

    expected = (job_profiles avg salary / 12) * experience_factor
    payback  = ceil(fee_numeric / (expected - current_monthly))
    """

    program_id, entity = _configured_program(answers, payload, catalog)
    if entity is None or program_id is None:
        return unavailable_result(
            "roi",
            "No published catalog program matches the selected program option.",
        )

    program_name = str(
        safe_get(entity, "program_name", None)
        or safe_get(entity, "specialization_name", None)
        or safe_get(entity, "spec_name", None)
        or program_id
    )
    fee = _number(safe_get(entity, "fee_numeric", None))
    annual_salary = _salary_numeric(entity)
    current_monthly = _current_monthly_salary(payload)
    discipline = " ".join(str(safe_get(entity, "discipline", "") or "").split())

    # Q4 tempers the expected figure so the number is honest, not rosy.
    factor = 1.0
    if definition is not None:
        experience_step = next(
            (step for step in definition.steps if step.type == "factor"), None
        )
        if experience_step is not None:
            chosen = next(
                (
                    option
                    for option in experience_step.choices
                    if option.id == answers.get(experience_step.id)
                ),
                None,
            )
            if chosen is not None and chosen.factor is not None:
                factor = float(chosen.factor)

    lead_tags: dict[str, Any] = {"tool": "roi", "program_id": program_id}
    # Q6 is a pure lead signal; Q3/Q5 tailor the copy. All reach the CRM.
    for step_id in ("start_intent", "goal", "qualification"):
        chosen_id = answers.get(step_id)
        if chosen_id and definition is not None:
            step = next((s for s in definition.steps if s.id == step_id), None)
            option = (
                next((o for o in step.choices if o.id == chosen_id), None)
                if step is not None
                else None
            )
            if option is not None:
                lead_tags[step_id] = option.label

    # Missing catalog numerics is a content gap, not a computed outcome: report
    # it as unavailable so the reason names the absent fields.
    if fee is None or not annual_salary:
        return unavailable_result(
            "roi",
            "Normalized fee_numeric and salary_numeric data are not available for this program.",
        )
    if current_monthly is None:
        return unavailable_result(
            "roi",
            "The current salary value or its monthly/annual period is not configured.",
        )

    expected_monthly = (annual_salary / 12) * factor
    monthly_delta = expected_monthly - current_monthly

    # Guardrail: already earning above the program's average outcome. Reframe
    # honestly rather than showing a fake payback — this is a real segment.
    if monthly_delta <= 0:
        return ToolResult(
            status="cannot_compute",
            partial={"headline": "Your payback picture is a little different."},
            full={
                "message": (
                    "You're already earning above the average starting salary for this "
                    "program — the value here is the qualification and progression, not "
                    "a salary jump. A counsellor can talk through what it unlocks."
                ),
                "program_id": program_id,
                "program_name": program_name,
                "fee_numeric": fee,
                "expected_monthly_salary": round(expected_monthly),
                "current_monthly_salary": round(current_monthly),
            },
            cta_program_ids=_rank_by_roi(catalog, discipline) if discipline else [program_id],
            lead_tags={**lead_tags, "result_status": "already_above_average"},
        )

    payback = math.ceil(fee / monthly_delta)
    # Spec: the 3 best-ROI programs in the same discipline, ranked by
    # fee/salary. The selected program competes on the same footing rather than
    # being pinned to the front — the point of the list is the better option.
    ranked = _rank_by_roi(catalog, discipline) if discipline else []
    if not ranked:
        ranked = [program_id]

    template = (definition.partial_reveal_template if definition is not None else None) or (
        "Your payback period looks {band}."
    )
    return ToolResult(
        partial={"headline": template.format(band=_payback_band(payback))},
        full={
            "message": (
                f"Program cost ₹{round(fee):,} · Expected uplift ₹{round(monthly_delta):,}/mo · "
                f"Pays back in {_friendly_payback(payback)}"
            ),
            "payback_months": payback,
            "payback_label": _friendly_payback(payback),
            "program_id": program_id,
            "program_name": program_name,
            "fee_numeric": fee,
            "monthly_uplift": round(monthly_delta),
            "expected_monthly_salary": round(expected_monthly),
            "current_monthly_salary": round(current_monthly),
            "experience_factor": factor,
        },
        cta_program_ids=ranked[:3],
        lead_tags={**lead_tags, "payback_months": payback},
    )


__all__ = ["score_roi"]
