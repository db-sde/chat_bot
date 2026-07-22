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
    target = _normalized(selected or answers.get("program"))
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


def score_roi(
    answers: Mapping[str, str],
    payload: Mapping[str, Any],
    catalog: Any,
    *,
    definition: ToolDefinition | None = None,
) -> ToolResult:
    """Use configured v1 buckets when present, otherwise normalized salary delta."""

    if definition is not None and definition.roi_buckets:
        salary_answer = answers.get("current_salary")
        bucket = next(
            (
                candidate
                for candidate in definition.roi_buckets
                if candidate.option_id == salary_answer
            ),
            None,
        )
        if bucket is None:
            return unavailable_result("roi", "A configured salary band has not been selected.")
        program_id, entity = _configured_program(answers, payload, catalog)
        if entity is None or program_id is None:
            return unavailable_result(
                "roi",
                "No published catalog program matches the selected program option.",
            )
        fee = _number(safe_get(entity, "fee_numeric", None))
        discipline = " ".join(str(safe_get(entity, "discipline", "") or "").split())
        ranked_ids = _rank_same_discipline_by_fee(catalog, discipline) if discipline else []
        if program_id not in ranked_ids:
            ranked_ids.insert(0, program_id)
        program_name = str(
            safe_get(entity, "program_name", None)
            or safe_get(entity, "spec_name", None)
            or program_id
        )
        message = (
            f"Using the approved v1 salary-band model, the estimated payback for "
            f"{program_name} is {bucket.payback_months} months."
        )
        return ToolResult(
            partial={"headline": bucket.headline},
            full={
                "message": message,
                "payback_months": bucket.payback_months,
                "program_id": program_id,
                "program_name": program_name,
                **({"fee_numeric": fee} if fee is not None else {}),
            },
            cta_program_ids=ranked_ids[:3],
            lead_tags={
                "tool": "roi",
                "payback_months": bucket.payback_months,
                "model": "v1_salary_band",
            },
        )

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
