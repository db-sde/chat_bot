import json
from pathlib import Path

import pytest

from config import Settings
from data.loader import CatalogStore
from main import ChatbotService
from nlu.mention_extractor import extract_mentions
from resolver.focus_updater import FocusUpdateResult, update_focus
from routing.comparison_handler import handle_comparison
from schemas import ChatRequest
from session.state import ConversationState
from session.store import MemorySessionStore
from taxonomy.entity_matcher import EntityMatcher
from taxonomy.index_builder import TaxonomyIndexes, build_indexes


@pytest.fixture(scope="module")
def comparison_catalog() -> tuple[CatalogStore, TaxonomyIndexes, EntityMatcher]:
    path = Path(__file__).parents[1] / "data" / "catalog.sample.json"
    records = json.loads(path.read_text(encoding="utf-8"))["entities"]
    catalog = CatalogStore(records=records)
    indexes = build_indexes(catalog)
    return catalog, indexes, EntityMatcher(indexes, catalog)


def comparison_update(
    message: str,
    dependencies: tuple[CatalogStore, TaxonomyIndexes, EntityMatcher],
) -> FocusUpdateResult:
    catalog, indexes, matcher = dependencies
    mentions = extract_mentions(message, matcher)
    return update_focus(
        ConversationState(session_id="comparison-test"),
        mentions,
        intent="comparison",
        catalog=catalog,
        indexes=indexes,
        category_index=indexes.category_index,
    )


def test_separate_university_spans_are_comparison_operands(comparison_catalog) -> None:
    update = comparison_update("Compare LPU and NMIMS", comparison_catalog)

    assert update.ambiguous == {}
    assert [item.entity_id for item in update.comparison_universities] == [
        "uni-lpu",
        "uni-nmims",
    ]
    assert update.comparison_entity_ids == ()


def test_one_ambiguous_span_does_not_absorb_resolved_operand(comparison_catalog) -> None:
    update = comparison_update("Compare SMU and LPU", comparison_catalog)

    assert {item.entity_id for item in update.ambiguous["university"]} == {
        "uni-sikkim-manipal",
        "uni-srinivas-management",
    }
    assert [item.entity_id for item in update.comparison_universities] == ["uni-lpu"]
    assert [item.entity_id for item in update.resolved["university"]] == ["uni-lpu"]


@pytest.mark.parametrize(
    ("message", "expected_ids"),
    [
        (
            "Compare MBA fees of LPU and NMIMS",
            ("course-lpu-mba", "course-nmims-mba"),
        ),
        (
            "Compare LPU MBA and NMIMS MBA",
            ("course-lpu-mba", "course-nmims-mba"),
        ),
        (
            "Compare Amity MBA and Jain MBA",
            ("course-amity-mba", "course-jain-mba"),
        ),
    ],
)
def test_common_category_resolves_one_course_per_university(
    comparison_catalog,
    message: str,
    expected_ids: tuple[str, str],
) -> None:
    update = comparison_update(message, comparison_catalog)

    assert update.ambiguous == {}
    assert update.comparison_common_category == "mba"
    assert update.comparison_entity_ids == expected_ids


def test_category_comparison_contract_is_preserved(comparison_catalog) -> None:
    update = comparison_update("Compare MBA and MCA", comparison_catalog)

    assert update.ambiguous == {}
    assert update.comparison_categories == ("mba", "mca")
    assert update.focus.entity_id is None


def test_specialization_provider_records_form_named_family_operands(
    comparison_catalog,
) -> None:
    update = comparison_update("Compare Marketing and Finance", comparison_catalog)

    assert update.ambiguous == {}
    assert len(update.comparison_specializations) == 2
    assert {
        item.canonical_name for item in update.comparison_specializations[0]
    } == {"Marketing"}
    assert {
        item.canonical_name for item in update.comparison_specializations[1]
    } == {"Finance Management"}


@pytest.mark.asyncio
async def test_handler_renders_university_operands(comparison_catalog) -> None:
    catalog, indexes, _ = comparison_catalog
    update = comparison_update("Compare LPU and NMIMS", comparison_catalog)

    payload = await handle_comparison(
        catalog=catalog,
        category_index=indexes.category_index,
        universities=update.comparison_universities,
    )

    assert "Lovely Professional University Online" in payload.text
    assert "Narsee Monjee Institute of Management Studies Online" in payload.text
    assert "NAAC A++" in payload.text


@pytest.mark.asyncio
async def test_handler_renders_concrete_mba_fee_comparison(comparison_catalog) -> None:
    catalog, indexes, _ = comparison_catalog
    update = comparison_update("Compare MBA fees of LPU and NMIMS", comparison_catalog)

    payload = await handle_comparison(
        catalog=catalog,
        category_index=indexes.category_index,
        universities=update.comparison_universities,
        entity_ids=update.comparison_entity_ids,
        common_category=update.comparison_common_category,
    )

    assert "Lovely Professional University" in payload.text
    assert "NMIMS Online" in payload.text
    assert "INR 1,60,000" in payload.text
    assert "INR 1,96,000" in payload.text


