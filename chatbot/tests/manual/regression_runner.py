#!/usr/bin/env python3
"""Run the DegreeBaba end-to-end regression transcript against a live API."""

from __future__ import annotations

import argparse
import json
import time
import uuid
from dataclasses import dataclass
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
        "Which universities offer Marketing specialization?",
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
    "OUTCOME_INTENT": [
        "i want to talk to consulaor",
        "i need someone to help me",
        "Tell me about harward uni",
        "what is the value of pi",
        "tell me about the about today news",
        "I'm confused",
        "need help deciding",
        "can somebody guide me",
    ],
    "FINAL_BLUEPRINT": [
        "monypal mba fees",
        "markting",
        "finace",
        "lpuu",
        "nmis",
        "Harvard MBA",
        "Oxford MBA",
        "Stanford MBA",
        "Marketing",
        "Finance",
        "HR",
        "MBA",
        "MCA",
        "IGNOU MBA",
        "SMU",
    ],
}

DETERMINISTIC_ACTION_CASES = {
    "Show MBA specializations",
    "Which universities offer Marketing specialization?",
}
GEMINI_CALLBACK_CASES = {
    "I'm confused",
    "need help deciding",
    "can somebody guide me",
}
FINAL_BLUEPRINT_ZERO_GEMINI_CASES = set(TEST_SUITES["FINAL_BLUEPRINT"])
TRACKED_ACTION_CASES = (
    DETERMINISTIC_ACTION_CASES | GEMINI_CALLBACK_CASES | FINAL_BLUEPRINT_ZERO_GEMINI_CASES
)


@dataclass(frozen=True, slots=True)
class TextExpectation:
    """Required and forbidden response fragments for one acceptance input."""

    required: tuple[str, ...]
    forbidden: tuple[str, ...] = ()


FINAL_BLUEPRINT_EXPECTATIONS = {
    "monypal mba fees": TextExpectation(
        required=("Manipal University Jaipur", "Sikkim Manipal University"),
        forbidden=("couldn't find",),
    ),
    "markting": TextExpectation(
        required=("Marketing is offered", "published universities"),
        forbidden=("Which one did you mean", "couldn't find"),
    ),
    "finace": TextExpectation(
        required=("Finance Management is offered", "Jain University Online"),
        forbidden=("Which one did you mean", "couldn't find"),
    ),
    "lpuu": TextExpectation(
        required=("Lovely Professional University",),
        forbidden=("couldn't find",),
    ),
    "nmis": TextExpectation(
        required=("Narsee Monjee",),
        forbidden=("couldn't find",),
    ),
    "Harvard MBA": TextExpectation(
        required=("couldn't find Harvard", "Available MBA providers include"),
    ),
    "Oxford MBA": TextExpectation(
        required=("couldn't find Oxford", "Available MBA providers include"),
    ),
    "Stanford MBA": TextExpectation(
        required=("couldn't find Stanford", "Available MBA providers include"),
    ),
    "Marketing": TextExpectation(
        required=("Marketing is offered", "published universities"),
        forbidden=("Which one did you mean",),
    ),
    "Finance": TextExpectation(
        required=("Finance Management is offered", "Jain University Online"),
        forbidden=("Which one did you mean",),
    ),
    "HR": TextExpectation(
        required=("Human Resource Management is offered",),
        forbidden=("Which one did you mean",),
    ),
    "MBA": TextExpectation(
        required=("MBA is available from",),
        forbidden=("Which one did you mean",),
    ),
    "MCA": TextExpectation(
        required=("MCA is available from",),
        forbidden=("Which one did you mean",),
    ),
    "IGNOU MBA": TextExpectation(
        required=("IGNOU does not currently offer MBA", "Available providers include"),
    ),
    "SMU": TextExpectation(
        required=(
            "Which one did you mean",
            "Sikkim Manipal University",
            "Srinivas Management University",
        ),
    ),
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
    [
        "NMIMS MBA",
        "What are the fees?",
    ],
    [
        "NMIMS MBA",
        "What is BBA?",
    ],
    [
        "NMIMS MBA",
        "Show Marketing specializations",
    ],
    [
        "Talk to counsellor",
        "Browse Universities",
    ],
]

FINAL_BLUEPRINT_MULTI_TURN_CASES = {
    ("NMIMS MBA", "What are the fees?"): "contextual_fee_followup",
    ("NMIMS MBA", "What is BBA?"): "explicit_unknown_drops_context",
    (
        "NMIMS MBA",
        "Show Marketing specializations",
    ): "specialization_discovery_drops_context",
    ("Talk to counsellor", "Browse Universities"): "lead_state_isolation",
}


