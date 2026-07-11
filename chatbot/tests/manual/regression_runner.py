#!/usr/bin/env python3
"""Run the DegreeBaba end-to-end regression transcript against a live API."""

from __future__ import annotations

import argparse
import json
import time
import uuid
from datetime import datetime
from pathlib import Path

import requests

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


def extract_text(response: requests.Response) -> str:
    """Extract the final text field from the API's SSE response."""

    text = response.text.strip()
    if not text:
        return ""
    lines: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        raw = line[5:].strip()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            lines.append(raw)
            continue
        if isinstance(payload, dict):
            for key in ("content", "message", "text"):
                if key in payload:
                    lines.append(str(payload[key]))
                    break
        else:
            lines.append(str(payload))
    return "\n".join(lines) if lines else text


class RegressionRunner:
    def __init__(self, base_url: str, *, timeout_seconds: float = 120.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.chat_url = f"{self.base_url}/chat"
        self.timeout_seconds = timeout_seconds

    def chat(self, message: str, session_id: str | None = None) -> dict[str, object]:
        payload = {"message": message}
        if session_id:
            payload["session_id"] = session_id
        started = time.perf_counter()
        try:
            response = requests.post(
                self.chat_url,
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=self.timeout_seconds,
            )
            return {
                "status": response.status_code,
                "latency_ms": round((time.perf_counter() - started) * 1000),
                "response": extract_text(response),
            }
        except Exception as exc:  # pragma: no cover - manual network harness
            return {"status": "ERROR", "latency_ms": 0, "response": str(exc)}

    def run_single_turn_tests(self) -> list[dict[str, object]]:
        results: list[dict[str, object]] = []
        for suite_name, questions in TEST_SUITES.items():
            print(f"\n{'=' * 80}\nRUNNING SUITE: {suite_name}\n{'=' * 80}")
            for question in questions:
                result = self.chat(question)
                preview = str(result["response"])[:300].replace("\n", " ")
                print(
                    f"\nQ: {question}\nStatus : {result['status']}\n"
                    f"Latency: {result['latency_ms']}ms\nAnswer : {preview}"
                )
                results.append({"suite": suite_name, "question": question, **result})
        return results

    def run_multi_turn_tests(self) -> list[dict[str, object]]:
        results: list[dict[str, object]] = []
        print(f"\n{'=' * 80}\nRUNNING MULTI-TURN TESTS\n{'=' * 80}")
        for index, conversation in enumerate(MULTI_TURN_TESTS, start=1):
            session_id = f"test_{uuid.uuid4().hex[:8]}"
            print(f"\n\nConversation #{index}\nSession: {session_id}")
            turns: list[dict[str, object]] = []
            for message in conversation:
                result = self.chat(message, session_id=session_id)
                preview = str(result["response"])[:300].replace("\n", " ")
                print(
                    f"\nQ: {message}\nLatency: {result['latency_ms']}ms\nA: {preview}"
                )
                turns.append({"message": message, **result})
            results.append(
                {
                    "conversation_number": index,
                    "session_id": session_id,
                    "turns": turns,
                }
            )
        return results

    def run(self, output_dir: Path) -> Path:
        health = requests.get(f"{self.base_url}/health", timeout=10)
        print(f"\nHealth Check: {health.status_code}")
        single_turn = self.run_single_turn_tests()
        multi_turn = self.run_multi_turn_tests()
        now = datetime.now()
        report = {
            "generated_at": now.isoformat(),
            "base_url": self.base_url,
            "single_turn_results": single_turn,
            "multi_turn_results": multi_turn,
            "summary": {
                "single_turn_count": len(single_turn),
                "multi_turn_conversations": len(multi_turn),
            },
        }
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"chatbot_test_report_{now:%Y%m%d_%H%M%S}.json"
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        average = round(
            sum(int(result["latency_ms"]) for result in single_turn)
            / max(len(single_turn), 1)
        )
        print(
            f"\n{'=' * 80}\nSUMMARY\n{'=' * 80}\n"
            f"Single-turn tests : {len(single_turn)}\n"
            f"Multi-turn suites : {len(multi_turn)}\n"
            f"Average latency   : {average}ms\n"
            f"Report            : {path}\n{'=' * 80}"
        )
        return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output-dir", type=Path, default=Path.cwd())
    parser.add_argument("--timeout", type=float, default=120.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    print(f"\n{'=' * 80}\nDEGREEBABA CHATBOT REGRESSION TEST RUNNER\n{'=' * 80}")
    RegressionRunner(args.base_url, timeout_seconds=args.timeout).run(args.output_dir)


if __name__ == "__main__":
    main()
