from __future__ import annotations

import pytest
import pytest_asyncio

from config import Settings
from data.loader import CatalogStore
from nlu.mention_extractor import extract_mentions, tokenize
from taxonomy.entity_matcher import EntityMatcher
from taxonomy.fuzzy_bucket import build_fuzzy_buckets, search_bucket
from taxonomy.index_builder import build_indexes, normalize_category


def _university_record(entity_id: str, name: str) -> dict[str, object]:
    return {
        "id": entity_id,
        "_meta": {"page_type": "university"},
        "university_name": name,
        "university_full_name": name,
        "duration": "2 Years",
        "naac_grade": "A+",
        "ugc_approved": "Approved",
        "starting_fee": "INR 1,00,000",
    }


def _course_record(entity_id: str, university: str) -> dict[str, object]:
    return {
        "id": entity_id,
        "_meta": {"page_type": "course"},
        "program_name": "Online MBA",
        "university_name": university,
        "category": "mba",
        "duration": "2 Years",
        "total_fee": "INR 1,00,000",
        "eligibility_summary": "Graduation",
    }


@pytest_asyncio.fixture
async def sample_matcher() -> EntityMatcher:
    catalog = await CatalogStore.create(
        settings=Settings(redis_url=None, catalog_url=None, catalog_path=None)
    )
    return EntityMatcher(build_indexes(catalog), catalog)


def test_catalog_fields_generate_attribute_index() -> None:
    catalog = CatalogStore(
        records=[
            _university_record("delta", "Delta Knowledge Institute"),
            _course_record("delta-mba", "Delta Knowledge Institute"),
        ]
    )
    indexes = build_indexes(catalog)

    assert indexes.attribute_index["fee"] == frozenset({"fee"})
    assert indexes.attribute_index["fees"] == frozenset({"fee"})
    assert indexes.attribute_index["duration"] == frozenset({"duration"})
    assert indexes.attribute_index["naac"] == frozenset({"naac"})
    assert indexes.attribute_index["approvals"] == frozenset({"approval"})
    assert "program" not in indexes.attribute_index


def test_generated_acronym_participates_in_fuzzy_matching_with_provenance() -> None:
    catalog = CatalogStore(records=[_university_record("delta", "Delta Knowledge Institute")])
    matcher = EntityMatcher(build_indexes(catalog), catalog)

    acronym = matcher.resolve_slot(tokenize("dki"), "university")
    typo = matcher.resolve_slot(tokenize("dkii"), "university")

    assert [(item.entity_id, item.method, item.matched_catalog_term) for item in acronym] == [
        ("delta", "acronym", "dki")
    ]
    assert [(item.entity_id, item.method, item.matched_catalog_term) for item in typo] == [
        ("delta", "rapidfuzz", "dki")
    ]
    assert typo[0].confidence == "MEDIUM"


def test_monypal_uses_guarded_two_edit_match_without_lowering_global_cutoff() -> None:
    catalog = CatalogStore(
        records=[
            _university_record("north", "Manipal North University"),
            _university_record("south", "Manipal South University"),
        ]
    )
    matcher = EntityMatcher(build_indexes(catalog), catalog)

    candidates = matcher.resolve_slot(tokenize("monypal"), "university")

    assert {item.entity_id for item in candidates} == {"north", "south"}
    assert {item.confidence for item in candidates} == {"MEDIUM"}
    assert {item.method for item in candidates} == {"rapidfuzz"}
    assert {item.matched_catalog_term for item in candidates} == {"manipal"}
    assert all(item.score is not None and item.score < 80 for item in candidates)


def test_fuzzy_matching_rejects_unsafe_one_character_query() -> None:
    catalog = CatalogStore(records=[_university_record("alpha", "Alpha University")])
    matcher = EntityMatcher(build_indexes(catalog), catalog)

    assert matcher.resolve_slot(tokenize("a"), "university") == []


def test_adaptive_fuzzy_matching_rejects_a_near_tied_two_edit_guess() -> None:
    buckets = build_fuzzy_buckets(
        {
            "manipal": {"first"},
            "munipal": {"second"},
        }
    )

    assert search_bucket("monypal", buckets) == ()


def test_shared_catalog_brand_tokens_generate_ambiguity_without_name_tables() -> None:
    catalog = CatalogStore(
        records=[
            _university_record("north", "North Acme University"),
            _university_record("south", "South Acme Institute"),
        ]
    )
    indexes = build_indexes(catalog)

    assert indexes.ambiguity_clusters["university"]["acme"] == frozenset(
        {"north", "south"}
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Online MBA", "mba"),
        ("Master of Business Administration", "mba"),
        ("Masters of Computer Applications", "mca"),
        ("Online B.Com", "bcom"),
        ("Online B.Tech", "btech"),
    ],
)
def test_category_derivation_is_generic_and_not_code_enumerated(
    raw: str,
    expected: str,
) -> None:
    assert normalize_category(raw) == expected


def test_spelled_out_degree_resolves_through_generated_initialism() -> None:
    catalog = CatalogStore(
        records=[
            _university_record("delta", "Delta Knowledge Institute"),
            _course_record("delta-mba", "Delta Knowledge Institute"),
        ]
    )
    matcher = EntityMatcher(build_indexes(catalog), catalog)

    candidates = matcher.resolve_slot(
        tokenize("Master of Business Administration"),
        "course",
    )

    assert [(item.entity_id, item.method, item.matched_catalog_term) for item in candidates] == [
        ("category:mba", "acronym", "mba")
    ]


