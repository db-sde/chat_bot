"""Validated catalog entity models and nested discriminator adapter."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Discriminator, Tag, TypeAdapter

from .course import (
    Course,
    CourseEntity,
    CourseMeta,
    CourseModel,
    FeePlan,
    Highlight,
    JobProfile,
)
from .specialization import (
    OtherSpec,
    OtherSpecialization,
    Specialization,
    SpecializationEntity,
    SpecializationMeta,
    SpecializationModel,
)
from .university import (
    FAQ,
    Accreditation,
    Fact,
    FacultyMember,
    ProgramRow,
    PublisherModel,
    Review,
    University,
    UniversityEntity,
    UniversityMeta,
    UniversityModel,
)


def _page_type(value: Any) -> str | None:
    if isinstance(value, dict):
        meta = value.get("_meta", value.get("meta"))
    else:
        meta = getattr(value, "meta", None)
    if isinstance(meta, dict):
        return meta.get("page_type")
    return getattr(meta, "page_type", None)


CatalogEntity = Annotated[
    Annotated[University, Tag("university")]
    | Annotated[Course, Tag("course")]
    | Annotated[Specialization, Tag("specialization")],
    Discriminator(_page_type),
]
Entity = CatalogEntity
CATALOG_ENTITY_ADAPTER = TypeAdapter(CatalogEntity)


def parse_entity(value: Any) -> CatalogEntity:
    """Validate a publisher envelope using its strict nested page-type tag."""

    return CATALOG_ENTITY_ADAPTER.validate_python(value)


__all__ = [
    "CATALOG_ENTITY_ADAPTER",
    "FAQ",
    "Accreditation",
    "CatalogEntity",
    "Course",
    "CourseEntity",
    "CourseMeta",
    "CourseModel",
    "Entity",
    "Fact",
    "FacultyMember",
    "FeePlan",
    "Highlight",
    "JobProfile",
    "OtherSpec",
    "OtherSpecialization",
    "ProgramRow",
    "PublisherModel",
    "Review",
    "Specialization",
    "SpecializationEntity",
    "SpecializationMeta",
    "SpecializationModel",
    "University",
    "UniversityEntity",
    "UniversityMeta",
    "UniversityModel",
    "parse_entity",
]
