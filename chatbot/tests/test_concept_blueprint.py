from __future__ import annotations

import logging

import pytest
import pytest_asyncio

from config import Settings
from data.loader import CatalogStore
from main import ChatbotService
from resilience.intent_metrics import IntentMetrics
from schemas import ChatRequest
from session.store import MemorySessionStore


class NoRecognitionLLM:
    intent_configured = True
    synthesis_configured = False

    def __init__(self) -> None:
        self.intent_calls: list[str] = []

    async def decide_action_tiny(self, message: str, _summary: str):
        self.intent_calls.append(message)
        raise AssertionError(f"recognition unexpectedly reached Gemini: {message}")

    async def health(self):
        return {"status": "ok", "providers": {"fake": "ok"}}


@pytest_asyncio.fixture
async def blueprint_service():
    llm = NoRecognitionLLM()
    metrics = IntentMetrics()
    service = await ChatbotService.create(
        Settings(
            redis_url=None,
            gemini_api_key=None,
            groq_api_key=None,
            openai_api_key=None,
            lead_prompt_after_turn=100,
        ),
        session_store=MemorySessionStore(),
        llm=llm,
        intent_metrics=metrics,
    )
    yield service, llm, metrics
    await service.close()


async def turn(service: ChatbotService, message: str, session_id: str):
    return await service.process_turn(ChatRequest(message=message, session_id=session_id))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("message", "route", "expected"),
    [
        ("monypal mba fees", "clarification", "Manipal"),
        ("markting", "list_providers", "Marketing is offered"),
        ("finace", "list_providers", "Finance Management is offered"),
        ("lpuu", "clarification", "Lovely Professional University"),
        ("nmis", "clarification", "Narsee Monjee"),
    ],
)
async def test_catalog_typos_are_deterministic_and_zero_gemini(
    blueprint_service,
    message: str,
    route: str,
    expected: str,
) -> None:
    service, llm, metrics = blueprint_service
    before = metrics.snapshot()["llm_intent_calls"]

    result = await turn(service, message, f"typo-{message}")

    assert result.route == route
    assert expected in result.payload.text
    assert metrics.snapshot()["llm_intent_calls"] == before
    assert llm.intent_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("unknown", ["Harvard", "Oxford", "Stanford"])
async def test_unknown_university_is_retained_with_known_course_providers(
    blueprint_service,
    unknown: str,
) -> None:
    service, llm, metrics = blueprint_service

    result = await turn(service, f"{unknown} MBA", f"unknown-{unknown}")

    assert result.route == "fallback"
    assert unknown in result.payload.text
    assert "Available MBA providers include" in result.payload.text
    assert result.state.focus.university_concept is None
    assert result.state.focus.course_concept == "mba"
    assert result.state.focus.unknown_entities == [unknown.casefold()]
    assert metrics.snapshot()["llm_intent_calls"] == 0
    assert llm.intent_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("message", "expected_route"),
    [
        ("Marketing", "list_providers"),
        ("Finance", "list_providers"),
        ("HR", "list_providers"),
        ("MBA", "category"),
        ("MCA", "category"),
    ],
)
async def test_providerless_concepts_discover_without_clarifying(
    blueprint_service,
    message: str,
    expected_route: str,
) -> None:
    service, llm, _ = blueprint_service

    result = await turn(service, message, f"discovery-{message}")

    assert result.route == expected_route
    assert result.state.pending_clarification is None
    assert llm.intent_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    [
        "I need career guidance for MBA",
        "Which MBA specialization is best for me?",
    ],
)
async def test_known_concept_guidance_reaches_advisory_without_becoming_facts(
    blueprint_service,
    message: str,
) -> None:
    service, llm, metrics = blueprint_service

    result = await turn(service, message, f"known-guidance-{message}")

    assert result.route == "advisory"
    assert metrics.snapshot()["llm_intent_calls"] == 0
    assert llm.intent_calls == []


@pytest.mark.asyncio
async def test_weak_topic_locking_and_attribute_context(blueprint_service) -> None:
    service, llm, _ = blueprint_service
    await turn(service, "NMIMS MBA", "weak-lock")

    fee = await turn(service, "What are the fees?", "weak-lock")
    switched = await turn(service, "What is BBA?", "weak-lock")

    assert fee.route == "factual"
    assert "INR 1,96,000" in fee.payload.text
    assert switched.route == "fallback"
    assert switched.state.focus.university_concept is None
    assert switched.state.focus.course_concept is None
    assert switched.state.focus.unknown_entities == ["bba"]
    assert "NMIMS" not in switched.payload.text
    assert llm.intent_calls == []


