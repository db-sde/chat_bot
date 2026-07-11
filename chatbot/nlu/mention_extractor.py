"""Extract raw, independent slot candidates without making resolution decisions."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

TOKEN_RE = re.compile(r"[a-z0-9]+(?:['&-][a-z0-9]+)?", re.IGNORECASE)
REFERENCE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "course",
        re.compile(
            r"\b(?:this|that|the)\s+(?:course|program|degree)\b|\b(?:universit(?:y|ies)|uni)\s+(?:that\s+)?provide\s+(?:this|it)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "university",
        re.compile(r"\b(?:this|that|the)\s+(?:university|uni|college|institute)\b", re.IGNORECASE),
    ),
    (
        "entity",
        re.compile(r"\b(?:it|this\s+one|that\s+one|this\s+program)\b", re.IGNORECASE),
    ),
    (
        "course",
        re.compile(
            r"\b(?:for\s+)?which\s+(?:uni(?:versity)?|universities)\b|"
            r"\bwho\s+offers\s+(?:this|it)\b",
            re.IGNORECASE,
        ),
    ),
)


@dataclass(slots=True)
class MentionResult:
    """Raw matcher output; candidate arbitration belongs to resolver/."""

    universities: list[Any] = field(default_factory=list)
    courses: list[Any] = field(default_factory=list)
    specializations: list[Any] = field(default_factory=list)
    reference: str | None = None
    tokens: list[str] = field(default_factory=list)

    @property
    def has_explicit_mentions(self) -> bool:
        return bool(self.universities or self.courses or self.specializations)

    def candidates_for(self, slot_type: str) -> list[Any]:
        return {
            "university": self.universities,
            "course": self.courses,
            "category": self.courses,
            "specialization": self.specializations,
        }.get(slot_type, [])


def tokenize(message: str) -> list[str]:
    """Normalize a user utterance into taxonomy-safe lowercase tokens."""

    return [match.group(0).lower().strip("-'&") for match in TOKEN_RE.finditer(message)]


def detect_reference(message: str) -> str | None:
    for kind, pattern in REFERENCE_PATTERNS:
        if pattern.search(message):
            return kind
    return None


def extract_mentions(message: str, matcher: Any) -> MentionResult:
    """Resolve all slot types independently and retain every candidate."""

    tokens = tokenize(message)
    courses = list(matcher.resolve_slot(tokens, "course"))
    specializations = list(matcher.resolve_slot(tokens, "specialization"))
    high_category_spans = [
        (candidate.start, candidate.end)
        for candidate in courses
        if getattr(candidate, "confidence", None) == "HIGH"
    ]
    # Category scope wins only where its matched interval contains the specialization
    # interval. Disjoint evidence such as "MBA Marketing" must remain independently usable.
    specializations = [
        candidate
        for candidate in specializations
        if not any(
            start <= getattr(candidate, "start", 0)
            and getattr(candidate, "end", 0) <= end
            for start, end in high_category_spans
        )
    ]
    return MentionResult(
        universities=list(matcher.resolve_slot(tokens, "university")),
        courses=courses,
        specializations=specializations,
        reference=detect_reference(message),
        tokens=tokens,
    )
