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
from rapidfuzz.distance import DamerauLevenshtein

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
    edit_distance: int | None = None


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

    # Transposition/anagram rule: same length, same first letter, identical multiset
    if (
        len(query_key) == len(candidate_key)
        and query_key[:1] == candidate_key[:1]
        and Counter(query_key) == Counter(candidate_key)
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

        # Search still reads exactly one bucket for the query. Long terms also
        # register the two-character length bands used by the guarded adaptive
        # matcher below; this remains bounded at five bucket entries per term.
        radius = 2 if len(compact) >= 6 else 1
        possible_lengths = {max(1, len(compact) + offset) for offset in range(-radius, radius + 1)}
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
    """Return qualifying hits from one bounded bucket, best first.

    ``minimum_score`` remains the ordinary acceptance threshold.  A separate,
    deliberately narrow adaptive path admits a two-edit typo only when both
    values are long single tokens with stable first/last characters and the
    best term has a clear score margin.  This covers mistakes such as
    ``monypal`` -> ``manipal`` without making a global 70-ish score acceptable.
    """

    normalized = normalize_text(query)
    if not normalized:
        return ()
    query_key = normalized.replace(" ", "")
    # Exact acronym lookup already handles legitimate one-to-three-character
    # catalog codes. Fuzzy matching such short prose tokens is unsafe (``BBA``
    # must not become the generated ``BA`` acronym for Business Analytics).
    if len(query_key) <= 3:
        return ()
    hits: list[FuzzyHit] = []
    for item in buckets.get(bucket_key(normalized), ()):
        # A single query token must not fuzzy-match a multiword alias. Its
        # catalog's useful component tokens are indexed independently; allowing
        # this comparison turns generic words such as ``online`` into MBA/MCA.
        if " " not in normalized and " " in item.term:
            continue
        candidate_key = normalize_text(item.term).replace(" ", "")
        hits.append(
            FuzzyHit(
                term=item.term,
                entity_ids=item.entity_ids,
                score=pragmatic_score(normalized, item.term),
                edit_distance=DamerauLevenshtein.distance(query_key, candidate_key),
            )
        )
    ranked = sorted(hits, key=lambda hit: (-hit.score, hit.term))
    accepted = [hit for hit in ranked if hit.score >= minimum_score]
    if accepted:
        return tuple(accepted)

    # The adaptive path is MEDIUM evidence only.  Restrict it to long,
    # single-token terms, two edits, stable endpoints, and a decisive margin
    # over the next indexed term. Provider ids sharing the same winning term do
    # not count as competing meanings; that ambiguity is retained downstream.
    if " " in normalized or len(query_key) < 6 or not ranked:
        return ()
    best = ranked[0]
    best_key = normalize_text(best.term).replace(" ", "")
    if (
        " " in best.term
        or len(best_key) < 6
        or best.edit_distance is None
        or best.edit_distance > 2
        or query_key[:1] != best_key[:1]
        or query_key[-1:] != best_key[-1:]
    ):
        return ()
    runner_up_score = ranked[1].score if len(ranked) > 1 else 0.0
    if best.score - runner_up_score < 12.0:
        return ()
    return (best,)


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
