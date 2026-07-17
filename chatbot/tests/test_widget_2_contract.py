from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

WIDGET_DIR = Path(__file__).resolve().parents[1] / "widget"


def _source(name: str) -> str:
    return (WIDGET_DIR / name).read_text(encoding="utf-8")


def _function_source(source: str, name: str) -> str:
    """Return one top-level widget function without depending on its exact position."""

    match = re.search(
        rf"^  (?:async\s+)?function\s+{re.escape(name)}\s*\([^)]*\)\s*{{",
        source,
        flags=re.MULTILINE,
    )
    assert match is not None, f"widget.js is missing {name}()"
    next_function = re.search(
        r"^  (?:async\s+)?function\s+[A-Za-z_$][\w$]*\s*\(",
        source[match.end() :],
        flags=re.MULTILINE,
    )
    end = match.end() + next_function.start() if next_function else len(source)
    return source[match.start() : end]


class _DemoParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.scenarios: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if (
            tag == "input"
            and values.get("type") == "radio"
            and values.get("name") == "scenario"
            and values.get("value")
        ):
            self.scenarios.add(str(values["value"]))


def test_production_widget_owns_guided_state_and_catalog_transports() -> None:
    source = _source("widget.js")

    assert "guideBundle" in source
    assert "guideBusy" in source
    assert "viewedActions: new Set()" in source
    assert "/api/widget/guide/context" in source
    assert "/api/widget/guide/catalog/" in source
    assert "/api/widget/guide/compare" in source


def test_guided_actions_do_not_enter_typed_chat_transport() -> None:
    source = _source("widget.js")
    guided_functions = (
        "executeGuidedAction",
        "selectGuidedEntity",
        "showUniversityPrograms",
        "showCourseSpecializations",
    )

    for name in guided_functions:
        function_source = _function_source(source, name)
        assert "/chat" not in function_source
        assert "sendMessage(" not in function_source

    send_message = _function_source(source, "sendMessage")
    assert "fetch(`${apiBase}/chat`" in send_message
    assert 'composer.addEventListener("submit"' in source
    assert "sendMessage(input.value)" in source


def test_course_selection_renders_course_card_before_optional_specializations() -> None:
    source = _source("widget.js")
    select_entity = _function_source(source, "selectGuidedEntity")

    for name in ("showUniversityPrograms", "showCourseSpecializations"):
        function_source = _function_source(source, name)
        assert "presentGuidedCard(" not in function_source
        assert "renderUniversityCard(" not in function_source
        assert "renderProgramCard(" not in function_source

    assert "showUniversityPrograms(" in select_entity
    assert "showCourseSpecializations(" not in select_entity
    assert 'transitionNavigation("course_card")' in select_entity
    assert 'loadFollowupChips({ cardType: "course" })' in select_entity
    assert "renderProgramCard(course)" in select_entity
    assert "presentGuidedCard(" in select_entity
    assert "specialization" in select_entity.casefold()


def test_guided_responses_are_paced_and_filter_completed_actions() -> None:
    source = _source("widget.js")
    delay = re.search(r"const GUIDED_THINKING_MS\s*=\s*(\d+);", source)
    guided_response = _function_source(source, "runGuidedResponse")

    assert delay is not None
    assert 500 <= int(delay.group(1)) <= 800
    assert "guideBusy" in guided_response
    assert "GUIDED_THINKING_MS" in guided_response
    assert re.search(r"viewedActions\.add\(", source)
    assert re.search(r"viewedActions\.(?:has|forEach)\(", source)

    quick_actions = _function_source(source, "renderQuickActions")
    assert re.search(r"slice\(0,\s*3\)", quick_actions)
    assert '"More' in quick_actions


def test_typing_and_all_guided_choice_surfaces_respect_the_visible_cap() -> None:
    source = _source("widget.js")
    show_typing = _function_source(source, "showTyping")
    starter_bank = _function_source(source, "renderStarterBank")
    finder_step = _function_source(source, "renderFinderStep")

    assert "state.messages.appendChild(state.typing)" in show_typing
    assert "state.openingChips" in starter_bank
    assert "opening.top" in starter_bank
    assert "opening.more" in starter_bank
    assert "emitStarterImpressions()" in starter_bank
    assert '"More"' in starter_bank
    assert "renderOptionPage" in finder_step
    assert "const pageSize" in finder_step
    assert "current.options.forEach" not in finder_step


