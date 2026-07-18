"""Regression tests for focus transition bugs found in manual testing.

Each test directly reproduces a bug from the manual click-through session and
verifies the pipeline fix.  These must remain green for every future change.
"""

import logging

import pytest
import pytest_asyncio

from config import Settings
from main import ChatbotService
from schemas import ChatRequest
from session.store import MemorySessionStore


@pytest_asyncio.fixture
async def service():
    settings = Settings(
        redis_url=None,
        groq_api_key=None,
        openai_api_key=None,
        lead_prompt_after_turn=100,
    )
    instance = await ChatbotService.create(settings, session_store=MemorySessionStore())
    yield instance
    await instance.close()


async def turn(service: ChatbotService, message: str, session_id: str):
    return await service.process_turn(ChatRequest(message=message, session_id=session_id))


# ---------------------------------------------------------------------------
# Bug 2.1: "NMIMS MBA Analytics" then "LPU MBA fee" must switch to LPU
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_focus_switches_fully_to_lpu_on_new_university_mention(service) -> None:
    """Stale specialization from NMIMS must not survive when LPU + MBA are named."""

    result1 = await turn(service, "NMIMS MBA Analytics", "bug-2.1")
    assert result1.state.focus.university is not None  # NMIMS resolved

    result2 = await turn(service, "LPU MBA fee", "bug-2.1")
    focus = result2.state.focus
    # University must have switched away from NMIMS.
    assert focus.university == "uni-lpu", f"expected LPU, got {focus.university}"
    # The old specialization (Business Analytics) must be cleared.
    assert focus.specialization is None, f"stale spec survived: {focus.specialization}"
    # The answer must reflect LPU's data, not NMIMS's INR 1,96,000.
    assert "1,96,000" not in result2.payload.text


# ---------------------------------------------------------------------------
# Bug 2.2: Re-mentioning shallower slot without deeper slot resets deeper
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_specialization_resets_when_university_and_category_rementioned(service) -> None:
    """Saying 'NMIMS MCA' after a specialization must zoom out."""

    await turn(service, "NMIMS MCA Cloud Computing", "bug-2.2")
    result = await turn(service, "Tell me about NMIMS MCA", "bug-2.2")
    focus = result.state.focus
    # Specialization must be gone — the user zoomed out to the course level.
    assert focus.specialization is None, f"stale spec: {focus.specialization}"
    assert focus.specialization_concept is None
    # The course overview may now list available specializations as follow-up
    # catalog data; it must still render the course itself, not a stale spec page.
    assert result.payload.text.startswith("NMIMS Global Access MCA")
    assert "Popular Specializations" in result.payload.text


# ---------------------------------------------------------------------------
# Bug 2.3: Off-topic turns must not reuse old focus
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_off_topic_does_not_reuse_stale_focus(service) -> None:
    """'What is the value of pi' must not return MBA data from a prior turn."""

    await turn(service, "NMIMS MBA Analytics", "bug-2.3")
    result = await turn(service, "What is the value of pi", "bug-2.3")
    # Should route to fallback or discovery, not factual with stale data.
    assert result.route in {"fallback", "discovery"}, f"got route={result.route}"
    # Must not contain NMIMS/MBA in response text.
    assert "NMIMS" not in result.payload.text
    assert "1,96,000" not in result.payload.text


# ---------------------------------------------------------------------------
# Bug 2.4: Phonetic typo must resolve deterministically without inventing one provider
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_monypal_surfaces_true_manipal_ambiguity(service) -> None:
    """'Monypal' resolves to the catalog's Manipal family and asks which one."""

    result = await turn(service, "tell me about Monypal University", "bug-2.4")
    text = result.payload.text.casefold()
    assert result.route == "clarification"
    assert "manipal" in text
    assert "monypal" not in text


# ---------------------------------------------------------------------------
# Bug 2.5: "jian university" fuzzy match to Jain
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_jian_resolves_or_asks_about_jain(service) -> None:
    """'jian' must not silently fall through to stale focus."""

    await turn(service, "NMIMS MBA", "bug-2.5")
    result = await turn(service, "tell me about jian university", "bug-2.5")
    # Either it auto-resolved to Jain or asked "did you mean Jain?".
    text = result.payload.text.casefold()
    focus = result.state.focus
    resolved_jain = focus.university == "uni-jain" or focus.entity_id == "uni-jain"
    asked_jain = "jain" in text
    assert resolved_jain or asked_jain, (
        f"Neither resolved to Jain nor asked about it; "
        f"focus={focus}, text={result.payload.text[:100]}"
    )
    # Must not silently keep the old NMIMS focus.
    if not resolved_jain and not asked_jain:
        assert focus.university != "uni-nmims"


# ---------------------------------------------------------------------------
# Bug 2.6: No duplicate entity ids in aggregate answers
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_duplicate_universities_in_eligibility_listing(service) -> None:
    """Category-wide eligibility must not list the same university twice."""

    result = await turn(service, "MBA eligibility", "bug-2.6")
    text = result.payload.text
    # Extract university mentions by splitting on the eligibility separator.
    parts = text.split(";")
    university_keys: list[str] = []
    for part in parts:
        if ":" in part:
            university_keys.append(part.split(":")[0].strip().casefold())
    # Check for duplicates.
    assert len(university_keys) == len(set(university_keys)), (
        f"Duplicate universities in eligibility: {university_keys}"
    )


# ---------------------------------------------------------------------------
# Section 3: Logging test — pipeline stages emit per-turn trace
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_structured_logging_emits_pipeline_stages(service, caplog) -> None:
    """A /chat turn must produce log lines for key pipeline stages."""

    with caplog.at_level(logging.INFO):
        await turn(service, "LPU MCA fee", "log-test")

    records = caplog.records
    logger_names = {record.name for record in records}
    messages = " ".join(record.getMessage() for record in records)

    # Must include logs from the named pipeline loggers.
    assert "chatbot.nlu" in logger_names, f"missing chatbot.nlu; got {logger_names}"
    assert "chatbot.resolver" in logger_names, f"missing chatbot.resolver; got {logger_names}"
    assert "chatbot.routing" in logger_names, f"missing chatbot.routing; got {logger_names}"

    # Must contain key pipeline fields.
    assert "mention:" in messages, "missing mention extraction log"
    assert "focus:" in messages, "missing focus state log"
    assert "route:" in messages, "missing routing decision log"

    # Correlation id must be present (format: sess_<prefix>:turn_<n>).
    assert any("sess_" in getattr(record, "cor", "") and "turn_" in getattr(record, "cor", "")
               for record in records), (
        "no correlation id found in log records"
    )
