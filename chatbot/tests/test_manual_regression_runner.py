from __future__ import annotations

import json

import requests

from tests.manual.regression_runner import (
    RegressionRunner,
    _validate_final_blueprint_conversation,
    _validate_intent_metrics,
    _validate_tracked_action,
    extract_response_payload,
)


def _response(body: str, *, status: int = 200) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response.encoding = "utf-8"
    response._content = body.encode()
    return response


def _zero_delta(messages: int = 1) -> dict[str, int]:
    return {
        "total_messages": messages,
        "llm_intent_calls": 0,
        "llm_intent_failures": 0,
        "action_from_deterministic_rule": messages,
        "action_from_heuristic_regex": 0,
        "action_from_gemini": 0,
        "llm_intent_latency_samples": 0,
    }


def _metrics(messages: int = 1) -> dict[str, object]:
    return {
        "total_messages": messages,
        "llm_intent_calls": 0,
        "llm_intent_call_rate": 0.0,
        "llm_intent_failures": 0,
        "action_from_deterministic_rule": messages,
        "action_from_heuristic_regex": 0,
        "action_from_gemini": 0,
        "llm_intent_latency_ms": {"sample_count": 0, "p50": None, "p95": None},
    }


def test_extract_response_payload_keeps_final_cta_after_streamed_tokens() -> None:
    final = {
        "session_id": "session-1",
        "text": "Lead form opened.",
        "suggested_chips": [],
        "cta": {
            "label": "Talk to a counsellor",
            "action": "lead_capture",
            "payload": {"target_action": "OPEN_LEAD_WIDGET"},
        },
    }
    response = _response(
        'event: token\ndata: {"session_id":"session-1","token":"Lead "}\n\n'
        f"event: response\ndata: {json.dumps(final)}\n\n"
    )

    assert extract_response_payload(response) == final


def test_gemini_callback_timeout_is_reported_instead_of_raised() -> None:
    result = {"response": "I need a little more detail."}
    delta = {
        **_zero_delta(),
        "llm_intent_calls": 1,
        "llm_intent_failures": 1,
        "action_from_deterministic_rule": 0,
        "action_from_heuristic_regex": 1,
        "llm_intent_latency_samples": 1,
    }

    failures = _validate_tracked_action("I'm confused", result, delta)

    assert any("metrics were unexpected" in failure for failure in failures)
    assert any("did not reach the lead funnel" in failure for failure in failures)


def test_lead_isolation_acceptance_requires_full_cta_payload() -> None:
    turns = [
        {
            "response": "Absolutely. What name should our counsellor use?",
            "response_payload": {
                "text": "Absolutely. What name should our counsellor use?",
                "cta": {
                    "payload": {"target_action": "OPEN_LEAD_WIDGET"},
                },
            },
        },
        {
            "response": "I can help you explore online programs.",
            "response_payload": {"text": "I can help you explore online programs."},
        },
    ]

    assert (
        _validate_final_blueprint_conversation(
            "lead_state_isolation",
            turns,
            _zero_delta(messages=2),
        )
        == []
    )


def test_metrics_failures_make_the_run_degraded() -> None:
    metrics = {
        **_metrics(),
        "llm_intent_calls": 1,
        "llm_intent_call_rate": 1.0,
        "llm_intent_failures": 1,
        "action_from_deterministic_rule": 0,
        "action_from_heuristic_regex": 1,
        "llm_intent_latency_ms": {"sample_count": 1, "p50": 1400.0, "p95": 1400.0},
    }

    failures = _validate_intent_metrics(metrics, expected_messages=1)

    assert failures == ["observed 1 LLM intent failure(s); run is degraded"]


def test_report_is_saved_before_validation_failure_exits(
    tmp_path,
    monkeypatch,
) -> None:
    runner = RegressionRunner("http://example.test")
    health = _response('{"status":"ok"}')
    monkeypatch.setattr(runner.http, "get", lambda *_args, **_kwargs: health)
    monkeypatch.setattr(runner, "reset_intent_metrics", lambda: None)
    monkeypatch.setattr(runner, "get_intent_metrics", _metrics)

    def fake_single_turn() -> list[dict[str, object]]:
        result: dict[str, object] = {
            "suite": "synthetic",
            "question": "synthetic",
            "status": 200,
            "latency_ms": 1,
            "response": "synthetic answer",
            "response_payload": {"text": "synthetic answer"},
        }
        runner._record_failures(
            "single_turn",
            "synthetic",
            ["synthetic failure"],
            result=result,
        )
        return [result]

    monkeypatch.setattr(runner, "run_single_turn_tests", fake_single_turn)
    monkeypatch.setattr(runner, "run_multi_turn_tests", lambda: [])

    path = runner.run(tmp_path)
    report = json.loads(path.read_text())
    runner.close()

    assert report["passed"] is False
    assert report["summary"]["validation_failure_count"] == 1
    assert report["validation_failures"][0]["message"] == "synthetic failure"
