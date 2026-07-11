"""Public, candidate-preserving taxonomy matcher."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .ambiguity_clusters import expand_single_token_cluster
from .index_builder import SlotType, TaxonomyIndexes, build_indexes
from .ngram_matcher import match_ngrams

Confidence = Literal["HIGH", "MEDIUM"]


@dataclass(frozen=True, slots=True)
class Candidate:
    entity_id: str
    confidence: Confidence
    matched_span: str
    layer: int
    slot_type: SlotType
    canonical_name: str
    score: float | None = None
    start: int = 0
    end: int = 0


def _candidate_key(candidate: Candidate) -> tuple[int, int, int, float, str, str]:
    return (
        0 if candidate.confidence == "HIGH" else 1,
        candidate.layer,
        -len(candidate.matched_span.split()),
        -(candidate.score or 0.0),
        candidate.canonical_name.casefold(),
        candidate.entity_id,
    )


class EntityMatcher:
    """Resolve mentions to ranked candidates without making the final choice."""

    def __init__(self, indexes: TaxonomyIndexes, catalog: object | None = None) -> None:
        self.indexes = indexes
        self.catalog = catalog

    @classmethod
    def from_catalog(cls, catalog: object) -> EntityMatcher:
        return cls(build_indexes(catalog), catalog)

    def resolve_slot(
        self,
        query_tokens: list[str] | tuple[str, ...],
        slot_type: SlotType,
    ) -> list[Candidate]:
        best_by_id: dict[str, Candidate] = {}
        for match in match_ngrams(query_tokens, slot_type, self.indexes):
            entity_ids = expand_single_token_cluster(
                self.indexes.ambiguity_clusters,
                slot_type,
                match.matched_span,
                match.entity_ids,
            )
            for entity_id in entity_ids:
                candidate = Candidate(
                    entity_id=entity_id,
                    confidence=match.confidence,  # type: ignore[arg-type]
                    matched_span=match.matched_span,
                    layer=match.layer,
                    slot_type=slot_type,
                    canonical_name=self.indexes.entity_names.get(entity_id, entity_id),
                    score=match.score,
                    start=match.start,
                    end=match.end,
                )
                previous = best_by_id.get(entity_id)
                if previous is None or _candidate_key(candidate) < _candidate_key(previous):
                    best_by_id[entity_id] = candidate
        return sorted(best_by_id.values(), key=_candidate_key)


_DEFAULT_MATCHER: EntityMatcher | None = None


def configure_matcher(indexes: TaxonomyIndexes, catalog: object | None = None) -> EntityMatcher:
    global _DEFAULT_MATCHER
    _DEFAULT_MATCHER = EntityMatcher(indexes, catalog)
    return _DEFAULT_MATCHER


def resolve_slot(
    query_tokens: list[str] | tuple[str, ...],
    slot_type: SlotType,
    *,
    indexes: TaxonomyIndexes | None = None,
    catalog: object | None = None,
) -> list[Candidate]:
    """Module-level compatibility entrypoint used by simple integrations/tests."""

    matcher = EntityMatcher(indexes, catalog) if indexes is not None else _DEFAULT_MATCHER
    if matcher is None:
        raise RuntimeError("taxonomy matcher is not configured")
    return matcher.resolve_slot(query_tokens, slot_type)


__all__ = ["Candidate", "Confidence", "EntityMatcher", "configure_matcher", "resolve_slot"]