def extract_response_payload(response: requests.Response) -> dict[str, object]:
    """Return the final response-shaped SSE payload without discarding CTA data."""

    body = response.text.strip()
    if not body:
        return {}

    final_payload: dict[str, object] | None = None
    streamed_tokens: list[str] = []
    unparsed_data: list[str] = []
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        raw = line[5:].strip()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            unparsed_data.append(raw)
            continue
        if not isinstance(payload, dict):
            unparsed_data.append(str(payload))
            continue
        if "token" in payload:
            streamed_tokens.append(str(payload["token"]))
        if any(key in payload for key in ("text", "content", "message")):
            final_payload = dict(payload)

    if final_payload is not None:
        if "text" not in final_payload:
            for key in ("content", "message"):
                if key in final_payload:
                    final_payload["text"] = str(final_payload[key])
                    break
        return final_payload
    if streamed_tokens:
        return {"text": "".join(streamed_tokens)}
    if unparsed_data:
        return {"text": "\n".join(unparsed_data)}
    return {"text": body}


def extract_text(response: requests.Response) -> str:
    """Backward-compatible text-only view of the final SSE payload."""

    return str(extract_response_payload(response).get("text", ""))


class RegressionRunner:
    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 120.0,
        admin_api_key: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.chat_url = f"{self.base_url}/chat"
        self.timeout_seconds = timeout_seconds
        self.admin_api_key = admin_api_key
        self.http = requests.Session()
        self.validation_failures: list[dict[str, str]] = []

    def close(self) -> None:
        self.http.close()

    def __enter__(self) -> RegressionRunner:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    def _admin_headers(self) -> dict[str, str]:
        if not self.admin_api_key:
            return {}
        return {"Authorization": f"Bearer {self.admin_api_key}"}

    def reset_intent_metrics(self) -> None:
        response = self.http.post(
            f"{self.base_url}/admin/metrics/reset",
            headers=self._admin_headers(),
            timeout=10,
        )
        response.raise_for_status()

    def get_intent_metrics(self) -> dict[str, object]:
        response = self.http.get(f"{self.base_url}/metrics", timeout=10)
        response.raise_for_status()
        metrics = response.json()
        if not isinstance(metrics, dict):
            raise TypeError("GET /metrics returned a non-object JSON payload")
        return metrics

    def _record_failures(
        self,
        scope: str,
        case: str,
        failures: list[str],
        *,
        result: dict[str, object] | None = None,
    ) -> None:
        if not failures:
            return
        if result is not None:
            result["validation_failures"] = list(failures)
        for message in failures:
            failure = {"scope": scope, "case": case, "message": message}
            self.validation_failures.append(failure)
            print(f"VALIDATION FAILURE [{scope} / {case}]: {message}")

    def chat(self, message: str, session_id: str | None = None) -> dict[str, object]:
        payload = {"message": message}
        if session_id:
            payload["session_id"] = session_id
        started = time.perf_counter()
        try:
            response = self.http.post(
                self.chat_url,
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=self.timeout_seconds,
            )
            response_payload = extract_response_payload(response)
            return {
                "status": response.status_code,
                "latency_ms": round((time.perf_counter() - started) * 1000),
                "response": str(response_payload.get("text", "")),
                "response_payload": response_payload,
            }
        except Exception as exc:  # pragma: no cover - manual network harness
            return {
                "status": "ERROR",
                "latency_ms": round((time.perf_counter() - started) * 1000),
                "response": str(exc),
                "response_payload": {},
            }

    def run_single_turn_tests(self) -> list[dict[str, object]]:
        results: list[dict[str, object]] = []
        for suite_name, questions in TEST_SUITES.items():
            print(f"\n{'=' * 80}\nRUNNING SUITE: {suite_name}\n{'=' * 80}")
            for question in questions:
                failures: list[str] = []
                metrics_before: dict[str, object] | None = None
                if question in TRACKED_ACTION_CASES:
                    try:
                        metrics_before = self.get_intent_metrics()
                    except Exception as exc:  # pragma: no cover - live harness failure
                        failures.append(
                            f"could not read pre-turn metrics: {type(exc).__name__}: {exc}"
                        )
                result = self.chat(question)
                failures.extend(_validate_basic_result(result))
                delta: dict[str, int] | None = None
                if metrics_before is not None:
                    try:
                        metrics_after = self.get_intent_metrics()
                    except Exception as exc:  # pragma: no cover - live harness failure
                        failures.append(
                            f"could not read post-turn metrics: {type(exc).__name__}: {exc}"
                        )
                    else:
                        delta = _metrics_delta(metrics_before, metrics_after)
                        result["action_metrics_delta"] = delta
                if question in TRACKED_ACTION_CASES:
                    failures.extend(_validate_tracked_action(question, result, delta))
                if question in FINAL_BLUEPRINT_EXPECTATIONS:
                    failures.extend(_validate_final_blueprint_single(question, result))
                result["validation_failures"] = list(failures)
                self._record_failures(
                    "single_turn",
                    question,
                    failures,
                    result=result,
                )
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
            acceptance_case = FINAL_BLUEPRINT_MULTI_TURN_CASES.get(tuple(conversation))
            case_label = acceptance_case or f"conversation_{index}"
            failures: list[str] = []
            metrics_before: dict[str, object] | None = None
            if acceptance_case is not None:
                try:
                    metrics_before = self.get_intent_metrics()
                except Exception as exc:  # pragma: no cover - live harness failure
                    failures.append(
                        f"could not read pre-conversation metrics: {type(exc).__name__}: {exc}"
                    )
            print(f"\n\nConversation #{index}\nSession: {session_id}")
            turns: list[dict[str, object]] = []
            for turn_number, message in enumerate(conversation, start=1):
                result = self.chat(message, session_id=session_id)
                turn_failures = _validate_basic_result(result)
                result["validation_failures"] = list(turn_failures)
                failures.extend(
                    f"turn {turn_number} ({message}): {failure}" for failure in turn_failures
                )
                preview = str(result["response"])[:300].replace("\n", " ")
                print(f"\nQ: {message}\nLatency: {result['latency_ms']}ms\nA: {preview}")
                turns.append({"message": message, **result})
            delta: dict[str, int] | None = None
            if metrics_before is not None:
                try:
                    metrics_after = self.get_intent_metrics()
                except Exception as exc:  # pragma: no cover - live harness failure
                    failures.append(
                        f"could not read post-conversation metrics: {type(exc).__name__}: {exc}"
                    )
                else:
                    delta = _metrics_delta(metrics_before, metrics_after)
            if acceptance_case is not None:
                failures.extend(
                    _validate_final_blueprint_conversation(
                        acceptance_case,
                        turns,
                        delta,
                    )
                )
            conversation_result: dict[str, object] = {
                "conversation_number": index,
                "session_id": session_id,
                "turns": turns,
                "validation_failures": list(failures),
            }
            if acceptance_case is not None:
                conversation_result["acceptance_case"] = acceptance_case
            if delta is not None:
                conversation_result["action_metrics_delta"] = delta
            self._record_failures(
                "multi_turn",
                case_label,
                failures,
                result=conversation_result,
            )
            results.append(conversation_result)
        return results

    def run(self, output_dir: Path) -> Path:
        self.validation_failures.clear()
        health_snapshot: dict[str, object] = {}
        single_turn: list[dict[str, object]] = []
        multi_turn: list[dict[str, object]] = []
        intent_metrics: dict[str, object] = {}

        can_execute = True
        try:
            health = self.http.get(f"{self.base_url}/health", timeout=10)
            try:
                health_body: object = health.json()
            except ValueError:
                health_body = health.text
            health_snapshot = {
                "status_code": health.status_code,
                "body": health_body,
            }
            health.raise_for_status()
        except Exception as exc:  # pragma: no cover - live harness failure
            can_execute = False
            self._record_failures(
                "harness",
                "health",
                [f"health check failed: {type(exc).__name__}: {exc}"],
            )
        else:
            print(f"\nHealth Check: {health.status_code}")

        if can_execute:
            try:
                self.reset_intent_metrics()
            except Exception as exc:  # pragma: no cover - live harness failure
                self._record_failures(
                    "harness",
                    "metrics_reset",
                    [f"metrics reset failed: {type(exc).__name__}: {exc}"],
                )
            try:
                single_turn = self.run_single_turn_tests()
            except Exception as exc:  # pragma: no cover - defensive harness boundary
                self._record_failures(
                    "harness",
                    "single_turn_execution",
                    [f"unexpected runner failure: {type(exc).__name__}: {exc}"],
                )
            try:
                multi_turn = self.run_multi_turn_tests()
            except Exception as exc:  # pragma: no cover - defensive harness boundary
                self._record_failures(
                    "harness",
                    "multi_turn_execution",
                    [f"unexpected runner failure: {type(exc).__name__}: {exc}"],
                )

        try:
            intent_metrics = self.get_intent_metrics()
        except Exception as exc:  # pragma: no cover - live harness failure
            self._record_failures(
                "harness",
                "metrics_snapshot",
                [f"final metrics snapshot failed: {type(exc).__name__}: {exc}"],
            )

        expected_messages = len(single_turn) + sum(
            len(conversation["turns"]) for conversation in multi_turn
        )
        if intent_metrics:
            self._record_failures(
                "metrics",
                "final_invariants",
                _validate_intent_metrics(intent_metrics, expected_messages),
            )

        now = datetime.now()
        passed = not self.validation_failures
        report = {
            "generated_at": now.isoformat(),
            "base_url": self.base_url,
            "health": health_snapshot,
            "single_turn_results": single_turn,
            "multi_turn_results": multi_turn,
            "intent_metrics": intent_metrics,
            "passed": passed,
            "validation_failures": list(self.validation_failures),
            "summary": {
                "single_turn_count": len(single_turn),
                "multi_turn_conversations": len(multi_turn),
                "message_count": expected_messages,
                "validation_failure_count": len(self.validation_failures),
                "passed": passed,
            },
        }
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"chatbot_test_report_{now:%Y%m%d_%H%M%S}.json"
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        average = round(
            sum(int(result["latency_ms"]) for result in single_turn) / max(len(single_turn), 1)
        )
        latency = intent_metrics.get("llm_intent_latency_ms", {})
        if not isinstance(latency, dict):
            latency = {}
        p50 = _format_latency_ms(latency.get("p50"))
        p95 = _format_latency_ms(latency.get("p95"))
        try:
            rate = float(intent_metrics.get("llm_intent_call_rate", 0.0)) * 100
        except (TypeError, ValueError):
            rate = 0.0
        print(
            f"\n{'=' * 80}\nSUMMARY\n{'=' * 80}\n"
            f"Single-turn tests : {len(single_turn)}\n"
            f"Multi-turn suites : {len(multi_turn)}\n"
            f"Average latency   : {average}ms\n"
            f"Messages: {intent_metrics.get('total_messages', 0)}\n"
            f"LLM Intent Calls: {intent_metrics.get('llm_intent_calls', 0)}\n"
            f"Rate: {rate:.2f}%\n"
            f"LLM Intent p50 latency: {p50}\n"
            f"LLM Intent p95 latency: {p95}\n"
            "LLM Intent failures (fell back to heuristic): "
            f"{intent_metrics.get('llm_intent_failures', 0)}\n"
            "Actions from deterministic rules: "
            f"{intent_metrics.get('action_from_deterministic_rule', 0)}\n"
            "Actions from heuristic regex: "
            f"{intent_metrics.get('action_from_heuristic_regex', 0)}\n"
            "Actions from Gemini: "
            f"{intent_metrics.get('action_from_gemini', 0)}\n"
            f"Validation failures: {len(self.validation_failures)}\n"
            f"Result            : {'PASS' if passed else 'FAIL'}\n"
            f"Report            : {path}\n{'=' * 80}"
        )
        if self.validation_failures:
            print("\nVALIDATION FAILURES")
            for failure in self.validation_failures:
                print(f"- [{failure['scope']} / {failure['case']}] {failure['message']}")
        return path


