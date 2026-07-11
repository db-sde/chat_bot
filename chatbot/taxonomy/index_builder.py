"""Build immutable, request-time taxonomy indexes from a :class:`CatalogStore`."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal

from .alias_tables import CURATED_ALIASES, normalize_text
from .ambiguity_clusters import build_ambiguity_clusters
from .category_index import CategoryIndex
from .fuzzy_bucket import BucketKey, FuzzyTerm, build_fuzzy_buckets

SlotType = Literal["university", "course", "specialization"]
FrequencyClass = Literal["STRONG", "WEAK", "SUPPRESSED"]

STOPWORDS = frozenset(
    {"university", "online", "institute", "of", "the", "and", "management", "college"}
)
KNOWN_CATEGORY_EXPANSIONS = {
    "master of business administration": "mba",
    "masters of business administration": "mba",
    "master of computer applications": "mca",
    "masters of computer applications": "mca",
    "bachelor of business administration": "bba",
    "bachelor of computer applications": "bca",
}
KNOWN_CATEGORY_CODES = frozenset(
    {"mba", "mca", "bba", "bca", "bcom", "mcom", "ba", "ma", "bsc", "msc"}
)


@dataclass(frozen=True, slots=True)
class CatalogRecord:
    id: str
    page_type: str
    canonical_name: str
    university_name: str | None = None
    university_id: str | None = None
    program_name: str | None = None
    category: str | None = None
    specialization_name: str | None = None
    aliases: tuple[str, ...] = ()

    def as_mapping(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "id": self.id,
                "page_type": self.page_type,
                "canonical_name": self.canonical_name,
                "university_name": self.university_name,
                "university_names": tuple(
                    value for value in (self.university_name, self.university_id) if value
                ),
                "university_id": self.university_id,
                "program_name": self.program_name,
                "category": self.category,
                "specialization_name": self.specialization_name,
                "aliases": self.aliases,
            }
        )


@dataclass(frozen=True, slots=True)
class TaxonomyIndexes:
    canonical_name_index: Mapping[str, Mapping[str, frozenset[str]]]
    ngram_index: Mapping[str, Mapping[int, Mapping[str, frozenset[str]]]]
    frequency_buckets: Mapping[str, Mapping[str, FrequencyClass]]
    acronym_index: Mapping[str, Mapping[str, frozenset[str]]]
    alias_index: Mapping[str, Mapping[str, frozenset[str]]]
    fuzzy_buckets: Mapping[str, Mapping[BucketKey, tuple[FuzzyTerm, ...]]]
    entity_names: Mapping[str, str]
    entity_slot_types: Mapping[str, str]
    entity_tokens: Mapping[str, frozenset[str]]
    entity_metadata: Mapping[str, Mapping[str, object]]
    ambiguity_clusters: Mapping[str, Mapping[str, frozenset[str]]]
    category_index: CategoryIndex

    # Short compatibility names are convenient in tests and callers.
    @property
    def canonical(self) -> Mapping[str, Mapping[str, frozenset[str]]]:
        return self.canonical_name_index

    @property
    def ngrams(self) -> Mapping[str, Mapping[int, Mapping[str, frozenset[str]]]]:
        return self.ngram_index

    @property
    def acronyms(self) -> Mapping[str, Mapping[str, frozenset[str]]]:
        return self.acronym_index

    @property
    def aliases(self) -> Mapping[str, Mapping[str, frozenset[str]]]:
        return self.alias_index


def normalize_category(value: object) -> str:
    normalized = normalize_text(value)
    if normalized in KNOWN_CATEGORY_EXPANSIONS:
        return KNOWN_CATEGORY_EXPANSIONS[normalized]
    tokens = normalized.split()
    for token in tokens:
        if token in KNOWN_CATEGORY_CODES:
            return token
    return normalized


def category_entity_id(category: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", normalize_category(category)).strip("-")
    return f"category:{slug}"


def _as_mapping(value: object) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    dumper = getattr(value, "model_dump", None)
    if callable(dumper):
        return dumper(by_alias=True)
    if hasattr(value, "__dict__"):
        return vars(value)
    return {}


def _get(value: object, *names: str) -> Any:
    mapping = _as_mapping(value)
    for name in names:
        if name in mapping and mapping[name] is not None:
            return mapping[name]
        attribute = getattr(value, name, None)
        if attribute is not None:
            return attribute
    return None


def _strings(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Mapping):
        found = _get(value, "name", "label", "value", "title", "abbreviation")
        return (str(found),) if found else ()
    if isinstance(value, Iterable):
        result: list[str] = []
        for item in value:
            result.extend(_strings(item))
        return tuple(result)
    return (str(value),)


def catalog_records(catalog: object) -> tuple[CatalogRecord, ...]:
    """Extract metadata from CatalogStore or a small dict/list mock catalog."""

    metadata = getattr(catalog, "metadata", None)
    catalog_entities = getattr(catalog, "entities", {})
    if isinstance(metadata, Mapping):
        items: Iterable[object] = metadata.values()
    elif callable(getattr(catalog, "list_metadata", None)):
        items = catalog.list_metadata()
    elif isinstance(catalog, Mapping):
        for key in ("metadata", "entities", "records", "items", "data"):
            nested = catalog.get(key)
            if isinstance(nested, Mapping):
                items = nested.values()
                break
            if isinstance(nested, Iterable) and not isinstance(nested, (str, bytes)):
                items = nested
                break
        else:
            items = catalog.values()
    elif isinstance(catalog, Iterable):
        items = catalog
    else:
        items = ()

    records: list[CatalogRecord] = []
    for item in items:
        item_id = _get(item, "id", "entity_id", "slug")
        full_entity = (
            catalog_entities.get(str(item_id)) if isinstance(catalog_entities, Mapping) else None
        )
        meta = _get(item, "_meta", "meta")
        page_type = normalize_text(_get(item, "page_type") or _get(meta, "page_type"))
        university = _get(item, "university_name", "university_full_name")
        university_full_name = _get(item, "university_full_name")
        program = _get(item, "program_name", "course_name")
        specialization = _get(item, "specialization_name", "spec_name")
        canonical = _get(item, "canonical_name", "name", "title")
        if not canonical:
            canonical = (
                university_full_name or university
                if page_type == "university"
                else specialization or program
            )
        entity_id = _get(item, "id", "entity_id", "slug")
        if not entity_id or not page_type or not canonical:
            continue
        aliases = list(_strings(_get(item, "aliases", "known_aliases")))
        aliases.extend(_strings(_get(full_entity, "aliases", "known_aliases")))
        aliases.extend(_strings(_get(item, "abbreviation", "acronym", "short_name")))
        linked_university = _get(full_entity, "linked_university")
        university_id = _get(linked_university, "id", "entity_id", "slug")
        if university_id is None and isinstance(linked_university, str):
            university_id = linked_university
        category = normalize_category(_get(item, "category") or program)
        if page_type not in {"course", "specialization"}:
            category = ""
        records.append(
            CatalogRecord(
                id=str(entity_id),
                page_type=page_type,
                canonical_name=str(canonical),
                university_name=str(university) if university else None,
                university_id=str(university_id) if university_id else None,
                program_name=str(program) if program else None,
                category=category or None,
                specialization_name=str(specialization) if specialization else None,
                aliases=tuple(dict.fromkeys(alias for alias in aliases if alias)),
            )
        )
    return tuple(records)


def _tokens(value: str) -> tuple[str, ...]:
    return tuple(token for token in normalize_text(value).split() if token not in STOPWORDS)


def _spans(tokens: tuple[str, ...]) -> Iterable[tuple[int, str]]:
    for size in (1, 2, 3):
        for start in range(0, len(tokens) - size + 1):
            yield size, " ".join(tokens[start : start + size])


def _acronyms(name: str) -> set[str]:
    all_tokens = normalize_text(name).split()
    filtered = [token for token in all_tokens if token not in STOPWORDS]
    # Conventional institutional acronyms retain University/Institute/etc. but
    # omit the delivery-mode suffix "Online" (NMIMS, IGNOU, LPU, SMU).
    institutional = [token for token in all_tokens if token not in {"online", "of", "the", "and"}]
    result = {
        "".join(token[0] for token in all_tokens),
        "".join(token[0] for token in filtered),
        "".join(token[0] for token in institutional),
    }
    return {item for item in result if item}


def _freeze_set_map(values: Mapping[str, set[str]]) -> Mapping[str, frozenset[str]]:
    return MappingProxyType(
        {key: frozenset(sorted(entity_ids)) for key, entity_ids in sorted(values.items())}
    )


def _freeze_slot_set_map(
    values: Mapping[str, Mapping[str, set[str]]],
) -> Mapping[str, Mapping[str, frozenset[str]]]:
    return MappingProxyType(
        {slot: _freeze_set_map(slot_values) for slot, slot_values in values.items()}
    )


def build_indexes(catalog: object) -> TaxonomyIndexes:
    records = catalog_records(catalog)
    slots = ("university", "course", "specialization")
    canonical: dict[str, dict[str, set[str]]] = {slot: defaultdict(set) for slot in slots}
    ngrams: dict[str, dict[int, dict[str, set[str]]]] = {
        slot: {1: defaultdict(set), 2: defaultdict(set), 3: defaultdict(set)} for slot in slots
    }
    acronyms: dict[str, dict[str, set[str]]] = {slot: defaultdict(set) for slot in slots}
    aliases: dict[str, dict[str, set[str]]] = {slot: defaultdict(set) for slot in slots}
    entity_names: dict[str, str] = {}
    entity_slots: dict[str, str] = {}
    entity_tokens: dict[str, frozenset[str]] = {}
    metadata: dict[str, Mapping[str, object]] = {
        record.id: record.as_mapping() for record in records
    }

    category_records = [record.as_mapping() for record in records]
    category_index = CategoryIndex.from_records(category_records)

    def add(slot: str, entity_id: str, name: str, known_aliases: Iterable[str] = ()) -> None:
        normalized_name = normalize_text(name)
        if not normalized_name:
            return
        canonical[slot][normalized_name].add(entity_id)
        entity_names[entity_id] = name
        entity_slots[entity_id] = slot
        tokens = _tokens(name)
        entity_tokens[entity_id] = frozenset(tokens)
        for size, span in _spans(tokens):
            ngrams[slot][size][span].add(entity_id)
        for acronym in _acronyms(name):
            acronyms[slot][acronym].add(entity_id)
        for alias in known_aliases:
            key = normalize_text(alias)
            if not key:
                continue
            aliases[slot][key].add(entity_id)
            compact = key.replace(" ", "")
            if len(key.split()) == 1 and 2 <= len(compact) <= 15:
                acronyms[slot][compact].add(entity_id)

    # Universities and specialization pages retain concrete ids.
    for record in records:
        if record.page_type == "university":
            add("university", record.id, record.canonical_name, record.aliases)
            if record.university_name and normalize_text(record.university_name) != normalize_text(
                record.canonical_name
            ):
                aliases["university"][normalize_text(record.university_name)].add(record.id)
        elif record.page_type == "specialization":
            add(
                "specialization",
                record.id,
                record.specialization_name or record.canonical_name,
                record.aliases,
            )

    # A course family is one semantic candidate regardless of provider count.
    categories = sorted({record.category for record in records if record.category})
    for category in categories:
        entity_id = category_entity_id(category)
        display = category.upper() if len(category) <= 5 else category.title()
        metadata[entity_id] = MappingProxyType(
            {
                "id": entity_id,
                "page_type": "category",
                "canonical_name": display,
                "category": category,
                "university_name": None,
                "university_id": None,
                "specialization_name": None,
                "aliases": (),
            }
        )
        add("course", entity_id, display)

    # If a feed lacks separate university pages, synthesize a semantic university
    # candidate so its course/specialization records remain discoverable.
    indexed_universities = {
        normalize_text(name)
        for entity_id, name in entity_names.items()
        if entity_slots[entity_id] == "university"
    }
    university_lookup_keys = set(indexed_universities)
    university_lookup_keys.update(aliases["university"])
    university_lookup_keys.update(acronyms["university"])
    indexed_university_token_sets = [
        set(_tokens(name))
        for entity_id, name in entity_names.items()
        if entity_slots[entity_id] == "university"
    ]
    for university in sorted(
        {record.university_name for record in records if record.university_name}
    ):
        university_key = normalize_text(university)
        university_tokens = set(_tokens(university))
        compact_tokens = {token.replace(" ", "") for token in university_tokens}
        known_by_name_or_alias = (
            university_key in university_lookup_keys
            or bool(compact_tokens & university_lookup_keys)
            or any(
                university_tokens
                and existing_tokens
                and (
                    university_tokens == existing_tokens
                    or university_tokens < existing_tokens
                    or existing_tokens < university_tokens
                )
                for existing_tokens in indexed_university_token_sets
            )
        )
        if known_by_name_or_alias:
            continue
        entity_id = "university:" + re.sub(r"[^a-z0-9]+", "-", normalize_text(university)).strip(
            "-"
        )
        metadata[entity_id] = MappingProxyType(
            {
                "id": entity_id,
                "page_type": "university",
                "canonical_name": university,
                "university_name": university,
                "university_id": None,
                "category": None,
                "specialization_name": None,
                "aliases": (),
            }
        )
        add("university", entity_id, university)

    frequency: dict[str, dict[str, FrequencyClass]] = {slot: {} for slot in slots}
    for slot in slots:
        for size in (1, 2, 3):
            for span, ids in ngrams[slot][size].items():
                count = len(ids)
                bucket: FrequencyClass = (
                    "STRONG" if count == 1 else "WEAK" if count <= 6 else "SUPPRESSED"
                )
                frequency[slot][span] = bucket
                if size == 1 and bucket == "STRONG":
                    aliases[slot][span].update(ids)

    # Curated aliases replace (rather than merge with) lower-confidence derivation.
    for slot, table in CURATED_ALIASES.items():
        for raw_alias, targets in table.items():
            resolved: set[str] = set()
            for target in targets:
                target_key = (
                    normalize_category(target) if slot == "course" else normalize_text(target)
                )
                if slot == "course":
                    candidate_id = category_entity_id(target_key)
                    if candidate_id in entity_names:
                        resolved.add(candidate_id)
                else:
                    resolved.update(canonical[slot].get(target_key, ()))
                    target_tokens = set(_tokens(target))
                    for entity_id, name in entity_names.items():
                        if entity_slots[entity_id] == slot and target_tokens <= set(_tokens(name)):
                            resolved.add(entity_id)
            if resolved:
                aliases[slot][normalize_text(raw_alias)] = resolved

    frozen_acronyms = _freeze_slot_set_map(acronyms)
    fuzzy_by_slot: dict[str, Mapping[BucketKey, tuple[FuzzyTerm, ...]]] = {}
    for slot in slots:
        fuzzy_terms: dict[str, set[str]] = defaultdict(set)
        for name, ids in canonical[slot].items():
            fuzzy_terms[name].update(ids)
        for alias, ids in aliases[slot].items():
            fuzzy_terms[alias].update(ids)
        for span, ids in ngrams[slot][1].items():
            if frequency[slot].get(span) != "SUPPRESSED":
                fuzzy_terms[span].update(ids)
        fuzzy_by_slot[slot] = build_fuzzy_buckets(fuzzy_terms)

    frozen_names = MappingProxyType(dict(entity_names))
    frozen_slots = MappingProxyType(dict(entity_slots))
    clusters = build_ambiguity_clusters(frozen_names, frozen_slots, frozen_acronyms)
    frozen_ngrams = MappingProxyType(
        {
            slot: MappingProxyType(
                {size: _freeze_set_map(values) for size, values in sizes.items()}
            )
            for slot, sizes in ngrams.items()
        }
    )
    return TaxonomyIndexes(
        canonical_name_index=_freeze_slot_set_map(canonical),
        ngram_index=frozen_ngrams,
        frequency_buckets=MappingProxyType(
            {slot: MappingProxyType(dict(values)) for slot, values in frequency.items()}
        ),
        acronym_index=frozen_acronyms,
        alias_index=_freeze_slot_set_map(aliases),
        fuzzy_buckets=MappingProxyType(fuzzy_by_slot),
        entity_names=frozen_names,
        entity_slot_types=frozen_slots,
        entity_tokens=MappingProxyType(dict(entity_tokens)),
        entity_metadata=MappingProxyType(metadata),
        ambiguity_clusters=clusters,
        category_index=category_index,
    )


__all__ = [
    "STOPWORDS",
    "CatalogRecord",
    "FrequencyClass",
    "SlotType",
    "TaxonomyIndexes",
    "build_indexes",
    "catalog_records",
    "category_entity_id",
    "normalize_category",
]
