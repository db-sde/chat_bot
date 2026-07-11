from __future__ import annotations

import pytest

from config import Settings
from llm.client import LLMUnavailable
from main import ChatbotService, _event_stream
from schemas import ChatRequest
from session.store import MemorySessionStore


class CountingLLM:
    intent_configured = True
    synthesis_configured = True

    def __init__(self) -> None:
        self.intent_calls = 0
        self.stream_calls = 0

    async def classify_intent(self, message: str) -> str:
        self.intent_calls += 1
        raise AssertionError(f"unexpected classifier call: {message}")

    async def stream_synthesis(self, prompt: str):
        self.stream_calls += 1
        raise AssertionError(f"unexpected synthesis call: {prompt}")
        yield ""  # pragma: no cover - keeps this an async generator

    async def health(self):
        return {"status": "ok", "providers": {"fake": "ok"}}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    [
        "Tell me about manipal japiur",
        "monypal university",
        "Tell me about NMIMS MBA Marketing",
        "Which universities offer MCA?",
    ],
)
async def test_structured_catalog_http_payload_path_is_zero_llm(message: str) -> None:
    llm = CountingLLM()
    service = await ChatbotService.create(
        Settings(redis_url=None, lead_prompt_after_turn=100),
        session_store=MemorySessionStore(),
        llm=llm,
    )
    try:
        result = await service.process_turn(ChatRequest(message=message, session_id=message))
        events = [chunk async for chunk in _event_stream(service, result)]
    finally:
        await service.close()

    assert len(events) == 1
    assert events[0].startswith(b"event: response")
    assert llm.intent_calls == 0
    assert llm.stream_calls == 0


class PartialFailureLLM(CountingLLM):
    intent_configured = False

    async def stream_synthesis(self, prompt: str):
        del prompt
        self.stream_calls += 1
        yield "unfinished provider sentence"
        raise LLMUnavailable("provider disconnected")


@pytest.mark.asyncio
async def test_failed_stream_does_not_emit_partial_tokens_before_fallback() -> None:
    llm = PartialFailureLLM()
    service = await ChatbotService.create(
        Settings(
            redis_url=None,
            lead_prompt_after_turn=100,
            enable_answer_synthesis=True,
        ),
        session_store=MemorySessionStore(),
        llm=llm,
    )
    try:
        result = await service.process_turn(
            ChatRequest(message="Tell me about LPU", session_id="partial-stream")
        )
        assert result.synthesis_prompt is not None
        events = [chunk async for chunk in _event_stream(service, result)]
    finally:
        await service.close()

    assert len(events) == 1
    assert events[0].startswith(b"event: response")
    assert b"unfinished provider sentence" not in events[0]
    assert llm.stream_calls == 1
