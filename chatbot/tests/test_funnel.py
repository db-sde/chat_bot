import asyncio
from types import SimpleNamespace

import pytest

from leads.funnel import LeadFunnel
from response.builder import build_response
from response.cta import callback_cta, lead_capture_cta
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

    assert state.lead.active is True
    assert state.lead.last_asked_field == "name"
    assert "name" in payload.text.lower()
    assert "phone" not in payload.text.lower()
    assert payload.cta is not None
    assert payload.cta.action == "lead_capture"
    assert payload.cta.payload == {"target_action": "OPEN_LEAD_WIDGET"}


def test_chat_navigation_yields_to_product_routing(funnel) -> None:
    lead_funnel, _ = funnel

    assert lead_funnel.is_deferral("Browse Universities")
    assert lead_funnel.is_deferral("Keep exploring programs")


@pytest.mark.parametrize(
    ("message", "command"),
    [
        ("cancel", "cancel"),
        ("Never mind.", "cancel"),
        ("not now", "cancel"),
        ("restart", "restart"),
        ("start over", "restart"),
        ("reset callback form", "restart"),
        ("How do I restart my application?", None),
    ],
)
def test_lifecycle_commands_are_exact(message: str, command: str | None, funnel) -> None:
    lead_funnel, _ = funnel

    assert lead_funnel.lifecycle_command(message) == command


def test_cancel_command_precedes_name_parsing(funnel) -> None:
    lead_funnel, _ = funnel
    state = ConversationState(session_id="cancel")
    lead_funnel.handle_callback(state, "Talk to a counsellor")

    payload = lead_funnel.handle_lifecycle_command(state, "cancel")

    assert payload is not None
    assert "cancelled" in payload.text
    assert state.lead.active is False
    assert state.lead.last_asked_field is None
    assert state.lead.name is None
    assert lead_funnel.capture(state, "cancel", allow_lowercase_name=True) == []


def test_restart_clears_partial_contact_data_and_asks_for_name(funnel) -> None:
    lead_funnel, _ = funnel
    state = ConversationState(session_id="restart")
    state.lead.active = True
    state.lead.name = "Aryan Kinha"
    state.lead.phone = "9876543210"
    state.lead.email = "aryan@example.com"
    state.lead.last_asked_field = "email"

    payload = lead_funnel.handle_lifecycle_command(state, "start over")

    assert payload is not None
    assert "start over" in payload.text
    assert "name" in payload.text.lower()
    assert state.lead.active is True
    assert state.lead.last_asked_field == "name"
    assert state.lead.name is None
    assert state.lead.phone is None
    assert state.lead.email is None


def test_inactive_state_does_not_claim_bare_lifecycle_commands(funnel) -> None:
    lead_funnel, _ = funnel
    state = ConversationState(session_id="inactive-command")

    assert lead_funnel.handle_lifecycle_command(state, "cancel") is None
    assert lead_funnel.handle_lifecycle_command(state, "restart") is None
    assert state.lead.active is False


@pytest.mark.asyncio
async def test_ordinary_response_augmentation_is_a_noop(funnel) -> None:
    lead_funnel, webhook = funnel
    state = ConversationState(session_id="ordinary")
    state.turn_count = 10
    payload = build_response("Here are the published MBA fees.")

    result = lead_funnel.augment(
        state,
        payload,
        "Email the university at admissions@example.com or call 9876543210",
    )
    await asyncio.sleep(0)

    assert result is payload
    assert state.lead.active is False
    assert state.lead.last_asked_field is None
    assert state.lead.name is None
    assert state.lead.phone is None
    assert state.lead.email is None
    assert webhook.events == []


def test_lead_cta_factories_keep_legacy_action_and_add_widget_target() -> None:
    for cta in (lead_capture_cta(), callback_cta()):
        assert cta["action"] == "lead_capture"
        assert cta["payload"] == {"target_action": "OPEN_LEAD_WIDGET"}


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


@pytest.mark.asyncio
async def test_completion_deactivates_flow_and_preserves_crm_snapshot(funnel) -> None:
    lead_funnel, webhook = funnel
    state = ConversationState(session_id="complete")
    state.lead.active = True
    state.lead.name = "Aryan Kinha"
    state.lead.phone = "9876543210"
    state.lead.last_asked_field = "email"

    answer = lead_funnel.inspect_pending_answer(state, "aryan@example.com")
    assert answer is not None and answer.valid
    changed = lead_funnel.commit_pending_answer(state, answer)
    payload = lead_funnel.captured_reply_response(state, changed)
    await asyncio.sleep(0)

    assert state.lead.active is False
    assert state.lead.last_asked_field is None
    assert state.lead.email == "aryan@example.com"
    assert "have your details" in payload.text
    assert len(webhook.events) == 1
    assert webhook.events[0].captured_fields == ["email"]


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
