#!/usr/bin/env python3

import json
import time
import uuid
import requests
from datetime import datetime

BASE_URL = "http://127.0.0.1:8000"
CHAT_URL = f"{BASE_URL}/chat"

HEADERS = {
    "Content-Type": "application/json"
}


TEST_SUITES = {
    "CATEGORY": [
        "Tell me about MBA",
        "MBA fees",
        "MBA eligibility",
        "Which universities offer MBA?",
        "Tell me about MCA",
        "MCA fees",
        "MCA eligibility",
    ],

    "UNIVERSITY": [
        "Tell me about LPU",
        "Tell me about NMIMS",
        "Tell me about Amity",
        "Tell me about Jain University",
        "Tell me about IGNOU",
        "Tell me about Manipal University Jaipur",
        "Tell me about Sikkim Manipal University",
        "Tell me about SMU",
    ],

    "UNIVERSITY_FACTS": [
        "What is the NAAC grade of NMIMS Online?",
        "Is Amity Online UGC approved?",
        "What is the fee structure of LPU?",
        "What programs does NMIMS offer?",
        "What is the starting fee at Jain University?",
        "What is the accreditation of IGNOU?",
    ],

    "COURSES": [
        "Tell me about LPU MBA",
        "Tell me about NMIMS MBA",
        "Tell me about Amity MBA",
        "Tell me about Jain MBA",
        "Tell me about LPU MCA",
        "Tell me about IGNOU MCA",
        "What is the fee for LPU MBA?",
        "What is the eligibility for NMIMS MBA?",
        "What is the duration of Amity MBA?",
    ],

    "SPECIALIZATIONS": [
        "Tell me about MBA Marketing",
        "Tell me about Marketing specialization",
        "Tell me about LPU MBA Marketing",
        "Tell me about NMIMS MBA Marketing",
        "Tell me about Jain MBA Finance",
        "Tell me about NMIMS MBA Analytics",
        "Tell me about HR specialization",
        "Which university offers Marketing specialization?",
        "Which university offers Finance specialization?",
    ],

    "COMPARISON": [
        "Compare LPU and NMIMS",
        "Compare MBA fees of LPU and NMIMS",
        "Compare LPU MBA and NMIMS MBA",
        "Compare Amity MBA and Jain MBA",
        "Compare MBA and MCA",
        "Compare Marketing and Finance",
    ],

    "DISCOVERY": [
        "Show all MBA programs",
        "Show all MCA programs",
        "Show MBA specializations",
        "Which universities offer MBA?",
        "Which universities offer MCA?",
        "I have completed graduation. Which online MBA options are available?",
        "I want an MBA in Marketing. What are my options?",
    ],

    "ADVISORY": [
        "Suggest an affordable Online MBA",
        "Which Online MBA is best for Marketing?",
        "Which university has the highest accreditation and reasonable fees?",
        "Which MBA should I choose?",
        "Which specialization has the best career opportunities?",
        "I have a budget of 1.8 lakh. Which MBA should I choose?",
    ],

    "LEADS": [
        "Call me",
        "I need counselling",
        "Can someone contact me?",
        "I need admission guidance",
        "Talk to an advisor",
        "Help me choose a university",
    ],

    "TYPOS": [
        "Tell me about manipal japiur",
        "Tell me about igno",
        "Tell me about jian university",
        "lpu mba markting",
        "nmims mba analitics",
        "monypal university",
        "tell me about lpuu",
    ],

    "AMBIGUITY": [
        "Tell me about Marketing",
        "MBA Marketing",
        "Tell me about SMU",
        "Which university offers Marketing specialization?",
        "Tell me about Finance",
    ],

    "NEGATIVE": [
        "Tell me about IIT Bombay Online MBA",
        "Tell me about Harvard MBA",
        "Tell me about Oxford Online MBA",
        "Tell me about BCA",
        "Tell me about MBA in Artificial Intelligence",
        "Compare Harvard and LPU",
        "Tell me about XYZ University",
    ],
}


MULTI_TURN_TESTS = [
    [
        "Tell me about NMIMS MBA",
        "What is the fee?",
        "What is the eligibility?",
        "What is the duration?",
    ],

    [
        "Tell me about LPU MBA",
        "What is the fee?",
        "What is the duration?",
    ],

    [
        "Tell me about NMIMS MBA",
        "Tell me about LPU MBA",
        "What is the fee?",
    ],

    [
        "Tell me about MBA Marketing",
        "LPU MBA Marketing",
        "What is the fee?",
    ],

    [
        "Tell me about Jain MBA Finance",
        "What is the fee?",
        "What jobs can I get?",
    ],
]