def test_new_guided_card_collapses_the_previous_information_card() -> None:
    source = _source("widget.js")
    styles = _source("widget.css")
    presenter = _function_source(source, "presentGuidedCard")
    collapse = _function_source(source, "collapseGuidedCards")

    assert "collapseGuidedCards(" in presenter
    assert "querySelectorAll" in collapse
    assert any(
        marker in collapse
        for marker in (".open = false", 'setAttribute("open"', "classList.add")
    )
    assert "collapsed" in styles or "[open]" in styles


def test_clearing_context_resets_guidance_but_preserves_rendered_chat() -> None:
    source = _source("widget.js")
    clear_context = _function_source(source, "clearContext")

    assert "updateContext(null)" in clear_context
    assert "guideBundle" in clear_context
    assert "viewedActions.clear()" in clear_context
    assert "state.messages.replaceChildren" not in clear_context
    assert "state.messages.innerHTML" not in clear_context
    assert "state.messages.remove" not in clear_context


def test_demo_switches_all_scenarios_and_loads_only_the_real_widget() -> None:
    source = _source("demo.html")
    parser = _DemoParser()
    parser.feed(source)

    assert parser.scenarios == {"homepage", "university", "course", "specialization"}
    assert 'embed.src = "/widget.js"' in source
    assert "prototype.js" not in source
    assert "prototype.css" not in source
    assert 'pageType: "university"' in source
    assert 'pageType: "course"' in source
    assert 'pageType: "specialization"' in source
    assert 'pageUniversitySlug: "nmims"' in source
    assert 'pageEntitySlug: "nmims-online"' in source
    assert 'pageEntitySlug: "nmims-online-mba"' in source
    assert 'pageEntitySlug: "nmims-mba-analytics"' in source
    assert re.search(r"location\.(?:assign|replace|href|search)", source)


def test_premium_admissions_ui_contracts_are_present() -> None:
    source = _source("widget.js")
    styles = _source("widget.css")
    create_message = _function_source(source, "createMessage")
    update_context = _function_source(source, "updateContext")

    assert "db-widget__message-row--grouped" in create_message
    assert "contextCourse" in update_context
    assert "contextMeta" in update_context
    assert 'chip_id: "apply_now"' in source
    assert 'chip_handler: "cta_apply"' in source
    assert "width: max-content" in styles
    assert "db-widget__context-meta-item" in styles
    assert "db-widget__ai-accent" in styles
    assert "@media (max-width: 560px)" in styles
    assert ".db-widget__sticky-context[hidden]" in styles


def test_clearing_context_removes_all_stale_context_content() -> None:
    source = _source("widget.js")
    update_context = _function_source(source, "updateContext")

    assert 'state.contextLabel.textContent = ""' in update_context
    assert 'state.contextCourse.textContent = ""' in update_context
    assert 'academicPath ? `· ${academicPath}` : ""' in update_context
    assert "state.contextCourse.parentElement.hidden = true" in update_context
    assert "state.contextMeta.replaceChildren()" in update_context
    assert 'state.contextChip.removeAttribute("aria-label")' in update_context


def test_recommendation_cards_match_the_reference_card_structure() -> None:
    source = _source("widget.js")
    styles = _source("widget.css")
    university_card = _function_source(source, "renderUniversityCard")
    program_card = _function_source(source, "renderProgramCard")
    card_actions = _function_source(source, "cardActions")
    open_details = _function_source(source, "openDetails")
    presenter = _function_source(source, "presentGuidedCard")

    for renderer in (university_card, program_card):
        assert "cardPills(" in renderer
        assert "db-widget__card-header" in renderer
        assert "db-widget__card-mark" in renderer
        assert "compactMetadata(" not in renderer
        assert "statPills(" not in renderer

    assert "db-widget__card-emi" in program_card
    assert "db-widget__card-job" in program_card
    assert ".db-widget__program-card, .db-widget__university-card" in presenter

    assert 'detailsLabel = "Details"' in card_actions
    assert '"+ Compare"' in card_actions
    assert 'detailSection(detailBody, "Key details", details.key_details)' in open_details
    assert ".db-widget__pills-row" in styles
    assert ".db-widget__card-job" in styles
    assert "min-height: 42px" in styles
    assert "flex: 1 1 0" in styles


