"""DegreeBaba taxonomy indexing and candidate matching."""

from .category_index import CategoryIndex
from .entity_matcher import Candidate, EntityMatcher, configure_matcher, resolve_slot
from .index_builder import TaxonomyIndexes, build_indexes, category_entity_id, normalize_category

__all__ = [
    "Candidate",
    "CategoryIndex",
    "EntityMatcher",
    "TaxonomyIndexes",
    "build_indexes",
    "category_entity_id",
    "configure_matcher",
    "normalize_category",
    "resolve_slot",
]
