"""Turn candidate arbitration results into one focused clarification."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from taxonomy.entity_matcher import Candidate
from taxonomy.index_builder import TaxonomyIndexes

from .focus_updater import FocusUpdateResult


@dataclass(frozen=True, slots=True)
class ClarificationDecision:
    needs_clarification: bool
    text: str | None = None
    slot_type: str | None = None
    candidates: tuple[str, ...] = ()
    labels: tuple[str, ...] = ()
    confidence: str | None = None
    focus: Any = None


def _metadata(indexes: TaxonomyIndexes | None, entity_id: str) -> Mapping[str, object]:
    return indexes.entity_metadata.get(entity_id, {}) if indexes else {}


def candidate_label(candidate: Candidate, indexes: TaxonomyIndexes | None = None) -> str:
    metadata = _metadata(indexes, candidate.entity_id)
    canonical = str(metadata.get("canonical_name") or candidate.canonical_name)
    university = metadata.get("university_name")
    if university and metadata.get("page_type") in {"course", "specialization"}:
        return f"{canonical} at {university}"
    return canonical


def _set_pending(
    state: object,
    candidates: tuple[Candidate, ...],
    slot_type: str,
) -> None:
    values = [candidate.entity_id for candidate in candidates]
    turn_count = getattr(state, "turn_count", 0)
    try:
        from session.state import PendingClarification

        pending: Any = PendingClarification(
            candidates=values,
            slot_type=slot_type
            if slot_type in {"university", "course", "specialization"}
            else "specialization",
            asked_at_turn=turn_count,
        )
    except (ImportError, TypeError, ValueError):
        pending = type(
            "PendingClarificationRecord",
            (),
            {"candidates": values, "slot_type": slot_type, "asked_at_turn": turn_count},
        )()
    state.pending_clarification = pending


def _resolved_context(update: FocusUpdateResult, indexes: TaxonomyIndexes | None) -> str:
    labels: list[str] = []
    for candidates in update.resolved.values():
        if len(candidates) == 1:
            labels.append(candidate_label(candidates[0], indexes))
    return " + ".join(dict.fromkeys(labels))


def clarify(
    state: object,
    update: FocusUpdateResult,
    *,
    indexes: TaxonomyIndexes | None = None,
) -> ClarificationDecision:
    """Persist one pending choice, never re-asking already confident slots."""

    if update.ambiguous:
        priority = ("university", "course", "specialization", "entity")
        slot_type = next(
            (slot for slot in priority if slot in update.ambiguous), next(iter(update.ambiguous))
        )
        candidates = tuple(update.ambiguous[slot_type])
        labels = tuple(candidate_label(candidate, indexes) for candidate in candidates)
        _set_pending(state, candidates, slot_type)
        options = "; ".join(f"{index}. {label}" for index, label in enumerate(labels, 1))
        return ClarificationDecision(
            needs_clarification=True,
            text=f"I found a few matches. Which one did you mean? {options}",
            slot_type=slot_type,
            candidates=tuple(candidate.entity_id for candidate in candidates),
            labels=labels,
            confidence="HIGH",
            focus=update.focus,
        )

    if update.medium:
        priority = ("university", "course", "specialization")
        slot_type = next(
            (slot for slot in priority if slot in update.medium), next(iter(update.medium))
        )
        candidates = tuple(update.medium[slot_type])
        # Keep tied fuzzy candidates, but ask only about this unresolved slot.
        labels = tuple(candidate_label(candidate, indexes) for candidate in candidates)
        _set_pending(state, candidates, slot_type)
        if len(labels) == 1:
            question = f"Did you mean {labels[0]}?"
        else:
            question = "Did you mean " + " or ".join(labels) + "?"
        context = _resolved_context(update, indexes)
        if context:
            question += f" I've already got {context} ready."
        return ClarificationDecision(
            needs_clarification=True,
            text=question,
            slot_type=slot_type,
            candidates=tuple(candidate.entity_id for candidate in candidates),
            labels=labels,
            confidence="MEDIUM",
            focus=update.focus,
        )

    state.pending_clarification = None
    return ClarificationDecision(needs_clarification=False, focus=update.focus)


build_clarification = clarify


class Clarifier:
    def __init__(self, indexes: TaxonomyIndexes | None = None) -> None:
        self.indexes = indexes

    def resolve(self, state: object, update: FocusUpdateResult) -> ClarificationDecision:
        return clarify(state, update, indexes=self.indexes)

    build = resolve


__all__ = [
    "ClarificationDecision",
    "Clarifier",
    "build_clarification",
    "candidate_label",
    "clarify",
]
