from __future__ import annotations

import pytest
import pytest_asyncio

from config import Settings
from main import ChatbotService
from schemas import ChatRequest
from session.store import MemorySessionStore


@pytest_asyncio.fixture(scope="module")
async def sprint_service() -> ChatbotService:
    service = await ChatbotService.create(
        Settings(
            redis_url=None,
            gemini_api_key=None,
            groq_api_key=None,
            openai_api_key=None,
            # A low value proves normal answers no longer activate collection.
            lead_prompt_after_turn=1,
            lead_prompt_interval=1,
        ),
        session_store=MemorySessionStore(),
    )
    yield service
    await service.close()


async def turn(service: ChatbotService, session_id: str, message: str):
    return await service.process_turn(ChatRequest(session_id=session_id, message=message))


@pytest.mark.asyncio
async def test_normal_chat_never_activates_or_populates_lead_flow(
    sprint_service: ChatbotService,
) -> None:
    overview = await turn(sprint_service, "sprint-lead-normal", "Tell me about MBA")
    browse = await turn(sprint_service, "sprint-lead-normal", "Browse universities")

    assert overview.route == "category"
    assert browse.route == "discovery"
    assert "Browse Online Universities" in browse.payload.text
    assert not browse.state.lead.active
    assert browse.state.lead.last_asked_field is None
    assert browse.state.lead.name is None
    assert "What name should our counsellor use?" not in overview.payload.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    ("Which MBA is best?", "Best MBA for me?", "Recommend a university."),
)
async def test_personal_recommendation_phrases_start_advisor(
    sprint_service: ChatbotService,
    message: str,
) -> None:
    result = await turn(sprint_service, f"sprint-advisor-trigger-{message}", message)

    assert result.route == "advisory"
    assert result.state.advisor.active
    assert result.state.advisor.last_asked_field == "current_education"
    assert "Current education" in result.payload.text


@pytest.mark.asyncio
async def test_lead_flow_is_explicit_cancellable_restartable_and_escapable(
    sprint_service: ChatbotService,
) -> None:
    started = await turn(sprint_service, "sprint-lead-life", "Request Callback")
    assert started.route == "lead"
    assert started.state.lead.active
    assert started.state.lead.name is None
    assert started.state.lead.last_asked_field == "name"

    cancelled = await turn(sprint_service, "sprint-lead-life", "cancel")
    assert cancelled.route == "lead"
    assert not cancelled.state.lead.active
    assert cancelled.state.lead.name is None

    await turn(sprint_service, "sprint-lead-life", "Talk to Counsellor")
    await turn(sprint_service, "sprint-lead-life", "Aryan Kinha")
    restarted = await turn(sprint_service, "sprint-lead-life", "restart")
    assert restarted.state.lead.active
    assert restarted.state.lead.name is None
    assert restarted.state.lead.last_asked_field == "name"

    escaped = await turn(sprint_service, "sprint-lead-life", "Browse universities")
    assert escaped.route == "discovery"
    assert not escaped.state.lead.active
    assert escaped.state.lead.last_asked_field is None


