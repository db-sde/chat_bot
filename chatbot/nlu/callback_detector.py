"""Zero-LLM callback detection that always runs before normal NLU."""

from __future__ import annotations

import re

_HUMAN = r"(?:counsell?or|advisor|human|person)"
_CALLBACK_PATTERNS = (
    r"\b(?:please\s+)?call\s+me\b",
    rf"\b(?:i\s+)?(?:want|need|would\s+like)\s+to\s+(?:talk|speak)\s+"
    rf"(?:to|with)\s+(?:someone|(?:an?|the)\s+{_HUMAN})\b",
    rf"\b(?:talk|speak)\s+(?:to|with)\s+(?:someone|(?:an?|the)?\s*{_HUMAN})\b",
    rf"\b(?:can|could|would)\s+(?:an?|the)\s+{_HUMAN}\s+help\s+me\b",
    rf"\bconnect\s+me(?:\s+(?:to|with)\s+(?:someone|(?:an?|the)?\s*{_HUMAN}))?\b",
    r"\bcontact\s+me\b",
    r"\b(?:i\s+)?(?:want|need|would\s+like|am\s+looking\s+for)\s+"
    r"(?:some\s+)?(?:admission\s+)?counsell?ing\b",
    r"\b(?:i\s+)?(?:want|need|would\s+like|am\s+looking\s+for)\s+"
    r"(?:some\s+)?admission\s+guidance\b",
    r"\badmission\s+guidance\s+please\b",
    r"\brequest\s+(?:a\s+)?callback\b",
    r"\bcallback\b",
)
_CALLBACK_RE = re.compile("|".join(_CALLBACK_PATTERNS), re.IGNORECASE)

_NEGATED_CALLBACK_RE = re.compile(
    r"\b(?:do\s+not|don['\u2019]?t|dont|never)\s+"
    r"(?:call|contact|connect)(?:\s+me)?\b|"
    r"\bno\s+(?:callback|call(?:s)?|contact)\b|"
    r"\b(?:do\s+not|don['\u2019]?t|dont|not)\s+(?:want|need)\s+(?:a\s+)?callback\b",
    re.IGNORECASE,
)


def is_callback_request(message: str) -> bool:
    """Return true only for an explicit request to speak with a person."""

    normalized = message.strip()
    if _NEGATED_CALLBACK_RE.search(normalized):
        return False
    return bool(_CALLBACK_RE.search(normalized))


def detect_callback(message: str) -> bool:
    """Backward-friendly named entrypoint."""

    return is_callback_request(message)
