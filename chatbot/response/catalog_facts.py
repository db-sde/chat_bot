"""Structured Catalog V3 fact projections used by guided cards."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from data.accessor import safe_get
from response.cards import clean_text, first_value, has_value, related_specialization_names


def _values(value: Any, *fields: str, limit: int = 8) -> list[str]:
    items = value if isinstance(value, Iterable) and not isinstance(value, (str, bytes, Mapping)) else [value]
    result: list[str] = []
    for item in items:
        rendered = clean_text(item if isinstance(item, (str, int, float)) else first_value(item, *fields, default=None))
        if rendered and rendered not in result:
            result.append(rendered)
        if len(result) >= limit:
            break
    return result


def _nested_lines(
    value: Any,
    *,
    field_groups: tuple[tuple[str, ...], ...],
    limit: int = 6,
) -> list[str]:
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
                clean_text(first_value(item, *fields, default=None))
                for fields in field_groups
            ]
            rendered = " — ".join(part for part in parts if part)
        if rendered and rendered.casefold() not in {line.casefold() for line in result}:
            result.append(rendered)
        if len(result) >= limit:
            break
    return result


def accreditation_items(entity: Any) -> list[str]:
    details: list[str] = []
    naac = clean_text(safe_get(entity, "naac_grade", None))
    ugc = clean_text(first_value(entity, "ugc_status", "ugc_approved", default=None))
    structured_types: set[str] = set()
    for item in safe_get(entity, "accreditations", None) or []:
        accreditation_type = clean_text(first_value(item, "type", default=None))
        accreditation_value = clean_text(first_value(item, "value", default=None))
        if accreditation_type:
            structured_types.add(accreditation_type.casefold())
            if accreditation_type.casefold() == "naac" and naac:
                accreditation_value = " ".join(
                    value
                    for value in (accreditation_value, f"(NAAC grade {naac})")
                    if value
                )
            details.append(
                " — ".join(
                    value for value in (accreditation_type, accreditation_value) if value
                )
            )
            continue
        details.extend(
            _nested_lines(
                item,
                field_groups=(
                    ("body_name", "name", "title"),
                    ("body_descriptor", "descriptor", "status"),
                    ("body_detail", "detail", "description"),
                ),
                limit=1,
            )
        )
    if naac and "naac" not in structured_types:
        details.insert(0, f"NAAC grade {naac}")
    if ugc and ugc.casefold() not in {"true", "false"} and "ugc" not in structured_types:
        details.insert(0, ugc)
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
    result: list[str] = []
    rank = safe_get(entity, "nirf_rank", None)
    if isinstance(rank, int) and rank > 0:
        result.append(f"NIRF rank {rank}")
    result.extend(_values(safe_get(entity, "rankings", []), "name", "title", "value", limit=6))
    return list(dict.fromkeys(result))[:6]


def specialization_items(entity: Any, catalog: Any = None) -> list[str]:
    result = related_specialization_names(entity, catalog, limit=8)
    result.extend(
        _values(
            safe_get(entity, "specializations", []),
            "specialization_name",
            "spec_name",
            "name",
            "title",
            limit=8,
        )
    )
    return list(dict.fromkeys(result))[:8]


def career_items(entity: Any) -> list[str]:
    result: list[str] = []
    for profile in safe_get(entity, "job_profiles", []) or []:
        title = clean_text(safe_get(profile, "job_title", None))
        salary = clean_text(first_value(profile, "avg_salary", "salary_display", default=None))
        if title:
            result.append(f"{title} ({salary})" if salary else title)
    result.extend(
        _values(
            safe_get(entity, "career_outcomes", []),
            "job_title",
            "role",
            "name",
            "title",
            limit=4,
        )
    )
    return list(dict.fromkeys(result))[:4]


__all__ = ["accreditation_items", "career_items", "ranking_items", "specialization_items"]
