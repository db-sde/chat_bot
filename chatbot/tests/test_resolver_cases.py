import json

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from config import Settings
from data.loader import CatalogStore
from main import ChatbotService, _event_stream, app
from nlu.mention_extractor import tokenize
from schemas import ChatRequest
from session.store import MemorySessionStore
from taxonomy.entity_matcher import EntityMatcher
from taxonomy.index_builder import build_indexes


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


def raw_university_matcher() -> EntityMatcher:
    records = [
        {
            "id": "raw-nmims",
            "_meta": {"page_type": "university"},
            "university_name": "NMIMS Online",
            "university_full_name": "Narsee Monjee Institute of Management Studies Online",
        },
        {
            "id": "raw-ignou",
            "_meta": {"page_type": "university"},
            "university_name": "Indira Gandhi National Open University",
            "university_full_name": "Indira Gandhi National Open University",
        },
        {
            "id": "raw-sikkim-manipal",
            "_meta": {"page_type": "university"},
            "university_name": "Sikkim Manipal University",
            "university_full_name": "Sikkim Manipal University Online",
        },
        {
            "id": "raw-srinivas",
            "_meta": {"page_type": "university"},
            "university_name": "Srinivas Management University",
            "university_full_name": "Srinivas Management University",
        },
    ]
    catalog = CatalogStore(records=records)
    return EntityMatcher(build_indexes(catalog), catalog)


@pytest.mark.asyncio
async def test_case_01_mba_programs_stays_at_category_level(service) -> None:
    result = await turn(service, "tell me about mba programs", "case-01")
    assert result.route == "category"
    assert result.state.focus.category == "mba"
    assert result.state.focus.entity_id is None
    assert "haven't selected one university" in result.payload.text


@pytest.mark.asyncio
async def test_case_02_referential_followup_lists_universities(service) -> None:
    await turn(service, "tell me about mba programs", "case-02")
    result = await turn(
        service,
        "tell me about the uni that provide this program",
        "case-02",
    )
    assert result.route == "category"
    assert result.state.focus.category == "mba"
    assert "NMIMS" in result.payload.text and "Amity" in result.payload.text


@pytest.mark.asyncio
async def test_case_03_which_universities_provide_mba_does_not_pick_one(service) -> None:
    result = await turn(service, "you tell me which uni provide mba program", "case-03")
    assert result.route == "category"
    assert result.state.focus.university is None
    assert result.state.focus.entity_id is None


@pytest.mark.asyncio
async def test_case_04_lpu_curated_alias(service) -> None:
    result = await turn(service, "i want to know about lpu", "case-04")
    assert result.state.focus.entity_id == "uni-lpu"
    assert "Lovely Professional University" in result.payload.text


@pytest.mark.asyncio
async def test_case_05_online_programs_is_discovery(service) -> None:
    result = await turn(service, "tell me about online programs", "case-05")
    assert result.route == "discovery"
    assert {"MBA", "MCA"}.issubset(set(result.payload.suggested_chips))


@pytest.mark.asyncio
async def test_case_06_callback_short_circuits_to_lead_funnel(service) -> None:
    state_before = (await turn(service, "mba", "case-06")).state.focus.model_copy(deep=True)
    result = await turn(service, "i want to talk to someone", "case-06")
    assert result.route == "lead"
    assert result.state.lead.last_asked_field == "name"
    assert result.state.focus == state_before


@pytest.mark.asyncio
async def test_lowercase_name_reply_is_captured_without_stealing_product_queries(service) -> None:
    await turn(service, "call me", "lowercase-lead")
    captured = await turn(service, "aryan kinha", "lowercase-lead")
    assert captured.route == "lead"
    assert captured.state.lead.name == "Aryan Kinha"

    await turn(service, "call me", "product-after-lead")
    product = await turn(service, "career guidance please", "product-after-lead")
    assert product.route != "lead"
    assert product.state.lead.name is None

    await turn(service, "call me", "entity-after-lead")
    entity = await turn(service, "Sikkim", "entity-after-lead")
    assert entity.route != "lead"
    assert entity.state.lead.name is None


@pytest.mark.asyncio
async def test_case_07_nmims_then_mba_resets_university(service) -> None:
    await turn(service, "tell me about nmims", "case-07")
    result = await turn(service, "tell me about mba", "case-07")
    assert result.route == "category"
    assert result.state.focus.university is None
    assert result.state.focus.category == "mba"


