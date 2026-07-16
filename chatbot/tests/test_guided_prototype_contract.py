from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

WIDGET_DIR = Path(__file__).resolve().parents[1] / "widget"
PROTOTYPE_DIR = WIDGET_DIR / "prototype"


class _PrototypeParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.scenarios: set[str] = set()
        self.scripts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.add(str(values["id"]))
        if values.get("name") == "scenario" and values.get("value"):
            self.scenarios.add(str(values["value"]))
        if tag == "script" and values.get("src"):
            self.scripts.append(str(values["src"]))


def _source(name: str) -> str:
    return (PROTOTYPE_DIR / name).read_text(encoding="utf-8")


def test_simulator_has_all_scenarios_and_controller_mount_points() -> None:
    parser = _PrototypeParser()
    parser.feed(_source("index.html"))

    assert parser.scenarios == {"homepage", "university", "course", "specialization"}
    assert {
        "scenario-form",
        "context-json",
        "context-bar",
        "clear-context",
        "feed",
        "guide-heading",
        "guide-actions",
        "more-actions",
        "sheet-backdrop",
        "picker-sheet",
        "sheet-title",
        "sheet-search",
        "sheet-list",
        "sheet-close",
        "chat-form",
        "chat-input",
        "chat-submit",
        "lead-sheet",
        "lead-form",
        "lead-close",
        "lead-phone",
        "status-region",
    } <= parser.ids
    assert parser.scripts == ["./prototype.js"]


def test_scenarios_use_the_exact_logical_context_contract() -> None:
    source = _source("prototype.js")

    assert 'homepage: Object.freeze({ page_type: "homepage" })' in source
    assert 'university: Object.freeze({ page_type: "university", university: "nmims" })' in source
    assert (
        'course: Object.freeze({ page_type: "course", university: "nmims", course: "mba" })'
        in source
    )
    assert 'specialization: "business-analytics"' in source


def test_guide_and_chat_transports_are_kept_separate() -> None:
    source = _source("prototype.js")
    guided_section = source.split("class GuidedNavigator", maxsplit=1)[1].split(
        "function renderChatQuickActions", maxsplit=1
    )[0]

    assert 'fetch(`${apiBase}/chat`' in source
    assert source.count("chatTransport.send(") == 1
    assert 'dom.chatForm.addEventListener("submit"' in source
    assert '"/chat"' not in guided_section
    assert "chatTransport" not in guided_section
    assert "this.api.catalog(picker.requestKind" in guided_section
    assert ".innerHTML" not in source


def test_exploration_states_use_prompts_and_choices_instead_of_entity_cards() -> None:
    source = _source("prototype.js")
    render_bundle = source.split('renderBundle(origin = "page") {', maxsplit=1)[1].split(
        "programLabel(item)", maxsplit=1
    )[0]
    select_entity = source.split("selectEntity(entity, selectionLabel) {", maxsplit=1)[1].split(
        'async loadContext(origin = "page")', maxsplit=1
    )[0]
    category_flow = source.split("showProgramCategory(category) {", maxsplit=1)[1].split(
        "compareKind()", maxsplit=1
    )[0]

    assert render_bundle.count("renderEntityCard(") == 1
    assert re.search(
        r'pageType\s*===\s*"university"[\s\S]+pageType\s*===\s*"course"[\s\S]+'
        r"renderEntityCard\(",
        render_bundle,
    )
    assert "What would you like to know?" in render_bundle
    assert "showUniversityPrograms()" in render_bundle
    assert "showCourseSpecializations()" in render_bundle
    assert "renderEntityCard(" not in select_entity
    assert "renderEntityCard(" not in category_flow
    assert 'this.openPicker("courses"' in category_flow
    assert "renderHelpChoose" not in source


def test_specialization_and_information_states_remain_answer_cards() -> None:
    source = _source("prototype.js")
    handlers = source.split("handleAction(action, label) {", maxsplit=1)[1].split(
        "\n    renderChooseFirst(subject", maxsplit=1
    )[0]
    comparison = source.split("async submitComparison() {", maxsplit=1)[1].split(
        "openLead()", maxsplit=1
    )[0]

    assert "strongest catalog match" in source
    for renderer in (
        "renderFees(this)",
        "renderEligibility(this)",
        "renderCareer(this)",
        "renderReviews(this)",
        "renderSyllabus(this)",
        "renderAccreditations(this)",
    ):
        assert renderer in handlers
    assert "renderComparison(this, payload)" in comparison


def test_guided_responses_are_paced_and_choices_are_progressively_disclosed() -> None:
    source = _source("prototype.js")
    delay = re.search(r"const GUIDED_THINKING_MS = (\d+);", source)

    assert delay is not None
    assert 500 <= int(delay.group(1)) <= 900
    assert "function thinkingIndicator()" in source
    assert "async runGuidedResponse(callback)" in source
    assert "await wait(GUIDED_THINKING_MS)" in source
    assert 'const pageSize = offset === 0 ? 3 : 2;' in source
    assert 'const primaryLimit = pageType === "homepage" ? 4 : 3;' in source
    assert "visible.slice(0, 3)" in source


def test_viewed_actions_are_filtered_and_previous_answer_cards_collapse() -> None:
    source = _source("prototype.js")
    styles = _source("prototype.css")

    assert "viewedActions: new Set()" in source
    assert "this.state.viewedActions.add(action)" in source
    assert "!viewed.has(action)" in source
    assert "function collapsePrimaryCards(dom)" in source
    assert 'card.dataset.primaryCard = "true"' in source
    assert ".prototype-thinking" in styles
    assert ".prototype-collapsed-answer" in styles


def test_lead_form_preserves_the_existing_phone_only_contract() -> None:
    source = _source("prototype.js")
    lead_method = source.split("lead(sessionId, phone, signal)", maxsplit=1)[1].split(
        "class ChatTransport", maxsplit=1
    )[0]

    assert "session_id: sessionId || null" in lead_method
    assert "phone," in lead_method
    assert 'source: "guided_prototype"' in lead_method
    assert not re.search(r"\b(?:name|email)\s*:", lead_method)
    assert 'id="lead-name"' not in _source("index.html")
    assert 'id="lead-email"' not in _source("index.html")


def test_visual_layer_has_reference_palette_and_responsive_device_rules() -> None:
    source = _source("prototype.css").casefold()

    assert "--navy: #0e1f3d" in source
    assert "--orange: #e84010" in source
    assert "--canvas: #f7f8fa" in source
    assert ".widget-shell" in source
    assert "@media (max-width: 820px)" in source
    assert "@media (max-width: 480px)" in source
    assert "prefers-reduced-motion" in source


def test_production_embed_assets_do_not_load_the_simulator_controller() -> None:
    production_script = (WIDGET_DIR / "widget.js").read_text(encoding="utf-8")
    production_demo = (WIDGET_DIR / "demo.html").read_text(encoding="utf-8")

    assert "guided-prototype" not in production_script
    assert "prototype.js" not in production_script
    assert "prototype.js" not in production_demo
