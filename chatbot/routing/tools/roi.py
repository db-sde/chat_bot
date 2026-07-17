"""Deterministic ROI scoring using normalized numeric catalog fields only."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from data.accessor import safe_get

from .base import ToolResult, unavailable_result


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
    salaries = {
        salary
        for profile in (safe_get(entity, "job_profiles", []) or [])
        if (salary := _number(safe_get(profile, "salary_numeric", None))) is not None
    }
    # The spec does not define how to aggregate multiple job-profile salaries.
    # Compute only when the normalized data supplies one unambiguous value.
    return next(iter(salaries)) if len(salaries) == 1 else None


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


def score_roi(
    answers: Mapping[str, str],
    payload: Mapping[str, Any],
    catalog: Any,
) -> ToolResult:
    """Compute payback from salary delta; never use gross salary as payback."""

    program_id = answers.get("program")
    if not program_id:
        return unavailable_result("roi", "A catalog program has not been selected.")
    entity = _catalog_entity(catalog, program_id)
    if entity is None:
        return unavailable_result("roi", "The selected program is not in the loaded catalog.")
    fee = _number(safe_get(entity, "fee_numeric", None))
    post_salary = _salary_numeric(entity)
    current_salary = _current_annual_salary(payload)
    if fee is None or post_salary is None:
        return unavailable_result(
            "roi",
            "Normalized fee_numeric and salary_numeric data are not available for this program.",
        )
    if current_salary is None:
        return unavailable_result(
            "roi",
            "The current salary value or its monthly/annual period is not configured.",
        )
    payback = _payback_months(fee, post_salary, current_salary)
    if payback is None:
        return ToolResult(
            status="cannot_compute",
            partial={"message": "A reliable positive salary-delta payback cannot be computed."},
            full={"message": "A reliable positive salary-delta payback cannot be computed."},
            lead_tags={"tool": "roi", "result_status": "cannot_compute"},
            reason=(
                "The expected post-program salary is not higher than the supplied current "
                "salary, or the normalized fee is not positive."
            ),
        )

    discipline = " ".join(str(safe_get(entity, "discipline", "") or "").split())
    ranked_ids = _rank_same_discipline(catalog, discipline, current_salary) if discipline else []
    if not ranked_ids:
        ranked_ids = [program_id]
    return ToolResult(
        partial={"headline": f"Estimated salary-delta payback: {payback} months."},
        full={
            "message": (
                f"Estimated salary-delta payback is {payback} months, using the normalized "
                "program fee and expected annual salary data."
            ),
            "payback_months": payback,
            "fee_numeric": fee,
            "current_salary_annual": current_salary,
            "expected_post_program_salary_annual": post_salary,
        },
        cta_program_ids=ranked_ids,
        lead_tags={"tool": "roi", "payback_months": payback},
    )


__all__ = ["score_roi"]
