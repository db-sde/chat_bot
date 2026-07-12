from types import SimpleNamespace

import pytest

from config import Settings
from main import ChatbotService
from response.templates import about_answer, provider_answer, render_topic, topic_from_message
from routing.advisory_handler import handle_advisory, parse_budget
from schemas import ChatRequest
from session.store import MemorySessionStore


def _state(category: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(focus=SimpleNamespace(category=category))


def _course(entity_id: str, university: str, fee: str) -> dict:
    return {
        "id": entity_id,
        "_meta": {"page_type": "course"},
        "category": "mba",
        "program_name": "Online MBA",
        "university_name": university,
        "total_fee": fee,
    }


def _specialization(
    entity_id: str,
    name: str,
    university: str,
    fee: str,
    salary: str | None = None,
) -> dict:
    entity = {
        "id": entity_id,
        "_meta": {"page_type": "specialization"},
        "category": "mba",
        "specialization_name": name,
        "spec_name": name,
        "university_name": university,
        "total_fee": fee,
    }
    if salary:
        entity["job_profiles"] = [
            {"job_title": f"{name} role", "avg_salary": salary}
        ]
    return entity


def test_about_falls_back_to_structured_published_fields() -> None:
    answer = about_answer(
        {
            "spec_name": "Marketing",
            "university_name": "NMIMS Online",
            "duration": "2 Years",
            "mode": "Online",
            "total_fee": "INR 1,96,000",
            "eligibility_summary": "Graduation from a recognized university",
        }
    )

    assert "Marketing is offered by NMIMS Online" in answer
    assert "duration: 2 Years" in answer
    assert "mode: Online" in answer
    assert "fee: INR 1,96,000" in answer
    assert "eligibility: Graduation from a recognized university" in answer
    assert "don't have published" not in answer


def test_provider_answer_prefers_name_and_resolves_linked_university() -> None:
    direct = provider_answer(
        {"spec_name": "Finance Management", "university_name": "Jain University Online"}
    )
    assert direct == "Finance Management is offered by Jain University Online."

    catalog = {
        "uni-jain": {
            "id": "uni-jain",
            "_meta": {"page_type": "university"},
            "university_full_name": "Jain University Online",
        }
    }
    linked = {"spec_name": "Finance Management", "linked_university": "uni-jain"}
    assert render_topic("provider", linked, catalog=catalog) == direct


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Which university offers MBA Finance?", "provider"),
        ("Who offers Finance Management?", "provider"),
        ("What job can I get after this?", "jobs"),
        ("What roles are available?", "jobs"),
        ("What are the career opportunities?", "jobs"),
        ("Tell me about salary prospects", "jobs"),
        ("What package and earnings are published?", "jobs"),
        ("What career support is available?", "placements"),
    ],
)
def test_topic_synonyms_are_deterministic(message: str, expected: str) -> None:
    assert topic_from_message(message) == expected


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("I have a budget of 1.8 lakh", 180_000),
        ("My maximum is 1.8 lakhs", 180_000),
        ("Budget 1.8L", 180_000),
        ("I can spend 180000", 180_000),
        ("My budget is ₹1,80,000", 180_000),
        ("Keep it under INR 180,000", 180_000),
        ("It is a 2 year program", None),
    ],
)
def test_parse_budget_formats(message: str, expected: float | None) -> None:
    assert parse_budget(message) == expected


@pytest.mark.asyncio
async def test_budget_ceiling_filters_out_more_expensive_mba_options() -> None:
    catalog = {
        "lpu": _course("lpu", "Lovely Professional University", "INR 1,60,000"),
        "manipal": _course("manipal", "Manipal University Jaipur", "INR 1,75,000"),
        "nmims": _course("nmims", "NMIMS Online", "INR 1,96,000"),
        "jain": _course("jain", "Jain University Online", "INR 1,96,000"),
    }
    category_index = {"mba": tuple(catalog)}

    result = await handle_advisory(
        _state("mba"),
        "I have a budget of 1.8 lakh. Which MBA should I choose?",
        catalog,
        category_index,
    )

    assert "INR 1,80,000" in result.text
    assert "Lovely Professional University" in result.text
    assert "Manipal University Jaipur" in result.text
    assert "NMIMS Online" not in result.text
    assert "Jain University Online" not in result.text


@pytest.mark.asyncio
async def test_budget_ceiling_reports_explicit_no_fit() -> None:
    catalog = {
        "lpu": _course("lpu", "Lovely Professional University", "INR 1,60,000"),
        "manipal": _course("manipal", "Manipal University Jaipur", "INR 1,75,000"),
    }

    result = await handle_advisory(
        _state("mba"),
        "My MBA budget is ₹1,50,000",
        catalog,
        {"mba": tuple(catalog)},
    )

    assert "couldn't find any published MBA option" in result.text
    assert "at or below INR 1,50,000" in result.text


