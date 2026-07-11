"""Catalog loading, validation, and defensive access."""

from .accessor import safe_get
from .loader import SAMPLE_CATALOG_PATH, CatalogStore, DataStore, EntityMetadata
from .models import CatalogEntity, Course, Specialization, University, parse_entity

__all__ = [
    "SAMPLE_CATALOG_PATH",
    "CatalogEntity",
    "CatalogStore",
    "Course",
    "DataStore",
    "EntityMetadata",
    "Specialization",
    "University",
    "parse_entity",
    "safe_get",
]
