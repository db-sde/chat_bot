from __future__ import annotations

import json
from pathlib import Path

import pytest

from widget.config import (
    DEFAULT_WIDGET_CONFIG_PATH,
    InvalidSiteKeyError,
    UnknownSiteKeyError,
    WidgetConfig,
    WidgetConfigLoadError,
    WidgetConfigStore,
)


def _valid_config(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "bot_name": "DegreeBaba AI Advisor",
        "avatar_url": "/widget/avatar.svg",
        "primary_color": "#ff6b00",
        "welcome_message": "How can I help with your university search?",
        "show_typing_indicator": True,
        "show_avatar": True,
        "auto_open": False,
    }
    value.update(overrides)
    return value


def _write(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_bundled_site_config_loads_with_only_supported_fields() -> None:
    store = WidgetConfigStore(DEFAULT_WIDGET_CONFIG_PATH, auto_reload=False)

    config = store.get("degreebaba")

    assert isinstance(config, WidgetConfig)
    assert config.primary_color == "#FF6B00"
    assert set(config.model_dump()) == {
        "bot_name",
        "avatar_url",
        "primary_color",
        "welcome_message",
        "show_typing_indicator",
        "show_avatar",
        "auto_open",
    }


def test_external_file_can_change_config_without_code_changes(tmp_path: Path) -> None:
    path = tmp_path / "widgets.json"
    _write(path, {"partner-one": _valid_config(bot_name="Partner Advisor")})
    store = WidgetConfigStore(path, auto_reload=False)

    assert store.get("partner-one").bot_name == "Partner Advisor"

    _write(path, {"partner-one": _valid_config(bot_name="Updated Advisor")})
    store.reload()
    assert store.get("partner-one").bot_name == "Updated Advisor"


def test_unknown_site_key_fails_closed_and_try_get_is_explicit(tmp_path: Path) -> None:
    path = tmp_path / "widgets.json"
    _write(path, {"known": _valid_config()})
    store = WidgetConfigStore(path)

    with pytest.raises(UnknownSiteKeyError):
        store.get("unknown")
    assert store.try_get("unknown") is None


@pytest.mark.parametrize("site_key", ["", " leading", "../escape", "contains space", "a" * 65])
def test_invalid_site_key_is_rejected(site_key: str, tmp_path: Path) -> None:
    path = tmp_path / "widgets.json"
    _write(path, {"known": _valid_config()})
    store = WidgetConfigStore(path)

    with pytest.raises(InvalidSiteKeyError):
        store.get(site_key)


@pytest.mark.parametrize(
    "override",
    [
        {"primary_color": "purple"},
        {"primary_color": "#1234"},
        {"avatar_url": "javascript:alert(1)"},
        {"avatar_url": "//untrusted.example/avatar.png"},
        {"show_avatar": "true"},
        {"welcome_message": ""},
    ],
)
def test_invalid_field_values_fail_the_whole_file(
    override: dict[str, object],
    tmp_path: Path,
) -> None:
    path = tmp_path / "widgets.json"
    _write(path, {"known": _valid_config(**override)})

    with pytest.raises(WidgetConfigLoadError):
        WidgetConfigStore(path)


def test_unknown_configuration_field_is_forbidden(tmp_path: Path) -> None:
    path = tmp_path / "widgets.json"
    _write(path, {"known": _valid_config(custom_css="body { display: none; }")})

    with pytest.raises(WidgetConfigLoadError, match="custom_css"):
        WidgetConfigStore(path)


def test_duplicate_json_keys_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "widgets.json"
    path.write_text(
        '{"known": {"bot_name": "First"}, "known": {"bot_name": "Second"}}',
        encoding="utf-8",
    )

    with pytest.raises(WidgetConfigLoadError, match="Duplicate JSON key: known"):
        WidgetConfigStore(path)


def test_payload_uses_nested_public_contract_and_resolved_site_key(tmp_path: Path) -> None:
    path = tmp_path / "widgets.json"
    _write(path, {"known": _valid_config(avatar_url="https://cdn.example/avatar.png")})
    store = WidgetConfigStore(path)

    payload = store.payload("known")

    assert payload == {
        "site_key": "known",
        "branding": {
            "bot_name": "DegreeBaba AI Advisor",
            "avatar_url": "https://cdn.example/avatar.png",
            "primary_color": "#FF6B00",
            "welcome_message": "How can I help with your university search?",
        },
        "behavior": {
            "show_typing_indicator": True,
            "show_avatar": True,
            "auto_open": False,
        },
    }
