"""Outcome-driven intent classification for unresolved catalog turns."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from llm.client import (
    CircuitOpen,
    LLMCatalogContentFailure,
    LLMParseFailure,
    LLMTimeout,
    LLMUnavailable,
)
from nlu.action_classifier import Action

LOGGER = logging.getLogger("chatbot.nlu")


class Intent(StrEnum):
    FACTUAL = "factual"
    COMPARISON = "comparison"
    ADVISORY = "advisory"
    DISCOVERY = "discovery"
    CALLBACK = "callback"
    CHITCHAT = "chitchat"
    UNRELATED = "unrelated"
    UNRESOLVED_ENTITY = "unresolved_entity"


_CHITCHAT = re.compile(
    r"^\s*(?:hi|hello|hey|good\s+(?:morning|afternoon|evening)|"
    r"thanks?|thank\s+you|bye)[!. ]*$",
    re.IGNORECASE,
)

# These two bounded patterns are used only after the taxonomy has already found
# HIGH-confidence catalog evidence. They preserve zero-LLM comparison/advisory
# routing; they are not an escalation classifier for unresolved messages.
_CATALOG_COMPARISON = re.compile(
    r"\b(?:compare|comparison|versus|vs\.?|difference\s+between)\b|"
    r"\bwhich\b[^?]{0,100}\bbetter\b[^?]{0,100}\bor\b",
    re.IGNORECASE,
)
_CATALOG_ADVISORY = re.compile(
    r"\b(?:best\b[^?]{0,80}\bfor\s+me|"
    r"which\b[^?]{0,80}\b(?:should\s+i|is\s+best|has\s+the\s+best)|"
    r"which\s+university\b[^?]{0,80}\b(?:highest|reasonable\s+fees?)|"
    r"recommend|suggest|suit(?:s|able)?\s+(?:me|my)|help\s+me\s+choose|"
    r"career\s+(?:guidance|growth)|working\s+professional\s+(?:advice|guidance))\b",
    re.IGNORECASE,
)
_DISCOVERY = re.compile(
    r"\b(?:what\s+(?:courses|programs|universities)\s+(?:are|do\s+you\s+have)|"
    r"show\s+me\s+(?:courses|programs|universities)|explore|browse|"
    r"available\s+(?:courses|programs)|online\s+programs?)\b",
    re.IGNORECASE,
)

_DOMAIN_VOCABULARY = re.compile(
    r"\b(?:accreditation|admission|career|course|degree|duration|eligibility|"
    r"fees?|naac|online|placement|program|speciali[sz]ation|"
    r"ugc|uni(?:versity|versities)?)\b",
    re.IGNORECASE,
)

_OPEN_REASONING = re.compile(
    r"\b(?:confus(?:ed|ing)|help\s+(?:me\s+)?(?:decid(?:e|ing)|choose)|"
    r"guide\s+me|somebody\s+guide|someone\s+to\s+help|career\s+(?:guidance|growth)|"
    r"working\s+professional|recommend|suggest|"
    r"best\b[^?]{0,80}\bfor\s+me|"
    r"compare|comparison|versus|vs\.?|which\s+should\s+i)\b",
    re.IGNORECASE,
)


def is_exact_chitchat(message: str) -> bool:
    """Return true only for the small exact greeting/thanks/bye fast path."""

    return bool(_CHITCHAT.fullmatch(message.strip()))


def catalog_intent(message: str) -> Intent:
    """Backward-compatible name for the bounded local regex classifier."""

    return heuristic_intent(message)


def heuristic_intent(message: str) -> Intent:
    """Return a bounded local intent; FACTUAL means no confident regex result."""

    if is_exact_chitchat(message):
        return Intent.CHITCHAT
    if _CATALOG_COMPARISON.search(message):
        return Intent.COMPARISON
    if _CATALOG_ADVISORY.search(message):
        return Intent.ADVISORY
    if _DISCOVERY.search(message):
        return Intent.DISCOVERY
    return Intent.FACTUAL


def fallback_intent(message: str) -> Intent:
    """Minimal degraded-mode fallback used only when Gemini cannot classify."""

    return Intent.FACTUAL if _DOMAIN_VOCABULARY.search(message) else Intent.UNRESOLVED_ENTITY


def should_use_reasoning_llm(message: str) -> bool:
    """Gate Gemini to advisory/comparison/open-reasoning turns only."""

    return bool(_OPEN_REASONING.search(message))


def _failure_reason(error: Exception) -> str:
    if isinstance(error, LLMCatalogContentFailure):
        return "catalog-content"
    if isinstance(error, CircuitOpen):
        return "circuit-open"
    if isinstance(error, LLMTimeout):
        return "timeout"
    if isinstance(error, (LLMParseFailure, ValueError)):
        return "parse-failure"
    return "provider-unavailable"


@dataclass(frozen=True, slots=True)
class ActionDecision:
    """Action chosen by Gemini or the degraded local fallback."""

    action: Action
    entity: str | None = None
    needs_clarification: bool = False
    source: str = "gemini"


async def decide_action(
    message: str,
    mention_summary: str,
    llm: Any,
    *,
    metrics: Any | None = None,
    message_metric: Any | None = None,
) -> ActionDecision:
    """Run one strict Gemini decision, falling back locally without a retry."""

    call_metric = (
        metrics.begin_llm_intent(message_metric)
        if metrics is not None and message_metric is not None
        else None
    )
    try:
        decision = await llm.decide_action_tiny(message, mention_summary)
        action = Action(decision.action)
        entity = decision.entity
        needs_clarification = decision.needs_clarification
    except (LLMUnavailable, ValueError, AttributeError, TypeError) as error:
        reason = _failure_reason(error)
        if call_metric is not None:
            metrics.finish(call_metric, failed=True)
        if reason == "catalog-content":
            LOGGER.warning(
                "Gemini decision rejected catalog-like content reason=%s error=%s",
                reason,
                type(error).__name__,
            )
        else:
            LOGGER.warning(
                "Gemini action fallback reason=%s error=%s",
                reason,
                type(error).__name__,
            )
        fallback = fallback_intent(message)
        action = (
            Action.GET_FACTS
            if fallback is Intent.FACTUAL
            else Action.UNSUPPORTED_ENTITY
        )
        return ActionDecision(action=action, source="heuristic_regex")

    if call_metric is not None:
        metrics.finish(call_metric, failed=False)
    return ActionDecision(
        action=action,
        entity=entity,
        needs_clarification=needs_clarification,
    )


__all__ = [
    "ActionDecision",
    "Intent",
    "catalog_intent",
    "decide_action",
    "fallback_intent",
    "heuristic_intent",
    "is_exact_chitchat",
    "should_use_reasoning_llm",
]
