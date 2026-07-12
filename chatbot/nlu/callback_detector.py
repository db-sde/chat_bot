"""Zero-LLM callback detection that always runs before normal NLU."""

from __future__ import annotations

import re

from rapidfuzz import fuzz

_HUMAN_TERMS = (
    "counsellor",
    "counselor",
    "advisor",
    "adviser",
    "admissions",
    "admission",
    "human",
    "person",
    "agent",
    "representative",
    "someone",
)
# Tuned against real typos ("counsular", "concellor") — fuzz.ratio on a single
# substitution/transposition in a 9-10 char word typically lands in the high 70s,
# so 75 is the floor that catches those without opening up to unrelated words.
_HUMAN_FUZZY_THRESHOLD = 75
_MIN_FUZZY_LEN = 4  # skip short words (to, my, an) so they can't accidentally score high

_VERB_TARGET_RE = re.compile(
    r"\b(?:want|need|would\s+like|am\s+looking\s+for)?\s*"
    r"(?:to\s+)?(?:talk|speak|connect|chat)\s+"
    r"(?:me\s+)?"
    r"(?:to\s+|with\s+)?"  # preposition is now optional — "talk counsellor" must still match
    r"(?:an?\s+|the\s+)?"
    r"([a-z]+)\b",
    re.IGNORECASE,
)

_HUMAN_HELP_RE = re.compile(
    r"\b(?:can|could|would)\s+(?:an?\s+|the\s+)?([a-z]+)\s+help\s+me\b",
    re.IGNORECASE,
)

_DIRECT_PATTERNS = (
    r"\b(?:please\s+)?call\s+me\b",
    r"\bcontact\s+me\b",
    r"\brequest\s+(?:a\s+)?callback\b",
    r"\bcallback\b",
    # "connect me" alone (no stated target) is still a valid bare request; if a
    # target follows, _VERB_TARGET_RE below decides whether it's human-related —
    # this stops "connect me to the LPU website" from false-triggering.
    r"\bconnect\s+me\b(?=$|[.!?,]|\s+(?:please|now|asap|today)\b)",
    r"\b(?:i\s+)?(?:want|need|would\s+like|am\s+looking\s+for)\s+"
    r"(?:some\s+)?(?:admission\s+)?counsell?ing\b",
    r"\b(?:i\s+)?(?:want|need|would\s+like|am\s+looking\s+for)\s+"
    r"(?:some\s+)?admission\s+guidance\b",
    r"\badmission\s+guidance\s+please\b",
)
_DIRECT_RE = re.compile("|".join(_DIRECT_PATTERNS), re.IGNORECASE)

_NEGATED_CALLBACK_RE = re.compile(
    r"\b(?:do\s+not|don['\u2019]?t|dont|never)\s+"
    r"(?:call|contact|connect)(?:\s+me)?\b|"
    r"\bno\s+(?:callback|call(?:s)?|contact)\b|"
    r"\b(?:do\s+not|don['\u2019]?t|dont|not)\s+(?:want|need)\s+(?:a\s+)?callback\b",
    re.IGNORECASE,
)


def _fuzzy_human_match(word: str) -> bool:
    word = word.lower()
    if word in _HUMAN_TERMS:
        return True
    if len(word) < _MIN_FUZZY_LEN:
        return False
    return any(fuzz.ratio(word, term) >= _HUMAN_FUZZY_THRESHOLD for term in _HUMAN_TERMS)


def is_callback_request(message: str) -> bool:
    """Return true for an explicit request to speak with a person, tolerating typos
    and missing prepositions ("talk counsellor", "talk to counsular")."""

    normalized = message.strip()
    if not normalized:
        return False
    if _NEGATED_CALLBACK_RE.search(normalized):
        return False
    if _DIRECT_RE.search(normalized):
        return True
    return any(
        _fuzzy_human_match(match.group(1))
        for pattern in (_VERB_TARGET_RE, _HUMAN_HELP_RE)
        for match in pattern.finditer(normalized)
    )


def detect_callback(message: str) -> bool:
    """Backward-friendly named entrypoint."""

    return is_callback_request(message)
