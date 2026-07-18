"""Small, deterministic presentation helpers for catalog entities.

This module deliberately keeps entity access behind :func:`safe_get`.  Catalog and
index objects are infrastructure objects, so their public methods/mappings can be
inspected normally; values returned from them are always treated as entity data.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from html import unescape
from typing import Any

from data.accessor import safe_get

_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")
_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def has_value(value: Any) -> bool:
    """Return whether a catalog value is useful for an answer."""

    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip()) and value.strip().lower() not in {"null", "none", "n/a"}
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def first_value(entity: Any, *paths: str, default: Any = None) -> Any:
    """Return the first populated entity field from ``paths``."""

    for path in paths:
        value = safe_get(entity, path, None)
        if has_value(value):
            return value
    return default


def clean_text(value: Any, *, max_chars: int | None = None) -> str:
    """Convert stored rich text into compact chat-safe plain text."""

    if not has_value(value):
        return ""
    text = unescape(_TAG_RE.sub(" ", str(value)))
    text = _SPACE_RE.sub(" ", text).strip()
    if max_chars and len(text) > max_chars:
        shortened = text[: max_chars - 1].rsplit(" ", 1)[0].rstrip(" ,;:")
        return f"{shortened}…"
    return text


def entity_label(entity: Any, default: str = "this program") -> str:
    """Get the most specific human-readable name for an entity."""

    page_type = entity_page_type(entity)
    paths = {
        "university": ("university_full_name", "university_name", "name"),
        "course": ("program_name", "name"),
        "specialization": ("specialization_name", "spec_name", "name"),
    }.get(
        page_type,
        (
            "specialization_name",
            "spec_name",
            "program_name",
            "university_name",
            "university_full_name",
            "name",
        ),
    )
    value = first_value(entity, *paths, default=default)
    return clean_text(value) or default


def entity_university(entity: Any) -> str:
    return clean_text(first_value(entity, "university_name", "university_full_name", default=""))


def entity_page_type(entity: Any) -> str:
    value = first_value(entity, "_meta.page_type", "page_type", default="")
    rendered = str(value).strip().lower()
    if rendered:
        return rendered
    category = clean_text(safe_get(entity, "category", None)).casefold()
    if category == "university" or has_value(safe_get(entity, "university_full_name", None)):
        return "university"
    if category == "specialization" or has_value(
        safe_get(entity, "specialization_name", None)
    ):
        return "specialization"
    if has_value(safe_get(entity, "program_name", None)):
        return "course"
    return ""


def entity_heading(entity: Any) -> str:
    """Return a compact, self-contained heading for a publisher record."""

    label = entity_label(entity)
    page_type = entity_page_type(entity)
    if page_type == "university":
        return label

    provider = entity_university(entity)
    program = clean_text(first_value(entity, "program_name", "parent_course", default=None))

    parts: list[str] = []
    for value in (
        provider,
        program if page_type == "specialization" else "",
        label,
    ):
        if not value:
            continue
        normalized = value.casefold()
        if any(normalized == part.casefold() for part in parts):
            continue
        if (
            page_type == "specialization"
            and program
            and value == program
            and program.casefold() in label.casefold()
        ):
            continue
        parts.append(value)
    return " ".join(parts) or label


def render_sections(
    title: str,
    sections: Iterable[tuple[str, Iterable[Any]]],
    *,
    intro: str | None = None,
) -> str:
    """Render compact chat-safe headings and bullets without changing the API schema."""

    blocks = [clean_text(title)]
    if intro and (cleaned_intro := clean_text(intro)):
        blocks.append(cleaned_intro)
    for heading, values in sections:
        items: list[str] = []
        seen: set[str] = set()
        for value in values:
            cleaned = clean_text(value)
            key = cleaned.casefold()
            if not cleaned or key in seen:
                continue
            seen.add(key)
            items.append(cleaned)
        if items:
            blocks.append(f"{clean_text(heading)}:\n" + "\n".join(f"• {item}" for item in items))
    return "\n\n".join(block for block in blocks if block)


def entity_fee(entity: Any) -> str:
    """Return the most comparable published fee field for an entity."""

    value = first_value(entity, "total_fee", "starting_fee", default=None)
    if has_value(value):
        return clean_text(value)

    numeric = first_value(
        entity,
        "total_fee_numeric",
        "starting_fee_numeric",
        "fee_numeric",
        default=None,
    )
    if isinstance(numeric, (int, float)) and not isinstance(numeric, bool):
        return format_inr(float(numeric))

    plans = safe_get(entity, "fee_plans", []) or []
    if isinstance(plans, Iterable) and not isinstance(plans, (str, bytes, Mapping)):
        for plan in plans:
            value = first_value(plan, "plan_total", "plan_amount", default=None)
            if has_value(value):
                return clean_text(value)

    programs = safe_get(entity, "programs_table", []) or []
    if isinstance(programs, Iterable) and not isinstance(programs, (str, bytes, Mapping)):
        for program in programs:
            value = safe_get(program, "program_fee", None)
            if has_value(value):
                return clean_text(value)
    return ""


def parse_money(value: Any) -> float | None:
    """Extract the first numeric amount without changing the stored representation."""

    if not has_value(value):
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    match = _NUMBER_RE.search(str(value))
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


def format_inr(value: float) -> str:
    """Format a numeric amount using Indian digit grouping."""

    rounded = round(value)
    sign = "-" if rounded < 0 else ""
    digits = str(abs(rounded))
    if len(digits) <= 3:
        grouped = digits
    else:
        tail = digits[-3:]
        head = digits[:-3]
        pairs: list[str] = []
        while head:
            pairs.append(head[-2:])
            head = head[:-2]
        grouped = f"{','.join(reversed(pairs))},{tail}"
    return f"{sign}INR {grouped}"


def unwrap_catalog_record(record: Any) -> Any:
    """Unwrap common catalog-record containers without directly reading entity data."""

    if record is None:
        return None
    for path in ("data", "entity", "payload", "envelope", "document"):
        candidate = safe_get(record, path, None)
        if has_value(candidate):
            return candidate
    return record


def catalog_get_entity(catalog: Any, entity_id: Any) -> Any:
    """Fetch an entity from one of the lightweight CatalogStore API variants."""

    if entity_id is None:
        return None
    if not isinstance(entity_id, (str, int)):
        return unwrap_catalog_record(entity_id)
    if catalog is None:
        return None

    for method_name in ("get_entity", "get", "by_id", "load_entity"):
        method = getattr(catalog, method_name, None)
        if callable(method):
            try:
                result = method(str(entity_id))
            except (KeyError, TypeError, ValueError):
                continue
            if result is not None:
                return unwrap_catalog_record(result)

    if isinstance(catalog, Mapping):
        return unwrap_catalog_record(catalog.get(entity_id) or catalog.get(str(entity_id)))

    for attr_name in ("entities", "records", "items_by_id", "_entities"):
        container = getattr(catalog, attr_name, None)
        if isinstance(container, Mapping):
            result = container.get(entity_id) or container.get(str(entity_id))
            if result is not None:
                return unwrap_catalog_record(result)
    return None


def iter_catalog_entities(catalog: Any) -> list[Any]:
    """Return a snapshot of all in-memory entities exposed by a catalog."""

    if catalog is None:
        return []

    for method_name in ("all_entities", "list_entities", "all", "values"):
        method = getattr(catalog, method_name, None)
        if callable(method):
            try:
                result = method()
            except TypeError:
                continue
            if isinstance(result, Mapping):
                result = result.values()
            if result is not None and not isinstance(result, (str, bytes)):
                try:
                    return [unwrap_catalog_record(item) for item in result]
                except TypeError:
                    pass

    if isinstance(catalog, Mapping):
        return [unwrap_catalog_record(item) for item in catalog.values()]

    for attr_name in ("entities", "records", "items_by_id", "_entities"):
        container = getattr(catalog, attr_name, None)
        if isinstance(container, Mapping):
            return [unwrap_catalog_record(item) for item in container.values()]
        if container is not None and not isinstance(container, (str, bytes)):
            try:
                return [unwrap_catalog_record(item) for item in container]
            except TypeError:
                continue
    return []


def find_catalog_entity(catalog: Any, reference: Any) -> Any:
    """Resolve an id, slug, or exact display name against the in-memory catalog."""

    if reference is None:
        return None
    entity = catalog_get_entity(catalog, reference)
    if entity is not None:
        return entity

    target = _SPACE_RE.sub(" ", str(reference).strip().lower())
    if not target:
        return None
    for candidate in iter_catalog_entities(catalog):
        values = (
            first_value(candidate, "id", "entity_id", default=""),
            safe_get(candidate, "slug", ""),
            entity_label(candidate, default=""),
            entity_university(candidate),
        )
        if any(
            _SPACE_RE.sub(" ", str(value).strip().lower()) == target for value in values if value
        ):
            return candidate
    return None


def related_specialization_names(
    entity: Any,
    catalog: Any,
    *,
    limit: int = 8,
) -> list[str]:
    """Find specialization labels related by publisher links/provider/category."""

    result: list[str] = []
    seen: set[str] = set()

    def add(value: Any) -> None:
        label = clean_text(value)
        key = label.casefold()
        if label and key not in seen:
            seen.add(key)
            result.append(label)

    current_label = clean_text(
        first_value(entity, "specialization_name", "spec_name", default=None)
    )
    current_id = clean_text(first_value(entity, "id", "entity_id", "slug", default=None))
    current_course = first_value(entity, "linked_course.id", "linked_course", default=None)
    if isinstance(current_course, Mapping):
        current_course = first_value(current_course, "id", "entity_id", "slug", default=None)
    current_course = clean_text(current_course)
    provider = entity_university(entity).casefold()
    category = clean_text(
        first_value(entity, "program_name", "parent_course", "category", default=None)
    ).casefold()
    page_type = entity_page_type(entity)

    other_specs = safe_get(entity, "other_specs", []) or []
    if isinstance(other_specs, Iterable) and not isinstance(other_specs, (str, bytes, Mapping)):
        for item in other_specs:
            add(first_value(item, "other_spec_name", "specialization_name", "name", default=None))

    for candidate in iter_catalog_entities(catalog):
        if entity_page_type(candidate) != "specialization":
            continue
        candidate_label = clean_text(
            first_value(candidate, "specialization_name", "spec_name", default=None)
        )
        if not candidate_label or candidate_label.casefold() == current_label.casefold():
            continue
        candidate_provider = entity_university(candidate).casefold()
        candidate_category = clean_text(
            first_value(candidate, "program_name", "parent_course", "category", default=None)
        ).casefold()
        linked_course = first_value(candidate, "linked_course.id", "linked_course", default=None)
        if isinstance(linked_course, Mapping):
            linked_course = first_value(linked_course, "id", "entity_id", "slug", default=None)
        linked_course = clean_text(linked_course)

        linked = bool(
            (current_id and linked_course and linked_course == current_id)
            or (current_course and linked_course and linked_course == current_course)
        )
        same_provider = bool(provider and candidate_provider == provider)
        same_category = bool(category and candidate_category == category)
        related = linked
        if page_type == "university":
            related = same_provider
        elif page_type in {"course", "specialization"}:
            has_link = bool(linked_course)
            related = linked or (
                not has_link and same_provider and (not category or same_category)
            )
        if related:
            add(candidate_label)
        if len(result) >= limit:
            break
    return result[:limit]


def numbered_lines(labels: Iterable[str]) -> str:
    cleaned = [clean_text(label) for label in labels if clean_text(label)]
    return "\n".join(f"{number}. {label}" for number, label in enumerate(cleaned, start=1))


__all__ = [
    "catalog_get_entity",
    "clean_text",
    "entity_fee",
    "entity_heading",
    "entity_label",
    "entity_page_type",
    "entity_university",
    "find_catalog_entity",
    "first_value",
    "format_inr",
    "has_value",
    "iter_catalog_entities",
    "numbered_lines",
    "parse_money",
    "related_specialization_names",
    "render_sections",
    "unwrap_catalog_record",
]
