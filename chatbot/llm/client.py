"""Resilient provider wrapper for intent classification and answer synthesis."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from google import genai
from google.genai import types as genai_types
from groq import AsyncGroq
from openai import AsyncOpenAI

from llm.prompts import SYNTHESIS_SYSTEM_PROMPT

LOGGER = logging.getLogger(__name__)
T = TypeVar("T")
_GEMINI_MIN_TRANSPORT_TIMEOUT_MS = 10_000
GEMINI_DECISION_ACTIONS = {
    "recommend",
    "discovery",
    "clarify",
    "callback",
    "unrelated",
    "unsupported_entity",
}
_DECISION_KEYS = {"action", "entity", "needs_clarification"}
_GEMINI_DECISION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["action", "entity", "needs_clarification"],
    "properties": {
        "action": {
            "type": "string",
            "enum": sorted(GEMINI_DECISION_ACTIONS),
            "description": (
                "Use callback when the user expresses confusion, asks for guidance or "
                "help deciding, or wants human assistance. Use clarify only for catalog "
                "entity or selection ambiguity. Use unsupported_entity when the message "
                "names an entity absent from Resolved so far. Use discovery only to browse "
                "catalog options without a missing named entity."
            ),
        },
        "entity": {
            "type": ["string", "null"],
            "description": (
                "The missing named entity only for unsupported_entity; otherwise null."
            ),
        },
        "needs_clarification": {
            "type": "boolean",
            "description": "True only when action is clarify.",
        },
    },
}
_CATALOG_FIELD_RE = re.compile(
    r'"(?:fee|price|cost|duration|naac|grade|eligibility|placement|salary|'
    r'accreditation|ranking)"\s*:',
    re.IGNORECASE,
)
_CATALOG_VALUE_RE = re.compile(
    r"(?:₹\s*\d|\bINR\s*[\d,]|\b\d+(?:\.\d+)?\s*"
    r"(?:years?|months?|semesters?|terms?|lpa)\b|\bNAAC\b|"
    r"\bgrade\s+[A-D](?:\+{1,2})?\b)",
    re.IGNORECASE,
)


class LLMUnavailable(RuntimeError):
    """Raised when a bounded LLM attempt cannot serve a request."""


class CircuitOpen(LLMUnavailable):
    """Raised while a provider's circuit breaker is cooling down."""


class LLMTimeout(LLMUnavailable):
    """Raised when the provider exceeds the single bounded attempt."""


class LLMParseFailure(LLMUnavailable):
    """Raised when a decision response is not valid strict JSON."""


class LLMDecisionSchemaFailure(LLMParseFailure):
    """Raised when parsed decision JSON violates the exact local schema."""


class LLMCatalogContentFailure(LLMParseFailure):
    """Raised when a decision response attempts to originate catalog-like facts."""


@dataclass(frozen=True, slots=True)
class GeminiDecision:
    """Strictly validated routing decision returned by Gemini."""

    action: str
    entity: str | None
    needs_clarification: bool


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise LLMDecisionSchemaFailure(f"duplicate decision field: {key}")
        value[key] = item
    return value


