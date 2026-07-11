"""Bounded fuzzy lookup helpers.

Only the query's ``(first_letter, length_band)`` bucket is searched.  Terms are
also registered for the bands reachable by a one-character insertion/deletion;
this preserves the bounded lookup while avoiding hard ``len // 3`` boundaries
such as ``markting`` (8 chars) versus ``marketing`` (9 chars).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from rapidfuzz import fuzz

from .alias_tables import normalize_text

BucketKey = tuple[str, int]


def length_band(value: str | int) -> int:
    length = value if isinstance(value, int) else len(normalize_text(value).replace(" ", ""))
    return max(0, length // 3)


def bucket_key(value: str, *, assumed_length: int | None = None) -> BucketKey:
    normalized = normalize_text(value).replace(" ", "")
    first = normalized[:1]
    return first, length_band(len(normalized) if assumed_length is None else assumed_length)


@dataclass(frozen=True, slots=True)
class FuzzyTerm:
    term: str
    entity_ids: frozenset[str]


@dataclass(frozen=True, slots=True)
class FuzzyHit:
    term: str
    entity_ids: frozenset[str]
    score: float


def pragmatic_score(query: str, candidate: str) -> float:
    """Score a term, including the documented short-acronym typo behavior.

    RapidFuzz correctly scores ordinary one-edit typos (``markting``) highly.
    Very short reordered strings such as ``mabb``/``mba`` are otherwise overly
    penalized.  If the longer token is exactly the shorter token's character
    multiset plus one repeated character, treat it as a medium-confidence typo.
    """

    query_key = normalize_text(query).replace(" ", "")
    candidate_key = normalize_text(candidate).replace(" ", "")
    if not query_key or not candidate_key:
        return 0.0

    score = float(fuzz.token_sort_ratio(query_key, candidate_key))
    longer, shorter = (
        (query_key, candidate_key)
        if len(query_key) >= len(candidate_key)
        else (candidate_key, query_key)
    )
    if (
        len(longer) == len(shorter) + 1
        and longer[:1] == shorter[:1]
        and not (Counter(shorter) - Counter(longer))
    ):
        score = max(score, 85.0)
    return score


def build_fuzzy_buckets(
    terms: Mapping[str, Iterable[str]],
) -> Mapping[BucketKey, tuple[FuzzyTerm, ...]]:
    """Freeze a term -> entity-id mapping into bounded search buckets."""

    buckets: dict[BucketKey, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for raw_term, raw_ids in terms.items():
        term = normalize_text(raw_term)
        compact = term.replace(" ", "")
        if not compact:
            continue
        ids = {str(entity_id) for entity_id in raw_ids if entity_id is not None}
        if not ids:
            continue

        # Register only bands that a one-character edit can reach.  Search still
        # reads exactly one bucket for the query.
        possible_lengths = {max(1, len(compact) - 1), len(compact), len(compact) + 1}
        for possible_length in possible_lengths:
            buckets[bucket_key(term, assumed_length=possible_length)][term].update(ids)

    return MappingProxyType(
        {
            key: tuple(
                FuzzyTerm(term=term, entity_ids=frozenset(sorted(ids)))
                for term, ids in sorted(values.items())
            )
            for key, values in buckets.items()
        }
    )


def search_bucket(
    query: str,
    buckets: Mapping[BucketKey, tuple[FuzzyTerm, ...]],
    *,
    minimum_score: float = 80.0,
) -> tuple[FuzzyHit, ...]:
    """Return all qualifying hits in the query's single bucket, best first."""

    normalized = normalize_text(query)
    if not normalized:
        return ()
    hits = [
        FuzzyHit(
            term=item.term, entity_ids=item.entity_ids, score=pragmatic_score(normalized, item.term)
        )
        for item in buckets.get(bucket_key(normalized), ())
    ]
    return tuple(
        sorted(
            (hit for hit in hits if hit.score >= minimum_score),
            key=lambda hit: (-hit.score, hit.term),
        )
    )


__all__ = [
    "BucketKey",
    "FuzzyHit",
    "FuzzyTerm",
    "bucket_key",
    "build_fuzzy_buckets",
    "length_band",
    "pragmatic_score",
    "search_bucket",
]
