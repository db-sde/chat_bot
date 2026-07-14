import json
import pytest
from fastapi.testclient import TestClient
from main import app

def extract_stream_payloads(response_text):
    payloads = []
    for line in response_text.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            data = line[5:].strip()
            try:
                payloads.append(json.loads(data))
            except Exception:
                payloads.append(data)
    return payloads

def test_widget_parameter_tolerance():
    """Verify that requests with extra query parameters and extra payload fields succeed."""
    with TestClient(app) as client:
        # Test extra payload fields in the POST body
        payload = {
            "message": "tell me about MBA",
            "session_id": "test_tolerance_payload",
            "extra_field_1": "test_value",
            "extra_field_2": 99.9,
            "widget_version": "v1.2.3"
        }
        r = client.post("/chat", json=payload)
        assert r.status_code == 200
        payloads = extract_stream_payloads(r.text)
        assert len(payloads) > 0
        assert "MBA" in payloads[-1]["text"]

        # Test extra query parameters in the URL path
        r_query = client.post("/chat?widget_id=abc&timestamp=123456789&source=widget", json={
            "message": "tell me about MBA",
            "session_id": "test_tolerance_query"
        })
        assert r_query.status_code == 200
        payloads_q = extract_stream_payloads(r_query.text)
        assert len(payloads_q) > 0
        assert "MBA" in payloads_q[-1]["text"]

def test_advisory_classification_routing():
    """Verify routing of various advisory and recommendation queries."""
    with TestClient(app) as client:
        # 1. "which is the best online mba program"
        r1 = client.post("/chat", json={
            "message": "which is the best online mba program",
            "session_id": "test_advisory_route_1"
        })
        assert r1.status_code == 200
        payloads1 = extract_stream_payloads(r1.text)
        assert len(payloads1) > 0
        text1 = payloads1[-1]["text"]
        # Should initiate the advisory profile funnel asking about education
        assert "Advisor profile" in text1 or "Current education" in text1

        # 2. "tell me the best mba courses"
        r2 = client.post("/chat", json={
            "message": "tell me the best mba courses",
            "session_id": "test_advisory_route_2"
        })
        assert r2.status_code == 200
        payloads2 = extract_stream_payloads(r2.text)
        assert len(payloads2) > 0
        text2 = payloads2[-1]["text"]
        # Note: This query routes to MBA overview facts (category overview)
        assert "MBA" in text2

        # 3. "are there any best specializations"
        r3 = client.post("/chat", json={
            "message": "are there any best specializations",
            "session_id": "test_advisory_route_3"
        })
        assert r3.status_code == 200
        payloads3 = extract_stream_payloads(r3.text)
        assert len(payloads3) > 0
        text3 = payloads3[-1]["text"]
        # Routes to general fallback because no category/specialization matched in mentions
        assert "couldn't confidently match" in text3.lower()

        # 4. "Show MBA specializations"
        r4 = client.post("/chat", json={
            "message": "Show MBA specializations",
            "session_id": "test_advisory_route_4"
        })
        assert r4.status_code == 200
        payloads4 = extract_stream_payloads(r4.text)
        assert len(payloads4) > 0
        text4 = payloads4[-1]["text"]
        # Routes to specialization listing
        assert "MBA Specializations" in text4 or "Marketing" in text4

def test_lead_funnel_precedence():
    """Verify that a product query successfully exits an active lead capture funnel."""
    with TestClient(app) as client:
        session_id = "test_funnel_precedence_session"
        
        # Step 1: Start lead capture
        r1 = client.post("/chat", json={
            "message": "request callback",
            "session_id": session_id
        })
        assert r1.status_code == 200
        payloads1 = extract_stream_payloads(r1.text)
        assert "name" in payloads1[-1]["text"].lower() or "counsellor" in payloads1[-1]["text"].lower()

        # Step 2: Send product query: "what is the fee for LPU MBA?"
        r2 = client.post("/chat", json={
            "message": "what is the fee for LPU MBA?",
            "session_id": session_id
        })
        assert r2.status_code == 200
        payloads2 = extract_stream_payloads(r2.text)
        text2 = payloads2[-1]["text"]
        
        # Verify it bypassed the lead funnel name capture and returned course fee info instead
        assert "counsellor" not in text2.lower()
        assert "1,34,000" in text2 or "fee" in text2.lower()
        
        has_lpu_context = (
            "Lovely Professional University" in text2 
            or "LPU" in text2 
            or any("Lovely Professional University" in chip or "LPU" in chip for chip in payloads2[-1].get("suggested_chips", []))
        )
        assert has_lpu_context
