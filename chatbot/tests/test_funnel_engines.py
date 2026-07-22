from __future__ import annotations

import json
from pathlib import Path

import pytest

from funnel import (
    DEFAULT_CHIP_MAP_PATH,
    DEFAULT_FLOW_MAP_PATH,
    ChipEngine,
    ChipJourneyState,
    ChipMapLoadError,
    ChipMapStore,
    FlowMapLoadError,
    FlowMapStore,
    FunnelStage,
    JourneyEngine,
    ResolvedChip,
    apply_progression,
)


@pytest.fixture()
def store() -> ChipMapStore:
    return ChipMapStore(DEFAULT_CHIP_MAP_PATH, auto_reload=False)


def _ids(chips: object) -> list[str]:
    return [chip.id for chip in chips]  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("page_type", "top", "more"),
    [
        (
            "homepage",
            ["browse_universities", "browse_programs", "career_quiz_tool", "validity"],
            ["compare_universities", "counsellor"],
        ),
        (
            "pillar",
            ["list_providers", "fees_across", "specialization_quiz_tool", "check_eligibility"],
            ["compare_top", "careers", "counsellor"],
        ),
        (
            "university",
            ["programs_here", "placement_support", "reviews", "counsellor"],
            [
                "approvals",
                "why_choose",
                "admission_process",
                "compare_others",
                "average_rating",
            ],
        ),
        (
            "course",
            ["fees_emi", "eligibility", "specializations", "reviews"],
            [
                "careers",
                "placement_support",
                "admission_process",
                "scholarship_tool",
                "syllabus",
                "apply_now",
                "compare_program",
                "counsellor",
            ],
        ),
        (
            "specialization",
            ["careers", "fees_emi", "eligibility", "placement_support"],
            [
                "admission_process",
                "reviews",
                "scholarship_tool",
                "compare_specializations",
                "syllabus",
                "apply_now",
                "counsellor",
            ],
        ),
    ],
)
def test_journey_engine_returns_only_configured_opening_sets(
    store: ChipMapStore,
    page_type: str,
    top: list[str],
    more: list[str],
) -> None:
    result = JourneyEngine(store).opening(page_type)

    assert _ids(result.top) == top
    assert _ids(result.more) == more
    assert result.config_version == "2026-07-22-chip-final"
    assert not result.missing_surface


def test_catalog_v3_chip_labels_are_short_and_action_oriented(
    store: ChipMapStore,
) -> None:
    chips = store.snapshot().chips

    assert chips["programs_here"].label == "📚 Programs offered"
    assert "starting_fees" not in chips
    assert chips["eligibility"].label == "✅ Eligibility"
    assert chips["syllabus"].label == "📖 Curriculum"
    assert chips["scholarship_tool"].label == "🎓 Scholarships"
    assert chips["compare_program"].label == "⚖️ Compare this program"
    assert chips["compare_specializations"].label == "⚖️ Compare specializations"


@pytest.mark.parametrize(
    ("answer_state", "expected"),
    [
        ("fees", ["eligibility", "roi_tool", "counsellor"]),
        ("eligibility_yes", ["admission_steps", "scholarship_tool", "apply_now"]),
        ("eligibility_no", ["eligible_programs", "counsellor"]),
        ("careers", ["see_fees", "roi_tool", "apply_now", "counsellor"]),
        ("syllabus", ["careers_from_syllabus", "eligibility", "apply_now", "counsellor"]),
        ("validity", ["browse_programs", "counsellor"]),
        ("reviews", ["fees_emi", "apply_now", "counsellor"]),
        ("comparison", ["roi_tool", "apply_now", "counsellor"]),
    ],
)
def test_chip_engine_resolves_specified_answer_surfaces(
    store: ChipMapStore,
    answer_state: str,
    expected: list[str],
) -> None:
    result = ChipEngine(store).lookup(
        page_type="homepage" if answer_state == "validity" else "course",
        answer_state=answer_state,
        interaction_count=1,
    )

    assert _ids(result.chips) == expected
    assert not result.missing_surface


def test_progression_adds_conversion_and_promotes_it_at_threshold(
    store: ChipMapStore,
) -> None:
    engine = ChipEngine(store)

    early = engine.lookup("course", card_type="course", interaction_count=2)
    warm = engine.lookup("course", card_type="course", interaction_count=3)

    assert _ids(early.chips) == [
        "fees_emi",
        "eligibility",
        "specializations",
        "reviews",
        "apply_now",
    ]
    assert _ids(warm.chips) == [
        "apply_now",
        "fees_emi",
        "eligibility",
        "specializations",
        "reviews",
    ]


def test_progression_never_returns_an_up_funnel_chip(store: ChipMapStore) -> None:
    config = store.snapshot()
    browse = ResolvedChip(
        id="browse_programs",
        label="📚 Browse programs",
        handler="list_programs",
        funnel_stage=FunnelStage.TOP,
    )
    apply = ResolvedChip(
        id="apply_now",
        label="📝 Apply now",
        handler="cta_apply",
        funnel_stage=FunnelStage.BOTTOM,
    )

    result = apply_progression(
        [browse, apply],
        config=config,
        source_stage=FunnelStage.BOTTOM,
        interaction_count=1,
    )

    assert _ids(result) == ["apply_now"]


