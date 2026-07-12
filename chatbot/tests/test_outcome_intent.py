"""Outcome-driven Gemini routing regressions from production transcripts."""

from __future__ import annotations

import logging
from collections.abc import Mapping

import pytest

from config import Settings
from llm.client import (
    GeminiDecision,
    LLMCatalogContentFailure,
    LLMParseFailure,
    LLMTimeout,
)
from main import ChatbotService
from nlu.callback_detector import is_callback_request
from resilience.intent_metrics import IntentMetrics
from schemas import ChatRequest
from session.store import MemorySessionStore


class ScriptedIntentLLM:
    """Small injected classifier that never performs provider I/O."""

    intent_configured = True
    synthesis_configured = False

    def __init__(
        self,
        responses: Mapping[str, GeminiDecision | Exception] | None = None,
        *,
        default: GeminiDecision | Exception = GeminiDecision(
            "unsupported_entity",
            "Unknown entity",
            False,
        ),
    ) -> None:
        self.responses = dict(responses or {})
        self.default = default
        self.intent_calls: list[str] = []
        self.mention_summaries: list[str] = []

    async def decide_action_tiny(
        self,
        message: str,
        mention_summary: str,
    ) -> GeminiDecision:
        self.intent_calls.append(message)
        self.mention_summaries.append(mention_summary)
        result = self.responses.get(message, self.default)
        if isinstance(result, Exception):
            raise result
        return result

    async def health(self):
        return {"status": "ok", "providers": {"gemini": "ok"}}


class ExplodingIntentLLM(ScriptedIntentLLM):
    async def decide_action_tiny(
        self,
        message: str,
        mention_summary: str,
    ) -> GeminiDecision:
        self.intent_calls.append(message)
        self.mention_summaries.append(mention_summary)
        raise AssertionError(f"fast path unexpectedly called Gemini: {message}")


async def make_service(llm: ScriptedIntentLLM) -> tuple[ChatbotService, IntentMetrics]:
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
    return service, metrics


async def turn(service: ChatbotService, message: str, session_id: str):
    return await service.process_turn(ChatRequest(message=message, session_id=session_id))


@pytest.mark.asyncio
async def test_typo_callback_uses_fuzzy_fast_path_and_zero_gemini_calls() -> None:
    llm = ExplodingIntentLLM()
    service, metrics = await make_service(llm)
    try:
        before = (
            await turn(service, "Tell me about NMIMS MBA", "typo-callback")
        ).state.focus.model_copy(deep=True)

        result = await turn(
            service,
            "i want to talk to consulaor",
            "typo-callback",
        )
    finally:
        await service.close()

    assert result.route == "lead"
    assert result.state.focus == before
    assert result.state.lead.last_asked_field == "name"
    assert llm.intent_calls == []
    snapshot = metrics.snapshot()
    assert snapshot["total_messages"] == 2
    assert snapshot["llm_intent_calls"] == 0


@pytest.mark.asyncio
async def test_vague_human_help_uses_gemini_callback_without_reusing_stale_focus() -> None:
    message = "i need someone to help me"
    llm = ScriptedIntentLLM({message: GeminiDecision("callback", None, False)})
    service, metrics = await make_service(llm)
    try:
        before = (
            await turn(service, "Tell me about NMIMS MBA", "vague-help")
        ).state.focus.model_copy(deep=True)

        result = await turn(service, message, "vague-help")
    finally:
        await service.close()

    assert result.route == "lead"
    assert result.state.focus == before
    assert "INR 1,96,000" not in result.payload.text
    assert llm.intent_calls == [message]
    snapshot = metrics.snapshot()
    assert snapshot["llm_intent_calls"] == 1
    assert snapshot["llm_intent_failures"] == 0


@pytest.mark.asyncio
async def test_harward_is_explicitly_unresolved_and_leaves_focus_untouched() -> None:
    message = "Tell me about harward uni"
    llm = ScriptedIntentLLM(
        {message: GeminiDecision("unsupported_entity", "Harward", False)}
    )
    service, metrics = await make_service(llm)
    try:
        before = (
            await turn(service, "Tell me about NMIMS MBA", "harward")
        ).state.focus.model_copy(deep=True)

        result = await turn(service, message, "harward")
    finally:
        await service.close()

    text = result.payload.text.casefold()
    assert result.route == "fallback"
    assert result.state.focus == before
    assert '"Harward"' in result.payload.text
    assert '"harward uni"' not in text
    assert "published catalog" in text
    assert "1,96,000" not in text
    assert llm.intent_calls == [message]
    assert metrics.snapshot()["llm_intent_calls"] == 1


@pytest.mark.asyncio
async def test_pi_uses_gemini_unrelated_and_cannot_answer_from_stale_focus() -> None:
    message = "what is the value of pi"
    llm = ScriptedIntentLLM({message: GeminiDecision("unrelated", None, False)})
    service, metrics = await make_service(llm)
    try:
        await turn(service, "Tell me about NMIMS MBA", "pi")
        result = await turn(service, message, "pi")
    finally:
        await service.close()

    assert result.route == "fallback"
    assert result.state.focus.model_dump(exclude_none=True) == {}
    assert "NMIMS" not in result.payload.text
    assert "1,96,000" not in result.payload.text
    assert llm.intent_calls == [message]
    assert metrics.snapshot()["llm_intent_calls"] == 1


