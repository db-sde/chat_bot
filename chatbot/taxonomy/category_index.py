"""Reverse indexes for course-family discovery and cross-slot intersections."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from .alias_tables import normalize_text


def _freeze_sets(values: Mapping[str, set[str]]) -> Mapping[str, tuple[str, ...]]:
    return MappingProxyType({key: tuple(sorted(items)) for key, items in values.items()})


@dataclass(frozen=True, slots=True)
class CategoryIndex:
    """Immutable category/specialization lookup over concrete catalog records."""

    category_to_entities: Mapping[str, tuple[str, ...]]
    entity_to_categories: Mapping[str, tuple[str, ...]]
    specialization_to_entities: Mapping[str, tuple[str, ...]]
    entity_to_specializations: Mapping[str, tuple[str, ...]]
    university_to_entities: Mapping[str, tuple[str, ...]]
    entity_to_universities: Mapping[str, tuple[str, ...]]

    @classmethod
    def empty(cls) -> CategoryIndex:
        empty = MappingProxyType({})
        return cls(empty, empty, empty, empty, empty, empty)

    @classmethod
    def from_records(cls, records: Iterable[Mapping[str, object]]) -> CategoryIndex:
        category_to_entities: dict[str, set[str]] = defaultdict(set)
        entity_to_categories: dict[str, set[str]] = defaultdict(set)
        specialization_to_entities: dict[str, set[str]] = defaultdict(set)
        entity_to_specializations: dict[str, set[str]] = defaultdict(set)
        university_to_entities: dict[str, set[str]] = defaultdict(set)
        entity_to_universities: dict[str, set[str]] = defaultdict(set)

        for record in records:
            entity_id = str(record.get("id") or record.get("entity_id") or "").strip()
            if not entity_id:
                continue
            for raw_category in _as_values(record.get("categories") or record.get("category")):
                category = normalize_text(raw_category)
                if category:
                    category_to_entities[category].add(entity_id)
                    entity_to_categories[entity_id].add(category)
            for raw_specialization in _as_values(
                record.get("specializations") or record.get("specialization_name")
            ):
                specialization = normalize_text(raw_specialization)
                if specialization:
                    specialization_to_entities[specialization].add(entity_id)
                    entity_to_specializations[entity_id].add(specialization)
            for raw_university in _as_values(
                record.get("university_names") or record.get("university_name")
            ):
                university = normalize_text(raw_university)
                if university:
                    university_to_entities[university].add(entity_id)
                    entity_to_universities[entity_id].add(university)

        return cls(
            category_to_entities=_freeze_sets(category_to_entities),
            entity_to_categories=_freeze_sets(entity_to_categories),
            specialization_to_entities=_freeze_sets(specialization_to_entities),
            entity_to_specializations=_freeze_sets(entity_to_specializations),
            university_to_entities=_freeze_sets(university_to_entities),
            entity_to_universities=_freeze_sets(entity_to_universities),
        )

    def entities_for_category(self, category: str) -> tuple[str, ...]:
        return self.category_to_entities.get(normalize_text(category), ())

    def entities_for_specialization(self, specialization: str) -> tuple[str, ...]:
        query = normalize_text(specialization)
        direct = self.specialization_to_entities.get(query)
        if direct is not None:
            return direct
        # Token containment supports requests such as "analytics" for
        # "Business Analytics" without guessing a provider.
        matches: set[str] = set()
        query_tokens = set(query.split())
        for name, entity_ids in self.specialization_to_entities.items():
            if query_tokens and query_tokens <= set(name.split()):
                matches.update(entity_ids)
        return tuple(sorted(matches))

    def entities_for_university(self, university: str) -> tuple[str, ...]:
        query = normalize_text(university)
        direct = self.university_to_entities.get(query)
        if direct is not None:
            return direct
        query_tokens = set(query.split())
        matches: set[str] = set()
        for name, entity_ids in self.university_to_entities.items():
            name_tokens = set(name.split())
            if (
                query_tokens
                and name_tokens
                and (query_tokens <= name_tokens or name_tokens <= query_tokens)
            ):
                matches.update(entity_ids)
        return tuple(sorted(matches))

    def categories_for_entity(self, entity_id: str) -> tuple[str, ...]:
        return self.entity_to_categories.get(str(entity_id), ())

    def specializations_for_entity(self, entity_id: str) -> tuple[str, ...]:
        return self.entity_to_specializations.get(str(entity_id), ())

    def intersect(
        self,
        *,
        category: str | None = None,
        specialization: str | None = None,
        university: str | None = None,
        entity_ids: Iterable[str] | None = None,
    ) -> tuple[str, ...]:
        """Intersect any supplied filters without ever selecting the first match."""

        pools: list[set[str]] = []
        if entity_ids is not None:
            pools.append({str(entity_id) for entity_id in entity_ids})
        if category:
            pools.append(set(self.entities_for_category(category)))
        if specialization:
            pools.append(set(self.entities_for_specialization(specialization)))
        if university:
            pools.append(set(self.entities_for_university(university)))
        if not pools:
            return ()
        result = pools[0]
        for pool in pools[1:]:
            result &= pool
        return tuple(sorted(result))

    # Friendly aliases used by discovery/category handlers.
    entities_matching = intersect


def _as_values(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Mapping):
        for key in ("name", "value", "title", "label"):
            if value.get(key):
                return (str(value[key]),)
        return ()
    if isinstance(value, Iterable):
        result: list[str] = []
        for item in value:
            result.extend(_as_values(item))
        return tuple(result)
    return (str(value),)


__all__ = ["CategoryIndex"]
