"""Pure action selection from resolved catalog mentions and bounded phrase markers."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Any


class Action(StrEnum):
    """Response actions shared by deterministic, heuristic, and Gemini sources."""

    GET_FACTS = "get_facts"
    LIST_SPECIALIZATIONS = "list_specializations"
    LIST_PROVIDERS = "list_providers"
    COMPARE = "compare"
    RECOMMEND = "recommend"
    DISCOVERY = "discovery"
    CLARIFY = "clarify"
    CALLBACK = "callback"
    UNSUPPORTED_ENTITY = "unsupported_entity"
    CHITCHAT = "chitchat"
    UNRELATED = "unrelated"
    FALLBACK = "fallback"


_SPECIALIZATION_MARKER = re.compile(r"\bspeciali[sz]ations?\b", re.IGNORECASE)
_PROVIDER_REQUEST = re.compile(
    r"\b(?:which\s+universit(?:y|ies)\s+(?:offers?|provides?)|who\s+offers?)\b",
    re.IGNORECASE,
)
_OPTIONS_REQUEST = re.compile(
    r"\b(?:what\s+are\s+(?:my|the)\s+options?|what\s+options?\s+(?:are\s+)?available)\b",
    re.IGNORECASE,
)
_COMPARE_MARKER = re.compile(
    r"\b(?:compare|comparison|versus|vs\.?|difference\s+between)\b|"
    r"\bwhich\b[^?]{0,100}\bbetter\b[^?]{0,100}\bor\b",
    re.IGNORECASE,
)
_RECOMMEND_MARKER = re.compile(
    r"\b(?:best\s+for\s+me|recommend|suggest|help\s+me\s+choose|"
    r"which\s+(?:one|course|program|university|(?:online\s+)?mba|mca|"
    r"speciali[sz]ation)\b[^?]{0,80}\b(?:should\s+i|is\s+best|has\s+the\s+best)|"
    r"which\s+university\b[^?]{0,80}\b(?:highest|reasonable\s+fees?))\b",
    re.IGNORECASE,
)


def _candidates(mentions: Any, field: str, *, confidence: str = "HIGH") -> list[Any]:
    return [
        candidate
        for candidate in getattr(mentions, field, ()) or ()
        if str(getattr(candidate, "confidence", "")).upper() == confidence
    ]


def _semantic_groups(candidates: list[Any], slot: str) -> dict[tuple[Any, ...], list[Any]]:
    groups: dict[tuple[Any, ...], list[Any]] = {}
    for candidate in candidates:
        key = (
            slot,
            int(getattr(candidate, "start", 0)),
            int(getattr(candidate, "end", 0)),
            " ".join(str(getattr(candidate, "matched_span", "")).casefold().split()),
        )
        groups.setdefault(key, []).append(candidate)
    return groups


def _all_high_groups(mentions: Any) -> dict[tuple[Any, ...], list[Any]]:
    groups: dict[tuple[Any, ...], list[Any]] = {}
    for slot, field in (
        ("university", "universities"),
        ("category", "courses"),
        ("specialization", "specializations"),
    ):
        groups.update(_semantic_groups(_candidates(mentions, field), slot))
    return groups


def _one_specialization_family(mentions: Any) -> bool:
    candidates = _candidates(mentions, "specializations")
    if not candidates:
        return False
    names = {
        " ".join(str(getattr(candidate, "canonical_name", "")).casefold().split())
        for candidate in candidates
    }
    names.discard("")
    return len(names) == 1


def classify(mentions: Any, message: str) -> Action | None:
    """Return a confident deterministic action, or ``None`` for the next layer."""

    high_categories = _candidates(mentions, "courses")
    high_specializations = _candidates(mentions, "specializations")
    high_universities = _candidates(mentions, "universities")
    groups = _all_high_groups(mentions)

    if _one_specialization_family(mentions) and (
        _PROVIDER_REQUEST.search(message)
        or (
            _OPTIONS_REQUEST.search(message)
            and high_categories
            and not high_universities
        )
    ):
        return Action.LIST_PROVIDERS

    if (
        _SPECIALIZATION_MARKER.search(message)
        and high_categories
        and not high_specializations
        and not _candidates(mentions, "specializations", confidence="MEDIUM")
    ):
        return Action.LIST_SPECIALIZATIONS

    if _COMPARE_MARKER.search(message) and (
        len(groups) >= 2
        or (groups and bool(getattr(mentions, "unresolved_terms", ())))
    ):
        return Action.COMPARE

    if (
        groups
        and not _COMPARE_MARKER.search(message)
        and not _RECOMMEND_MARKER.search(message)
    ):
        # Ambiguous HIGH families still remain deterministic here: focus_updater
        # and clarify() already know how to present every candidate without
        # selecting one. Provider-list markers above are the shape override.
        return Action.GET_FACTS

    return None


def mention_summary(mentions: Any) -> str:
    """Render catalog-owned mention names for the bounded Gemini decision prompt."""

    rendered: list[str] = []
    for label, field in (
        ("category", "courses"),
        ("university", "universities"),
        ("specialization", "specializations"),
    ):
        candidates = _candidates(mentions, field)
        confidence = "high"
        if not candidates:
            candidates = _candidates(mentions, field, confidence="MEDIUM")
            confidence = "medium"
        names: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            name = " ".join(str(getattr(candidate, "canonical_name", "")).strip().split())
            key = name.casefold()
            if name and key not in seen:
                seen.add(key)
                names.append(name)
            if len(names) == 6:
                break
        value = f"{confidence}({'|'.join(names)})" if names else "none"
        rendered.append(f"{label}={value}")
    return ", ".join(rendered)


__all__ = ["Action", "classify", "mention_summary"]
