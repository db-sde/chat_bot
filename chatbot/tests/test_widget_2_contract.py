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


def test_intermediate_guided_navigation_uses_questions_before_cards() -> None:
    source = _source("widget.js")
    select_entity = _function_source(source, "selectGuidedEntity")

    for name in ("showUniversityPrograms", "showCourseSpecializations"):
        function_source = _function_source(source, name)
        assert "presentGuidedCard(" not in function_source
        assert "renderUniversityCard(" not in function_source
        assert "renderProgramCard(" not in function_source

    assert "showUniversityPrograms(" in select_entity
    assert "showCourseSpecializations(" in select_entity
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
    assert "const primaryLimit = 3" in starter_bank
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
    assert '"Apply Now", "lead"' in source
    assert "width: max-content" in styles
    assert "db-widget__context-meta-item" in styles
    assert "db-widget__ai-accent" in styles
    assert "@media (max-width: 560px)" in styles


def test_recommendation_cards_use_compact_metadata_and_progressive_details() -> None:
    source = _source("widget.js")
    styles = _source("widget.css")
    university_card = _function_source(source, "renderUniversityCard")
    program_card = _function_source(source, "renderProgramCard")
    card_actions = _function_source(source, "cardActions")
    open_details = _function_source(source, "openDetails")

    for renderer in (university_card, program_card):
        assert "compactMetadata(" in renderer
        assert "statPills(" not in renderer

    assert "db-widget__emi-line" not in program_card

    assert 'detailsLabel = "Details"' in card_actions
    assert '"+ Compare"' in card_actions
    assert 'detailSection(detailBody, "Key details", details.key_details)' in open_details
    assert ".db-widget__compact-meta" in styles
    assert ".db-widget__compact-meta-item:not(:last-child)::after" in styles
    assert "min-height: 28px" in styles
    assert "width: auto" in styles


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
