"""Regression coverage for the Section A correctness gate."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import pytest_asyncio

from config import Settings
from leads.funnel import LeadFunnel
from main import ChatbotService
from schemas import ChatRequest
from session.state import ConversationState
from session.store import MemorySessionStore


class NoopWebhook:
    async def push(self, event) -> None:
        del event


@pytest_asyncio.fixture
async def service():
    settings = Settings(
        redis_url=None,
        groq_api_key=None,
        openai_api_key=None,
        lead_prompt_after_turn=100,
    )
    instance = await ChatbotService.create(settings, session_store=MemorySessionStore())
    yield instance
    await instance.close()


async def turn(service: ChatbotService, message: str, session_id: str):
    return await service.process_turn(ChatRequest(message=message, session_id=session_id))


@pytest.mark.asyncio
async def test_exact_pending_phone_reproduction_is_captured(service) -> None:
    await turn(service, "talk to a counsellor", "pending-phone")
    await turn(service, "Aryan Kinha", "pending-phone")

    result = await turn(service, "0000000000", "pending-phone")

    assert result.route == "lead"
    assert result.state.lead.phone == "0000000000"
    assert result.state.lead.last_asked_field == "email"
    assert "saved your phone" in result.payload.text.casefold()


@pytest.mark.asyncio
async def test_invalid_pending_phone_gets_specific_retry_not_discovery(service) -> None:
    await turn(service, "talk to a counsellor", "invalid-phone")
    await turn(service, "Aryan Kinha", "invalid-phone")

    result = await turn(service, "12345", "invalid-phone")

    assert result.route == "lead"
    assert result.state.lead.phone is None
    assert result.state.lead.last_asked_field == "phone"
    assert result.payload.text == (
        "That doesn't look like a valid phone number — could you share a 10-digit number?"
    )


@pytest.mark.asyncio
async def test_pending_contact_is_committed_before_product_routing(service) -> None:
    await turn(service, "talk to a counsellor", "contact-question")
    await turn(service, "Aryan Kinha", "contact-question")

    result = await turn(
        service,
        "9876543210 and what is the fee for NMIMS MBA?",
        "contact-question",
    )

    assert result.state.lead.phone == "9876543210"
    assert result.route == "factual"
    assert "INR 1,96,000" in result.payload.text


@pytest.mark.asyncio
@pytest.mark.parametrize("message", ["skip", "not now"])
async def test_pending_name_deferrals_are_not_captured(service, message: str) -> None:
    await turn(service, "talk to a counsellor", f"defer-{message}")
    result = await turn(service, message, f"defer-{message}")

    assert result.state.lead.name is None
    assert result.state.lead.last_asked_field == "name"


def test_prompted_phone_validation_accepts_any_ten_digit_shape() -> None:
    funnel = LeadFunnel(
        NoopWebhook(),
        SimpleNamespace(lead_prompt_after_turn=100, lead_prompt_interval=2),
    )
    state = ConversationState(session_id="shape")
    state.lead.last_asked_field = "phone"

    answer = funnel.inspect_pending_answer(state, "0000000000")

    assert answer is not None and answer.valid
    assert answer.values["phone"] == "0000000000"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("message", "category"),
    [
        ("Master of Business Administration", "mba"),
        ("MBA", "mba"),
        ("tell me about Master of Business Administration", "mba"),
        ("Master of Computer Applications", "mca"),
    ],
)
async def test_full_category_names_outrank_specialization_tokens(
    service,
    message: str,
    category: str,
) -> None:
    result = await turn(service, message, f"category-{category}-{message}")

    assert result.route == "category"
    assert result.state.focus.category == category
    assert result.state.focus.specialization is None
    assert result.state.focus.entity_id is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    ["for which uni", "which university", "who offers this"],
)
async def test_short_domain_followups_retain_category_focus(service, message: str) -> None:
    await turn(service, "MBA", f"focus-{message}")

    result = await turn(service, message, f"focus-{message}")

    assert result.route == "category"
    assert result.state.focus.category == "mba"
    assert result.state.focus.university is None
    assert result.state.focus.specialization is None
    assert result.state.focus.entity_id is None
