from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

import main as main_module
from config import Settings
from data.loader import SAMPLE_CATALOG_PATH
from routing.tools import ToolEngine, ToolResult, ToolsContentStore
from session.navigation import advance_navigation, sync_page_navigation
from session.state import ActiveFlow, ConversationState, NavigationStep
from session.store import MemorySessionStore


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    temporary = tmp_path_factory.mktemp("widget-v2-funnel")
    settings = Settings(
        catalog_url=None,
        catalog_path=SAMPLE_CATALOG_PATH,
        redis_url=None,
        openai_api_key=None,
        groq_api_key=None,
        gemini_api_key=None,
        crm_webhook_url=None,
        analytics_webhook_url=None,
        dead_letter_path=temporary / "lead-dead-letters.jsonl",
        analytics_dead_letter_path=temporary / "analytics-dead-letters.jsonl",
        lead_prompt_after_turn=100,
        log_level="CRITICAL",
    )
    patcher = pytest.MonkeyPatch()
    patcher.setattr(main_module, "get_settings", lambda: settings)
    try:
        with TestClient(main_module.app) as test_client:
            yield test_client
    finally:
        patcher.undo()


def _final_payload(response_text: str) -> dict[str, Any]:
    for block in reversed(response_text.replace("\r\n", "\n").split("\n\n")):
        event = ""
        data = ""
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line.removeprefix("event:").strip()
            elif line.startswith("data:"):
                data = line.removeprefix("data:").strip()
        if event == "response" and data:
            return json.loads(data)
    raise AssertionError("No final SSE response event was returned")


def _chat(client: TestClient, message: str, session_id: str) -> dict[str, Any]:
    response = client.post(
        "/chat",
        json={"message": message, "session_id": session_id, "site_key": "degreebaba"},
    )
    assert response.status_code == 200
    return _final_payload(response.text)


def _portal_call(client: TestClient, operation: Any, *args: Any) -> Any:
    assert client.portal is not None
    return client.portal.call(operation, *args)


def _persisted_state(client: TestClient, session_id: str) -> ConversationState:
    state = _portal_call(client, client.app.state.service.session_store.get, session_id)
    assert state is not None
    return state


def _career_content(version: str = "integration-v1") -> dict[str, object]:
    questions = [
        {
            "id": f"q{index}",
            "prompt": f"Career question {index}",
            "type": "choice",
            "options": [
                {"id": "business", "label": "Business", "weights": {"mba": 2}},
                {"id": "technology", "label": "Technology", "weights": {"mca": 2}},
            ],
        }
        for index in range(1, 6)
    ]
    return {
        "version": version,
        "tools": {
            "roi": {
                "enabled": False,
                "entry_copy": "",
                "unavailable_reason": "ROI test content is intentionally disabled.",
                "steps": [],
                "question_bank": {},
                "reward_bands": [],
            },
            "career_quiz": {
                "enabled": True,
                "entry_copy": "Answer the configured career questions.",
                "steps": questions,
                "question_bank": {},
                "reward_bands": [],
            },
            "scholarship": {
                "enabled": False,
                "entry_copy": "",
                "unavailable_reason": "Scholarship test content is intentionally disabled.",
                "steps": [],
                "question_bank": {},
                "reward_bands": [],
            },
        },
    }


@contextmanager
def _temporary_tool_engine(
    client: TestClient,
    tmp_path: Path,
    *,
    version: str = "integration-v1",
) -> Iterator[ToolEngine]:
    content_path = tmp_path / f"tools-{version}.json"
    content_path.write_text(json.dumps(_career_content(version)), encoding="utf-8")
    service = client.app.state.service
    original = service.tools
    engine = ToolEngine(
        ToolsContentStore(content_path, auto_reload=False),
        catalog=service.catalog,
        entity_resolver=service._resolve_tool_entity,
        program_lookup=service._lookup_tool_programs,
    )
    service.tools = engine
    try:
        yield engine
    finally:
        service.tools = original


