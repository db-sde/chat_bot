from __future__ import annotations

from fastapi.testclient import TestClient

from main import app


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
            "/api/widget/guide/chips",
            headers={
                "Origin": "https://partner.example",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"


def test_free_text_chat_endpoint_is_not_exposed() -> None:
    removed_path = "/" + "chat"
    with TestClient(app) as client:
        response = client.post(removed_path, json={"message": "not accepted"})

    assert response.status_code == 404


def test_widget_assets_are_served_from_stable_embed_urls() -> None:
    with TestClient(app) as client:
        script = client.get("/widget.js")
        stylesheet = client.get("/widget.css")
        demo = client.get("/widget/demo.html")
        source = client.get("/widget/src/widget.js")

    assert script.status_code == 200
    assert "application/javascript" in script.headers["content-type"]
    assert "AUTO-GENERATED FILE" in script.text[:300]
    assert 'data-site-key' in script.text
    assert stylesheet.status_code == 200
    assert "text/css" in stylesheet.headers["content-type"]
    assert ".db-chip" in stylesheet.text
    assert demo.status_code == 200
    assert "widget.js" in demo.text
    assert source.status_code == 404
