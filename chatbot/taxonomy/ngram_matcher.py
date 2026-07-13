"""Longest-span-first matching over prebuilt taxonomy indexes."""

from __future__ import annotations

from dataclasses import dataclass

from .alias_tables import normalize_text
from .fuzzy_bucket import search_bucket
from .index_builder import TaxonomyIndexes, category_initialism


@dataclass(frozen=True, slots=True)
class SpanMatch:
    entity_ids: frozenset[str]
    confidence: str
    matched_span: str
    layer: int
    start: int
    end: int
    score: float | None = None
    method: str = "unknown"
    matched_catalog_term: str | None = None


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


def _ngram_hit(
    indexes: TaxonomyIndexes,
    slot_type: str,
    span: str,
    size: int,
    query_tokens: tuple[str, ...],
) -> frozenset[str]:
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


def _has_shorter_exact_match(
    indexes: TaxonomyIndexes,
    slot_type: str,
    span_tokens: tuple[str, ...],
) -> bool:
    """Keep a broad fuzzy span from hiding a narrower exact catalog phrase."""

    if len(span_tokens) < 2:
        return False
    canonical = indexes.canonical_name_index.get(slot_type, {})
    aliases = indexes.alias_index.get(slot_type, {})
    acronyms = indexes.acronym_index.get(slot_type, {})
    for size in range(len(span_tokens) - 1, 0, -1):
        for start in range(len(span_tokens) - size + 1):
            subspan = " ".join(span_tokens[start : start + size])
            if canonical.get(subspan) or aliases.get(subspan):
                return True
            if acronyms.get(subspan.replace(" ", "")):
                return True
            if slot_type == "course":
                initialism = category_initialism(subspan)
                if initialism and (
                    canonical.get(initialism)
                    or aliases.get(initialism)
                    or acronyms.get(initialism)
                ):
                    return True
    return False


def match_ngrams(
    query_tokens: list[str] | tuple[str, ...],
    slot_type: str,
    indexes: TaxonomyIndexes,
) -> tuple[SpanMatch, ...]:
    """Run exact → alias → acronym → n-gram → bounded fuzzy matching."""

    tokens = normalize_query_tokens(query_tokens)
    if not tokens:
        return ()
    matches: list[SpanMatch] = []
    covered: set[int] = set()

    longest_alias = max(
        (len(alias.split()) for alias in indexes.alias_index.get(slot_type, {})),
        default=3,
    )
    longest_canonical = max(
        (len(name.split()) for name in indexes.canonical_name_index.get(slot_type, {})),
        default=3,
    )
    # Course phrases such as "Master of Business Administration" can resolve
    # through a generated initialism even when that wording is not a catalog
    # alias, so inspect a small bounded phrase window for that slot.
    generated_initialism_window = 6 if slot_type == "course" else 3
    longest_exact = max(generated_initialism_window, longest_alias, longest_canonical)
    for size in range(min(len(tokens), longest_exact), 0, -1):
        if len(tokens) < size:
            continue
        for start in range(len(tokens) - size + 1):
            end = start + size
            if any(position in covered for position in range(start, end)):
                continue
            span = " ".join(tokens[start:end])
            entity_ids = indexes.canonical_name_index.get(slot_type, {}).get(span)
            layer = 1
            score: float | None = None
            confidence = "HIGH"
            method = "exact"
            matched_catalog_term: str | None = span if entity_ids else None
            if not entity_ids:
                entity_ids = indexes.alias_index.get(slot_type, {}).get(span)
                method = "alias"
                matched_catalog_term = span if entity_ids else None
            if not entity_ids:
                acronym = span.replace(" ", "")
                entity_ids = indexes.acronym_index.get(slot_type, {}).get(acronym)
                layer = 2
                method = "acronym"
                matched_catalog_term = acronym if entity_ids else None
            if not entity_ids and slot_type == "course":
                initialism = category_initialism(span)
                if initialism:
                    entity_ids = (
                        indexes.canonical_name_index.get(slot_type, {}).get(initialism)
                        or indexes.alias_index.get(slot_type, {}).get(initialism)
                        or indexes.acronym_index.get(slot_type, {}).get(initialism)
                    )
                    layer = 2
                    method = "acronym"
                    matched_catalog_term = initialism if entity_ids else None
            # Partial n-grams and fuzzy lookup remain deliberately bounded to
            # three query tokens. Longer phrases above are exact catalog names
            # or aliases only.
            if size > 3 and not entity_ids:
                continue
            if not entity_ids:
                entity_ids = _ngram_hit(indexes, slot_type, span, size, tokens)
                layer = 3
                method = "ngram"
                matched_catalog_term = span if entity_ids else None
            if not entity_ids:
                # Matching is longest-span-first, but confidence layers still
                # have global precedence. For example, fuzzy ``online mba is``
                # must not consume the exact catalog alias ``online mba``.
                hits = (
                    ()
                    if _has_shorter_exact_match(
                        indexes,
                        slot_type,
                        tuple(span.split()),
                    )
                    else search_bucket(span, indexes.fuzzy_buckets.get(slot_type, {}))
                )
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
                    method = "rapidfuzz"
                    matched_catalog_term = "|".join(dict.fromkeys(hit.term for hit in selected))
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
                    method=method,
                    matched_catalog_term=matched_catalog_term,
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
