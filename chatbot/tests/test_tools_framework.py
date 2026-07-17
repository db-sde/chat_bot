from __future__ import annotations

import json
from pathlib import Path

from routing.tools import (
    EscapeSignals,
    ToolDefinition,
    ToolEngine,
    ToolsContentStore,
    score_career_quiz,
    score_roi,
    score_scholarship,
)
from session.state import ConversationState


def _choice_steps(count: int = 5) -> list[dict[str, object]]:
    return [
        {
            "id": f"q{index}",
            "prompt": f"Question {index}",
            "type": "choice",
            "options": [
                {
                    "id": "a",
                    "label": "Business",
                    "weights": {"management": 2},
                },
                {
                    "id": "b",
                    "label": "Technology",
                    "weights": {"technology": 2},
                },
            ],
        }
        for index in range(1, count + 1)
    ]


def _content_document(*, version: str = "v1") -> dict[str, object]:
    return {
        "version": version,
        "tools": {
            "career_quiz": {
                "enabled": True,
                "entry_copy": "Answer the configured questions.",
                "steps": _choice_steps(),
                "question_bank": {},
                "reward_bands": [],
            },
            "roi": {
                "enabled": True,
                "entry_copy": "Use normalized catalog data.",
                "steps": [
                    {
                        "id": "program",
                        "prompt": "Choose a program.",
                        "type": "entity",
                        "options": [],
                    },
                    {
                        "id": "current_salary",
                        "prompt": "Choose current annual salary.",
                        "type": "bucket",
                        "value_period": "annual",
                        "buckets": [{"id": "b1", "label": "INR 6L", "value": 600000}],
                    },
                ],
                "question_bank": {},
                "reward_bands": [],
            },
            "scholarship": {
                "enabled": False,
                "entry_copy": "",
                "unavailable_reason": "Question bank pending.",
                "steps": [],
                "question_bank": {},
                "reward_bands": [],
            },
        },
    }


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def test_tools_content_hot_reload_retains_last_good_snapshot(tmp_path: Path) -> None:
    path = tmp_path / "tools.json"
    _write_json(path, _content_document(version="good"))
    store = ToolsContentStore(path, auto_reload=False)

    invalid = _content_document(version="bad")
    invalid["unexpected"] = True
    _write_json(path, invalid)

    assert store.refresh() is False
    assert store.version == "good"
    assert store.get("career_quiz", version="good") is not None
    assert store.last_error is not None


def test_tools_content_requires_a_new_version_for_changed_content(tmp_path: Path) -> None:
    path = tmp_path / "tools.json"
    original = _content_document(version="pinned-v1")
    _write_json(path, original)
    store = ToolsContentStore(path, auto_reload=False)

    changed = _content_document(version="pinned-v1")
    changed["tools"]["career_quiz"]["entry_copy"] = "Changed without a version bump."
    _write_json(path, changed)

    assert store.refresh() is False
    retained = store.get("career_quiz", version="pinned-v1")
    assert retained is not None
    assert retained.entry_copy == "Answer the configured questions."


def test_spec_shaped_tool_content_is_enabled_unless_explicitly_disabled(
    tmp_path: Path,
) -> None:
    path = tmp_path / "tools.json"
    document = _content_document(version="spec-shaped-v1")
    document["tools"]["career_quiz"].pop("enabled")
    _write_json(path, document)

    definition = ToolsContentStore(path, auto_reload=False).get("career_quiz")

    assert definition is not None
    assert definition.enabled is True


def test_disabled_tool_exits_honestly_with_conversion_actions(tmp_path: Path) -> None:
    path = tmp_path / "tools.json"
    document = _content_document(version="disabled-v3")
    document["tools"]["roi"]["enabled"] = False
    document["tools"]["roi"]["unavailable_reason"] = "ROI content is pending."
    _write_json(path, document)
    state = ConversationState(session_id="unavailable")
    turn = ToolEngine(ToolsContentStore(path, auto_reload=False)).enter(state, "roi")

    assert turn.result is not None and turn.result.status == "content_unavailable"
    assert turn.content_version == "disabled-v3"
    assert turn.answered_step is None
    assert turn.response.metadata["tool_flow"]["version"] == "disabled-v3"
    assert state.active_flow is None
    assert [action.message for action in turn.response.quick_actions] == [
        "Call me",
        "Browse programs",
    ]


