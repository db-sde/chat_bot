from __future__ import annotations

import pytest
import pytest_asyncio

from config import Settings
from main import ChatbotService
from nlu.intent import Intent, heuristic_intent
from nlu.mention_extractor import tokenize
from schemas import ChatRequest
from session.store import MemorySessionStore


class ExplodingIntentLLM:
    intent_configured = True
    synthesis_configured = False

    def __init__(self) -> None:
        self.intent_calls = 0

    async def classify_intent(self, message: str) -> str:
        self.intent_calls += 1
        raise AssertionError(f"structured turn unexpectedly called intent LLM: {message}")

    async def health(self):
        return {"status": "ok", "providers": {"fake": "ok"}}


@pytest_asyncio.fixture
async def deterministic_service():
    llm = ExplodingIntentLLM()
    service = await ChatbotService.create(
        Settings(
            redis_url=None,
            groq_api_key=None,
            openai_api_key=None,
            lead_prompt_after_turn=100,
        ),
        session_store=MemorySessionStore(),
        llm=llm,
    )
    yield service, llm
    await service.close()


async def turn(service: ChatbotService, message: str, session_id: str):
    return await service.process_turn(ChatRequest(message=message, session_id=session_id))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("message", "missing"),
    [
        ("Tell me about IIT Bombay Online MBA", "IIT Bombay"),
        ("Tell me about Harvard MBA", "Harvard"),
        ("Tell me about Oxford Online MBA", "Oxford"),
        ("Tell me about MBA in Artificial Intelligence", "Artificial Intelligence"),
    ],
)
async def test_mixed_known_unknown_acknowledges_missing_qualifier(
    deterministic_service,
    message: str,
    missing: str,
) -> None:
    service, llm = deterministic_service

    result = await turn(service, message, f"partial-{missing}")

    assert result.route == "category"
    assert f"couldn't find {missing}" in result.payload.text
    assert "MBA is available" in result.payload.text
    assert result.synthesis_prompt is None
    assert llm.intent_calls == 0


@pytest.mark.asyncio
async def test_pure_negative_still_uses_existing_no_match_path(deterministic_service) -> None:
    service, llm = deterministic_service

    result = await turn(service, "Tell me about XYZ University", "pure-negative")

    assert result.route == "fallback"
    assert "couldn't confidently match" in result.payload.text
    assert "I did match" not in result.payload.text
    assert llm.intent_calls == 0


@pytest.mark.asyncio
async def test_mixed_comparison_reports_unknown_and_summarizes_known_university(
    deterministic_service,
) -> None:
    service, llm = deterministic_service

    result = await turn(service, "Compare Harvard and LPU", "partial-comparison")

    assert result.route == "comparison"
    assert result.state.pending_clarification is None
    assert "couldn't find Harvard" in result.payload.text
    assert "Lovely Professional University" in result.payload.text
    assert "Which two course categories" not in result.payload.text
    assert llm.intent_calls == 0


@pytest.mark.asyncio
async def test_structured_category_offer_is_deterministic(deterministic_service) -> None:
    service, llm = deterministic_service

    first = await turn(service, "Which universities offer MCA?", "mca-one")
    second = await turn(service, "Which universities offer MCA?", "mca-two")

    assert first.route == second.route == "category"
    assert first.payload.text == second.payload.text
    assert "MCA is available" in first.payload.text
    assert llm.intent_calls == 0


@pytest.mark.asyncio
async def test_one_letter_article_is_not_an_amity_acronym(deterministic_service) -> None:
    service, _ = deterministic_service
    assert service.matcher.resolve_slot(tokenize("a"), "university") == []


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Which university is better, LPU or NMIMS?", Intent.COMPARISON),
        ("Which Online MBA is best for Marketing?", Intent.ADVISORY),
        ("Which specialization has the best career opportunities?", Intent.ADVISORY),
        ("I have a budget of 1.8 lakh. Which MBA should I choose?", Intent.ADVISORY),
    ],
)
def test_structured_intents_are_local(message: str, expected: Intent) -> None:
    assert heuristic_intent(message) is expected
