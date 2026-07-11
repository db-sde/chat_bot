"""Resilient provider wrapper for intent classification and answer synthesis."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from groq import AsyncGroq
from openai import AsyncOpenAI

from llm.prompts import INTENT_SYSTEM_PROMPT, SYNTHESIS_SYSTEM_PROMPT

LOGGER = logging.getLogger(__name__)
T = TypeVar("T")
VALID_INTENTS = {"factual", "comparison", "advisory", "discovery", "chitchat"}


class LLMUnavailable(RuntimeError):
    """Raised after bounded retries when an LLM provider cannot serve a request."""


class CircuitOpen(LLMUnavailable):
    """Raised while a provider's circuit breaker is cooling down."""


@dataclass(slots=True)
class CircuitBreaker:
    """Simple consecutive-failure breaker with an automatic cooldown."""

    threshold: int = 3
    cooldown_seconds: float = 30.0
    failures: int = 0
    opened_at: float | None = None

    def before_call(self) -> None:
        if self.opened_at is None:
            return
        if time.monotonic() - self.opened_at >= self.cooldown_seconds:
            self.failures = 0
            self.opened_at = None
            return
        raise CircuitOpen("LLM circuit breaker is open")

    def success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def failure(self) -> None:
        self.failures += 1
        if self.failures >= self.threshold:
            self.opened_at = time.monotonic()


