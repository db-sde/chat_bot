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
    OPEN_LEAD_FORM = "open_lead_form"
    TOOL_ENTRY = "tool_entry"
    UNSUPPORTED_ENTITY = "unsupported_entity"
    CHITCHAT = "chitchat"
    UNRELATED = "unrelated"
    FALLBACK = "fallback"


_SPECIALIZATION_MARKER = re.compile(r"\bspeciali[sz]ations?\b", re.IGNORECASE)
_PROVIDER_REQUEST = re.compile(
    r"\b(?:which\s+universit(?:y|ies)\s+(?:offers?|provides?)|who\s+offers?|"
    r"universit(?:y|ies)\s+(?:with|offering|that\s+offers?))\b",
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
    r"\b(?:(?:the\s+)?best\b[^?]{0,80}\bfor\s+me|cheapest|lowest[-\s]+cost|top|"
    r"(?:under|below|within|up\s*to|upto)\s*"
    r"(?:a\s+budget\s+of\s*)?(?:₹\s*|rs\.?\s*|inr\s*)?\d|"
    r"recommend|suggest|help\s+me\s+choose|"
    r"career\s+(?:guidance|growth)|working\s+professional\s+(?:advice|guidance)|"
    r"which\b[^?]{0,80}\b(?:should\s+i|(?:is|are)\s+(?:the\s+)?best|has\s+the\s+best)|"
    r"which\s+university\b[^?]{0,80}\b(?:highest|reasonable\s+fees?))\b",
    re.IGNORECASE,
)
_TOOL_TOKEN = re.compile(
    r"^\s*tool:(roi|career_quiz|scholarship)\s*$",
    re.IGNORECASE,
)
_TOOL_ALIASES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "roi",
        re.compile(
            r"^\s*(?:calculate|check|show)?\s*(?:my\s+)?(?:program\s+)?roi(?:\s+calculator)?\s*[.!]?\s*$",
            re.I,
        ),
    ),
    (
        "career_quiz",
        re.compile(
            r"^\s*(?:start|take|open)?\s*(?:the\s+)?career(?:[-\s]+path)?\s+quiz\s*[.!]?\s*$", re.I
        ),
    ),
    (
        "scholarship",
        re.compile(
            r"^\s*(?:check|start|open)?\s*(?:my\s+)?scholarship(?:\s+(?:checker|eligibility))?\s*[.!]?\s*$",
            re.I,
        ),
    ),
)


def tool_id_from_message(message: str) -> str | None:
    """Return a bounded tool id for fixed widget tokens or unambiguous aliases."""

    token = _TOOL_TOKEN.fullmatch(message)
    if token:
        return token.group(1).casefold()
    for tool_id, pattern in _TOOL_ALIASES:
        if pattern.fullmatch(message):
            return tool_id
    return None


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


def _one_specialization_span(mentions: Any) -> bool:
    """Whether the user supplied one specialization concept span.

    A catalog can publish that span on many provider records and, occasionally,
    on closely related canonical labels. Those records are discovery results,
    not separate operands the user must disambiguate. Separate spans (for
    example ``Marketing and Finance``) remain separate semantic groups.
    """

    candidates = _candidates(mentions, "specializations")
    if not candidates:
        return False
    return len(_semantic_groups(candidates, "specialization")) == 1


def _unknown_entities(mentions: Any) -> tuple[Any, ...]:
    """Return explicit unknown-entity evidence across extractor versions."""

    unknown = getattr(mentions, "unknown_entities", ()) or ()
    unresolved = getattr(mentions, "unresolved_terms", ()) or ()
    return tuple(unknown) + tuple(unresolved)


def has_deferred_clarification(mentions: Any) -> bool:
    """Whether MEDIUM evidence needs the post-resolution clarifier.

    This is deliberately a hint rather than ``Action.CLARIFY``. Clarification
    needs the resolver's candidates and focus update; dispatching it before
    resolution would create a content-free response.
    """

    for field in ("universities", "courses", "specializations"):
        if _candidates(mentions, field, confidence="MEDIUM") and not _candidates(mentions, field):
            return True
    return False


def classify(mentions: Any, message: str) -> Action | None:
    """Return a confident deterministic action, or ``None`` for the next layer."""

    if tool_id_from_message(message) is not None:
        return Action.TOOL_ENTRY

    high_categories = _candidates(mentions, "courses")
    high_specializations = _candidates(mentions, "specializations")
    high_universities = _candidates(mentions, "universities")
    groups = _all_high_groups(mentions)

    # Any named catalog gap routes through the honest unsupported handler while
    # retaining compatible known concepts (for example an unknown university +
    # a known course). Mixed comparisons remain on their established partial-
    # comparison path so the known operand can still be summarized.
    if (
        _unknown_entities(mentions)
        and not has_deferred_clarification(mentions)
        and not (_COMPARE_MARKER.search(message) and groups)
    ):
        return Action.UNSUPPORTED_ENTITY

    if high_specializations and (
        _PROVIDER_REQUEST.search(message)
        or (_OPTIONS_REQUEST.search(message) and high_categories and not high_universities)
    ):
        return Action.LIST_PROVIDERS

    # A specialization is a concept until a university is supplied. Multiple
    # provider rows in the index should therefore become provider discovery,
    # not a choice between duplicate specialization labels.
    if (
        _one_specialization_span(mentions)
        and not high_universities
        and not _COMPARE_MARKER.search(message)
        and not _RECOMMEND_MARKER.search(message)
    ):
        return Action.LIST_PROVIDERS

    if (
        _SPECIALIZATION_MARKER.search(message)
        and high_categories
        and not high_specializations
        and not _candidates(mentions, "specializations", confidence="MEDIUM")
        and not _RECOMMEND_MARKER.search(message)
    ):
        return Action.LIST_SPECIALIZATIONS

    if _COMPARE_MARKER.search(message) and (
        len(groups) >= 2 or (groups and bool(getattr(mentions, "unresolved_terms", ())))
    ):
        return Action.COMPARE

    # Ranking, budget, and personal-fit language changes the requested outcome,
    # even when the catalog subject itself is already resolved. This must run
    # before the generic catalog-facts branch so phrases such as "Cheapest MBA"
    # do not collapse into the ordinary category overview. Catalog evidence is
    # required here; open-ended no-evidence reasoning remains behind the Gemini
    # gate in ``nlu.intent``.
    if groups and _RECOMMEND_MARKER.search(message):
        return Action.RECOMMEND

    if groups and not _COMPARE_MARKER.search(message) and not _RECOMMEND_MARKER.search(message):
        # Ambiguous HIGH families still remain deterministic here: focus_updater
        # and clarify() already know how to present every candidate without
        # selecting one. Provider-list markers above are the shape override.
        return Action.GET_FACTS

    # MEDIUM evidence is intentionally left for the resolver/clarifier. Callers
    # can inspect ``has_deferred_clarification`` without short-circuiting it.
    if has_deferred_clarification(mentions):
        return None

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


__all__ = [
    "Action",
    "classify",
    "has_deferred_clarification",
    "mention_summary",
    "tool_id_from_message",
]