def test_catalog_picker_has_clear_sections_and_mobile_sheet_containment() -> None:
    source = _source("widget.js")
    styles = _source("widget.css")
    results = _function_source(source, "renderPickerResults")
    open_picker = _function_source(source, "openPicker")

    assert '"⭐ Popular"' in results
    assert '"db-widget__picker-section db-widget__picker-section--all"' in results
    assert 'normalizedQuery ? `${filtered.length} Results` : "All"' in results
    assert "db-widget__picker-letter" not in results
    assert "data.items.length" in open_picker
    assert '.db-widget__launcher--open' in styles
    assert "grid-template-columns: minmax(0, 1fr)" in styles
    assert ".db-widget__picker-search:focus" in styles
    assert ".db-widget__picker-overlay .db-widget__picker-header::before" in styles


def test_comparison_picker_confirms_and_excludes_the_first_selection() -> None:
    source = _source("widget.js")
    results = _function_source(source, "renderPickerResults")
    picker = _function_source(source, "openPicker")
    comparison = _function_source(source, "openComparisonPicker")
    styles = _source("widget.css")

    assert "options.excludeIds" in results
    assert "excludedIds.has(String(item.id))" in results
    assert "options.selectionLabel" in picker
    assert '"db-widget__picker-selection"' in picker
    assert "`Choose a different ${optionLabel}`" in comparison
    assert "excludeIds: state.compareSelections.map" in comparison
    assert "selectionLabel: selected && selected.label" in comparison
    assert "selectionCount === 1" in comparison
    assert ".db-widget__picker-selection" in styles
    assert ".db-widget__picker-search-field .db-widget__picker-search:focus-visible" in styles


def test_widget_uses_degreebaba_tokens_and_exposes_accessible_ui_state() -> None:
    source = _source("widget.js")
    styles = _source("widget.css")
    show_typing = _function_source(source, "showTyping")
    starter_bank = _function_source(source, "renderStarterBank")
    build_widget = _function_source(source, "buildWidget")

    canonical_tokens = {
        "--color-navy: #0e1f3d",
        "--color-orange: #e84010",
        "--color-bg: #f7f8fa",
        "--color-border: #e5e7eb",
        "--font-sans: \"DM Sans\"",
        "--radius-lg: 12px",
        "--shadow-card: 0 1px 3px rgba(0, 0, 0, 0.06)",
        "--shadow-modal: 0 8px 24px rgba(0, 0, 0, 0.12)",
    }
    for token in canonical_tokens:
        assert token in styles

    assert "linear-gradient" not in styles
    assert "backdrop-filter: blur" not in styles
    assert '"#E84010"' in source
    assert 'setAttribute("aria-busy"' in show_typing
    assert 'setAttribute("aria-expanded"' in starter_bank
    assert 'setAttribute("aria-labelledby"' in build_widget


def test_funnel_chips_and_navigation_are_server_driven() -> None:
    source = _source("widget.js")
    load_context = _function_source(source, "loadGuideContext")
    load_followups = _function_source(source, "loadFollowupChips")

    assert "const NavigationStep = Object.freeze" in source
    assert "function transitionNavigation" in source
    assert "OPENING_ACTIONS" not in source
    assert "MORE_ACTIONS" not in source
    assert "guidedFollowUps" not in source
    assert 'query.set("session_id", state.sessionId)' in load_context
    assert "payload.opening" in source
    assert 'fetchJson("/api/widget/guide/chips"' in load_followups
    assert "payload.followup" in load_followups
    assert "safeFallbackActions()" in load_followups