@pytest.mark.parametrize(
    ("message", "normalized", "display"),
    [
        ("Harvard MBA", "harvard", "Harvard"),
        ("Oxford MBA", "oxford", "Oxford"),
        ("Stanford MBA", "stanford", "Stanford"),
        ("Tell me about harward uni", "harward", "Harward"),
        ("Harward", "harward", "Harward"),
        ("harward", "harward", "Harward"),
        ("IIT", "iit", "IIT"),
    ],
)
def test_unknown_catalog_entities_are_retained_conservatively(
    sample_matcher: EntityMatcher,
    message: str,
    normalized: str,
    display: str,
) -> None:
    mentions = extract_mentions(message, sample_matcher)

    assert mentions.unknown_entities == [normalized]
    assert mentions.unresolved_terms == [display]


@pytest.mark.parametrize(
    "message",
    [
        "Tell me about MBA",
        "What are the fees?",
        "NAAC approvals",
        "Tell me about online programs",
        "Browse Universities",
        "Can somebody guide me",
    ],
)
def test_unknown_detection_ignores_unframed_prose_starters_and_attributes(
    sample_matcher: EntityMatcher,
    message: str,
) -> None:
    assert extract_mentions(message, sample_matcher).unknown_entities == []


def test_catalog_attributes_are_extracted_without_becoming_unknowns(
    sample_matcher: EntityMatcher,
) -> None:
    mentions = extract_mentions(
        "What are the fees, duration, NAAC and UGC approvals and placements?",
        sample_matcher,
    )

    assert set(mentions.attributes) == {
        "fee",
        "duration",
        "naac",
        "ugc",
        "approval",
        "placement",
    }
    assert mentions.unknown_entities == []


def test_short_unknown_acronym_is_retained_without_fuzzy_false_positive(
    sample_matcher: EntityMatcher,
) -> None:
    mentions = extract_mentions("What is BBA?", sample_matcher)

    assert mentions.courses == []
    assert mentions.specializations == []
    assert mentions.unknown_entities == ["bba"]
    assert mentions.unresolved_terms == ["BBA"]


def test_single_online_token_does_not_fuzzy_match_multiword_course_aliases(
    sample_matcher: EntityMatcher,
) -> None:
    mentions = extract_mentions("online programs", sample_matcher)

    assert mentions.courses == []
    assert mentions.specializations == []
    assert mentions.unknown_entities == []


@pytest.mark.parametrize(
    "message",
    ["Tell me about affordable Online MBA", "Tell me about distance Online MBA"],
)
def test_resolved_multiword_span_suppresses_contained_acronym_fragment(
    sample_matcher: EntityMatcher,
    message: str,
) -> None:
    mentions = extract_mentions(message, sample_matcher)

    assert [item.entity_id for item in mentions.courses] == ["category:mba"]
    assert mentions.unknown_entities == []


def test_shorter_exact_catalog_phrase_beats_broad_fuzzy_span(
    sample_matcher: EntityMatcher,
) -> None:
    mentions = extract_mentions("Which Online MBA is best for Marketing?", sample_matcher)

    assert [item.entity_id for item in mentions.courses] == ["category:mba"]
    assert mentions.courses[0].matched_span == "online mba"
    assert mentions.courses[0].method == "alias"
    assert mentions.unknown_entities == []


def test_absent_lowercase_concept_stays_unknown_but_catalog_fixture_resolves_it(
    sample_matcher: EntityMatcher,
) -> None:
    absent = extract_mentions("betch", sample_matcher)
    assert absent.courses == []
    assert absent.unknown_entities == ["betch"]

    catalog = CatalogStore(
        records=[
            _university_record("delta", "Delta Knowledge Institute"),
            {
                "id": "delta-btech",
                "_meta": {"page_type": "course"},
                "program_name": "Online B.Tech",
                "university_name": "Delta Knowledge Institute",
                "duration": "4 Years",
            },
        ]
    )
    matcher = EntityMatcher(build_indexes(catalog), catalog)
    resolved = extract_mentions("betch", matcher)

    assert [(item.entity_id, item.confidence, item.method) for item in resolved.courses] == [
        ("category:btech", "MEDIUM", "rapidfuzz")
    ]
    assert resolved.unknown_entities == []


@pytest.mark.parametrize(
    "message",
    [
        "Manipal University Jaipur",
        "Tell me about Manipal University Jaipur",
        "Sikkim Manipal University",
        "Tell me about Sikkim Manipal University",
        "starting fee at Jain",
        "What is the starting fee at Jain University?",
        "Show all MBA programs",
        "you tell me which uni provide mba program",
        "completed graduation",
        "online MBA options",
        "I have completed graduation. Which online MBA options are available?",
        "Suggest affordable Online MBA",
        "Suggest an affordable Online MBA",
        "best Online MBA for Marketing",
        "Which Online MBA is best for Marketing?",
        "budget 1.8 lakh",
        "I have a budget of 1.8 lakh. Which MBA should I choose?",
    ],
)
def test_resolved_and_structural_phrases_are_not_unknown_entities(
    sample_matcher: EntityMatcher,
    message: str,
) -> None:
    assert extract_mentions(message, sample_matcher).unknown_entities == []


@pytest.mark.parametrize(
    "message",
    ["IIT Bombay Online MBA", "Tell me about IIT Bombay Online MBA"],
)
def test_contained_unknown_acronym_is_collapsed_into_longer_entity_span(
    sample_matcher: EntityMatcher,
    message: str,
) -> None:
    mentions = extract_mentions(message, sample_matcher)

    assert mentions.unknown_entities == ["iit bombay"]
    assert mentions.unresolved_terms == ["IIT Bombay"]
