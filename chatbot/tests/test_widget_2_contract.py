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
