import pytest

from nlu.callback_detector import is_callback_request


@pytest.mark.parametrize(
    "message",
    [
        "Call me",
        "I want to talk to someone",
        "I want to talk to an advisor",
        "Talk to an advisor",
        "Can a counsellor help me?",
        "Could a counselor help me with admissions?",
        "I need counselling",
        "I am looking for admission counseling",
        "I need admission guidance",
        "Admission guidance please",
        "Please connect me with a person",
        "Request a callback",
    ],
)
def test_explicit_human_help_requests_trigger_callback(message: str) -> None:
    assert is_callback_request(message)


@pytest.mark.parametrize(
    "message",
    [
        "Don't call me",
        "Do not call me please",
        "No callback please",
        "I don't want a callback",
        "Never contact me",
        "No calls, just show me the fees",
    ],
)
def test_negated_callback_requests_do_not_trigger(message: str) -> None:
    assert not is_callback_request(message)


@pytest.mark.parametrize(
    "message",
    [
        "Career guidance please",
        "What admission guidance is available?",
        "Can you help me choose an MBA?",
        "Tell me about university counselling services",
        "Does NMIMS offer career counseling?",
    ],
)
def test_catalog_or_decision_help_is_not_misrouted_to_callback(message: str) -> None:
    assert not is_callback_request(message)
