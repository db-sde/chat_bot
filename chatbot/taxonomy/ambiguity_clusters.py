"""Precomputed collision clusters for short university/entity mentions."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from types import MappingProxyType

from .alias_tables import normalize_text

STOP_LEAD_TOKENS = frozenset({"online", "the", "of", "and", "university", "institute", "college"})
MIN_SHARED_TOKEN_LENGTH = 4


def build_ambiguity_clusters(
    entity_names: Mapping[str, str],
    entity_slot_types: Mapping[str, str],
    acronym_indexes: Mapping[str, Mapping[str, frozenset[str]]],
) -> Mapping[str, Mapping[str, frozenset[str]]]:
    """Build acronym and leading-brand collision sets per slot type."""

    clusters: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))

    for slot_type, acronyms in acronym_indexes.items():
        for acronym, entity_ids in acronyms.items():
            if len(entity_ids) > 1:
                clusters[slot_type][normalize_text(acronym)].update(entity_ids)

    leading: dict[tuple[str, str], set[str]] = defaultdict(set)
    token_families: dict[tuple[str, str], set[str]] = defaultdict(set)
    for entity_id, canonical_name in entity_names.items():
        slot_type = entity_slot_types.get(entity_id)
        tokens = normalize_text(canonical_name).split()
        first = next((token for token in tokens if token not in STOP_LEAD_TOKENS), "")
        if slot_type and first:
            leading[(slot_type, first)].add(entity_id)
        if slot_type:
            for token in set(tokens) - STOP_LEAD_TOKENS:
                if len(token) >= MIN_SHARED_TOKEN_LENGTH:
                    token_families[(slot_type, token)].add(entity_id)
    for (slot_type, first), entity_ids in leading.items():
        if len(entity_ids) > 1:
            clusters[slot_type][first].update(entity_ids)
    # Shared catalog tokens identify provider/brand families without maintaining
    # a list of known university names. Generic envelope words are excluded
    # above, and only actual collisions become ambiguity clusters.
    for (slot_type, brand), entity_ids in token_families.items():
        if len(entity_ids) > 1:
            clusters[slot_type][brand].update(entity_ids)

    return MappingProxyType(
        {
            slot_type: MappingProxyType(
                {key: frozenset(sorted(entity_ids)) for key, entity_ids in sorted(values.items())}
            )
            for slot_type, values in clusters.items()
        }
    )


def expand_single_token_cluster(
    clusters: Mapping[str, Mapping[str, frozenset[str]]],
    slot_type: str,
    matched_span: str,
    entity_ids: frozenset[str],
) -> frozenset[str]:
    """Expand only single-token matches; a longer phrase is disambiguating evidence."""

    token = normalize_text(matched_span)
    if len(token.split()) != 1:
        return entity_ids
    cluster = clusters.get(slot_type, {}).get(token)
    return frozenset(set(entity_ids) | set(cluster or ()))


__all__ = ["build_ambiguity_clusters", "expand_single_token_cluster"]
