from __future__ import annotations

from resolver.clarifier import clarify
from resolver.focus_updater import FocusUpdateResult
from session.state import ConversationState
from taxonomy.entity_matcher import Candidate


def _candidate(entity_id: str, slot: str, canonical: str) -> Candidate:
    return Candidate(
        entity_id=entity_id,
        confidence="HIGH",
        matched_span=canonical,
        layer=1,
        slot_type=slot,  # type: ignore[arg-type]
        canonical_name=canonical,
    )


def test_provider_rows_for_one_specialization_family_do_not_clarify() -> None:
    state = ConversationState(session_id="marketing-family")
    candidates = (
        _candidate("lpu:mba:marketing", "specialization", "Marketing"),
        _candidate("nmims:mba:marketing", "specialization", "Marketing"),
    )
    update = FocusUpdateResult(
        focus=state.focus,
        ambiguous={"specialization": candidates},
    )

    decision = clarify(state, update)

    assert decision.needs_clarification is False
    assert state.pending_clarification is None


def test_distinct_university_candidates_still_clarify() -> None:
    state = ConversationState(session_id="smu-family")
    candidates = (
        _candidate("university:sikkim-manipal", "university", "Sikkim Manipal University"),
        _candidate("university:manipal", "university", "Manipal University Jaipur"),
    )
    update = FocusUpdateResult(
        focus=state.focus,
        ambiguous={"university": candidates},
    )

    decision = clarify(state, update)

    assert decision.needs_clarification is True
    assert decision.slot_type == "university"
    assert len(decision.candidates) == 2