@pytest.mark.asyncio
async def test_case_08_mba_marketing_lists_all_provider_candidates(service) -> None:
    result = await turn(service, "tell me about mba marketing", "case-08")
    pending = result.state.pending_clarification
    assert result.route == "clarification"
    assert pending is not None and len(pending.candidates) >= 4
    assert "Marketing at" in result.payload.text


@pytest.mark.asyncio
async def test_case_09_nmims_mba_fee_persists_exact_entity(service) -> None:
    await turn(service, "tell me about nmims mba", "case-09")
    result = await turn(service, "what is the fee?", "case-09")
    assert result.route == "factual"
    assert result.state.focus.entity_id == "course-nmims-mba"
    assert "INR 1,96,000" in result.payload.text


@pytest.mark.asyncio
async def test_case_10_compare_mba_and_mca_is_category_level(service) -> None:
    result = await turn(service, "compare mba and mca", "case-10")
    assert result.route == "comparison"
    assert "MBA:" in result.payload.text and "MCA:" in result.payload.text
    assert result.state.focus.entity_id is None


@pytest.mark.asyncio
async def test_case_11_null_or_missing_placement_is_graceful(service) -> None:
    await turn(service, "nmims mba", "case-11")
    result = await turn(service, "what placement support is available?", "case-11")
    assert result.route == "factual"
    assert "don't have published placement" in result.payload.text


@pytest.mark.asyncio
async def test_case_12_db_answerable_fact_is_deterministic(service) -> None:
    await turn(service, "nmims mba", "case-12")
    result = await turn(service, "what is the duration?", "case-12")
    assert result.route == "factual"
    assert result.synthesis_prompt is None
    assert result.payload.text == "The published duration for Online MBA is 2 Years."


def test_case_13_lpu_alias_table_has_layer_one_priority(service) -> None:
    candidate = service.matcher.resolve_slot(tokenize("lpu"), "university")[0]
    assert candidate.entity_id == "uni-lpu"
    assert candidate.layer == 1 and candidate.confidence == "HIGH"


def test_case_14_nmims_is_auto_generated_acronym_without_alias_enrichment() -> None:
    candidates = raw_university_matcher().resolve_slot(tokenize("nmims"), "university")
    assert [(item.entity_id, item.layer) for item in candidates] == [("raw-nmims", 2)]


def test_case_15_amity_partial_token_containment(service) -> None:
    candidates = service.matcher.resolve_slot(tokenize("amity"), "university")
    assert [item.entity_id for item in candidates] == ["uni-amity"]


def test_case_16_manipal_bigram_unique_and_unigram_ambiguous(service) -> None:
    unique = service.matcher.resolve_slot(tokenize("manipal jaipur"), "university")
    ambiguous = service.matcher.resolve_slot(tokenize("manipal"), "university")
    assert [item.entity_id for item in unique] == ["uni-manipal-jaipur"]
    assert {item.entity_id for item in ambiguous} == {
        "uni-manipal-jaipur",
        "uni-sikkim-manipal",
    }


def test_case_17_ignou_is_auto_generated_acronym_without_alias_enrichment() -> None:
    candidates = raw_university_matcher().resolve_slot(tokenize("ignou"), "university")
    assert [(item.entity_id, item.layer) for item in candidates] == [("raw-ignou", 2)]


def test_case_18_mba_alone_is_a_category_pseudo_entity(service) -> None:
    candidates = service.matcher.resolve_slot(tokenize("mba"), "course")
    assert [item.entity_id for item in candidates] == ["category:mba"]


@pytest.mark.asyncio
@pytest.mark.parametrize("typo", ["mbaa", "mabb"])
async def test_case_19_mba_typos_require_medium_confirmation(service, typo: str) -> None:
    result = await turn(service, typo, f"case-19-{typo}")
    candidate = service.matcher.resolve_slot(tokenize(typo), "course")[0]
    assert candidate.confidence == "MEDIUM"
    assert result.route == "clarification"
    assert result.payload.text.startswith("Did you mean MBA?")


def test_case_20_analytics_token_resolves_business_analytics(service) -> None:
    candidates = service.matcher.resolve_slot(tokenize("analytics"), "specialization")
    assert len(candidates) == 1
    assert candidates[0].canonical_name == "Business Analytics"


def test_case_21_hr_uses_curated_specialization_alias(service) -> None:
    candidate = service.matcher.resolve_slot(tokenize("hr"), "specialization")[0]
    assert candidate.entity_id == "spec-lpu-mba-human-resource-management"
    assert candidate.layer == 1