def _format_latency_ms(value: object) -> str:
    if value is None:
        return "N/A"
    return f"{round(float(value))}ms"


def _validate_basic_result(result: dict[str, object]) -> list[str]:
    failures: list[str] = []
    if result.get("status") != 200:
        failures.append(f"expected HTTP 200, got {result.get('status')!r}")
    if not str(result.get("response", "")).strip():
        failures.append("response text was empty")
    if not isinstance(result.get("response_payload"), dict):
        failures.append("final SSE response payload was not an object")
    return failures


def _validate_text_expectation(
    text: str,
    expectation: TextExpectation,
) -> list[str]:
    failures: list[str] = []
    normalized = text.casefold()
    missing = [value for value in expectation.required if value.casefold() not in normalized]
    present = [value for value in expectation.forbidden if value.casefold() in normalized]
    if missing:
        failures.append(f"response was missing required text: {missing}")
    if present:
        failures.append(f"response contained forbidden text: {present}")
    return failures


def _validate_zero_gemini_delta(
    delta: dict[str, int] | None,
    *,
    expected_messages: int,
) -> list[str]:
    if delta is None:
        return ["metrics delta was unavailable; zero-Gemini behavior was not proved"]

    failures: list[str] = []
    if delta["total_messages"] != expected_messages:
        failures.append(
            "metrics message delta mismatch: "
            f"expected {expected_messages}, got {delta['total_messages']}"
        )
    for key in (
        "llm_intent_calls",
        "llm_intent_failures",
        "action_from_gemini",
        "llm_intent_latency_samples",
    ):
        if delta[key] != 0:
            failures.append(f"expected {key}=0, got {delta[key]}")
    local_sources = delta["action_from_deterministic_rule"] + delta["action_from_heuristic_regex"]
    if local_sources != expected_messages:
        failures.append(
            f"local action-source delta mismatch: expected {expected_messages}, got {local_sources}"
        )
    return failures


