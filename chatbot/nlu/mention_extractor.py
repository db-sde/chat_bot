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
    # Terms requested in a structured entity-bearing phrase that the taxonomy did
    # not resolve.  This is deliberately conservative: it is used to acknowledge a
    # partial match, never to manufacture a new catalog entity.
    unresolved_terms: list[str] = field(default_factory=list)

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


def _display_unresolved(value: str) -> str:
    words = [word for word in value.strip(" ,.-").split() if word]
    return " ".join(word.upper() if len(word) <= 3 else word.title() for word in words)


def _remove_known_phrases(value: str, candidates: list[Any]) -> str:
    remaining = value.casefold()
    phrases = sorted(
        {
            str(getattr(candidate, "matched_span", "")).strip().casefold()
            for candidate in candidates
            if getattr(candidate, "matched_span", None)
        },
        key=len,
        reverse=True,
    )
    for phrase in phrases:
        remaining = re.sub(rf"\b{re.escape(phrase)}\b", " ", remaining)
    remaining = re.sub(
        r"\b(?:compare|comparison|and|or|vs|versus|with|of|the|an?|"
        r"for|at|from|online|distance|affordable|reasonable|best|top|highest|"
        r"cheap(?:est)?|low(?:er)?|flexible|university|uni|college|institute|"
        r"course|program|degree|mba|mca|fees?|cost|eligibility|duration|"
        r"speciali[sz]ation)\b",
        " ",
        remaining,
    )
    return " ".join(remaining.split())


def _comparison_clauses(message: str) -> tuple[str, str] | None:
    patterns = (
        r"\bcompare\s+(.+?)\s+(?:and|vs\.?|versus)\s+(.+?)(?:[?.!]|$)",
        r"\bdifference\s+between\s+(.+?)\s+and\s+(.+?)(?:[?.!]|$)",
        r"\bwhich\b[^?]*?\bbetter\b\s*[,;:]?\s*(.+?)\s+or\s+(.+?)(?:[?.!]|$)",
        r"^\s*(.+?)\s+(?:vs\.?|versus)\s+(.+?)(?:[?.!]|$)",
    )
    for pattern in patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            return match.group(1), match.group(2)
    return None


def _unresolved_terms(
    message: str,
    *,
    universities: list[Any],
    courses: list[Any],
    specializations: list[Any],
) -> list[str]:
    """Return only high-signal unknown operands/qualifiers from structured queries."""

    candidates = [*universities, *courses, *specializations]
    unresolved: list[str] = []

    # Unknown institution qualifier immediately before a resolved degree.
    institution = re.search(
        r"\btell\s+me\s+about\s+(.+?)\s+(?:online\s+)?(?:mba|mca)\b",
        message,
        re.IGNORECASE,
    )
    if institution and courses and not universities:
        value = _remove_known_phrases(institution.group(1), candidates)
        if value:
            unresolved.append(_display_unresolved(value))

    # Unknown specialization qualifier after a degree. Stop at punctuation or a
    # new question so discovery wording after a known specialization is not swept in.
    specialization = re.search(
        r"\b(?:mba|mca)\s+in\s+([a-z][a-z0-9& -]*?)"
        r"(?=[?.!,;]|\b(?:what|which|who|how)\b|$)",
        message,
        re.IGNORECASE,
    )
    if specialization and courses and not specializations:
        value = _remove_known_phrases(specialization.group(1), candidates)
        if value:
            unresolved.append(_display_unresolved(value))

    # Preserve an unknown side of a named comparison (Harvard vs LPU). Known
    # category/specialization/provider words are removed before deciding that a
    # clause contains a missing operand.
    comparison = _comparison_clauses(message)
    if comparison and candidates:
        for clause in comparison:
            value = _remove_known_phrases(clause, candidates)
            if value:
                unresolved.append(_display_unresolved(value))

    return list(dict.fromkeys(unresolved))


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
    universities = list(matcher.resolve_slot(tokens, "university"))
    return MentionResult(
        universities=universities,
        courses=courses,
        specializations=specializations,
        reference=detect_reference(message),
        tokens=tokens,
        unresolved_terms=_unresolved_terms(
            message,
            universities=universities,
            courses=courses,
            specializations=specializations,
        ),
    )
