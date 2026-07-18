"""Typed DegreeBaba course publisher envelope."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from .university import FAQ, Accreditation, PublisherModel, Review


class CourseMeta(PublisherModel):
    document_title: str | None = None
    page_type: Literal["course"] = "course"
    generated_by: str | None = None


class Highlight(PublisherModel):
    highlight_title: str | None = None
    highlight_description: str | None = None


class FeePlan(PublisherModel):
    plan_name: str | None = None
    plan_amount: str | None = None
    plan_total: str | None = None
    plan_note: str | None = None


class JobProfile(PublisherModel):
    job_title: str | None = None
    avg_salary: str | None = None
    salary_numeric: int | float | None = None


class Course(PublisherModel):
    meta: CourseMeta = Field(default_factory=CourseMeta, alias="_meta")
    id: str | None = None
    slug: str | None = None
    aliases: list[str] | None = None
    category: str | None = None

    program_name: str | None = None
    university_name: str | None = None
    linked_university: Any | None = None
    hero_description: str | None = None
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
    num_specializations: str | None = None
    specialization_ids: list[str] | None = None
    discipline: str | None = None
    budget_bucket: str | None = None
    difficulty_level: str | None = None

    about_heading: str | None = None
    highlights_heading: str | None = None
    accreditations_heading: str | None = None
    specializations_heading: str | None = None
    fee_heading: str | None = None
    eligibility_heading: str | None = None
    admission_heading: str | None = None
    syllabus_heading: str | None = None
    placement_heading: str | None = None
    jobs_heading: str | None = None
    faqs_heading: str | None = None

    about_content: str | None = None
    specializations_intro: str | None = None
    eligibility_content: str | None = None
    admission_steps: str | list[str] | None = None
    admission_fee_note: str | None = None
    syllabus_content: str | None = None
    placement_content: str | None = None
    certificate_description: str | None = None
    validity: str | None = None
    emi_amount: str | None = None
    emi_numeric: int | float | None = None
    eligibility_category: str | None = None
    eligibility_requirements: list[str] | None = None
    career_outcomes: list[str] | None = None
    career_tracks: list[str] | None = None
    salary_outcomes: list[dict[str, Any]] | None = None
    accreditations: list[Accreditation] | None = None
    average_rating: float | None = None
    review_count: int | None = None
    recommendation_attributes: dict[str, Any] | None = None
    recommendation_profile: dict[str, Any] | None = None
    discovery_tags: list[str] | None = None
    finder_tags: list[str] | None = None
    roi_tags: list[str] | None = None
    scholarship_available: bool | None = None
    scholarship_types: list[str] | None = None
    lead_tags: list[str] | None = None
    search_keywords: list[str] | None = None
    normalized_search_keywords: list[str] | None = None
    edge_case_notes: list[str] | None = Field(default=None, alias="_edge_case_notes")

    highlights: list[Highlight] | None = None
    fee_plans: list[FeePlan] | None = None
    job_profiles: list[JobProfile] | None = None
    reviews: list[Review] | None = None
    faqs: list[FAQ] | None = None

    seo_title: str | None = None
    meta_description: str | None = None
    eligibility_summary: str | None = None


CourseModel = Course
CourseEntity = Course
