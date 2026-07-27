"""Aptitude scoring and fee-model waiver calculation for the scholarship check.

Server-side scoring only: the client never sees `correct`, and options are
shuffled at serve time, so a repeat visitor cannot pattern-match a position.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from data.accessor import safe_get

from .base import ToolResult, unavailable_result
from .content import ToolDefinition

# Waiver figures are real money, so they are rounded to clean, honourable
# amounts a counsellor can actually apply.
_ROUNDING = 500


def _round_waiver(amount: float) -> int:
    return int(round(amount / _ROUNDING) * _ROUNDING)


def score_scholarship(
    answers: Mapping[str, str],
    definition: ToolDefinition,
    payload: Mapping[str, Any],
    catalog: Any = None,
) -> ToolResult:
    """Count correct aptitude answers and award a band percentage of the pool."""

    setup = definition.setup
    if setup is None:
        return unavailable_result("scholarship", "The scholarship fee model is not configured.")

    # Q1 — fee model sets the waiver ceiling.
    fee_model = next(
        (option for option in setup.choices if option.id == answers.get(setup.id)),
        None,
    )
    if fee_model is None or fee_model.pool is None:
        return unavailable_result("scholarship", "A fee plan has not been selected.")

    # Q2–Q7 — aptitude, scored against the bank's stored option ids.
    served_ids = payload.get("served_question_ids")
    if not isinstance(served_ids, (list, tuple)) or not served_ids:
        return unavailable_result("scholarship", "No scholarship questions were served.")
    bank = {
        step.id: step
        for steps in definition.question_bank.values()
        for step in steps
    }
    correct_count = 0
    for question_id in served_ids:
        question = bank.get(str(question_id))
        if question is None or question.correct is None:
            return unavailable_result(
                "scholarship",
                f"Scholarship question {question_id!r} has no configured answer key.",
            )
        # A missing answer scores zero rather than failing: the user still
        # completed the flow and the floor band guarantees they win something.
        if answers.get(question.id) == question.correct:
            correct_count += 1

    band = next(
        (
            candidate
            for candidate in definition.reward_bands
            if candidate.min_correct is not None
            and candidate.max_correct is not None
            and candidate.min_correct <= correct_count <= candidate.max_correct
        ),
        None,
    )
    if band is None or band.pct is None:
        return unavailable_result(
            "scholarship",
            "The scholarship reward bands do not cover this score.",
        )

    waiver = _round_waiver(fee_model.pool * band.pct)
    program_id = str(payload.get("program_id") or "").strip()
    # The waiver is real money, so show what the user actually pays when the
    # catalog publishes a fee for the program in context.
    standard_fee = definition.standard_fee
    if catalog is not None and program_id:
        entity = None
        getter = getattr(catalog, "get_entity", None)
        if callable(getter):
            entity = getter(program_id)
        elif isinstance(catalog, Mapping):
            entity = catalog.get(program_id)
        if entity is not None:
            published = safe_get(entity, "fee_numeric", None)
            if isinstance(published, (int, float)) and not isinstance(published, bool):
                standard_fee = int(published)
    net_fee = max(0, standard_fee - waiver) if standard_fee is not None else None
    return ToolResult(
        partial={
            "headline": definition.partial_reveal_template
            or "You've qualified for a fee waiver!"
        },
        full={
            "message": (
                f"You've qualified for a ₹{waiver:,} fee waiver, "
                f"valid on the {fee_model.label.lower()} plan."
            ),
            "waiver_amount": waiver,
            "fee_model": fee_model.label,
            "fee_model_id": fee_model.id,
            "pool": fee_model.pool,
            "correct_count": correct_count,
            "questions_served": len(served_ids),
            "reward_band": band.label,
            **({"standard_fee": standard_fee} if standard_fee is not None else {}),
            **({"net_fee": net_fee} if net_fee is not None else {}),
            "claim_steps": list(definition.claim_steps),
            "counsellor_note": (
                "Our counsellor will confirm and apply this to your admission."
            ),
        },
        cta_program_ids=[program_id] if program_id else [],
        # The counsellor must see exactly what was promised — a waiver the CRM
        # does not know about is worse than no tool at all.
        lead_tags={
            "tool": "scholarship",
            "waiver_amount": waiver,
            "fee_model": fee_model.label,
            "fee_model_id": fee_model.id,
            "correct_count": correct_count,
            "reward_band": band.label,
        },
    )


__all__ = ["score_scholarship"]
