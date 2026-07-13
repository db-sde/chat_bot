"""Defensive access helpers for publisher data.

Handlers use :func:`safe_get` instead of assuming fields survived ingestion. It accepts
mapping keys, Pydantic attributes/aliases, sequence indexes, and dotted/bracket paths.
Malformed input always resolves to the supplied default.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

_BRACKET_TOKEN = re.compile(r"\[\s*(?:'([^']*)'|\"([^\"]*)\"|([^\]]+))\s*\]")
_MISSING = object()


def _parts(path: str | int | Sequence[str | int] | None) -> list[str | int]:
    if path is None or path == "":
        return []
    if isinstance(path, int):
        return [path]
    if isinstance(path, str):
        normalized = _BRACKET_TOKEN.sub(
            lambda match: "." + next(
                group for group in match.groups() if group is not None
            ).strip(),
            path,
        )
        return [part for part in normalized.split(".") if part != ""]
    if isinstance(path, Sequence):
        return list(path)
    return []


def _model_value(model: BaseModel, part: str | int) -> Any:
    if not isinstance(part, str):
        return _MISSING
    fields = type(model).model_fields
    if part in fields:
        return getattr(model, part, _MISSING)
    for name, field in fields.items():
        if field.alias == part or field.serialization_alias == part:
            return getattr(model, name, _MISSING)
    extra = model.model_extra or {}
    return extra.get(part, _MISSING)


def _step(value: Any, part: str | int) -> Any:
    if isinstance(value, Mapping):
        if part in value:
            return value[part]
        # Dotted paths naturally produce string indexes; numeric mapping keys are
        # still supported without changing ordinary string-key behavior.
        if isinstance(part, str) and part.lstrip("-").isdigit():
            return value.get(int(part), _MISSING)
        return _MISSING
    if isinstance(value, BaseModel):
        return _model_value(value, part)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        try:
            index = part if isinstance(part, int) else int(part)
            return value[index]
        except (IndexError, TypeError, ValueError):
            return _MISSING
    if isinstance(part, str):
        try:
            return getattr(value, part, _MISSING)
        except Exception:
            return _MISSING
    return _MISSING


def safe_get(
    obj: Any,
    path: str | int | Sequence[str | int] | None,
    default: Any = None,
) -> Any:
    """Read ``path`` from dictionaries, models, and lists without ever raising.

    Explicit ``null``/``None`` values are preserved when they are the final value.
    If traversal must continue through one, ``default`` is returned.
    """

    try:
        parts = _parts(path)
        current = obj
        for part in parts:
            if current is None:
                return default
            current = _step(current, part)
            if current is _MISSING:
                return default
        return current
    except Exception:
        return default


@dataclass(frozen=True, slots=True)
class FocusValidation:
    """Catalog validation result for one concept focus.

    ``compatible_entity_ids`` always contains the full compatible set (possibly
    empty); validation never turns a multi-record concept into a first-record
    choice. ``dropped_context_slots`` reports the inherited fields removed when
    current-turn explicit evidence won a conflict.
    """

    valid: bool
    compatible_entity_ids: tuple[str, ...] = ()
    explicit_conflict: bool = False
    dropped_context_slots: tuple[str, ...] = ()
    reason: str = "valid"


_ENTITY_SLOTS = ("university", "course", "specialization")
_SLOT_ALIASES = {
    "university": "university",
    "university_concept": "university",
    "course": "course",
    "course_concept": "course",
    "category": "course",
    "specialization": "specialization",
    "specialization_concept": "specialization",
}


def _value(obj: object, name: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _clean(value: object) -> str | None:
    text = " ".join(str(value or "").split())
    return text or None


def _metadata_value(metadata: object, name: str) -> Any:
    if isinstance(metadata, Mapping):
        return metadata.get(name)
    return getattr(metadata, name, None)


def _concept_values(
    focus: object,
    metadata_by_id: Mapping[str, object],
) -> dict[str, tuple[str, ...]]:
    """Read concept-first fields, falling back to one legacy persisted focus."""

    university_concept = _clean(_value(focus, "university_concept"))
    legacy_university = _clean(_value(focus, "university"))
    entity_id = _clean(_value(focus, "entity_id"))

    university_values: list[str] = []
    if university_concept:
        university_values.append(university_concept)
        # During the additive migration the synchronized legacy university ID
        # remains the safest way to discover short/provider-name variants of a
        # long canonical concept (for example Narsee Monjee... vs NMIMS Online).
        legacy_metadata = metadata_by_id.get(legacy_university or "", {})
        university_values.extend(
            value
            for value in (
                _clean(_metadata_value(legacy_metadata, "university_name")),
                _clean(_metadata_value(legacy_metadata, "canonical_name")),
            )
            if value
        )
    elif legacy_university:
        legacy_metadata = metadata_by_id.get(legacy_university, {})
        university_values.extend(
            value
            for value in (
                _clean(_metadata_value(legacy_metadata, "university_name")),
                _clean(_metadata_value(legacy_metadata, "canonical_name")),
                legacy_university,
            )
            if value
        )
    elif entity_id:
        entity_metadata = metadata_by_id.get(entity_id, {})
        university = _clean(_metadata_value(entity_metadata, "university_name"))
        if university:
            university_values.append(university)

    course = _clean(_value(focus, "course_concept")) or _clean(
        _value(focus, "category")
    )
    if course is None and entity_id:
        course = _clean(
            _metadata_value(metadata_by_id.get(entity_id, {}), "category")
        )

    specialization = _clean(_value(focus, "specialization_concept")) or _clean(
        _value(focus, "specialization")
    )
    if specialization is None and entity_id:
        entity_metadata = metadata_by_id.get(entity_id, {})
        specialization = _clean(
            _metadata_value(entity_metadata, "specialization_name")
            or _metadata_value(entity_metadata, "spec_name")
        )

    return {
        "university": tuple(dict.fromkeys(university_values)),
        "course": (course,) if course else (),
        "specialization": (specialization,) if specialization else (),
    }


def _index_entities(index: object, method_name: str, values: Iterable[str]) -> set[str]:
    method = getattr(index, method_name, None)
    if not callable(method):
        return set()
    result: set[str] = set()
    for value in values:
        try:
            found = method(value)
        except (KeyError, TypeError, ValueError):
            continue
        if found is None or isinstance(found, (str, bytes)):
            if found:
                result.add(str(found))
            continue
        try:
            result.update(str(item) for item in found)
        except TypeError:
            continue
    return result


def _compatible_ids(
    concepts: Mapping[str, tuple[str, ...]],
    category_index: object,
    metadata_by_id: Mapping[str, object],
) -> tuple[str, ...]:
    pools: list[set[str]] = []
    if concepts["university"]:
        pools.append(
            _index_entities(
                category_index,
                "entities_for_university",
                concepts["university"],
            )
        )
    if concepts["course"]:
        pools.append(
            _index_entities(
                category_index,
                "entities_for_category",
                concepts["course"],
            )
        )
    if concepts["specialization"]:
        pools.append(
            _index_entities(
                category_index,
                "entities_for_specialization",
                concepts["specialization"],
            )
        )
    if not pools:
        return ()

    compatible = pools[0]
    for pool in pools[1:]:
        compatible &= pool
    if not compatible:
        return ()

    # Prefer the record shape a late-binding handler will need, but do not make
    # validation depend on publishers having every intermediate page type. A
    # specialization-only feed can still prove that a provider/category exists.
    desired_page_type = (
        "specialization"
        if concepts["specialization"]
        else "course"
        if concepts["course"]
        else "university"
    )
    preferred = {
        entity_id
        for entity_id in compatible
        if str(
            _metadata_value(metadata_by_id.get(entity_id, {}), "page_type") or ""
        ).casefold()
        == desired_page_type
    }
    return tuple(sorted(preferred or compatible))


def _normalize_explicit_slots(
    focus: object,
    explicit_slots: Iterable[str] | None,
    present_slots: set[str],
) -> set[str]:
    if explicit_slots is not None:
        return {
            normalized
            for value in explicit_slots
            if (normalized := _SLOT_ALIASES.get(str(value).casefold())) in present_slots
        }

    sources = _value(focus, "sources", {})
    if isinstance(sources, Mapping):
        has_slot_provenance = any(
            _SLOT_ALIASES.get(str(slot).casefold()) in present_slots
            for slot in sources
        )
        found = {
            normalized
            for slot, source in sources.items()
            if str(source).casefold() == "explicit"
            and (normalized := _SLOT_ALIASES.get(str(slot).casefold())) in present_slots
        }
        if has_slot_provenance:
            return found
    if str(_value(focus, "source", "")).casefold() == "explicit":
        return set(present_slots)
    return set()


def _drop_focus_slot(focus: object, slot: str) -> None:
    fields = {
        "university": ("university_concept", "university"),
        "course": ("course_concept", "category"),
        "specialization": ("specialization_concept", "specialization"),
    }[slot]
    for field_name in fields:
        if isinstance(focus, MutableMapping):
            focus[field_name] = None
        elif hasattr(focus, field_name):
            setattr(focus, field_name, None)

    sources = _value(focus, "sources", {})
    if isinstance(sources, dict):
        sources.pop(slot, None)
    if isinstance(focus, MutableMapping):
        focus["entity_id"] = None
    elif hasattr(focus, "entity_id"):
        focus.entity_id = None  # type: ignore[attr-defined]


def validate_focus(
    focus: object,
    indexes: object,
    *,
    explicit_slots: Iterable[str] | None = None,
    entity_metadata: Mapping[str, object] | None = None,
) -> FocusValidation:
    """Validate concept combinations against immutable catalog-derived indexes.

    When current-turn explicit concepts conflict with inherited slots, inherited
    slots are removed from both the concept and compatibility fields and the
    explicit subset is revalidated. Two incompatible explicit concepts are kept
    intact so a handler can explain the catalog conflict. ``attribute`` and
    ``unknown_entities`` deliberately do not participate in entity validation.
    """

    category_index = getattr(indexes, "category_index", indexes)
    metadata = entity_metadata
    if metadata is None:
        candidate_metadata = getattr(indexes, "entity_metadata", None)
        metadata = candidate_metadata if isinstance(candidate_metadata, Mapping) else {}

    concepts = _concept_values(focus, metadata)
    present = {slot for slot in _ENTITY_SLOTS if concepts[slot]}
    if not present:
        return FocusValidation(valid=True, reason="no_entity_concepts")

    compatible = _compatible_ids(concepts, category_index, metadata)
    if compatible:
        return FocusValidation(valid=True, compatible_entity_ids=compatible)

    explicit = _normalize_explicit_slots(focus, explicit_slots, present)
    inherited = present - explicit
    dropped: tuple[str, ...] = ()
    if explicit and inherited:
        dropped = tuple(slot for slot in _ENTITY_SLOTS if slot in inherited)
        for slot in dropped:
            _drop_focus_slot(focus, slot)
        concepts = _concept_values(focus, metadata)
        compatible = _compatible_ids(concepts, category_index, metadata)
        if compatible:
            if hasattr(focus, "source"):
                focus.source = "explicit"  # type: ignore[attr-defined]
            return FocusValidation(
                valid=True,
                compatible_entity_ids=compatible,
                dropped_context_slots=dropped,
                reason="dropped_inherited_context",
            )
        present = {slot for slot in _ENTITY_SLOTS if concepts[slot]}
        explicit &= present

    explicit_conflict = len(explicit) >= 2 and explicit == present
    return FocusValidation(
        valid=False,
        explicit_conflict=explicit_conflict,
        dropped_context_slots=dropped,
        reason=("explicit_catalog_conflict" if explicit_conflict else "no_catalog_match"),
    )


__all__ = ["FocusValidation", "safe_get", "validate_focus"]
