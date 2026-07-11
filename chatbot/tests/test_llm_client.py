import asyncio
from types import SimpleNamespace

import pytest

import llm.client as client_module
from llm.client import LLMClient, LLMUnavailable


def _settings(**overrides):
    values = {
        "groq_api_key": "groq-test-key",
        "openai_api_key": None,
        "llm_intent_timeout_seconds": 0.2,
        "llm_synthesis_timeout_seconds": 0.2,
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


def test_provider_clients_disable_sdk_retries(monkeypatch) -> None:
    captured: dict[str, dict] = {}

    def fake_groq(**kwargs):
        captured["groq"] = kwargs
        return object()

    def fake_openai(**kwargs):
        captured["openai"] = kwargs
        return object()

    monkeypatch.setattr(client_module, "AsyncGroq", fake_groq)
    monkeypatch.setattr(client_module, "AsyncOpenAI", fake_openai)
    client = LLMClient(_settings(openai_api_key="openai-test-key"))

    client._groq_client()
    client._openai_client()

    assert captured["groq"]["max_retries"] == 0
    assert captured["openai"]["max_retries"] == 0


@pytest.mark.asyncio
async def test_failed_completion_has_one_provider_attempt() -> None:
    completions = _Completions(error=ConnectionError("provider down"))
    client = LLMClient(_settings())
    client._groq = _provider(completions)

    with pytest.raises(LLMUnavailable, match="groq LLM call unavailable"):
        await client.classify_intent("Tell me about LPU")

    assert completions.calls == 1
    assert client._breakers["groq"].failures == 1


@pytest.mark.asyncio
async def test_invalid_intent_counts_as_one_failed_provider_attempt() -> None:
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="not-a-valid-intent"))]
    )
    completions = _Completions(result=response)
    client = LLMClient(_settings())
    client._groq = _provider(completions)

    with pytest.raises(LLMUnavailable, match="groq LLM call unavailable"):
        await client.classify_intent("Tell me about LPU")

    assert completions.calls == 1
    assert client._breakers["groq"].failures == 1


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