def test_no_specialization_uses_down_funnel_server_actions_only() -> None:
    source = _source("widget.js")
    show_specializations = _function_source(source, "showCourseSpecializations")

    assert 'answerState: "no_specializations"' in show_specializations
    assert "loadFollowupChips(" in show_specializations
    assert 'action: "browse_programs"' not in show_specializations
    assert 'openPicker("course"' not in show_specializations


def test_widget_emits_non_blocking_funnel_analytics_and_renders_tool_reveal() -> None:
    source = _source("widget.js")
    analytics = _function_source(source, "emitAnalytics")
    chip_impressions = _function_source(source, "emitChipShown")
    lead_panel = _function_source(source, "openLeadPanel")

    assert "/api/widget/analytics" in analytics
    assert "keepalive: true" in analytics
    assert "void fetch" in analytics
    for event_name in (
        "chip_shown",
        "chip_tapped",
        "card_shown",
        "cascade_step",
        "apply_clicked",
        "counsellor_clicked",
    ):
        assert f'"{event_name}"' in source
    assert "response.response" in lead_panel
    assert "renderBotPayload(response.response)" in lead_panel
    assert 'emitAnalytics("lead_captured"' not in source
    assert "chip_id: String(action.chip_id)" in chip_impressions


def test_funnel_widget_keeps_server_state_and_internal_tokens_out_of_user_bubbles() -> None:
    source = _source("widget.js")
    transition = _function_source(source, "transitionNavigation")
    action_handler = _function_source(source, "handleAction")
    sender = _function_source(source, "sendMessage")
    followups = _function_source(source, "renderGuidedActions")

    for step in ("APPROVALS", "REVIEWS", "SYLLABUS", "ADMISSIONS", "VALIDITY"):
        assert f'{step}: "{step}"' in source
    assert "navigation.completed_actions" in transition
    assert "state.viewedActions.clear()" in transition
    assert "displayText: action.label" in action_handler
    assert 'String(options.displayText || message)' in sender
    assert "safeFallbackActions()" not in followups


def test_generic_info_flow_uses_neutral_eligibility_and_a_down_funnel_picker() -> None:
    source = _source("widget.js")
    guided_info = _function_source(source, "showGuidedInfo")
    select_entity = _function_source(source, "selectGuidedEntity")

    assert 'eligibility: "eligibility_borderline"' in guided_info
    assert "state.pendingGuidedInfo" in guided_info
    assert "await showProgramOptions()" in guided_info
    assert "safeFallbackActions()" not in guided_info
    assert "state.pendingGuidedInfo" in select_entity


def test_admission_chip_uses_grounded_guided_info_instead_of_generic_chat() -> None:
    source = _source("widget.js")
    guided_card = _function_source(source, "guidedInfoCard")
    executor = _function_source(source, "executeGuidedAction")

    assert 'admission_process: "admissions"' in source
    assert 'get_admission_steps: "admissions"' in source
    assert 'admissions: ["Next steps", "Admission process"]' in guided_card
    assert '"accreditations", "admissions"' in executor
    assert "Admission-process details haven't been published yet." in guided_card


def test_eligibility_summary_is_not_repeated_as_a_missing_checklist() -> None:
    source = _source("widget.js")
    renderer = _function_source(source, "renderEligibilityCard")

    assert "else if (!summary)" in renderer


def test_guided_info_does_not_claim_unpublished_data_is_confirmed() -> None:
    source = _source("widget.js")
    guided_info = _function_source(source, "showGuidedInfo")

    assert "bundle.info[kind].available" in guided_info
    assert "details haven't been published" in guided_info


def test_first_send_waits_for_context_and_starter_impressions_require_visibility() -> None:
    source = _source("widget.js")
    sender = _function_source(source, "sendMessage")
    builder = _function_source(source, "buildWidget")
    loader = _function_source(source, "loadGuideContext")
    impressions = _function_source(source, "emitStarterImpressions")
    set_open = _function_source(source, "setOpen")

    assert "if (state.guideReady) await state.guideReady" in sender
    assert "state.conversationStarted = true" in sender
    assert "renderStarterBank(pageType)" not in builder
    assert "starter.hidden = true" in builder
    assert "state.starter.hidden = state.conversationStarted" in loader
    assert "renderStarterBank(state.starterType)" in loader
    assert "!state.open" in impressions
    assert "state.starter.hidden" in impressions
    assert "state.starterImpressionKey" in impressions
    assert "emitStarterImpressions()" in set_open


