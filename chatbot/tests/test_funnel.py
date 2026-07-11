import asyncio
from types import SimpleNamespace

import pytest

from leads.funnel import LeadFunnel
from session.state import ConversationState


class RecordingWebhook:
    def __init__(self) -> None:
        self.events = []

    async def push(self, event) -> None:
        self.events.append(event)


@pytest.fixture
def funnel() -> tuple[LeadFunnel, RecordingWebhook]:
    webhook = RecordingWebhook()
    settings = SimpleNamespace(lead_prompt_after_turn=2, lead_prompt_interval=1)
    return LeadFunnel(webhook, settings), webhook


def test_callback_starts_with_one_name_ask(funnel) -> None:
    lead_funnel, _ = funnel
    state = ConversationState(session_id="callback")
    payload = lead_funnel.handle_callback(state, "I want to talk to someone")

    assert state.lead.last_asked_field == "name"
    assert "name" in payload.text.lower()
    assert "phone" not in payload.text.lower()


@pytest.mark.asyncio
async def test_each_new_field_schedules_a_crm_snapshot(funnel) -> None:
    lead_funnel, webhook = funnel
    state = ConversationState(session_id="lead")
    state.lead.last_asked_field = "name"

    changed = lead_funnel.capture(state, "Aryan Kinha")
    await asyncio.sleep(0)

    assert changed == ["name"]
    assert state.lead.name == "Aryan Kinha"
    assert len(webhook.events) == 1
    assert webhook.events[0].captured_fields == ["name"]


def test_ignored_lead_ask_is_not_mistaken_for_a_name(funnel) -> None:
    lead_funnel, _ = funnel
    state = ConversationState(session_id="product")
    state.lead.last_asked_field = "name"

    assert lead_funnel.capture(state, "what is the mba fee?") == []
    assert state.lead.name is None

    assert lead_funnel.capture(state, "tell me about LPU") == []
    assert lead_funnel.capture(state, "compare Amity and Jain") == []


@pytest.mark.asyncio
async def test_phone_and_email_are_validated_and_normalized(funnel) -> None:
    lead_funnel, _ = funnel
    state = ConversationState(session_id="contacts")

    changed = lead_funnel.capture(state, "Reach me at +91 9876543210 or ME@Example.COM")
    await asyncio.sleep(0)

    assert changed == ["email", "phone"]
    assert state.lead.phone == "9876543210"
    assert state.lead.email == "me@example.com"


@pytest.mark.asyncio
async def test_hyphenated_indian_phone_is_normalized(funnel) -> None:
    lead_funnel, webhook = funnel
    state = ConversationState(session_id="hyphen-phone")
    changed = lead_funnel.capture(state, "+91-98765-43210")
    await asyncio.sleep(0)
    assert changed == ["phone"]
    assert state.lead.phone == "9876543210"
    assert webhook.events