def test_career_flow_runs_questions_partial_lead_reveal_and_exit(tmp_path: Path) -> None:
    path = tmp_path / "tools.json"
    _write_json(path, _content_document())
    engine = ToolEngine(
        ToolsContentStore(path, auto_reload=False),
        program_lookup=lambda discipline: [f"course-{discipline}-{index}" for index in range(3)],
    )
    state = ConversationState(session_id="career")

    turn = engine.enter(state, "career_quiz")
    assert turn.content_version == "v1"
    assert turn.answered_step is None
    assert state.active_flow is not None and state.active_flow.step == "q1"
    for index in range(1, 6):
        answer_token = turn.response.quick_actions[0].message
        assert answer_token.startswith(f"tool:answer:q{index}:")
        turn = engine.dispatch(state, answer_token)
        assert turn is not None
        assert turn.content_version == "v1"
        assert turn.answered_step == f"q{index}"

    assert turn.lifecycle == "partial_reveal"
    assert state.active_flow is not None and state.active_flow.step == "partial_reveal"
    before_partial_view = state.model_dump(mode="json")
    partial_view = engine.current(state)
    assert partial_view is not None and partial_view.lifecycle == "partial_reveal"
    assert partial_view.result == turn.result
    assert partial_view.answered_step is None
    assert state.model_dump(mode="json") == before_partial_view
    turn = engine.dispatch(state, "tool:continue")
    assert turn is not None and turn.needs_lead
    assert state.active_flow is not None and state.active_flow.step == "await_lead"
    before_lead_view = state.model_dump(mode="json")
    lead_view = engine.resume_view(state)
    assert lead_view is not None and lead_view.lifecycle == "await_lead"
    assert lead_view.needs_lead
    assert state.model_dump(mode="json") == before_lead_view

    turn = engine.resume_after_lead(state)
    assert turn is not None and turn.completed and turn.lifecycle == "reveal"
    assert turn.result is not None
    assert turn.result.full["top_discipline"] == "management"
    assert state.active_flow is None
    assert [action.message for action in turn.response.quick_actions] == [
        "Apply now",
        "Call me",
        "Compare programs",
    ]


def test_current_view_is_read_only_and_uses_the_flow_pinned_snapshot(tmp_path: Path) -> None:
    path = tmp_path / "tools.json"
    _write_json(path, _content_document(version="pinned-v1"))
    store = ToolsContentStore(path, auto_reload=False)
    engine = ToolEngine(store)
    state = ConversationState(session_id="resume")

    first = engine.enter(state, "career_quiz")
    second = engine.dispatch(state, first.response.quick_actions[0].message)
    assert second is not None and state.active_flow is not None
    assert state.active_flow.step == "q2"

    _write_json(path, _content_document(version="current-v2"))
    assert store.refresh() is True
    before = state.model_dump(mode="json")

    current = engine.current(state)
    resumed = engine.resume_view(state)

    assert current is not None and resumed is not None
    assert current.lifecycle == resumed.lifecycle == "question"
    assert current.content_version == resumed.content_version == "pinned-v1"
    assert current.answered_step is None
    assert current.response.metadata["tool_flow"]["step"] == "q2"
    assert current.response.metadata["tool_flow"]["version"] == "pinned-v1"
    assert "Please choose" not in current.response.text
    assert state.model_dump(mode="json") == before


def test_invalid_tool_answer_escapes_for_strong_new_intent(tmp_path: Path) -> None:
    path = tmp_path / "tools.json"
    _write_json(path, _content_document())
    engine = ToolEngine(ToolsContentStore(path, auto_reload=False))
    state = ConversationState(session_id="escape")
    engine.enter(state, "career_quiz")

    turn = engine.dispatch(
        state,
        "Tell me about NMIMS",
        escape=EscapeSignals(high_confidence_catalog_mention=True),
    )

    assert turn is not None and turn.escaped and not turn.consumed
    assert state.active_flow is None


def test_entering_another_tool_replaces_the_active_flow(tmp_path: Path) -> None:
    path = tmp_path / "tools.json"
    _write_json(path, _content_document())
    engine = ToolEngine(ToolsContentStore(path, auto_reload=False))
    state = ConversationState(session_id="replace")
    engine.enter(state, "career_quiz")

    turn = engine.enter(state, "roi")

    assert turn.replaced_tool == "career_quiz"
    assert state.active_flow is not None and state.active_flow.tool == "roi"
    assert state.active_flow.step == "program"


