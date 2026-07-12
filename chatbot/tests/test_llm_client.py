import asyncio
from types import SimpleNamespace

import pytest

import llm.client as client_module
from llm.client import (
    CircuitOpen,
    LLMCatalogContentFailure,
    LLMClient,
    LLMDecisionSchemaFailure,
    LLMParseFailure,
    LLMTimeout,
    LLMUnavailable,
)


def _settings(**overrides):
    values = {
        "groq_api_key": "groq-test-key",
        "openai_api_key": None,
        "gemini_api_key": "gemini-test-key",
        "gemini_model": "gemini-3.1-flash-lite",
        "gemini_intent_timeout_ms": 200,
        "llm_synthesis_timeout_seconds": 0.2,
        "llm_circuit_failure_threshold": 3,
        "llm_circuit_cooldown_seconds": 30,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class _Completions:
    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls = 0

    async def create(self, **_kwargs):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.result


def _provider(completions: _Completions):
    return SimpleNamespace(chat=SimpleNamespace(completions=completions))


class _GeminiModels:
    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[dict] = []

    async def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.result


class _GeminiClient:
    def __init__(self, models: _GeminiModels) -> None:
        self.models = models
        self.async_closed = False
        self.closed = False
        self.aio = SimpleNamespace(models=models, aclose=self._aclose)

    async def _aclose(self) -> None:
        self.async_closed = True

    def close(self) -> None:
        self.closed = True


def test_provider_clients_disable_sdk_retries(monkeypatch) -> None:
    captured: dict[str, dict] = {}

    def fake_groq(**kwargs):
        captured["groq"] = kwargs
        return object()

    def fake_openai(**kwargs):
        captured["openai"] = kwargs
        return object()

    gemini = _GeminiClient(_GeminiModels())

    def fake_gemini(**kwargs):
        captured["gemini"] = kwargs
        return gemini

    monkeypatch.setattr(client_module, "AsyncGroq", fake_groq)
    monkeypatch.setattr(client_module, "AsyncOpenAI", fake_openai)
    monkeypatch.setattr(client_module.genai, "Client", fake_gemini)
    client = LLMClient(_settings(openai_api_key="openai-test-key"))

    client._groq_client()
    client._openai_client()
    assert client._gemini_client() is client._gemini_client()

    assert captured["groq"]["max_retries"] == 0
    assert captured["openai"]["max_retries"] == 0
    options = captured["gemini"]["http_options"]
    # Gemini rejects shorter transport deadlines; the strict classifier cutoff
    # is independently enforced by asyncio.timeout.
    assert options.timeout == 10_000
    assert options.retry_options.attempts == 1


@pytest.mark.asyncio
async def test_tiny_decision_uses_exact_prompt_and_generation_bounds() -> None:
    models = _GeminiModels(
        result=SimpleNamespace(
            text='{"action":"callback","entity":null,"needs_clarification":false}'
        )
    )
    client = LLMClient(_settings())
    client._gemini = _GeminiClient(models)

    decision = await client.decide_action_tiny(
        'can "somebody" guide me',
        "category=none, university=none, specialization=none",
    )

    assert decision.action == "callback"
    assert decision.entity is None
    assert decision.needs_clarification is False
    assert len(models.calls) == 1
    request = models.calls[0]
    assert request["model"] == "gemini-3.1-flash-lite"
    assert request["contents"] == (
        "Given this message and what was found in the catalog, decide the action.\n\n"
        'Message: "can \\"somebody\\" guide me"\n'
        "Resolved so far: category=none, university=none, specialization=none\n\n"
        "Return ONLY this JSON, no other text:\n"
        '{"action": "<one of: recommend, discovery, clarify, callback, '
        'unsupported_entity, unrelated>",\n'
        ' "entity": "<name mentioned but not found in catalog, or null>",\n'
        ' "needs_clarification": <true|false>}'
    )
    assert request["config"].temperature == 0
    assert request["config"].max_output_tokens == 96
    assert request["config"].response_mime_type == "application/json"
    schema = request["config"].response_json_schema
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]["action"]["enum"]) == {
        "recommend",
        "discovery",
        "clarify",
        "callback",
        "unsupported_entity",
        "unrelated",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("action", "entity", "needs_clarification"),
    [
        ("recommend", None, False),
        ("discovery", None, False),
        ("clarify", None, True),
        ("callback", None, False),
        ("unsupported_entity", "Harward", False),
        ("unrelated", None, False),
    ],
)
async def test_all_allowed_gemini_decisions_are_accepted(
    action: str,
    entity: str | None,
    needs_clarification: bool,
) -> None:
    import json

    models = _GeminiModels(
        result=SimpleNamespace(
            text=json.dumps(
                {
                    "action": action,
                    "entity": entity,
                    "needs_clarification": needs_clarification,
                }
            )
        )
    )
    client = LLMClient(_settings())
    client._gemini = _GeminiClient(models)

    decision = await client.decide_action_tiny("message", "category=none")

    assert (decision.action, decision.entity, decision.needs_clarification) == (
        action,
        entity,
        needs_clarification,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text",
    [
        "",
        'prefix {"action":"callback","entity":null,"needs_clarification":false}',
        '```json\n{"action":"callback","entity":null,"needs_clarification":false}\n```',
        "[]",
        '{"action":"callback","entity":null}',
        '{"action":"callback","entity":null,"needs_clarification":false,"note":null}',
        '{"action":"callback","action":"clarify","entity":null,'
        '"needs_clarification":false}',
        '{"action":"get_facts","entity":null,"needs_clarification":false}',
        '{"action":"unsupported_entity","entity":42,"needs_clarification":false}',
        '{"action":"clarify","entity":null,"needs_clarification":"true"}',
        '{"action":"unsupported_entity","entity":null,"needs_clarification":false}',
        '{"action":"callback","entity":"Harward","needs_clarification":false}',
        '{"action":"callback","entity":null,"needs_clarification":true}',
    ],
)
async def test_invalid_tiny_decision_is_a_parse_failure(text: str) -> None:
    models = _GeminiModels(result=SimpleNamespace(text=text))
    client = LLMClient(_settings())
    client._gemini = _GeminiClient(models)

    with pytest.raises(LLMParseFailure):
        await client.decide_action_tiny("message", "category=none")

    assert len(models.calls) == 1
    assert client._breakers["gemini"].failures == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text",
    [
        '{"action":"unsupported_entity","entity":"INR 1,96,000",'
        '"needs_clarification":false}',
        '{"action":"unsupported_entity","entity":"NAAC A++",'
        '"needs_clarification":false}',
        '{"action":"unsupported_entity","entity":"2 years",'
        '"needs_clarification":false}',
        '{"action":"callback","entity":null,"needs_clarification":false,'
        '"fee":"INR 1,96,000"}',
    ],
)
async def test_catalog_like_decision_content_is_rejected_distinctly(text: str) -> None:
    models = _GeminiModels(result=SimpleNamespace(text=text))
    client = LLMClient(_settings())
    client._gemini = _GeminiClient(models)

    with pytest.raises(LLMCatalogContentFailure):
        await client.decide_action_tiny("message", "category=none")

    assert client._breakers["gemini"].failures == 1


