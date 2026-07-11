"""Typed DegreeBaba university publisher envelope."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PublisherModel(BaseModel):
    """Permissive for new publisher fields, typed for every documented field."""

    model_config = ConfigDict(extra="allow", populate_by_name=True, serialize_by_alias=True)


class UniversityMeta(PublisherModel):
    document_title: str | None = None
    page_type: Literal["university"]
    generated_by: str | None = None


class Fact(PublisherModel):
    fact_title: str | None = None
    fact_description: str | None = None


class Accreditation(PublisherModel):
    body_name: str | None = None
    body_descriptor: str | None = None
    body_detail: str | None = None


class ProgramRow(PublisherModel):
    program_name: str | None = None
    program_fee: str | None = None
    program_eligibility: str | None = None


class FacultyMember(PublisherModel):
    member_name: str | None = None
    member_program: str | None = None
    member_designation: str | None = None
    member_qualification: str | None = None


class Review(PublisherModel):
    review_text: str | None = None
    reviewer_name: str | None = None
    reviewer_label: str | None = None


class FAQ(PublisherModel):
    question: str | None = None
    answer: str | None = None


class University(PublisherModel):
    meta: UniversityMeta = Field(alias="_meta")
    id: str | None = None
    slug: str | None = None
    aliases: list[str] | None = None

    university_name: str | None = None
    university_full_name: str | None = None
    hero_description: str | None = None
    established_year: str | None = None
    naac_grade: str | None = None
    ugc_approved: str | None = None
    mode_of_learning: str | None = None
    starting_fee: str | None = None
    num_programs: str | None = None

    about_heading: str | None = None
    why_choose_heading: str | None = None
    facts_heading: str | None = None
    accreditations_heading: str | None = None
    programs_heading: str | None = None
    admission_heading: str | None = None
    emi_heading: str | None = None
    exam_heading: str | None = None
    faculty_heading: str | None = None
    placement_heading: str | None = None
    reviews_heading: str | None = None
    faqs_heading: str | None = None

    about_content: str | None = None
    why_choose_content: str | None = None
    admission_steps: str | None = None
    admission_fee_note: str | None = None
    emi_content: str | None = None
    exam_content: str | None = None
    faculty_intro: str | None = None
    placement_content: str | None = None
    programs_intro: str | None = None

    facts: list[Fact] | None = None
    accreditations: list[Accreditation] | None = None
    programs_table: list[ProgramRow] | None = None
    faculty_members: list[FacultyMember] | None = None
    reviews: list[Review] | None = None
    faqs: list[FAQ] | None = None

    seo_title: str | None = None
    meta_description: str | None = None


UniversityModel = University
UniversityEntity = University