@pytest.mark.asyncio
async def test_explicit_specialization_discovery_clears_inherited_university(
    blueprint_service,
) -> None:
    service, llm, _ = blueprint_service
    await turn(service, "NMIMS MBA", "discovery-switch")

    result = await turn(
        service,
        "Show Marketing specializations",
        "discovery-switch",
    )

    assert result.route == "list_providers"
    assert result.state.focus.university_concept is None
    assert result.state.focus.course_concept is None
    assert result.state.focus.specialization_concept == "Marketing"
    assert "5 published universities" in result.payload.text
    assert llm.intent_calls == []


@pytest.mark.asyncio
async def test_explicit_invalid_combination_is_explained(blueprint_service) -> None:
    service, llm, _ = blueprint_service

    result = await turn(service, "IGNOU MBA", "invalid-combination")

    assert result.route == "fallback"
    assert "IGNOU does not currently offer MBA" in result.payload.text
    assert "Available providers include" in result.payload.text
    assert llm.intent_calls == []


@pytest.mark.asyncio
async def test_true_acronym_ambiguity_still_clarifies(blueprint_service) -> None:
    service, llm, _ = blueprint_service

    result = await turn(service, "SMU", "true-ambiguity")

    assert result.route == "clarification"
    assert "Sikkim Manipal" in result.payload.text
    assert "Srinivas Management" in result.payload.text
    assert llm.intent_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("normal_turn", ["Browse Universities", "Marketing", "MBA", "Fees"])
async def test_pending_lead_name_never_intercepts_normal_chat(
    blueprint_service,
    normal_turn: str,
) -> None:
    service, llm, _ = blueprint_service
    session_id = f"lead-isolation-{normal_turn}"
    opened = await turn(service, "Talk to counsellor", session_id)

    result = await turn(service, normal_turn, session_id)

    assert opened.payload.cta is not None
    assert opened.payload.cta.payload == {"target_action": "OPEN_LEAD_WIDGET"}
    assert result.route != "lead"
    assert result.state.lead.name is None
    assert "valid name" not in result.payload.text.casefold()
    assert llm.intent_calls == []


@pytest.mark.asyncio
async def test_blueprint_observability_events_are_emitted(
    blueprint_service,
    caplog: pytest.LogCaptureFixture,
) -> None:
    service, _, _ = blueprint_service
    with caplog.at_level(logging.INFO):
        await turn(service, "markting", "logs-recognition")
        await turn(service, "Harvard MBA", "logs-unknown")
        await turn(service, "IGNOU MBA", "logs-validation")
        await turn(service, "SMU", "logs-clarification")

    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "[recognition]" in messages
    assert "method=\"rapidfuzz\"" in messages
    assert "[unknown_entity]" in messages
    assert "[validation]" in messages
    assert "[focus_update]" in messages
    assert "[clarification]" in messages


@pytest.mark.asyncio
async def test_btech_typo_resolves_when_btech_exists_in_catalog() -> None:
    records = [
        {
            "id": "uni-delta",
            "_meta": {"page_type": "university"},
            "university_name": "Delta University",
            "university_full_name": "Delta University",
        },
        {
            "id": "course-delta-btech",
            "_meta": {"page_type": "course"},
            "program_name": "Online BTech",
            "university_name": "Delta University",
            "category": "btech",
            "duration": "4 Years",
            "total_fee": "INR 4,00,000",
        },
    ]
    catalog = CatalogStore(records=records)
    llm = NoRecognitionLLM()
    metrics = IntentMetrics()
    service = await ChatbotService.create(
        Settings(redis_url=None, lead_prompt_after_turn=100),
        catalog=catalog,
        session_store=MemorySessionStore(),
        llm=llm,
        intent_metrics=metrics,
    )
    try:
        result = await turn(service, "betch", "catalog-btech")
    finally:
        await service.close()

    assert result.route == "clarification"
    assert "BTECH" in result.payload.text.upper()
    assert metrics.snapshot()["llm_intent_calls"] == 0
    assert llm.intent_calls == []