def _validate_final_blueprint_single(
    question: str,
    result: dict[str, object],
) -> list[str]:
    expectation = FINAL_BLUEPRINT_EXPECTATIONS[question]
    return _validate_text_expectation(str(result.get("response", "")), expectation)


def _cta_target_action(result: dict[str, object]) -> str | None:
    response_payload = result.get("response_payload")
    if not isinstance(response_payload, dict):
        return None
    cta = response_payload.get("cta")
    if not isinstance(cta, dict):
        return None
    payload = cta.get("payload")
    if not isinstance(payload, dict):
        return None
    target_action = payload.get("target_action")
    return str(target_action) if target_action is not None else None


def _validate_final_blueprint_conversation(
    case: str,
    turns: list[dict[str, object]],
    delta: dict[str, int] | None,
) -> list[str]:
    failures = _validate_zero_gemini_delta(delta, expected_messages=len(turns))
    if len(turns) != 2:
        failures.append(f"expected 2 turns, got {len(turns)}")
        return failures

    first_text = str(turns[0].get("response", ""))
    second_text = str(turns[1].get("response", ""))
    if case == "contextual_fee_followup":
        failures.extend(
            _validate_text_expectation(
                second_text,
                TextExpectation(
                    required=("published total fee", "INR 1,96,000"),
                    forbidden=("Which one did you mean",),
                ),
            )
        )
    elif case == "explicit_unknown_drops_context":
        failures.extend(
            _validate_text_expectation(
                second_text,
                TextExpectation(
                    required=("couldn't find", "BBA", "published catalog"),
                    forbidden=("NMIMS", "INR 1,96,000"),
                ),
            )
        )
    elif case == "specialization_discovery_drops_context":
        failures.extend(
            _validate_text_expectation(
                second_text,
                TextExpectation(
                    required=(
                        "Marketing is offered by 5 published universities",
                        "Amity University Online",
                        "Jain University Online",
                        "Lovely Professional University",
                        "Manipal University Jaipur",
                        "NMIMS Online",
                    ),
                    forbidden=("Which one did you mean",),
                ),
            )
        )
    elif case == "lead_state_isolation":
        failures.extend(
            _validate_text_expectation(
                first_text,
                TextExpectation(required=("What name should our counsellor use?",)),
            )
        )
        target_action = _cta_target_action(turns[0])
        if target_action != "OPEN_LEAD_WIDGET":
            failures.append(
                "callback CTA target_action mismatch: "
                f"expected 'OPEN_LEAD_WIDGET', got {target_action!r}"
            )
        failures.extend(
            _validate_text_expectation(
                second_text,
                TextExpectation(
                    required=("explore online programs",),
                    forbidden=("valid name", "What name should our counsellor use?"),
                ),
            )
        )
    else:  # pragma: no cover - guarded by the declared case table
        failures.append(f"unknown Final Blueprint conversation case: {case}")
    return failures