@pytest.mark.asyncio
async def test_advisor_collects_only_missing_profile_fields_then_recommends(
    sprint_service: ChatbotService,
) -> None:
    session_id = "sprint-advisor"
    education = await turn(sprint_service, session_id, "Which MBA is best for me?")
    experience = await turn(sprint_service, session_id, "Completed graduation")
    goal = await turn(sprint_service, session_id, "2 years")
    budget = await turn(sprint_service, session_id, "Marketing career")
    specialization = await turn(sprint_service, session_id, "2 lakh")
    result = await turn(sprint_service, session_id, "Finance")

    assert education.route == "advisory" and "Current education" in education.payload.text
    assert "Work experience" in experience.payload.text
    assert "Career goal" in goal.payload.text
    assert "Budget" in budget.payload.text
    assert "Preferred specialization" in specialization.payload.text
    assert result.route == "advisory"
    assert "Recommended programs" in result.payload.text
    assert "Why it matches" in result.payload.text
    assert result.payload.text.count("### ") == 3
    assert result.state.advisor.current_education == "Completed graduation"
    assert result.state.advisor.work_experience == "2 years"
    assert result.state.advisor.career_goal == "Marketing career"
    assert result.state.advisor.budget == 200_000
    assert result.state.advisor.preferred_specialization == "Finance"
    assert not result.state.advisor.active


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "experience",
    ("Fresher", "Less than 2 years", "2-5 years", "More than 5 years"),
)
async def test_every_suggested_experience_action_advances_advisor(
    sprint_service: ChatbotService,
    experience: str,
) -> None:
    session_id = f"sprint-advisor-experience-{experience}"
    await turn(sprint_service, session_id, "Which MBA is best for me?")
    await turn(sprint_service, session_id, "Completed graduation")

    result = await turn(sprint_service, session_id, experience)

    assert result.route == "advisory"
    assert result.state.advisor.work_experience == experience
    assert "Career goal" in result.payload.text


@pytest.mark.asyncio
async def test_advisor_does_not_consume_an_unrelated_question(
    sprint_service: ChatbotService,
) -> None:
    session_id = "sprint-advisor-break"
    await turn(sprint_service, session_id, "Best MBA for me?")
    unrelated = await turn(sprint_service, session_id, "What is pi?")

    assert unrelated.route == "fallback"
    assert not unrelated.state.advisor.active
    assert unrelated.state.advisor.current_education is None
    assert unrelated.state.focus.entity_id is None


@pytest.mark.asyncio
async def test_advisor_reentry_asks_only_still_missing_fields(
    sprint_service: ChatbotService,
) -> None:
    session_id = "sprint-advisor-resume"
    await turn(sprint_service, session_id, "Best MBA for me?")
    await turn(sprint_service, session_id, "Completed graduation")
    await turn(sprint_service, session_id, "What is pi?")

    resumed = await turn(sprint_service, session_id, "Which MBA is best for me?")

    assert resumed.route == "advisory"
    assert resumed.state.advisor.current_education == "Completed graduation"
    assert resumed.state.advisor.last_asked_field == "work_experience"
    assert "Work experience" in resumed.payload.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("message", "expected_route", "required_text"),
    [
        ("Show MBA universities", "category", "Published Universities"),
        (
            "Universities with Finance specialization",
            "list_providers",
            "Published Universities",
        ),
        ("Cheapest MBA", "advisory", "lower-cost MBA options"),
        ("Top online MBA programs", "advisory", "ranking data"),
        ("MBA under 2 lakh", "advisory", "INR 2,00,000"),
    ],
)
async def test_discovery_queries_use_catalog_retrieval(
    sprint_service: ChatbotService,
    message: str,
    expected_route: str,
    required_text: str,
) -> None:
    result = await turn(sprint_service, f"sprint-discovery-{message}", message)

    assert result.route == expected_route
    assert required_text in result.payload.text


@pytest.mark.asyncio
async def test_comparison_and_context_rules(
    sprint_service: ChatbotService,
) -> None:
    comparison = await turn(
        sprint_service,
        "sprint-compare",
        "Compare NMIMS and Amity",
    )
    assert comparison.route == "comparison"
    assert "NMIMS" in comparison.payload.text
    assert "Amity" in comparison.payload.text
    assert all("NMIMS" in chip and "Amity" in chip for chip in comparison.payload.suggested_chips)

    session_id = "sprint-context"
    await turn(sprint_service, session_id, "Tell me about NMIMS MCA")
    fee = await turn(sprint_service, session_id, "What are the fees?")
    assert fee.route == "factual"
    assert fee.state.focus.entity_id == "course-nmims-mca"
    assert "published total fee" in fee.payload.text

    unrelated = await turn(sprint_service, session_id, "What is pi?")
    assert unrelated.route == "fallback"
    assert unrelated.state.focus.entity_id is None
    assert unrelated.state.focus.university_concept is None
    assert unrelated.state.focus.course_concept is None