@pytest.mark.asyncio
async def test_schema_failure_has_specific_subtype() -> None:
    models = _GeminiModels(
        result=SimpleNamespace(
            text='{"action":"get_facts","entity":null,"needs_clarification":false}'
        )
    )
    client = LLMClient(_settings())
    client._gemini = _GeminiClient(models)

    with pytest.raises(LLMDecisionSchemaFailure):
        await client.decide_action_tiny("message", "category=none")


@pytest.mark.asyncio
async def test_tiny_decision_timeout_has_one_attempt_and_opens_breaker() -> None:
    class NeverModels(_GeminiModels):
        async def generate_content(self, **kwargs):
            self.calls.append(kwargs)
            await asyncio.Event().wait()

    models = NeverModels()
    client = LLMClient(
        _settings(
            gemini_intent_timeout_ms=10,
            llm_circuit_failure_threshold=1,
        )
    )
    client._gemini = _GeminiClient(models)

    with pytest.raises(LLMTimeout):
        await client.decide_action_tiny("message", "category=none")
    with pytest.raises(CircuitOpen):
        await client.decide_action_tiny("message", "category=none")

    assert len(models.calls) == 1


@pytest.mark.asyncio
async def test_close_releases_both_gemini_transports() -> None:
    gemini = _GeminiClient(_GeminiModels())
    client = LLMClient(_settings())
    client._gemini = gemini

    await client.close()

    assert gemini.async_closed and gemini.closed
    assert client._gemini is None


