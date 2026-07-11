"""Bounded intent classification with a deterministic outage fallback."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Any

from llm.client import LLMUnavailable


class Intent(StrEnum):
    FACTUAL = "factual"
    COMPARISON = "comparison"
    ADVISORY = "advisory"
    DISCOVERY = "discovery"
    CHITCHAT = "chitchat"
    UNRELATED = "unrelated"


_CHITCHAT = re.compile(
    r"^\s*(?:hi|hello|hey|good\s+(?:morning|afternoon|evening)|thanks?|thank\s+you|bye)[!. ]*$",
    re.IGNORECASE,
)
_COMPARISON = re.compile(
    r"\b(?:compare|comparison|versus|vs\.?|difference\s+between)\b",
    re.IGNORECASE,
)
_ADVISORY = re.compile(
    r"\b(?:best\s+for\s+me|which\s+(?:one|course|program|university)\s+should\s+i|recommend|suggest|suit(?:s|able)?\s+(?:me|my)|help\s+me\s+choose)\b",
    re.IGNORECASE,
)
_DISCOVERY = re.compile(
    r"\b(?:what\s+(?:courses|programs|universities)\s+(?:are|do\s+you\s+have)|show\s+me\s+(?:courses|programs|universities)|explore|browse|available\s+(?:courses|programs)|online\s+programs?)\b",
    re.IGNORECASE,
)
_UNRELATED = re.compile(
    r"\b(?:value\s+of\s+pi|capital\s+of\s+[a-z]+|weather\s+(?:in|for)|"
    r"cricket\s+score|tell\s+me\s+a\s+joke|recipe\s+for|who\s+is\s+the\s+"
    r"(?:president|prime\s+minister)|solve\s+(?:this\s+)?(?:equation|integral))\b",
    re.IGNORECASE,
)


def heuristic_intent(message: str) -> Intent:
    text = message.strip()
    if _CHITCHAT.fullmatch(text):
        return Intent.CHITCHAT
    if _COMPARISON.search(text):
        return Intent.COMPARISON
    if _ADVISORY.search(text):
        return Intent.ADVISORY
    if _DISCOVERY.search(text):
        return Intent.DISCOVERY
    if _UNRELATED.search(text):
        return Intent.UNRELATED
    return Intent.FACTUAL


async def classify_intent(message: str, llm: Any | None = None, *, use_llm: bool = True) -> Intent:
    """Classify intent, failing closed to the local deterministic classifier."""

    heuristic = heuristic_intent(message)
    # Explicit linguistic signals are cheaper and more reliable than a network round trip.
    if heuristic is not Intent.FACTUAL or not llm or not use_llm:
        return heuristic
    if not getattr(llm, "intent_configured", False):
        return heuristic
    try:
        return Intent(await llm.classify_intent(message))
    except (LLMUnavailable, ValueError):
        return heuristic