def test_tool_reveal_uses_apply_counsellor_compare_priority(store: ChipMapStore) -> None:
    result = ChipEngine(store).lookup(
        page_type="specialization",
        answer_state="tool_reveal",
        interaction_count=0,
    )

    assert _ids(result.chips)[:3] == ["apply_now", "counsellor", "compare"]
    assert _ids(result.chips)[3:] == []


def test_roi_is_only_declared_on_context_ready_followup_surfaces(
    store: ChipMapStore,
) -> None:
    config = store.snapshot()
    roi_surfaces = {
        key
        for key, surface in config.surfaces.items()
        if "roi_tool" in surface.follow
    }

    assert roi_surfaces == {
        "answer:fees",
        "answer:careers",
        "answer:comparison",
        "answer:placement",
    }
    assert all(
        "roi_tool" not in (*surface.top, *surface.more)
        for surface in config.surfaces.values()
    )


def test_completed_actions_are_suppressed_without_removing_all_conversion(
    store: ChipMapStore,
) -> None:
    result = ChipEngine(store).lookup(
        page_type="course",
        answer_state="fees",
        interaction_count=1,
        state=ChipJourneyState(
            completed_actions=frozenset({"eligibility", "counsellor"})
        ),
    )

    assert _ids(result.chips) == ["roi_tool", "apply_now"]
    assert "eligibility" not in _ids(result.chips)
    assert "counsellor" not in _ids(result.chips)


def test_completed_action_suppresses_other_labels_for_the_same_handler(
    store: ChipMapStore,
) -> None:
    result = ChipEngine(store).lookup(
        page_type="specialization",
        answer_state="careers",
        interaction_count=1,
        state=ChipJourneyState(completed_actions=frozenset({"fees_emi"})),
    )

    assert "see_fees" not in _ids(result.chips)
    assert _ids(result.chips) == ["roi_tool", "apply_now", "counsellor"]


def test_no_specialization_surface_never_moves_back_to_browsing(
    store: ChipMapStore,
) -> None:
    result = ChipEngine(store).lookup(
        page_type="course",
        answer_state="no_specializations",
        interaction_count=1,
    )

    assert _ids(result.chips) == [
        "fees_emi",
        "careers",
        "apply_now",
        "counsellor",
    ]
    assert not {"browse_programs", "browse_universities"}.intersection(_ids(result.chips))


