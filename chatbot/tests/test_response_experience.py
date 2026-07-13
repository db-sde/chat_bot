from types import SimpleNamespace

import pytest

from response.templates import (
    about_answer,
    ranking_answer,
    suggested_chips,
)
from routing.category_handler import handle_category
from routing.comparison_handler import handle_comparison
from routing.factual_handler import handle_factual
from routing.list_handler import handle_list_providers, handle_list_specializations


def _course(
    entity_id: str = "course-nmims-mba",
    university: str = "NMIMS",
) -> dict:
    return {
        "id": entity_id,
        "_meta": {"page_type": "course"},
        "category": "mba",
        "program_name": "Online MBA",
        "university_name": university,
        "hero_description": "An industry-aligned online management program.",
        "duration": "2 Years",
        "mode": "Online",
        "total_fee": "INR 1,96,000",
        "starting_fee": "INR 49,000 per semester",
        "eligibility_summary": "Bachelor's degree from a recognized university",
        "ugc_status": "UGC Entitled",
        "naac_grade": "A+",
        "accreditations": [
            {
                "body_name": "UGC-DEB",
                "body_descriptor": "Entitled",
            }
        ],
        "rankings": [
            {
                "organization": "Example Education Survey",
                "rank": "#5",
                "year": "2025",
            }
        ],
        "placement_content": "Resume reviews and interview preparation are available.",
        "job_profiles": [{"job_title": "Marketing Manager", "avg_salary": "INR 8 LPA"}],
    }


def _specialization(
    entity_id: str,
    name: str,
    university: str = "NMIMS",
    course_id: str = "course-nmims-mba",
) -> dict:
    return {
        "id": entity_id,
        "_meta": {"page_type": "specialization"},
        "category": "mba",
        "specialization_name": name,
        "spec_name": name,
        "university_name": university,
        "linked_course": course_id,
        "total_fee": "INR 1,96,000",
    }


def test_overview_uses_structured_catalog_sections_and_related_records() -> None:
    course = _course()
    catalog = {
        course["id"]: course,
        "marketing": _specialization("marketing", "Marketing"),
        "finance": _specialization("finance", "Finance"),
    }

    text = about_answer(course, catalog)

    assert text.startswith("NMIMS Online MBA")
    assert "Overview:\n• An industry-aligned" in text
    assert "Published Details:" in text
    assert "• duration: 2 Years" in text
    assert "• eligibility: Bachelor's degree" in text
    assert "Approvals & Accreditations:" in text
    assert "UGC-DEB — Entitled" in text
    assert "Popular Specializations:\n• Marketing\n• Finance" in text
    assert "Placement Support:" in text
    assert "Career Outcomes:" in text
    assert "Published Rankings:" in text
    assert "Example Education Survey — #5 — 2025" in text


def test_absent_ranking_is_reported_honestly() -> None:
    text = ranking_answer(
        {
            "_meta": {"page_type": "university"},
            "university_name": "Example University",
        }
    )

    assert "don't have published ranking information" in text
    assert "top" not in text.casefold()


def test_quick_actions_are_published_data_driven_and_subject_qualified() -> None:
    course = _course()
    course["placement_content"] = None
    course["job_profiles"] = []
    catalog = {
        course["id"]: course,
        "marketing": _specialization("marketing", "Marketing"),
    }

    chips = suggested_chips(course, "about", catalog=catalog)

    assert chips == [
        "NMIMS Online MBA Fees",
        "NMIMS Online MBA Eligibility",
        "NMIMS Online MBA Specializations",
        "Compare NMIMS Online MBA with another university",
    ]
    assert all("Placement" not in chip for chip in chips)


@pytest.mark.asyncio
async def test_factual_handler_returns_structured_overview_and_dynamic_actions() -> None:
    course = _course()
    catalog = {
        course["id"]: course,
        "marketing": _specialization("marketing", "Marketing"),
    }

    payload = await handle_factual(
        message="Tell me about NMIMS MBA",
        catalog=catalog,
        entity=course,
        use_llm=False,
    )

    assert "Published Details:" in payload.text
    assert payload.suggested_chips
    assert all("NMIMS" in chip for chip in payload.suggested_chips)


