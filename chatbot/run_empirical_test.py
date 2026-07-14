import json
import sys
import os
from fastapi.testclient import TestClient

# Ensure we're in the chatbot folder or add it to path
sys.path.append(os.path.abspath('.'))

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

def main():
    print("Initializing TestClient and running lifespan...")
    with TestClient(app) as client:
        print("=== TEST 1: Widget parameter tolerance ===")
        # Extra payload fields
        payload = {
            "message": "tell me about MBA",
            "session_id": "test_tolerance_1",
            "extra_field_1": "test",
            "extra_field_2": 42
        }
        r = client.post("/chat", json=payload)
        print(f"POST /chat (extra payload fields) -> Status: {r.status_code}")
        payloads = extract_stream_payloads(r.text)
        print(f"Payloads count: {len(payloads)}")
        if payloads:
            print(f"Last payload text preview: {payloads[-1].get('text', '')[:100]}...")
        
        # Extra query parameters
        r_query = client.post("/chat?widget_id=123&client_ts=99999", json={
            "message": "tell me about MBA",
            "session_id": "test_tolerance_2"
        })
        print(f"POST /chat (extra query parameters) -> Status: {r_query.status_code}")
        payloads_q = extract_stream_payloads(r_query.text)
        print(f"Payloads count: {len(payloads_q)}")
        if payloads_q:
            print(f"Last payload text preview: {payloads_q[-1].get('text', '')[:100]}...")
        
        print("\n=== TEST 2: Advisory/recommendation queries ===")
        queries = [
            "which is the best online mba program",
            "tell me the best mba courses",
            "are there any best specializations",
            "are there any best mba specializations"
        ]
        for q in queries:
            session_id = f"test_advisory_{queries.index(q)}"
            r = client.post("/chat", json={"message": q, "session_id": session_id})
            print(f"Query: '{q}' -> Status: {r.status_code}")
            payloads = extract_stream_payloads(r.text)
            print(f"Payloads count: {len(payloads)}")
            if payloads:
                print(f"Last payload text preview: {payloads[-1].get('text', '')[:100]}...")
            print("-" * 50)

        print("\n=== TEST 3: Lead funnel precedence ===")
        session_id = "test_lead_precedence_session"
        
        # Step 1: Request callback to activate the lead funnel
        print("Sending callback request...")
        r1 = client.post("/chat", json={"message": "request callback", "session_id": session_id})
        payloads1 = extract_stream_payloads(r1.text)
        print(f"Response to callback: {payloads1[-1].get('text', '') if payloads1 else ''}")
        
        # Step 2: Send product query: "what is the fee for LPU MBA?"
        print("Sending product query: 'what is the fee for LPU MBA?'...")
        r2 = client.post("/chat", json={"message": "what is the fee for LPU MBA?", "session_id": session_id})
        payloads2 = extract_stream_payloads(r2.text)
        print(f"Response to product query: {payloads2[-1].get('text', '') if payloads2 else ''}")
        print(f"Suggested chips: {payloads2[-1].get('suggested_chips', []) if payloads2 else []}")

if __name__ == "__main__":
    main()