def extract_text(response):
    try:
        text = response.text.strip()

        if not text:
            return ""

        lines = []

        for line in text.splitlines():
            line = line.strip()

            if not line:
                continue

            if line.startswith("data:"):
                payload = line[5:].strip()

                try:
                    obj = json.loads(payload)

                    if isinstance(obj, dict):
                        if "content" in obj:
                            lines.append(str(obj["content"]))
                        elif "message" in obj:
                            lines.append(str(obj["message"]))
                        elif "text" in obj:
                            lines.append(str(obj["text"]))
                    else:
                        lines.append(str(obj))

                except Exception:
                    lines.append(payload)

        if lines:
            return "\n".join(lines)

        return text

    except Exception as e:
        return f"ERROR PARSING RESPONSE: {e}"


def chat(message, session_id=None):
    payload = {
        "message": message
    }

    if session_id:
        payload["session_id"] = session_id

    started = time.time()

    try:
        response = requests.post(
            CHAT_URL,
            headers=HEADERS,
            json=payload,
            timeout=120
        )

        latency = round((time.time() - started) * 1000)

        return {
            "status": response.status_code,
            "latency_ms": latency,
            "response": extract_text(response)
        }

    except Exception as e:
        return {
            "status": "ERROR",
            "latency_ms": 0,
            "response": str(e)
        }


def run_single_turn_tests():
    results = []

    for suite_name, questions in TEST_SUITES.items():

        print(f"\n{'='*80}")
        print(f"RUNNING SUITE: {suite_name}")
        print(f"{'='*80}")

        for question in questions:

            result = chat(question)

            print(f"\nQ: {question}")
            print(f"Status : {result['status']}")
            print(f"Latency: {result['latency_ms']}ms")

            preview = result["response"][:300].replace("\n", " ")
            print(f"Answer : {preview}")

            results.append({
                "suite": suite_name,
                "question": question,
                **result
            })

    return results


def run_multi_turn_tests():
    results = []

    print(f"\n{'='*80}")
    print("RUNNING MULTI-TURN TESTS")
    print(f"{'='*80}")

    for index, conversation in enumerate(MULTI_TURN_TESTS, start=1):

        session_id = f"test_{uuid.uuid4().hex[:8]}"

        print(f"\n\nConversation #{index}")
        print(f"Session: {session_id}")

        conversation_results = []

        for message in conversation:

            result = chat(message, session_id=session_id)

            print(f"\nQ: {message}")
            print(f"Latency: {result['latency_ms']}ms")

            preview = result["response"][:300].replace("\n", " ")
            print(f"A: {preview}")

            conversation_results.append({
                "message": message,
                **result
            })

        results.append({
            "conversation_number": index,
            "session_id": session_id,
            "turns": conversation_results
        })

    return results


def save_report(single_turn_results, multi_turn_results):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    report = {
        "generated_at": datetime.now().isoformat(),
        "base_url": BASE_URL,
        "single_turn_results": single_turn_results,
        "multi_turn_results": multi_turn_results,
        "summary": {
            "single_turn_count": len(single_turn_results),
            "multi_turn_conversations": len(multi_turn_results)
        }
    }

    filename = f"chatbot_test_report_{timestamp}.json"

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    return filename


def main():
    print("\n")
    print("=" * 80)
    print("DEGREEBABA CHATBOT REGRESSION TEST RUNNER")
    print("=" * 80)

    health = requests.get(f"{BASE_URL}/health", timeout=10)

    print(f"\nHealth Check: {health.status_code}")

    single_turn_results = run_single_turn_tests()
    multi_turn_results = run_multi_turn_tests()

    report_file = save_report(
        single_turn_results,
        multi_turn_results
    )

    total_tests = len(single_turn_results)

    avg_latency = round(
        sum(r["latency_ms"] for r in single_turn_results) / max(total_tests, 1)
    )

    print("\n")
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Single-turn tests : {len(single_turn_results)}")
    print(f"Multi-turn suites : {len(multi_turn_results)}")
    print(f"Average latency   : {avg_latency}ms")
    print(f"Report            : {report_file}")
    print("=" * 80)


if __name__ == "__main__":
    main()