def test_case_22_finance_token_resolves_finance_management(service) -> None:
    candidates = service.matcher.resolve_slot(tokenize("finance"), "specialization")
    assert len(candidates) == 1
    assert candidates[0].canonical_name == "Finance Management"


def test_case_23_smu_acronym_collision_preserves_both_candidates() -> None:
    candidates = raw_university_matcher().resolve_slot(tokenize("smu"), "university")
    assert {item.entity_id for item in candidates} == {
        "raw-sikkim-manipal",
        "raw-srinivas",
    }


def test_case_24_jain_token_resolves_online_university(service) -> None:
    candidates = service.matcher.resolve_slot(tokenize("jain"), "university")
    assert [item.entity_id for item in candidates] == ["uni-jain"]


@pytest.mark.asyncio
async def test_case_25_marketing_mba_keeps_provider_ambiguity(service) -> None:
    result = await turn(service, "marketing mba", "case-25")
    assert result.route == "clarification"
    assert result.state.pending_clarification is not None
    assert len(result.state.pending_clarification.candidates) == 5


@pytest.mark.asyncio
async def test_case_26_all_three_slots_resolve_independently(service) -> None:
    result = await turn(service, "lpu mba markting", "case-26")
    assert result.route == "factual"
    assert result.state.focus.university == "uni-lpu"
    assert result.state.focus.category == "mba"
    assert result.state.focus.specialization == "Marketing"
    assert result.state.focus.entity_id == "spec-lpu-mba-marketing"


@pytest.mark.asyncio
async def test_pending_clarification_resolves_alias_and_ordinal_directly(service) -> None:
    await turn(service, "mba marketing", "pending-alias")
    alias = await turn(service, "nmims", "pending-alias")
    assert alias.state.pending_clarification is None
    assert alias.state.focus.entity_id == "spec-nmims-mba-marketing"

    first = await turn(service, "manipal", "pending-ordinal")
    offered_first = first.state.pending_clarification.candidates[0]
    ordinal = await turn(service, "the first one", "pending-ordinal")
    assert ordinal.state.pending_clarification is None
    assert ordinal.state.focus.entity_id == offered_first


@pytest.mark.asyncio
async def test_uncertain_topic_switch_cannot_reintroduce_stale_focus(service) -> None:
    await turn(service, "nmims", "medium-switch")
    await turn(service, "mbaa", "medium-switch")
    confirmed = await turn(service, "yes please", "medium-switch")
    assert confirmed.route == "category"
    assert confirmed.state.focus.university is None
    assert confirmed.state.focus.category == "mba"

    await turn(service, "mba", "ambiguous-switch")
    await turn(service, "manipal", "ambiguous-switch")
    selected = await turn(service, "the first one", "ambiguous-switch")
    assert selected.state.focus.category is None
    assert selected.state.focus.entity_id.startswith("uni-")


@pytest.mark.asyncio
async def test_generic_knowledge_overrides_focus_but_entity_naac_stays_factual(service) -> None:
    await turn(service, "lpu", "knowledge-scope")
    generic = await turn(service, "what is NAAC?", "knowledge-scope")
    assert generic.route == "knowledge"
    assert "National Assessment and Accreditation Council" in generic.payload.text

    entity = await turn(service, "what is the NAAC grade of LPU?", "knowledge-scope")
    assert entity.route == "factual"
    assert "NAAC grade A++" in entity.payload.text


@pytest.mark.asyncio
async def test_publisher_specialization_category_is_derived_from_document_title() -> None:
    catalog = CatalogStore(
        records=[
            {
                "id": "raw-spec",
                "_meta": {
                    "page_type": "specialization",
                    "document_title": "Chandigarh Online MBA Banking Specialization Page",
                },
                "spec_name": "Banking & Insurance",
                "university_name": "Chandigarh University",
                "linked_university": None,
                "linked_course": None,
            }
        ]
    )
    assert catalog.get_metadata("raw-spec").category == "mba"


