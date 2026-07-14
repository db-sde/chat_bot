"""Formatting primitives for the additive rich-response transport."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from response.cards import clean_text, first_value, has_value
from schemas import CardFact, ComparisonCard, ComparisonItem, ProgramCard, UniversityCard

_BULLET_RE = re.compile(r"^\s*[•*-]\s+")
_SPACE_RE = re.compile(r"\s+")
_LEADING_DURATION_RE = re.compile(r"^(A|An)\s+(\d+)\s+years\s+", re.IGNORECASE)
_PROGRAM_ACRONYM_RE = re.compile(
    r"\b(mba|bba|mca|bca|mcom|bcom|msc|bsc)\b",
    re.IGNORECASE,
)
_FACT_PREFIXES: tuple[tuple[str, str], ...] = (
    ("published total fee", "Fee"),
    ("published starting fee", "Starting fee"),
    ("published fee range", "Fee range"),
    ("published fee", "Fee"),
    ("duration", "Duration"),
    ("mode", "Mode"),
    ("eligibility", "Eligibility"),
    ("specializations", "Specializations"),
    ("placement support", "Placement support"),
    ("career options", "Career options"),
    ("approvals", "Approvals"),
    ("rankings", "Rankings"),
    ("naac", "NAAC"),
)


def optional_text(value: Any, *, max_chars: int | None = None) -> str | None:
    """Return clean publisher text or ``None`` for an absent value."""

    rendered = clean_text(value, max_chars=max_chars)
    return rendered or None


def catalog_strings(
    value: Any,
    *,
    fields: Sequence[str] = ("name", "title"),
    limit: int = 8,
) -> list[str]:
    """Render a publisher collection without depending on one feed shape."""

    if not has_value(value):
        return []
    items: Iterable[Any]
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes, Mapping)):
        items = value
    else:
        items = (value,)

    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        if isinstance(item, (str, int, float)):
            rendered = clean_text(item)
        else:
            rendered = clean_text(first_value(item, *fields, default=None))
        key = rendered.casefold()
        if not rendered or key in seen:
            continue
        seen.add(key)
        result.append(rendered)
        if len(result) >= limit:
            break
    return result


def card_fact(label: str, value: Any, *, max_chars: int = 300) -> CardFact | None:
    """Create one fact only when the catalog supplied a usable value."""

    rendered_label = clean_text(label)
    rendered_value = clean_text(value, max_chars=max_chars)
    if not rendered_label or not rendered_value:
        return None
    return CardFact(label=rendered_label, value=rendered_value)


def unique_facts(facts: Iterable[CardFact | None], *, limit: int = 8) -> list[CardFact]:
    result: list[CardFact] = []
    seen: set[tuple[str, str]] = set()
    for fact in facts:
        if fact is None:
            continue
        key = (fact.label.casefold(), fact.value.casefold())
        if key in seen:
            continue
        seen.add(key)
        result.append(fact)
        if len(result) >= limit:
            break
    return result


def _polish_catalog_copy(value: str) -> str:
    """Fix narrow display grammar without adding or changing catalog facts."""

    rendered = _LEADING_DURATION_RE.sub(
        lambda match: f"{match.group(1)} {match.group(2)}-year ",
        value,
    )
    return _PROGRAM_ACRONYM_RE.sub(lambda match: match.group(1).upper(), rendered)


def _sentence(value: Any, *, max_chars: int = 360) -> str:
    rendered = clean_text(value, max_chars=max_chars)
    if not rendered:
        return ""
    rendered = _polish_catalog_copy(rendered)
    return rendered if rendered.endswith((".", "!", "?")) else f"{rendered}."


def _joined_labels(values: Iterable[str], *, limit: int = 3) -> str:
    labels = [clean_text(value) for value in values if clean_text(value)][:limit]
    if len(labels) < 2:
        return labels[0] if labels else ""
    if len(labels) == 2:
        return f"{labels[0]} and {labels[1]}"
    return f"{', '.join(labels[:-1])}, and {labels[-1]}"


def _next_step(actions: Iterable[Any], fallback: str) -> str:
    action = next((clean_text(value) for value in actions if clean_text(value)), "")
    if not action:
        return fallback

    action = action.rstrip(" .?!")
    lowered = action.casefold()
    if lowered.startswith("compare "):
        return f"Would you like me to compare {action[8:]}?"
    for suffix, prompt in (
        (" fees", "review the published fees for"),
        (" eligibility", "check the published eligibility for"),
        (" specializations", "explore the published specializations for"),
    ):
        if lowered.endswith(suffix) and (subject := action[: -len(suffix)].strip()):
            return f"Would you like to {prompt} {subject}?"
    if lowered.startswith(("talk to ", "speak to ", "book callback")):
        return "Would you like me to connect you with a counsellor?"
    return "You can use the follow-up options below to keep exploring."


def _university_advisor_message(
    card: UniversityCard,
    next_actions: Iterable[Any],
) -> str:
    paragraphs: list[str] = []
    if card.summary:
        paragraphs.append(_sentence(card.summary))
    else:
        paragraphs.append(f"I found {card.name} in the current published catalog.")

    why_choose = next(
        (fact.value for fact in card.highlights if fact.label.casefold().startswith("why ")),
        "",
    )
    if why_choose and (
        not card.summary or clean_text(why_choose).casefold() not in card.summary.casefold()
    ):
        paragraphs.append(_sentence(why_choose, max_chars=300))
    elif card.programs:
        programs = _joined_labels(card.programs)
        paragraphs.append(f"Its published program list includes {programs}.")

    fallback = (
        f"Would you like to explore {card.programs[0]} in more detail?"
        if card.programs
        else (
            f"Would you like to explore its published {card.highlights[0].label.casefold()}?"
            if card.highlights
            else "Would you like to compare it with another university in the catalog?"
        )
    )
    paragraphs.append(_next_step(next_actions, fallback))
    return "\n\n".join(value for value in paragraphs if value)


def _program_advisor_message(
    card: ProgramCard,
    next_actions: Iterable[Any],
) -> str:
    paragraphs: list[str] = []
    if card.summary:
        paragraphs.append(_sentence(card.summary))

    if card.kind == "specialization":
        context: list[str] = []
        if card.category:
            context.append(card.category.upper() if len(card.category) <= 6 else card.category)
        context.append("specialization")
        if card.university_name:
            context.append(f"at {card.university_name}")
        paragraphs.append(f"{card.name} is a published {' '.join(context)}.")
    elif card.university_name:
        paragraphs.append(
            f"This is a published {card.name} offering from {card.university_name}."
        )
    elif not card.summary:
        paragraphs.append(f"I found {card.name} in the current published catalog.")

    if card.career_outcomes:
        careers = _joined_labels(card.career_outcomes)
        paragraphs.append(f"Published career paths include {careers}.")

    if card.specializations:
        fallback = f"Would you like to explore {card.specializations[0]} next?"
    elif card.career_outcomes:
        fallback = "Would you like to compare this with another catalog program?"
    elif card.eligibility:
        fallback = "Would you like to look more closely at its published eligibility?"
    elif card.fee:
        fallback = "Would you like to compare its published fee with another program?"
    elif card.highlights:
        fallback = (
            f"Would you like to explore its published {card.highlights[0].label.casefold()}?"
        )
    else:
        fallback = "Would you like to compare it with another program in the catalog?"
    paragraphs.append(_next_step(next_actions, fallback))
    return "\n\n".join(value for value in paragraphs if value)


def _comparison_advisor_message(
    card: ComparisonCard,
    next_actions: Iterable[Any],
) -> str:
    labels = [
        f"{item.subtitle} {item.name}" if item.subtitle else item.name for item in card.items
    ]
    operands = _joined_labels(labels)
    paragraphs = [
        f"I've placed {operands} side by side using their published catalog details."
    ]

    common_labels: set[str] | None = None
    display_labels: dict[str, str] = {}
    for item in card.items:
        labels_for_item = {fact.label.casefold() for fact in item.facts}
        common_labels = (
            labels_for_item
            if common_labels is None
            else common_labels.intersection(labels_for_item)
        )
        display_labels.update({fact.label.casefold(): fact.label for fact in item.facts})
    if common_labels:
        compared = _joined_labels(display_labels[label] for label in sorted(common_labels))
        paragraphs.append(f"The comparison card covers {compared} where they are published.")

    paragraphs.append(
        _next_step(
            next_actions,
            "Tell me which factor matters most, and I can help you narrow the choice.",
        )
    )
    return "\n\n".join(paragraphs)


def advisor_message(
    text: Any,
    *,
    card: UniversityCard | ProgramCard | ComparisonCard | None = None,
    next_actions: Iterable[Any] = (),
) -> str:
    """Create concise advisor copy, leaving raw facts to the component card."""

    if isinstance(card, UniversityCard):
        return _university_advisor_message(card, next_actions)
    if isinstance(card, ProgramCard):
        return _program_advisor_message(card, next_actions)
    if isinstance(card, ComparisonCard):
        return _comparison_advisor_message(card, next_actions)
    legacy = str(text or "").strip()
    return legacy or "What would you like to explore about online universities or programs?"


def _parsed_fact(value: str) -> CardFact | None:
    cleaned = clean_text(value).rstrip(".")
    lowered = cleaned.casefold()
    for prefix, label in _FACT_PREFIXES:
        if lowered == prefix:
            return card_fact("Published detail", cleaned)
        if lowered.startswith(f"{prefix} "):
            return card_fact(label, cleaned[len(prefix) :].strip(" :-"))
    return card_fact("Published detail", cleaned)


def comparison_items_from_text(text: str, *, limit: int = 3) -> list[ComparisonItem]:
    """Parse deterministic comparison bullets when structured operands are absent.

    This intentionally accepts only explicit bullet rows containing a label and
    colon. It does not infer entities or attempt fuzzy matching.
    """

    result: list[ComparisonItem] = []
    seen: set[str] = set()
    for line in str(text or "").splitlines():
        if not _BULLET_RE.match(line):
            continue
        row = _BULLET_RE.sub("", line, count=1).strip()
        if ":" not in row:
            continue
        operand, detail_text = row.split(":", 1)
        operand = _SPACE_RE.sub(" ", operand).strip(" .")
        if not operand or not detail_text.strip():
            continue

        first_label, separator, second_label = operand.partition(" — ")
        name = clean_text(second_label if separator else first_label)
        subtitle = clean_text(first_label) if separator else ""
        key = f"{name}\0{subtitle}".casefold()
        if not name or key in seen:
            continue

        facts = unique_facts(
            _parsed_fact(part) for part in detail_text.split(";") if part.strip()
        )
        if not facts:
            continue
        seen.add(key)
        result.append(
            ComparisonItem(
                name=name,
                subtitle=subtitle or None,
                facts=facts,
            )
        )
        if len(result) >= limit:
            break
    return result


__all__ = [
    "advisor_message",
    "card_fact",
    "catalog_strings",
    "comparison_items_from_text",
    "optional_text",
    "unique_facts",
]
