"""Zero-LLM callback detection that always runs before normal NLU."""

from __future__ import annotations

import re

_CALLBACK_PATTERNS = (
    r"\b(?:please\s+)?call\s+me\b",
    r"\b(?:i\s+)?(?:want|need|would like)\s+to\s+(?:talk|speak)\s+(?:to|with)\s+"
    r"(?:someone|a\s+(?:counsell?or|advisor|human|person))\b",
    r"\bconnect\s+me\b",
    r"\bcontact\s+me\b",
    r"\bspeak\s+(?:to|with)\s+(?:a\s+)?(?:counsell?or|advisor|human|person)\b",
    r"\btalk\s+(?:to|with)\s+(?:someone|a\s+(?:counsell?or|advisor|human|person))\b",
    r"\brequest\s+(?:a\s+)?callback\b",
    r"\bcallback\b",
)
_CALLBACK_RE = re.compile("|".join(_CALLBACK_PATTERNS), re.IGNORECASE)


def is_callback_request(message: str) -> bool:
    """Return true only for an explicit request to speak with a person."""

    return bool(_CALLBACK_RE.search(message.strip()))


def detect_callback(message: str) -> bool:
    """Backward-friendly named entrypoint."""

    return is_callback_request(message)