@dataclass(slots=True)
class LLMClient:
    """Wrap Groq and OpenAI behind a bounded, failure-aware interface.

    Clients are created lazily so local development and the test suite work without API keys.
    Settings are accessed by attribute to keep this wrapper compatible with test settings.
    """

    settings: Any
    _groq: AsyncGroq | None = field(default=None, init=False, repr=False)
    _openai: AsyncOpenAI | None = field(default=None, init=False, repr=False)
    _breakers: dict[str, CircuitBreaker] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        threshold = int(getattr(self.settings, "llm_circuit_failure_threshold", 3))
        cooldown = float(getattr(self.settings, "llm_circuit_cooldown_seconds", 30.0))
        self._breakers = {
            "groq": CircuitBreaker(threshold, cooldown),
            "openai": CircuitBreaker(threshold, cooldown),
        }

    @property
    def intent_configured(self) -> bool:
        return bool(getattr(self.settings, "groq_api_key", None))

    @property
    def synthesis_configured(self) -> bool:
        return bool(
            getattr(self.settings, "openai_api_key", None)
            or getattr(self.settings, "groq_api_key", None)
        )

    def _groq_client(self) -> AsyncGroq:
        key = getattr(self.settings, "groq_api_key", None)
        if not key:
            raise LLMUnavailable("GROQ_API_KEY is not configured")
        if self._groq is None:
            self._groq = AsyncGroq(api_key=key)
        return self._groq

    def _openai_client(self) -> AsyncOpenAI:
        key = getattr(self.settings, "openai_api_key", None)
        if not key:
            raise LLMUnavailable("OPENAI_API_KEY is not configured")
        if self._openai is None:
            self._openai = AsyncOpenAI(api_key=key)
        return self._openai

    async def _bounded_call(
        self,
        provider: str,
        timeout: float,
        operation: Callable[[], Awaitable[T]],
    ) -> T:
        breaker = self._breakers[provider]
        breaker.before_call()
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                result = await asyncio.wait_for(operation(), timeout=timeout)
                breaker.success()
                return result
            except Exception as exc:
                # SDK exceptions intentionally collapse to one typed application error. A
                # single retry is permitted; authentication/validation errors remain bounded.
                last_error = exc
                if attempt == 0:
                    await asyncio.sleep(0.05)
        breaker.failure()
        LOGGER.warning("%s LLM call failed: %s", provider, last_error)
        raise LLMUnavailable(f"{provider} LLM call unavailable") from last_error

    async def classify_intent(self, message: str) -> str:
        """Classify intent with Groq, returning only a supported label."""

        model = getattr(self.settings, "groq_intent_model", "llama-3.1-8b-instant")
        timeout = float(getattr(self.settings, "llm_intent_timeout_seconds", 2.5))

        async def operation() -> str:
            response = await self._groq_client().chat.completions.create(
                model=model,
                temperature=0,
                max_tokens=8,
                messages=[
                    {"role": "system", "content": INTENT_SYSTEM_PROMPT},
                    {"role": "user", "content": message[:1_500]},
                ],
            )
            return (response.choices[0].message.content or "").strip().lower()

        label = await self._bounded_call("groq", timeout, operation)
        if label not in VALID_INTENTS:
            raise LLMUnavailable("Intent provider returned an unsupported label")
        return label

    def _synthesis_provider(self) -> str:
        return "openai" if getattr(self.settings, "openai_api_key", None) else "groq"

    async def synthesize(self, prompt: str) -> str:
        """Return one short grounded answer, with a strict timeout and one retry."""

        provider = self._synthesis_provider()
        timeout = float(getattr(self.settings, "llm_synthesis_timeout_seconds", 5.0))

        async def operation() -> str:
            if provider == "openai":
                response = await self._openai_client().chat.completions.create(
                    model=getattr(self.settings, "openai_synthesis_model", "gpt-4.1-mini"),
                    temperature=0.2,
                    max_tokens=220,
                    messages=[
                        {"role": "system", "content": SYNTHESIS_SYSTEM_PROMPT},
                        {"role": "user", "content": prompt[:8_000]},
                    ],
                )
            else:
                response = await self._groq_client().chat.completions.create(
                    model=getattr(self.settings, "groq_synthesis_model", "llama-3.3-70b-versatile"),
                    temperature=0.2,
                    max_tokens=220,
                    messages=[
                        {"role": "system", "content": SYNTHESIS_SYSTEM_PROMPT},
                        {"role": "user", "content": prompt[:8_000]},
                    ],
                )
            return (response.choices[0].message.content or "").strip()

        answer = await self._bounded_call(provider, timeout, operation)
        if not answer:
            raise LLMUnavailable("Synthesis provider returned an empty answer")
        return answer

    async def stream_synthesis(self, prompt: str) -> AsyncIterator[str]:
        """Yield provider deltas as they arrive; no buffer-then-flush behavior."""

        provider = self._synthesis_provider()
        breaker = self._breakers[provider]
        breaker.before_call()
        timeout = float(getattr(self.settings, "llm_synthesis_timeout_seconds", 5.0))
        emitted = False

        async def open_stream():
            if provider == "openai":
                return await asyncio.wait_for(
                    self._openai_client().chat.completions.create(
                        model=getattr(
                            self.settings, "openai_synthesis_model", "gpt-4.1-mini"
                        ),
                        temperature=0.2,
                        max_tokens=220,
                        stream=True,
                        messages=[
                            {"role": "system", "content": SYNTHESIS_SYSTEM_PROMPT},
                            {"role": "user", "content": prompt[:8_000]},
                        ],
                    ),
                    timeout=timeout,
                )
            return await asyncio.wait_for(
                self._groq_client().chat.completions.create(
                    model=getattr(
                        self.settings, "groq_synthesis_model", "llama-3.3-70b-versatile"
                    ),
                    temperature=0.2,
                    max_tokens=220,
                    stream=True,
                    messages=[
                        {"role": "system", "content": SYNTHESIS_SYSTEM_PROMPT},
                        {"role": "user", "content": prompt[:8_000]},
                    ],
                ),
                timeout=timeout,
            )

        last_error: Exception | None = None
        for attempt in range(2):
            try:
                stream = await open_stream()
                async with asyncio.timeout(timeout):
                    async for chunk in stream:
                        token = chunk.choices[0].delta.content or ""
                        if token:
                            emitted = True
                            yield token
                breaker.success()
                return
            except Exception as exc:
                last_error = exc
                if not emitted and attempt == 0:
                    await asyncio.sleep(0.05)
                    continue
                break

        breaker.failure()
        LOGGER.warning("%s streaming call failed: %s", provider, last_error)
        suffix = " after output began" if emitted else ""
        raise LLMUnavailable(f"{provider} streaming unavailable{suffix}") from last_error

    async def health(self) -> dict[str, Any]:
        """Probe configured provider APIs with a short, token-free models request."""

        async def probe(name: str) -> str:
            configured = (
                self.intent_configured
                if name == "groq"
                else bool(getattr(self.settings, "openai_api_key", None))
            )
            if not configured:
                return "not_configured"
            if self._breakers[name].opened_at is not None:
                return "circuit_open"
            try:
                if name == "groq":
                    await asyncio.wait_for(self._groq_client().models.list(), timeout=1.0)
                else:
                    await asyncio.wait_for(self._openai_client().models.list(), timeout=1.0)
                return "ok"
            except Exception:
                return "down"

        groq, openai = await asyncio.gather(probe("groq"), probe("openai"))
        providers = {"groq": groq, "openai": openai}
        degraded = any(value in {"down", "circuit_open"} for value in providers.values())
        return {"status": "degraded" if degraded else "ok", "providers": providers}