@pytest.mark.asyncio
async def test_category_and_list_responses_use_headings_and_bullets() -> None:
    first = _course("alpha-mba", "Alpha University")
    second = _course("beta-mba", "Beta University")
    marketing = _specialization(
        "alpha-marketing",
        "Marketing",
        university="Alpha University",
        course_id="alpha-mba",
    )
    catalog = {item["id"]: item for item in (first, second, marketing)}
    index = {"mba": tuple(catalog)}

    category = await handle_category(
        message="Show MBA universities",
        catalog=catalog,
        category_index=index,
        category="mba",
    )
    specializations = await handle_list_specializations(
        catalog=catalog,
        category_index=index,
        category="mba",
    )
    providers = await handle_list_providers(
        catalog=catalog,
        category_index=SimpleNamespace(
            entities_for_specialization=lambda _value: ("alpha-marketing",)
        ),
        specialization="Marketing",
    )

    assert category.text.startswith("MBA Programs")
    assert "Published Universities:\n• Alpha University\n• Beta University" in category.text
    assert "MBA Career Scope" in category.suggested_chips
    assert "Compare Alpha University and Beta University MBA" in category.suggested_chips
    assert specializations.text.startswith("MBA Specializations")
    assert "Published Options:\n• Marketing" in specializations.text
    assert providers.text.startswith("Marketing Programs")
    assert "Published Universities:\n• Alpha University" in providers.text


@pytest.mark.asyncio
async def test_category_career_action_returns_published_roles() -> None:
    first = _course("alpha-mba", "Alpha University")
    second = _course("beta-mba", "Beta University")
    catalog = {item["id"]: item for item in (first, second)}

    payload = await handle_category(
        message="MBA Career Scope",
        catalog=catalog,
        category_index={"mba": tuple(catalog)},
        category="mba",
    )

    assert payload.text.startswith("MBA Career Scope")
    assert "Published Career Outcomes:\n• Marketing Manager" in payload.text
    assert "actual outcomes depend" in payload.text


@pytest.mark.asyncio
async def test_comparison_actions_repeat_operands_and_dimension_is_honored() -> None:
    alpha = {
        "id": "alpha",
        "_meta": {"page_type": "university"},
        "university_name": "Alpha University",
        "university_full_name": "Alpha University Online",
        "starting_fee": "INR 1,50,000",
        "programs_table": [
            {
                "program_name": "Online MBA",
                "program_fee": "INR 1,50,000",
                "program_eligibility": "Bachelor's degree",
            }
        ],
        "placement_content": "Interview preparation and recruiter connects.",
    }
    beta = {
        "id": "beta",
        "_meta": {"page_type": "university"},
        "university_name": "Beta University",
        "university_full_name": "Beta University Online",
        "starting_fee": "INR 1,70,000",
        "programs_table": [
            {
                "program_name": "Online MBA",
                "program_fee": "INR 1,70,000",
                "program_eligibility": "Bachelor's degree",
            }
        ],
        "placement_content": "Career coaching and interview preparation.",
    }
    catalog = {"alpha": alpha, "beta": beta}

    overview = await handle_comparison(
        message="Compare Alpha University and Beta University",
        catalog=catalog,
        universities=("alpha", "beta"),
    )
    placements = await handle_comparison(
        message="Compare Alpha University and Beta University placements",
        catalog=catalog,
        universities=("alpha", "beta"),
    )

    assert overview.text.startswith("University Comparison")
    assert overview.suggested_chips
    assert all("Alpha University and Beta University" in chip for chip in overview.suggested_chips)
    assert "Compare Alpha University and Beta University placements" in overview.suggested_chips
    assert "placement support Interview preparation" in placements.text
    assert "placement support Career coaching" in placements.text