@pytest.mark.asyncio
async def test_garbled_news_turn_is_not_silently_answered_from_catalog_focus() -> None:
    message = "tell me about the about today news"
    llm = ScriptedIntentLLM({message: GeminiDecision("unrelated", None, False)})
    service, metrics = await make_service(llm)
    try:
        await turn(service, "Tell me about NMIMS MBA", "garbled-news")
        result = await turn(service, message, "garbled-news")
    finally:
        await service.close()

    assert result.route == "fallback"
    assert "NMIMS" not in result.payload.text
    assert "1,96,000" not in result.payload.text
    assert llm.intent_calls == [message]
    assert metrics.snapshot()["llm_intent_calls"] == 1


@pytest.mark.asyncio
async def test_known_entity_control_sequence_never_calls_gemini() -> None:
    llm = ExplodingIntentLLM()
    service, metrics = await make_service(llm)
    try:
        results = [
            await turn(service, "Tell me about NMIMS MBA", "known-control"),
            await turn(service, "What is the fee?", "known-control"),
            await turn(service, "Compare LPU and NMIMS", "known-control"),
            await turn(service, "Tell me about Jain MBA Finance", "known-control"),
        ]
    finally:
        await service.close()

    assert [result.route for result in results] == [
        "factual",
        "factual",
        "comparison",
        "factual",
    ]
    assert "INR 1,96,000" in results[1].payload.text
    assert llm.intent_calls == []
    snapshot = metrics.snapshot()
    assert snapshot["total_messages"] == 4
    assert snapshot["llm_intent_calls"] == 0
    assert snapshot["llm_intent_call_rate"] == 0.0
    assert snapshot["action_from_deterministic_rule"] == 4


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "reason"),
    [
        (LLMTimeout("simulated timeout"), "timeout"),
        (LLMParseFailure("simulated malformed JSON"), "parse-failure"),
        (LLMCatalogContentFailure("simulated catalog content"), "catalog-content"),
    ],
)
async def test_classifier_failure_warns_records_metrics_and_completes(
    failure: Exception,
    reason: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    message = "what is the value of pi"
    llm = ScriptedIntentLLM({message: failure})
    service, metrics = await make_service(llm)
    try:
        with caplog.at_level(logging.WARNING, logger="chatbot.nlu"):
            result = await turn(service, message, f"failure-{reason}")
    finally:
        await service.close()

    assert result.route == "fallback"
    assert result.payload.text
    assert llm.intent_calls == [message]
    assert f"reason={reason}" in caplog.text
    if reason == "catalog-content":
        assert "rejected catalog-like content" in caplog.text
    snapshot = metrics.snapshot()
    assert snapshot["total_messages"] == 1
    assert snapshot["llm_intent_calls"] == 1
    assert snapshot["llm_intent_failures"] == 1
    assert snapshot["llm_intent_latency_ms"]["sample_count"] == 1
    assert snapshot["action_from_heuristic_regex"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    [
        "I'm confused",
        "need help deciding",
        "can somebody guide me",
    ],
)
async def test_open_human_help_reaches_callback_through_gemini(message: str) -> None:
    assert is_callback_request(message) is False
    llm = ScriptedIntentLLM({message: GeminiDecision("callback", None, False)})
    service, metrics = await make_service(llm)
    try:
        before = (
            await turn(service, "Tell me about NMIMS MBA", f"open-help-{message}")
        ).state.focus.model_copy(deep=True)
        result = await turn(service, message, f"open-help-{message}")
    finally:
        await service.close()

    assert result.route == "lead"
    assert result.state.focus == before
    assert result.state.lead.last_asked_field == "name"
    assert llm.intent_calls == [message]
    assert llm.mention_summaries == [
        "category=none, university=none, specialization=none"
    ]
    snapshot = metrics.snapshot()
    assert snapshot["llm_intent_calls"] == 1
    assert snapshot["llm_intent_failures"] == 0
    assert snapshot["action_from_gemini"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("message", "route", "required"),
    [
        (
            "Show MBA specializations",
            "list_specializations",
            ("Business Analytics", "Finance Management", "Marketing"),
        ),
        (
            "Which universities offer Marketing specialization?",
            "list_providers",
            (
                "Amity University Online",
                "Jain University Online",
                "Lovely Professional University",
                "Manipal University Jaipur",
                "NMIMS Online",
            ),
        ),
    ],
)
async def test_list_actions_are_specific_and_zero_gemini(
    message: str,
    route: str,
    required: tuple[str, ...],
) -> None:
    llm = ExplodingIntentLLM()
    service, metrics = await make_service(llm)
    try:
        result = await turn(service, message, f"list-action-{route}")
    finally:
        await service.close()

    assert result.route == route
    assert all(value in result.payload.text for value in required)
    assert "Which one did you mean" not in result.payload.text
    assert llm.intent_calls == []
    snapshot = metrics.snapshot()
    assert snapshot["llm_intent_calls"] == 0
    assert snapshot["llm_intent_latency_ms"]["sample_count"] == 0
    assert snapshot["action_from_deterministic_rule"] == 1