@pytest.mark.asyncio
async def test_unique_university_specialization_join_works_without_category_or_links() -> None:
    catalog = CatalogStore(
        records=[
            {
                "_meta": {"page_type": "university"},
                "university_name": "Lovely Professional University",
                "university_full_name": "Lovely Professional University Online",
            },
            {
                "_meta": {"page_type": "university"},
                "university_name": "Chandigarh University",
                "university_full_name": "Chandigarh University Online",
            },
            {
                "_meta": {"page_type": "specialization"},
                "spec_name": "Banking & Insurance",
                "university_name": "Lovely Professional University",
                "linked_university": None,
                "linked_course": None,
                "total_fee": "INR 1,60,000",
            },
            {
                "_meta": {"page_type": "specialization"},
                "spec_name": "Banking & Insurance",
                "university_name": "Chandigarh University",
                "linked_university": None,
                "linked_course": None,
                "total_fee": "INR 1,65,000",
            },
        ]
    )
    service = await ChatbotService.create(
        Settings(redis_url=None, lead_prompt_after_turn=100),
        catalog=catalog,
        session_store=MemorySessionStore(),
    )
    result = await turn(
        service,
        "What is the fee for Banking and Insurance at Chandigarh University?",
        "native-join",
    )
    metadata = service.catalog.get_metadata(result.state.focus.entity_id)
    assert metadata is not None and metadata.university_name == "Chandigarh University"
    assert "INR 1,65,000" in result.payload.text
    await service.close()


@pytest.mark.asyncio
async def test_manual_reindex_failure_retains_current_catalog() -> None:
    settings = Settings(
        redis_url=None,
        catalog_path="/definitely/missing/catalog.json",
        lead_prompt_after_turn=100,
    )
    current = await CatalogStore.create(catalog_path=None, settings=Settings(redis_url=None))
    service = await ChatbotService.create(
        settings,
        catalog=current,
        session_store=MemorySessionStore(),
    )
    original_ids = set(service.catalog.entities)
    with pytest.raises(RuntimeError, match="existing index retained"):
        await service.reindex()
    assert set(service.catalog.entities) == original_ids
    await service.close()


class FakeStreamingLLM:
    intent_configured = False
    synthesis_configured = True

    async def stream_synthesis(self, prompt: str):
        assert "Catalog facts" in prompt
        yield "Grounded"
        yield " answer"

    async def health(self):
        return {"status": "ok", "providers": {"fake": "ok"}}


@pytest.mark.asyncio
async def test_llm_backed_sse_emits_real_deltas_before_final_payload() -> None:
    service = await ChatbotService.create(
        Settings(redis_url=None, lead_prompt_after_turn=100),
        session_store=MemorySessionStore(),
        llm=FakeStreamingLLM(),
    )
    result = await turn(service, "tell me about lpu", "stream")
    events = [chunk async for chunk in _event_stream(service, result)]
    decoded = [chunk.decode() for chunk in events]
    assert decoded[0].startswith("event: token") and '"token":"Grounded"' in decoded[0]
    assert decoded[1].startswith("event: token") and '"token":" answer"' in decoded[1]
    assert decoded[2].startswith("event: response")
    await service.close()


@pytest.mark.asyncio
async def test_slow_stream_cannot_overwrite_a_newer_session_turn() -> None:
    service = await ChatbotService.create(
        Settings(redis_url=None, lead_prompt_after_turn=100),
        session_store=MemorySessionStore(),
        llm=FakeStreamingLLM(),
    )
    broad = await turn(service, "tell me about lpu", "concurrent-stream")
    newer = await turn(service, "tell me about mba", "concurrent-stream")
    assert newer.state.focus.category == "mba"
    _ = [chunk async for chunk in _event_stream(service, broad)]
    persisted = await service.session_store.get_or_create("concurrent-stream")
    assert persisted.turn_count == 2
    assert persisted.focus.category == "mba" and persisted.focus.university is None
    await service.close()


def test_http_endpoints_serve_sse_health_and_reindex() -> None:
    with TestClient(app) as client:
        chat = client.post("/chat", json={"message": "mba", "session_id": "http"})
        assert chat.status_code == 200
        assert chat.headers["content-type"].startswith("text/event-stream")
        assert "event: response" in chat.text
        data_line = next(line for line in chat.text.splitlines() if line.startswith("data: "))
        payload = json.loads(data_line.removeprefix("data: "))
        assert payload["session_id"] == "http" and payload["suggested_chips"]

        health = client.get("/health")
        assert health.status_code == 200
        assert {"redis", "database", "llm"} <= set(health.json()["dependencies"])

        reindex = client.post("/admin/reindex")
        assert reindex.status_code == 200
        assert reindex.json()["entity_count"] >= 24