def test_roi_uses_salary_delta_and_ceil_not_gross_salary() -> None:
    catalog = {
        "p1": {
            "id": "p1",
            "discipline": "management",
            "fee_numeric": 120000,
            "salary_numeric": 840000,
        },
        "p2": {
            "id": "p2",
            "discipline": "management",
            "fee_numeric": 100000,
            "salary_numeric": 900000,
        },
        "p3": {
            "id": "p3",
            "discipline": "management",
            "fee_numeric": 200000,
            "salary_numeric": 960000,
        },
    }
    result = score_roi(
        {"program": "p1", "current_salary": "b1"},
        {
            "answer_values": {"current_salary": 600000},
            "answer_periods": {"current_salary": "annual"},
        },
        catalog,
    )

    assert result.status == "ok"
    assert result.full["payback_months"] == 6
    assert result.cta_program_ids == ["p2", "p1", "p3"]


def test_roi_refuses_to_parse_missing_numeric_shadow_fields() -> None:
    result = score_roi(
        {"program": "p1"},
        {
            "answer_values": {"current_salary": 50000},
            "answer_periods": {"current_salary": "monthly"},
        },
        {"p1": {"id": "p1", "total_fee": "INR 1,20,000"}},
    )

    assert result.status == "content_unavailable"
    assert "fee_numeric" in (result.reason or "")
    assert "salary_numeric" in (result.reason or "")


def test_roi_flow_preserves_cannot_compute_status_on_safe_exit(tmp_path: Path) -> None:
    path = tmp_path / "tools.json"
    _write_json(path, _content_document())
    state = ConversationState(session_id="roi-cannot-compute")
    engine = ToolEngine(
        ToolsContentStore(path, auto_reload=False),
        catalog={
            "p1": {
                "id": "p1",
                "discipline": "management",
                "fee_numeric": 120000,
                "salary_numeric": 500000,
            }
        },
    )

    engine.enter(state, "roi")
    salary_question = engine.dispatch(state, "p1")
    assert salary_question is not None
    turn = engine.dispatch(state, salary_question.response.quick_actions[0].message)

    assert turn is not None and turn.result is not None
    assert turn.result.status == "cannot_compute"
    assert turn.answered_step == "current_salary"
    assert turn.content_version == "v1"
    assert turn.response.metadata["tool_flow"]["status"] == "cannot_compute"
    assert turn.response.metadata["tool_flow"]["version"] == "v1"
    assert state.active_flow is None


def test_career_score_sums_configured_weights() -> None:
    definition = ToolDefinition.model_validate(
        {
            "enabled": True,
            "steps": _choice_steps(),
            "question_bank": {},
            "reward_bands": [],
        }
    )

    result = score_career_quiz(
        {f"q{index}": "a" for index in range(1, 6)},
        definition,
        program_lookup=lambda discipline: [f"{discipline}-mba"],
    )

    assert result.status == "ok"
    assert result.full["top_discipline"] == "management"
    assert result.full["weights"] == {"management": 10.0}


def test_scholarship_counts_configured_answers_and_selects_band() -> None:
    questions = [
        {
            "id": f"s{index}",
            "prompt": f"Scholarship question {index}",
            "type": "choice",
            "options": [
                {"id": "a", "label": "A", "correct": True},
                {"id": "b", "label": "B", "correct": False},
            ],
        }
        for index in range(1, 8)
    ]
    definition = ToolDefinition.model_validate(
        {
            "enabled": True,
            "steps": [],
            "question_bank": {"online-mba": questions},
            "reward_bands": [
                {"min_correct": 0, "max_correct": 3, "label": "Band 1"},
                {"min_correct": 4, "max_correct": 5, "label": "Band 2"},
                {"min_correct": 6, "max_correct": 7, "label": "Band 3"},
            ],
        }
    )
    answers = {f"s{index}": "a" if index <= 6 else "b" for index in range(1, 8)}

    result = score_scholarship(
        answers,
        definition,
        {"question_bank_key": "online-mba", "program_id": "course-mba"},
    )

    assert result.status == "ok"
    assert result.full["correct_count"] == 6
    assert result.full["reward_band"] == "Band 3"
    assert result.cta_program_ids == ["course-mba"]