@pytest.mark.asyncio
async def test_budget_does_not_treat_per_term_starting_fee_as_total() -> None:
    catalog = {
        "unknown-total": {
            "id": "unknown-total",
            "_meta": {"page_type": "course"},
            "category": "mba",
            "program_name": "Online MBA",
            "university_name": "Example University",
            "starting_fee": "INR 40,000 per semester",
        }
    }

    result = await handle_advisory(
        _state("mba"),
        "My MBA budget is INR 50,000",
        catalog,
        {"mba": ("unknown-total",)},
    )

    assert "couldn't find any published MBA option" in result.text
    assert "Example University" not in result.text


@pytest.mark.asyncio
async def test_career_ranking_uses_only_published_average_salary_data() -> None:
    catalog = {
        "marketing": _specialization(
            "marketing", "Marketing", "Lovely Professional University", "INR 1,60,000", "INR 8 LPA"
        ),
        "analytics": _specialization(
            "analytics", "Business Analytics", "NMIMS Online", "INR 1,96,000", "INR 7.5 LPA"
        ),
        "hr": _specialization(
            "hr",
            "Human Resource Management",
            "Lovely Professional University",
            "INR 1,60,000",
            "INR 7 LPA",
        ),
        "finance": _specialization(
            "finance", "Finance Management", "Jain University Online", "INR 1,96,000", "INR 6.5 LPA"
        ),
        "unpublished": _specialization(
            "unpublished", "Operations", "Example University", "INR 1,50,000"
        ),
    }

    result = await handle_advisory(
        _state(),
        "Which specialization has the best career opportunities?",
        catalog,
    )

    assert result.text.index("Marketing at") < result.text.index("Business Analytics at")
    assert result.text.index("Business Analytics at") < result.text.index("Human Resource")
    assert result.text.index("Human Resource") < result.text.index("Finance Management")
    assert "Operations" not in result.text
    assert "published average-salary figures" in result.text
    assert "not a placement guarantee" in result.text


@pytest.mark.asyncio
async def test_same_specialization_candidate_ids_become_bounded_shortlist() -> None:
    catalog = {
        "lpu-marketing": _specialization(
            "lpu-marketing", "Marketing", "Lovely Professional University", "INR 1,60,000"
        ),
        "nmims-marketing": _specialization(
            "nmims-marketing", "Marketing", "NMIMS Online", "INR 1,96,000"
        ),
    }

    result = await handle_advisory(
        _state("mba"),
        "Which Online MBA is best for Marketing?",
        catalog,
        candidate_ids=("lpu-marketing", "nmims-marketing"),
    )

    assert "2 published Marketing options" in result.text
    assert "Lovely Professional University" in result.text
    assert "NMIMS Online" in result.text
    assert "lower fees, published career data, or accreditation" in result.text


@pytest.mark.asyncio
async def test_finance_provider_and_job_followup_use_published_record() -> None:
    service = await ChatbotService.create(
        Settings(redis_url=None, lead_prompt_after_turn=100),
        session_store=MemorySessionStore(),
    )
    try:
        provider = await service.process_turn(
            ChatRequest(
                message="Which university offers Finance specialization?",
                session_id="finance-provider-jobs",
            )
        )
        jobs = await service.process_turn(
            ChatRequest(message="What jobs can I get?", session_id="finance-provider-jobs")
        )
    finally:
        await service.close()

    assert provider.route == "list_providers"
    assert "Finance Management is offered by 1 published university" in provider.payload.text
    assert "Jain University Online" in provider.payload.text
    assert jobs.route == "factual"
    assert "Financial Analyst (INR 6.5 LPA)" in jobs.payload.text


@pytest.mark.asyncio
async def test_accreditation_and_fee_query_shortlists_universities_not_categories() -> None:
    service = await ChatbotService.create(
        Settings(
            redis_url=None,
            gemini_api_key=None,
            lead_prompt_after_turn=100,
        ),
        session_store=MemorySessionStore(),
    )
    try:
        result = await service.process_turn(
            ChatRequest(
                message="Which university has the highest accreditation and reasonable fees?",
                session_id="accreditation-fees",
            )
        )
    finally:
        await service.close()

    assert result.route == "advisory"
    assert "highest published NAAC grade" in result.payload.text
    assert "A++" in result.payload.text
    assert "Indira Gandhi National Open University" in result.payload.text
    assert "Lovely Professional University Online" in result.payload.text
    assert "Jain University Online" in result.payload.text
    assert "MCA currently has the lowest" not in result.payload.text