@pytest.mark.asyncio
async def test_handler_renders_specialization_family_aggregate(comparison_catalog) -> None:
    catalog, indexes, _ = comparison_catalog
    update = comparison_update("Compare Marketing and Finance", comparison_catalog)

    payload = await handle_comparison(
        catalog=catalog,
        category_index=indexes.category_index,
        specializations=update.comparison_specializations,
    )

    assert "Marketing: 5 provider options" in payload.text
    assert "Finance Management: 1 provider option" in payload.text


@pytest.mark.asyncio
async def test_handler_keeps_category_comparison(comparison_catalog) -> None:
    catalog, indexes, _ = comparison_catalog
    update = comparison_update("Compare MBA and MCA", comparison_catalog)

    payload = await handle_comparison(
        catalog=catalog,
        category_index=indexes.category_index,
        categories=update.comparison_categories,
    )

    assert "MBA:" in payload.text
    assert "MCA:" in payload.text


async def _service() -> ChatbotService:
    return await ChatbotService.create(
        Settings(redis_url=None, lead_prompt_after_turn=100),
        session_store=MemorySessionStore(),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("message", "first", "second"),
    [
        ("Compare LPU and NMIMS", "Lovely Professional University", "Narsee Monjee"),
        ("Compare MBA fees of LPU and NMIMS", "INR 1,60,000", "INR 1,96,000"),
        ("Compare LPU MBA and NMIMS MBA", "INR 1,60,000", "INR 1,96,000"),
        ("Compare Amity MBA and Jain MBA", "Amity University", "Jain University"),
    ],
)
async def test_named_comparisons_are_wired_end_to_end(
    message: str,
    first: str,
    second: str,
) -> None:
    service = await _service()
    try:
        result = await service.process_turn(ChatRequest(message=message, session_id=message))
    finally:
        await service.close()

    assert result.route == "comparison"
    assert result.state.pending_clarification is None
    assert first in result.payload.text and second in result.payload.text
    assert "Which one did you mean" not in result.payload.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    [
        "Compare Harvard and LPU",
        "LPU vs Harvard",
        "Difference between LPU and Harvard",
        "Which is better, LPU or Harvard?",
    ],
)
async def test_mixed_comparison_syntaxes_acknowledge_unknown_operand(message: str) -> None:
    service = await _service()
    try:
        result = await service.process_turn(ChatRequest(message=message, session_id=message))
    finally:
        await service.close()

    assert result.route == "comparison"
    assert "couldn't find Harvard" in result.payload.text
    assert "Lovely Professional University" in result.payload.text
    assert "Which two course categories" not in result.payload.text


@pytest.mark.asyncio
async def test_ambiguous_comparison_resumes_after_operand_selection() -> None:
    service = await _service()
    try:
        first = await service.process_turn(
            ChatRequest(message="Compare SMU and LPU", session_id="smu-comparison")
        )
        second = await service.process_turn(
            ChatRequest(message="the first one", session_id="smu-comparison")
        )
    finally:
        await service.close()

    assert first.route == "clarification"
    assert second.route == "comparison"
    assert "Sikkim Manipal University" in second.payload.text
    assert "Lovely Professional University" in second.payload.text


@pytest.mark.asyncio
@pytest.mark.parametrize("message", ["Compare LPU", "Compare LPU and MBA"])
async def test_incomplete_comparison_asks_for_second_university(message: str) -> None:
    service = await _service()
    try:
        result = await service.process_turn(ChatRequest(message=message, session_id=message))
    finally:
        await service.close()

    assert result.route == "comparison"
    assert "Which other university" in result.payload.text
    assert "published information I can provide" not in result.payload.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    ["Tell me about affordable Online MBA", "Tell me about distance Online MBA"],
)
async def test_catalog_modifiers_are_not_reported_as_unknown_entities(message: str) -> None:
    service = await _service()
    try:
        result = await service.process_turn(ChatRequest(message=message, session_id=message))
    finally:
        await service.close()

    assert result.route == "category"
    assert "couldn't find" not in result.payload.text


@pytest.mark.asyncio
async def test_preposition_is_not_in_unknown_comparison_operand() -> None:
    service = await _service()
    try:
        result = await service.process_turn(
            ChatRequest(
                message="Compare fees for Harvard and LPU",
                session_id="comparison-preposition",
            )
        )
    finally:
        await service.close()

    assert "couldn't find Harvard" in result.payload.text
    assert "couldn't find FOR Harvard" not in result.payload.text