def test_response_action_metadata_is_applied_before_cards_and_propagated() -> None:
    source = _source("widget.js")
    renderer = _function_source(source, "renderBotPayload")
    chip_metadata = _function_source(source, "applyChipMetadata")
    analytics_payload = _function_source(source, "analyticsPayload")
    sender = _function_source(source, "sendMessage")
    followups = _function_source(source, "loadFollowupChips")
    lead_panel = _function_source(source, "openLeadPanel")

    assert renderer.index("applyActionMetadata(actions)") < renderer.index("components.forEach")
    assert "chipPayload.correlation_id" in chip_metadata
    assert "correlation_id" in analytics_payload
    assert "body.chip_config_version" in sender
    assert "body.chip_correlation_id" in sender
    assert "config_version: state.configVersion" in followups
    assert "correlation_id: state.correlationId" in followups
    assert "leadBody.chip_config_version" in lead_panel
    assert "leadBody.chip_correlation_id" in lead_panel


def test_guided_card_impressions_use_the_loaded_followup_surface() -> None:
    source = _source("widget.js")
    info_card = _function_source(source, "guidedInfoCard")
    guided_info = _function_source(source, "showGuidedInfo")
    validity_card = _function_source(source, "validityCard")
    execute = _function_source(source, "executeGuidedAction")

    assert 'emitAnalytics("card_shown"' not in info_card
    assert guided_info.index("await loadFollowupChips") < guided_info.index(
        'emitAnalytics("card_shown"'
    )
    assert 'emitAnalytics("card_shown"' not in validity_card
    validity_branch = execute.index('action === "online_validity"')
    assert execute.index("await loadFollowupChips", validity_branch) < execute.index(
        'emitAnalytics("card_shown"', validity_branch
    )


def test_active_tool_resume_and_lead_gate_name_are_supported() -> None:
    source = _source("widget.js")
    loader = _function_source(source, "loadGuideContext")
    renderer = _function_source(source, "renderBotPayload")
    active_flow = _function_source(source, "applyActiveFlow")
    lead_panel = _function_source(source, "openLeadPanel")

    assert "payload.active_flow" in loader
    assert "state.activeFlowResumeKey" in loader
    assert "renderBotPayload(resumeResponse)" in loader
    assert "activeFlowMetadata(safePayload)" in renderer
    assert "emptyToolContext" in renderer
    assert 'step === "await_lead"' in active_flow
    assert "flow.requires_lead === true" in active_flow
    assert 'state.currentChipSurface = `tool:${tool}`' in active_flow
    assert 'state.currentFunnelStage = "bottom"' in active_flow
    assert "requiresName" in lead_panel
    assert "leadBody.name = normalizedName" in lead_panel


def test_action_lead_tags_are_preserved_in_analytics() -> None:
    source = _source("widget.js")
    payload = _function_source(source, "analyticsPayload")

    assert "item.lead_tags" in payload
    assert "{ lead_tags: item.lead_tags }" in payload


def test_conversion_chip_is_persisted_before_lead_submission_without_rendering_followups() -> None:
    source = _source("widget.js")
    persist = _function_source(source, "persistCompletedChip")
    execute = _function_source(source, "executeGuidedAction")
    lead_panel = _function_source(source, "openLeadPanel")

    assert 'fetchJson("/api/widget/guide/chips"' in persist
    assert "completed_chip_id: chip.chip_id" in persist
    assert "config_version: chip.config_version" in persist
    assert "correlation_id: chip.correlation_id" in persist
    assert "applyServerNavigation(payload)" in persist
    assert "renderBotPayload" not in persist
    assert "persistCompletedChip(chip)" in execute
    assert "await persistence" in lead_panel
    assert "!chipPersisted" in lead_panel
