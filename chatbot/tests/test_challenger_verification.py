import json

from fastapi.testclient import TestClient

from main import app


def parse_sse(text: str) -> dict:
    response_payload = {}
    for line in text.splitlines():
        if line.startswith("data: "):
            payload_str = line[5:].strip()
            try:
                data = json.loads(payload_str)
                if "text" in data:
                    response_payload = data
            except Exception:
                pass
    return response_payload


def test_widget_parameter_tolerance():
    """Verify that requests with multiple extra query parameters or body parameters succeed."""
    with TestClient(app) as client:
        # 1. URL Query Parameters
        response_query = client.post(
            "/chat?utm_source=widget&extra_param=123&another=xyz",
            json={"message": "mba", "session_id": "test_widget_query"},
        )
        assert response_query.status_code == 200
        payload_query = parse_sse(response_query.text)
        assert payload_query.get("session_id") == "test_widget_query"
        assert len(payload_query.get("text", "")) > 0

        # 2. Extra fields in JSON body
        response_json = client.post(
            "/chat",
            json={
                "message": "mba",
                "session_id": "test_widget_json",
                "site_key": "dummy_key",
                "page_university_slug": "nmims",
                "extra_param_1": "val1",
                "extra_param_2": 999,
            },
        )
        assert response_json.status_code == 200
        payload_json = parse_sse(response_json.text)
        assert payload_json.get("session_id") == "test_widget_json"
        assert len(payload_json.get("text", "")) > 0


def test_advisory_classification():
    """Verify routing of various advisory and recommendation queries."""
    with TestClient(app) as client:
        # Case A: "which is the best online mba program"
        # Expected: Routes to advisory, starting the advisor profiling flow.
        res_a = client.post(
            "/chat",
            json={"message": "which is the best online mba program", "session_id": "test_adv_a"},
        )
        assert res_a.status_code == 200
        payload_a = parse_sse(res_a.text)
        assert "education" in payload_a.get("text", "").lower()
        assert "Completed graduation" in payload_a.get("suggested_chips", [])

        # Case B: "tell me the best mba courses"
        # Expected: Routes to category overview (MBA Programs...) as per local classification rules.
        res_b = client.post(
            "/chat", json={"message": "tell me the best mba courses", "session_id": "test_adv_b"}
        )
        assert res_b.status_code == 200
        payload_b = parse_sse(res_b.text)
        assert "MBA" in payload_b.get("text", "")
        assert "published universities" in payload_b.get("text", "").lower()

        # Case C: "are there any best specializations" (fresh session)
        # With no named catalog concept, it routes to the general fallback.
        res_c = client.post(
            "/chat",
            json={"message": "are there any best specializations", "session_id": "test_adv_c"},
        )
        assert res_c.status_code == 200
        payload_c = parse_sse(res_c.text)
        assert "couldn't confidently match" in payload_c.get("text", "").lower()

        # Case D: "are there any best specializations" (with prior MBA focus)
        # Expected: Routes to category overview since focus is set.
        client.post("/chat", json={"message": "MBA", "session_id": "test_adv_d"})
        res_d = client.post(
            "/chat",
            json={"message": "are there any best specializations", "session_id": "test_adv_d"},
        )
        assert res_d.status_code == 200
        payload_d = parse_sse(res_d.text)
        assert "MBA" in payload_d.get("text", "")


def test_lead_funnel_precedence():
    """Verify that starting a lead capture session and then sending a product query
    successfully exits the funnel and displays the course fee instead of capturing it as a name.
    """
    with TestClient(app) as client:
        session_id = "test_lead_precedence_session"

        # 1. Start lead capture session (Request callback)
        res_start = client.post(
            "/chat", json={"message": "Request Callback", "session_id": session_id}
        )
        assert res_start.status_code == 200
        payload_start = parse_sse(res_start.text)
        # Should ask for name
        assert "name" in payload_start.get("text", "").lower()

        # 2. Send a product query for a program published under LPU in Catalog V3.
        res_query = client.post(
            "/chat", json={"message": "what is the fee for LPU MCA?", "session_id": session_id}
        )
        assert res_query.status_code == 200
        payload_query = parse_sse(res_query.text)

        # 3. Verify it exited the funnel and displayed the course fee
        # The response text should describe fees for the MCA course.
        assert "fee" in payload_query.get("text", "").lower()
        # Verify the suggested chips refer to Lovely Professional University (LPU)
        assert any(
            "Lovely Professional University" in chip
            for chip in payload_query.get("suggested_chips", [])
        )

        # The next turn must use normal chat rather than the abandoned lead flow.
        res_next = client.post("/chat", json={"message": "hello", "session_id": session_id})
        assert res_next.status_code == 200
        payload_next = parse_sse(res_next.text)
        # It must not emit the lead-capture completion response.
        assert "saved" not in payload_next.get("text", "").lower()
        assert "counsellor" not in payload_next.get("text", "").lower()
