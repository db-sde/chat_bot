"""Resolve answers to an outstanding clarification before ordinary NLU."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from taxonomy.alias_tables import normalize_text
from taxonomy.index_builder import TaxonomyIndexes, normalize_category

ORDINALS = {
    "first": 0,
    "1": 0,
    "1st": 0,
    "second": 1,
    "2": 1,
    "2nd": 1,
    "third": 2,
    "3": 2,
    "3rd": 2,
    "fourth": 3,
    "4": 3,
    "4th": 3,
    "fifth": 4,
    "5": 4,
    "5th": 4,
    "sixth": 5,
    "6": 5,
    "6th": 5,
}
AFFIRMATIVE = frozenset({"yes", "y", "yep", "yeah", "correct", "right", "that one"})
POLITE_FILLERS = frozenset({"please", "pls", "thanks", "thank", "you", "it", "is"})
REJECTION_RE = re.compile(
    r"\b(?:no|none\s+of\s+these|neither|nope|not\s+these|something\s+else|different\s+one)\b",
    re.IGNORECASE,
)
TOPIC_RE = re.compile(
    r"\b(?:tell|what|which|compare|about|fees?|duration|eligibility|emi|placements?|"
    r"admission|accreditation|program|course|university|mba|mca|callback|call me)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class PendingClarificationResult:
    handled: bool
    resolved: bool = False
    new_topic: bool = False
    entity_id: str | None = None
    slot_type: str | None = None
    label: str | None = None


def _metadata(indexes: TaxonomyIndexes | None, entity_id: str) -> Mapping[str, object]:
    return indexes.entity_metadata.get(entity_id, {}) if indexes else {}


def _label(indexes: TaxonomyIndexes | None, entity_id: str) -> str:
    metadata = _metadata(indexes, entity_id)
    canonical = str(metadata.get("canonical_name") or entity_id)
    university = metadata.get("university_name")
    if university and metadata.get("page_type") in {"course", "specialization"}:
        return f"{canonical} at {university}"
    return canonical


def _choice_from_input(
    raw_input: str,
    candidates: list[str],
    slot_type: str | None,
    indexes: TaxonomyIndexes | None,
) -> str | None:
    query = normalize_text(raw_input)
    if len(candidates) == 1:
        query_tokens = set(query.split())
        if query in AFFIRMATIVE or (
            bool(query_tokens & AFFIRMATIVE) and query_tokens <= AFFIRMATIVE | POLITE_FILLERS
        ):
            return candidates[0]
    for token in query.split():
        if token in ORDINALS and ORDINALS[token] < len(candidates):
            return candidates[ORDINALS[token]]
    label_matches: list[str] = []
    for entity_id in candidates:
        labels = {
            _label(indexes, entity_id),
            str(_metadata(indexes, entity_id).get("canonical_name") or ""),
        }
        if query in {normalize_text(label) for label in labels if label}:
            label_matches.append(entity_id)
    if len(label_matches) == 1:
        return label_matches[0]
    if indexes and slot_type:
        for lookup in (indexes.alias_index, indexes.acronym_index, indexes.canonical_name_index):
            matches = lookup.get(slot_type, {}).get(query) or lookup.get(slot_type, {}).get(
                query.replace(" ", "")
            )
            offered = set(matches or ()) & set(candidates)
            if len(offered) == 1:
                return next(iter(offered))
        # Provider-level course/specialization choices are often answered with
        # only the university alias ("lpu", "nmims"). Resolve that alias to a
        # university id/name, then select only if exactly one offered record uses it.
        university_ids: set[str] = set()
        for lookup in (
            indexes.alias_index,
            indexes.acronym_index,
            indexes.canonical_name_index,
        ):
            university_ids.update(
                lookup.get("university", {}).get(query)
                or lookup.get("university", {}).get(query.replace(" ", ""))
                or ()
            )
        provider_matches: list[str] = []
        for entity_id in candidates:
            metadata = _metadata(indexes, entity_id)
            linked_id = str(metadata.get("university_id") or "")
            university_name = normalize_text(metadata.get("university_name"))
            candidate_provider_ids = {linked_id} if linked_id else set()
            if university_name:
                for lookup in (
                    indexes.alias_index,
                    indexes.acronym_index,
                    indexes.canonical_name_index,
                ):
                    candidate_provider_ids.update(
                        lookup.get("university", {}).get(university_name)
                        or lookup.get("university", {}).get(university_name.replace(" ", ""))
                        or ()
                    )
            if university_ids.intersection(candidate_provider_ids) or (
                university_name and university_name == query
            ):
                provider_matches.append(entity_id)
        if len(provider_matches) == 1:
            return provider_matches[0]
    return None


def _apply_choice(state: object, entity_id: str, indexes: TaxonomyIndexes | None) -> None:
    focus = getattr(state, "focus", state)
    metadata = _metadata(indexes, entity_id)
    page_type = str(metadata.get("page_type") or "")
    if page_type == "category" or entity_id.startswith("category:"):
        category = metadata.get("category") or entity_id.partition(":")[2].replace("-", " ")
        focus.category = normalize_category(category)
        focus.entity_id = None
        _join_existing_focus(focus, indexes)
        return
    if page_type == "university":
        focus.university = entity_id
        focus.entity_id = None if focus.category or focus.specialization else entity_id
        _join_existing_focus(focus, indexes)
        return
        return
    if metadata.get("university_id") or metadata.get("university_name"):
        focus.university = str(metadata.get("university_id") or metadata.get("university_name"))
    if metadata.get("category"):
        focus.category = normalize_category(metadata["category"])
    if page_type == "specialization":
        focus.specialization = str(
            metadata.get("specialization_name") or metadata.get("canonical_name") or entity_id
        )
    focus.entity_id = entity_id


def _join_existing_focus(focus: object, indexes: TaxonomyIndexes | None) -> None:
    if indexes is None or not getattr(focus, "category", None):
        return
    reverse = indexes.category_index
    pool = set(reverse.entities_for_category(str(focus.category)))
    university = getattr(focus, "university", None)
    if university:
        university_pool = set(reverse.entities_for_university(str(university)))
        metadata = _metadata(indexes, str(university))
        for key in (metadata.get("university_name"), metadata.get("canonical_name")):
            if key:
                university_pool.update(reverse.entities_for_university(str(key)))
        pool &= university_pool
    specialization = getattr(focus, "specialization", None)
    desired_type = "specialization" if specialization else "course"
    if specialization:
        pool &= set(reverse.entities_for_specialization(str(specialization)))
    pool = {
        candidate_id
        for candidate_id in pool
        if _metadata(indexes, candidate_id).get("page_type") == desired_type
    }
    focus.entity_id = next(iter(pool)) if len(pool) == 1 else None


def resolve_pending_clarification(
    raw_input: str,
    state: object,
    *,
    indexes: TaxonomyIndexes | None = None,
    catalog: object | None = None,
) -> PendingClarificationResult:
    del catalog
    pending = getattr(state, "pending_clarification", None)
    if pending is None:
        return PendingClarificationResult(handled=False)
    if REJECTION_RE.search(raw_input):
        state.pending_clarification = None
        return PendingClarificationResult(handled=False, new_topic=True)
    candidates = list(getattr(pending, "candidates", ()) or ())
    slot_type = getattr(pending, "slot_type", None)
    choice = _choice_from_input(raw_input, candidates, slot_type, indexes)
    if choice:
        _apply_choice(state, choice, indexes)
        state.pending_clarification = None
        return PendingClarificationResult(
            handled=True,
            resolved=True,
            entity_id=choice,
            slot_type=slot_type,
            label=_label(indexes, choice),
        )

    query = normalize_text(raw_input)
    known_outside_offer = False
    if indexes:
        for lookup in (indexes.alias_index, indexes.acronym_index, indexes.canonical_name_index):
            for values in lookup.values():
                matches = values.get(query) or values.get(query.replace(" ", ""))
                if matches and not (set(matches) & set(candidates)):
                    known_outside_offer = True
                    break
            if known_outside_offer:
                break
    new_topic = known_outside_offer or bool(TOPIC_RE.search(raw_input))
    if new_topic:
        state.pending_clarification = None
    return PendingClarificationResult(handled=False, new_topic=new_topic, slot_type=slot_type)


check_pending_clarification = resolve_pending_clarification


class PendingClarificationResolver:
    def __init__(
        self, indexes: TaxonomyIndexes | None = None, catalog: object | None = None
    ) -> None:
        self.indexes = indexes
        self.catalog = catalog

    def resolve(self, raw_input: str, state: object) -> PendingClarificationResult:
        return resolve_pending_clarification(
            raw_input, state, indexes=self.indexes, catalog=self.catalog
        )


__all__ = [
    "PendingClarificationResolver",
    "PendingClarificationResult",
    "check_pending_clarification",
    "resolve_pending_clarification",
]