def _validate_intent_metrics(
    metrics: dict[str, object],
    expected_messages: int,
) -> list[str]:
    try:
        total_messages = int(metrics["total_messages"])
        llm_calls = int(metrics["llm_intent_calls"])
        llm_failures = int(metrics["llm_intent_failures"])
        deterministic = int(metrics["action_from_deterministic_rule"])
        heuristic = int(metrics["action_from_heuristic_regex"])
        gemini = int(metrics["action_from_gemini"])
        rate = float(metrics["llm_intent_call_rate"])
        latency = metrics["llm_intent_latency_ms"]
        if not isinstance(latency, dict):
            raise TypeError("llm_intent_latency_ms is not an object")
        sample_count = int(latency["sample_count"])
    except (KeyError, TypeError, ValueError) as exc:
        return [f"malformed metrics snapshot: {type(exc).__name__}: {exc}"]

    failures: list[str] = []
    if total_messages != expected_messages:
        failures.append(
            f"message count mismatch: expected {expected_messages}, got {total_messages}"
        )
    source_total = deterministic + heuristic + gemini
    if source_total != total_messages:
        failures.append(
            f"action source count mismatch: expected {total_messages}, got {source_total}"
        )
    expected_rate = llm_calls / total_messages if total_messages else 0.0
    if abs(rate - expected_rate) > 1e-12:
        failures.append(f"LLM call rate mismatch: expected {expected_rate}, got {rate}")
    if sample_count != llm_calls:
        failures.append(f"LLM latency sample mismatch: expected {llm_calls}, got {sample_count}")
    if gemini + llm_failures != llm_calls:
        failures.append(
            "Gemini outcome count mismatch: "
            f"calls={llm_calls}, successful_actions={gemini}, failures={llm_failures}"
        )
    if llm_failures:
        failures.append(f"observed {llm_failures} LLM intent failure(s); run is degraded")
    return failures


