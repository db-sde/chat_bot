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
    assert 'this.api.catalog("courses"' in guided_section
    assert ".innerHTML" not in source


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
