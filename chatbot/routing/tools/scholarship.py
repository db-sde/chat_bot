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
    if not bank_key:
        return unavailable_result(
            "scholarship",
            "A scholarship question bank has not been mapped to this program.",
        )
    steps = definition.question_bank.get(bank_key, ())
    if len(steps) != 7:
        return unavailable_result(
            "scholarship",
            "A complete seven-question scholarship bank is not configured for this program.",
        )
    correct_count = 0
    for step in steps:
        answer = answers.get(step.id)
        selected = next((option for option in step.choices if option.id == answer), None)
        if selected is None or selected.correct is None:
            return unavailable_result(
                "scholarship",
                f"A scored answer is not configured for scholarship question {step.id!r}.",
            )
        correct_count += int(selected.correct)
    matching = [
        band
        for band in definition.reward_bands
        if band.min_correct <= correct_count <= band.max_correct
    ]
    if len(matching) != 1:
        return unavailable_result(
            "scholarship",
            "The scholarship reward bands do not cover this score exactly once.",
        )
    band = matching[0]
    program_id = str(payload.get("program_id") or "").strip()
    return ToolResult(
        partial={"headline": "Your answers reached a configured fee-waiver band."},
        full={
            "message": f"Configured fee-waiver result: {band.label}.",
            "correct_count": correct_count,
            "reward_band": band.label,
        },
        cta_program_ids=[program_id] if program_id else [],
        lead_tags={
            "tool": "scholarship",
            "correct_count": correct_count,
            "reward_band": band.label,
        },
    )


__all__ = ["score_scholarship"]