def _metrics_delta(
    before: dict[str, object],
    after: dict[str, object],
) -> dict[str, int]:
    keys = (
        "total_messages",
        "llm_intent_calls",
        "llm_intent_failures",
        "action_from_deterministic_rule",
        "action_from_heuristic_regex",
        "action_from_gemini",
    )
    delta = {key: int(after.get(key, 0)) - int(before.get(key, 0)) for key in keys}
    before_latency = before.get("llm_intent_latency_ms", {})
    after_latency = after.get("llm_intent_latency_ms", {})
    before_samples = (
        int(before_latency.get("sample_count", 0)) if isinstance(before_latency, dict) else 0
    )
    after_samples = (
        int(after_latency.get("sample_count", 0)) if isinstance(after_latency, dict) else 0
    )
    delta["llm_intent_latency_samples"] = after_samples - before_samples
    return delta


def _validate_tracked_action(
    question: str,
    result: dict[str, object],
    delta: dict[str, int] | None,
) -> list[str]:
    failures: list[str] = []
    response = str(result.get("response", ""))
    if question in DETERMINISTIC_ACTION_CASES:
        failures.extend(_validate_zero_gemini_delta(delta, expected_messages=1))
        if delta is not None and delta["action_from_deterministic_rule"] != 1:
            failures.append(
                "deterministic action source mismatch: "
                f"expected 1, got {delta['action_from_deterministic_rule']}"
            )
        if question == "Show MBA specializations":
            required = ("Business Analytics", "Finance Management", "Marketing")
        else:
            required = (
                "Amity University Online",
                "Jain University Online",
                "Lovely Professional University",
                "Manipal University Jaipur",
                "NMIMS Online",
            )
        failures.extend(
            _validate_text_expectation(
                response,
                TextExpectation(
                    required=required,
                    forbidden=("Which one did you mean",),
                ),
            )
        )
        return failures

    if question in FINAL_BLUEPRINT_ZERO_GEMINI_CASES:
        failures.extend(_validate_zero_gemini_delta(delta, expected_messages=1))
        return failures

    if delta is None:
        failures.append("metrics delta was unavailable; Gemini callback was not proved")
    elif not (
        delta["total_messages"] == 1
        and delta["llm_intent_calls"] == 1
        and delta["llm_intent_failures"] == 0
        and delta["action_from_gemini"] == 1
        and delta["llm_intent_latency_samples"] == 1
    ):
        failures.append(f"Gemini callback metrics were unexpected: {delta}")
    if "What name should our counsellor use?" not in response:
        failures.append("Gemini callback did not reach the lead funnel")
    return failures


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output-dir", type=Path, default=Path.cwd())
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--admin-api-key")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    print(f"\n{'=' * 80}\nDEGREEBABA CHATBOT REGRESSION TEST RUNNER\n{'=' * 80}")
    with RegressionRunner(
        args.base_url,
        timeout_seconds=args.timeout,
        admin_api_key=args.admin_api_key,
    ) as runner:
        runner.run(args.output_dir)
        failed = bool(runner.validation_failures)
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