def test_guide_context_returns_persisted_session_opening_and_navigation(
    client: TestClient,
) -> None:
    session_id = "widget-v2-guide-context"
    response = client.get(
        "/api/widget/guide/context",
        params={
            "session_id": session_id,
            "page_type": "course",
            "university": "nmims",
            "course": "mca",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"] == session_id
    assert payload["opening"]["surface"] == "page:course"
    assert payload["opening"]["config_version"]
    assert payload["opening"]["top"]
    assert payload["navigation"] == {
        **payload["navigation"],
        "step": "course_card",
        "page_type": "course",
        "surface": "page:course",
        "entity_id": "course-nmims-mca",
        "interaction_count": 0,
    }

    persisted = _persisted_state(client, session_id)
    assert persisted.navigation.step is NavigationStep.COURSE_CARD
    assert persisted.navigation.entity_id == "course-nmims-mca"
    assert persisted.navigation.config_version == payload["opening"]["config_version"]


def test_homepage_hydration_clears_stale_academic_focus(client: TestClient) -> None:
    session_id = "widget-v2-home-clears-focus"
    course = client.get(
        "/api/widget/guide/context",
        params={
            "session_id": session_id,
            "page_type": "course",
            "university": "nmims",
            "course": "mca",
        },
    )
    assert course.status_code == 200
    assert _persisted_state(client, session_id).focus.entity_id == "course-nmims-mca"

    homepage = client.get(
        "/api/widget/guide/context",
        params={"session_id": session_id, "page_type": "homepage"},
    )

    assert homepage.status_code == 200
    persisted = _persisted_state(client, session_id)
    assert persisted.focus.entity_id is None
    assert persisted.focus.university_concept is None
    assert persisted.focus.course_concept is None
    assert persisted.navigation.page_type == "homepage"


def test_guide_chip_post_persists_progress_and_suppresses_completed_action(
    client: TestClient,
) -> None:
    session_id = "widget-v2-chip-progress"
    context = client.get(
        "/api/widget/guide/context",
        params={"session_id": session_id, "page_type": "homepage"},
    )
    assert context.status_code == 200

    response = client.post(
        "/api/widget/guide/chips",
        json={
            "session_id": session_id,
            "page_type": "homepage",
            "surface": "page:home",
            "completed_chip_id": "fees_emi",
            "config_version": context.json()["opening"]["config_version"],
            "answer_state": "fees",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    action_ids = [action["chip_id"] for action in payload["followup"]["actions"]]
    assert payload["navigation"]["interaction_count"] == 1
    assert payload["navigation"]["completed_actions"] == ["fees_emi"]
    assert payload["navigation"]["step"] == "fees"
    assert "fees_emi" not in action_ids
    assert {"roi_tool", "counsellor"} <= set(action_ids)

    persisted = _persisted_state(client, session_id)
    assert persisted.navigation.interaction_count == 1
    assert persisted.navigation.completed_actions == ["fees_emi"]
    assert persisted.navigation.step is NavigationStep.FEES


def test_no_specialization_answer_returns_to_the_authoritative_course_card(
    client: TestClient,
) -> None:
    session_id = "widget-v2-no-specializations"
    context = client.get(
        "/api/widget/guide/context",
        params={
            "session_id": session_id,
            "page_type": "course",
            "university": "uni-sikkim-manipal",
            "course": "bba",
        },
    )
    assert context.status_code == 200

    response = client.post(
        "/api/widget/guide/chips",
        json={
            "session_id": session_id,
            "page_type": "course",
            "surface": "page:course",
            "entity_id": "course-sikkim-manipal-bba",
            "completed_chip_id": "specializations",
            "config_version": context.json()["opening"]["config_version"],
            "answer_state": "no_specializations",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    action_ids = {action["chip_id"] for action in payload["followup"]["actions"]}
    assert payload["navigation"]["step"] == "course_card"
    assert payload["navigation"]["entity_id"] == "course-sikkim-manipal-bba"
    assert not {"browse_programs", "browse_universities"}.intersection(action_ids)

    persisted = _persisted_state(client, session_id)
    assert persisted.navigation.step is NavigationStep.COURSE_CARD
    assert persisted.navigation.entity_id == "course-sikkim-manipal-bba"


def test_chat_routed_chip_persists_completion_without_a_second_request(
    client: TestClient,
) -> None:
    session_id = "widget-v2-chat-chip-progress"
    context = client.get(
        "/api/widget/guide/context",
        params={
            "session_id": session_id,
            "page_type": "course",
            "university": "nmims",
            "course": "mca",
        },
    )
    assert context.status_code == 200

    response = client.post(
        "/chat",
        json={
            "session_id": session_id,
            "message": "Am I eligible?",
            "chip_id": "eligibility",
            "chip_surface": "page:course",
            "chip_config_version": context.json()["opening"]["config_version"],
            "page_type": "course",
            "page_entity_slug": "course-nmims-mca",
        },
    )

    assert response.status_code == 200
    payload = _final_payload(response.text)
    persisted = _persisted_state(client, session_id)
    assert persisted.navigation.interaction_count == 1
    assert persisted.navigation.completed_actions == ["eligibility"]
    assert persisted.navigation.step is NavigationStep.ELIGIBILITY
    assert all(
        action.get("chip_id") != "eligibility"
        for action in payload["quick_actions"]
    )


def test_typed_answer_surface_keeps_navigation_step_in_sync(client: TestClient) -> None:
    session_id = "widget-v2-typed-answer-step"
    context = client.get(
        "/api/widget/guide/context",
        params={
            "session_id": session_id,
            "page_type": "course",
            "university": "nmims",
            "course": "mca",
        },
    )
    assert context.status_code == 200

    response = client.post(
        "/chat",
        json={
            "session_id": session_id,
            "message": "What is the fee?",
            "page_type": "course",
            "page_entity_slug": "course-nmims-mca",
        },
    )

    assert response.status_code == 200
    payload = _final_payload(response.text)
    assert payload["quick_actions"]
    assert payload["quick_actions"][0]["surface"] == "answer:fees"
    persisted = _persisted_state(client, session_id)
    assert persisted.navigation.surface == "answer:fees"
    assert persisted.navigation.step is NavigationStep.FEES


@pytest.mark.asyncio
async def test_navigation_survives_memory_session_store_serialization() -> None:
    store = MemorySessionStore()
    state = ConversationState(session_id="widget-v2-navigation-round-trip")
    sync_page_navigation(
        state,
        page_type="course",
        entity_id="course-nmims-mca",
        config_version="test-config-v1",
    )
    advance_navigation(state, chip_id="fees_emi", surface="card:course")

    await store.set(state)
    loaded = await store.get(state.session_id)
    await store.close()

    assert loaded is not None
    assert loaded is not state
    assert loaded.navigation.model_dump(mode="json") == state.navigation.model_dump(mode="json")
    assert loaded.navigation.step is NavigationStep.FEES
    assert loaded.navigation.completed_actions == ["fees_emi"]


def test_replayed_chip_does_not_inflate_interaction_depth() -> None:
    state = ConversationState(session_id="widget-v2-chip-replay")
    sync_page_navigation(state, page_type="course", config_version="test-config-v1")

    advance_navigation(state, chip_id="fees_emi", surface="page:course")
    advance_navigation(state, chip_id="fees_emi", surface="page:course")

    assert state.navigation.interaction_count == 1
    assert state.navigation.completed_actions == ["fees_emi"]


def test_guide_chip_rejects_stale_page_context(client: TestClient) -> None:
    session_id = "widget-v2-stale-chip-context"
    context = client.get(
        "/api/widget/guide/context",
        params={
            "session_id": session_id,
            "page_type": "specialization",
            "entity_id": "spec-nmims-mca-cloud-computing",
        },
    )
    assert context.status_code == 200

    response = client.post(
        "/api/widget/guide/chips",
        json={
            "session_id": session_id,
            "page_type": "homepage",
            "surface": "page:home",
            "completed_chip_id": "browse_universities",
            "config_version": context.json()["opening"]["config_version"],
        },
    )

    assert response.status_code == 409
    persisted = _persisted_state(client, session_id)
    assert persisted.navigation.page_type == "specialization"
    assert persisted.navigation.completed_actions == []


def test_unconfigured_roi_tool_is_honest_clears_flow_and_never_calls_llm(
    client: TestClient,
) -> None:
    service = client.app.state.service
    service.analytics.reset_snapshot()
    decide_action = AsyncMock(side_effect=AssertionError("tool entry must not call the LLM"))
    with patch.object(type(service.llm), "decide_action_tiny", new=decide_action):
        payload = _chat(client, "tool:roi", "widget-v2-roi-unavailable")

    persisted = _persisted_state(client, "widget-v2-roi-unavailable")
    assert "unavailable" in payload["text"].casefold()
    assert "fee_numeric" in payload["text"]
    assert persisted.active_flow is None
    assert persisted.navigation.step is NavigationStep.HOMEPAGE
    event_counts = service.analytics.snapshot()["event_counts"]
    assert event_counts.get("tool_started", 0) == 0
    assert event_counts.get("tool_completed", 0) == 0
    decide_action.assert_not_awaited()


def test_roi_program_step_reuses_catalog_matcher_for_university_course_phrase(
    client: TestClient,
) -> None:
    service = client.app.state.service

    assert service._resolve_tool_entity("NMIMS MCA") == "course-nmims-mca"
    assert service._resolve_tool_entity("a course that is not in the catalog") is None


def test_configured_tool_flow_survives_reload_and_strong_intents_escape(
    client: TestClient,
    tmp_path: Path,
) -> None:
    service = client.app.state.service
    with _temporary_tool_engine(client, tmp_path):
        callback_session = "widget-v2-tool-callback-escape"
        first = _chat(client, "tool:career_quiz", callback_session)
        first_answer = next(
            action["message"]
            for action in first["quick_actions"]
            if action["message"].startswith("tool:answer:q1:")
        )

        serialized = _persisted_state(client, callback_session)
        assert serialized.active_flow is not None
        assert serialized.active_flow.step == "q1"
        _portal_call(client, service.session_store.set, serialized)

        second = _chat(client, first_answer, callback_session)
        assert second["metadata"]["tool_flow"]["step"] == "q2"
        reloaded = _persisted_state(client, callback_session)
        assert reloaded.active_flow is not None
        assert reloaded.active_flow.step == "q2"
        assert reloaded.active_flow.version == "integration-v1"

        callback_payload = _chat(client, "Call me", callback_session)
        callback_state = _persisted_state(client, callback_session)
        assert callback_payload["metadata"]["route"] == "lead"
        assert callback_state.active_flow is None
        assert callback_state.lead.active

        entity_session = "widget-v2-tool-entity-escape"
        _chat(client, "tool:career_quiz", entity_session)
        entity_payload = _chat(client, "Tell me about NMIMS", entity_session)
        entity_state = _persisted_state(client, entity_session)
        assert entity_state.active_flow is None
        assert entity_payload["metadata"]["route"] != "tool"
        assert "NMIMS" in entity_payload["message"]


def test_tool_analytics_count_answers_not_question_renders_and_refresh_resumes(
    client: TestClient,
    tmp_path: Path,
) -> None:
    session_id = "widget-v2-tool-analytics"
    service = client.app.state.service
    with _temporary_tool_engine(client, tmp_path, version="analytics-v1"):
        service.analytics.reset_snapshot()
        payload = _chat(client, "tool:career_quiz", session_id)
        counts = service.analytics.snapshot()["event_counts"]
        assert counts["tool_started"] == 1
        assert counts.get("tool_step", 0) == 0
        assert counts.get("tool_completed", 0) == 0

        resumed = client.get(
            "/api/widget/guide/context",
            params={"session_id": session_id, "page_type": "homepage"},
        )
        assert resumed.status_code == 200
        assert resumed.json()["active_flow"]["step"] == "q1"
        assert resumed.json()["active_flow"]["response"]["metadata"]["tool_flow"][
            "version"
        ] == "analytics-v1"
        assert _persisted_state(client, session_id).active_flow.step == "q1"

        for answered_count in range(1, 6):
            answer = next(
                action["message"]
                for action in payload["quick_actions"]
                if action["message"].startswith(f"tool:answer:q{answered_count}:")
            )
            payload = _chat(client, answer, session_id)
            assert service.analytics.snapshot()["event_counts"]["tool_step"] == answered_count

        counts = service.analytics.snapshot()["event_counts"]
        assert counts["tool_partial_reveal"] == 1
        assert counts.get("tool_completed", 0) == 0

        gated = _chat(client, "tool:continue", session_id)
        assert gated["metadata"]["tool_flow"]["step"] == "await_lead"
        assert service.analytics.snapshot()["event_counts"]["tool_lead_gate"] == 1

        lead = client.post(
            "/api/widget/lead",
            json={
                "session_id": session_id,
                "name": "Aryan Kinha",
                "phone": "9876543211",
                "source": "career_quiz_gate",
            },
        )
        assert lead.status_code == 200
        counts = service.analytics.snapshot()["event_counts"]
        assert counts["tool_completed"] == 1
        assert counts["lead_captured"] == 1


def test_widget_analytics_accepts_batched_chip_impression_and_metrics_counts_it(
    client: TestClient,
) -> None:
    service = client.app.state.service
    service.analytics.reset_snapshot()
    config_version = service.chip_map.snapshot().version

    response = client.post(
        "/api/widget/analytics",
        json={
            "session_id": "widget-v2-analytics",
            "event": "chip_shown",
            "surface": "page:home",
            "funnel_stage": "top",
            "interaction_count": 0,
            "entity": {"type": None, "id": None},
            "config_version": config_version,
            "content_version": "not_applicable",
            "chips": [
                {"chip_id": "browse_universities", "chip_handler": "list_universities"},
                {"chip_id": "browse_programs", "chip_handler": "list_programs"},
            ],
        },
    )

    assert response.status_code == 200
    assert response.json() == {"accepted": True, "session_id": "widget-v2-analytics"}
    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    funnel = metrics.json()["funnel_analytics"]
    assert funnel["accepted"] == 1
    assert funnel["event_counts"] == {"chip_shown": 1}


def test_session_start_fires_on_first_message_not_guide_hydration(
    client: TestClient,
) -> None:
    session_id = "widget-v2-first-message-denominator"
    service = client.app.state.service
    service.analytics.reset_snapshot()

    context = client.get(
        "/api/widget/guide/context",
        params={"session_id": session_id, "page_type": "homepage"},
    )
    assert context.status_code == 200
    assert service.analytics.snapshot()["event_counts"] == {}

    _chat(client, "hello", session_id)
    _chat(client, "hello again", session_id)

    assert service.analytics.snapshot()["event_counts"]["session_start"] == 1


def test_lead_captured_requires_name_and_phone_and_emits_once(client: TestClient) -> None:
    service = client.app.state.service
    service.analytics.reset_snapshot()

    phone_only = client.post(
        "/api/widget/lead",
        json={
            "session_id": "widget-v2-phone-only-is-not-conversion",
            "phone": "9876543210",
            "source": "ordinary_widget",
        },
    )
    assert phone_only.status_code == 200
    assert service.analytics.snapshot()["event_counts"] == {}

    session_id = "widget-v2-name-phone-conversion"
    _chat(client, "Call me", session_id)
    _chat(client, "Aryan Kinha", session_id)
    _chat(client, "9876543210", session_id)

    snapshot = service.analytics.snapshot()
    assert snapshot["event_counts"]["lead_captured"] == 1
    persisted = _persisted_state(client, session_id)
    assert persisted.lead.name == "Aryan Kinha"
    assert persisted.lead.phone == "9876543210"
    assert persisted.lead.conversion_recorded


def test_phone_lead_capture_resumes_persisted_tool_reveal(
    client: TestClient,
    tmp_path: Path,
) -> None:
    session_id = "widget-v2-tool-lead-resume"
    service = client.app.state.service
    with _temporary_tool_engine(client, tmp_path, version="lead-resume-v1") as engine:
        result = ToolResult(
            partial={"headline": "Your partial career result is ready."},
            full={
                "message": "Your full configured career result is MBA.",
                "top_discipline": "mba",
            },
            cta_program_ids=["course-nmims-mba"],
            lead_tags={"tool": "career_quiz", "top_discipline": "mba"},
        )
        state = ConversationState(
            session_id=session_id,
            active_flow=ActiveFlow(
                tool="career_quiz",
                step="await_lead",
                answers={f"q{index}": "business" for index in range(1, 6)},
                payload={"result": result.model_dump(mode="json")},
                version=engine.content_store.version,
            ),
        )
        state.navigation.step = NavigationStep.TOOL
        state.navigation.config_version = service.chip_map.snapshot().version
        _portal_call(client, service.session_store.set, state)
        service.analytics.reset_snapshot()

        webhook_push = AsyncMock()
        with patch.object(service.lead_funnel.webhook, "push", new=webhook_push):
            response = client.post(
                "/api/widget/lead",
                json={
                    "session_id": session_id,
                    "name": "Aryan Kinha",
                    "phone": "9876543210",
                    "source": "career_quiz_gate",
                },
            )

        assert response.status_code == 200
        payload = response.json()
        assert payload["success"] is True
        assert payload["response"] is not None
        assert payload["response"]["text"] == "Your full configured career result is MBA."
        assert payload["response"]["metadata"]["tool_flow"]["step"] == "reveal"
        assert [action["chip_id"] for action in payload["response"]["quick_actions"]][:3] == [
            "apply_now",
            "counsellor",
            "compare",
        ]

        persisted = _persisted_state(client, session_id)
        assert persisted.active_flow is None
        assert persisted.lead.name == "Aryan Kinha"
        assert persisted.lead.phone == "9876543210"
        assert not persisted.lead.active
        webhook_push.assert_awaited_once()
        crm_event = webhook_push.await_args.args[0]
        assert crm_event.context["tool"] == "career_quiz"
        assert crm_event.context["top_discipline"] == "mba"
        assert crm_event.context["widget_source"] == "career_quiz_gate"
        assert crm_event.captured_fields == ["name", "phone"]
        lead_event = next(
            event
            for event in service.analytics.snapshot()["events"]
            if event["event"] == "lead_captured"
        )
        assert lead_event["lead_tags"] == {
            "tool": "career_quiz",
            "top_discipline": "mba",
        }
