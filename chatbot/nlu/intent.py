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
    r"\b(?:compare|comparison|versus|vs\.?|difference\s+between)\b|"
    r"\bwhich\b[^?]{0,100}\bbetter\b[^?]{0,100}\bor\b",
    re.IGNORECASE,
)
_ADVISORY = re.compile(
    r"\b(?:best\s+for\s+me|"
    r"which\s+(?:one|course|program|university|(?:online\s+)?mba|mca|"
    r"speciali[sz]ation)\b[^?]{0,80}\b(?:should\s+i|is\s+best|has\s+the\s+best)|"
    r"which\s+university\b[^?]{0,80}\b(?:highest|reasonable\s+fees?)|"
    r"recommend|suggest|suit(?:s|able)?\s+(?:me|my)|help\s+me\s+choose)\b",
    re.IGNORECASE,
)
_DISCOVERY = re.compile(
    r"\b(?:what\s+(?:courses|programs|universities)\s+(?:are|do\s+you\s+have)|show\s+me\s+(?:courses|programs|universities)|explore|browse|available\s+(?:courses|programs)|online\s+programs?)\b",
    re.IGNORECASE,
)
_STRUCTURED_FACTUAL = re.compile(
    r"\b(?:which\s+(?:universities|university|uni)\s+(?:offers?|provides?)|"
    r"who\s+offers?|tell\s+me\s+about|what\s+is\s+the\s+|"
    r"is\s+.+\s+(?:approved|accredited))\b",
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
    if (
        heuristic is not Intent.FACTUAL
        or _STRUCTURED_FACTUAL.search(message)
        or not llm
        or not use_llm
    ):
        return heuristic
    if not getattr(llm, "intent_configured", False):
        return heuristic
    try:
        return Intent(await llm.classify_intent(message))
    except (LLMUnavailable, ValueError):
        return heuristic
