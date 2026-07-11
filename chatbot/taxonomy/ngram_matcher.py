"""Longest-span-first matching over prebuilt taxonomy indexes."""

from __future__ import annotations

from dataclasses import dataclass

from .alias_tables import normalize_text
from .fuzzy_bucket import search_bucket
from .index_builder import TaxonomyIndexes


@dataclass(frozen=True, slots=True)
class SpanMatch:
    entity_ids: frozenset[str]
    confidence: str
    matched_span: str
    layer: int
    start: int
    end: int
    score: float | None = None


def normalize_query_tokens(query_tokens: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    tokens: list[str] = []
    for raw_token in query_tokens:
        tokens.extend(normalize_text(raw_token).split())
    return tuple(token for token in tokens if token)


def _weak_has_cooccurrence(
    indexes: TaxonomyIndexes,
    slot_type: str,
    entity_id: str,
    span_tokens: tuple[str, ...],
    all_query_tokens: tuple[str, ...],
) -> bool:
    if len(span_tokens) > 1:
        return True
    entity_tokens = indexes.entity_tokens.get(entity_id, frozenset())
    return any(token not in span_tokens and token in entity_tokens for token in all_query_tokens)


def _index_hit(
    indexes: TaxonomyIndexes,
    slot_type: str,
    span: str,
    size: int,
    query_tokens: tuple[str, ...],
) -> frozenset[str]:
    exact = indexes.canonical_name_index.get(slot_type, {}).get(span)
    if exact:
        return exact
    entity_ids = indexes.ngram_index.get(slot_type, {}).get(size, {}).get(span)
    if not entity_ids:
        return frozenset()
    bucket = indexes.frequency_buckets.get(slot_type, {}).get(span)
    if bucket == "SUPPRESSED":
        return frozenset()
    if bucket == "STRONG":
        return entity_ids
    span_tokens = tuple(span.split())
    allowed = {
        entity_id
        for entity_id in entity_ids
        if _weak_has_cooccurrence(indexes, slot_type, entity_id, span_tokens, query_tokens)
    }
    # Collision-prone leading brands must surface their ambiguity rather than
    # disappearing under the ordinary WEAK co-occurrence rule.
    if not allowed and size == 1 and span in indexes.ambiguity_clusters.get(slot_type, {}):
        allowed.update(entity_ids)
    return frozenset(allowed)


def match_ngrams(
    query_tokens: list[str] | tuple[str, ...],
    slot_type: str,
    indexes: TaxonomyIndexes,
) -> tuple[SpanMatch, ...]:
    """Run alias → acronym → n-gram → bounded fuzzy matching per span."""

    tokens = normalize_query_tokens(query_tokens)
    if not tokens:
        return ()
    matches: list[SpanMatch] = []
    covered: set[int] = set()

    for size in (3, 2, 1):
        if len(tokens) < size:
            continue
        for start in range(len(tokens) - size + 1):
            end = start + size
            if any(position in covered for position in range(start, end)):
                continue
            span = " ".join(tokens[start:end])
            entity_ids = indexes.alias_index.get(slot_type, {}).get(span)
            layer = 1
            score: float | None = None
            confidence = "HIGH"
            if not entity_ids:
                entity_ids = indexes.acronym_index.get(slot_type, {}).get(span.replace(" ", ""))
                layer = 2
            if not entity_ids:
                entity_ids = _index_hit(indexes, slot_type, span, size, tokens)
                layer = 3
            if not entity_ids:
                hits = search_bucket(span, indexes.fuzzy_buckets.get(slot_type, {}))
                if hits:
                    best_score = hits[0].score
                    # Keep tied/near-tied names to preserve genuine fuzzy ambiguity.
                    selected = [hit for hit in hits if hit.score >= best_score - 1.0]
                    entity_ids = frozenset(
                        entity_id for hit in selected for entity_id in hit.entity_ids
                    )
                    score = best_score
                    confidence = "HIGH" if best_score >= 90.0 else "MEDIUM"
                    layer = 4
            if not entity_ids:
                continue
            matches.append(
                SpanMatch(
                    entity_ids=frozenset(entity_ids),
                    confidence=confidence,
                    matched_span=span,
                    layer=layer,
                    start=start,
                    end=end,
                    score=score,
                )
            )
            # A broad, multi-token MEDIUM fuzzy guess is not strong enough to
            # suppress a shorter exact/high-confidence span (e.g. ``mba
            # markting`` must still examine ``markting`` -> Marketing HIGH).
            if not (layer == 4 and confidence == "MEDIUM" and size > 1):
                covered.update(range(start, end))
    return tuple(matches)


class NgramMatcher:
    def __init__(self, indexes: TaxonomyIndexes) -> None:
        self.indexes = indexes

    def match(
        self, query_tokens: list[str] | tuple[str, ...], slot_type: str
    ) -> tuple[SpanMatch, ...]:
        return match_ngrams(query_tokens, slot_type, self.indexes)


__all__ = ["NgramMatcher", "SpanMatch", "match_ngrams", "normalize_query_tokens"]
