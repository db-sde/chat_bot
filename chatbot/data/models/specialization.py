"""Typed DegreeBaba specialization publisher envelope."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from .course import Highlight, JobProfile
from .university import FAQ, PublisherModel, Review


class SpecializationMeta(PublisherModel):
    document_title: str | None = None
    page_type: Literal["specialization"] = "specialization"
    generated_by: str | None = None


class OtherSpecialization(PublisherModel):
    other_spec_name: str | None = None
    other_spec_fee: str | None = None


class Specialization(PublisherModel):
    meta: SpecializationMeta = Field(default_factory=SpecializationMeta, alias="_meta")
    id: str | None = None
    slug: str | None = None
    aliases: list[str] | None = None
    category: str | None = None
    specialization_name: str | None = None
    program_name: str | None = None
    parent_course: str | None = None

    spec_name: str | None = None
    university_name: str | None = None
    linked_university: Any | None = None
    linked_course: Any | None = None
    duration: str | None = None
    mode: str | None = None
    naac_grade: str | None = None
    ugc_status: str | None = None
    total_fee: str | None = None
    total_fee_numeric: int | float | None = None
    starting_fee: str | None = None
    starting_fee_numeric: int | float | None = None
    fee_numeric: int | float | None = None
    fee_metadata: dict[str, Any] | None = None

    about_heading: str | None = None
    highlights_heading: str | None = None
    eligibility_heading: str | None = None
    fee_heading: str | None = None
    other_specs_heading: str | None = None
    syllabus_heading: str | None = None
    exam_heading: str | None = None
    admission_heading: str | None = None
    placement_heading: str | None = None
    jobs_heading: str | None = None
    certificate_heading: str | None = None
    faqs_heading: str | None = None

    about_content: str | None = None
    eligibility_content: str | None = None
    syllabus_content: str | None = None
    exam_content: str | None = None
    admission_steps: str | list[str] | None = None
    admission_fee_note: str | None = None
    placement_content: str | None = None
    certificate_description: str | None = None
    emi_amount: str | None = None
    emi_numeric: int | float | None = None
    eligibility_category: str | None = None
    eligibility_requirements: list[str] | None = None
    career_outcomes: list[str] | None = None
    career_tracks: list[str] | None = None
    salary_outcomes: list[dict[str, Any]] | None = None
    discipline: str | None = None
    budget_bucket: str | None = None
    difficulty_level: str | None = None
    recommendation_attributes: dict[str, Any] | None = None
    recommendation_profile: dict[str, Any] | None = None
    discovery_tags: list[str] | None = None
    finder_tags: list[str] | None = None
    roi_tags: list[str] | None = None
    career_quiz_categories: list[str] | None = None
    lead_tags: list[str] | None = None
    search_keywords: list[str] | None = None
    normalized_search_keywords: list[str] | None = None
    edge_case_notes: list[str] | None = Field(default=None, alias="_edge_case_notes")

    highlights: list[Highlight] | None = None
    other_specs: list[OtherSpecialization] | None = None
    job_profiles: list[JobProfile] | None = None
    reviews: list[Review] | None = None
    faqs: list[FAQ] | None = None

    seo_title: str | None = None
    meta_description: str | None = None
    eligibility_summary: str | None = None


SpecializationModel = Specialization
SpecializationEntity = Specialization
OtherSpec = OtherSpecialization
