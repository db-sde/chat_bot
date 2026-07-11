"""Apply topic-switch rules and safely join independently resolved slots."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from taxonomy.category_index import CategoryIndex
from taxonomy.entity_matcher import Candidate
from taxonomy.index_builder import TaxonomyIndexes, normalize_category


@dataclass(frozen=True, slots=True)
class FocusUpdateResult:
    focus: Any
    resolved: Mapping[str, tuple[Candidate, ...]] = field(default_factory=dict)
    ambiguous: Mapping[str, tuple[Candidate, ...]] = field(default_factory=dict)
    medium: Mapping[str, tuple[Candidate, ...]] = field(default_factory=dict)
    comparison_categories: tuple[str, ...] = ()
    joined_entity_ids: tuple[str, ...] = ()

    @property
    def needs_clarification(self) -> bool:
        return bool(self.ambiguous or self.medium)


def _value(item: object, name: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(name, default)
    return getattr(item, name, default)


def _coerce_candidate(item: object, slot_type: str) -> Candidate:
    if isinstance(item, Candidate):
        return item
    entity_id = str(_value(item, "entity_id", _value(item, "id", item)))
    canonical = str(
        _value(item, "canonical_name", _value(item, "name", _value(item, "label", entity_id)))
    )
    confidence = str(_value(item, "confidence", "HIGH")).upper()
    return Candidate(
        entity_id=entity_id,
        confidence="MEDIUM" if confidence == "MEDIUM" else "HIGH",
        matched_span=str(_value(item, "matched_span", canonical)),
        layer=int(_value(item, "layer", 3)),
        slot_type=slot_type,  # type: ignore[arg-type]
        canonical_name=canonical,
        score=_value(item, "score"),
    )


def _candidate_lists(mentions: object) -> dict[str, tuple[Candidate, ...]]:
    field_names = {
        "university": ("universities", "university_candidates", "university"),
        "course": ("courses", "course_candidates", "categories", "category"),
        "specialization": ("specializations", "specialization_candidates", "specialization"),
    }
    result: dict[str, tuple[Candidate, ...]] = {}
    for slot, names in field_names.items():
        raw: object = ()
        for name in names:
            value = _value(mentions, name)
            if value:
                raw = value
                break
        if isinstance(raw, (str, Mapping, Candidate)):
            raw_items: Iterable[object] = (raw,)
        elif isinstance(raw, Iterable):
            raw_items = raw
        else:
            raw_items = ()
        deduped: dict[str, Candidate] = {}
        for item in raw_items:
            candidate = _coerce_candidate(item, slot)
            current = deduped.get(candidate.entity_id)
            if current is None or (
                current.confidence == "MEDIUM" and candidate.confidence == "HIGH"
            ):
                deduped[candidate.entity_id] = candidate
        result[slot] = tuple(deduped.values())
    return result


def _assign(target: object, field_name: str, value: object) -> None:
    if hasattr(target, field_name):
        setattr(target, field_name, value)


def _metadata(indexes: TaxonomyIndexes | None, entity_id: str) -> Mapping[str, object]:
    return indexes.entity_metadata.get(entity_id, {}) if indexes else {}


def _label(candidate: Candidate, indexes: TaxonomyIndexes | None) -> str:
    metadata = _metadata(indexes, candidate.entity_id)
    return str(metadata.get("canonical_name") or candidate.canonical_name)


def _category(candidate: Candidate, indexes: TaxonomyIndexes | None) -> str:
    metadata = _metadata(indexes, candidate.entity_id)
    return normalize_category(metadata.get("category") or candidate.canonical_name)


def _university_keys(candidate: Candidate, indexes: TaxonomyIndexes | None) -> tuple[str, ...]:
    metadata = _metadata(indexes, candidate.entity_id)
    values = [
        candidate.entity_id,
        candidate.canonical_name,
        metadata.get("canonical_name"),
        metadata.get("university_name"),
        metadata.get("university_id"),
    ]
    aliases = metadata.get("aliases")
    if isinstance(aliases, (list, tuple, set, frozenset)):
        values.extend(aliases)
    return tuple(dict.fromkeys(str(value) for value in values if value))


def _build_join_candidates(
    entity_ids: Iterable[str],
    slot_type: str,
    indexes: TaxonomyIndexes | None,
) -> tuple[Candidate, ...]:
    result: list[Candidate] = []
    for entity_id in sorted(set(entity_ids)):
        metadata = _metadata(indexes, entity_id)
        result.append(
            Candidate(
                entity_id=entity_id,
                confidence="HIGH",
                matched_span=str(metadata.get("canonical_name") or entity_id),
                layer=3,
                slot_type="specialization" if slot_type == "entity" else slot_type,  # type: ignore[arg-type]
                canonical_name=str(metadata.get("canonical_name") or entity_id),
            )
        )
    return tuple(result)


def update_focus(
    state: object,
    mentions: object,
    *,
    intent: str | None = None,
    catalog: object | None = None,
    indexes: TaxonomyIndexes | None = None,
    category_index: CategoryIndex | None = None,
) -> FocusUpdateResult:
    """Mutate a ConversationState-like focus and return arbitration details.

    ``catalog`` is accepted for integration symmetry; the indexes already contain
    the CatalogStore metadata and linked-university reverse maps used for joining.
    """

    del catalog  # Catalog-derived data is frozen into ``indexes``/``category_index``.
    focus = getattr(state, "focus", state)
    candidates = _candidate_lists(mentions)
    reverse = category_index or (indexes.category_index if indexes else None)
    resolved: dict[str, tuple[Candidate, ...]] = {}
    ambiguous: dict[str, tuple[Candidate, ...]] = {}
    medium: dict[str, tuple[Candidate, ...]] = {}

    high_by_slot: dict[str, tuple[Candidate, ...]] = {}
    for slot, values in candidates.items():
        high = tuple(candidate for candidate in values if candidate.confidence == "HIGH")
        med = tuple(candidate for candidate in values if candidate.confidence == "MEDIUM")
        high_by_slot[slot] = high
        if med and not high:
            medium[slot] = med

    # Independently extracted specialization names commonly map to one page per
    # provider.  Narrow that set with explicit university/category evidence before
    # declaring ambiguity (LPU + MBA + Marketing -> one concrete specialization).
    university_high = high_by_slot["university"]
    course_high_for_join = high_by_slot["course"]
    specialization_high = high_by_slot["specialization"]
    if reverse and len(specialization_high) > 1:
        pool = {candidate.entity_id for candidate in specialization_high}
        inherited_category = _value(focus, "category")
        if len(course_high_for_join) == 1:
            pool &= set(reverse.entities_for_category(_category(course_high_for_join[0], indexes)))
        elif inherited_category:
            pool &= set(reverse.entities_for_category(str(inherited_category)))
        if len(university_high) == 1:
            university_pool: set[str] = set()
            for key in _university_keys(university_high[0], indexes):
                university_pool.update(reverse.entities_for_university(key))
            pool &= university_pool
        elif not course_high_for_join and _value(focus, "university"):
            inherited_university = str(_value(focus, "university"))
            university_pool = set(reverse.entities_for_university(inherited_university))
            inherited_metadata = _metadata(indexes, inherited_university)
            for key in (
                inherited_metadata.get("university_name"),
                inherited_metadata.get("canonical_name"),
            ):
                if key:
                    university_pool.update(reverse.entities_for_university(str(key)))
            pool &= university_pool
        if pool:
            high_by_slot["specialization"] = tuple(
                candidate for candidate in specialization_high if candidate.entity_id in pool
            )

    # Treat an uncertain explicit anchor as a provisional topic switch. This
    # prevents a confirmed "mbaa" on the next turn from inheriting an unrelated
    # old university, while retaining a university confidently named alongside it.
    if (len(high_by_slot["course"]) > 1 or "course" in medium) and len(
        high_by_slot["university"]
    ) != 1:
        _assign(focus, "university", None)
        _assign(focus, "specialization", None)
        _assign(focus, "entity_id", None)
    if (len(high_by_slot["university"]) > 1 or "university" in medium) and len(
        high_by_slot["course"]
    ) != 1:
        _assign(focus, "category", None)
        _assign(focus, "specialization", None)
        _assign(focus, "entity_id", None)

    comparison_categories: tuple[str, ...] = ()
    course_high = high_by_slot["course"]
    if (intent or _value(mentions, "intent")) == "comparison" and len(course_high) >= 2:
        comparison_categories = tuple(
            dict.fromkeys(_category(item, indexes) for item in course_high)
        )
        for target in (state, focus):
            if hasattr(target, "comparison_categories"):
                target.comparison_categories = list(comparison_categories)
        _assign(focus, "entity_id", None)
        resolved["course"] = course_high
    elif len(course_high) > 1:
        ambiguous["course"] = course_high

    for slot in ("university", "specialization"):
        high = high_by_slot[slot]
        if len(high) > 1:
            ambiguous[slot] = high

    single: dict[str, Candidate] = {
        slot: values[0]
        for slot, values in high_by_slot.items()
        if len(values) == 1 and slot not in ambiguous
    }
    if course_high and len(course_high) == 1:
        single["course"] = course_high[0]

    explicit_university = "university" in single
    explicit_category = "course" in single
    explicit_specialization = "specialization" in single

    # --- Hierarchical slot reset (Bug 2.1/2.2 fix) ---
    # When a shallower slot is explicitly re-mentioned without the deeper slot,
    # the deeper slot must be reset.  Previously, only the university-XOR-category
    # branches below ran, so when both were present (e.g. "LPU MBA fee") neither
    # branch fired and the stale specialization from a prior turn survived into
    # the join logic, producing wrong-entity answers.
    #
    # Depth order: university/category (same level) > specialization.
    has_shallow_mention = explicit_university or explicit_category
    if has_shallow_mention and not explicit_specialization:
        _assign(focus, "specialization", None)
        _assign(focus, "entity_id", None)

    # Concrete topic-switch guarantees: category-only cannot stick to a prior
    # university, and university-only cannot retain a prior course/spec context.
    if explicit_category and not explicit_university:
        _assign(focus, "university", None)
        _assign(focus, "specialization", None)
        _assign(focus, "entity_id", None)
    if explicit_university and not explicit_category:
        _assign(focus, "category", None)
        if not explicit_specialization:
            _assign(focus, "specialization", None)
        _assign(focus, "entity_id", None)

    university_candidate = single.get("university")
    category_candidate = single.get("course")
    specialization_candidate = single.get("specialization")
    if university_candidate:
        _assign(focus, "university", university_candidate.entity_id)
        resolved["university"] = (university_candidate,)
    if category_candidate:
        _assign(focus, "category", _category(category_candidate, indexes))
        resolved["course"] = (category_candidate,)
    if specialization_candidate:
        _assign(focus, "specialization", _label(specialization_candidate, indexes))
        resolved["specialization"] = (specialization_candidate,)
    if single:
        _assign(focus, "entity_id", None)

    joined: tuple[str, ...] = ()
    current_university = _value(focus, "university")
    current_category = _value(focus, "category")
    current_specialization = _value(focus, "specialization")

    # A concrete specialization can be unique without a category field (publisher-native
    # pages may have linked_course=null). Validate it against any university evidence before
    # setting the entity id so duplicate specialization labels are never first-picked.
    if reverse and specialization_candidate and current_specialization and not current_category:
        compatible = True
        if current_university:
            university_pool: set[str] = set()
            keys = [str(current_university)]
            if university_candidate:
                keys.extend(_university_keys(university_candidate, indexes))
            for key in keys:
                university_pool.update(reverse.entities_for_university(key))
            compatible = specialization_candidate.entity_id in university_pool
        if compatible:
            _assign(focus, "entity_id", specialization_candidate.entity_id)
            joined = (specialization_candidate.entity_id,)
        elif explicit_specialization and not explicit_university:
            _assign(focus, "university", None)
            _assign(focus, "entity_id", specialization_candidate.entity_id)
            joined = (specialization_candidate.entity_id,)
    # University-only focus is already a unique catalog record.
    elif current_university and not current_category and not current_specialization:
        if university_candidate:
            _assign(focus, "entity_id", university_candidate.entity_id)
            joined = (university_candidate.entity_id,)
    elif reverse and (current_university or current_specialization) and current_category:
        university_keys: list[str | None] = [
            str(current_university) if current_university else None
        ]
        if university_candidate:
            university_keys.extend(_university_keys(university_candidate, indexes))
        university_pool: set[str] | None = None
        for key in university_keys:
            if key:
                matches = set(reverse.entities_for_university(key))
                university_pool = matches if university_pool is None else university_pool | matches
        specialization_ids = (
            {specialization_candidate.entity_id} if specialization_candidate else None
        )
        base_ids = reverse.intersect(
            category=str(current_category),
            specialization=str(current_specialization) if current_specialization else None,
            entity_ids=specialization_ids,
        )
        pool = set(base_ids)
        if university_pool is not None:
            pool &= university_pool
        desired_type = "specialization" if current_specialization else "course"
        if indexes:
            pool = {
                entity_id
                for entity_id in pool
                if _metadata(indexes, entity_id).get("page_type") == desired_type
            }
        joined = tuple(sorted(pool))
        if len(joined) == 1:
            _assign(focus, "entity_id", joined[0])
        elif len(joined) > 1:
            ambiguous[desired_type] = _build_join_candidates(joined, desired_type, indexes)
            _assign(focus, "entity_id", None)
        elif explicit_specialization and not explicit_university and not explicit_category:
            # A specialization-only switch that is incompatible with inherited
            # context must not silently combine unrelated slots.
            _assign(focus, "university", None)
            _assign(focus, "category", None)
            if specialization_candidate:
                _assign(focus, "entity_id", specialization_candidate.entity_id)
                joined = (specialization_candidate.entity_id,)
    elif specialization_candidate and not current_university and not current_category:
        _assign(focus, "entity_id", specialization_candidate.entity_id)
        joined = (specialization_candidate.entity_id,)

    return FocusUpdateResult(
        focus=focus,
        resolved=resolved,
        ambiguous=ambiguous,
        medium=medium,
        comparison_categories=comparison_categories,
        joined_entity_ids=joined,
    )


class FocusUpdater:
    def __init__(
        self,
        *,
        catalog: object | None = None,
        indexes: TaxonomyIndexes | None = None,
        category_index: CategoryIndex | None = None,
    ) -> None:
        self.catalog = catalog
        self.indexes = indexes
        self.category_index = category_index

    def update(
        self, state: object, mentions: object, *, intent: str | None = None
    ) -> FocusUpdateResult:
        return update_focus(
            state,
            mentions,
            intent=intent,
            catalog=self.catalog,
            indexes=self.indexes,
            category_index=self.category_index,
        )


__all__ = ["FocusUpdateResult", "FocusUpdater", "update_focus"]
