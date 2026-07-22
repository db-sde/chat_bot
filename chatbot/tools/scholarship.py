"""Configured question-bank and reward-band scoring for scholarship checks."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .base import ToolResult, unavailable_result
from .content import ToolDefinition


def score_scholarship(
    answers: Mapping[str, str],
    definition: ToolDefinition,
    payload: Mapping[str, Any],
) -> ToolResult:
    """Count configured correct options and select exactly one configured reward band."""

    bank_key = str(payload.get("question_bank_key") or payload.get("program_id") or "").strip()
    steps = definition.question_bank.get(bank_key, ()) if bank_key else ()
    if not steps:
        steps = definition.question_bank.get("default", ()) or definition.steps
    if len(steps) != 7:
        return unavailable_result(
            "scholarship",
            "A complete seven-question scholarship bank is not configured for this program.",
        )
    uses_waiver_scoring = any(
        option.bonus > 0
        for step in steps
        for option in step.choices
    ) or any(band.min_waiver is not None for band in definition.reward_bands)
    correct_count = 0
    waiver = definition.base_waiver
    reasons: list[str] = []
    for step in steps:
        answer = answers.get(step.id)
        selected = next((option for option in step.choices if option.id == answer), None)
        if selected is None:
            return unavailable_result(
                "scholarship",
                f"A scored answer is not configured for scholarship question {step.id!r}.",
            )
        if uses_waiver_scoring:
            waiver += selected.bonus
            if selected.bonus and selected.reason_label:
                reasons.append(selected.reason_label)
        else:
            if selected.correct is None:
                return unavailable_result(
                    "scholarship",
                    f"A scored answer is not configured for scholarship question {step.id!r}.",
                )
            correct_count += int(selected.correct)
    if uses_waiver_scoring:
        if definition.max_waiver is not None:
            waiver = min(waiver, definition.max_waiver)
        matching = [
            band
            for band in definition.reward_bands
            if band.min_waiver is not None
            and band.max_waiver is not None
            and band.min_waiver <= waiver <= band.max_waiver
        ]
    else:
        matching = [
            band
            for band in definition.reward_bands
            if band.min_correct is not None
            and band.max_correct is not None
            and band.min_correct <= correct_count <= band.max_correct
        ]
    if len(matching) != 1:
        return unavailable_result(
            "scholarship",
            "The scholarship reward bands do not cover this score exactly once.",
        )
    band = matching[0]
    program_id = str(payload.get("program_id") or "").strip()
    if uses_waiver_scoring:
        net_fee = (
            max(0, definition.standard_fee - waiver)
            if definition.standard_fee is not None
            else None
        )
        full = {
            "message": f"You qualify for a configured fee waiver of ₹{waiver:,}.",
            "waiver_amount": waiver,
            "reward_band": band.label,
            "reasons": reasons,
            "claim_steps": list(definition.claim_steps),
        }
        if net_fee is not None:
            full["net_fee"] = net_fee
        partial = {
            "headline": definition.partial_reveal_template
            or "You've qualified for a fee waiver!"
        }
        lead_tags = {
            "tool": "scholarship",
            "waiver_amount": waiver,
            "reward_band": band.label,
        }
    else:
        full = {
            "message": f"Configured fee-waiver result: {band.label}.",
            "correct_count": correct_count,
            "reward_band": band.label,
        }
        partial = {"headline": "Your answers reached a configured fee-waiver band."}
        lead_tags = {
            "tool": "scholarship",
            "correct_count": correct_count,
            "reward_band": band.label,
        }
    return ToolResult(
        partial=partial,
        full=full,
        cta_program_ids=[program_id] if program_id else [],
        lead_tags=lead_tags,
    )


__all__ = ["score_scholarship"]