def test_missing_surface_logs_and_returns_safe_defaults(
    store: ChipMapStore,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("WARNING"):
        result = ChipEngine(store).lookup(
            page_type="course",
            answer_state="not_configured",
            interaction_count=1,
        )

    assert result.missing_surface
    assert _ids(result.chips) == ["apply_now", "counsellor"]
    assert "Missing chip surface: answer:not_configured" in caplog.text


def test_invalid_hot_reload_keeps_last_good_snapshot(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    path = tmp_path / "chip_map.json"
    document = json.loads(DEFAULT_CHIP_MAP_PATH.read_text(encoding="utf-8"))
    path.write_text(json.dumps(document), encoding="utf-8")
    store = ChipMapStore(path, auto_reload=False)

    document["chips"]["fees_emi"]["handler"] = "not_registered"
    path.write_text(json.dumps(document), encoding="utf-8")
    with caplog.at_level("WARNING"):
        snapshot = store.reload()

    assert snapshot.version == "2026-07-22-chip-final"
    assert snapshot.chips["fees_emi"].handler == "get_fees"
    assert "keeping last-good config" in caplog.text


def test_flow_map_exactly_covers_configured_chip_surfaces(store: ChipMapStore) -> None:
    flow = FlowMapStore(store, DEFAULT_FLOW_MAP_PATH, auto_reload=False).snapshot()
    chips = store.snapshot()

    assert flow is not None
    assert flow.version == chips.version
    assert set(flow.surfaces) == set(chips.surfaces)
    for key, surface in chips.surfaces.items():
        assert set(flow.surfaces[key]) == set(
            (*surface.top, *surface.more, *surface.follow)
        )


def test_flow_map_rejects_an_unknown_destination(
    tmp_path: Path,
) -> None:
    chip_path = tmp_path / "chip_map.json"
    flow_path = tmp_path / "flow_map.json"
    chip_path.write_text(DEFAULT_CHIP_MAP_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    document = json.loads(DEFAULT_FLOW_MAP_PATH.read_text(encoding="utf-8"))
    document["surfaces"]["page:home"]["validity"] = "answer:not_real"
    flow_path.write_text(json.dumps(document), encoding="utf-8")
    local_store = ChipMapStore(chip_path, auto_reload=False)

    with pytest.raises(FlowMapLoadError, match="unknown surface"):
        FlowMapStore(local_store, flow_path, auto_reload=False)


def test_invalid_flow_hot_reload_keeps_last_good_snapshot(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    chip_path = tmp_path / "chip_map.json"
    flow_path = tmp_path / "flow_map.json"
    chip_path.write_text(DEFAULT_CHIP_MAP_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    document = json.loads(DEFAULT_FLOW_MAP_PATH.read_text(encoding="utf-8"))
    flow_path.write_text(json.dumps(document), encoding="utf-8")
    local_store = ChipMapStore(chip_path, auto_reload=False)
    flow_store = FlowMapStore(local_store, flow_path, auto_reload=False)

    document["surfaces"]["page:home"]["validity"] = "answer:not_real"
    flow_path.write_text(json.dumps(document), encoding="utf-8")
    with caplog.at_level("WARNING"):
        snapshot = flow_store.reload()

    assert snapshot.surfaces["page:home"]["validity"] == "answer:validity"
    assert "keeping last-good config" in caplog.text


def test_completed_chip_advances_the_persisted_flow_pointer(
    store: ChipMapStore,
) -> None:
    state = {
        "navigation": {
            "current_node": "page:home",
            "completed_actions": [],
        }
    }

    result = ChipEngine(store).lookup(
        page_type="homepage",
        answer_state="validity",
        completed_chip_id="validity",
        interaction_count=1,
        state=state,
    )

    assert result.surface == "answer:validity"
    assert _ids(result.chips) == ["browse_programs", "counsellor"]
    assert state["navigation"]["current_node"] == "answer:validity"


def test_terminal_chip_short_circuits_to_conversion_chips(
    store: ChipMapStore,
) -> None:
    state = {
        "navigation": {
            "current_node": "page:home",
            "completed_actions": ["counsellor"],
        }
    }

    result = ChipEngine(store).lookup(
        page_type="homepage",
        completed_chip_id="counsellor",
        interaction_count=1,
        state=state,
    )

    assert result.funnel_stage is FunnelStage.BOTTOM
    assert _ids(result.chips) == ["apply_now"]


def test_chip_map_requires_a_version_bump_for_changed_content(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    path = tmp_path / "chip_map.json"
    document = json.loads(DEFAULT_CHIP_MAP_PATH.read_text(encoding="utf-8"))
    path.write_text(json.dumps(document), encoding="utf-8")
    store = ChipMapStore(path, auto_reload=False)

    document["chips"]["fees_emi"]["label"] = "Changed without a version bump"
    path.write_text(json.dumps(document), encoding="utf-8")
    with caplog.at_level("WARNING"):
        snapshot = store.reload()

    assert snapshot.chips["fees_emi"].label == "💰 Fees & EMI"
    assert "without a new version identifier" in caplog.text


def test_chip_map_retains_prior_version_for_in_flight_actions(tmp_path: Path) -> None:
    path = tmp_path / "chip_map.json"
    first = json.loads(DEFAULT_CHIP_MAP_PATH.read_text(encoding="utf-8"))
    path.write_text(json.dumps(first), encoding="utf-8")
    store = ChipMapStore(path, auto_reload=False)

    second = json.loads(json.dumps(first))
    second["version"] = "2026-07-17"
    second["chips"]["fees_emi"]["label"] = "Updated fees label"
    path.write_text(json.dumps(second), encoding="utf-8")
    store.reload()

    current = store.snapshot()
    prior = store.snapshot(version=first["version"])
    assert current is not None and current.version == "2026-07-17"
    assert prior is not None
    assert prior.chips["fees_emi"].label == "💰 Fees & EMI"


def test_initial_load_rejects_unregistered_handlers(tmp_path: Path) -> None:
    path = tmp_path / "chip_map.json"
    document = json.loads(DEFAULT_CHIP_MAP_PATH.read_text(encoding="utf-8"))
    document["chips"]["fees_emi"]["handler"] = "not_registered"
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ChipMapLoadError, match="unregistered handler"):
        ChipMapStore(path, auto_reload=False)


def test_fill_and_ab_schema_are_preserved_without_runtime_assignment(tmp_path: Path) -> None:
    path = tmp_path / "chip_map.json"
    document = json.loads(DEFAULT_CHIP_MAP_PATH.read_text(encoding="utf-8"))
    document["chips"]["future_experiment"] = {
        "handler": "compare",
        "label": "⚖️ Compare with {rival}",
        "funnel_stage": "bottom",
        "type": "nav_set",
        "fill": {"rival": "nearest_by_fee_band"},
        "ab": [
            {"id": "a", "label": "⚖️ Compare with {rival}"},
            {"id": "b", "label": "⚖️ See the closest alternative"}
        ]
    }
    path.write_text(json.dumps(document), encoding="utf-8")

    snapshot = ChipMapStore(path, auto_reload=False).snapshot()

    experiment = snapshot.chips["future_experiment"]
    assert experiment.fill == {"rival": "nearest_by_fee_band"}
    assert [variant.id for variant in experiment.ab] == ["a", "b"]