def _parse_gemini_decision(raw: str) -> GeminiDecision:
    if _CATALOG_FIELD_RE.search(raw) or _CATALOG_VALUE_RE.search(raw):
        raise LLMCatalogContentFailure(
            "Gemini decision contained suspected catalog-like content"
        )
    try:
        parsed = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
    except LLMParseFailure:
        raise
    except (json.JSONDecodeError, TypeError) as exc:
        raise LLMParseFailure("Gemini decision was not one JSON object") from exc
    if not isinstance(parsed, dict):
        raise LLMDecisionSchemaFailure("Gemini decision must be a JSON object")
    if set(parsed) != _DECISION_KEYS:
        raise LLMDecisionSchemaFailure("Gemini decision fields did not match the schema")

    action = parsed["action"]
    entity = parsed["entity"]
    needs_clarification = parsed["needs_clarification"]
    if not isinstance(action, str) or action not in GEMINI_DECISION_ACTIONS:
        raise LLMDecisionSchemaFailure("Gemini decision action was not allowed")
    if entity is not None and (
        not isinstance(entity, str) or not entity or entity != entity.strip()
    ):
        raise LLMDecisionSchemaFailure("Gemini decision entity must be a name or null")
    if type(needs_clarification) is not bool:
        raise LLMDecisionSchemaFailure(
            "Gemini decision needs_clarification must be boolean"
        )
    if action == "unsupported_entity" and entity is None:
        raise LLMDecisionSchemaFailure("unsupported_entity requires an entity name")
    if action != "unsupported_entity" and entity is not None:
        raise LLMDecisionSchemaFailure("only unsupported_entity may include an entity")
    if needs_clarification is not (action == "clarify"):
        raise LLMDecisionSchemaFailure(
            "needs_clarification must agree with the clarify action"
        )
    return GeminiDecision(action, entity, needs_clarification)


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
    """Wrap Gemini, Groq, and OpenAI behind bounded provider interfaces.

    Clients are created lazily so local development and the test suite work without API keys.
    Settings are accessed by attribute to keep this wrapper compatible with test settings.
    """

    settings: Any
    _groq: AsyncGroq | None = field(default=None, init=False, repr=False)
    _openai: AsyncOpenAI | None = field(default=None, init=False, repr=False)
    _gemini: genai.Client | None = field(default=None, init=False, repr=False)
    _breakers: dict[str, CircuitBreaker] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        threshold = int(getattr(self.settings, "llm_circuit_failure_threshold", 3))
        cooldown = float(getattr(self.settings, "llm_circuit_cooldown_seconds", 30.0))
        self._breakers = {
            "groq": CircuitBreaker(threshold, cooldown),
            "openai": CircuitBreaker(threshold, cooldown),
            "gemini": CircuitBreaker(threshold, cooldown),
        }

    @property
    def intent_configured(self) -> bool:
        return bool(getattr(self.settings, "gemini_api_key", None))

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
            # The application owns the request deadline and fallback path. SDK retries
            # would otherwise multiply that deadline before control returns to us.
            self._groq = AsyncGroq(api_key=key, max_retries=0)
        return self._groq

    def _openai_client(self) -> AsyncOpenAI:
        key = getattr(self.settings, "openai_api_key", None)
        if not key:
            raise LLMUnavailable("OPENAI_API_KEY is not configured")
        if self._openai is None:
            self._openai = AsyncOpenAI(api_key=key, max_retries=0)
        return self._openai

    def _gemini_client(self) -> genai.Client:
        key = getattr(self.settings, "gemini_api_key", None)
        if not key:
            raise LLMUnavailable("GEMINI_API_KEY is not configured")
        if self._gemini is None:
            timeout_ms = int(getattr(self.settings, "gemini_intent_timeout_ms", 1400))
            self._gemini = genai.Client(
                api_key=key,
                http_options=genai_types.HttpOptions(
                    # Gemini rejects server deadlines below 10 seconds. The
                    # classifier's outer asyncio deadline below still enforces
                    # the configured 1.2-1.5s application cutoff exactly.
                    timeout=max(timeout_ms, _GEMINI_MIN_TRANSPORT_TIMEOUT_MS),
                    retry_options=genai_types.HttpRetryOptions(attempts=1),
                ),
            )
        return self._gemini

    async def _bounded_call(
        self,
        provider: str,
        timeout: float,
        operation: Callable[[], Awaitable[T]],
    ) -> T:
        breaker = self._breakers[provider]
        breaker.before_call()
        try:
            async with asyncio.timeout(timeout):
                result = await operation()
        except Exception as exc:
            # Provider failures collapse to one typed application error. There is no
            # application retry: deterministic routing/fallback can resume immediately.
            breaker.failure()
            LOGGER.warning("%s LLM call failed: %s", provider, exc)
            raise LLMUnavailable(f"{provider} LLM call unavailable") from exc
        breaker.success()
        return result

    async def decide_action_tiny(
        self,
        message: str,
        mention_summary: str,
    ) -> GeminiDecision:
        """Choose one unresolved-turn action with a bounded strict-JSON request."""

        breaker = self._breakers["gemini"]
        breaker.before_call()
        timeout_ms = int(getattr(self.settings, "gemini_intent_timeout_ms", 1400))
        model = str(
            getattr(self.settings, "gemini_model", "gemini-3.1-flash-lite")
        )
        prompt = (
            "Given this message and what was found in the catalog, decide the action.\n\n"
            f"Message: {json.dumps(message, ensure_ascii=False)}\n"
            f"Resolved so far: {mention_summary}\n\n"
            "Return ONLY this JSON, no other text:\n"
            '{"action": "<one of: recommend, discovery, clarify, callback, '
            'unsupported_entity, unrelated>",\n'
            ' "entity": "<name mentioned but not found in catalog, or null>",\n'
            ' "needs_clarification": <true|false>}'
        )
        try:
            async with asyncio.timeout(timeout_ms / 1000):
                response = await self._gemini_client().aio.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=genai_types.GenerateContentConfig(
                        temperature=0,
                        max_output_tokens=96,
                        response_mime_type="application/json",
                        response_json_schema=_GEMINI_DECISION_SCHEMA,
                    ),
                )
            decision = _parse_gemini_decision(response.text or "")
        except CircuitOpen:
            raise
        except LLMParseFailure:
            breaker.failure()
            raise
        except TimeoutError as exc:
            breaker.failure()
            raise LLMTimeout("Gemini action decision timed out") from exc
        except Exception as exc:
            breaker.failure()
            if isinstance(exc, LLMUnavailable):
                raise
            raise LLMUnavailable("Gemini action decision unavailable") from exc
        breaker.success()
        return decision

    async def close(self) -> None:
        """Close the pooled Gemini async and sync transports."""

        if self._gemini is None:
            return
        try:
            await self._gemini.aio.aclose()
        finally:
            self._gemini.close()
            self._gemini = None

    def _synthesis_provider(self) -> str:
        return "openai" if getattr(self.settings, "openai_api_key", None) else "groq"

    async def synthesize(self, prompt: str) -> str:
        """Return one short grounded answer with one strict wall-clock deadline."""

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
            answer = (response.choices[0].message.content or "").strip()
            if not answer:
                raise ValueError("Synthesis provider returned an empty answer")
            return answer

        return await self._bounded_call(provider, timeout, operation)

    async def stream_synthesis(self, prompt: str) -> AsyncIterator[str]:
        """Yield provider deltas as they arrive; no buffer-then-flush behavior."""

        provider = self._synthesis_provider()
        breaker = self._breakers[provider]
        breaker.before_call()
        timeout = float(getattr(self.settings, "llm_synthesis_timeout_seconds", 5.0))
        emitted = False

        async def open_stream():
            if provider == "openai":
                return await self._openai_client().chat.completions.create(
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
                )
            return await self._groq_client().chat.completions.create(
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
            )

        deadline = asyncio.get_running_loop().time() + timeout
        try:
            # One absolute deadline covers connection setup and every streamed delta.
            # Each timeout context exits before yielding so its cancellation cannot leak into
            # caller work performed between tokens; all pulls still share the same deadline.
            async with asyncio.timeout_at(deadline):
                stream = await open_stream()
            iterator = stream.__aiter__()
            while True:
                try:
                    if asyncio.get_running_loop().time() >= deadline:
                        raise TimeoutError
                    async with asyncio.timeout_at(deadline):
                        chunk = await anext(iterator)
                except StopAsyncIteration:
                    break
                token = chunk.choices[0].delta.content or ""
                if token:
                    emitted = True
                    yield token
        except Exception as exc:
            breaker.failure()
            LOGGER.warning("%s streaming call failed: %s", provider, exc)
            suffix = " after output began" if emitted else ""
            raise LLMUnavailable(f"{provider} streaming unavailable{suffix}") from exc
        breaker.success()

    async def health(self) -> dict[str, Any]:
        """Probe configured provider APIs with a short, token-free models request."""

        async def probe(name: str) -> str:
            configured = {
                "gemini": self.intent_configured,
                "groq": bool(getattr(self.settings, "groq_api_key", None)),
                "openai": bool(getattr(self.settings, "openai_api_key", None)),
            }[name]
            if not configured:
                return "not_configured"
            if self._breakers[name].opened_at is not None:
                return "circuit_open"
            try:
                if name == "groq":
                    await asyncio.wait_for(self._groq_client().models.list(), timeout=1.0)
                elif name == "openai":
                    await asyncio.wait_for(self._openai_client().models.list(), timeout=1.0)
                else:
                    await asyncio.wait_for(
                        self._gemini_client().aio.models.get(
                            model=str(
                                getattr(
                                    self.settings,
                                    "gemini_model",
                                    "gemini-3.1-flash-lite",
                                )
                            )
                        ),
                        timeout=1.0,
                    )
                return "ok"
            except Exception:
                return "down"

        gemini, groq, openai = await asyncio.gather(
            probe("gemini"),
            probe("groq"),
            probe("openai"),
        )
        providers = {"gemini": gemini, "groq": groq, "openai": openai}
        degraded = any(value in {"down", "circuit_open"} for value in providers.values())
        return {"status": "degraded" if degraded else "ok", "providers": providers}
