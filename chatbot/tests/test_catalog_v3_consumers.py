"""Consumer-layer compatibility checks for the immutable Catalog V3 fixture."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from data.loader import SAMPLE_CATALOG_PATH, CatalogStore
from funnel import ChipEngine, ChipMapStore, JourneyEngine
from main import ChatbotService
from presentation.cards import build_comparison_card, build_entity_card
from presentation.chips import catalog_chip_context
from presentation.experience import catalog_options
from presentation.guided_navigation import guide_context
from response.cards import entity_label
from response.templates import (
    accreditation_items,
    fee_answer,
    reviews_answer,
    topic_from_message,
)
from routing.factual_handler import handle_factual


@pytest.fixture(scope="module")
async def v3_catalog() -> CatalogStore:
    return await CatalogStore.create(catalog_path=SAMPLE_CATALOG_PATH)


def test_v3_entities_load_without_legacy_meta(v3_catalog: CatalogStore) -> None:
    counts = {
        page_type: len(v3_catalog.list_metadata(page_type))
        for page_type in ("university", "course", "specialization")
    }

    assert counts == {"university": 15, "course": 53, "specialization": 89}
    assert v3_catalog.get_metadata("course-nmims-mca").category == "mca"
    assert v3_catalog.get_metadata("spec-nmims-mca-cloud-computing").category == "mca"


def test_v3_cards_use_relationships_ratings_and_specific_labels(
    v3_catalog: CatalogStore,
) -> None:
    university = v3_catalog.get_entity("uni-nmims")
    course = v3_catalog.get_entity("course-nmims-mca")
    specialization = v3_catalog.get_entity("spec-nmims-mca-cloud-computing")

    university_card = build_entity_card(university, v3_catalog)
    course_card = build_entity_card(course, v3_catalog)
    specialization_card = build_entity_card(specialization, v3_catalog)

    assert university_card.program_count == len(university.program_ids)
    assert university_card.programs == ["MCA", "MCom", "BCA", "MSc AI & ML"]
    assert course_card.average_rating == course.average_rating
    assert course_card.review_count == course.review_count
    assert course_card.specialization_count == len(course.specialization_ids)
    assert specialization_card.name == specialization.specialization_name
    assert entity_label(specialization) == specialization.specialization_name


def test_v3_structured_accreditations_fees_and_reviews(v3_catalog: CatalogStore) -> None:
    university = v3_catalog.get_entity("uni-nmims")
    course = v3_catalog.get_entity("course-nmims-mca")

    accreditations = accreditation_items(university)
    assert "UGC — Entitled" in accreditations
    assert "AICTE — Approved" in accreditations
    assert "NAAC — Accredited (NAAC grade A+)" in accreditations
    assert "Catalog fee metadata: starting, semester, INR." in fee_answer(course)

    lms_reviews = reviews_answer(course, theme="lms")
    assert f"{course.average_rating}/5 from {course.review_count} reviews" in lms_reviews
    assert "LMS platform" in lms_reviews
    assert "career growth" not in lms_reviews.casefold()


@pytest.mark.parametrize(
    ("message", "topic"),
    [
        ("Student Reviews", "reviews"),
        ("Average Rating", "average_rating"),
        ("Faculty Reviews", "faculty_reviews"),
        ("Placement Reviews", "placement_reviews"),
        ("LMS Reviews", "lms_reviews"),
        ("Flexibility Reviews", "flexibility_reviews"),
    ],
)
def test_v3_review_surfaces_route_to_their_structured_topic(
    message: str,
    topic: str,
) -> None:
    assert topic_from_message(message) == topic


@pytest.mark.asyncio
async def test_exact_v3_faq_is_returned_without_synthesis(v3_catalog: CatalogStore) -> None:
    course = v3_catalog.get_entity("course-nmims-mca")
    faq = course.faqs[0]

    class UnexpectedLLM:
        synthesis_configured = True
        calls = 0

        async def synthesize(self, _prompt: str) -> str:
            self.calls += 1
            return "unexpected"

    llm = UnexpectedLLM()
    payload = await handle_factual(
        message=faq.question,
        entity=course,
        catalog=v3_catalog,
        llm=llm,
    )

    assert payload.text == faq.answer
    assert llm.calls == 0


def test_guided_consumers_use_exact_links_and_structured_info(
    v3_catalog: CatalogStore,
) -> None:
    context = guide_context(
        v3_catalog,
        page_type="course",
        entity_id="course-nmims-mca",
    )

    assert context is not None
    assert [item["id"] for item in context["related"]["specializations"]] == [
        "spec-nmims-mca-cloud-computing"
    ]
    assert context["info"]["fees"]["fee_numeric"] == 158_000
    assert context["info"]["fees"]["fee_metadata"] == {
        "currency": "INR",
        "fee_type": "starting",
        "billing_cycle": "semester",
    }
    assert context["info"]["reviews"]["review_count"] == 3
    assert {item["theme"] for item in context["info"]["reviews"]["testimonials"]} == {
        "career growth",
        "flexibility",
        "lms",
    }


def test_university_reviews_use_only_published_linked_program_reviews(
    v3_catalog: CatalogStore,
) -> None:
    context = guide_context(
        v3_catalog,
        page_type="university",
        entity_id="uni-nmims",
    )

    assert context is not None
    reviews = context["info"]["reviews"]
    assert reviews["available"] is True
    assert reviews["review_count"] == 16
    assert reviews["scope_label"] == (
        "Published reviews across 4 NMIMS Global Access programs"
    )
    assert {item["reviewer_label"] for item in reviews["testimonials"]} == {
        "MCA",
        "MCom",
        "BCA",
        "MSc AI & ML",
    }
    assert all(item["text"] for item in reviews["testimonials"])


def test_v3_opening_chips_follow_published_entity_capabilities(
    v3_catalog: CatalogStore,
) -> None:
    journey = JourneyEngine(ChipMapStore(auto_reload=False))
    nmims = v3_catalog.get_entity("uni-nmims")
    amity = v3_catalog.get_entity("uni-amity")
    no_specializations = v3_catalog.get_entity("course-sikkim-manipal-bba")

    nmims_opening = journey.opening(
        "university",
        entity_context=catalog_chip_context(nmims, v3_catalog),
    )
    amity_opening = journey.opening(
        "university",
        entity_context=catalog_chip_context(amity, v3_catalog),
    )
    course_opening = journey.opening(
        "course",
        entity_context=catalog_chip_context(no_specializations, v3_catalog),
    )

    assert [chip.id for chip in nmims_opening.top] == [
        "programs_here",
        "placement_support",
        "reviews",
        "counsellor",
    ]
    assert "reviews" in {chip.id for chip in nmims_opening.top}
    assert [chip.id for chip in (*amity_opening.top, *amity_opening.more)] == [
        "programs_here",
        "placement_support",
        "reviews",
        "counsellor",
        "approvals",
        "why_choose",
        "compare_others",
        "average_rating",
    ]
    assert "specializations" not in {chip.id for chip in course_opening.top}


def test_v3_followup_chips_remove_unanswerable_specialization_actions(
    v3_catalog: CatalogStore,
) -> None:
    specialization = v3_catalog.get_entity("spec-nmims-mca-cloud-computing")
    result = ChipEngine(ChipMapStore(auto_reload=False)).lookup(
        page_type="specialization",
        card_type="specialization",
        interaction_count=1,
        entity_context=catalog_chip_context(specialization, v3_catalog),
    )

    chip_ids = [chip.id for chip in result.chips]
    assert chip_ids == ["careers", "fees_emi", "eligibility", "apply_now"]
    assert "reviews" not in chip_ids
    assert "syllabus" not in chip_ids


def test_program_picker_deduplicates_by_program_not_v3_discipline(
    v3_catalog: CatalogStore,
) -> None:
    options, _ = catalog_options(v3_catalog, "program")
    names = {option.name for option in options}

    assert {"MCA", "MCom", "BCA", "MSc AI & ML"}.issubset(names)
    assert len(options) == len(names)
    assert len(options) > 5


def test_comparison_and_analytics_use_v3_structures(v3_catalog: CatalogStore) -> None:
    university = v3_catalog.get_entity("uni-nmims")
    comparison = build_comparison_card(
        [university, v3_catalog.get_entity("uni-amity")],
        v3_catalog,
    )
    facts = {fact.label: fact.value for fact in comparison.items[0].facts}

    assert facts["NAAC grade"] == university.comparison_attributes["naac_grade"]
    assert facts["NIRF rank"] == str(university.comparison_attributes["nirf_rank"])
    assert facts["Placement support"] == "Available"
    assert facts["Industry projects"] == "Available"

    service = SimpleNamespace(catalog=v3_catalog)
    dimensions = ChatbotService.catalog_analytics_dimensions(
        service,
        "course-nmims-mca",
    )
    assert dimensions["review_count"] == 3
    assert dimensions["average_rating"] == 4.5
    assert dimensions["career_outcomes"]
    assert dimensions["fee_metadata"]["currency"] == "INR"
