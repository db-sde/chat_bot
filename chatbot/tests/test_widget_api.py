from __future__ import annotations

import json

from fastapi.testclient import TestClient

from main import app


def _response_events(body: str) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for block in body.replace("\r\n", "\n").split("\n\n"):
        event = ""
        data = ""
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line.removeprefix("event:").strip()
            elif line.startswith("data:"):
                data = line.removeprefix("data:").strip()
        if event == "response" and data:
            events.append(json.loads(data))
    return events


def test_widget_config_endpoint_uses_nested_tenant_contract() -> None:
    with TestClient(app) as client:
        response = client.get("/api/widget/config/degreebaba")

    assert response.status_code == 200
    assert response.json() == {
        "site_key": "degreebaba",
        "branding": {
            "bot_name": "DegreeBaba AI Advisor",
            "avatar_url": None,
            "primary_color": "#FF6B00",
            "welcome_message": (
                "Hi! I can help you explore universities and online programs."
            ),
        },
        "behavior": {
            "show_typing_indicator": True,
            "show_avatar": True,
            "auto_open": False,
        },
    }


def test_widget_config_endpoint_rejects_invalid_and_unknown_tenants() -> None:
    with TestClient(app) as client:
        invalid = client.get("/api/widget/config/contains%20space")
        unknown = client.get("/api/widget/config/not-configured")

    assert invalid.status_code == 400
    assert unknown.status_code == 404


def test_widget_embed_cors_preflight_is_public_by_default() -> None:
    with TestClient(app) as client:
        response = client.options(
            "/chat",
            headers={
                "Origin": "https://partner.example",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"


def test_chat_transport_keeps_legacy_fields_and_adds_rich_components() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/chat",
            json={
                "message": "Tell me about NMIMS MCA",
                "session_id": "widget-rich-program",
                "site_key": "degreebaba",
                "page_university_slug": "nmims",
            },
        )

    assert response.status_code == 200
    payload = _response_events(response.text)[-1]
    assert payload["text"]
    assert payload["message"]
    assert payload["message"] != payload["text"]
    component_types = {
        component["type"]
        for component in payload["components"]
        if isinstance(component, dict)
    }
    assert {"program_card", "quick_actions"}.issubset(component_types)
    assert payload["suggested_chips"]


def test_widget_assets_are_served_from_stable_embed_urls() -> None:
    with TestClient(app) as client:
        script = client.get("/widget.js")
        stylesheet = client.get("/widget.css")
        demo = client.get("/widget/demo.html")

    assert script.status_code == 200
    assert "application/javascript" in script.headers["content-type"]
    assert "script.dataset.siteKey" in script.text
    assert stylesheet.status_code == 200
    assert "text/css" in stylesheet.headers["content-type"]
    assert ".db-widget" in stylesheet.text
    assert demo.status_code == 200
    assert "widget.js" in demo.text