@pytest.mark.asyncio
async def test_bounded_call_uses_one_attempt_and_deadline() -> None:
    client = LLMClient(_settings())
    calls = 0

    async def never_finishes():
        nonlocal calls
        calls += 1
        await asyncio.Event().wait()

    with pytest.raises(LLMUnavailable, match="groq LLM call unavailable"):
        await client._bounded_call("groq", 0.01, never_finishes)

    assert calls == 1


class _DelayedStream:
    def __init__(self, delay: float) -> None:
        self.delay = delay
        self.sent = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.sent:
            raise StopAsyncIteration
        await asyncio.sleep(self.delay)
        self.sent = True
        return SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content="late token"))]
        )


class _DelayedCompletions(_Completions):
    def __init__(self, delay: float) -> None:
        super().__init__()
        self.delay = delay

    async def create(self, **_kwargs):
        self.calls += 1
        await asyncio.sleep(self.delay)
        return _DelayedStream(self.delay)


@pytest.mark.asyncio
async def test_stream_open_and_consumption_share_one_absolute_deadline() -> None:
    completions = _DelayedCompletions(delay=0.12)
    client = LLMClient(_settings(llm_synthesis_timeout_seconds=0.2))
    client._groq = _provider(completions)
    tokens: list[str] = []

    with pytest.raises(LLMUnavailable, match="groq streaming unavailable"):
        async for token in client.stream_synthesis("grounded prompt"):
            tokens.append(token)

    assert tokens == []
    assert completions.calls == 1


class _InterruptedStream:
    def __init__(self) -> None:
        self.index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        self.index += 1
        if self.index == 1:
            return SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="partial"))]
            )
        raise ConnectionError("stream interrupted")


@pytest.mark.asyncio
async def test_interrupted_stream_is_not_retried_after_partial_output() -> None:
    completions = _Completions(result=_InterruptedStream())
    client = LLMClient(_settings())
    client._groq = _provider(completions)
    tokens: list[str] = []

    with pytest.raises(LLMUnavailable, match="after output began"):
        async for token in client.stream_synthesis("grounded prompt"):
            tokens.append(token)

    assert tokens == ["partial"]
    assert completions.calls == 1
    assert client._breakers["groq"].failures == 1


class _TwoTokenStream:
    def __init__(self) -> None:
        self.index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        self.index += 1
        if self.index > 2:
            raise StopAsyncIteration
        return SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content=f"token-{self.index}"))]
        )


@pytest.mark.asyncio
async def test_stream_deadline_does_not_cancel_consumer_between_tokens() -> None:
    completions = _Completions(result=_TwoTokenStream())
    client = LLMClient(_settings(llm_synthesis_timeout_seconds=0.01))
    client._groq = _provider(completions)
    stream = client.stream_synthesis("grounded prompt")

    assert await anext(stream) == "token-1"
    await asyncio.sleep(0.02)
    with pytest.raises(LLMUnavailable, match="after output began"):
        await anext(stream)

    assert completions.calls == 1
